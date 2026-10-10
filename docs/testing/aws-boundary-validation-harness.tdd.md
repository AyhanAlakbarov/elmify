# AWS boundary validation harness: TDD evidence

Source specification: [AWS Boundary Validation Harness design](../superpowers/specs/2026-08-10-aws-boundary-validation-harness-design.md).
Implementation plan: [AWS Boundary Validation Harness plan](../superpowers/plans/2026-08-10-aws-boundary-validation-harness.md).

## Operator and reviewer journeys

The validation operator explicitly supplies an approved stack or queue identifier to an
AWS-gated integration test or validation command. The controlled-egress path validates
the HTTPS target, the disposable stack resources and outputs, private Fargate task
result, and VPC Flow Log evidence. The SQS path runs bounded trials and requires all
five documented fair-queue metric series. Both scripts write only deterministic evidence
and fail closed or label missing evidence as unavailable.

The reviewer can reproduce the local, substituted-boundary tests below. The integration
tests remain opt-in: absent `PHASE1_VALIDATION_STACK` and
`PHASE1_VALIDATION_QUEUE_URL` produce skips rather than AWS requests.

## Tasks 1–4 RED/GREEN ledger

| Task | Test target | RED commit and observed output | GREEN commit and observed output | Guaranteed behavior |
| --- | --- | --- | --- | --- |
| 1: disposable Fargate resources | `tests/research/test_controlled_egress_validation.py` | `ee01134` — import of `REQUIRED_OUTPUTS` failed during collection (1 collection error). | `ec9f841` — `3 passed in 0.06s`. | Required resource/output contracts, a private one-off Fargate definition, and its CloudFormation outputs exist. |
| 2: in-container probe | `tests/research/test_controlled_egress_validation.py` | `9ec1600` — `3` new probe tests failed and `3` prior tests passed (exit 1). | `cdb60fb` — `6 passed in 0.06s`. | Probe accepts only credential-free HTTPS URLs, expects private/metadata connections to fail, checks its allowed endpoints, and emits one marked JSON result. |
| 3: Fargate and Flow Log evidence | `tests/research/test_controlled_egress_validation.py`, `tests/integration/test_controlled_egress.py` | `60e28a1` — `6 passed, 7 failed in 0.11s`; failures named the missing controller/evidence functions. | `8c98104` — `13 passed, 1 skipped in 0.07s`; follow-up `6dc9e74` GREEN: `14 passed, 1 skipped in 0.07s`. | Controller requires all stack outputs, starts exactly one private Fargate task, bounds Flow Log polling at the deadline, records evidence atomically, and leaves the live test gated. |
| 4: SQS fairness metrics | `tests/research/test_fairness_validation.py`, `tests/integration/test_sqs_fair_queue.py` | `2131262` — `.FFFF`, `4 failed, 1 passed in 0.14s`; metric APIs were missing. | `7ae0ccc` — `5 passed, 1 skipped in 0.09s`. | Five fair-queue metric series are queried and bounded, negative values fail, evidence is atomic, and live queue validation remains gated. |

The RED/GREEN outputs above are copied from the Task 1–4 execution reports in
`.superpowers/sdd/2026-08-10-aws-boundary-validation-harness/`.

## Task 5 coverage closure

Additional local tests substitute CloudFormation, ECS, SQS, CloudWatch, STS, and CLI
sessions. They cover controlled-egress controller success/timeout and both CLI modes,
plus SQS validation success/timeout/client-failure, evidence writing, and CLI output.
No production code was changed.

Initial coverage run after Tasks 1–4 was RED: `19 passed` but combined coverage was
`51.45%`, below the required 80%. The first added closure set was still RED at `79.42%`.
The final command and observed output were:

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

| Module | Statements | Missed | Line coverage |
| --- | ---: | ---: | ---: |
| `scripts.validate_controlled_egress` | 184 | 25 | 86% |
| `scripts.validate_sqs_fairness` | 127 | 36 | 72% |
| Combined | 311 | 61 | **80.39%** |

Observed result: `28 passed in 0.34s`; the coverage gate reported
`Required test coverage of 80% reached. Total coverage: 80.39%`.

## Complete local verification

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest -m "not aws" -q
```

Observed result: `68 passed, 2 deselected in 3.87s`. `uv` also reported that the active
`VIRTUAL_ENV` path did not match this worktree's `.venv` and would be ignored. PostgreSQL
was available at `127.0.0.1:5432`; no AWS-marked test ran and no AWS request occurred.

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run pytest \
  tests/integration/test_controlled_egress.py \
  tests/integration/test_sqs_fair_queue.py \
  -q
```

Observed result: `2 skipped in 0.09s`. With both live environment variables absent,
the `aws`-marked tests skipped before making an AWS request.

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run ruff check .
```

Observed result: `All checks passed!`

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run mypy apps config
```

Observed result: `Success: no issues found in 54 source files`.

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run python manage.py check
```

Observed result: `System check identified no issues (0 silenced).`

```text
UV_CACHE_DIR=/tmp/tehsil-agent-uv-cache uv run python manage.py makemigrations --check --dry-run
```

Observed result: `No changes detected`. Django emitted a runtime warning while checking
migration history because PostgreSQL at `127.0.0.1:5432` refused the connection.

## Authenticated-operability boundary

No AWS deployment, authenticated AWS validation, or live validation script ran in this
execution. Authenticated operability remains unverified until separately authorized
deployment and probing in the approved validation account.
