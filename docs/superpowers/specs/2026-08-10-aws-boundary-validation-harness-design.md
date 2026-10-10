# AWS Boundary-Validation Harness Design

## Purpose

Complete the missing authenticated AWS validation path without deploying or
contacting AWS during implementation. The harness will prove that a disposable
Fargate task uses the intended network boundary, that the Standard SQS queue
exhibits observable fair-queue behavior, and that each result is preserved as
reproducible evidence.

Local tests must exercise every controller branch with substituted AWS clients.
Live tests remain opt-in through the existing `aws` pytest marker and explicit
environment configuration.

## Scope

The change extends the repository's existing validation seams:

- `infra/template.yaml`
- `scripts/validate_controlled_egress.py`
- `scripts/validate_sqs_fairness.py`
- their focused tests under `tests/research/` and `tests/integration/`
- `docs/validation/controlled-egress.md`
- `docs/validation/sqs-fair-queue.md`

There will be no new harness framework, provider abstraction, workflow service,
or evidence database. The two existing scripts remain the public commands and
the two existing Markdown files remain the canonical evidence locations.

## Infrastructure

`infra/template.yaml` will add one required `ProbeImage` parameter. The value is
the immutable URI of this repository's built worker image, ensuring that the
in-container probe and the controller use the same versioned code.

The disposable validation stack will contain:

- an ECS cluster;
- one Fargate task definition using `awsvpc` networking;
- a CloudWatch Logs group for probe output;
- an execution role limited to image pull and log delivery;
- a task role limited to the validation queue, validation bucket, and validation
  secret operations needed by the probe;
- a validation S3 bucket and Secrets Manager secret containing no sensitive
  production data;
- outputs for the cluster, task definition, private subnets, worker security
  group, task log group, validation queue, bucket, secret, and Flow Log group.

The controller will launch a standalone task with `assignPublicIp=DISABLED` in
the existing private subnets. It will not create an ECS service or leave a
running task. Standalone tasks are the native ECS mechanism for one-time work:
<https://docs.aws.amazon.com/AmazonECS/latest/developerguide/standalone-tasks.html>.

The VPC Flow Log will use a 60-second maximum aggregation interval. AWS notes
that records still require additional best-effort delivery time after capture,
so the controller must use an explicit polling deadline rather than assume
immediate availability:
<https://docs.aws.amazon.com/vpc/latest/userguide/flow-log-records.html>.

## Controlled-Egress Probe

`scripts/validate_controlled_egress.py` will support two modes in the same file:

1. Controller mode, invoked with `--stack-name`, discovers stack outputs,
   launches the standalone task, waits for it to stop, reads its structured log
   result, and polls Flow Logs.
2. Task mode, invoked by the task definition with `--task-probe`, performs the
   network and endpoint requests and emits one machine-readable result prefixed
   with a fixed marker.

Task mode will:

- require an HTTPS public probe URL and reject credentials or non-HTTPS input;
- resolve and record the public destination addresses;
- require successful HTTPS retrieval from the public destination;
- require connection failure for loopback, RFC 1918 private, link-local, and EC2
  metadata targets within per-attempt timeouts;
- call `HeadBucket`, `GetQueueAttributes`, and `DescribeSecret` against only the
  validation resources supplied to the task;
- record each assertion, destination, timing, and error category without
  recording credentials, secret values, response bodies, or authorization
  headers.

Controller mode will obtain the stopped task's ENI and private address, parse
the marked task result, and search the Flow Log group for an accepted TCP flow
from that ENI address to one of the recorded public destination addresses on
port 443. A matching record proves the public test connection was observed at
the configured VPC boundary.

Both ECS completion and Flow Log polling are bounded. Failure to start the task,
task timeout, non-zero container exit, missing structured output, failed task
assertion, or exhausted Flow Log deadline causes a non-zero harness result. An
exhausted Flow Log deadline is reported as `evidence_unavailable`, not as proof
that the traffic did not occur, because Flow Log delivery is best effort.

## SQS Fair-Queue Metrics

`scripts/validate_sqs_fairness.py` retains the existing traffic pattern and
three-trial default: 120 deliberately slow noisy-tenant messages, then five
quiet-tenant messages, consumed by 12 pollers. The receipt-order criterion also
remains unchanged: every trial must receive a quiet-tenant message before 90
noisy-tenant messages drain.

Each trial will record its UTC and monotonic start/end boundaries. After queue
activity, the script will issue bounded CloudWatch metric polling for the five
fair-queue metrics documented under the `AWS/SQS` namespace:

- `ApproximateNumberOfNoisyGroups`
- `ApproximateNumberOfMessagesVisibleInQuietGroups`
- `ApproximateNumberOfMessagesNotVisibleInQuietGroups`
- `ApproximateNumberOfMessagesDelayedInQuietGroups`
- `ApproximateAgeOfOldestMessageInQuietGroups`

The authoritative metric list and approximate semantics are documented by AWS:
<https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html>.

Every metric must provide at least one timestamped, non-negative datapoint in
the observation window while the queue is active. Approximate values are
recorded as observations; they are not treated as strict ordering guarantees.
The script fails when the receipt-order criterion fails, a metric is absent at
the polling deadline, or a datapoint is invalid.

## Evidence Format

Each script writes its existing Markdown evidence file, or a caller-supplied
`--output` path for tests and disposable runs. The Markdown contains one fenced,
sorted JSON document with:

- `schema_version`;
- source Git revision;
- generation timestamp in UTC;
- AWS partition, account, region, and stack or queue identity;
- immutable or resolved resource identifiers;
- exact non-secret probe inputs;
- UTC observation windows and polling limits;
- task ARN, ENI identity, container exit status, and individual probe results;
- matching Flow Log records reduced to the fields needed for the proof;
- per-trial receipt results and timestamped fair-queue metric datapoints;
- explicit assertion outcomes and an overall verdict.

Evidence is written through a sibling temporary file followed by `Path.replace()`
so interruption cannot leave a partially written report. Stable key ordering and
explicit schema versioning make runs comparable. Local tests may generate
fixture evidence in temporary directories, but the checked-in validation files
must never claim an authenticated PASS unless AWS was actually contacted under
explicit live-test configuration.

## Test Strategy

Implementation follows RED-GREEN-REFACTOR. Tests will precede each production
change and will mock only external AWS and clock boundaries.

Focused unit guarantees will cover:

- the expanded required CloudFormation resource set;
- private-subnet `RunTask` configuration with public IP assignment disabled;
- task-result parsing and rejection of malformed or incomplete results;
- public/blocked destination assertion aggregation;
- Flow Log tuple parsing, matching, deadline success, and deadline exhaustion;
- the exact five fair-queue metric queries;
- metric polling success, missing datapoints, negative datapoints, and timeout;
- deterministic evidence serialization and atomic replacement;
- exit status derived from all required assertions rather than partial success.

The existing integration tests remain marked `aws` and skip unless the validation
stack or queue variables are explicitly present. No local or CI test may infer
permission to deploy, create, update, or delete an AWS stack.

## Validation Commands

Local completion requires the repository's existing checks:

```text
uv run pytest tests/research/test_controlled_egress_validation.py tests/research/test_fairness_validation.py -q
uv run pytest -q
uv run ruff check .
uv run mypy apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

The AWS-marked integration tests must remain skipped locally. Running the live
scripts is a later, separately authorized operation after the disposable stack
and immutable `ProbeImage` are explicitly approved for deployment.

## Deliberate Omissions

- No unified `AwsBoundaryHarness` class or shared provider interface.
- No Lambda, Step Functions, EventBridge, daemon, or ECS service.
- No additional dependency beyond the repository's existing boto3 and standard
  library.
- No event-driven Flow Log processing or durable evidence database.
- No automated AWS deployment or cleanup in this implementation task.

Add orchestration only if validation becomes scheduled or spans multiple
providers. Add a durable evidence store only when retention, querying, or
attestation requirements exceed versioned repository reports.
