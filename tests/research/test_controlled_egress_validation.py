import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.research.egress import FetchResult, ResolvedTarget
from scripts import validate_controlled_egress as harness
from scripts.validate_controlled_egress import (
    REQUIRED_OUTPUTS,
    REQUIRED_RESOURCES,
    required_outputs_present,
    required_resources_present,
)


def _probe_payload(*, failed_name: str | None = None) -> dict[str, object]:
    categories = (
        ("public_https", "public_https"),
        ("blocked_loopback", "loopback"),
        ("blocked_private", "private"),
        ("blocked_link_local", "link_local"),
        ("blocked_metadata", "metadata"),
        ("s3_endpoint", "aws_service_endpoint"),
        ("sqs_endpoint", "aws_service_endpoint"),
        ("secrets_endpoint", "aws_service_endpoint"),
    )
    checks = [
        {
            "name": name,
            "passed": name != failed_name,
            "error_type": (
                None
                if name == failed_name and name.startswith("blocked_")
                else "OSError"
                if name.startswith("blocked_")
                else "RuntimeError"
                if name == failed_name
                else None
            ),
            "destination_category": category,
            "elapsed_seconds": 0.01,
        }
        for name, category in categories
    ]
    return {
        "public_url": "https://aws.amazon.com/",
        "public_destination_ips": ["54.239.28.85"],
        "checks": checks,
        "passed": failed_name is None,
    }


def _marked_probe_event() -> dict[str, object]:
    return {"message": harness.PROBE_MARKER + json.dumps(_probe_payload())}


def test_validation_requires_every_network_boundary_resource() -> None:
    assert required_resources_present(REQUIRED_RESOURCES)
    assert not required_resources_present(REQUIRED_RESOURCES - {"WorkerSecurityGroup"})


def test_source_revision_fingerprints_dirty_worktree(monkeypatch, tmp_path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "source.txt"
    source.write_text("clean\\n", encoding="utf-8")
    subprocess.run(["git", "add", "source.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.test",
            "commit",
            "-qm",
            "test",
        ],
        cwd=tmp_path,
        check=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    source.write_text("dirty\\n", encoding="utf-8")
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    monkeypatch.chdir(tmp_path)

    assert harness._source_revision() == f"{revision}+dirty:{sha256(diff.encode()).hexdigest()}"


def test_validation_requires_every_probe_output() -> None:
    assert required_outputs_present(REQUIRED_OUTPUTS)
    assert not required_outputs_present(REQUIRED_OUTPUTS - {"ProbeTaskDefinitionArn"})


def test_template_defines_one_off_private_fargate_probe() -> None:
    template = Path("infra/template.yaml").read_text(encoding="utf-8")
    for fragment in (
        "ProbeImage:",
        "ValidationCluster:",
        "ProbeTaskDefinition:",
        "NetworkMode: awsvpc",
        "- FARGATE",
        "MaxAggregationInterval: 60",
        "ProbeTaskDefinitionArn:",
        "WorkerPrivateSubnetAId:",
        "WorkerPrivateSubnetBId:",
        "WorkerSecurityGroupId:",
        "ProbeLogGroupName:",
        "FlowLogGroupName:",
        "EvidenceBucketName:",
        "ValidationSecretArn:",
    ):
        assert fragment in template
    # Task 17 adds persistent WebService/WorkerService AWS::ECS::Service
    # resources alongside this one-off probe; the probe-only boundary this
    # test used to assert no longer holds by design.


def test_controlled_egress_module_command_is_used_everywhere() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.validate_controlled_egress", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    template = Path("infra/template.yaml").read_text(encoding="utf-8")
    documentation = Path("docs/validation/controlled-egress.md").read_text(encoding="utf-8")
    assert "            - -m\n            - scripts.validate_controlled_egress" in template
    assert (
        "uv run python -m scripts.validate_controlled_egress" in documentation
        or '"verdict":' in documentation
    )


def test_validation_docs_do_not_publish_filesystem_script_entrypoints() -> None:
    paths = (
        Path("docs/validation/controlled-egress.md"),
        Path("docs/validation/sqs-fair-queue.md"),
        Path("docs/superpowers/plans/2026-08-10-aws-boundary-validation-harness.md"),
        Path("docs/superpowers/plans/2026-08-10-phase-1-funding-intelligence-concierge-mvp.md"),
    )
    for path in paths:
        if path.exists():
            content = path.read_text(encoding="utf-8")
            assert "python scripts/validate_controlled_egress.py" not in content
            assert "python scripts/validate_sqs_fairness.py" not in content


def test_probe_url_requires_plain_https_origin() -> None:
    assert harness.validate_https_probe_url("https://aws.amazon.com/") == "https://aws.amazon.com/"
    for value in (
        "http://aws.amazon.com/",
        "https://user:pass@example.com/",
        "file:///etc/passwd",
    ):
        with pytest.raises(ValueError):
            harness.validate_https_probe_url(value)


def test_task_probe_requires_public_blocked_and_endpoint_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        harness,
        "validate_public_url",
        lambda _url: ResolvedTarget("https", "aws.amazon.com", 443, ("54.239.28.85",)),
    )
    monkeypatch.setattr(
        harness,
        "fetch_data_file",
        lambda _url, **_kwargs: FetchResult(_url, (), "text/html", b"ok"),
    )
    connector = Mock(side_effect=OSError("blocked"))
    monkeypatch.setattr(harness.socket, "create_connection", connector)
    clients = {name: Mock() for name in ("s3", "sqs", "secretsmanager")}
    monkeypatch.setattr(harness.boto3, "client", lambda name: clients[name])

    result = harness.run_task_probe(
        "https://aws.amazon.com/",
        queue_url="https://sqs.eu-central-1.amazonaws.com/123/validation",
        bucket="validation-bucket",
        secret_arn="arn:aws:secretsmanager:eu-central-1:123:secret:validation",
    )

    assert result["passed"] is True
    assert result["public_destination_ips"] == ["54.239.28.85"]
    assert all(check["passed"] for check in result["checks"])
    assert all(check["elapsed_seconds"] >= 0 for check in result["checks"])
    assert {check["destination_category"] for check in result["checks"]} == {
        "aws_service_endpoint",
        "link_local",
        "loopback",
        "metadata",
        "private",
        "public_https",
    }
    assert (
        harness.parse_probe_events(
            [{"message": harness.PROBE_MARKER + json.dumps(result)}], exit_code=0
        )["passed"]
        is True
    )
    assert connector.call_count == 4
    clients["s3"].head_bucket.assert_called_once_with(Bucket="validation-bucket")
    clients["sqs"].get_queue_attributes.assert_called_once_with(
        QueueUrl="https://sqs.eu-central-1.amazonaws.com/123/validation",
        AttributeNames=["QueueArn"],
    )
    clients["secretsmanager"].describe_secret.assert_called_once_with(
        SecretId="arn:aws:secretsmanager:eu-central-1:123:secret:validation"
    )


def test_task_probe_records_an_unexpected_reachable_private_target(monkeypatch) -> None:
    monkeypatch.setattr(
        harness,
        "validate_public_url",
        lambda _url: ResolvedTarget("https", "aws.amazon.com", 443, ("54.239.28.85",)),
    )
    monkeypatch.setattr(
        harness,
        "fetch_data_file",
        lambda _url, **_kwargs: FetchResult(_url, (), "text/html", b"ok"),
    )
    monkeypatch.setattr(harness.socket, "create_connection", lambda *_args, **_kwargs: Mock())
    monkeypatch.setattr(harness.boto3, "client", lambda _name: Mock())

    result = harness.run_task_probe(
        "https://aws.amazon.com/",
        queue_url="queue-url",
        bucket="bucket",
        secret_arn="secret-arn",
    )

    assert result["passed"] is False
    assert any(
        check["name"] == "blocked_loopback" and not check["passed"] for check in result["checks"]
    )


def test_task_probe_rejects_https_redirect_to_http(monkeypatch) -> None:
    monkeypatch.setattr(
        harness,
        "validate_public_url",
        lambda _url: ResolvedTarget("https", "example.com", 443, ("93.184.216.34",)),
    )
    monkeypatch.setattr(
        harness,
        "fetch_data_file",
        lambda _url, **_kwargs: FetchResult(
            "http://example.com/final", ("http://example.com/final",), "text/html", b"ok"
        ),
    )
    monkeypatch.setattr(harness.socket, "create_connection", Mock(side_effect=OSError("blocked")))
    monkeypatch.setattr(harness.boto3, "client", lambda _name: Mock())

    result = harness.run_task_probe(
        "https://example.com/",
        queue_url="queue-url",
        bucket="bucket",
        secret_arn="secret-arn",
    )

    public_check = next(check for check in result["checks"] if check["name"] == "public_https")
    assert result["passed"] is False
    assert public_check["passed"] is False
    assert public_check["error_type"] == "ValueError"


def test_probe_result_requires_exactly_one_marked_event() -> None:
    events = [_marked_probe_event()]
    assert harness.parse_probe_events(events, exit_code=0)["passed"] is True
    with pytest.raises(ValueError):
        harness.parse_probe_events([], exit_code=0)
    with pytest.raises(ValueError):
        harness.parse_probe_events(events * 2, exit_code=0)


@pytest.mark.parametrize(
    "payload",
    [
        {**_probe_payload(), "checks": []},
        {
            **_probe_payload(),
            "checks": _probe_payload()["checks"] + [_probe_payload()["checks"][0]],
        },
        {**_probe_payload(), "checks": [{"name": "public_https", "passed": True}]},
        {
            **_probe_payload(),
            "passed": True,
            "checks": _probe_payload(failed_name="public_https")["checks"],
        },
        {**_probe_payload(), "public_destination_ips": ["not-an-ip"]},
        {**_probe_payload(), "public_destination_ips": ["10.0.0.1"]},
        {**_probe_payload(), "public_destination_ips": [{"address": "54.239.28.85"}]},
        {
            **_probe_payload(),
            "public_destination_ips": ["54.239.28.85", "54.239.28.85"],
        },
    ],
    ids=(
        "empty-checks",
        "duplicate-check",
        "malformed-check",
        "dishonest-passed",
        "malformed-address",
        "non-global-address",
        "non-string-address",
        "duplicate-address",
    ),
)
def test_probe_result_rejects_untrusted_payload(payload) -> None:
    with pytest.raises(ValueError):
        harness.parse_probe_events(
            [{"message": harness.PROBE_MARKER + json.dumps(payload)}], exit_code=0
        )


@pytest.mark.parametrize(
    ("payload", "exit_code"),
    [(_probe_payload(), 1), (_probe_payload(failed_name="public_https"), 0)],
)
def test_probe_result_must_agree_with_container_exit(payload, exit_code) -> None:
    with pytest.raises(ValueError):
        harness.parse_probe_events(
            [{"message": harness.PROBE_MARKER + json.dumps(payload)}], exit_code=exit_code
        )


def test_stack_outputs_fail_closed_when_an_output_is_missing() -> None:
    cloudformation = Mock()
    cloudformation.describe_stacks.return_value = {
        "Stacks": [{"Outputs": [{"OutputKey": "ProbeClusterArn", "OutputValue": "cluster"}]}]
    }
    with pytest.raises(ValueError, match="missing required outputs"):
        harness.stack_outputs("validation-stack", cloudformation)


def test_flow_log_match_requires_task_to_public_https_accept() -> None:
    record = "2 123 eni-1 10.50.10.8 54.239.28.85 49152 443 6 5 500 100 160 ACCEPT OK"
    assert harness.flow_log_matches(
        record,
        eni_id="eni-1",
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
        window_start_ms=120_000,
        window_end_ms=130_000,
    )
    assert not harness.flow_log_matches(
        record.replace(" ACCEPT ", " REJECT "),
        eni_id="eni-1",
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
        window_start_ms=120_000,
        window_end_ms=130_000,
    )
    assert not harness.flow_log_matches(
        record,
        eni_id="eni-2",
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
        window_start_ms=120_000,
        window_end_ms=130_000,
    )
    assert not harness.flow_log_matches(
        record,
        eni_id="eni-1",
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
        window_start_ms=200_000,
        window_end_ms=210_000,
    )


def test_flow_log_polling_exhausts_partial_pages_with_aggregation_allowance() -> None:
    record = "2 123 eni-1 10.50.10.8 54.239.28.85 49152 443 6 5 500 100 160 ACCEPT OK"
    logs = Mock()
    logs.filter_log_events.side_effect = [
        {"events": [], "nextToken": "page-2"},
        {"events": [{"message": record}]},
    ]

    result = harness.poll_flow_logs(
        logs,
        log_group="flow-logs",
        window_start_ms=120_000,
        window_end_ms=130_000,
        eni_id="eni-1",
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
        timeout_seconds=3,
        poll_seconds=2,
        monotonic=Mock(side_effect=[0.0, 0.0, 0.0]),
        sleep=Mock(),
    )

    assert result == [record]
    first_request = logs.filter_log_events.call_args_list[0].kwargs
    assert first_request["startTime"] == 60_000
    assert first_request["endTime"] == 190_000
    assert logs.filter_log_events.call_args_list[1].kwargs["nextToken"] == "page-2"


def test_flow_log_polling_stops_at_deadline() -> None:
    logs = Mock()
    logs.filter_log_events.return_value = {"events": []}
    monotonic = Mock(side_effect=[0.0, 0.0, 2.0, 2.0, 2.0, 4.0])
    sleep = Mock()
    with pytest.raises(TimeoutError, match="Flow Log evidence unavailable"):
        harness.poll_flow_logs(
            logs,
            log_group="flow-logs",
            window_start_ms=0,
            window_end_ms=1_000,
            eni_id="eni-1",
            source_ip="10.50.10.8",
            destination_ips={"54.239.28.85"},
            timeout_seconds=3,
            poll_seconds=2,
            monotonic=monotonic,
            sleep=sleep,
        )
    assert sleep.call_count == 2


def test_flow_log_polling_caps_sleep_to_remaining_deadline() -> None:
    logs = Mock()
    logs.filter_log_events.return_value = {"events": []}
    sleep = Mock()
    with pytest.raises(TimeoutError, match="Flow Log evidence unavailable"):
        harness.poll_flow_logs(
            logs,
            log_group="flow-logs",
            window_start_ms=0,
            window_end_ms=1_000,
            eni_id="eni-1",
            source_ip="10.50.10.8",
            destination_ips={"54.239.28.85"},
            timeout_seconds=3,
            poll_seconds=5,
            monotonic=Mock(side_effect=[0.0, 0.0, 0.0, 3.0]),
            sleep=sleep,
        )
    sleep.assert_called_once_with(3.0)


def test_fargate_launch_fails_closed_on_ecs_placement_failure() -> None:
    ecs = Mock()
    ecs.run_task.return_value = {
        "tasks": [],
        "failures": [{"arn": "task-definition", "reason": "RESOURCE:ENI"}],
    }
    with pytest.raises(RuntimeError, match="RESOURCE:ENI"):
        harness.run_fargate_probe(
            outputs=_probe_outputs(),
            public_url="https://aws.amazon.com/",
            ecs=ecs,
            logs=Mock(),
            task_timeout_seconds=180,
            flow_log_timeout_seconds=600,
            poll_seconds=5,
        )


def test_fargate_launch_disables_public_ip(monkeypatch) -> None:
    ecs = Mock()
    ecs.run_task.return_value = {
        "tasks": [{"taskArn": "arn:aws:ecs:r:1:task/c/t-1"}],
        "failures": [],
    }
    waiter = Mock()
    ecs.get_waiter.return_value = waiter
    ecs.describe_tasks.return_value = {
        "tasks": [
            {
                "taskArn": "arn:aws:ecs:r:1:task/c/t-1",
                "lastStatus": "STOPPED",
                "attachments": [
                    {
                        "type": "ElasticNetworkInterface",
                        "details": [
                            {"name": "networkInterfaceId", "value": "eni-1"},
                            {"name": "privateIPv4Address", "value": "10.50.10.8"},
                        ],
                    }
                ],
                "containers": [{"exitCode": 0}],
            }
        ]
    }
    probe_logs = Mock()
    probe_logs.get_log_events.side_effect = [
        {"events": [], "nextForwardToken": "page-2"},
        {"events": [_marked_probe_event()], "nextForwardToken": "page-2"},
    ]
    poll_flow_logs = Mock(return_value=["matched"])
    monkeypatch.setattr(harness, "poll_flow_logs", poll_flow_logs)

    result = harness.run_fargate_probe(
        outputs=_probe_outputs(),
        public_url="https://aws.amazon.com/",
        ecs=ecs,
        logs=probe_logs,
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
    )

    request = ecs.run_task.call_args.kwargs
    assert request["launchType"] == "FARGATE"
    assert request["overrides"]["containerOverrides"][0]["command"][:3] == [
        "python",
        "-m",
        "scripts.validate_controlled_egress",
    ]
    assert request["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
    assert request["networkConfiguration"]["awsvpcConfiguration"]["subnets"] == [
        "subnet-a",
        "subnet-b",
    ]
    assert result["passed"] is True
    assert result["flow_log_match_count"] == 1
    assert "eni_id" not in result
    assert "eni_private_ip" not in result
    assert "task_id" not in result
    assert "flow_log_records" not in result
    assert poll_flow_logs.call_args.kwargs["eni_id"] == "eni-1"
    assert probe_logs.get_log_events.call_count == 2
    waiter.wait.assert_called_once()


def test_probe_log_reader_waits_for_marker_after_stable_token(monkeypatch) -> None:
    marker = _marked_probe_event()
    logs = Mock()
    logs.get_log_events.side_effect = [
        {"events": [], "nextForwardToken": "token"},
        {"events": [], "nextForwardToken": "token"},
        {"events": [marker], "nextForwardToken": "next-token"},
    ]
    monkeypatch.setattr(harness.time, "sleep", lambda _seconds: None)

    events = harness._read_probe_events(
        logs,
        log_group="probe-logs",
        log_stream="probe-stream",
        start_time_ms=0,
        timeout_seconds=10,
        monotonic=Mock(side_effect=[0.0, 0.0, 1.0, 2.0, 3.0]),
    )

    assert events == [marker]
    assert logs.get_log_events.call_count == 3


def test_nonzero_task_exit_preserves_failed_probe_evidence(monkeypatch) -> None:
    ecs = Mock()
    ecs.run_task.return_value = {
        "tasks": [{"taskArn": "arn:aws:ecs:r:1:task/c/t-1"}],
        "failures": [],
    }
    ecs.get_waiter.return_value = Mock()
    ecs.describe_tasks.return_value = {
        "tasks": [
            {
                "lastStatus": "STOPPED",
                "attachments": [
                    {
                        "type": "ElasticNetworkInterface",
                        "details": [
                            {"name": "networkInterfaceId", "value": "eni-1"},
                            {"name": "privateIPv4Address", "value": "10.50.10.8"},
                        ],
                    }
                ],
                "containers": [{"exitCode": 1}],
            }
        ]
    }
    logs = Mock()
    failed_payload = _probe_payload(failed_name="public_https")
    logs.get_log_events.return_value = {
        "events": [{"message": harness.PROBE_MARKER + json.dumps(failed_payload)}]
    }
    poll_flow_logs = Mock()
    monkeypatch.setattr(harness, "poll_flow_logs", poll_flow_logs)

    result = harness.run_fargate_probe(
        outputs=_probe_outputs(),
        public_url="https://aws.amazon.com/",
        ecs=ecs,
        logs=logs,
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
    )

    assert result["passed"] is False
    assert result["exit_code"] == 1
    assert result["checks"] == failed_payload["checks"]
    assert result["flow_log_match_count"] == 0
    poll_flow_logs.assert_not_called()


def test_evidence_write_is_sorted_and_atomic(tmp_path) -> None:
    output = tmp_path / "controlled-egress.md"
    harness.write_evidence(output, "Controlled-egress validation", {"z": 1, "a": 2})
    assert output.read_text(encoding="utf-8") == (
        '# Controlled-egress validation\n\n```json\n{\n  "a": 2,\n  "z": 1\n}\n```\n'
    )
    assert not output.with_suffix(".md.tmp").exists()


def test_validation_records_substituted_stack_and_fargate_evidence(monkeypatch) -> None:
    outputs = _probe_outputs()
    cloudformation = Mock()
    cloudformation.describe_stacks.return_value = {
        "Stacks": [
            {
                "StackId": "stack-id",
                "Outputs": [
                    {"OutputKey": key, "OutputValue": value} for key, value in outputs.items()
                ],
            }
        ]
    }
    cloudformation.get_paginator.return_value.paginate.return_value = [
        {
            "StackResourceSummaries": [
                {"LogicalResourceId": resource, "ResourceStatus": "CREATE_COMPLETE"}
                for resource in harness.REQUIRED_RESOURCES
            ]
        }
    ]
    monkeypatch.setattr(harness, "_source_revision", lambda: "revision")
    monkeypatch.setattr(
        harness.boto3.session, "Session", lambda: SimpleNamespace(region_name="eu-central-1")
    )
    monkeypatch.setattr(
        harness,
        "run_fargate_probe",
        lambda **_kwargs: {"passed": True, "flow_log_match_count": 1},
    )

    result = harness.run_validation(
        "validation-stack",
        public_url="https://aws.amazon.com/",
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
        cloudformation=cloudformation,
        ecs=Mock(),
        logs=Mock(),
        sts=Mock(
            get_caller_identity=lambda: {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/private",
            }
        ),
    )

    assert result["verdict"] == "passed"
    assert result["stack"] == {"name": "validation-stack"}
    assert result["sts"] == {"authenticated": True}
    assert result["fargate"]["flow_log_match_count"] == 1
    assert "outputs" not in result
    rendered = json.dumps(result, sort_keys=True)
    for private_value in (
        "123456789012",
        "arn:aws:",
        "queue-url",
        "ValidationSecretArn",
        "task/c/",
    ):
        assert private_value not in rendered


def test_failed_controlled_validation_omits_private_stack_values(monkeypatch) -> None:
    outputs = _probe_outputs()
    cloudformation = Mock()
    cloudformation.describe_stacks.return_value = {
        "Stacks": [
            {
                "StackId": "arn:aws:cloudformation:eu-central-1:123456789012:stack/private",
                "Outputs": [
                    {"OutputKey": key, "OutputValue": value} for key, value in outputs.items()
                ],
            }
        ]
    }
    cloudformation.get_paginator.return_value.paginate.return_value = [
        {
            "StackResourceSummaries": [
                {"LogicalResourceId": resource, "ResourceStatus": "CREATE_COMPLETE"}
                for resource in harness.REQUIRED_RESOURCES
            ]
        }
    ]
    monkeypatch.setattr(
        harness.boto3.session, "Session", lambda: SimpleNamespace(region_name="eu-central-1")
    )
    monkeypatch.setattr(harness, "run_fargate_probe", Mock(side_effect=RuntimeError("failed")))

    result = harness.run_validation(
        "validation-stack",
        public_url="https://aws.amazon.com/",
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
        cloudformation=cloudformation,
        ecs=Mock(),
        logs=Mock(),
        sts=Mock(
            get_caller_identity=lambda: {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/private",
            }
        ),
    )

    rendered = json.dumps(result, sort_keys=True)
    assert result["verdict"] == "failed"
    assert "123456789012" not in rendered
    assert "arn:aws:" not in rendered
    assert "outputs" not in result


def test_validation_records_timeout_as_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(harness, "_source_revision", lambda: "revision")
    monkeypatch.setattr(
        harness.boto3.session, "Session", lambda: SimpleNamespace(region_name="eu-central-1")
    )
    cloudformation = Mock()
    cloudformation.describe_stacks.side_effect = TimeoutError("unavailable")

    result = harness.run_validation(
        "validation-stack",
        public_url="https://aws.amazon.com/",
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
        cloudformation=cloudformation,
        ecs=Mock(),
        logs=Mock(),
        sts=Mock(),
    )

    assert result["verdict"] == "evidence_unavailable"
    assert result["error"] == {"type": "TimeoutError"}


def test_main_writes_substituted_controlled_egress_evidence(monkeypatch, tmp_path) -> None:
    output = tmp_path / "controlled-egress.md"
    session = Mock()
    monkeypatch.setattr(
        sys, "argv", ["validate", "--stack-name", "validation-stack", "--output", str(output)]
    )
    monkeypatch.setattr(harness.boto3.session, "Session", lambda: session)
    monkeypatch.setattr(harness, "run_validation", lambda *_args, **_kwargs: {"verdict": "passed"})

    assert harness.main() == 0
    assert '"verdict": "passed"' in output.read_text(encoding="utf-8")


def test_task_probe_main_emits_substituted_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate",
            "--task-probe",
            "--queue-url",
            "queue-url",
            "--bucket",
            "bucket",
            "--secret-arn",
            "secret-arn",
        ],
    )
    monkeypatch.setattr(harness, "run_task_probe", lambda *_args, **_kwargs: {"passed": True})

    assert harness.main() == 0
    assert capsys.readouterr().out == 'AWS_BOUNDARY_PROBE={"passed": true}\n'


def _probe_outputs() -> dict[str, str]:
    return {
        "ProbeClusterArn": "cluster",
        "ProbeTaskDefinitionArn": "task-definition",
        "WorkerPrivateSubnetAId": "subnet-a",
        "WorkerPrivateSubnetBId": "subnet-b",
        "WorkerSecurityGroupId": "sg-1",
        "ProbeLogGroupName": "probe-logs",
        "FlowLogGroupName": "flow-logs",
        "ResearchQueueUrl": "queue-url",
        "EvidenceBucketName": "bucket",
        "ValidationSecretArn": "secret",
    }
