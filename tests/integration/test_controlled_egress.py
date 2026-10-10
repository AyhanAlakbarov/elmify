import os

import boto3
import pytest

from scripts.validate_controlled_egress import run_validation


@pytest.mark.aws
def test_controlled_egress_validation_stack() -> None:
    stack_name = os.getenv("PHASE1_VALIDATION_STACK")
    if not stack_name:
        pytest.skip("PHASE1_VALIDATION_STACK is not configured")
    session = boto3.session.Session()
    result = run_validation(
        stack_name,
        public_url="https://aws.amazon.com/",
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
        cloudformation=session.client("cloudformation"),
        ecs=session.client("ecs"),
        logs=session.client("logs"),
        sts=session.client("sts"),
    )
    assert result["verdict"] == "passed"
