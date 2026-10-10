# AWS Live Boundary Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Correct the operational entry points, add privacy-safe disposable-run orchestration, run the two AWS boundary probes once in `eu-central-1`, prove teardown, and record reproducible evidence.

**Architecture:** Reuse the existing CloudFormation template and Python harnesses. A small Bash controller creates one temporary ECR repository, deploys the one validation stack with an immutable image digest, runs controlled egress followed by SQS fairness, and always deletes and audits the resources.

**Tech Stack:** Python 3.12, Bash, `uv`, pytest, Ruff, Mypy, Docker, AWS CLI v2, CloudFormation, ECR, ECS/Fargate, VPC Flow Logs, CloudWatch, and SQS.

## Global Constraints

- Tasks 1–4 make no billable AWS changes; authenticated calls in Task 4 are read-only validation calls.
- Task 5 begins only after the user gives a final go/no-go immediately before ECR creation.
- Use only `AWS_PROFILE=tehsil-sandbox` and `AWS_REGION=eu-central-1`; reject any other value.
- Use the existing temporary AWS login session and create no access key.
- Treat `$2 USD` as an operational ceiling, not a guaranteed hard cap.
- Send `TERM` no later than 30 minutes after starting the live controller; cleanup may continue until deletion is proven.
- Make no automatic live retry. Diagnose locally and request fresh approval before any second billable run.
- Delete resources after success, failure, timeout, or interruption; cleanup failure overrides probe success.
- Add no dependency.
- Do not print, write, or commit AWS account IDs, IAM names, raw ARNs, registry/repository URIs, queue URLs, credentials, MFA material, or secret values.
- Preserve unrelated user files. Stage only files listed by the active task.
- Use test-first RED/GREEN commits for behavior changes.

## File Map

- Modify `infra/template.yaml`: use the working module command inside the Fargate task.
- Modify `scripts/validate_controlled_egress.py`: use module command overrides and emit privacy-safe evidence.
- Modify `scripts/validate_sqs_fairness.py`: emit privacy-safe evidence.
- Create `scripts/run_aws_boundary_validation.sh`: preflight, deploy, probe, teardown, audit, cleanup-only recovery, and run summary.
- Modify `tests/research/test_controlled_egress_validation.py`: module-command and privacy contracts.
- Modify `tests/research/test_fairness_validation.py`: module-command and privacy contracts.
- Create `tests/test_aws_boundary_run_controller.py`: shell lifecycle and cleanup tests using substituted command boundaries.
- Modify `docs/validation/controlled-egress.md`: working command and live result.
- Modify `docs/validation/sqs-fair-queue.md`: working command and live result.
- Create `docs/validation/aws-boundary-run.md`: sanitized run and teardown summary.
- Create `docs/testing/aws-live-boundary-validation.tdd.md`: RED/GREEN/offline/live verification transcript without identifiers.
- Modify `docs/superpowers/plans/2026-08-10-phase-1-funding-intelligence-concierge-mvp.md`: mark only the two live boundary-proof steps after success.

---

### Task 1: Correct Every Operational Python Entry Point

**Files:**
- Modify: `tests/research/test_controlled_egress_validation.py`
- Modify: `tests/research/test_fairness_validation.py`
- Modify: `infra/template.yaml`
- Modify: `scripts/validate_controlled_egress.py`
- Modify: `docs/validation/controlled-egress.md`
- Modify: `docs/validation/sqs-fair-queue.md`

**Interfaces:**
- Consumes: repository-root Python module imports and the current Fargate command override.
- Produces: `python -m scripts.validate_controlled_egress` and `python -m scripts.validate_sqs_fairness` as the only documented/runtime invocation forms.

- [x] **Step 1: Write failing exact-entry-point tests**

Add `subprocess` and `sys` to both test modules; add `Path` to the fairness test module (the controlled-egress test already imports it):

```python
import subprocess
import sys
from pathlib import Path
```

Add to `tests/research/test_controlled_egress_validation.py`:

```python
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
    assert "uv run python -m scripts.validate_controlled_egress" in documentation
```

Extend `test_fargate_launch_disables_public_ip()` with:

```python
    assert request["overrides"]["containerOverrides"][0]["command"][:3] == [
        "python",
        "-m",
        "scripts.validate_controlled_egress",
    ]
```

Add to `tests/research/test_fairness_validation.py`:

```python
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
    assert "uv run python -m scripts.validate_sqs_fairness" in documentation
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-task1-red uv run pytest tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py -q
```

Expected: the module `--help` subprocesses pass, while the template, override, and documentation assertions fail because they still use filesystem-script execution.

- [x] **Step 3: Commit the RED checkpoint**

```text
git add tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py
git commit -m "test: expose AWS validation entrypoint failure"
```

- [x] **Step 4: Apply the minimal module-command correction**

Change the CloudFormation command to:

```yaml
          Command:
            - python
            - -m
            - scripts.validate_controlled_egress
            - --task-probe
```

Change `run_fargate_probe()` to build:

```python
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
        outputs["ValidationBucketName"],
        "--secret-arn",
        outputs["ValidationSecretArn"],
    ]
```

Replace the two documented commands while retaining their arguments:

```text
uv run python -m scripts.validate_controlled_egress \
  --stack-name "$PHASE1_VALIDATION_STACK" \
  --output docs/validation/controlled-egress.md

uv run python -m scripts.validate_sqs_fairness \
  --queue-url "$PHASE1_VALIDATION_QUEUE_URL" \
  --trials 3 \
  --output docs/validation/sqs-fair-queue.md
```

- [x] **Step 5: Run GREEN verification**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-task1-green uv run pytest tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py -q
UV_CACHE_DIR=/tmp/tehsil-aws-live-task1-green uv run python -m scripts.validate_controlled_egress --help
UV_CACHE_DIR=/tmp/tehsil-aws-live-task1-green uv run python -m scripts.validate_sqs_fairness --help
UV_CACHE_DIR=/tmp/tehsil-aws-live-task1-green uv run ruff check infra scripts tests
```

Expected: all commands exit zero and make no AWS call.

- [x] **Step 6: Commit the correction**

```text
git add infra/template.yaml scripts/validate_controlled_egress.py docs/validation/controlled-egress.md docs/validation/sqs-fair-queue.md
git commit -m "fix: use runnable AWS validation modules"
```

### Task 2: Remove Private AWS Identity From Evidence

**Files:**
- Modify: `tests/research/test_controlled_egress_validation.py`
- Modify: `tests/research/test_fairness_validation.py`
- Modify: `scripts/validate_controlled_egress.py`
- Modify: `scripts/validate_sqs_fairness.py`

**Interfaces:**
- Consumes: raw AWS responses needed in process memory.
- Produces: evidence containing operational facts but no account, IAM, URL, ARN, stack-output, or registry identity.

- [x] **Step 1: Write failing privacy-contract tests**

Replace the final assertions in `test_validation_records_substituted_stack_and_fargate_evidence()` with:

```python
    assert result["verdict"] == "passed"
    assert result["stack"] == {"name": "validation-stack"}
    assert result["sts"] == {"authenticated": True}
    assert result["fargate"]["task_id"] == "t-1"
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
```

Use a 12-digit substituted account in the test STS response and make the substituted Fargate result `{"passed": True, "task_id": "t-1"}`.

Extend `test_validation_records_substituted_trials_and_metrics()` with:

```python
    assert result["queue"] == {"name": "validation-queue"}
    assert result["sts"] == {"authenticated": True}
    rendered = json.dumps(result, sort_keys=True)
    assert "123456789012" not in rendered
    assert "arn:aws:" not in rendered
    assert "queue-url" not in rendered
```

Extend `test_validation_records_client_failure()` to assert `queue-url` is absent. Add this controlled-egress failure-after-output-loading case:

```python
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
```

- [x] **Step 2: Run the privacy tests and verify RED**

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-task2-red uv run pytest tests/research/test_controlled_egress_validation.py::test_validation_records_substituted_stack_and_fargate_evidence tests/research/test_controlled_egress_validation.py::test_failed_controlled_validation_omits_private_stack_values tests/research/test_fairness_validation.py::test_validation_records_substituted_trials_and_metrics tests/research/test_fairness_validation.py::test_validation_records_client_failure -q
```

Expected: failures expose the current STS identity, queue URL/ARN, stack ID, raw outputs, and task ARN fields.

- [x] **Step 3: Commit the RED checkpoint**

```text
git add tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py
git commit -m "test: require private AWS validation evidence"
```

- [x] **Step 4: Construct only safe controlled-egress evidence**

In `run_validation()` keep outputs local and replace the persisted identity/resource blocks with:

```python
        stack = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]
        evidence["stack"] = {"name": stack_name}
        if not stack_resources(stack_name, cloudformation):
            raise ValueError("stack is missing required resources")
        outputs = stack_outputs(stack_name, cloudformation)
        identity = sts.get_caller_identity()
        if not identity.get("Account") or not identity.get("Arn"):
            raise ValueError("STS returned incomplete caller identity")
        evidence["sts"] = {"authenticated": True}
```

In `run_fargate_probe()` retain the raw ARN only for API calls and return:

```python
    result: dict[str, object] = {
        "task_id": task_arn.rsplit("/", 1)[-1],
        "eni_id": eni_id,
        "eni_private_ip": private_ip,
        "exit_code": exit_code,
        "checks": probe_result["checks"],
        "public_destination_ips": sorted(destination_ips),
        "flow_log_records": [],
        "observation_window": {
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "start_time_ms": start_time_ms,
            "end_time_ms": end_time_ms,
        },
        "limits": {
            "task_timeout_seconds": task_timeout_seconds,
            "flow_log_timeout_seconds": flow_log_timeout_seconds,
            "poll_seconds": poll_seconds,
        },
        "passed": bool(probe_result["passed"]),
    }
```

- [x] **Step 5: Construct only safe SQS evidence**

Initialize `queue` as an empty mapping, then persist only its name and authenticated state:

```python
queue_arn = getattr(sqs, "get_queue_attributes")(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
    "Attributes"
]["QueueArn"]
queue_name = queue_arn.rsplit(":", 1)[-1]
evidence["queue"] = {"name": queue_name}
identity = getattr(sts, "get_caller_identity")()
if not identity.get("Account") or not identity.get("Arn"):
    raise ValueError("STS returned incomplete caller identity")
evidence["sts"] = {"authenticated": True}
```

Do not add a generic recursive redactor; omitting private fields at construction is smaller and fail-closed.

- [x] **Step 6: Run GREEN and privacy scanning**

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-task2-green uv run pytest tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py -q
UV_CACHE_DIR=/tmp/tehsil-aws-live-task2-green uv run ruff check scripts tests
```

Then serialize substituted results in the focused tests and verify that the prohibited strings are absent. Expected: all checks pass.

- [x] **Step 7: Commit the evidence correction**

```text
git add scripts/validate_controlled_egress.py scripts/validate_sqs_fairness.py
git commit -m "fix: keep AWS validation evidence private"
```

### Task 3: Add the Disposable Run and Cleanup Controller

**Files:**
- Create: `tests/test_aws_boundary_run_controller.py`
- Create: `scripts/run_aws_boundary_validation.sh`
- Create: `docs/validation/aws-boundary-run.md`
- Modify: `infra/template.yaml`

**Interfaces:**
- Consumes: `AWS_PROFILE`, `AWS_REGION`, Docker access, `infra/template.yaml`, and both Python harness modules.
- Produces: `main`, `cleanup`, `audit_absence`, and `--cleanup-only`; the process exits zero only after both probes and teardown pass.

- [x] **Step 1: Write failing shell safety-contract tests**

Create `tests/test_aws_boundary_run_controller.py` with these contracts:

```python
import os
import signal
import subprocess
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_aws_boundary_validation.sh"


def _run_sourced(
    body: str, tmp_path: Path, *, timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    trace = tmp_path / "trace"
    command = textwrap.dedent(
        f"""
        set -Eeuo pipefail
        source {SCRIPT}
        aws_cli() {{ printf 'aws %s\\n' "$*" >> "$TRACE"; }}
        docker_cli() {{ printf 'docker %s\\n' "$*" >> "$TRACE"; }}
        {body}
        """
    )
    return subprocess.run(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "TRACE": str(trace),
            "AWS_PROFILE": "tehsil-sandbox",
            "AWS_REGION": "eu-central-1",
        },
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_controller_has_bounded_private_cleanup_contract() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    template = (ROOT / "infra/template.yaml").read_text(encoding="utf-8")
    for fragment in (
        "set -Eeuo pipefail",
        "umask 077",
        'EXPECTED_PROFILE="tehsil-sandbox"',
        'EXPECTED_REGION="eu-central-1"',
        "trap finish EXIT",
        "trap 'exit 124' INT TERM",
        "Project=tehsil-agent",
        "Purpose=aws-boundary-validation",
        "--cleanup-only",
        "--preflight-only",
        "delete-repository --repository-name",
        "--force",
        "wait stack-delete-complete",
    ):
        assert fragment in source
    assert "get-login-password" in source
    assert "--password-stdin" in source
    for fragment in (
        'LogGroupName: !Sub "/tehsil/validation/${AWS::StackName}/flow"',
        'ClusterName: !Sub "${AWS::StackName}-probe"',
        'LogGroupName: !Sub "/tehsil/validation/${AWS::StackName}/probe"',
    ):
        assert fragment in template


def test_probe_failure_still_runs_cleanup(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        preflight() { :; }
        select_docker_command() { :; }
        publish_image() { :; }
        deploy_stack() { :; }
        run_controlled_probe() { return 7; }
        stack_count() { printf '0\\n'; }
        repository_count() { printf '0\\n'; }
        delete_owned_stack() { printf 'stack-delete\\n' >> "$TRACE"; }
        delete_owned_repo() { printf 'repo-delete\\n' >> "$TRACE"; }
        audit_absence() { printf 'audit\\n' >> "$TRACE"; }
        write_run_summary() { :; }
        main
        """,
        tmp_path,
    )
    assert completed.returncode != 0
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines()[-3:] == [
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_success_runs_both_probes_then_cleanup(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        preflight() { :; }
        select_docker_command() { :; }
        publish_image() { printf 'image\\n' >> "$TRACE"; }
        deploy_stack() { printf 'stack\\n' >> "$TRACE"; }
        run_controlled_probe() { printf 'controlled\\n' >> "$TRACE"; }
        run_sqs_probe() { printf 'sqs\\n' >> "$TRACE"; }
        stack_count() { printf '0\\n'; }
        repository_count() { printf '0\\n'; }
        delete_owned_stack() { printf 'stack-delete\\n' >> "$TRACE"; }
        delete_owned_repo() { printf 'repo-delete\\n' >> "$TRACE"; }
        audit_absence() { printf 'audit\\n' >> "$TRACE"; }
        write_run_summary() { :; }
        main
        """,
        tmp_path,
    )
    assert completed.returncode == 0
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines() == [
        "image",
        "stack",
        "controlled",
        "sqs",
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_image_publication_uses_substituted_commands_without_printing_registry(
    tmp_path: Path,
) -> None:
    completed = _run_sourced(
        """
        aws_cli() {
          printf 'aws %s %s\\n' "$1" "$2" >> "$TRACE"
          case "$1 $2" in
            "ecr create-repository") printf 'private-registry.example/repository\\n' ;;
            "ecr get-login-password") printf 'temporary-password\\n' ;;
            "ecr describe-images")
              printf 'sha256:%s\\n' \
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
              ;;
          esac
        }
        docker_cli() { printf 'docker %s\\n' "$1" >> "$TRACE"; cat >/dev/null || true; }
        publish_image
        """,
        tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    assert "private-registry.example" not in completed.stdout
    assert "temporary-password" not in completed.stdout
    assert (tmp_path / "trace").read_text(encoding="utf-8").splitlines() == [
        "aws ecr create-repository",
        "aws ecr get-login-password",
        "docker login",
        "docker build",
        "docker tag",
        "docker push",
        "aws ecr describe-images",
    ]


def test_sigterm_still_runs_cleanup(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    command = textwrap.dedent(
        f"""
        set -Eeuo pipefail
        source {SCRIPT}
        preflight() {{ :; }}
        select_docker_command() {{ :; }}
        publish_image() {{ :; }}
        deploy_stack() {{ :; }}
        run_controlled_probe() {{ printf 'controlled-start\\n' >> "$TRACE"; sleep 30; }}
        stack_count() {{ printf '0\\n'; }}
        repository_count() {{ printf '0\\n'; }}
        delete_owned_stack() {{ printf 'stack-delete\\n' >> "$TRACE"; }}
        delete_owned_repo() {{ printf 'repo-delete\\n' >> "$TRACE"; }}
        audit_absence() {{ printf 'audit\\n' >> "$TRACE"; }}
        write_run_summary() {{ :; }}
        main
        """
    )
    process = subprocess.Popen(
        ["bash", "-c", command],
        cwd=ROOT,
        env={
            **os.environ,
            "TRACE": str(trace),
            "AWS_PROFILE": "tehsil-sandbox",
            "AWS_REGION": "eu-central-1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if trace.exists() and "controlled-start" in trace.read_text(encoding="utf-8"):
            break
        time.sleep(0.01)
    else:
        process.kill()
        raise AssertionError("controller did not reach the probe")
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=10)
    assert process.returncode != 0
    assert trace.read_text(encoding="utf-8").splitlines()[-3:] == [
        "stack-delete",
        "repo-delete",
        "audit",
    ]


def test_cleanup_only_refuses_unowned_resources(tmp_path: Path) -> None:
    completed = _run_sourced(
        """
        stack_count() { printf '1\\n'; }
        repository_count() { printf '0\\n'; }
        stack_is_owned() { return 9; }
        delete_owned_stack() { printf 'unexpected-delete\\n' >> "$TRACE"; }
        cleanup_only
        """,
        tmp_path,
    )
    assert completed.returncode != 0
    assert "ownership tags do not match" in completed.stderr
    assert not (tmp_path / "trace").exists()
```

- [x] **Step 2: Run RED**

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-task3-red uv run pytest tests/test_aws_boundary_run_controller.py -q
```

Expected: failure because the controller does not exist.

- [x] **Step 3: Commit the RED checkpoint**

```text
git add tests/test_aws_boundary_run_controller.py
git commit -m "test: define disposable AWS run lifecycle"
```

- [x] **Step 4: Implement the minimal shell state machine**

Create `scripts/run_aws_boundary_validation.sh` with this fixed state and lifecycle:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

EXPECTED_PROFILE="tehsil-sandbox"
EXPECTED_REGION="eu-central-1"
STACK_NAME="tehsil-phase1-validation"
REPOSITORY_NAME="tehsil-phase1-validation-probe"
CONTROLLED_OUTPUT="docs/validation/controlled-egress.md"
SQS_OUTPUT="docs/validation/sqs-fair-queue.md"
RUN_OUTPUT="docs/validation/aws-boundary-run.md"
IMAGE_DIGEST=""
REPOSITORY_URI=""
PROBE_IMAGE=""
QUEUE_URL=""
CLUSTER_ARN=""
PROBE_STATUS=1
CLEANUP_STATUS=1
STACK_DELETE_STATUS=1
REPOSITORY_DELETE_STATUS=1
AUDIT_STATUS=1
CLEANUP_STARTED=0
RUN_STARTED_AT=""

aws_cli() {
  aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@" 2>/dev/null
}

docker_cli() {
  "${DOCKER_COMMAND[@]}" "$@"
}

run_python() {
  uv run python -m "$@"
}

require_context() {
  [[ "${AWS_PROFILE:-}" == "$EXPECTED_PROFILE" ]] || {
    echo "AWS profile must be $EXPECTED_PROFILE" >&2
    return 2
  }
  [[ "${AWS_REGION:-}" == "$EXPECTED_REGION" ]] || {
    echo "AWS region must be $EXPECTED_REGION" >&2
    return 2
  }
  export AWS_DEFAULT_REGION="$AWS_REGION"
}

select_docker_command() {
  if docker info >/dev/null 2>&1; then
    DOCKER_COMMAND=(docker)
  elif sudo -n docker info >/dev/null 2>&1; then
    DOCKER_COMMAND=(sudo -n docker)
  else
    echo "Docker access unavailable; run sudo -v and retry" >&2
    return 2
  fi
}

finish() {
  local original_status=$?
  trap - EXIT INT TERM
  if cleanup; then
    CLEANUP_STATUS=0
  else
    CLEANUP_STATUS=$?
  fi
  write_run_summary "$original_status" "$CLEANUP_STATUS"
  if (( original_status == 0 && CLEANUP_STATUS == 0 )); then
    exit 0
  fi
  exit 1
}

main() {
  require_context
  preflight
  select_docker_command
  trap finish EXIT
  trap 'exit 124' INT TERM
  RUN_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  publish_image
  deploy_stack
  run_controlled_probe
  run_sqs_probe
  PROBE_STATUS=0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  case "${1:-}" in
    --preflight-only)
      require_context
      preflight
      ;;
    --cleanup-only)
      require_context
      cleanup_only
      ;;
    "")
      main
      ;;
    *)
      echo "usage: $0 [--preflight-only|--cleanup-only]" >&2
      exit 2
      ;;
  esac
fi
```

Use explicit, auditable resource names in `infra/template.yaml`:

```yaml
  FlowLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/tehsil/validation/${AWS::StackName}/flow"
      RetentionInDays: 30

  ValidationCluster:
    Type: AWS::ECS::Cluster
    Properties:
      ClusterName: !Sub "${AWS::StackName}-probe"

  ProbeLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/tehsil/validation/${AWS::StackName}/probe"
      RetentionInDays: 7
```

Add static test assertions for all three names. This makes cleanup-only auditing possible after CloudFormation no longer exposes stack outputs.

Implement the AWS operations with these exact functions:

```bash
stack_count() {
  aws_cli cloudformation list-stacks \
    --query "length(StackSummaries[?StackName=='${STACK_NAME}' && StackStatus!='DELETE_COMPLETE'])" \
    --output text
}

repository_count() {
  aws_cli ecr describe-repositories \
    --query "length(repositories[?repositoryName=='${REPOSITORY_NAME}'])" \
    --output text
}

preflight() {
  echo "Preflight: validating identity, names, and region"
  [[ "$(aws_cli sts get-caller-identity --query 'Account != null && Arn != null' --output text)" == "True" ]]
  [[ "$(stack_count)" == "0" ]]
  [[ "$(repository_count)" == "0" ]]
  [[ "$(aws_cli logs describe-log-groups --log-group-name-prefix "/tehsil/validation/${STACK_NAME}/" --query 'length(logGroups)' --output text)" == "0" ]]
}

publish_image() {
  echo "Deploy: publishing immutable probe image"
  REPOSITORY_URI="$(aws_cli ecr create-repository \
    --repository-name "$REPOSITORY_NAME" \
    --tags Key=Project,Value=tehsil-agent Key=Purpose,Value=aws-boundary-validation \
    --query 'repository.repositoryUri' --output text)"
  local registry="${REPOSITORY_URI%%/*}"
  aws_cli ecr get-login-password | docker_cli login --username AWS --password-stdin "$registry" >/dev/null 2>&1
  docker_cli build --platform linux/amd64 --target web --tag tehsil-agent:aws-boundary . >/dev/null 2>&1
  docker_cli tag tehsil-agent:aws-boundary "${REPOSITORY_URI}:validation"
  docker_cli push "${REPOSITORY_URI}:validation" >/dev/null 2>&1
  IMAGE_DIGEST="$(aws_cli ecr describe-images --repository-name "$REPOSITORY_NAME" \
    --image-ids imageTag=validation --query 'imageDetails[0].imageDigest' --output text)"
  [[ "$IMAGE_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
  PROBE_IMAGE="${REPOSITORY_URI}@${IMAGE_DIGEST}"
}

stack_output() {
  local key=$1
  aws_cli cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" --output text
}

deploy_stack() {
  echo "Deploy: creating disposable validation stack"
  aws_cli cloudformation deploy \
    --stack-name "$STACK_NAME" \
    --template-file infra/template.yaml \
    --parameter-overrides "ProbeImage=${PROBE_IMAGE}" \
    --capabilities CAPABILITY_IAM \
    --tags Project=tehsil-agent Purpose=aws-boundary-validation >/dev/null
  QUEUE_URL="$(stack_output ResearchQueueUrl)"
  CLUSTER_ARN="$(stack_output ProbeClusterArn)"
}

run_controlled_probe() {
  echo "Probe: controlled egress and Flow Logs"
  run_python scripts.validate_controlled_egress \
    --stack-name "$STACK_NAME" --output "$CONTROLLED_OUTPUT"
}

run_sqs_probe() {
  echo "Probe: three SQS fairness trials"
  run_python scripts.validate_sqs_fairness \
    --queue-url "$QUEUE_URL" --trials 3 --output "$SQS_OUTPUT"
}
```

Implement ownership checks and deletion without a retain/express escape hatch:

```bash
stack_is_owned() {
  [[ "$(aws_cli cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Tags[?Key=='Project'].Value | [0]" --output text)" == "tehsil-agent" ]] &&
  [[ "$(aws_cli cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query "Stacks[0].Tags[?Key=='Purpose'].Value | [0]" --output text)" == "aws-boundary-validation" ]]
}

repository_is_owned() {
  local repository_arn
  repository_arn="$(aws_cli ecr describe-repositories --repository-names "$REPOSITORY_NAME" \
    --query 'repositories[0].repositoryArn' --output text)"
  [[ "$(aws_cli ecr list-tags-for-resource --resource-arn "$repository_arn" \
    --query "tags[?Key=='Project'].Value | [0]" --output text)" == "tehsil-agent" ]] &&
  [[ "$(aws_cli ecr list-tags-for-resource --resource-arn "$repository_arn" \
    --query "tags[?Key=='Purpose'].Value | [0]" --output text)" == "aws-boundary-validation" ]]
}

delete_owned_stack() {
  [[ "$(stack_count)" == "0" ]] && return 0
  stack_is_owned || { echo "Refusing to delete an unowned stack" >&2; return 3; }
  CLUSTER_ARN="${CLUSTER_ARN:-$(stack_output ProbeClusterArn 2>/dev/null || true)}"
  local tasks
  if [[ -n "$CLUSTER_ARN" && "$CLUSTER_ARN" != "None" ]]; then
    tasks="$(aws_cli ecs list-tasks --cluster "$CLUSTER_ARN" --desired-status RUNNING \
      --query 'taskArns[]' --output text)"
    for task in $tasks; do
      aws_cli ecs stop-task --cluster "$CLUSTER_ARN" --task "$task" >/dev/null
    done
  fi
  aws_cli cloudformation delete-stack --stack-name "$STACK_NAME"
  aws_cli cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
}

delete_owned_repo() {
  [[ "$(repository_count)" == "0" ]] && return 0
  repository_is_owned || { echo "Refusing to delete an unowned repository" >&2; return 3; }
  aws_cli ecr delete-repository --repository-name "$REPOSITORY_NAME" --force >/dev/null
}
```

Implement the exact absence audit and idempotent cleanup:

```bash
audit_absence() {
  [[ "$(stack_count)" == "0" ]]
  [[ "$(repository_count)" == "0" ]]
  [[ "$(aws_cli ec2 describe-nat-gateways \
    --filter Name=tag:aws:cloudformation:stack-name,Values="$STACK_NAME" \
    --query "length(NatGateways[?State!='deleted'])" --output text)" == "0" ]]
  [[ "$(aws_cli ec2 describe-vpc-endpoints \
    --filters Name=tag:aws:cloudformation:stack-name,Values="$STACK_NAME" \
    --query 'length(VpcEndpoints)' --output text)" == "0" ]]
  [[ "$(aws_cli ec2 describe-addresses \
    --filters Name=tag:aws:cloudformation:stack-name,Values="$STACK_NAME" \
    --query 'length(Addresses)' --output text)" == "0" ]]
  [[ "$(aws_cli logs describe-log-groups \
    --log-group-name-prefix "/tehsil/validation/${STACK_NAME}/" \
    --query 'length(logGroups)' --output text)" == "0" ]]
  [[ "$(aws_cli ecs describe-clusters --clusters "${STACK_NAME}-probe" \
    --query "length(clusters[?status=='ACTIVE'])" --output text)" == "0" ]]
}

cleanup() {
  (( CLEANUP_STARTED == 0 )) || return 0
  CLEANUP_STARTED=1
  echo "Cleanup: deleting stack, repository, and validating absence"
  [[ "$(stack_count)" == "0" ]] || stack_is_owned || {
    echo "Refusing cleanup because the stack ownership tags do not match" >&2
    return 3
  }
  [[ "$(repository_count)" == "0" ]] || repository_is_owned || {
    echo "Refusing cleanup because the repository ownership tags do not match" >&2
    return 3
  }
  local failed=0
  if delete_owned_stack; then
    STACK_DELETE_STATUS=0
  else
    failed=1
  fi
  if delete_owned_repo; then
    REPOSITORY_DELETE_STATUS=0
  else
    failed=1
  fi
  if audit_absence; then
    AUDIT_STATUS=0
  else
    failed=1
  fi
  return "$failed"
}

cleanup_only() {
  cleanup
}
```

Implement the run summary without copying any captured AWS identifier:

```bash
write_run_summary() {
  local _controller_status=$1
  local cleanup_status=$2
  local revision digest started ended probe_verdict stack_verdict repository_verdict
  local audit_verdict teardown_verdict overall_verdict temporary
  revision="$(git rev-parse HEAD)"
  digest="${IMAGE_DIGEST:-unavailable}"
  started="${RUN_STARTED_AT:-unavailable}"
  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  probe_verdict="failed"
  stack_verdict="failed"
  repository_verdict="failed"
  audit_verdict="failed"
  teardown_verdict="failed"
  overall_verdict="failed"
  (( PROBE_STATUS == 0 )) && probe_verdict="passed"
  (( STACK_DELETE_STATUS == 0 )) && stack_verdict="passed"
  (( REPOSITORY_DELETE_STATUS == 0 )) && repository_verdict="passed"
  (( AUDIT_STATUS == 0 )) && audit_verdict="passed"
  (( cleanup_status == 0 )) && teardown_verdict="passed"
  if [[ "$probe_verdict" == "passed" && "$teardown_verdict" == "passed" ]]; then
    overall_verdict="passed"
  fi
  temporary="${RUN_OUTPUT}.tmp"
  printf '# AWS boundary validation run\n\n```json\n{\n' > "$temporary"
  printf '  "audit_verdict": "%s",\n' "$audit_verdict" >> "$temporary"
  printf '  "ended_at": "%s",\n' "$ended" >> "$temporary"
  printf '  "image_digest": "%s",\n' "$digest" >> "$temporary"
  printf '  "overall_verdict": "%s",\n' "$overall_verdict" >> "$temporary"
  printf '  "probe_verdict": "%s",\n' "$probe_verdict" >> "$temporary"
  printf '  "repository_deletion_verdict": "%s",\n' "$repository_verdict" >> "$temporary"
  printf '  "region": "%s",\n' "$AWS_REGION" >> "$temporary"
  printf '  "source_revision": "%s",\n' "$revision" >> "$temporary"
  printf '  "stack_deletion_verdict": "%s",\n' "$stack_verdict" >> "$temporary"
  printf '  "started_at": "%s",\n' "$started" >> "$temporary"
  printf '  "teardown_verdict": "%s",\n' "$teardown_verdict" >> "$temporary"
  printf '  "time_limit": "30 minutes"\n}\n```\n' >> "$temporary"
  mv "$temporary" "$RUN_OUTPUT"
}
```

The operator command is exactly:

```text
AWS_PROFILE=tehsil-sandbox AWS_REGION=eu-central-1 timeout --signal=TERM 30m bash scripts/run_aws_boundary_validation.sh
```

- [x] **Step 5: Add the honest initial run document**

Create `docs/validation/aws-boundary-run.md`:

```markdown
# AWS boundary validation run

No authenticated live run is recorded yet. The disposable controller must pass both probes,
delete its stack and ECR repository, and pass the absence audit before this document is replaced.
```

- [x] **Step 6: Run GREEN lifecycle verification**

```text
bash -n scripts/run_aws_boundary_validation.sh
UV_CACHE_DIR=/tmp/tehsil-aws-live-task3-green uv run pytest tests/test_aws_boundary_run_controller.py -q
UV_CACHE_DIR=/tmp/tehsil-aws-live-task3-green uv run ruff check tests/test_aws_boundary_run_controller.py
```

Expected: success, failure, `SIGTERM`, cleanup-only ownership rejection, and idempotent cleanup cases all pass without AWS or Docker access.

- [x] **Step 7: Commit the controller**

```text
git add infra/template.yaml scripts/run_aws_boundary_validation.sh tests/test_aws_boundary_run_controller.py docs/validation/aws-boundary-run.md
git commit -m "feat: add disposable AWS validation run controller"
```

### Task 4: Prove Offline Readiness and Present the Final Go/No-Go

**Files:**
- Create: `docs/testing/aws-live-boundary-validation.tdd.md`

**Interfaces:**
- Consumes: Tasks 1–3 and the local PostgreSQL/Docker environment.
- Produces: verified local readiness plus a read-only AWS preflight summary; no billable resource.

- [x] **Step 1: Start only local PostgreSQL if it is not already healthy**

Because the user deliberately retained `sudo` isolation for Docker, first refresh sudo interactively:

```text
sudo -v
sudo docker compose up -d --wait --wait-timeout 60 postgres
```

- [x] **Step 2: Run the complete local verification matrix**

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run pytest -m "not aws" -q
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run ruff check .
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run mypy .
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run python manage.py check
bash -n scripts/run_aws_boundary_validation.sh
sudo docker build --platform linux/amd64 --target web --tag tehsil-agent:aws-boundary-offline .
```

Expected: all configured checks pass. Record exact counts and warnings; do not convert warnings into claimed passes.

- [x] **Step 3: Run privacy and context scans**

Run this negative scan; exit zero means no prohibited value was found:

```text
! rg -n '[0-9]{12}|arn:aws:|:user/|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key' docs/validation
```

Expected: no output. Substituted values may exist only inside tests; committed evidence and operational logs contain none.

- [x] **Step 4: Perform authenticated read-only AWS preflight**

If needed, the user runs:

```text
aws login --profile tehsil-sandbox
```

Then run without displaying identity:

```text
aws sts get-caller-identity --profile tehsil-sandbox --region eu-central-1 --query 'Account != null && Arn != null' --output text
aws cloudformation validate-template --template-body file://infra/template.yaml --profile tehsil-sandbox --region eu-central-1
```

Expected: `True` and a valid template response. Run the collision-only preflight:

```text
AWS_PROFILE=tehsil-sandbox AWS_REGION=eu-central-1 bash scripts/run_aws_boundary_validation.sh --preflight-only
```

Expected: success with the fixed stack, repository, and log-group names absent; no AWS write.

- [x] **Step 5: Write and commit the TDD/offline report**

Create `docs/testing/aws-live-boundary-validation.tdd.md` with the RED commands and failures from Tasks 1–3, the GREEN commands and counts, Docker/CloudFormation results, and the statement `No billable AWS resources were created during Tasks 1–4.`

```text
git add docs/testing/aws-live-boundary-validation.tdd.md
git commit -m "docs: record AWS live validation readiness"
```

- [x] **Step 6: Present the final go/no-go checkpoint**

Report exactly this bounded inventory: one temporary ECR repository; one NAT gateway; five interface endpoints in two Availability Zones; one Fargate task; one secret; two log groups; one queue and DLQ; four alarms. Restate that `$2` is not a guaranteed cap, no resource exists yet, and the next command begins billing. Wait for the user's explicit approval.

### Task 5: Execute One Live Run and Prove Teardown

**Files:**
- Modify: `docs/validation/controlled-egress.md`
- Modify: `docs/validation/sqs-fair-queue.md`
- Modify: `docs/validation/aws-boundary-run.md`

**Interfaces:**
- Consumes: explicit final user approval and a valid temporary AWS session.
- Produces: two passing probe documents and one passing teardown summary, or a failed run with proven cleanup.

- [x] **Step 1: Refresh Docker authorization without widening privileges**

The user runs:

```text
sudo -v
```

Do not add the user to the Docker group and do not run the whole controller under sudo.

- [x] **Step 2: Start the live controller in a resumable terminal session**

```text
AWS_PROFILE=tehsil-sandbox AWS_REGION=eu-central-1 timeout --signal=TERM 30m bash scripts/run_aws_boundary_validation.sh
```

Poll the running session and report safe phase-only progress at least once per minute. Do not expose captured AWS output.

- [x] **Step 3: Handle the controller result**

If it exits zero, continue to Step 4.

If it exits non-zero, immediately run:

```text
AWS_PROFILE=tehsil-sandbox AWS_REGION=eu-central-1 bash scripts/run_aws_boundary_validation.sh --cleanup-only
```

Keep working until cleanup and the absence audit pass. Do not retry the probes automatically and do not commit failed evidence as a completed gate.

- [x] **Step 4: Independently verify the live evidence**

Require all of the following:

- `controlled-egress.md` contains `"verdict": "passed"` and the Flow Log match.
- `sqs-fair-queue.md` contains three passed trials and all five metric names.
- `aws-boundary-run.md` contains passed probe, teardown, audit, and overall verdicts.
- none of the three documents contains a 12-digit account ID, `arn:aws:`, an IAM-user path, a queue URL, a registry hostname, an access key pattern, or a secret value.

- [x] **Step 5: Independently verify absence**

Run the cleanup-only command again. Expected: it recognizes both resources are absent, performs only the read-only audit, and exits zero. Confirm there is no active matching NAT gateway, VPC endpoint, EIP, ECS task, log group, stack, or ECR repository.

- [x] **Step 6: Stop local PostgreSQL if it was started for this task**

```text
sudo docker compose stop postgres
```

The local Docker image and PostgreSQL volume may remain cached; they incur no AWS charge.

### Task 6: Commit Evidence and Close Only the Proven Phase 1 Steps

**Files:**
- Modify: `docs/validation/controlled-egress.md`
- Modify: `docs/validation/sqs-fair-queue.md`
- Modify: `docs/validation/aws-boundary-run.md`
- Modify: `docs/testing/aws-live-boundary-validation.tdd.md`
- Modify: `docs/superpowers/plans/2026-08-10-phase-1-funding-intelligence-concierge-mvp.md`

**Interfaces:**
- Consumes: successful Task 5 evidence and absence audit.
- Produces: a reproducible evidence commit and exactly two completed live-validation checkboxes.

- [x] **Step 1: Update the TDD report with live outcomes**

Append only sanitized command names, pass/fail outcomes, timestamps, trial counts, and teardown/audit results. Do not copy raw AWS CLI output.

- [x] **Step 2: Mark the two proven Phase 1 steps**

Change only these checklist entries from `[ ]` to `[x]`:

- Task 4, Step 4: `Deploy and run the real two-tenant fairness probe`.
- Task 5, Step 4: `Validate the AWS network boundary`.

Leave every other Phase 1 checkbox unchanged.

- [x] **Step 3: Run final local verification**

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-final uv run pytest -m "not aws" -q
UV_CACHE_DIR=/tmp/tehsil-aws-live-final uv run ruff check .
UV_CACHE_DIR=/tmp/tehsil-aws-live-final uv run mypy .
UV_CACHE_DIR=/tmp/tehsil-aws-live-final uv run python manage.py check
bash -n scripts/run_aws_boundary_validation.sh
```

Run the identifier/secret scan across the staged evidence. Expected: all checks pass and the scan is clean.

- [x] **Step 4: Inspect the exact staged delta**

Stage only the five files listed by this task. Confirm no account identifier or unrelated user file is staged and `git diff --cached --check` passes.

- [x] **Step 5: Commit the live proof**

```text
git add docs/validation/controlled-egress.md docs/validation/sqs-fair-queue.md docs/validation/aws-boundary-run.md docs/testing/aws-live-boundary-validation.tdd.md docs/superpowers/plans/2026-08-10-phase-1-funding-intelligence-concierge-mvp.md
git commit -m "test: record live AWS boundary validation"
```

- [x] **Step 6: Report the completion boundary**

Report the commit, exact verification counts, both live verdicts, clean teardown audit, and that only the Task 4/Task 5 live proof steps are complete. Remind the user to inspect AWS Billing the next day because billing data is delayed; do not claim a final exact charge until AWS reports it.
