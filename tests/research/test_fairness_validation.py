import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import validate_sqs_fairness as harness


def test_quiet_tenant_must_arrive_before_noisy_threshold() -> None:
    assert harness.quiet_tenant_served_before(["A"] * 119 + ["B"], quiet="B", limit=120)
    assert not harness.quiet_tenant_served_before(["A"] * 120 + ["B"], quiet="B", limit=120)
    assert not harness.quiet_tenant_served_before(["A"] * 119, quiet="B", limit=120)


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


def test_sqs_fairness_module_command_is_documented() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.validate_sqs_fairness", "--help"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    documentation = Path("docs/validation/sqs-fair-queue.md").read_text(encoding="utf-8")
    assert (
        "uv run python -m scripts.validate_sqs_fairness" in documentation
        or '"verdict":' in documentation
    )


def test_metric_queries_cover_every_documented_fair_queue_metric() -> None:
    queries = harness.metric_queries("validation-queue")
    assert {query["MetricStat"]["Metric"]["MetricName"] for query in queries} == set(
        harness.FAIR_QUEUE_METRICS
    )
    assert all(
        query["MetricStat"]["Metric"]["Dimensions"]
        == [{"Name": "QueueName", "Value": "validation-queue"}]
        for query in queries
    )


def test_metric_polling_returns_non_negative_timestamped_values() -> None:
    started = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    cloudwatch = Mock()
    cloudwatch.get_metric_data.return_value = {
        "MetricDataResults": [
            {"Id": f"fair{index}", "Timestamps": [started], "Values": [float(index)]}
            for index, _name in enumerate(harness.FAIR_QUEUE_METRICS)
        ]
    }
    result = harness.poll_fair_queue_metrics(
        cloudwatch,
        queue_name="validation-queue",
        started_at=started,
        ended_at=started + timedelta(seconds=30),
        timeout_seconds=60,
        poll_seconds=5,
        monotonic=Mock(side_effect=[0.0, 0.0]),
        sleep=Mock(),
    )
    assert set(result) == set(harness.FAIR_QUEUE_METRICS)
    assert all(points[0]["value"] >= 0 for points in result.values())


def test_metric_polling_times_out_when_one_metric_is_absent() -> None:
    started = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    cloudwatch = Mock()
    cloudwatch.get_metric_data.return_value = {"MetricDataResults": []}
    with pytest.raises(TimeoutError, match="fair-queue metrics unavailable"):
        harness.poll_fair_queue_metrics(
            cloudwatch,
            queue_name="validation-queue",
            started_at=started,
            ended_at=started + timedelta(seconds=30),
            timeout_seconds=3,
            poll_seconds=2,
            monotonic=Mock(side_effect=[0.0, 0.0, 2.0, 4.0]),
            sleep=Mock(),
        )


def test_metric_polling_rejects_negative_values() -> None:
    started = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    cloudwatch = Mock()
    cloudwatch.get_metric_data.return_value = {
        "MetricDataResults": [{"Id": "fair0", "Timestamps": [started], "Values": [-1.0]}]
    }
    with pytest.raises(ValueError, match="negative fair-queue metric"):
        harness.poll_fair_queue_metrics(
            cloudwatch,
            queue_name="validation-queue",
            started_at=started,
            ended_at=started + timedelta(seconds=30),
            timeout_seconds=60,
            poll_seconds=5,
            monotonic=Mock(side_effect=[0.0, 0.0]),
            sleep=Mock(),
        )


def test_run_trial_propagates_consumer_failure(monkeypatch) -> None:
    monkeypatch.setattr(harness, "NOISY_MESSAGES", 0)
    monkeypatch.setattr(harness, "QUIET_MESSAGES", 1)
    monkeypatch.setattr(harness, "QUIET_TENANT_DELAY_SECONDS", 0)
    monkeypatch.setattr(harness, "RECEIVE_POLLERS", 1)
    sqs = Mock()
    sqs.receive_message.side_effect = RuntimeError("consumer failed")

    with pytest.raises(RuntimeError):
        harness.run_trial("queue-url", sqs=sqs)


def test_run_trial_records_monotonic_boundaries(monkeypatch) -> None:
    monkeypatch.setattr(harness, "NOISY_MESSAGES", 0)
    monkeypatch.setattr(harness, "QUIET_MESSAGES", 0)
    monkeypatch.setattr(harness, "QUIET_TENANT_DELAY_SECONDS", 0)
    monkeypatch.setattr(harness, "RECEIVE_POLLERS", 1)
    started = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    ended = started + timedelta(seconds=2.5)

    result = harness.run_trial(
        "queue-url",
        sqs=Mock(),
        clock=Mock(side_effect=[started, ended]),
        monotonic=Mock(side_effect=[10.0, 10.0, 10.0, 12.5]),
    )

    assert result["duration_seconds"] == 2.5


def test_run_trial_starts_receive_deadline_after_sending(monkeypatch) -> None:
    monkeypatch.setattr(harness, "NOISY_MESSAGES", 0)
    monkeypatch.setattr(harness, "QUIET_MESSAGES", 1)
    monkeypatch.setattr(harness, "QUIET_TENANT_DELAY_SECONDS", 0)
    monkeypatch.setattr(harness, "RECEIVE_POLLERS", 1)
    sqs = Mock()

    def receive_message(**_kwargs):
        return {
            "Messages": [
                {
                    "Body": sqs.send_message.call_args.kwargs["MessageBody"],
                    "ReceiptHandle": "receipt-1",
                }
            ]
        }

    sqs.receive_message.side_effect = receive_message

    result = harness.run_trial(
        "queue-url",
        sqs=sqs,
        monotonic=Mock(side_effect=[0.0, 200.0, 200.0, 200.0, 201.0]),
    )

    assert result["passed"] is True
    assert result["received"] == 1


def test_validation_records_substituted_trials_and_metrics(monkeypatch) -> None:
    started = "2026-08-10T12:00:00+00:00"
    metrics = {
        metric: [{"timestamp": started, "value": 0}] for metric in harness.FAIR_QUEUE_METRICS
    }
    sqs = Mock()
    sqs.meta.region_name = "eu-central-1"
    sqs.get_queue_attributes.return_value = {
        "Attributes": {"QueueArn": "arn:aws:sqs:eu-central-1:123:validation-queue"}
    }
    monkeypatch.setattr(harness, "_source_revision", lambda: "revision")
    monkeypatch.setattr(harness, "utc_now", lambda: datetime.fromisoformat(started))
    monkeypatch.setattr(
        harness,
        "run_trial",
        lambda *_args, **_kwargs: {
            "started_at": started,
            "ended_at": started,
            "passed": True,
            "received": 125,
            "noisy_before_first_quiet": 1,
        },
    )
    monkeypatch.setattr(harness, "poll_fair_queue_metrics", lambda *_args, **_kwargs: metrics)

    result = harness.run_validation(
        "queue-url",
        trials=2,
        metric_timeout_seconds=60,
        poll_seconds=5,
        sqs=sqs,
        cloudwatch=Mock(),
        sts=Mock(
            get_caller_identity=lambda: {
                "Account": "123456789012",
                "Arn": "arn:aws:iam::123456789012:user/private",
            }
        ),
    )

    assert result["verdict"] == "passed"
    assert result["queue"] == {"name": "validation-queue"}
    assert result["sts"] == {"authenticated": True}
    rendered = json.dumps(result, sort_keys=True)
    assert "123456789012" not in rendered
    assert "arn:aws:" not in rendered
    assert "queue-url" not in rendered
    assert all(trial["metrics"] == metrics for trial in result["trials"])


def test_validation_records_metric_timeout_as_unavailable(monkeypatch) -> None:
    sqs = Mock()
    sqs.meta.region_name = "eu-central-1"
    sqs.get_queue_attributes.return_value = {
        "Attributes": {"QueueArn": "arn:aws:sqs:eu-central-1:123:validation-queue"}
    }
    monkeypatch.setattr(
        harness,
        "run_trial",
        lambda *_args, **_kwargs: {
            "started_at": "2026-08-10T12:00:00+00:00",
            "ended_at": "2026-08-10T12:00:00+00:00",
            "passed": True,
        },
    )
    monkeypatch.setattr(
        harness,
        "poll_fair_queue_metrics",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()),
    )

    result = harness.run_validation(
        "queue-url",
        trials=1,
        metric_timeout_seconds=60,
        poll_seconds=5,
        sqs=sqs,
        cloudwatch=Mock(),
        sts=Mock(
            get_caller_identity=lambda: {"Account": "123", "Arn": "arn:aws:iam::123:user/test"}
        ),
    )

    assert result["verdict"] == "evidence_unavailable"
    assert result["error"] == {"type": "TimeoutError"}


def test_validation_records_client_failure(monkeypatch) -> None:
    monkeypatch.setattr(harness, "_source_revision", lambda: "revision")
    sqs = Mock()
    sqs.meta.region_name = "eu-central-1"
    sqs.get_queue_attributes.side_effect = RuntimeError("denied")

    result = harness.run_validation(
        "queue-url",
        trials=1,
        metric_timeout_seconds=60,
        poll_seconds=5,
        sqs=sqs,
        cloudwatch=Mock(),
        sts=Mock(),
    )

    assert result["verdict"] == "failed"
    assert result["error"] == {"type": "RuntimeError"}
    assert "queue-url" not in json.dumps(result, sort_keys=True)


def test_evidence_write_is_sorted_and_atomic(tmp_path) -> None:
    output = tmp_path / "sqs-fair-queue.md"

    harness.write_evidence(output, "SQS fair-queue validation", {"z": 1, "a": 2})

    assert output.read_text(encoding="utf-8") == (
        '# SQS fair-queue validation\n\n```json\n{\n  "a": 2,\n  "z": 1\n}\n```\n'
    )
    assert not output.with_suffix(".md.tmp").exists()


def test_main_writes_substituted_sqs_evidence(monkeypatch, tmp_path) -> None:
    output = tmp_path / "sqs-fair-queue.md"
    session = Mock()
    monkeypatch.setattr(
        sys, "argv", ["validate", "--queue-url", "queue-url", "--output", str(output)]
    )
    monkeypatch.setattr(harness.boto3.session, "Session", lambda: session)
    monkeypatch.setattr(harness, "run_validation", lambda *_args, **_kwargs: {"verdict": "passed"})

    assert harness.main() == 0
    assert '"verdict": "passed"' in output.read_text(encoding="utf-8")


def test_main_writes_safe_evidence_when_client_creation_fails(monkeypatch, tmp_path) -> None:
    output = tmp_path / "sqs-fair-queue.md"
    monkeypatch.setattr(
        sys, "argv", ["validate", "--queue-url", "queue-url", "--output", str(output)]
    )
    monkeypatch.setattr(
        harness.boto3.session,
        "Session",
        Mock(side_effect=RuntimeError("credential-value-must-not-leak")),
    )

    assert harness.main() == 1
    rendered = output.read_text(encoding="utf-8")
    assert '"verdict": "failed"' in rendered
    assert '"type": "RuntimeError"' in rendered
    assert "credential-value-must-not-leak" not in rendered
