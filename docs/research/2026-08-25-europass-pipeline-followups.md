# Europass render pipeline — deferred follow-ups

Produced while executing `docs/superpowers/plans/2026-08-25-europass-render-pipeline.md`
(commits `c867444..ce7da4a`). Every item below was raised by a review, triaged, and
deliberately **not** fixed in that work. The whole-branch review judged all of them
non-blocking for merge. Nothing here is a known-broken invariant; they are real but
bounded.

## Closed 2026-08-25 by `ac499e1`

- **The blank CV.** `EUROPASS_API` rendered a name and an email and nothing else, through
  seventeen commits and a full review. Two independent causes, either sufficient alone:
  `POST /eprofile/cv` stores no content sections (`PUT /eprofile/cv/{id}` is the write
  path), and `preference.profileStructure` — sent as `[]` — is the list of sections the
  renderer prints. Its keys are kebab-case section ids from the editor's own bundle;
  camelCase spellings are stored, echoed back on GET, and then ignored, so a wrong key
  fails exactly like an empty list.
- **The 204 that "would not reproduce."** The document office renders asynchronously.
  The first download after a render routinely answers 204 with no body and the PDF a
  moment later. It reproduces reliably; the earlier seven attempts happened to land
  after the render finished. `_call` raised on it, discarding good renders. Now
  `EuropassNotReady`, polled six times.
- **The canary asserted nothing about content.** It compared profile *key names* and
  provenance markers, both of which a blank document satisfies. It now renders through
  production's own path and fails unless the degree, the institution and the language
  are on the page.
- **The committed fixture was itself blank** and was the strongest available evidence of
  the bug the whole time — a post-create readback with every section empty. Refreshed
  from a written profile.

Still open below.

## Worth doing before the trigger is built

- **`render_and_store` passes no `constraints`**, so BINDING funder rules are never
  evaluated on the released artefact. Correct today (one caller), but the trigger spec
  must decide this explicitly rather than inherit it by omission.
- **Spec/code divergence on provenance failures.** The spec says a provenance failure
  goes to the DLQ *immediately*; the code lets SQS redeliver twice more, costing three
  europa.eu calls ~15 min apart for a failure no retry can fix. Either implement it
  (`delete_message` + explicit DLQ send — `sqs:DeleteMessage` is already granted) or
  amend the spec.
- **No `sqs:SendMessage` on `EuropassQueue` for any role.** Correct for an inert merge;
  add it alongside the trigger.
- **The stale-cache-row recovery will not fire in production.** `render_and_store`
  treats a missing S3 object as a cache miss by catching `KeyError`, which
  `S3ObjectStore.get` raises only for `NoSuchKey`. But `EuropassWorkerTaskRole` has no
  `s3:ListBucket`, and S3 answers `AccessDenied` rather than `NoSuchKey` for an absent
  object when the caller cannot list — so the recovery path is unreachable as deployed
  and those messages DLQ instead. Found by the security review of `c867444..64b5da8`;
  not a vulnerability (it fails closed), but a real defect. Fix is either granting
  `s3:ListBucket` on the bucket, scoped to the `tenants/*` prefix via a condition, or
  treating `AccessDenied` as a miss — the former, because the latter would hide a
  genuinely broken IAM policy, which is the trade `S3ObjectStore.get` already documents.

## Pre-existing bugs found, untouched

- ~~**`download_document` returns 500 instead of 404 for a missing artefact.**~~
  **FIXED** in `5f8e448`. Fixed at the store rather than the view: `S3ObjectStore.get`
  now raises `KeyError` for a missing object, which is the contract both callers and
  every dict-backed test double already assumed. `download_document` needed no change;
  `europass_render.py` dropped its error-code string matching.
- **No `AWS_REGION` on any ECS task definition.** `run_europass_worker --once` and
  `run_research_worker --once` both fail with `NoRegionError`; with a region supplied
  the command wires up correctly. Pre-existing across both workers, now inherited by a
  second service.
- **The test Postgres role is a superuser** (`tehsil`, `usesuper = True`, same in CI),
  so the default `django_db` connection bypasses RLS. Enforcement *is* covered, but only
  through the separate restricted `runtime_connection` fixture in
  `tests/tenancy/test_database_isolation.py` — ordinary tenant-scoped tests prove
  nothing about RLS.

## Test-quality gaps

- `_PRODUCTION_REQUIRED_ENV_VARS` is hand-maintained and cannot catch the next instance
  of the bug it was written for. `re.findall(r'os\.environ\["([^"]+)"\]', ...)` over
  `production.py` is a self-maintaining replacement.
- `_FAILURE_THRESHOLD` is not pinned from below — `CircuitOpen` also matches
  `EuropassUnavailable`, so a threshold of 2 passes the existing test identically.
- The 3600s clamp in `_retry_after_seconds` has no test; its other three branches do.
- No test pins cross-tenant rejection of the worker's draft lookup.
- `test_only_worker_task_role_consumes_the_research_queue` now overstates what it proves:
  a third role holds `ReceiveMessage`/`DeleteMessage` and the test never checks `Resource`.
- Untested template properties: `VisibilityTimeout`, log-group retention, the new alarms,
  and that the DLQ redrive targets `EuropassDeadLetterQueue` rather than the research DLQ.
- `test_the_europass_worker_is_never_autoscaled` keys on the logical name, so a
  `ScalableTarget` named otherwise but pointed at `service/.../europass-worker` passes.
  Assert on `ResourceId`.
- `tests/documents/test_run_europass_worker.py` patches the shared stdlib `time` module,
  replacing `time.sleep` process-wide for that test.

## Small cleanups

- `EuropassCanaryFailures` shares a log group with the worker, so a worker traceback
  increments it. Over-broad rather than silent, but the alarm name will mislead whoever
  is paged.
- `ecs:RunTask` lacks an `ecs:cluster` condition; the `events.amazonaws.com` trust policy
  lacks `aws:SourceArn`/`aws:SourceAccount`. Standard hardening, low impact here.
- `sqs:GetQueueAttributes` is granted but never called (mirrors `WorkerTaskRole`).
- `SQSClient` Protocol is duplicated byte-for-byte from `apps/research/queue.py:9-14`;
  `documents` already imports from `research`, so importing it would delete the copy.
- `AttributeNames=["ApproximateReceiveCount"]` is requested but never read.
- `apps/documents/models.py` has a function-local `from django.utils import timezone`
  with no circular-import reason; module-level `timezone` is already imported there.
- Tests still use `timezone.timedelta`, the construct the module abandoned for mypy.
- `_open_circuit` re-loads a row the caller already holds; `reason[:200]` guards nothing.
- `store_document`'s `DocumentStoreRefused` is a `ValueError` outside the
  `EuropassUnavailable` family and discards paid-for europa.eu bytes. Unreachable today.
- Inert `!Sub` on the canary `Input`; no `EuropassQueueUrl` Output (note `ResearchQueueUrl`
  is a plain Output, not an Export).

## The dependency this plan could not close

`EMPL-ELM-SUPPORT@ec.europa.eu` is still unwritten. The 2-second inter-call delay is an
estimate until they supply a real number. `EuropassQueueAgeAlarm` and the
`EuropassCallsTotal` metric are what make our volume answerable in that email.
