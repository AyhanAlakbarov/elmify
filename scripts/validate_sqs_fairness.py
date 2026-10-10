import argparse
import json
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import boto3  # type: ignore[import-untyped]

from apps.research.schemas import ResearchMessage

FAIR_QUEUE_METRICS = (
    "ApproximateNumberOfNoisyGroups",
    "ApproximateNumberOfMessagesVisibleInQuietGroups",
    "ApproximateNumberOfMessagesNotVisibleInQuietGroups",
    "ApproximateNumberOfMessagesDelayedInQuietGroups",
    "ApproximateAgeOfOldestMessageInQuietGroups",
)
NOISY_MESSAGES = 120
QUIET_MESSAGES = 5
QUIET_TENANT_DELAY_SECONDS = 1
RECEIVE_POLLERS = 12
RECEIVE_DEADLINE_SECONDS = 180
QUIET_TENANT_THRESHOLD = NOISY_MESSAGES


def quiet_tenant_served_before(receipts: list[str], *, quiet: str, limit: int) -> bool:
    try:
        first_quiet = receipts.index(quiet)
    except ValueError:
        return False
    return first_quiet < limit


def metric_queries(queue_name: str) -> list[dict[str, object]]:
    return [
        {
            "Id": f"fair{index}",
            "Label": metric_name,
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/SQS",
                    "MetricName": metric_name,
                    "Dimensions": [{"Name": "QueueName", "Value": queue_name}],
                },
                "Period": 60,
                "Stat": "Maximum",
            },
            "ReturnData": True,
        }
        for index, metric_name in enumerate(FAIR_QUEUE_METRICS)
    ]


def poll_fair_queue_metrics(
    cloudwatch: object,
    *,
    queue_name: str,
    started_at: datetime,
    ended_at: datetime,
    timeout_seconds: int,
    poll_seconds: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, list[dict[str, object]]]:
    deadline = monotonic() + timeout_seconds
    metric_by_id = {f"fair{index}": metric for index, metric in enumerate(FAIR_QUEUE_METRICS)}
    while monotonic() < deadline:
        response = getattr(cloudwatch, "get_metric_data")(
            MetricDataQueries=metric_queries(queue_name),
            StartTime=started_at - timedelta(minutes=1),
            EndTime=ended_at + timedelta(minutes=1),
            ScanBy="TimestampAscending",
        )
        metrics: dict[str, list[dict[str, object]]] = {metric: [] for metric in FAIR_QUEUE_METRICS}
        for result in response.get("MetricDataResults", []):
            metric_name = metric_by_id.get(result.get("Id"))
            if metric_name is None:
                continue
            for timestamp, value in zip(
                result.get("Timestamps", []), result.get("Values", []), strict=True
            ):
                if value < 0:
                    raise ValueError("negative fair-queue metric")
                metrics[metric_name].append(
                    {
                        "timestamp": timestamp.astimezone(UTC).isoformat(),
                        "value": value,
                    }
                )
        if all(metrics.values()):
            return metrics
        sleep(min(poll_seconds, max(0, deadline - monotonic())))
    raise TimeoutError("fair-queue metrics unavailable before deadline")


def utc_now() -> datetime:
    return datetime.now(UTC)


def run_trial(
    queue_url: str,
    *,
    sqs: object | None = None,
    clock: Callable[[], datetime] = utc_now,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    sqs_client = boto3.client("sqs") if sqs is None else sqs
    noisy = uuid4()
    quiet = uuid4()
    started_at = clock()
    monotonic_started_at = monotonic()
    for tenant_id, count in ((noisy, NOISY_MESSAGES), (quiet, QUIET_MESSAGES)):
        if tenant_id == quiet:
            time.sleep(QUIET_TENANT_DELAY_SECONDS)
        for _ in range(count):
            message = ResearchMessage(kind="run_research", tenant_id=tenant_id, run_id=uuid4())
            getattr(sqs_client, "send_message")(
                QueueUrl=queue_url,
                MessageBody=message.model_dump_json(),
                MessageGroupId=str(tenant_id),
            )

    receipts: list[str] = []
    lock = threading.Lock()
    deadline = monotonic() + RECEIVE_DEADLINE_SECONDS

    def consume() -> None:
        while monotonic() < deadline:
            with lock:
                if len(receipts) >= NOISY_MESSAGES + QUIET_MESSAGES:
                    return
            response = getattr(sqs_client, "receive_message")(
                QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=10
            )
            for raw in response.get("Messages", []):
                message = ResearchMessage.model_validate_json(raw["Body"])
                with lock:
                    receipts.append(str(message.tenant_id))
                if message.tenant_id == noisy:
                    time.sleep(0.05)
                getattr(sqs_client, "delete_message")(
                    QueueUrl=queue_url, ReceiptHandle=raw["ReceiptHandle"]
                )

    with ThreadPoolExecutor(max_workers=RECEIVE_POLLERS) as executor:
        futures = [executor.submit(consume) for _ in range(RECEIVE_POLLERS)]
        for future in futures:
            future.result()
    ended_at = clock()
    monotonic_ended_at = monotonic()
    return {
        "started_at": started_at.astimezone(UTC).isoformat(),
        "ended_at": ended_at.astimezone(UTC).isoformat(),
        "duration_seconds": round(monotonic_ended_at - monotonic_started_at, 3),
        "passed": quiet_tenant_served_before(
            receipts, quiet=str(quiet), limit=QUIET_TENANT_THRESHOLD
        ),
        "received": len(receipts),
        "noisy_before_first_quiet": receipts.index(str(quiet)) if str(quiet) in receipts else None,
    }


def _source_revision() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
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
    queue_url: str,
    *,
    trials: int,
    metric_timeout_seconds: int,
    poll_seconds: int,
    sqs: object,
    cloudwatch: object,
    sts: object,
) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": 1,
        "source_revision": _source_revision(),
        "generated_at": utc_now().isoformat(),
        "region": getattr(getattr(sqs, "meta", None), "region_name", None),
        "sts": {},
        "queue": {},
        "trial_count": trials,
        "traffic": {
            "noisy_messages": NOISY_MESSAGES,
            "quiet_messages": QUIET_MESSAGES,
            "quiet_tenant_delay_seconds": QUIET_TENANT_DELAY_SECONDS,
            "receive_pollers": RECEIVE_POLLERS,
            "receive_deadline_seconds": RECEIVE_DEADLINE_SECONDS,
            "quiet_tenant_threshold": QUIET_TENANT_THRESHOLD,
        },
        "limits": {
            "metric_timeout_seconds": metric_timeout_seconds,
            "poll_seconds": poll_seconds,
        },
        "trials": [],
    }
    try:
        queue_arn = getattr(sqs, "get_queue_attributes")(
            QueueUrl=queue_url, AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
        queue_name = queue_arn.rsplit(":", 1)[-1]
        evidence["queue"] = {"name": queue_name}
        identity = getattr(sts, "get_caller_identity")()
        if not identity.get("Account") or not identity.get("Arn"):
            raise ValueError("STS returned incomplete caller identity")
        evidence["sts"] = {"authenticated": True}
        results = [run_trial(queue_url, sqs=sqs) for _ in range(trials)]
        evidence["trials"] = results
        for result in results:
            result["metrics"] = poll_fair_queue_metrics(
                cloudwatch,
                queue_name=queue_name,
                started_at=datetime.fromisoformat(str(result["started_at"])),
                ended_at=datetime.fromisoformat(str(result["ended_at"])),
                timeout_seconds=metric_timeout_seconds,
                poll_seconds=poll_seconds,
            )
        receipt_order_passed = all(bool(result["passed"]) for result in results)
        metrics_available = all(
            isinstance(metrics := result.get("metrics"), dict)
            and set(metrics) == set(FAIR_QUEUE_METRICS)
            for result in results
        )
        evidence["verdict"] = "passed" if receipt_order_passed and metrics_available else "failed"
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
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--metric-timeout-seconds", type=int, default=300)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--output", type=Path, default=Path("docs/validation/sqs-fair-queue.md"))
    args = parser.parse_args()
    if min(args.trials, args.metric_timeout_seconds, args.poll_seconds) <= 0:
        parser.error("trials, metric timeout, and polling interval must be positive")
    try:
        session = boto3.session.Session()
        result = run_validation(
            args.queue_url,
            trials=args.trials,
            metric_timeout_seconds=args.metric_timeout_seconds,
            poll_seconds=args.poll_seconds,
            sqs=session.client("sqs"),
            cloudwatch=session.client("cloudwatch"),
            sts=session.client("sts"),
        )
    except Exception as error:
        result = {
            "schema_version": 1,
            "source_revision": _source_revision(),
            "generated_at": utc_now().isoformat(),
            "queue": {},
            "trial_count": args.trials,
            "limits": {
                "metric_timeout_seconds": args.metric_timeout_seconds,
                "poll_seconds": args.poll_seconds,
            },
            "trials": [],
            "verdict": "failed",
            "error": {"type": type(error).__name__},
        }
    write_evidence(args.output, "SQS fair-queue validation", result)
    return 0 if result["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
