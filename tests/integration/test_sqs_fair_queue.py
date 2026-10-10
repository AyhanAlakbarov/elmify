import os

import boto3
import pytest

from scripts.validate_sqs_fairness import run_validation, write_evidence


@pytest.mark.aws
def test_validation_queue_is_standard_with_three_receive_redrive(tmp_path) -> None:
    queue_url = os.getenv("PHASE1_VALIDATION_QUEUE_URL")
    if not queue_url:
        pytest.skip("PHASE1_VALIDATION_QUEUE_URL is not configured")
    sqs = boto3.client("sqs")
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["FifoQueue", "RedrivePolicy"]
    )["Attributes"]
    assert attributes.get("FifoQueue", "false") == "false"
    assert '"maxReceiveCount":"3"' in attributes["RedrivePolicy"].replace(" ", "")
    result = run_validation(
        queue_url,
        trials=1,
        metric_timeout_seconds=300,
        poll_seconds=15,
        sqs=sqs,
        cloudwatch=boto3.client("cloudwatch"),
        sts=boto3.client("sts"),
    )
    evidence_path = tmp_path / "sqs-fair-queue.md"
    write_evidence(evidence_path, "SQS fair-queue validation", result)
    assert evidence_path.exists()
    assert result["verdict"] == "passed"
