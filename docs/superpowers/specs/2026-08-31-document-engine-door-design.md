# Document engine door — Design

**Date:** 2026-08-31
**Status:** Approved design, not yet implemented
**Type:** Subsystem — HTTP surface + async transport for the existing document engine

## Problem

`generate_cv`, `ingest_uploaded_cv`, `enqueue_europass_render` and `mark_ready` all
work, are tested, and have no caller outside tests. The engine is complete and
unreachable.

"Add a route" is not the fix, because the reachability problem is larger than it
reads:

- **There is no frontend.** Commit `451791e` (2026-08-20) deleted all 29 templates,
  `static/`, and `DESIGN.md` ahead of a React rebuild that was never specified.
  `config/settings/base.py:52` still points `DIRS` at a `templates/` directory that
  does not exist. Every existing view — `concierge/views.py:34` renders
  `counselor/dashboard.html` — resolves only against 12 **test-only** stubs wired in
  `config/settings/test.py`.
- **There is no API layer.** No DRF, no `JsonResponse` anywhere in `apps/`.
- **There is no login route.** Nothing includes `django.contrib.auth.urls`; no view
  calls `login()`. Session authentication has no way to begin.
- **There is no confirmation step.** Every fact writer sets `confirmed_by=None`
  (`ingestion.py:417`, `gaps.py:313`, `profile_bridge.py:106`), and
  `generatable_facts` filters on `confirmed_by__isnull=False` — but nothing in
  `apps/` ever sets it for a candidate. The product decision the CV work rests on
  ("the student's single click is the authorship record") has no code behind it.
- **There is no local-variant render path.** `render_and_store` refuses every
  variant except `EUROPASS_API` (`europass_render.py:100`, a deliberate choke
  point). `render_draft` produces an artefact for STANDARD / EUROPASS /
  GERMAN_TABULAR and nothing stores it.

This spec builds the smallest thing that makes the engine reachable end to end by a
real student, without deciding the presentation layer.

## Non-goals

- **No UI.** Not one template. The deliverable is JSON over HTTP.
- **No React.** The presentation layer stays undecided; this surface is what it will
  consume when it arrives.
- **No DRF.** Plain Django views returning `JsonResponse`. One dependency not added.
- **No motivation-letter engine.** Its seam is reserved below; the port is a separate
  spec.
- **No staff surface.** Login itself is role-neutral, but every document endpoint
  resolves `current_membership(request, Membership.Role.STUDENT)`, so a counselor
  session gets a 403 there and no staff-facing route is added.
  `approval_mode` defaults to `PER_DOCUMENT`
  (`models.py:178`), so the student approves their own document and the loop closes
  with student authentication alone. Staff login additionally needs an OTP-verify
  endpoint (`tenancy/middleware.py:36`) — separate work.
- **Not in scope from the remaining-work list:** unkeyed publications/awards/skills
  accuracy, date precision, drift re-measurement, the `gaps.answer_questions`
  free-text field, `_check_no_unexplained_gaps` silent pass, tailoring plan 4.

## Decisions

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Door shape | JSON endpoints, no UI | Restoring server-rendered templates re-adds what the repo just deleted; specifying React first blocks everything behind a much larger design. |
| Slice scope | Full loop: intake → generate → approve | Intake-only leaves `generate_cv` uncalled and costs a second pass through the same auth, tenancy and rate-limit plumbing. |
| Scan verdict transport | EventBridge → SQS → worker | Polling the S3 tag needs a `quarantine/` grant to `WebTaskRole` that `template.yaml:930` explicitly refuses. An HTTP webhook adds a public trust boundary needing shared-secret auth and replay protection, for no gain. |
| Generation execution | Queue + worker | Gunicorn runs with no `--timeout` override (`Dockerfile:41`), so the default 30s sync worker times out on one or two model calls capped at 20,000 output tokens. Raising the timeout parks a sync worker for up to 90s per student. |
| Job-state model | **None** | See "What was cut" below. |

## Architecture

Two tiers. Nothing new in the middle.

```
  student                     web tier (JsonResponse)                 worker tier
  -------                     -----------------------                 -----------
  POST /api/auth/login  ---->  authenticate + login, CSRF cookie
  POST .../uploads      ---->  register() -> presigned POST
      |                                                     S3 quarantine/
      +---- direct POST to S3 ------------------------------------> |
                                                                   v
                                             GuardDuty tags -> EventBridge
                                                                   |
                                                          DocumentScanQueue
                                                                   |
                                        apply_scan_result + ingest_uploaded_cv
                                                                   |
  GET .../uploads/<id>  ---->  {state, scan_result}   <-------------+
  GET .../facts/candidates -> confirmed_by IS NULL
  POST .../facts/confirm ---> confirm_facts()
  POST .../generate     ---->  pre-flight, then enqueue --> DocumentQueue
                                                                   |
                                              generate_cv -> create_draft
  GET .../drafts/<id>   ---->  content + verdicts_for()  <----------+
  POST .../drafts/<id>/approve -> mark_ready, then enqueue -> DocumentQueue
                                                                   |
                          EUROPASS_API -> enqueue_europass_render --+
                          otherwise    -> render_draft + store_document
                                                                   |
  GET /documents/<draft>/<file> (exists already)  <-----------------+
```

### Web tier — `apps/documents/api.py`

Session + CSRF authentication, Django's own. Ten endpoints, all `kind`-parameterised
rather than CV-named so the letter engine widens a validation set instead of adding
routes.

| Route | Behaviour |
|---|---|
| `POST /api/auth/login` | `authenticate` + `login`; `@ensure_csrf_cookie`. |
| `POST /api/auth/logout` | `logout`. |
| `POST /api/documents/uploads` | `concierge.documents.register()` then a presigned POST scoped to the derived key. Returns `{document_id, url, fields}`. |
| `GET /api/documents/uploads/<id>` | `{state, scan_result}`. The poll target. |
| `GET /api/documents/facts/candidates` | Unsuperseded facts with `confirmed_by IS NULL`, caller's ledger only. |
| `POST /api/documents/facts/confirm` | `{fact_ids: [...]}` → `confirm_facts()`. Returns the count confirmed. |
| `POST /api/documents/generate` | `{kind}`. Runs the pre-flight checks, enqueues, returns 202. |
| `GET /api/documents/drafts` | `?kind=` — id, version and status, newest first. This is how the client learns a generation finished. |
| `GET /api/documents/drafts/<id>` | Draft content plus `verdicts_for(draft)`. |
| `POST /api/documents/drafts/<id>/approve` | `mark_ready`, then enqueue a render. 202. |

**`GET /api/documents/uploads/<id>` is not optional.** It is tempting to let the
candidates list stand in for it, but `ingest_uploaded_cv` returns `()` when extraction
fails, so without this endpoint `BLOCKED` (malware found) is indistinguishable from
"nothing extracted". A student who uploaded an infected file has to be told.

**Pre-flight on `generate` is what replaces a job-state table.** `generate_cv`'s own
first three checks are all cheap — `IdentityNotConfirmed` (indexed read),
`ApplicationEmailMissing` (field read), `GenerationRateLimited` (cache read). The
endpoint runs the same three and returns 409/429 synchronously, so every *predictable*
failure is visible at request time. What stays asynchronous is model refusal and
`GenerationFailure`, which are rare and land in the dead-letter queue that the
existing `EuropassDeadLetterQueue` alarm pattern already covers.

### Worker tier — one task, two queues

`run_document_worker` mirrors `run_europass_worker.py` and calls `consume_once` against
both queues in its loop.

**`DocumentScanQueue`** — target of an EventBridge rule on GuardDuty's object scan
result. Handler:

1. Locate the `DocumentVersion` **by `object_key`**, never by an id read out of the
   event. An event for an unknown key is logged and the message deleted — otherwise it
   redelivers forever.
2. `apply_scan_result(document, status)`. The five GuardDuty statuses map exactly onto
   the existing `_SCAN_STATES` table in `concierge/documents.py:27`.
3. On `AVAILABLE`, call `ingest_uploaded_cv`, guarded for idempotency: skip when
   `VerifiedFact.objects.filter(student=..., source_ref=f"upload:{document.id}")`
   already exists. SQS delivery is at-least-once, and without this a redelivery
   duplicates every candidate fact.

**`DocumentQueue`** — our own messages, identifiers only, never content (the rule
`EuropassRenderMessage`'s docstring states: a queue is a durable store with its own
retention policy, so a second copy of a student's personal data must not live there).
Two kinds:

- `generate` → `generate_cv` → `create_draft`.
- `render` → resolve the effective variant; `EUROPASS_API` hands off to
  `enqueue_europass_render` (that queue is single-worker and pinned for the circuit
  breaker and europa.eu courtesy rate — it must not be bypassed), anything else calls
  `render_draft` + `store_document`.

Rendering stays worker-side because `render.py:766` records the decision explicitly:
*"now that the only caller is the single pinned Europass worker, one process is exactly
the right scope… Do not add a shared cache for this."* The web tier must not call
`render_draft`.

### Variant resolution

`render_draft` computes `draft.render_variant or select_render_variant(programme,
funding_opportunity)` internally, and the worker needs the same answer *before* it
decides which queue to use. Extract that expression as a public `resolve_variant(draft)`
in `render.py` and call it from both places rather than duplicating it.

`europass_render.py:104` asks for a related reconciliation — that `create_draft` should
persist the resolved variant. **Deliberately not done here.** `create_draft` accepts
`programme` but not `funding_opportunity`, so persisting a variant at creation time
would only be half-correct. Recorded as a follow-up, not smuggled into this change.

## New and changed code

No new models. No migrations.

| File | Change |
|---|---|
| `apps/documents/api.py` | New, ~240 lines — the ten endpoints |
| `apps/documents/confirmation.py` | New, ~30 — `confirm_facts(*, student: Membership, fact_ids: Iterable[UUID], actor: Membership) -> int` |
| `apps/documents/document_queue.py` | New, ~90 — both message models, `consume_once` |
| `apps/documents/document_worker.py` | New, ~90 — both handlers |
| `apps/documents/management/commands/run_document_worker.py` | New, ~35 |
| `apps/documents/urls.py` | +10 routes |
| `apps/concierge/documents.py` | `presigned_upload()`, ~20 — beside `register()`, whose docstring already names this as the intended caller |
| `apps/documents/render.py` | Extract `resolve_variant(draft)` |
| `config/settings/{base,production}.py` | `DOCUMENT_QUEUE_URL`, `DOCUMENT_SCAN_QUEUE_URL` |
| `infra/template.yaml` | 2 queues + 2 DLQs + age alarms, 1 EventBridge rule, `DocumentWorkerTaskDefinition` + role |

`confirm_facts` gets its own module rather than being folded into a neighbour: small
focused modules are this app's idiom (`entry_selection.py` is 17 lines), and both the
API and the future letter engine call it.

## Trust boundaries

Each of these gets a test; none of them is a place to be lazy.

- **Presigned POST conditions** pin the **exact key** (equality, not `starts-with`), a
  content-length ceiling, and a short expiry. The key is derived by `register()` from
  the row it creates, so a caller cannot aim an upload outside its own tenant prefix.
- **`confirm_facts` resolves ids through `student=membership`**, never by id alone. A
  fact id belonging to another student must 404 — not 403, matching
  `storage.py:100`'s convention that a 403 confirms the object exists.
- **The scan handler trusts only the object key**, which we derived. Nothing else in
  the EventBridge event influences which row is written.
- **Ingestion idempotency** as described above, because delivery is at-least-once.
- **Login is rate-limited** on a stable integer derived from the submitted username
  (`rate_limited` accepts `UUID | int`), since there is no actor id before
  authentication.
- **`rate_limited()` on upload issuance, confirm, and generate** — the existing
  fixed-window limiter, no new one.

### Known ceilings

- `apps/ratelimit.py` carries its own `ponytail:` note: `django.core.cache` is
  per-process `LocMemCache` and no `CACHES` backend is configured, so every limit is
  per web task. This spec adds call sites to a pre-existing condition and does not fix
  it. Fixing it is a shared cache backend, and it should be its own change.
- **One worker task holds both roles.** `DocumentWorkerTaskRole` needs `quarantine/*`
  read (scan and ingest) *and* `tenants/*` write (render and store) — the shape
  `WorkerTaskRole` already has. Splitting into two task definitions is stricter and is
  the named upgrade path. `# ponytail: one worker holds both grants; split the task
  definition if the scan path ever needs to run untrusted code.`
- **A third copy of the SQS idiom.** `apps/research/queue.py` and
  `europass_queue.py` are already two, and `europass_queue.py`'s docstring records that
  duplication as the deliberate choice. Refactoring two production queues to share a
  base is a larger, riskier diff than 90 copied lines. `# ponytail: third copy;
  extract a shared consume_once if a fourth queue appears.`

## The EventBridge event — verified, not inferred

Confirmed 2026-09-01 against
`docs.aws.amazon.com/guardduty/latest/ug/monitor-with-eventbridge-s3-malware-protection.html`,
which publishes verbatim samples for all five scan result statuses.

**Rule pattern:**

```json
{"detail-type": ["GuardDuty Malware Protection Object Scan Result"],
 "source": ["aws.guardduty"]}
```

**The three field paths the handler reads:**

| Value | Path |
|---|---|
| Bucket name | `detail.s3ObjectDetails.bucketName` |
| Object key | `detail.s3ObjectDetails.objectKey` |
| Scan result | `detail.scanResultDetails.scanResultStatus` |

**`_SCAN_STATES` (`concierge/documents.py:27`) is already correct.** Its five keys —
`NO_THREATS_FOUND`, `THREATS_FOUND`, `UNSUPPORTED`, `ACCESS_DENIED`, `FAILED` — are
exactly the five `scanResultStatus` values AWS documents, each with its own sample
event. No change is needed there.

**Do not read `detail.scanStatus`.** It is a *different* field with a different
vocabulary — `COMPLETED` / `SKIPPED` / `FAILED` — describing whether the scan ran, not
what it found. `SKIPPED` there corresponds to `UNSUPPORTED` or `ACCESS_DENIED` in
`scanResultStatus`, and `FAILED` appears in both with different meanings. Reading the
wrong one collapses "password-protected file" and "access denied" into a single
indistinguishable state.

**Required guard.** `apply_scan_result` does `_SCAN_STATES[result]`, which raises
`KeyError` on any value AWS adds later. The handler must validate the status against
the map *before* calling, and treat an unrecognised value as `REVIEW_REQUIRED` with a
log line. Without this, one unknown status crashes the handler, the message redelivers,
and the queue wedges until the DLQ catches it.

Key encoding is not a concern here: the keys we derive are
`quarantine/{tenant_uuid}/{document_uuid}`, hex and slashes only, so there is no
percent-encoding ambiguity to resolve.

**Fixture** — `tests/documents/fixtures/guardduty_scan_result.json`. This is the AWS
sample with its `{{...}}` placeholder braces removed and the key replaced by one of
ours; the parser tests drive off it, one variant per `scanResultStatus`.

```json
{
    "version": "0",
    "id": "72c7d362-737a-6dce-fc78-9e27a0171419",
    "detail-type": "GuardDuty Malware Protection Object Scan Result",
    "source": "aws.guardduty",
    "account": "111122223333",
    "time": "2024-02-28T01:01:01Z",
    "region": "us-east-1",
    "resources": ["arn:aws:guardduty:us-east-1:111122223333:malware-protection-plan/b4c7f464ab3a4EXAMPLE"],
    "detail": {
        "schemaVersion": "1.0",
        "scanStatus": "COMPLETED",
        "resourceType": "S3_OBJECT",
        "s3ObjectDetails": {
            "bucketName": "test-evidence-bucket",
            "objectKey": "quarantine/00000000-0000-0000-0000-0000000000a1/00000000-0000-0000-0000-0000000000b2",
            "eTag": "ASIAI44QH8DHBEXAMPLE",
            "versionId": "d41d8cd98f00b204e9800998eEXAMPLE",
            "s3Throttled": false
        },
        "scanResultDetails": {
            "scanResultStatus": "NO_THREATS_FOUND",
            "threats": null,
            "statusReasons": null
        }
    }
}
```

`threats` and `statusReasons` are `null` rather than absent on a clean scan, and
populated on `THREATS_FOUND` / `UNSUPPORTED` / `ACCESS_DENIED` respectively — the
parser must tolerate both shapes. Neither field is read by this design; only the three
paths in the table above are.

**Deliberately not subscribed:** `GuardDuty Malware Protection Post Scan Action Failed`
(tagging failed) and the three `Resource Status` events. We read the verdict from the
event, never from the object tag, so a tagging failure does not affect this path.

## Testing

Following the existing patterns — fake SQS client, fake object store, pytest-django,
one test module per new module.

- Presign: conditions pin the exact key, the size ceiling and the expiry.
- `confirm_facts`: confirms the caller's candidates; another student's fact id 404s;
  an already-confirmed or superseded fact is a no-op.
- `generate`: each pre-flight failure returns its status **and enqueues nothing**; the
  success path enqueues exactly one message.
- Scan handler: all five GuardDuty statuses map to the right state; only `AVAILABLE`
  triggers ingestion; a redelivered message does not duplicate facts; an unknown
  object key is dropped rather than redelivered.
- Render handler: `EUROPASS_API` enqueues and stores nothing itself; a local variant
  stores under the draft's own key.
- `approve`: `ApprovalBlocked` returns 409 with the blocking verdicts and enqueues
  nothing.
- Cross-tenant isolation for every id-addressed endpoint.

## Reserved for the motivation-letter engine

Not built here. The seams that keep the port from needing new infrastructure:

- Endpoints take `kind`, and `DocumentDraft.Kind` already has `MOTIVATION_LETTER` and
  `CORE_NARRATIVE` — the port widens the accepted set in one place.
- `DocumentQueue`'s message carries `kind`; the worker dispatches on it. The letter
  engine adds a branch, not a queue, not a task definition, not an alarm.
- `confirm_facts` is engine-level, not CV-level, so the letter path reuses it.

For the record, since it drives that spec's shape: the branch
`claude/phase2-motivation-letter-engine` cannot be merged. It forked at `551718e`
(2026-08-23), **before** the documents app existed, and master has 422 commits since;
the branch carries its own parallel `approval.py`, `generation.py`, `ingestion.py`,
migrations `0001–0010`, and the root `templates/`+`static/` tree that was deliberately
deleted. What is genuinely unique is small and portable: nine modules (~1,600 lines),
two model deltas (`NarrativeInput`, `RevisionRequest.advice_shown`), the funding-side
`ApplicationPrompt` and its loader, two templates, and ~2,900 lines of tests. Master's
models are otherwise a superset of the branch's, so the port does not decay while it
waits. It is a port onto current models, not a merge.

## What was cut, and why

Recorded so the smaller shape is not mistaken for an oversight.

- **`GenerationRequest` job model and its two migrations.** Justified originally by
  "the client cannot tell running from failed"; killed by the observation that every
  predictable failure is a cheap synchronous check. A job-state table for a case no
  frontend exists to render is scaffolding for later. Add it when a frontend actually
  renders "generation failed".
- **`GET /api/documents/requests/<id>`**, which went with it.
- **A second transport module.** Scan and work messages share
  `document_queue.py`; the EventBridge envelope is a second Pydantic model, not a
  second file.
- **Inline rendering in the approve request** — proposed, then withdrawn.
  `render.py:766` forbids the web tier from calling `render_draft`, and a 1-second
  weasyprint run is not a good enough reason to contradict a recorded decision.
