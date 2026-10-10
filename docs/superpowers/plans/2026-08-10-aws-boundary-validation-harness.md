# AWS Boundary-Validation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Complete the local, test-first AWS validation harness for disposable Fargate network probes, bounded VPC Flow Log evidence, SQS fair-queue metrics, and reproducible reports without deploying or contacting AWS.

**Architecture:** Extend the existing CloudFormation template and the two existing validation scripts. `validate_controlled_egress.py` becomes a dual-mode controller/task probe, while `validate_sqs_fairness.py` retains its traffic trial and adds bounded CloudWatch metric collection; both write deterministic evidence to their current Markdown destinations.

**Tech Stack:** Python 3.12, boto3/botocore already locked by `uv`, pytest/pytest-cov, AWS CloudFormation, ECS/Fargate, CloudWatch Logs, VPC Flow Logs, SQS, S3, and Secrets Manager.

## Global Constraints

- Do not deploy, update, or delete AWS resources and do not make authenticated AWS calls during this implementation.
- Python remains `>=3.12,<3.13`; use the repository's existing `uv` environment.
- Add no dependency: use the Python standard library and existing boto3 only.
- Keep `scripts/validate_controlled_egress.py` and `scripts/validate_sqs_fairness.py` as the public commands; add no harness framework or provider abstraction.
- Require an immutable project worker-image URI through CloudFormation parameter `ProbeImage`.
- Keep live tests behind the existing `aws` marker and explicit environment variables.
- Never record credentials, secret values, authorization headers, or response bodies in logs or evidence.
- Checked-in validation documents must not claim an authenticated PASS until a separately authorized AWS run occurs.
- Achieve at least 80% line coverage across the two validation scripts with local substituted-boundary tests.
- Preserve unrelated user files and stage only files named by the active task.

## File Map

- Modify `infra/template.yaml`: add the disposable task resources, scoped permissions, validation resources, one-minute Flow Log aggregation, and outputs.
- Modify `scripts/validate_controlled_egress.py`: add task mode, Fargate controller mode, Flow Log matching/polling, and atomic evidence output.
- Modify `scripts/validate_sqs_fairness.py`: add the five fair-queue metric queries, bounded polling, AWS identity metadata, and atomic evidence output.
- Modify `tests/research/test_controlled_egress_validation.py`: unit and controller tests with substituted AWS/clock boundaries.
- Modify `tests/research/test_fairness_validation.py`: metric-query, polling, timeout, and evidence tests.
- Modify `tests/integration/test_controlled_egress.py`: opt-in full live controlled-egress assertion.
- Modify `tests/integration/test_sqs_fair_queue.py`: opt-in full live fair-queue assertion.
- Modify `docs/validation/controlled-egress.md`: exact future live command and honest not-run state.
- Modify `docs/validation/sqs-fair-queue.md`: exact future live command and honest not-run state.
- Create `docs/testing/aws-boundary-validation-harness.tdd.md`: actual RED/GREEN/coverage evidence from this implementation.

---

### Task 1: Define the Disposable Fargate Validation Resources

**Files:**
- Modify: `tests/research/test_controlled_egress_validation.py`
- Modify: `infra/template.yaml`
- Modify: `scripts/validate_controlled_egress.py`

**Interfaces:**
- Consumes: the existing validation VPC, private subnets, worker security group, queue, endpoints, and Flow Log group.
- Produces: CloudFormation parameter `ProbeImage`; logical resources `ValidationCluster`, `ProbeLogGroup`, `ProbeExecutionRole`, `ProbeTaskRole`, `ValidationBucket`, `ValidationSecret`, and `ProbeTaskDefinition`; outputs consumed by Task 3.

- [x] **Step 1: Write the failing infrastructure contract tests**

Replace `tests/research/test_controlled_egress_validation.py` with the existing resource-set test plus these exact assertions:

```python
from pathlib import Path

from scripts.validate_controlled_egress import REQUIRED_OUTPUTS, REQUIRED_RESOURCES
from scripts.validate_controlled_egress import required_outputs_present
from scripts.validate_controlled_egress import required_resources_present


def test_validation_requires_every_network_boundary_resource() -> None:
    assert required_resources_present(REQUIRED_RESOURCES)
    assert not required_resources_present(REQUIRED_RESOURCES - {"WorkerSecurityGroup"})


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
        "ValidationBucketName:",
        "ValidationSecretArn:",
    ):
        assert fragment in template
    assert "AWS::ECS::Service" not in template
```

- [x] **Step 2: Run the focused test and verify RED**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_controlled_egress_validation.py -q
```

Expected: collection fails because `REQUIRED_OUTPUTS` and `required_outputs_present()` do not exist.

- [x] **Step 3: Commit the validated RED checkpoint**

```text
git add tests/research/test_controlled_egress_validation.py
git commit -m "test: define AWS boundary infrastructure contract"
```

- [x] **Step 4: Add the output contract to the controlled-egress script**

Add the new resource IDs to `REQUIRED_RESOURCES`, define the output names, and keep both checks as set containment:

```python
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
    "ValidationBucket",
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
    "ValidationBucketName",
    "ValidationSecretArn",
}


def required_outputs_present(output_keys: set[str]) -> bool:
    return REQUIRED_OUTPUTS <= output_keys
```

- [x] **Step 5: Add the minimal CloudFormation resources**

Add this parameter before `Resources`:

```yaml
Parameters:
  ProbeImage:
    Type: String
    Description: Immutable URI of the tehsil-agent worker image used by the one-off probe
    AllowedPattern: "^.+@sha256:[0-9a-f]{64}$"
```

Add `MaxAggregationInterval: 60` to `VpcFlowLog.Properties`, then add these resources after `VpcFlowLog`:

```yaml
  ValidationCluster:
    Type: AWS::ECS::Cluster

  ProbeLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      RetentionInDays: 7

  ValidationBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true

  ValidationSecret:
    Type: AWS::SecretsManager::Secret
    Properties:
      GenerateSecretString:
        PasswordLength: 32
        ExcludePunctuation: true

  ProbeExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: {Service: ecs-tasks.amazonaws.com}
            Action: sts:AssumeRole
      Policies:
        - PolicyName: PullImageAndWriteProbeLogs
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: ecr:GetAuthorizationToken
                Resource: "*"
              - Effect: Allow
                Action:
                  - ecr:BatchCheckLayerAvailability
                  - ecr:GetDownloadUrlForLayer
                  - ecr:BatchGetImage
                Resource: "*"
              - Effect: Allow
                Action:
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: !Sub "${ProbeLogGroup.Arn}:*"

  ProbeTaskRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: {Service: ecs-tasks.amazonaws.com}
            Action: sts:AssumeRole
      Policies:
        - PolicyName: ProbeOnlyValidationResources
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: sqs:GetQueueAttributes
                Resource: !GetAtt ResearchQueue.Arn
              - Effect: Allow
                Action: s3:ListBucket
                Resource: !GetAtt ValidationBucket.Arn
              - Effect: Allow
                Action: secretsmanager:DescribeSecret
                Resource: !Ref ValidationSecret

  ProbeTaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      RequiresCompatibilities:
        - FARGATE
      NetworkMode: awsvpc
      Cpu: "256"
      Memory: "512"
      ExecutionRoleArn: !GetAtt ProbeExecutionRole.Arn
      TaskRoleArn: !GetAtt ProbeTaskRole.Arn
      ContainerDefinitions:
        - Name: boundary-probe
          Image: !Ref ProbeImage
          Essential: true
          Command:
            - python
            - scripts/validate_controlled_egress.py
            - --task-probe
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: !Ref ProbeLogGroup
              awslogs-region: !Ref AWS::Region
              awslogs-stream-prefix: boundary-probe
```

Append these outputs while retaining `ResearchQueueUrl`:

```yaml
  ProbeClusterArn:
    Value: !GetAtt ValidationCluster.Arn
  ProbeTaskDefinitionArn:
    Value: !Ref ProbeTaskDefinition
  WorkerPrivateSubnetAId:
    Value: !Ref WorkerPrivateSubnetA
  WorkerPrivateSubnetBId:
    Value: !Ref WorkerPrivateSubnetB
  WorkerSecurityGroupId:
    Value: !Ref WorkerSecurityGroup
  ProbeLogGroupName:
    Value: !Ref ProbeLogGroup
  FlowLogGroupName:
    Value: !Ref FlowLogGroup
  ValidationBucketName:
    Value: !Ref ValidationBucket
  ValidationSecretArn:
    Value: !Ref ValidationSecret
```

- [x] **Step 6: Run the focused test and verify GREEN**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_controlled_egress_validation.py -q
```

Expected: all infrastructure contract tests pass without contacting AWS.

- [x] **Step 7: Commit the GREEN checkpoint**

```text
git add infra/template.yaml scripts/validate_controlled_egress.py
git commit -m "feat: define disposable Fargate validation task"
```

### Task 2: Add the In-Container Boundary Probe

**Files:**
- Modify: `tests/research/test_controlled_egress_validation.py`
- Modify: `scripts/validate_controlled_egress.py`

**Interfaces:**
- Consumes: `public_url`, `queue_url`, `bucket`, `secret_arn`, boto3 clients, `validate_public_url()`, `fetch_official_source()`, and `socket.create_connection()`.
- Produces: `validate_https_probe_url(url) -> str`, `run_task_probe(public_url, *, queue_url, bucket, secret_arn) -> dict[str, object]`, and marker `PROBE_MARKER = "AWS_BOUNDARY_PROBE="`.

- [x] **Step 1: Write failing task-probe tests**

Append tests using only substituted external boundaries:

```python
from unittest.mock import Mock

import pytest

from apps.research.egress import FetchResult, ResolvedTarget
from scripts import validate_controlled_egress as harness


def test_probe_url_requires_plain_https_origin() -> None:
    assert harness.validate_https_probe_url("https://aws.amazon.com/") == "https://aws.amazon.com/"
    for value in ("http://aws.amazon.com/", "https://user:pass@example.com/", "file:///etc/passwd"):
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
        "fetch_official_source",
        lambda _url: FetchResult(_url, (), "text/html", b"ok"),
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
        "fetch_official_source",
        lambda _url: FetchResult(_url, (), "text/html", b"ok"),
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
```

- [x] **Step 2: Run the task-probe tests and verify RED**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_controlled_egress_validation.py -q
```

Expected: collection fails because `validate_https_probe_url()` and `run_task_probe()` do not exist.

- [x] **Step 3: Commit the validated RED checkpoint**

```text
git add tests/research/test_controlled_egress_validation.py
git commit -m "test: specify Fargate boundary probe behavior"
```

- [x] **Step 4: Implement task mode with existing egress validation**

Add imports for `socket`, `urlsplit`, `validate_public_url`, and
`fetch_official_source`, then add:

```python
from urllib.parse import urlsplit

from apps.research.egress import fetch_official_source, validate_public_url

PROBE_MARKER = "AWS_BOUNDARY_PROBE="
BLOCKED_TARGETS = (
    ("blocked_loopback", "127.0.0.1", 80),
    ("blocked_private", "10.255.255.1", 443),
    ("blocked_link_local", "169.254.1.1", 80),
    ("blocked_metadata", "169.254.169.254", 80),
)


def validate_https_probe_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("public probe URL must be an HTTPS origin without credentials")
    return url


def _check(
    name: str,
    operation: Callable[[], object],
    *,
    expect_failure: bool = False,
) -> dict[str, object]:
    try:
        operation()
    except Exception as error:
        return {
            "name": name,
            "passed": expect_failure,
            "error_type": type(error).__name__,
        }
    return {"name": name, "passed": not expect_failure, "error_type": None}


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
        _check("public_https", lambda: fetch_official_source(public_url)),
        *(
            _check(
                name,
                lambda host=host, port=port: socket.create_connection(
                    (host, port), timeout=2
                ).close(),
                expect_failure=True,
            )
            for name, host, port in BLOCKED_TARGETS
        ),
        _check("s3_endpoint", lambda: s3.head_bucket(Bucket=bucket)),
        _check(
            "sqs_endpoint",
            lambda: sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"]),
        ),
        _check(
            "secrets_endpoint",
            lambda: secrets.describe_secret(SecretId=secret_arn),
        ),
    ]
    return {
        "public_url": public_url,
        "public_destination_ips": list(target.addresses),
        "checks": checks,
        "passed": all(bool(check["passed"]) for check in checks),
    }
```

Catching `Exception` is intentional at this external probe boundary: every
error type is recorded and forces the corresponding check to fail unless
failure is the expected blocked-target result.

- [x] **Step 5: Add task-mode CLI arguments and one marked JSON line**

Use one mutually exclusive mode decision in `main()`:

```python
parser.add_argument("--task-probe", action="store_true")
parser.add_argument("--public-url", default="https://aws.amazon.com/")
parser.add_argument("--queue-url")
parser.add_argument("--bucket")
parser.add_argument("--secret-arn")
```

When `--task-probe` is set, require the queue, bucket, and secret arguments,
call `run_task_probe()`, print `PROBE_MARKER + json.dumps(result, sort_keys=True)`,
and return zero only when `result["passed"]` is true. Do not write repository
evidence from inside the container.

- [x] **Step 6: Run the task-probe tests and verify GREEN**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_controlled_egress_validation.py -q
```

Expected: all task-probe and infrastructure tests pass without network access.

- [x] **Step 7: Commit the GREEN checkpoint**

```text
git add scripts/validate_controlled_egress.py
git commit -m "feat: add in-container AWS boundary probe"
```

### Task 3: Launch the Task, Poll Flow Logs, and Write Controlled-Egress Evidence

**Files:**
- Modify: `tests/research/test_controlled_egress_validation.py`
- Modify: `tests/integration/test_controlled_egress.py`
- Modify: `scripts/validate_controlled_egress.py`
- Modify: `docs/validation/controlled-egress.md`

**Interfaces:**
- Consumes: all `REQUIRED_OUTPUTS`, ECS `RunTask`/`DescribeTasks`, probe CloudWatch logs, VPC Flow Logs, and STS identity.
- Produces: `parse_probe_events(events) -> dict[str, object]`, `flow_log_matches(message, *, source_ip, destination_ips) -> bool`, `poll_flow_logs(logs, *, log_group, start_time_ms, source_ip, destination_ips, timeout_seconds, poll_seconds) -> list[str]`, `run_fargate_probe(*, outputs, public_url, ecs, logs, task_timeout_seconds, flow_log_timeout_seconds, poll_seconds) -> dict[str, object]`, `run_validation(stack_name, *, public_url, task_timeout_seconds, flow_log_timeout_seconds, poll_seconds, cloudformation, ecs, logs, sts) -> dict[str, object]`, and atomic Markdown evidence.

- [x] **Step 1: Write failing parser, deadline, launch, and evidence tests**

Append focused tests with fake clients. The core assertions must be:

```python
from datetime import datetime, timezone


def test_probe_result_requires_exactly_one_marked_event() -> None:
    events = [
        {
            "message": harness.PROBE_MARKER
            + '{"passed": true, "public_destination_ips": ["54.239.28.85"], "checks": []}'
        }
    ]
    assert harness.parse_probe_events(events)["passed"] is True
    with pytest.raises(ValueError):
        harness.parse_probe_events([])
    with pytest.raises(ValueError):
        harness.parse_probe_events(events * 2)


def test_stack_outputs_fail_closed_when_an_output_is_missing() -> None:
    cloudformation = Mock()
    cloudformation.describe_stacks.return_value = {
        "Stacks": [{"Outputs": [{"OutputKey": "ProbeClusterArn", "OutputValue": "cluster"}]}]
    }
    with pytest.raises(ValueError, match="missing required outputs"):
        harness.stack_outputs("validation-stack", cloudformation)


def test_flow_log_match_requires_task_to_public_https_accept() -> None:
    record = "2 123 eni-1 10.50.10.8 54.239.28.85 49152 443 6 5 500 1 2 ACCEPT OK"
    assert harness.flow_log_matches(
        record,
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
    )
    assert not harness.flow_log_matches(
        record.replace(" ACCEPT ", " REJECT "),
        source_ip="10.50.10.8",
        destination_ips={"54.239.28.85"},
    )


def test_flow_log_polling_stops_at_deadline() -> None:
    logs = Mock()
    logs.filter_log_events.return_value = {"events": []}
    monotonic = Mock(side_effect=[0.0, 0.0, 2.0, 4.0])
    sleep = Mock()
    with pytest.raises(TimeoutError, match="Flow Log evidence unavailable"):
        harness.poll_flow_logs(
            logs,
            log_group="flow-logs",
            start_time_ms=0,
            source_ip="10.50.10.8",
            destination_ips={"54.239.28.85"},
            timeout_seconds=3,
            poll_seconds=2,
            monotonic=monotonic,
            sleep=sleep,
        )
    assert sleep.call_count == 2


def test_fargate_launch_fails_closed_on_ecs_placement_failure() -> None:
    ecs = Mock()
    ecs.run_task.return_value = {
        "tasks": [],
        "failures": [{"arn": "task-definition", "reason": "RESOURCE:ENI"}],
    }
    with pytest.raises(RuntimeError, match="RESOURCE:ENI"):
        harness.run_fargate_probe(
            outputs={
                "ProbeClusterArn": "cluster",
                "ProbeTaskDefinitionArn": "task-definition",
                "WorkerPrivateSubnetAId": "subnet-a",
                "WorkerPrivateSubnetBId": "subnet-b",
                "WorkerSecurityGroupId": "sg-1",
                "ProbeLogGroupName": "probe-logs",
                "FlowLogGroupName": "flow-logs",
                "ResearchQueueUrl": "queue-url",
                "ValidationBucketName": "bucket",
                "ValidationSecretArn": "secret",
            },
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
                        "details": [{"name": "privateIPv4Address", "value": "10.50.10.8"}],
                    }
                ],
                "containers": [{"exitCode": 0}],
            }
        ]
    }
    probe_logs = Mock()
    probe_logs.get_log_events.return_value = {
        "events": [
            {
                "message": harness.PROBE_MARKER
                + '{"passed": true, "public_destination_ips": ["54.239.28.85"], "checks": []}'
            }
        ]
    }
    monkeypatch.setattr(harness, "poll_flow_logs", lambda *_args, **_kwargs: ["matched"])

    result = harness.run_fargate_probe(
        outputs={
            "ProbeClusterArn": "cluster",
            "ProbeTaskDefinitionArn": "task-definition",
            "WorkerPrivateSubnetAId": "subnet-a",
            "WorkerPrivateSubnetBId": "subnet-b",
            "WorkerSecurityGroupId": "sg-1",
            "ProbeLogGroupName": "probe-logs",
            "FlowLogGroupName": "flow-logs",
            "ResearchQueueUrl": "queue-url",
            "ValidationBucketName": "bucket",
            "ValidationSecretArn": "secret",
        },
        public_url="https://aws.amazon.com/",
        ecs=ecs,
        logs=probe_logs,
        task_timeout_seconds=180,
        flow_log_timeout_seconds=600,
        poll_seconds=5,
    )

    request = ecs.run_task.call_args.kwargs
    assert request["launchType"] == "FARGATE"
    assert request["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"
    assert request["networkConfiguration"]["awsvpcConfiguration"]["subnets"] == [
        "subnet-a",
        "subnet-b",
    ]
    assert result["passed"] is True
    waiter.wait.assert_called_once()


def test_evidence_write_is_sorted_and_atomic(tmp_path) -> None:
    output = tmp_path / "controlled-egress.md"
    harness.write_evidence(output, "Controlled-egress validation", {"z": 1, "a": 2})
    assert output.read_text(encoding="utf-8") == (
        '# Controlled-egress validation\n\n```json\n{\n  "a": 2,\n  "z": 1\n}\n```\n'
    )
    assert not output.with_suffix(".md.tmp").exists()
```

- [x] **Step 2: Run the controller tests and verify RED**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_controlled_egress_validation.py -q
```

Expected: failures name the missing parser, polling, controller, and evidence functions.

- [x] **Step 3: Commit the validated RED checkpoint**

```text
git add tests/research/test_controlled_egress_validation.py
git commit -m "test: specify bounded Fargate and Flow Log evidence"
```

- [x] **Step 4: Implement output discovery and strict probe parsing**

Add these functions:

```python
def stack_outputs(stack_name: str, cloudformation: object) -> dict[str, str]:
    response = cloudformation.describe_stacks(StackName=stack_name)
    outputs = {
        item["OutputKey"]: item["OutputValue"] for item in response["Stacks"][0].get("Outputs", [])
    }
    if not required_outputs_present(set(outputs)):
        missing = sorted(REQUIRED_OUTPUTS - set(outputs))
        raise ValueError(f"stack is missing required outputs: {', '.join(missing)}")
    return outputs


def parse_probe_events(events: list[dict[str, object]]) -> dict[str, object]:
    marked = [
        str(event["message"])[len(PROBE_MARKER) :]
        for event in events
        if str(event.get("message", "")).startswith(PROBE_MARKER)
    ]
    if len(marked) != 1:
        raise ValueError(f"expected one probe result, found {len(marked)}")
    result = json.loads(marked[0])
    if not isinstance(result, dict) or not isinstance(result.get("passed"), bool):
        raise ValueError("probe result has invalid schema")
    addresses = result.get("public_destination_ips")
    checks = result.get("checks")
    if not isinstance(addresses, list) or not addresses or not isinstance(checks, list):
        raise ValueError("probe result is missing addresses or checks")
    return result
```

Type `cloudformation` with a small local `Protocol` only if strict typing is later enabled for `scripts`; do not add a provider abstraction.

- [x] **Step 5: Implement Flow Log parsing and bounded polling**

Use the documented default Flow Log field order:

```python
def flow_log_matches(
    message: str,
    *,
    source_ip: str,
    destination_ips: set[str],
) -> bool:
    fields = message.split()
    return (
        len(fields) >= 14
        and fields[3] == source_ip
        and fields[4] in destination_ips
        and fields[6] == "443"
        and fields[7] == "6"
        and fields[12] == "ACCEPT"
        and fields[13] == "OK"
    )


def poll_flow_logs(
    logs: object,
    *,
    log_group: str,
    start_time_ms: int,
    source_ip: str,
    destination_ips: set[str],
    timeout_seconds: int,
    poll_seconds: int,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        response = logs.filter_log_events(
            logGroupName=log_group,
            startTime=start_time_ms,
            filterPattern=f'"{source_ip}" "443" "ACCEPT"',
        )
        matches = [
            str(event["message"])
            for event in response.get("events", [])
            if flow_log_matches(
                str(event.get("message", "")),
                source_ip=source_ip,
                destination_ips=destination_ips,
            )
        ]
        if matches:
            return matches
        sleep(poll_seconds)
    raise TimeoutError("Flow Log evidence unavailable before deadline")
```

- [x] **Step 6: Implement the bounded Fargate controller**

`run_fargate_probe` takes keyword-only `outputs: dict[str, str]`, `public_url:
str`, `ecs: object`, `logs: object`, `task_timeout_seconds: int`,
`flow_log_timeout_seconds: int`, and `poll_seconds: int`, returning
`dict[str, object]`. `run_validation` takes `stack_name: str` plus the same URL
and limits and substituted CloudFormation, ECS, Logs, and STS clients, returning
the evidence dictionary. It validates live stack resources and outputs, calls
`run_fargate_probe()`, attaches STS/session/source metadata, and derives the
verdict from the returned proof.

`run_fargate_probe()` must:

1. Record the UTC start time and epoch milliseconds before `RunTask`.
2. Call `ecs.run_task()` with one Fargate task, both private subnets, the worker
   security group, and `assignPublicIp="DISABLED"`.
3. Override the `boundary-probe` command with all task-mode arguments.
4. Reject any `failures` or a response without exactly one task ARN.
5. Use the `tasks_stopped` waiter with `WaiterConfig={"Delay": poll_seconds,
   "MaxAttempts": max(1, task_timeout_seconds // poll_seconds)}`.
6. Describe the stopped task; require exit code zero and extract its private IPv4
   address from the ENI attachment.
7. Read log stream `boundary-probe/boundary-probe/<task-id>` and parse the single
   marked result.
8. Call `poll_flow_logs()` using the task address and recorded public addresses.
9. Return the task ARN, ENI address, exit code, task checks, matching Flow Log
   records, observation window, limits, and `passed=True`.

The exact task override is:

```python
command = [
    "python",
    "scripts/validate_controlled_egress.py",
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

Do not stop, delete, or deregister resources: the standalone task has already
stopped, and stack cleanup remains a separately authorized deployment operation.

- [x] **Step 7: Implement atomic evidence and controller CLI**

Add:

```python
def write_evidence(path: Path, title: str, payload: dict[str, object]) -> None:
    rendered = f"# {title}\n\n```json\n" + json.dumps(payload, indent=2, sort_keys=True) + "\n```\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)
```

Controller CLI arguments must include:

```text
--stack-name (required outside task mode)
--public-url (default https://aws.amazon.com/)
--task-timeout-seconds (default 180)
--flow-log-timeout-seconds (default 600)
--poll-seconds (default 5)
--output (default docs/validation/controlled-egress.md)
```

Controller mode creates CloudFormation, ECS, Logs, and STS clients only after
argument validation. Evidence includes `schema_version=1`, source revision from
`git rev-parse HEAD`, UTC generation time, STS account/ARN, boto3 session region,
stack identity, resolved outputs, the Fargate result, all configured limits, and
the overall verdict. Client, waiter, parse, or timeout errors must still produce
evidence with verdict `failed` or `evidence_unavailable`, then return non-zero.

- [x] **Step 8: Update the opt-in integration test and honest operator document**

Change `tests/integration/test_controlled_egress.py` so the existing environment
gate calls `run_validation()` and asserts `result["verdict"] == "passed"`. Keep
the `aws` marker and skip when `PHASE1_VALIDATION_STACK` is absent.

Update `docs/validation/controlled-egress.md` to retain the not-run statement and
document only this later command:

```text
uv run python -m scripts.validate_controlled_egress \
  --stack-name "$PHASE1_VALIDATION_STACK" \
  --output docs/validation/controlled-egress.md
```

- [x] **Step 9: Run focused tests and verify GREEN**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_controlled_egress_validation.py tests/integration/test_controlled_egress.py -q
```

Expected: local tests pass and the live integration test skips; no AWS client reaches the network.

- [x] **Step 10: Commit the GREEN checkpoint**

```text
git add scripts/validate_controlled_egress.py tests/integration/test_controlled_egress.py docs/validation/controlled-egress.md
git commit -m "feat: capture bounded Fargate egress evidence"
```

### Task 4: Capture the Five SQS Fair-Queue Metrics

**Files:**
- Modify: `tests/research/test_fairness_validation.py`
- Modify: `tests/integration/test_sqs_fair_queue.py`
- Modify: `scripts/validate_sqs_fairness.py`
- Modify: `docs/validation/sqs-fair-queue.md`

**Interfaces:**
- Consumes: queue URL/ARN/name, each trial's UTC window, CloudWatch `GetMetricData`, STS identity, and existing receipt-order results.
- Produces: `FAIR_QUEUE_METRICS`, `metric_queries(queue_name)`, `poll_fair_queue_metrics(cloudwatch, *, queue_name, started_at, ended_at, timeout_seconds, poll_seconds)`, per-trial metric evidence, and atomic Markdown output.

- [x] **Step 1: Write failing metric and evidence tests**

Replace the small fairness test with its existing threshold assertions plus:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from scripts import validate_sqs_fairness as harness


def test_quiet_tenant_must_arrive_before_noisy_threshold() -> None:
    assert harness.quiet_tenant_served_before(["A"] * 89 + ["B"], quiet="B", limit=90)
    assert not harness.quiet_tenant_served_before(["A"] * 90 + ["B"], quiet="B", limit=90)
    assert not harness.quiet_tenant_served_before(["A"] * 89, quiet="B", limit=90)


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
    started = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
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
    started = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
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
    started = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
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
```

- [x] **Step 2: Run the fairness tests and verify RED**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_fairness_validation.py -q
```

Expected: failures name `FAIR_QUEUE_METRICS`, `metric_queries()`, and `poll_fair_queue_metrics()`.

- [x] **Step 3: Commit the validated RED checkpoint**

```text
git add tests/research/test_fairness_validation.py
git commit -m "test: specify SQS fair-queue metric evidence"
```

- [x] **Step 4: Implement exact metric queries**

Add:

```python
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

FAIR_QUEUE_METRICS = (
    "ApproximateNumberOfNoisyGroups",
    "ApproximateNumberOfMessagesVisibleInQuietGroups",
    "ApproximateNumberOfMessagesNotVisibleInQuietGroups",
    "ApproximateNumberOfMessagesDelayedInQuietGroups",
    "ApproximateAgeOfOldestMessageInQuietGroups",
)


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
```

- [x] **Step 5: Implement bounded metric polling**

Add a function with this exact public signature:

```python
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
```

The body must query from `started_at - timedelta(minutes=1)` through
`ended_at + timedelta(minutes=1)`, map IDs `fair0` through `fair4` back to
`FAIR_QUEUE_METRICS`, pair every timestamp/value, reject negative values, and
return only after all five metrics contain at least one datapoint. Timestamp
strings must be normalized to UTC ISO 8601. Sleep between empty polls and raise
`TimeoutError("fair-queue metrics unavailable before deadline")` at the bound.

- [x] **Step 6: Attach metric windows to the existing trials**

Change `run_trial()` to accept an optional already-created SQS client and UTC
clock, record `started_at` immediately before sends and `ended_at` after the
executor exits, and return both timestamps as ISO strings with the existing
receipt result. Do not alter the 120/5 messages, one-second quiet-tenant delay,
12 pollers, 180-second receive deadline, or threshold 90.

`run_validation` takes `queue_url: str` plus keyword-only `trials: int`,
`metric_timeout_seconds: int`, `poll_seconds: int`, and substituted SQS,
CloudWatch, and STS clients, returning the complete evidence dictionary. Its
body follows this sequence, which `main()` calls after constructing the clients:

1. Create SQS, CloudWatch, and STS clients once.
2. Get `QueueArn` and derive the queue name from its final colon-delimited field.
3. Run all trials and preserve their UTC windows.
4. Poll the five metrics for each trial window.
5. Add the metric results to that trial.
6. Pass only when every receipt-order result passes and every trial has all five
   metric series.

- [x] **Step 7: Add atomic, reproducible SQS evidence**

Use the same six-line temporary-write/`Path.replace()` implementation as the
controlled-egress script, kept local to avoid creating a shared framework.
Evidence must contain schema version, Git revision, UTC generation time, STS
account/ARN, session region, queue URL/ARN/name, trial count, traffic constants,
polling limits, every trial result, and the overall verdict. Add CLI arguments:

```text
--metric-timeout-seconds (default 300)
--poll-seconds (default 15)
--output (default docs/validation/sqs-fair-queue.md)
```

- [x] **Step 8: Update the opt-in integration test and honest operator document**

Keep the existing queue environment gate and Standard/redrive assertions in
`tests/integration/test_sqs_fair_queue.py`, then call one-trial validation with a
temporary evidence path and assert the verdict passes. It remains marked `aws`
and skipped without `PHASE1_VALIDATION_QUEUE_URL`.

Update `docs/validation/sqs-fair-queue.md` to retain the not-run statement and
document this later command:

```text
uv run python -m scripts.validate_sqs_fairness \
  --queue-url "$PHASE1_VALIDATION_QUEUE_URL" \
  --trials 3 \
  --output docs/validation/sqs-fair-queue.md
```

- [x] **Step 9: Run focused tests and verify GREEN**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest tests/research/test_fairness_validation.py tests/integration/test_sqs_fair_queue.py -q
```

Expected: local metric tests pass and the live integration test skips; no AWS client reaches the network.

- [x] **Step 10: Commit the GREEN checkpoint**

```text
git add scripts/validate_sqs_fairness.py tests/integration/test_sqs_fair_queue.py docs/validation/sqs-fair-queue.md
git commit -m "feat: capture SQS fair-queue metric evidence"
```

### Task 5: Verify the Complete Harness and Preserve TDD Evidence

**Files:**
- Modify if formatting requires it: `infra/template.yaml`
- Modify if formatting requires it: `scripts/validate_controlled_egress.py`
- Modify if formatting requires it: `scripts/validate_sqs_fairness.py`
- Modify if correction requires it: focused tests from Tasks 1-4
- Create: `docs/testing/aws-boundary-validation-harness.tdd.md`

**Interfaces:**
- Consumes: all RED/GREEN commits and command output from Tasks 1-4.
- Produces: a locally verified harness, at least 80% script coverage, and a factual TDD evidence report; no authenticated AWS validation claim.

- [x] **Step 1: Run focused coverage without AWS tests**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest \
  tests/research/test_controlled_egress_validation.py \
  tests/research/test_fairness_validation.py \
  --cov=scripts.validate_controlled_egress \
  --cov=scripts.validate_sqs_fairness \
  --cov-report=term-missing \
  --cov-fail-under=80 \
  -q
```

Expected: all focused tests pass and combined line coverage is at least 80%.

- [x] **Step 2: Run the complete local suite with AWS tests excluded**

Run:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest -m "not aws" -q
```

Expected: all local tests pass; no AWS-marked test runs.

- [x] **Step 3: Prove live tests remain opt-in**

Run with both live environment variables absent:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest \
  tests/integration/test_controlled_egress.py \
  tests/integration/test_sqs_fair_queue.py \
  -q
```

Expected: both tests skip and no AWS request occurs.

- [x] **Step 4: Run repository static and Django checks**

Run each command independently:

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run mypy apps config
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run python manage.py check
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run python manage.py makemigrations --check --dry-run
```

Expected: every command exits zero with no new warnings.

- [x] **Step 5: Inspect the exact implementation delta**

Run:

```text
git diff --check 8a6516c..HEAD
git diff --stat 8a6516c..HEAD
git status --short
```

Expected: the diff contains only the plan's harness, tests, infrastructure,
validation documents, and TDD report; pre-existing unrelated untracked files
remain untouched.

- [x] **Step 6: Write the factual TDD evidence report**

Create `docs/testing/aws-boundary-validation-harness.tdd.md` with:

- source spec and plan links;
- user journeys for the validation operator and reviewer;
- a task table mapping Tasks 1-4 to their test target, RED commit/output, GREEN
  commit/output, and guaranteed behavior;
- the exact focused coverage command and measured percentage;
- the full local-suite, Ruff, Mypy, Django check, migration check, and live-skip
  commands with their actual outcomes;
- a clear statement that no AWS deployment or authenticated live validation ran;
- known gap: authenticated operability remains unverified until separately
  authorized deployment and probing.

Do not invent output excerpts or PASS claims; copy only results observed in this
execution.

- [x] **Step 7: Commit final evidence or corrective refactoring**

If no refactor was needed:

```text
git add docs/testing/aws-boundary-validation-harness.tdd.md
git commit -m "docs: record AWS boundary harness TDD evidence"
```

If focused corrections were required after GREEN, stage only those corrections,
their tests, and the evidence report, rerun Steps 1-4, then commit:

```text
git add infra/template.yaml scripts/validate_controlled_egress.py scripts/validate_sqs_fairness.py tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py tests/integration/test_controlled_egress.py tests/integration/test_sqs_fair_queue.py docs/testing/aws-boundary-validation-harness.tdd.md
git commit -m "refactor: finalize AWS boundary validation harness"
```

No step in this plan runs either live validation script or any AWS deployment command.
