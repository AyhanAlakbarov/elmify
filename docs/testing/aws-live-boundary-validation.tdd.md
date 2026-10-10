# AWS live boundary validation: TDD evidence

Source plan: [AWS live boundary validation](../superpowers/plans/2026-08-11-aws-live-boundary-validation.md).

## RED/GREEN ledger

| Task | RED result | GREEN result |
| --- | --- | --- |
| Task 1: module entrypoints | `3 failed, 44 passed`; validation commands were not runnable through module entrypoints. | `47 passed`; both `python -m scripts.validate_controlled_egress --help` and `python -m scripts.validate_sqs_fairness --help` passed; `ruff check infra scripts tests` passed. |
| Task 2: private evidence construction | `4 failed`; evidence still risked carrying private AWS identifiers. | `48 passed`; `ruff check scripts tests` passed; follow-up direct-script documentation scan was clean. |
| Task 3: disposable run lifecycle | `6 failed`; the disposable AWS run controller did not exist. | `6 passed`; `bash -n scripts/run_aws_boundary_validation.sh` passed; `ruff check tests/test_aws_boundary_run_controller.py` passed. |

## Offline readiness

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run pytest -m "not aws" -q
```

Observed result: `96 passed, 2 deselected in 3.96s`.

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run ruff check .
```

Observed result: `All checks passed!`

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run mypy apps config
```

Observed result: `Success: no issues found in 54 source files`.

The repository CI and existing harness evidence scope mypy to `apps config`; the broader
draft-plan command `uv run mypy .` was not used as the release gate.

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run python manage.py check
```

Observed result: `System check identified no issues (0 silenced).`

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-offline uv run python manage.py makemigrations --check --dry-run
```

Observed result: `No changes detected`.

```text
bash -n scripts/run_aws_boundary_validation.sh
```

Observed result: exit `0`.

```text
sudo docker build --platform linux/amd64 --target web --tag tehsil-agent:aws-boundary-offline .
```

Observed result: the operator ran the local Docker build after the sudo prompt and reported it
complete. This Codex process did not inspect the image afterward because
`sudo -n docker image inspect tehsil-agent:aws-boundary-offline` returned
`sudo: a password is required`.

## Privacy scan

```text
rg -n '<prohibited AWS identifier patterns>' docs/validation
```

Observed result: exit `1` with no output; no prohibited identifier pattern was found.

## Authenticated read-only AWS preflight

```text
aws sts get-caller-identity --profile tehsil-sandbox --region eu-central-1 --query 'Account != null && Arn != null' --output text
```

Observed result: `True`.

```text
aws cloudformation validate-template --template-body file://infra/template.yaml --profile tehsil-sandbox --region eu-central-1 --query 'length(Parameters) >= `1` && length(Description) >= `1`' --output text
```

Observed result: `True`.

```text
AWS_PROFILE=tehsil-sandbox AWS_REGION=eu-central-1 bash scripts/run_aws_boundary_validation.sh --preflight-only
```

Observed result: exit `0` after printing `Preflight: validating identity, names, and region`.
This command made read-only AWS calls only and found no collision with the fixed stack,
repository, and log-group names.

```text
UV_CACHE_DIR=/tmp/tehsil-aws-live-debug uv run python -c '<boto3 STS boolean probe>'
```

Observed result after enabling the boto3 CRT extra: `True`. This proves the project
runtime can consume the AWS CLI login-profile credentials used by the validation modules.

## Failed live attempt

The first approved live controller attempt built and deployed the disposable resources, then
failed during controlled-egress validation with `MissingDependencyException`. The controller
still deleted the stack and ECR repository, and both the controller audit and a follow-up
`--cleanup-only` absence audit exited `0`. No SQS fairness probe ran in that attempt.

Root cause: the AWS CLI login profile required the boto3/botocore CRT extra inside the
project runtime. The dependency was updated before any retry.

The second approved live controller attempt reached both probe phases and deleted/audited
the disposable resources. Controlled egress passed, but the controller still failed because
two of three SQS trials served the quiet tenant after the arbitrary 90-message threshold.
The generated controlled-egress evidence also exposed a raw Flow Log record, so the failed
generated evidence was not retained as a committable artifact.

Root cause: the SQS probe was checking a stricter threshold than the starvation boundary
needed for Phase 1, and controlled-egress evidence kept raw identifiers that should only be
used internally for matching. The retry uses `NOISY_MESSAGES` as the quiet-tenant threshold
and records only a Flow Log match count.

The third approved live controller attempt passed controlled egress and all three SQS
receipt-order trials, then failed because CloudWatch did not publish all five fair-queue
metric series within the five-minute polling window. A follow-up read-only metric query
after teardown found all five series. The retry extends only the metric polling window to
15 minutes.

## Passed live retry

The approved live controller run passed both probes and its teardown audit. The generated
evidence records source revision `7b5afeb14e4de7420f29c892825b2dad1d754b9a` and contains
only allowlisted proof fields.

- Controlled egress passed: the Fargate probe passed and recorded one matching Flow Log.
- The SQS fair-queue probe passed all three trials and recorded all five fair-queue metrics
  for every trial.
- The run summary recorded passed probe, stack deletion, repository deletion, teardown, and
  absence-audit verdicts.
- A targeted identifier scan of `docs/validation` passed, followed by a successful
  `--cleanup-only` absence audit.

## Boundary

The real two-tenant SQS fairness probe and AWS network-boundary validation now have passing
live evidence. Billing data remains delayed, so this report makes no final cost claim.

## Post-run controller hardening

The controller now starts in its own process group, allowing its 30-minute watchdog to
terminate foreground image-publishing and stack-deployment commands as well as probes before
the exit trap performs cleanup. Evidence provenance now appends a SHA-256 fingerprint of the
tracked Git diff when the worktree is dirty, instead of claiming that `HEAD` alone identifies
the executed source.

These changes were verified by local TDD and offline checks only; no additional AWS run was
performed after the passing evidence above.

## Current-revision revalidation

Two separately approved preparatory attempts at revision
`b86cc207348ef4d229b8063d9f111bff34395ed5` failed before either live probe ran. The first
found Docker's default credential and Buildx state paths read-only; the second redirected that
state, deployed the disposable stack, then found uv's default cache path read-only. Both attempts
ran automatic cleanup, followed by independent zero-resource audits.

The separately approved final run used private temporary Docker and uv state. The tracked tree
was clean at launch. Controlled egress passed all eight checks and recorded one matching Flow
Log. All three SQS trials passed the approved starvation boundary with `85`, `83`, and `68`
noisy messages before the first quiet message; all five fair-queue metric series were present.

The temporary root CLI session expired while the controller waited for teardown, after stack
deletion but before repository deletion. After reauthentication, `--cleanup-only` exited `0` and
an independent audit found zero matching CloudFormation stacks, ECR repositories, non-deleted
NAT gateways, VPC endpoints, elastic IP addresses, validation log groups, and active ECS probe
clusters. Repository deletion occurred less than ten minutes after the first billable resource,
within the 30-minute operational limit. Billing data remains delayed, so no exact cost is claimed.

The probe-generated files themselves dirtied the tracked tree before later provenance snapshots.
Their final `source_revision` fields were reconciled to the clean launch revision above; no source
or infrastructure file changed during the run.
