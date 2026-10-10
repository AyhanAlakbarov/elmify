import argparse
import json
import math
import socket
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import boto3

from apps.research.egress import fetch_data_file, validate_public_url

PROBE_MARKER = "AWS_BOUNDARY_PROBE="
BLOCKED_TARGETS = (
    ("blocked_loopback", "127.0.0.1", 80),
    ("blocked_private", "10.255.255.1", 443),
    ("blocked_link_local", "169.254.1.1", 80),
    ("blocked_metadata", "169.254.169.254", 80),
)
CHECK_DESTINATION_CATEGORIES = {
    "public_https": "public_https",
    "blocked_loopback": "loopback",
    "blocked_private": "private",
    "blocked_link_local": "link_local",
    "blocked_metadata": "metadata",
    "s3_endpoint": "aws_service_endpoint",
    "sqs_endpoint": "aws_service_endpoint",
    "secrets_endpoint": "aws_service_endpoint",
}

REQUIRED_RESOURCES = {
    "WorkerPrivateSubnetA",
    "WorkerPrivateSubnetB",
    "NATGateway",
    "VpcFlowLog",
    "WorkerSecurityGroup",
    "S3Endpoint",
    "SqsEndpoint",
    "EcrApiEndpoint",
    "EcrDockerEndpoint",
    "LogsEndpoint",
    "SecretsEndpoint",
    "ValidationCluster",
    "ProbeLogGroup",
    "ProbeExecutionRole",
    "ProbeTaskRole",
    "EvidenceBucket",
    "ValidationSecret",
    "ProbeTaskDefinition",
}

REQUIRED_OUTPUTS = {
    "ProbeClusterArn",
    "ProbeTaskDefinitionArn",
    "WorkerPrivateSubnetAId",
    "WorkerPrivateSubnetBId",
    "WorkerSecurityGroupId",
    "ProbeLogGroupName",
    "FlowLogGroupName",
    "ResearchQueueUrl",
    "EvidenceBucketName",
    "ValidationSecretArn",
}


def required_resources_present(logical_ids: set[str]) -> bool:
    return REQUIRED_RESOURCES <= logical_ids


def required_outputs_present(output_keys: set[str]) -> bool:
    return REQUIRED_OUTPUTS <= output_keys


def validate_https_probe_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("public probe URL must be an HTTPS origin without credentials")
    return url


def stack_outputs(stack_name: str, cloudformation: object) -> dict[str, str]:
    response = cloudformation.describe_stacks(StackName=stack_name)
    outputs = {
        item["OutputKey"]: item["OutputValue"] for item in response["Stacks"][0].get("Outputs", [])
    }
    if not required_outputs_present(set(outputs)):
        missing = sorted(REQUIRED_OUTPUTS - set(outputs))
        raise ValueError(f"stack is missing required outputs: {', '.join(missing)}")
    return outputs


def parse_probe_events(events: list[dict[str, object]], *, exit_code: int) -> dict[str, object]:
    marked = [
        str(event["message"])[len(PROBE_MARKER) :]
        for event in events
        if str(event.get("message", "")).startswith(PROBE_MARKER)
    ]
    if len(marked) != 1:
        raise ValueError(f"expected one probe result, found {len(marked)}")
    result = json.loads(marked[0])
    if not isinstance(result, dict) or set(result) != {
        "public_url",
        "public_destination_ips",
        "checks",
        "passed",
    }:
        raise ValueError("probe result has invalid schema")
    public_url = result.get("public_url")
    if not isinstance(public_url, str):
        raise ValueError("probe result has invalid public URL")
    validate_https_probe_url(public_url)
    addresses = result.get("public_destination_ips")
    checks = result.get("checks")
    if not isinstance(addresses, list) or not addresses or not isinstance(checks, list):
        raise ValueError("probe result is missing addresses or checks")
    if any(not isinstance(address, str) for address in addresses):
        raise ValueError("probe result has invalid public address")
    if len(addresses) != len(set(addresses)):
        raise ValueError("probe result has duplicate addresses")
    try:
        if any(
            str(ip_address(address)) != address or not ip_address(address).is_global
            for address in addresses
        ):
            raise ValueError("probe result has invalid public address")
    except ValueError as error:
        raise ValueError("probe result has invalid public address") from error
    names: list[str] = []
    for check in checks:
        if not isinstance(check, dict) or set(check) != {
            "name",
            "passed",
            "error_type",
            "destination_category",
            "elapsed_seconds",
        }:
            raise ValueError("probe result has malformed check")
        name = check["name"]
        passed = check["passed"]
        error_type = check["error_type"]
        elapsed = check["elapsed_seconds"]
        if (
            not isinstance(name, str)
            or CHECK_DESTINATION_CATEGORIES.get(name) != check["destination_category"]
            or not isinstance(passed, bool)
        ):
            raise ValueError("probe result has malformed check")
        error_expected = passed == name.startswith("blocked_")
        if (
            (
                error_expected
                and (
                    not isinstance(error_type, str)
                    or not error_type.isidentifier()
                    or len(error_type) > 100
                )
            )
            or (not error_expected and error_type is not None)
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise ValueError("probe result has malformed check")
        names.append(name)
    if len(names) != len(set(names)) or set(names) != set(CHECK_DESTINATION_CATEGORIES):
        raise ValueError("probe result has invalid check set")
    passed = all(bool(check["passed"]) for check in checks)
    if (
        not isinstance(result.get("passed"), bool)
        or result["passed"] is not passed
        or result["passed"] is not (exit_code == 0)
    ):
        raise ValueError("probe result disagrees with checks or exit status")
    return result


def flow_log_matches(
    message: str,
    *,
    eni_id: str,
    source_ip: str,
    destination_ips: set[str],
    window_start_ms: int,
    window_end_ms: int,
) -> bool:
    fields = message.split()
    if len(fields) < 14:
        return False
    try:
        record_start_ms = int(fields[10]) * 1000
        record_end_ms = int(fields[11]) * 1000
    except ValueError:
        return False
    return (
        fields[2] == eni_id
        and fields[3] == source_ip
        and fields[4] in destination_ips
        and fields[6] == "443"
        and fields[7] == "6"
        and record_start_ms <= window_end_ms
        and record_end_ms >= window_start_ms
        and fields[12] == "ACCEPT"
        and fields[13] == "OK"
    )


def poll_flow_logs(
    logs: object,
    *,
    log_group: str,
    window_start_ms: int,
    window_end_ms: int,
    eni_id: str,
    source_ip: str,
    destination_ips: set[str],
    timeout_seconds: int,
    poll_seconds: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        next_token: str | None = None
        while True:
            request: dict[str, object] = {
                "logGroupName": log_group,
                "startTime": max(0, window_start_ms - 60_000),
                "endTime": window_end_ms + 60_000,
                "filterPattern": f'"{eni_id}" "{source_ip}" "443" "ACCEPT"',
            }
            if next_token is not None:
                request["nextToken"] = next_token
            response = logs.filter_log_events(**request)
            matches = [
                str(event["message"])
                for event in response.get("events", [])
                if flow_log_matches(
                    str(event.get("message", "")),
                    eni_id=eni_id,
                    source_ip=source_ip,
                    destination_ips=destination_ips,
                    window_start_ms=window_start_ms,
                    window_end_ms=window_end_ms,
                )
            ]
            if matches:
                return matches
            new_token = response.get("nextToken")
            if not isinstance(new_token, str) or new_token == next_token or monotonic() >= deadline:
                break
            next_token = new_token
        sleep(min(poll_seconds, max(0, deadline - monotonic())))
    raise TimeoutError("Flow Log evidence unavailable before deadline")


def _check(
    name: str,
    destination_category: str,
    operation: Callable[[], object],
    *,
    expect_failure: bool = False,
) -> dict[str, object]:
    started_at = time.monotonic()
    try:
        operation()
    except Exception as error:
        return {
            "name": name,
            "passed": expect_failure,
            "error_type": type(error).__name__,
            "destination_category": destination_category,
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
        }
    return {
        "name": name,
        "passed": not expect_failure,
        "error_type": None,
        "destination_category": destination_category,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }


def _fetch_https(public_url: str) -> object:
    result = fetch_data_file(public_url, require_https=True)
    for url in (*result.redirects, result.final_url):
        validate_https_probe_url(url)
    return result


def run_task_probe(
    public_url: str,
    *,
    queue_url: str,
    bucket: str,
    secret_arn: str,
) -> dict[str, object]:
    public_url = validate_https_probe_url(public_url)
    target = validate_public_url(public_url)
    s3 = boto3.client("s3")
    sqs = boto3.client("sqs")
    secrets = boto3.client("secretsmanager")
    checks = [
        _check("public_https", "public_https", lambda: _fetch_https(public_url)),
        *(
            _check(
                name,
                CHECK_DESTINATION_CATEGORIES[name],
                lambda host=host, port=port: socket.create_connection(
                    (host, port), timeout=2
                ).close(),
                expect_failure=True,
            )
            for name, host, port in BLOCKED_TARGETS
        ),
        _check(
            "s3_endpoint",
            "aws_service_endpoint",
            lambda: s3.head_bucket(Bucket=bucket),
        ),
        _check(
            "sqs_endpoint",
            "aws_service_endpoint",
            lambda: sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"]),
        ),
        _check(
            "secrets_endpoint",
            "aws_service_endpoint",
            lambda: secrets.describe_secret(SecretId=secret_arn),
        ),
    ]
    return {
        "public_url": public_url,
        "public_destination_ips": list(target.addresses),
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks),
    }


def stack_resources(stack_name: str, cloudformation: object) -> bool:
    resources: set[str] = set()
    paginator = cloudformation.get_paginator("list_stack_resources")
    for page in paginator.paginate(StackName=stack_name):
        resources.update(
            summary["LogicalResourceId"]
            for summary in page["StackResourceSummaries"]
            if summary["ResourceStatus"] != "DELETE_COMPLETE"
        )
    return required_resources_present(resources)


def validate_stack(stack_name: str) -> bool:
    return stack_resources(stack_name, boto3.client("cloudformation"))


def _task_network_interface(task: dict[str, object]) -> tuple[str, str]:
    for attachment in task.get("attachments", []):
        if attachment.get("type") != "ElasticNetworkInterface":
            continue
        details = {
            detail.get("name"): detail.get("value") for detail in attachment.get("details", [])
        }
        if details.get("networkInterfaceId") and details.get("privateIPv4Address"):
            return str(details["networkInterfaceId"]), str(details["privateIPv4Address"])
    raise ValueError("stopped task has no complete network interface identity")


def _read_probe_events(
    logs: object,
    *,
    log_group: str,
    log_stream: str,
    start_time_ms: int,
    timeout_seconds: int,
    poll_seconds: int = 5,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[dict[str, object]]:
    deadline = monotonic() + timeout_seconds
    events: list[dict[str, object]] = []
    next_token: str | None = None
    while monotonic() < deadline:
        request: dict[str, object] = {
            "logGroupName": log_group,
            "logStreamName": log_stream,
            "startFromHead": True,
        }
        if next_token is None:
            request["startTime"] = start_time_ms
        else:
            request["nextToken"] = next_token
        response = logs.get_log_events(**request)
        events.extend(response.get("events", []))
        if any(str(event.get("message", "")).startswith(PROBE_MARKER) for event in events):
            return events
        new_token = response.get("nextForwardToken")
        if isinstance(new_token, str) and new_token != next_token:
            next_token = new_token
            continue
        next_token = None
        time.sleep(min(poll_seconds, max(0, deadline - monotonic())))
    raise TimeoutError("probe logs unavailable before deadline")


def run_fargate_probe(
    *,
    outputs: dict[str, str],
    public_url: str,
    ecs: object,
    logs: object,
    task_timeout_seconds: int,
    flow_log_timeout_seconds: int,
    poll_seconds: int,
) -> dict[str, object]:
    started_at = datetime.now(UTC)
    start_time_ms = int(started_at.timestamp() * 1000)
    command = [
        "python",
        "-m",
        "scripts.validate_controlled_egress",
        "--task-probe",
        "--public-url",
        public_url,
        "--queue-url",
        outputs["ResearchQueueUrl"],
        "--bucket",
        outputs["EvidenceBucketName"],
        "--secret-arn",
        outputs["ValidationSecretArn"],
    ]
    response = ecs.run_task(
        cluster=outputs["ProbeClusterArn"],
        taskDefinition=outputs["ProbeTaskDefinitionArn"],
        count=1,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [outputs["WorkerPrivateSubnetAId"], outputs["WorkerPrivateSubnetBId"]],
                "securityGroups": [outputs["WorkerSecurityGroupId"]],
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={"containerOverrides": [{"name": "boundary-probe", "command": command}]},
    )
    failures = response.get("failures", [])
    tasks = response.get("tasks", [])
    if failures:
        reasons = ", ".join(str(failure.get("reason", "unknown")) for failure in failures)
        raise RuntimeError(f"ECS task placement failed: {reasons}")
    if len(tasks) != 1 or not tasks[0].get("taskArn"):
        raise RuntimeError("ECS RunTask did not return exactly one task")
    task_arn = str(tasks[0]["taskArn"])

    waiter = ecs.get_waiter("tasks_stopped")
    waiter.wait(
        cluster=outputs["ProbeClusterArn"],
        tasks=[task_arn],
        WaiterConfig={
            "Delay": poll_seconds,
            "MaxAttempts": max(1, task_timeout_seconds // poll_seconds),
        },
    )
    described = ecs.describe_tasks(cluster=outputs["ProbeClusterArn"], tasks=[task_arn])
    stopped_tasks = described.get("tasks", [])
    if len(stopped_tasks) != 1 or stopped_tasks[0].get("lastStatus") != "STOPPED":
        raise RuntimeError("ECS task did not stop")
    task = stopped_tasks[0]
    containers = task.get("containers", [])
    if len(containers) != 1:
        raise RuntimeError("boundary probe task has invalid container status")
    exit_code = containers[0].get("exitCode")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        raise RuntimeError("boundary probe task has invalid exit status")
    eni_id, private_ip = _task_network_interface(task)
    ended_at = datetime.now(UTC)
    end_time_ms = int(ended_at.timestamp() * 1000)
    task_id = task_arn.rsplit("/", 1)[-1]
    probe_events = _read_probe_events(
        logs,
        log_group=outputs["ProbeLogGroupName"],
        log_stream=f"boundary-probe/boundary-probe/{task_id}",
        start_time_ms=start_time_ms,
        timeout_seconds=task_timeout_seconds,
        poll_seconds=poll_seconds,
    )
    probe_result = parse_probe_events(probe_events, exit_code=exit_code)
    if probe_result["public_url"] != public_url:
        raise ValueError("probe result public URL does not match requested URL")
    destination_ips = {str(address) for address in probe_result["public_destination_ips"]}
    result: dict[str, object] = {
        "exit_code": exit_code,
        "checks": probe_result["checks"],
        "public_destination_ip_count": len(destination_ips),
        "flow_log_match_count": 0,
        "observation_window": {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
        },
        "limits": {
            "task_timeout_seconds": task_timeout_seconds,
            "flow_log_timeout_seconds": flow_log_timeout_seconds,
            "poll_seconds": poll_seconds,
        },
        "passed": bool(probe_result["passed"]),
    }
    if not result["passed"]:
        return result
    flow_log_records = poll_flow_logs(
        logs,
        log_group=outputs["FlowLogGroupName"],
        window_start_ms=start_time_ms,
        window_end_ms=end_time_ms,
        eni_id=eni_id,
        source_ip=private_ip,
        destination_ips=destination_ips,
        timeout_seconds=flow_log_timeout_seconds,
        poll_seconds=poll_seconds,
    )
    result["flow_log_match_count"] = len(flow_log_records)
    return result


def _source_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return revision if not diff else f"{revision}+dirty:{sha256(diff.encode()).hexdigest()}"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_validation(
    stack_name: str,
    *,
    public_url: str,
    task_timeout_seconds: int,
    flow_log_timeout_seconds: int,
    poll_seconds: int,
    cloudformation: object,
    ecs: object,
    logs: object,
    sts: object,
) -> dict[str, object]:
    validate_https_probe_url(public_url)
    generated_at = datetime.now(UTC).isoformat()
    evidence: dict[str, object] = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source_revision": _source_revision(),
        "region": boto3.session.Session().region_name,
        "stack": {"name": stack_name},
        "limits": {
            "task_timeout_seconds": task_timeout_seconds,
            "flow_log_timeout_seconds": flow_log_timeout_seconds,
            "poll_seconds": poll_seconds,
        },
    }
    try:
        cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
        evidence["stack"] = {"name": stack_name}
        if not stack_resources(stack_name, cloudformation):
            raise ValueError("stack is missing required resources")
        outputs = stack_outputs(stack_name, cloudformation)
        identity = sts.get_caller_identity()
        if not identity.get("Account") or not identity.get("Arn"):
            raise ValueError("STS returned incomplete caller identity")
        evidence["sts"] = {"authenticated": True}
        fargate = run_fargate_probe(
            outputs=outputs,
            public_url=public_url,
            ecs=ecs,
            logs=logs,
            task_timeout_seconds=task_timeout_seconds,
            flow_log_timeout_seconds=flow_log_timeout_seconds,
            poll_seconds=poll_seconds,
        )
        evidence["fargate"] = fargate
        evidence["verdict"] = "passed" if fargate["passed"] else "failed"
    except TimeoutError as error:
        evidence["verdict"] = "evidence_unavailable"
        evidence["error"] = {"type": type(error).__name__}
    except Exception as error:
        evidence["verdict"] = "failed"
        evidence["error"] = {"type": type(error).__name__}
    return evidence


def write_evidence(path: Path, title: str, payload: dict[str, object]) -> None:
    rendered = f"# {title}\n\n```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-name")
    parser.add_argument("--task-probe", action="store_true")
    parser.add_argument("--public-url", default="https://aws.amazon.com/")
    parser.add_argument("--queue-url")
    parser.add_argument("--bucket")
    parser.add_argument("--secret-arn")
    parser.add_argument("--task-timeout-seconds", type=int, default=180)
    parser.add_argument("--flow-log-timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("docs/validation/controlled-egress.md"))
    args = parser.parse_args()
    if args.task_probe:
        if not all((args.queue_url, args.bucket, args.secret_arn)):
            parser.error("--task-probe requires --queue-url, --bucket, and --secret-arn")
        result = run_task_probe(
            args.public_url,
            queue_url=args.queue_url,
            bucket=args.bucket,
            secret_arn=args.secret_arn,
        )
        print(PROBE_MARKER + json.dumps(result, sort_keys=True))
        return 0 if result["passed"] else 1
    if not args.stack_name:
        parser.error("--stack-name is required unless --task-probe is set")
    try:
        validate_https_probe_url(args.public_url)
        if min(args.task_timeout_seconds, args.flow_log_timeout_seconds, args.poll_seconds) <= 0:
            raise ValueError("timeouts and polling interval must be positive")
    except ValueError as error:
        parser.error(str(error))
    try:
        session = boto3.session.Session()
        result = run_validation(
            args.stack_name,
            public_url=args.public_url,
            task_timeout_seconds=args.task_timeout_seconds,
            flow_log_timeout_seconds=args.flow_log_timeout_seconds,
            poll_seconds=args.poll_seconds,
            cloudformation=session.client("cloudformation"),
            ecs=session.client("ecs"),
            logs=session.client("logs"),
            sts=session.client("sts"),
        )
    except Exception as error:
        result = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_revision": _source_revision(),
            "stack": {"name": args.stack_name},
            "limits": {
                "task_timeout_seconds": args.task_timeout_seconds,
                "flow_log_timeout_seconds": args.flow_log_timeout_seconds,
                "poll_seconds": args.poll_seconds,
            },
            "verdict": "failed",
            "error": {"type": type(error).__name__},
        }
    write_evidence(args.output, "Controlled-egress validation", result)
    return 0 if result["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
