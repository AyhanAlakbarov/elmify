# Document engine door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the finished-but-unreachable document engine a JSON door, so a real student can log in, upload a CV, confirm what it said, generate a document and approve it — with generation and rendering executed on a worker.

**Architecture:** Two tiers and nothing new in the middle. A web tier (`apps/documents/api.py`, plain Django views returning `JsonResponse`, session + CSRF auth) issues presigned S3 uploads, reads state, confirms facts, and *enqueues* work. A worker tier (`run_document_worker`) drains two SQS queues in one loop: `DocumentScanQueue` carries GuardDuty's object-scan verdict via EventBridge and triggers ingestion; `DocumentQueue` carries our own identifier-only messages and runs `generate_cv` → `create_draft` or resolves a render variant and either hands off to the pinned Europass worker or renders locally and stores.

**Tech Stack:** Django 5, Postgres + RLS, pydantic v2, boto3/SQS/S3, pytest + pytest-django, uv, CloudFormation.

**Spec:** `docs/superpowers/specs/2026-08-31-document-engine-door-design.md` — read it before Task 1. This plan implements it in full; where it makes a decision the spec left open, the task says so in the box marked **Spec gap**.

## Global Constraints

- **No UI, no template, no HTML, no React, no DRF.** The deliverable is JSON over HTTP from plain Django views. Do not add a dependency; do not create a `templates/` directory; do not touch `config/settings/base.py:52`'s `DIRS`.
- **No new models and no migrations.** `uv run python manage.py makemigrations --check --dry-run` must report no changes at every commit.
- **Every document endpoint resolves `current_membership(request, Membership.Role.STUDENT)`** and passes that membership into the service call — the check and the argument are the same object, so no view can pass the check and then write to another ledger. A counselor session gets 403 on every document endpoint. There is no staff surface in this change.
- **Queue messages carry identifiers only, never content.** Same rule and same reason as `EuropassRenderMessage`: a queue is a durable store with its own retention policy.
- **The web tier never calls `render_draft`, `render_cv`, `generate_cv` or `ingest_uploaded_cv`.** `apps/documents/render.py:764-769` records that decision; the web tier enqueues.
- **The worker never bypasses `EuropassQueue`.** A draft resolving to `EUROPASS_API` is handed to `enqueue_europass_render`; that queue is single-worker and pinned for the circuit breaker and the europa.eu courtesy rate.
- **Refusals on id-addressed endpoints are 404, never 403** — matching `apps/documents/storage.py:100`'s convention that a 403 confirms the object exists. (403 is reserved for "you are not a student here", which reveals nothing about any object.)
- Rate limiting uses `apps.ratelimit.rate_limited` — the existing fixed-window limiter. Do not write a second one. Its known ceiling (`LocMemCache`, per-process) is pre-existing and explicitly **not** fixed here.
- Commit convention: conventional commits, subject in the imperative, body explains *why*.
- Worktree: `/home/orkhan/Desktop/tehsil-door`, branch `claude/document-engine-door` (head `f0e19fe`). Commit with `git -C /home/orkhan/Desktop/tehsil-door` — a bare `git` from the parent directory lands on the wrong branch.
- Validation gate, all of which must pass before the branch is done:
  - `POSTGRES_DB=tehsil_door uv run pytest`
  - `uv run ruff check .` (**there is no `ruff format` in this repo — do not run it**)
  - `uv run mypy apps config`
  - `uv run bandit -c pyproject.toml -r apps config`
  - `uv run python manage.py makemigrations --check --dry-run`
- The test database name is per-worktree. Always prefix pytest with `POSTGRES_DB=tehsil_door`; the shared `test_tehsil` wedges across parallel sessions.

## File Structure

| File | Responsibility |
|---|---|
| `apps/documents/api.py` *(create)* | The ten endpoints. The only module in this change that knows about HTTP. Imports services; contains no domain logic. |
| `apps/documents/confirmation.py` *(create)* | `confirm_facts` — the candidate→confirmed transition. Its own module because both the API and the future letter engine call it, and small focused modules are this app's idiom (`entry_selection.py` is 17 lines). |
| `apps/documents/document_queue.py` *(create)* | Both message models and the SQS transport for both queues. One module, two queues — the EventBridge envelope is a second Pydantic model, not a second file. |
| `apps/documents/document_worker.py` *(create)* | Both handlers. Worker-side only. |
| `apps/documents/management/commands/run_document_worker.py` *(create)* | Drains both queues in one loop. |
| `apps/documents/urls.py` *(modify)* | +10 routes under `api/`. |
| `apps/documents/render.py` *(modify)* | Extract `resolve_variant(draft)`; `render_draft` calls it. |
| `apps/concierge/documents.py` *(modify)* | `presigned_upload()`; `_SCAN_STATES` → public `SCAN_STATES`; `apply_scan_result` stops raising `KeyError` on an unknown status. |
| `config/settings/base.py`, `config/settings/production.py` *(modify)* | `DOCUMENT_QUEUE_URL`, `DOCUMENT_SCAN_QUEUE_URL`. |
| `infra/template.yaml` *(modify)* | 2 queues + 2 DLQs + age/DLQ alarms, 1 EventBridge rule + queue policy, `DocumentWorkerTaskDefinition`/`Role`/`Service`/`LogGroup` + metric filter, `WebTaskRole` gains `s3:PutObject` on `quarantine/*` only, every task definition gains the two new queue URLs. |
| `tests/documents/fixtures/guardduty_scan_result.json` *(create)* | The AWS sample event, one of our keys substituted. |
| `tests/documents/test_confirmation.py`, `test_document_queue.py`, `test_document_worker.py`, `test_run_document_worker.py`, `test_api.py` *(create)* | One test module per new module, as the app already does. |
| `tests/concierge/test_documents.py`, `tests/documents/test_render.py`, `tests/infra/test_template.py` *(modify)* | Cover the modified functions and the changed trust boundary. |

---

### Task 1: `resolve_variant` — one answer to "which variant is this draft?"

The worker must know whether a draft is `EUROPASS_API` **before** it picks a queue. `render_draft` computes that inline today; two copies of the expression is how the worker and the renderer end up disagreeing.

**Files:**
- Modify: `apps/documents/render.py:761-763`
- Test: `tests/documents/test_render.py`

**Interfaces:**
- Consumes: `apps.documents.render.select_render_variant(program, opportunity) -> str`; `apps.documents.models.DocumentDraft` (fields `render_variant`, `programme`, `funding_opportunity`).
- Produces: `resolve_variant(draft: DocumentDraft) -> str`. Task 6's render handler calls it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_render.py`:

```python
def test_resolve_variant_prefers_the_stored_variant():
    """A draft that recorded its variant is not re-derived: a programme's
    requirement may have changed since the draft was approved, and the
    artefact must match the document the student consented to."""
    assert resolve_variant(DocumentDraft(render_variant="EUROPASS_API")) == "EUROPASS_API"


def test_resolve_variant_falls_back_to_the_selector_when_blank():
    """Blank is the create_draft default, so this is the common case, not the
    edge one: with no programme and no funder the selector answers STANDARD."""
    assert resolve_variant(DocumentDraft(render_variant="")) == "STANDARD"
```

Add `resolve_variant` to the `apps.documents.render` import block at the top of the file, and add `from apps.documents.models import DocumentDraft`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_render.py -k resolve_variant -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_variant'`

- [ ] **Step 3: Extract the function**

In `apps/documents/render.py`, immediately after `select_render_variant` (ends line 146), add:

```python
def resolve_variant(draft: DocumentDraft) -> str:
    """The variant this draft would actually render as.

    Public because the document worker needs the same answer *before* it
    decides which queue a render goes to (a EUROPASS_API draft must reach the
    pinned Europass worker, never a local render). Two copies of this
    expression is how the worker and the renderer end up disagreeing about
    what a draft is.
    """
    return draft.render_variant or select_render_variant(
        draft.programme, draft.funding_opportunity
    )
```

Then in `render_draft`, replace:

```python
    variant = draft.render_variant or select_render_variant(
        draft.programme, draft.funding_opportunity
    )
```

with:

```python
    variant = resolve_variant(draft)
```

Leave the comment block below it untouched — it explains the rate-limit guard, not the assignment.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_render.py -v`
Expected: PASS (the whole module — `render_draft`'s existing tests prove the extraction changed no behaviour)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/render.py tests/documents/test_render.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "refactor(documents): name the variant the worker has to agree on

The document worker picks a queue from the effective render variant, and
render_draft computed it inline. Two copies of the expression is how the
two ends up disagreeing about whether a draft is EUROPASS_API."
```

---

### Task 2: `confirm_facts` — the student's single click

Every fact writer in `apps/` sets `confirmed_by=None`, and `generatable_facts` filters on `confirmed_by__isnull=False`. Nothing performs the transition, so generation can never see a fact. This is that transition.

**Files:**
- Create: `apps/documents/confirmation.py`
- Test: `tests/documents/test_confirmation.py`

**Interfaces:**
- Consumes: `apps.documents.models.VerifiedFact`; `apps.documents.audit.record_event(*, actor, event, object_id)`; `apps.tenancy.models.Membership`.
- Produces: `confirm_facts(*, student: Membership, fact_ids: Iterable[UUID], actor: Membership) -> int` and `FactNotFound(LookupError)`. Task 10's confirm endpoint calls both.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_confirmation.py`:

```python
"""confirm_facts is a trust boundary, so the authorisation tests here are the
point of the file rather than a formality: an id is resolved through
``student=student``, never by id alone."""

from uuid import uuid4

import pytest

from apps.documents.confirmation import FactNotFound, confirm_facts
from apps.documents.models import VerifiedFact
from apps.documents.verification import generatable_facts
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope

from .conftest import make_fact

pytestmark = pytest.mark.django_db


def _candidate(student, name="Jane Doe"):
    return make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": name})


def test_a_candidate_becomes_visible_to_generation(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        assert not generatable_facts(membership_a).exists()

        confirmed = confirm_facts(
            student=membership_a, fact_ids=[fact.id], actor=membership_a
        )

        assert confirmed == 1
        fact.refresh_from_db()
        assert fact.confirmed_by_id == membership_a.id
        assert fact.confirmed_at is not None
        assert list(generatable_facts(membership_a)) == [fact]


def test_another_students_fact_id_is_not_found_and_nothing_is_written(
    agency_a, agency_b, membership_a, membership_b
):
    """404, not 403: a 403 would confirm the fact exists. All-or-nothing, so a
    batch carrying one foreign id confirms none of the caller's own either."""
    with tenant_scope(agency_b.id):
        theirs = _candidate(membership_b, name="Someone Else")
    with tenant_scope(agency_a.id):
        mine = _candidate(membership_a)

        with pytest.raises(FactNotFound):
            confirm_facts(
                student=membership_a, fact_ids=[mine.id, theirs.id], actor=membership_a
            )

        mine.refresh_from_db()
        assert mine.confirmed_by_id is None


def test_an_unknown_id_is_not_found(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        with pytest.raises(FactNotFound):
            confirm_facts(student=membership_a, fact_ids=[uuid4()], actor=membership_a)


def test_confirming_twice_is_a_no_op(agency_a, membership_a):
    """A resubmitted list must not fail -- the client retries, and the second
    call is not an error the student can act on."""
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        confirm_facts(student=membership_a, fact_ids=[fact.id], actor=membership_a)
        fact.refresh_from_db()
        stamped_at = fact.confirmed_at

        again = confirm_facts(
            student=membership_a, fact_ids=[fact.id], actor=membership_a
        )

        assert again == 0
        fact.refresh_from_db()
        assert fact.confirmed_at == stamped_at


def test_a_superseded_fact_is_skipped_not_confirmed(agency_a, membership_a):
    """A superseded row is not a candidate any more -- confirming it would put
    a corrected-away claim back in front of generation."""
    with tenant_scope(agency_a.id):
        old = _candidate(membership_a, name="Old Name")
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "New Name"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="correction",
            supersedes=old,
            confirmed_by=None,
            created_by=membership_a,
        )

        assert confirm_facts(
            student=membership_a, fact_ids=[old.id], actor=membership_a
        ) == 0
        old.refresh_from_db()
        assert old.confirmed_by_id is None


def test_every_confirmation_is_audited(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        confirm_facts(student=membership_a, fact_ids=[fact.id], actor=membership_a)

        events = AuditEvent.objects.filter(event="fact.confirmed", object_id=fact.id)
        assert events.count() == 1
        assert events.get().actor_id == membership_a.id
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_confirmation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.documents.confirmation'`

- [ ] **Step 3: Write the implementation**

Create `apps/documents/confirmation.py`:

```python
"""The student's single click: a candidate fact becomes a confirmed one.

Every fact writer in this app records ``confirmed_by=None`` on purpose -- an
applicant-written CV, a model's reading of it, and a profile bridge are all
claims, not verified facts -- and ``generatable_facts`` shows generation only
the confirmed ones. This module is the only transition between the two, so it
is where the authorship record is actually made.

Engine-level, not CV-level: the motivation-letter engine confirms from the
same ledger, which is why this is a module of its own rather than a function
inside a CV one.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership

from .audit import record_event
from .models import VerifiedFact


class FactNotFound(LookupError):
    """An id does not name a fact in this student's ledger.

    Callers must render this as 404, never 403: a 403 would confirm the fact
    exists, which is the convention storage.download_document already keeps.
    """


@transaction.atomic
def confirm_facts(*, student: Membership, fact_ids: Iterable[UUID], actor: Membership) -> int:
    """Stamp ``confirmed_by``/``confirmed_at`` on this student's candidates.

    Ids are resolved through ``student=student``, never by id alone, so a fact
    belonging to somebody else is indistinguishable from one that does not
    exist.

    All or nothing on *lookup*: an id that is not this student's raises before
    anything is written, so one bad id in a batch cannot half-confirm the rest.
    Already-confirmed and superseded rows are skipped rather than refused --
    a resubmitted list is a retry, and a superseded row is no longer a
    candidate. The return value counts rows actually changed.
    """
    ids = list(fact_ids)
    candidates = list(VerifiedFact.objects.select_for_update().filter(student=student, id__in=ids))
    if len(candidates) != len(set(ids)):
        raise FactNotFound("one or more fact ids are not in this student's ledger")
    superseded = set(
        VerifiedFact.objects.filter(supersedes_id__in=ids).values_list("supersedes_id", flat=True)
    )
    now = timezone.now()
    confirmed = 0
    for fact in candidates:
        if fact.confirmed_by_id is not None or fact.id in superseded:
            continue
        fact.confirmed_by = actor
        fact.confirmed_at = now
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        record_event(actor=actor, event="fact.confirmed", object_id=fact.id)
        confirmed += 1
    return confirmed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_confirmation.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/confirmation.py tests/documents/test_confirmation.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): the click that turns a candidate into a fact

Every writer records confirmed_by=None and generatable_facts filters on
confirmed_by IS NOT NULL, so nothing in apps/ could ever make a fact
visible to generation. Ids resolve through student= so another student's
fact id is not found rather than refused."
```

---

### Task 3: The upload door — a presigned POST, and a scan status that cannot wedge the queue

Two changes to `apps/concierge/documents.py`, both in the same file and both on the upload path, so they share a task.

`register()`'s docstring already names its intended caller: "A view issuing a presigned POST scopes it to the returned `object_key`." This writes that.

The second change is the guard the spec's EventBridge section requires. `apply_scan_result` does `_SCAN_STATES[result]`, which raises `KeyError` on any `scanResultStatus` AWS adds later — the handler dies, SQS redelivers, and the queue wedges behind one unknown status until the DLQ catches it. The fix goes **in the shared function**, not in the caller: every caller of `apply_scan_result` has the same problem, and one `.get()` is a smaller diff than a guard at each call site.

**Spec gap:** the spec says "the handler must validate the status against the map before calling, and treat an unrecognised value as `REVIEW_REQUIRED`". Doing that in the handler means either duplicating `apply_scan_result`'s body or passing it a status AWS never sent. Both are worse than making the shared function total. The handler still logs the unknown value (Task 5) — visibility stays where the spec put it, the crash is fixed at the root.

**Files:**
- Modify: `apps/concierge/documents.py:27-56`
- Test: `tests/concierge/test_documents.py`

**Interfaces:**
- Consumes: `apps.concierge.models.DocumentVersion` (`object_key`, `state`, `scan_result`); `django.conf.settings.EVIDENCE_BUCKET_NAME`.
- Produces: `presigned_upload(document: DocumentVersion, *, client: PresignClient | None = None) -> dict[str, object]` returning boto3's `{"url": str, "fields": dict}`; the public name `SCAN_STATES` (was `_SCAN_STATES`); `apply_scan_result` no longer raises `KeyError`. Task 5 imports `SCAN_STATES`; Task 9 calls `presigned_upload`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/concierge/test_documents.py`:

```python
class _FakePresigner:
    """Captures what would be signed. boto3 does no network call for
    generate_presigned_post either, but the point here is the conditions."""

    def __init__(self):
        self.calls = []

    def generate_presigned_post(self, **kwargs):
        self.calls.append(kwargs)
        return {"url": "https://s3.example.test/bucket", "fields": {"key": kwargs["Key"]}}


@pytest.mark.django_db
def test_presigned_upload_pins_the_exact_key_by_equality(agency_a, membership_a):
    """Equality, never starts-with. A prefix condition would let one student's
    signed form write anywhere under that prefix -- including over another of
    their own documents, after it had already been scanned clean."""
    from apps.concierge.documents import presigned_upload

    document = register(agency_a.id, membership_a.id)
    client = _FakePresigner()

    presigned_upload(document, client=client)

    conditions = client.calls[0]["Conditions"]
    assert {"key": document.object_key} in conditions
    assert not any(
        isinstance(condition, list) and condition[0] == "starts-with"
        for condition in conditions
    )


@pytest.mark.django_db
def test_presigned_upload_caps_the_size_and_the_clock(agency_a, membership_a):
    from apps.concierge.documents import presigned_upload

    document = register(agency_a.id, membership_a.id)
    client = _FakePresigner()

    presigned_upload(document, client=client)

    call = client.calls[0]
    (ceiling,) = [
        condition
        for condition in call["Conditions"]
        if isinstance(condition, list) and condition[0] == "content-length-range"
    ]
    assert ceiling[1] == 1
    assert ceiling[2] == 10 * 1024 * 1024
    assert 0 < call["ExpiresIn"] <= 900


@pytest.mark.django_db
def test_presigned_upload_takes_the_key_from_the_row(agency_a, membership_a, settings):
    """The key is not a parameter: register() derived it from the row, so a
    caller cannot aim an upload outside its own tenant's prefix."""
    from apps.concierge.documents import presigned_upload

    document = register(agency_a.id, membership_a.id)
    client = _FakePresigner()

    presigned_upload(document, client=client)

    assert client.calls[0]["Key"] == f"quarantine/{agency_a.id}/{document.id}"
    assert client.calls[0]["Bucket"] == settings.EVIDENCE_BUCKET_NAME


@pytest.mark.django_db
def test_an_unknown_scan_status_lands_in_review_instead_of_raising(agency_a, membership_a):
    """AWS may add a sixth scanResultStatus. A KeyError here would kill the
    scan handler, SQS would redeliver the same message, and every other
    student's upload would wait behind it until the DLQ caught it."""
    document = register(agency_a.id, membership_a.id)

    updated = apply_scan_result(document, "SOMETHING_NEW")

    assert updated.state == "REVIEW_REQUIRED"
    assert updated.scan_result == "SOMETHING_NEW"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/concierge/test_documents.py -v`
Expected: FAIL — `ImportError: cannot import name 'presigned_upload'` on the first three, `KeyError: 'SOMETHING_NEW'` on the fourth.

- [ ] **Step 3: Write the implementation**

In `apps/concierge/documents.py`, add to the imports:

```python
import boto3  # type: ignore[import-untyped]
from django.conf import settings
```

Rename `_SCAN_STATES` to `SCAN_STATES` (one definition, one use inside this module), and add the two upload constants beside it:

```python
SCAN_STATES = {
    "NO_THREATS_FOUND": "AVAILABLE",
    "THREATS_FOUND": "BLOCKED",
    "UNSUPPORTED": "REVIEW_REQUIRED",
    "ACCESS_DENIED": "REVIEW_REQUIRED",
    "FAILED": "REVIEW_REQUIRED",
}

#: A CV, not a corpus. Big enough for a scanned multi-page PDF, small enough
#: that a signed form is not an open upload slot into the evidence bucket.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: Long enough to start an upload on a bad connection, short enough that a
#: leaked form is not a standing grant.
_PRESIGN_EXPIRY_SECONDS = 900
```

Add the presign protocol beside `ReadableObjectStore`:

```python
class PresignClient(Protocol):
    def generate_presigned_post(self, **kwargs: object) -> dict[str, object]: ...
```

Replace `apply_scan_result`'s body:

```python
def apply_scan_result(document: DocumentVersion, result: str) -> DocumentVersion:
    """Record GuardDuty's verdict on one quarantined object.

    An unrecognised status is REVIEW_REQUIRED rather than a KeyError. AWS
    publishes five scanResultStatus values today and may add a sixth; a
    KeyError here kills whatever is draining the scan queue, the message
    redelivers, and every other student's upload waits behind it until the
    DLQ catches it. The raw value is still recorded (capped to the column
    width) so an unknown status is visible on the row rather than smoothed
    away.
    """
    with tenant_scope(document.tenant_id):
        document.state = SCAN_STATES.get(result, "REVIEW_REQUIRED")
        document.scan_result = result[:20]
        document.save(update_fields=["state", "scan_result"])
    return document
```

Add `presigned_upload` after `register`:

```python
def presigned_upload(
    document: DocumentVersion, *, client: PresignClient | None = None
) -> dict[str, object]:
    """A browser-postable form scoped to exactly this document's own key.

    The key is not a parameter -- it comes off the row ``register`` derived it
    on -- and the POST conditions pin it by EQUALITY. ``starts-with`` on the
    tenant prefix would turn one student's signed form into a write capability
    over every document in the agency, including one already scanned clean.

    The size ceiling is a condition rather than a check after the fact: S3
    rejects the upload itself, so an oversized file never reaches the bucket
    and never costs a scan.
    """
    s3 = client or boto3.client("s3")
    result = s3.generate_presigned_post(
        Bucket=settings.EVIDENCE_BUCKET_NAME,
        Key=document.object_key,
        Fields={"key": document.object_key},
        Conditions=[
            {"key": document.object_key},
            ["content-length-range", 1, _MAX_UPLOAD_BYTES],
        ],
        ExpiresIn=_PRESIGN_EXPIRY_SECONDS,
    )
    return dict(result)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/concierge/ tests/documents/ -v`
Expected: PASS. (Run both directories: the `_SCAN_STATES` rename is module-private, so nothing outside should break — this proves it.)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/concierge/documents.py tests/concierge/test_documents.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(concierge): sign an upload for one key, and stop an unknown verdict wedging the queue

register() already documented that a view would issue a presigned POST
scoped to the key it derived; presigned_upload is that, with the key
pinned by equality rather than prefix.

apply_scan_result indexed a five-key map, so a sixth scanResultStatus
from AWS would have killed the scan handler and redelivered forever."
```

---

### Task 4: `document_queue.py` — two message shapes, one transport

**Files:**
- Create: `apps/documents/document_queue.py`
- Create: `tests/documents/fixtures/guardduty_scan_result.json`
- Test: `tests/documents/test_document_queue.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. pydantic v2, boto3.
- Produces:
  - `SQSClient` (Protocol)
  - `DocumentWorkMessage(schema_version=1, action: Literal["generate","render"], kind: str, tenant_id: UUID, student_id: UUID, draft_id: UUID | None = None)`
  - `ScanResultEvent(object_key: str, scan_result: str, bucket_name: str)` — parses an EventBridge envelope in a `mode="before"` validator
  - `enqueue_document_work(message: DocumentWorkMessage, *, client: SQSClient | None = None, queue_url: str) -> None`
  - `consume_once(*, client: SQSClient, queue_url: str, handler: Callable[[_M], None], message_type: type[_M]) -> int`

  Tasks 5–7 and 9–12 all use these names.

- [ ] **Step 1: Write the fixture**

Create `tests/documents/fixtures/guardduty_scan_result.json` — the AWS sample with its `{{...}}` placeholder braces removed and the object key replaced by one of ours:

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

- [ ] **Step 2: Write the failing tests**

Create `tests/documents/test_document_queue.py`:

```python
import json
from pathlib import Path
from uuid import uuid4

import pytest

from apps.documents.document_queue import (
    DocumentWorkMessage,
    ScanResultEvent,
    consume_once,
    enqueue_document_work,
)

FIXTURE = Path(__file__).parent / "fixtures" / "guardduty_scan_result.json"


class _FakeSQS:
    def __init__(self, messages=()):
        self.sent = []
        self.deleted = []
        self._messages = list(messages)

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {}

    def receive_message(self, **kwargs):
        return {"Messages": self._messages}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)
        return {}


def _work(**overrides):
    fields = {
        "action": "generate",
        "kind": "CV",
        "tenant_id": uuid4(),
        "student_id": uuid4(),
    }
    fields.update(overrides)
    return DocumentWorkMessage(**fields)


def _event(**detail_overrides):
    event = json.loads(FIXTURE.read_text())
    event["detail"]["scanResultDetails"].update(detail_overrides)
    return event


def test_the_work_message_carries_no_pii_fields():
    """A queue is a durable store with its own retention policy. A student's
    name or employment history must not get a second copy there under
    different rules from the first -- the worker reads content from the
    database, under tenant scope."""
    assert set(DocumentWorkMessage.model_fields) == {
        "schema_version",
        "action",
        "kind",
        "tenant_id",
        "student_id",
        "draft_id",
    }


def test_the_work_message_rejects_extra_fields():
    with pytest.raises(ValueError):
        _work(full_name="Jane Doe")


def test_the_work_message_rejects_an_unknown_action():
    with pytest.raises(ValueError):
        _work(action="delete")


def test_enqueue_sends_the_serialised_message_without_a_group_id():
    """Standard queue, not FIFO: MessageGroupId is FIFO-only and SQS rejects
    it on a standard queue."""
    client = _FakeSQS()
    message = _work()

    enqueue_document_work(message, client=client, queue_url="q")

    body = json.loads(client.sent[0]["MessageBody"])
    assert body["student_id"] == str(message.student_id)
    assert client.sent[0]["QueueUrl"] == "q"
    assert "MessageGroupId" not in client.sent[0]


def test_consume_once_invokes_the_handler_and_deletes():
    message = _work()
    client = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-1"}])
    seen = []

    count = consume_once(
        client=client, queue_url="q", handler=seen.append, message_type=DocumentWorkMessage
    )

    assert count == 1
    assert seen[0].student_id == message.student_id
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"


def test_a_malformed_raw_message_is_skipped_and_not_counted():
    good = _work()
    client = _FakeSQS(
        [
            {"Body": 12345, "ReceiptHandle": "rh-bad"},
            {"Body": good.model_dump_json(), "ReceiptHandle": "rh-good"},
        ]
    )
    seen = []

    count = consume_once(
        client=client, queue_url="q", handler=seen.append, message_type=DocumentWorkMessage
    )

    assert count == 1
    assert client.deleted == [{"QueueUrl": "q", "ReceiptHandle": "rh-good"}]


def test_a_failing_handler_does_not_delete_the_message():
    """The message must return to the queue so SQS can retry it. Deleting on
    failure silently loses a student's CV."""
    client = _FakeSQS([{"Body": _work().model_dump_json(), "ReceiptHandle": "rh-2"}])

    def _boom(_message):
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError):
        consume_once(
            client=client, queue_url="q", handler=_boom, message_type=DocumentWorkMessage
        )
    assert client.deleted == []


@pytest.mark.parametrize(
    "status",
    ["NO_THREATS_FOUND", "THREATS_FOUND", "UNSUPPORTED", "ACCESS_DENIED", "FAILED"],
)
def test_the_scan_event_parses_every_documented_status(status):
    """AWS publishes a verbatim sample per scanResultStatus. All five reach
    the handler as the same three values."""
    parsed = ScanResultEvent.model_validate(_event(scanResultStatus=status))

    assert parsed.scan_result == status
    assert parsed.object_key.startswith("quarantine/")
    assert parsed.bucket_name == "test-evidence-bucket"


def test_the_scan_event_reads_scan_result_status_not_scan_status():
    """detail.scanStatus is a DIFFERENT field with a different vocabulary
    (COMPLETED/SKIPPED/FAILED): whether the scan ran, not what it found.
    Reading it would collapse 'password-protected' and 'access denied' into
    one indistinguishable state."""
    event = _event(scanResultStatus="THREATS_FOUND")
    event["detail"]["scanStatus"] = "COMPLETED"

    assert ScanResultEvent.model_validate(event).scan_result == "THREATS_FOUND"


def test_the_scan_event_tolerates_populated_threat_fields():
    """threats and statusReasons are null on a clean scan and populated on
    THREATS_FOUND / UNSUPPORTED / ACCESS_DENIED. Neither is read, and neither
    may break parsing."""
    event = _event(
        scanResultStatus="THREATS_FOUND",
        threats=[{"name": "EICAR-Test-File"}],
        statusReasons=["reason"],
    )

    assert ScanResultEvent.model_validate(event).scan_result == "THREATS_FOUND"


def test_an_event_missing_the_object_details_is_rejected():
    event = json.loads(FIXTURE.read_text())
    del event["detail"]["s3ObjectDetails"]

    with pytest.raises(ValueError):
        ScanResultEvent.model_validate(event)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_document_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.documents.document_queue'`

- [ ] **Step 4: Write the implementation**

Create `apps/documents/document_queue.py`:

```python
"""SQS transport for the document engine: our own work, and GuardDuty's verdict.

Two queues, one module. DocumentQueue carries messages we wrote;
DocumentScanQueue carries EventBridge envelopes AWS wrote. The envelope is a
second Pydantic model here rather than a second module -- they share one
consume_once, and splitting them would be two files that import each other.

DocumentWorkMessage carries identifiers only, never content, for the same
reason EuropassRenderMessage does: a queue is a durable store with its own
retention policy, so a second copy of a student's personal data must not live
there governed by different rules from the first. The worker reads the content
from the database, under tenant scope.

# ponytail: third copy of this repo's SQS idiom (apps/research/queue.py and
# apps/documents/europass_queue.py are the other two, and europass_queue.py's
# docstring records that duplication as the deliberate choice). Extract a
# shared consume_once if a fourth queue appears; refactoring two production
# queues to share a base is a larger, riskier diff than 90 copied lines.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID

import boto3  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, model_validator


class SQSClient(Protocol):
    def send_message(self, **kwargs: str) -> object: ...

    def receive_message(self, **kwargs: object) -> dict[str, object]: ...

    def delete_message(self, **kwargs: str) -> object: ...


class DocumentWorkMessage(BaseModel):
    """One unit of document work. Identifiers only -- see the module docstring.

    ``kind`` rather than a CV-named message: the motivation-letter engine adds
    a branch in the worker, not a queue, a task definition or an alarm. The
    accepted set of kinds is validated in exactly one place, ``api._SUPPORTED_KINDS``.

    ``draft_id`` is set for ``render`` and absent for ``generate`` -- a
    generation has no draft yet, which is the whole reason it is being queued.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    action: Literal["generate", "render"]
    kind: str
    tenant_id: UUID
    student_id: UUID
    draft_id: UUID | None = None


class ScanResultEvent(BaseModel):
    """The three values we read out of a GuardDuty object-scan event.

    Verified against AWS's published samples (docs.aws.amazon.com/guardduty/
    latest/ug/monitor-with-eventbridge-s3-malware-protection.html), which
    publishes a verbatim sample for each of the five scanResultStatus values.

    ``scan_result`` comes from ``detail.scanResultDetails.scanResultStatus``
    and NEVER from ``detail.scanStatus``: that is a different field with a
    different vocabulary (COMPLETED / SKIPPED / FAILED) describing whether the
    scan ran rather than what it found, and reading it collapses
    "password-protected file" and "access denied" into one state.

    ``threats`` and ``statusReasons`` are null on a clean scan and populated
    otherwise. Neither is read here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_key: str
    scan_result: str
    bucket_name: str

    @model_validator(mode="before")
    @classmethod
    def _unwrap_eventbridge(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "detail" not in value:
            return value
        detail = value.get("detail") or {}
        objects = detail.get("s3ObjectDetails") or {}
        results = detail.get("scanResultDetails") or {}
        # .get, not [], so a missing path becomes a ValidationError on a
        # required str field rather than a KeyError out of a validator --
        # pydantic does not translate KeyError, and an untranslated one here
        # would crash the consumer instead of skipping one bad message.
        return {
            "object_key": objects.get("objectKey"),
            "scan_result": results.get("scanResultStatus"),
            "bucket_name": objects.get("bucketName"),
        }


def enqueue_document_work(
    message: DocumentWorkMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    sqs = client or boto3.client("sqs")
    sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())


_M = TypeVar("_M", bound=BaseModel)


def consume_once(
    *,
    client: SQSClient,
    queue_url: str,
    handler: Callable[[_M], None],
    message_type: type[_M],
) -> int:
    """Receive at most one message, hand it to ``handler``, delete on success.

    ``message_type`` is a parameter because the two queues carry different
    shapes; everything else about draining them is identical.

    Deletion happens only after the handler returns. A handler that raises
    leaves the message on the queue, so SQS redelivers it and the DLQ
    eventually catches what never succeeds -- that is the entire retry story.
    """
    response = client.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        AttributeNames=["ApproximateReceiveCount"],
    )
    messages = response.get("Messages", [])
    if not isinstance(messages, list):
        return 0
    processed = 0
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        body = raw.get("Body")
        receipt = raw.get("ReceiptHandle")
        if not isinstance(body, str) or not isinstance(receipt, str):
            continue
        handler(message_type.model_validate_json(body))
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        processed += 1
    return processed
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_document_queue.py -v`
Expected: PASS (14 tests, five of them the parametrized status cases)

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/document_queue.py tests/documents/test_document_queue.py tests/documents/fixtures/guardduty_scan_result.json
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): the two message shapes the document worker drains

Work messages carry identifiers only -- a queue is a durable store with
its own retention, so a student's history must not get a second copy
there. The scan envelope reads scanResultStatus and never scanStatus:
the two are different vocabularies, and reading the wrong one collapses
'password-protected' and 'access denied' into one state."
```

---

### Task 5: The scan handler — GuardDuty's verdict, and ingestion behind it

**Files:**
- Create: `apps/documents/document_worker.py`
- Test: `tests/documents/test_document_worker.py`

**Interfaces:**
- Consumes: `ScanResultEvent` (Task 4); `apps.concierge.documents.SCAN_STATES`, `apply_scan_result` (Task 3); `apps.concierge.models.DocumentVersion`; `apps.documents.ingestion.ingest_uploaded_cv(*, document, student, client=None, store=None)`; `apps.documents.models.VerifiedFact`; `apps.tenancy.context.tenant_scope`; `apps.tenancy.db.set_local_tenant`.
- Produces: `handle_scan_result(event: ScanResultEvent) -> None`. Task 7's command passes it to `consume_once`.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_document_worker.py`:

```python
"""The scan handler's decisions, not GuardDuty's and not the extractor's.

ingest_uploaded_cv is monkeypatched throughout: what is under test here is
which events cause an ingestion at all, and extraction has its own module.
"""

import pytest
from django.conf import settings

from apps.concierge.documents import register
from apps.documents import document_worker
from apps.documents.document_queue import ScanResultEvent
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def ingested(monkeypatch):
    """Records every ingest_uploaded_cv call instead of making one."""
    calls = []
    monkeypatch.setattr(
        document_worker,
        "ingest_uploaded_cv",
        lambda **kwargs: calls.append(kwargs) or (),
    )
    return calls


def _event(document, status="NO_THREATS_FOUND", bucket=None):
    return ScanResultEvent(
        object_key=document.object_key,
        scan_result=status,
        bucket_name=bucket or settings.EVIDENCE_BUCKET_NAME,
    )


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("NO_THREATS_FOUND", "AVAILABLE"),
        ("THREATS_FOUND", "BLOCKED"),
        ("UNSUPPORTED", "REVIEW_REQUIRED"),
        ("ACCESS_DENIED", "REVIEW_REQUIRED"),
        ("FAILED", "REVIEW_REQUIRED"),
    ],
)
def test_every_documented_status_reaches_its_state(
    agency_a, membership_a, ingested, status, state
):
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document, status))

    document.refresh_from_db()
    assert document.state == state


def test_only_a_clean_scan_triggers_ingestion(agency_a, membership_a, ingested):
    """An infected upload must reach neither the extractor nor the ledger."""
    blocked = register(agency_a.id, membership_a.id)
    clean = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(blocked, "THREATS_FOUND"))
    assert ingested == []

    document_worker.handle_scan_result(_event(clean, "NO_THREATS_FOUND"))
    assert [call["document"].id for call in ingested] == [clean.id]


def test_a_redelivered_message_does_not_ingest_twice(agency_a, membership_a, ingested):
    """SQS delivery is at-least-once. Without the guard a redelivery
    duplicates every candidate fact the upload produced, and the student
    confirms the same claim twice."""
    document = register(agency_a.id, membership_a.id)
    with tenant_scope(agency_a.id):
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "Jane Doe"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref=f"upload:{document.id}",
            confirmed_by=None,
            created_by=membership_a,
        )

    document_worker.handle_scan_result(_event(document))

    assert ingested == []


def test_an_unknown_object_key_is_dropped_not_raised(agency_a, membership_a, ingested):
    """The message is deleted rather than redelivered forever: an event for a
    key we never minted is never going to find a row."""
    event = ScanResultEvent(
        object_key="quarantine/00000000-0000-0000-0000-0000000000a1/"
        "00000000-0000-0000-0000-0000000000b2",
        scan_result="NO_THREATS_FOUND",
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
    )

    document_worker.handle_scan_result(event)

    assert ingested == []


def test_a_key_outside_the_quarantine_shape_is_dropped(agency_a, membership_a, ingested):
    """The object key is the ONLY thing trusted out of the event, so its shape
    is checked: nothing else in the envelope may choose which row is written."""
    event = ScanResultEvent(
        object_key="tenants/anything/else",
        scan_result="NO_THREATS_FOUND",
        bucket_name=settings.EVIDENCE_BUCKET_NAME,
    )

    document_worker.handle_scan_result(event)

    assert ingested == []


def test_an_event_for_another_bucket_is_ignored(agency_a, membership_a, ingested):
    """The EventBridge rule matches on detail-type and source, which are
    account-wide: a scan of some other bucket must not write our rows."""
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document, bucket="someone-elses-bucket"))

    document.refresh_from_db()
    assert document.state == "QUARANTINED"
    assert ingested == []


def test_an_unknown_status_lands_in_review_and_does_not_ingest(
    agency_a, membership_a, ingested
):
    """AWS may add a sixth scanResultStatus. Treating it as clean would ingest
    an unscanned file; crashing would wedge the queue."""
    document = register(agency_a.id, membership_a.id)

    document_worker.handle_scan_result(_event(document, "SOMETHING_NEW"))

    document.refresh_from_db()
    assert document.state == "REVIEW_REQUIRED"
    assert ingested == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_document_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.documents.document_worker'`

- [ ] **Step 3: Write the implementation**

Create `apps/documents/document_worker.py`:

```python
"""The document queues' handlers. Worker-side only.

Nothing here may be called from a view. Generation costs up to two model
calls against a 30-second gunicorn worker, and render.py:764-769 records that
the web tier must not call render_draft at all.

# ponytail: each handler holds one transaction across its slow call (a model
# call in the scan path, weasyprint in the render path). RLS reads the
# app.tenant_id GUC, which SET LOCAL only holds inside a transaction, and both
# generate_cv and ingest_uploaded_cv read the ledger themselves -- so the call
# cannot sit outside one without splitting those functions' reads from their
# writes. One worker task at ~100 documents/day makes the held connection
# acceptable. Split them if that stops being true.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from django.conf import settings
from django.db import transaction

from apps.concierge.documents import SCAN_STATES, apply_scan_result
from apps.concierge.models import DocumentVersion
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .document_queue import ScanResultEvent
from .ingestion import ingest_uploaded_cv
from .models import VerifiedFact

logger = logging.getLogger(__name__)

#: The exact shape register() derives: quarantine/{tenant_uuid}/{document_uuid},
#: hex and slashes only. Matching it is how the tenant scope for the write is
#: taken from a key WE minted rather than from anything in the event.
_KEY_PATTERN = re.compile(
    r"^quarantine/(?P<tenant_id>[0-9a-fA-F-]{36})/[0-9a-fA-F-]{36}$"
)


def handle_scan_result(event: ScanResultEvent) -> None:
    """Apply one GuardDuty verdict, and ingest the file if it came back clean.

    The object key is the ONLY value trusted out of the event -- it is a key
    register() derived, its shape is checked, and the tenant scope for every
    write below comes out of it. Nothing else in the envelope influences which
    row is written.

    An event that cannot find a row is logged and returns normally, so the
    message is DELETED rather than redelivered forever. There is no future
    delivery in which an unknown key becomes known.
    """
    if event.bucket_name != settings.EVIDENCE_BUCKET_NAME:
        # The EventBridge rule matches detail-type and source, which are
        # account-wide. Another bucket's scan is not ours to act on.
        logger.warning("DocumentScanForeignBucket bucket=%s", event.bucket_name)
        return
    match = _KEY_PATTERN.match(event.object_key)
    if match is None:
        logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
        return
    try:
        tenant_id = UUID(match["tenant_id"])
    except ValueError:
        logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
        return
    if event.scan_result not in SCAN_STATES:
        # apply_scan_result puts it in REVIEW_REQUIRED; this is the line that
        # makes an unknown status visible instead of merely survivable.
        logger.warning("DocumentScanUnknownStatus status=%s", event.scan_result)

    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        document = DocumentVersion.objects.filter(object_key=event.object_key).first()
        if document is None:
            logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
            return
        apply_scan_result(document, event.scan_result)
        if document.state != "AVAILABLE":
            return
        if VerifiedFact.objects.filter(
            student_id=document.student_id, source_ref=f"upload:{document.id}"
        ).exists():
            # SQS delivery is at-least-once. Re-applying the scan state is
            # harmless (same value), but a second ingestion duplicates every
            # candidate fact and the student confirms the same claim twice.
            logger.info("DocumentScanAlreadyIngested document=%s", document.id)
            return
        ingest_uploaded_cv(document=document, student=document.student)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_document_worker.py -v`
Expected: PASS (11 tests, five of them the parametrized statuses)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/document_worker.py tests/documents/test_document_worker.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): act on a scan verdict, trusting only the key we minted

The row is found by object_key and the tenant scope comes out of that
key's own shape, so nothing else in the EventBridge envelope chooses
what gets written. Ingestion is guarded on source_ref because SQS
delivery is at-least-once and a redelivery would duplicate every
candidate fact."
```

---

### Task 6: The work handlers — generate, and render or hand off

**Files:**
- Modify: `apps/documents/document_worker.py`
- Test: `tests/documents/test_document_worker.py`

**Interfaces:**
- Consumes: `DocumentWorkMessage` (Task 4); `resolve_variant` (Task 1); `apps.documents.generation.generate_cv`; `apps.documents.drafts.create_draft`; `apps.documents.verification.generatable_facts`; `apps.documents.render.render_draft`, `UnsupportedRenderVariant`; `apps.documents.storage.store_document`; `apps.documents.europass_queue.EuropassRenderMessage`, `enqueue_europass_render`.
- Produces: `handle_document_work(message: DocumentWorkMessage) -> None`. Task 7's command passes it to `consume_once`.

**Spec gap:** the message carries no programme, so `generate_cv` is called with `programme=None` — an untailored CV. Tailoring needs a programme chosen somewhere, and this door has no endpoint that chooses one. Adding `programme_id` to the message would be a field nothing sets. When a programme picker lands, it adds an optional `programme_id` to `DocumentWorkMessage` and passes it through here; that is a one-field change, which is why it is not pre-built.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_document_worker.py`:

```python
from apps.documents.document_queue import DocumentWorkMessage
from apps.documents.drafts import create_draft
from apps.documents.generation import GenerationResult
from apps.documents.models import DocumentDraft
from apps.documents.render import RenderedArtifact, UnsupportedRenderVariant
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation

from .conftest import make_identity_fact


def _content():
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _approved_draft(agency_a, membership_a, variant=""):
    with tenant_scope(agency_a.id):
        draft = create_draft(
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            content=_content(),
            render_variant=variant,
        )
        DocumentDraft.objects.filter(id=draft.id).update(
            status=DocumentDraft.Status.APPROVED
        )
        draft.refresh_from_db()
    return draft


def test_a_generate_message_writes_a_draft(agency_a, membership_a, monkeypatch):
    monkeypatch.setattr(
        document_worker,
        "generate_cv",
        lambda **kwargs: GenerationResult(content=_content(), verdicts=(), retried=False),
    )
    with tenant_scope(agency_a.id):
        make_identity_fact(membership_a)

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
        )
    )

    with tenant_scope(agency_a.id):
        draft = DocumentDraft.objects.get(student=membership_a)
    assert draft.version == 1
    assert draft.status == DocumentDraft.Status.DRAFT


def test_a_europass_api_render_is_handed_to_the_pinned_worker(
    agency_a, membership_a, monkeypatch
):
    """That queue is single-worker and pinned for the circuit breaker and the
    europa.eu courtesy rate. Rendering here would bypass both, and nothing
    would be storing the artefact either."""
    handed = []
    rendered = []
    monkeypatch.setattr(
        document_worker, "enqueue_europass_render", lambda message, **kw: handed.append(message)
    )
    monkeypatch.setattr(document_worker, "render_draft", lambda **kw: rendered.append(kw))
    draft = _approved_draft(agency_a, membership_a, variant="EUROPASS_API")

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            draft_id=draft.id,
        )
    )

    assert [message.draft_id for message in handed] == [draft.id]
    assert rendered == []


def test_a_local_variant_is_stored_under_the_drafts_own_key(
    agency_a, membership_a, monkeypatch, fake_store
):
    monkeypatch.setattr(
        document_worker,
        "render_draft",
        lambda **kw: RenderedArtifact(
            variant="STANDARD",
            pdf_bytes=b"%PDF-1.7",
            field_mapped=None,
            page_count=1,
            byte_size=8,
        ),
    )
    monkeypatch.setattr(document_worker, "_object_store", lambda: fake_store)
    draft = _approved_draft(agency_a, membership_a, variant="STANDARD")

    document_worker.handle_document_work(
        DocumentWorkMessage(
            action="render",
            kind=DocumentDraft.Kind.CV,
            tenant_id=agency_a.id,
            student_id=membership_a.id,
            draft_id=draft.id,
        )
    )

    key = (
        f"tenants/{agency_a.id}/students/{membership_a.id}"
        f"/documents/{draft.id}/cv-standard.pdf"
    )
    assert fake_store.get(key) == b"%PDF-1.7"


def test_a_variant_with_no_worker_render_path_fails_loudly(
    agency_a, membership_a, monkeypatch
):
    """FIELD_MAPPED produces a dict rather than bytes and FUNDER_TEMPLATE needs
    a funder_template_id no draft carries. Storing an empty artefact would be
    a silent wrong answer; a raise sends the message to the DLQ, where the
    alarm is."""
    draft = _approved_draft(agency_a, membership_a, variant="FIELD_MAPPED")

    with pytest.raises(UnsupportedRenderVariant):
        document_worker.handle_document_work(
            DocumentWorkMessage(
                action="render",
                kind=DocumentDraft.Kind.CV,
                tenant_id=agency_a.id,
                student_id=membership_a.id,
                draft_id=draft.id,
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_document_worker.py -k "generate or render or variant" -v`
Expected: FAIL — `AttributeError: module 'apps.documents.document_worker' has no attribute 'handle_document_work'`

- [ ] **Step 3: Write the implementation**

Add to `apps/documents/document_worker.py`'s imports:

```python
from apps.research.storage import S3ObjectStore
from apps.tenancy.models import Membership

from .document_queue import DocumentWorkMessage, ScanResultEvent
from .drafts import create_draft
from .europass_queue import EuropassRenderMessage, enqueue_europass_render
from .generation import generate_cv
from .models import DocumentDraft, VerifiedFact
from .render import UnsupportedRenderVariant, render_draft, resolve_variant
from .storage import store_document
from .verification import generatable_facts
```

And append:

```python
#: The variants render_draft turns into PDF bytes with nothing else supplied.
#: FUNDER_TEMPLATE needs a funder_template_id no draft carries, and
#: FIELD_MAPPED produces a dict. Both are out of this door's scope.
_LOCAL_PDF_VARIANTS = frozenset({"STANDARD", "EUROPASS", "GERMAN_TABULAR"})


def _object_store() -> S3ObjectStore:
    """Indirection for tests only -- the one seam store_document takes."""
    return S3ObjectStore()


def _artefact_filename(variant: str) -> str:
    """Names the variant, so two variants of one draft cannot overwrite each
    other under the same key. Matches storage._SAFE_FILENAME."""
    return f"cv-{variant.lower().replace('_', '-')}.pdf"


def handle_document_work(message: DocumentWorkMessage) -> None:
    if message.action == "generate":
        _generate(message)
    else:
        _render(message)


def _generate(message: DocumentWorkMessage) -> None:
    """Generate a document from the student's confirmed ledger and store the draft.

    ``programme=None``: the message carries no programme, because no endpoint
    in this door chooses one. Tailoring arrives with a programme picker, as
    one optional field on the message passed through here.

    Every predictable failure (identity not confirmed, no application email,
    rate limit) was already checked synchronously by the generate endpoint.
    What reaches here and fails is model refusal or a GenerationFailure --
    rare, and the DLQ alarm is the right place for it.
    """
    tenant_id = message.tenant_id
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        student = Membership.objects.get(id=message.student_id)
        result = generate_cv(student=student, programme=None)
        create_draft(
            student=student,
            kind=message.kind,
            content=result.content,
            facts=list(generatable_facts(student)),
            actor=student,
        )


def _render(message: DocumentWorkMessage) -> None:
    """Render an approved draft, or hand it to the worker that may call europa.eu.

    The variant is resolved once, here, from the same expression render_draft
    uses -- the queue choice and the render must not be able to disagree.
    """
    tenant_id = message.tenant_id
    with tenant_scope(tenant_id):
        with transaction.atomic():
            set_local_tenant(tenant_id)
            draft = DocumentDraft.objects.select_related(
                "programme", "funding_opportunity"
            ).get(id=message.draft_id)
            variant = resolve_variant(draft)

        if variant == "EUROPASS_API":
            # EuropassQueue is single-worker and pinned for the circuit
            # breaker and the europa.eu courtesy rate. Calling render_draft
            # here would bypass both, and nothing would store the result.
            enqueue_europass_render(
                EuropassRenderMessage(tenant_id=tenant_id, draft_id=draft.id),
                queue_url=settings.EUROPASS_QUEUE_URL,
            )
            return
        if variant not in _LOCAL_PDF_VARIANTS:
            raise UnsupportedRenderVariant(f"no worker render path for variant {variant!r}")

        with transaction.atomic():
            set_local_tenant(tenant_id)
            artifact = render_draft(draft=draft)
            if artifact.pdf_bytes is None:
                raise UnsupportedRenderVariant(f"variant {variant!r} produced no PDF")
            store_document(
                draft=draft,
                filename=_artefact_filename(variant),
                content=artifact.pdf_bytes,
                store=_object_store(),
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_document_worker.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/document_worker.py tests/documents/test_document_worker.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): run a generation, and route a render by its resolved variant

A EUROPASS_API draft is handed to the pinned Europass worker rather than
rendered here: that queue is where the circuit breaker and the courtesy
rate live. Local variants render and store under the draft's own key,
which is the key download_document re-derives."
```

---

### Task 7: `run_document_worker` and the two settings

Configuration lands with the command that first needs it. Note the blast radius: adding a required variable to `config/settings/production.py` means **every** task definition must supply it — that is Task 13's job, and `tests/infra/test_template.py::test_app_task_definitions_supply_every_production_required_env_var` is the test that catches a miss.

**Files:**
- Create: `apps/documents/management/commands/run_document_worker.py`
- Modify: `config/settings/base.py:90-92`, `config/settings/production.py:11-12`
- Test: `tests/documents/test_run_document_worker.py`

**Interfaces:**
- Consumes: `consume_once`, `DocumentWorkMessage`, `ScanResultEvent` (Task 4); `handle_scan_result` (Task 5); `handle_document_work` (Task 6).
- Produces: `settings.DOCUMENT_QUEUE_URL`, `settings.DOCUMENT_SCAN_QUEUE_URL`; the `run_document_worker` management command. Tasks 11–12 read the first setting; Task 13 supplies both in CloudFormation.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_run_document_worker.py`:

```python
import pytest

from apps.documents.generation import GenerationRateLimited
from apps.documents.ingestion import IngestionRateLimited
from apps.documents.management.commands import run_document_worker

pytestmark = pytest.mark.django_db


def test_both_queues_are_drained_in_one_pass(monkeypatch, settings):
    """One task, two queues. A worker that polls only one leaves either every
    upload unscanned-for or every generation unrun, with no signal but a
    growing backlog."""
    settings.DOCUMENT_SCAN_QUEUE_URL = "scan-q"
    settings.DOCUMENT_QUEUE_URL = "work-q"
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())
    polled = []

    def _consume_once(*, queue_url, **kwargs):
        polled.append(queue_url)
        return 0

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    run_document_worker.Command().handle(once=True)

    assert polled == ["scan-q", "work-q"]


@pytest.mark.parametrize(
    "error",
    [GenerationRateLimited("too many"), IngestionRateLimited("too many")],
    ids=["generation", "ingestion"],
)
def test_a_rate_limited_message_is_deferred_not_crashed(monkeypatch, error):
    """Our own limiter firing is a designed outcome, not a crash. An uncaught
    exception kills the ECS task; each restart re-polls the same message and
    burns its limited redelivery budget faster than the window rolls over,
    driving a student's CV to the DLQ for no reason. The message is never
    deleted, so SQS redelivers it after the visibility timeout."""
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())

    def _consume_once(**kwargs):
        raise error

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    run_document_worker.Command().handle(once=True)


def test_an_unexpected_error_is_not_swallowed(monkeypatch):
    """Only the designed failures are caught. A blanket except would hide a
    genuine bug behind an endlessly redelivering message."""
    monkeypatch.setattr(run_document_worker.boto3, "client", lambda *a, **kw: object())

    def _consume_once(**kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(run_document_worker, "consume_once", _consume_once)

    with pytest.raises(RuntimeError):
        run_document_worker.Command().handle(once=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_run_document_worker.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_document_worker'`

- [ ] **Step 3: Add the settings**

In `config/settings/base.py`, beside the other two queue URLs (line 91):

```python
DOCUMENT_QUEUE_URL = os.getenv("DOCUMENT_QUEUE_URL", "test-document-queue")
DOCUMENT_SCAN_QUEUE_URL = os.getenv("DOCUMENT_SCAN_QUEUE_URL", "test-document-scan-queue")
```

In `config/settings/production.py`, beside the other two (line 12):

```python
DOCUMENT_QUEUE_URL = os.environ["DOCUMENT_QUEUE_URL"]
DOCUMENT_SCAN_QUEUE_URL = os.environ["DOCUMENT_SCAN_QUEUE_URL"]
```

- [ ] **Step 4: Write the command**

Create `apps/documents/management/commands/run_document_worker.py`:

```python
"""Drain both document queues.

Its own ECS service, mirroring run_europass_worker. Not folded into
run_research_worker: that service is scaled for research throughput, and this
one holds a different pair of grants.

One task drains both queues because they share a lifecycle -- an upload's
scan verdict and the generation it eventually causes are the same student's
journey, and two services would be two task definitions, two log groups and
two sets of alarms for a combined ~100 documents a day.

# ponytail: one worker holds both grants (quarantine/* read for the scan
# path, tenants/* write for the render path). Split the task definition if
# the scan path ever needs to run untrusted code.
"""

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.documents.document_queue import DocumentWorkMessage, ScanResultEvent, consume_once
from apps.documents.document_worker import handle_document_work, handle_scan_result
from apps.documents.generation import GenerationRateLimited
from apps.documents.ingestion import IngestionRateLimited


class Command(BaseCommand):
    help = "Consume GuardDuty scan verdicts and document work from SQS"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")
        while True:
            try:
                consume_once(
                    client=client,
                    queue_url=settings.DOCUMENT_SCAN_QUEUE_URL,
                    handler=handle_scan_result,
                    message_type=ScanResultEvent,
                )
                consume_once(
                    client=client,
                    queue_url=settings.DOCUMENT_QUEUE_URL,
                    handler=handle_document_work,
                    message_type=DocumentWorkMessage,
                )
            except (GenerationRateLimited, IngestionRateLimited) as error:
                # Our own limiter, not a failure. Same reasoning as
                # run_europass_worker's deferred branch: an uncaught exception
                # kills the ECS task, each restart re-polls the same message
                # and burns the maxReceiveCount budget faster than the window
                # rolls over. The message was never deleted, so SQS redelivers
                # it after the visibility timeout.
                self.stderr.write(f"Document work deferred: {error}")
            if options["once"]:
                return
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_run_document_worker.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/management/commands/run_document_worker.py config/settings/base.py config/settings/production.py tests/documents/test_run_document_worker.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): one worker, both document queues

Scan verdicts and document work share a lifecycle and a task. A
rate-limited message is deferred rather than crashed: killing the task
re-polls the same message and burns its redelivery budget faster than
the window rolls over."
```

---

### Task 8: `api.py` — the shared shape, and the way in

There is no login route in this repo: nothing includes `django.contrib.auth.urls` and no view calls `login()`. Session authentication has no way to begin, which is why this task comes before every other endpoint.

**Spec gap:** the spec lists `POST /api/auth/login` with `@ensure_csrf_cookie`. A client that has never made a request has no CSRF cookie, and `CsrfViewMiddleware` rejects a POST without a token — so the POST alone is unusable from a real browser. The route therefore answers **GET as well**: GET issues the cookie and reports whether the session is authenticated, POST authenticates. One route, two methods, rather than a second `/api/auth/csrf` nobody remembers to call. Endpoint count is unchanged.

**Files:**
- Create: `apps/documents/api.py`
- Modify: `apps/documents/urls.py`
- Test: `tests/documents/test_api.py`

**Interfaces:**
- Consumes: `apps.tenancy.services.current_membership`; `apps.tenancy.models.Membership`; `apps.ratelimit.rate_limited`.
- Produces, for Tasks 9–12:
  - `_ApiError(status: int, code: str)` — raise it anywhere inside a decorated view
  - `_json_errors(view)` — turns `_ApiError` into `{"error": code}` with its status
  - `_student_endpoint(view)` — 401 if unauthenticated, 403 if not a STUDENT here, otherwise calls `view(request, student, *args, **kwargs)`; includes `_json_errors`
  - `_json_body(request) -> dict[str, object]`
  - `_SUPPORTED_KINDS: frozenset[str]` — the one place a document kind is validated
  - `auth_login`, `auth_logout` views

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_api.py`:

```python
"""The door. Every test here is about a boundary -- who may call, what a
refusal reveals, and what a call is allowed to touch -- because the engine
behind it has its own tests and does not need re-testing through HTTP.

Asserts no markup, by design: this surface is JSON, and the presentation
layer that consumes it is deliberately undecided.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"


@pytest.fixture
def credentialed_user(db):
    return get_user_model().objects.create_user(
        username="student-login", password="correct-horse-battery"
    )


@pytest.fixture
def credentialed_membership(agency_a, credentialed_user):
    with tenant_scope(agency_a.id):
        return Membership.objects.create(
            tenant=agency_a, user=credentialed_user, role=Membership.Role.STUDENT
        )


def _post(client, url, payload, host):
    return client.post(url, json.dumps(payload), content_type="application/json",
                       HTTP_HOST=host)


def test_login_authenticates_and_starts_a_session(
    client, domain_a, credentialed_user, credentialed_membership
):
    response = _post(
        client,
        LOGIN,
        {"username": "student-login", "password": "correct-horse-battery"},
        domain_a.host,
    )

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert client.session.get("_auth_user_id") == str(credentialed_user.pk)


def test_a_wrong_password_is_401_and_starts_no_session(
    client, domain_a, credentialed_user, credentialed_membership
):
    response = _post(
        client, LOGIN, {"username": "student-login", "password": "wrong"}, domain_a.host
    )

    assert response.status_code == 401
    assert "_auth_user_id" not in client.session


def test_a_missing_user_is_the_same_401_as_a_wrong_password(client, domain_a):
    """Same status, same body: a different answer here is a username oracle."""
    response = _post(
        client, LOGIN, {"username": "nobody", "password": "wrong"}, domain_a.host
    )

    assert response.status_code == 401
    assert response.json() == {"error": "invalid_credentials"}


def test_login_attempts_are_rate_limited(
    client, domain_a, credentialed_user, credentialed_membership
):
    """There is no actor id before authentication, so the limiter keys on a
    stable integer derived from the submitted username -- keying on the
    client address would limit a whole university's NAT together."""
    for _ in range(10):
        _post(client, LOGIN, {"username": "student-login", "password": "wrong"},
              domain_a.host)

    response = _post(
        client, LOGIN, {"username": "student-login", "password": "wrong"}, domain_a.host
    )

    assert response.status_code == 429


def test_get_issues_the_csrf_cookie_a_post_needs(domain_a):
    """The reason GET exists. With CSRF enforced, a client that has never made
    a request has no token to send, so a POST-only login route is unusable
    from a browser."""
    strict = Client(enforce_csrf_checks=True)

    seeded = strict.get(LOGIN, HTTP_HOST=domain_a.host)

    assert seeded.status_code == 200
    assert "csrftoken" in strict.cookies


def test_a_post_without_a_csrf_token_is_refused(domain_a, credentialed_user):
    strict = Client(enforce_csrf_checks=True)

    response = strict.post(
        LOGIN,
        json.dumps({"username": "student-login", "password": "correct-horse-battery"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 403


def test_a_body_that_is_not_json_is_a_400(client, domain_a):
    response = client.post(
        LOGIN, "not json", content_type="application/json", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_json"}


def test_logout_ends_the_session(client, domain_a, user_a, membership_a):
    client.force_login(user_a)

    response = client.post(LOGOUT, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_logout_refuses_a_get(client, domain_a, user_a, membership_a):
    """A GET that logs you out is a CSRF hole dressed as a convenience."""
    client.force_login(user_a)

    assert client.get(LOGOUT, HTTP_HOST=domain_a.host).status_code == 405
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -v`
Expected: FAIL — every test 404s, there is no `/api/auth/login` route.

- [ ] **Step 3: Write the module**

Create `apps/documents/api.py`:

```python
"""The document engine's door: JSON over HTTP, no presentation layer.

Deliberately not DRF and deliberately not a template. The engine behind this
was complete and unreachable; what it needed was a caller, not a framework.
The presentation layer that eventually consumes these endpoints is still
undecided, and nothing here settles it.

Every document endpoint resolves ``current_membership(request, STUDENT)``
through ``_student_endpoint`` and receives that membership as an argument, so
the authorisation check and the ledger being written are the same object --
there is no way to pass the check and then act for a different student. A
counselor session gets 403 here: there is no staff surface behind this door
(staff login additionally needs an OTP-verify endpoint, which is separate
work).

Refusals on id-addressed endpoints are 404, never 403, matching
storage.download_document: a 403 would confirm the object exists.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import Callable
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from apps.ratelimit import rate_limited
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .models import DocumentDraft

#: The one place a document kind is validated. The motivation-letter engine
#: widens this set; it adds no route, no queue and no task definition.
_SUPPORTED_KINDS = frozenset({DocumentDraft.Kind.CV})

#: Ten failed sign-ins in fifteen minutes is generous for someone who has
#: forgotten which of two passwords they used, and a hard stop for a script.
_LOGIN_RATE_LIMIT = 10
_LOGIN_RATE_WINDOW_SECONDS = 900

_View = Callable[..., HttpResponse]


class _ApiError(Exception):
    """A refusal with a status and a stable machine-readable code.

    The code is the contract with whatever renders this: it is matched on, so
    it must not be a sentence anyone will later reword.
    """

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _json_errors(view: _View) -> _View:
    @wraps(view)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        try:
            return view(request, *args, **kwargs)
        except _ApiError as error:
            return JsonResponse({"error": error.code}, status=error.status)

    return _wrapped


def _student_endpoint(view: _View) -> _View:
    """Authenticated + STUDENT in this tenant, resolved once, passed in.

    401 for "not signed in" and 403 for "not a student here" are both
    object-independent, so neither reveals anything: the id-addressed
    refusals inside the views are 404.

    Not django.contrib.auth.decorators.login_required, which redirects: a 302
    to a login page is not an answer a JSON client can act on.
    """

    @wraps(view)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication_required"}, status=401)
        try:
            student = current_membership(request, Membership.Role.STUDENT)
        except PermissionDenied:
            return JsonResponse({"error": "student_membership_required"}, status=403)
        return view(request, student, *args, **kwargs)

    return _json_errors(_wrapped)


def _json_body(request: HttpRequest) -> dict[str, object]:
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        raise _ApiError(400, "invalid_json") from None
    if not isinstance(body, dict):
        raise _ApiError(400, "invalid_json")
    return body


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
@_json_errors
def auth_login(request: HttpRequest) -> HttpResponse:
    """GET issues the CSRF cookie; POST signs in.

    GET is not a spare endpoint. CsrfViewMiddleware rejects a POST with no
    token, and a client that has never made a request has no cookie to build
    one from -- so a POST-only login route cannot be used from a browser at
    all. One route with two methods beats a second endpoint nobody remembers
    to call first.

    The rate limiter keys on a stable integer derived from the submitted
    username, because there is no actor id before authentication and
    rate_limited takes UUID | int. Keying on the client address would limit a
    whole university's NAT together; keying on the username limits the
    account actually under attack.

    A wrong password and an unknown username give the identical response. A
    different one is a username oracle.
    """
    if request.method == "GET":
        return JsonResponse({"authenticated": request.user.is_authenticated})
    body = _json_body(request)
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    if rate_limited(
        "api-login",
        zlib.crc32(username.encode()),
        limit=_LOGIN_RATE_LIMIT,
        window_seconds=_LOGIN_RATE_WINDOW_SECONDS,
    ):
        raise _ApiError(429, "rate_limited")
    user = authenticate(request, username=username, password=password)
    if user is None:
        raise _ApiError(401, "invalid_credentials")
    login(request, user)
    return JsonResponse({"authenticated": True})


@require_POST
def auth_logout(request: HttpRequest) -> HttpResponse:
    """POST only. A GET that ends a session is a CSRF hole dressed as a
    convenience -- any page can make the browser issue one."""
    logout(request)
    return JsonResponse({"authenticated": False})
```

Then in `apps/documents/urls.py`, add the import and the two routes:

```python
from django.urls import path

from . import api, views

urlpatterns = [
    path(
        "documents/<uuid:draft_id>/<str:filename>",
        views.download_document,
        name="documents-download",
    ),
    path("student/gap-interview/", views.gap_interview, name="student-gap-interview"),
    path("api/auth/login", api.auth_login, name="api-auth-login"),
    path("api/auth/logout", api.auth_logout, name="api-auth-logout"),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/api.py apps/documents/urls.py tests/documents/test_api.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): a way in, and the shape every endpoint behind it shares

Nothing in this repo included django.contrib.auth.urls or called login(),
so session authentication had no way to begin. GET issues the CSRF cookie
a browser needs before it can POST; the limiter keys on the submitted
username because there is no actor id yet."
```

---

### Task 9: The upload endpoints

`GET /api/documents/uploads/<id>` is not optional. `ingest_uploaded_cv` returns `()` when extraction fails, so without it BLOCKED (malware found) is indistinguishable from "nothing extracted" — and a student who uploaded an infected file has to be told.

**Files:**
- Modify: `apps/documents/api.py`, `apps/documents/urls.py`
- Test: `tests/documents/test_api.py`

**Interfaces:**
- Consumes: `apps.concierge.documents.register(tenant_id, student_id)` and `presigned_upload(document, client=None)` (Task 3); `apps.tenancy.context.current_tenant_id`; `apps.concierge.models.DocumentVersion`.
- Produces: `uploads` (POST) and `upload_status` (GET) views; routes `api-documents-uploads` and `api-documents-upload-status`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_api.py`:

```python
from apps.concierge.documents import apply_scan_result, register

UPLOADS = "/api/documents/uploads"


def test_an_upload_returns_a_form_scoped_to_a_new_document(
    client, domain_a, user_a, membership_a, monkeypatch
):
    import apps.documents.api as api

    monkeypatch.setattr(
        api,
        "presigned_upload",
        lambda document: {
            "url": "https://s3.example.test/bucket",
            "fields": {"key": document.object_key},
        },
    )
    client.force_login(user_a)

    response = client.post(UPLOADS, HTTP_HOST=domain_a.host)

    assert response.status_code == 201
    body = response.json()
    assert body["fields"]["key"].startswith(f"quarantine/{domain_a.agency_id}/")
    assert body["fields"]["key"].endswith(body["document_id"])


def test_an_upload_needs_a_student_session(client, domain_a, counselor_user,
                                           counselor_membership):
    """There is no staff surface behind this door."""
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.post(UPLOADS, HTTP_HOST=domain_a.host)

    assert response.status_code == 403


def test_an_anonymous_upload_is_401(client, domain_a):
    assert client.post(UPLOADS, HTTP_HOST=domain_a.host).status_code == 401


def test_upload_issuance_is_rate_limited(client, domain_a, user_a, membership_a,
                                         monkeypatch):
    """A signed form is a write capability into the evidence bucket. Issuing
    them without a ceiling is issuing unlimited ones."""
    import apps.documents.api as api

    monkeypatch.setattr(api, "presigned_upload", lambda document: {"url": "", "fields": {}})
    client.force_login(user_a)
    for _ in range(10):
        client.post(UPLOADS, HTTP_HOST=domain_a.host)

    assert client.post(UPLOADS, HTTP_HOST=domain_a.host).status_code == 429


def test_the_poll_reports_the_scan_verdict(client, domain_a, user_a, membership_a):
    """BLOCKED must be distinguishable from 'nothing was extracted':
    ingest_uploaded_cv returns () for both, and a student whose file carried
    malware has to be told."""
    document = register(domain_a.agency_id, membership_a.id)
    apply_scan_result(document, "THREATS_FOUND")
    client.force_login(user_a)

    response = client.get(f"{UPLOADS}/{document.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert response.json() == {"state": "BLOCKED", "scan_result": "THREATS_FOUND"}


def test_another_students_upload_is_404(
    client, domain_a, user_a, membership_a, agency_a, django_user_model
):
    """404, not 403: a 403 confirms the document exists."""
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a,
            user=django_user_model.objects.create_user(username="other-student"),
            role=Membership.Role.STUDENT,
        )
    document = register(agency_a.id, other.id)
    client.force_login(user_a)

    response = client.get(f"{UPLOADS}/{document.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 404


def test_another_tenants_upload_is_404(
    client, domain_a, domain_b, user_a, membership_a, agency_b, membership_b
):
    document = register(agency_b.id, membership_b.id)
    client.force_login(user_a)

    response = client.get(f"{UPLOADS}/{document.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -k upload -v`
Expected: FAIL — 404 from the URL resolver on every one.

- [ ] **Step 3: Write the views**

Add to `apps/documents/api.py`'s imports:

```python
from uuid import UUID

from django.views.decorators.http import require_GET

from apps.concierge.documents import presigned_upload, register
from apps.concierge.models import DocumentVersion
from apps.tenancy.context import current_tenant_id
```

Add the constants beside the login ones:

```python
#: A signed form is a write capability into the evidence bucket, so issuing
#: them is limited the same way any other write is.
_UPLOAD_RATE_LIMIT = 10
_UPLOAD_RATE_WINDOW_SECONDS = 3600
```

And the two views:

```python
@require_POST
@_student_endpoint
def uploads(request: HttpRequest, student: Membership) -> HttpResponse:
    """Register a document row, and sign a form that can only fill that row.

    The key is never accepted from the caller: register() derives it from the
    row it creates, and the presigned conditions pin that exact key. A caller
    therefore cannot aim an upload outside its own tenant's prefix even by
    lying about every field it does control.
    """
    if rate_limited(
        "api-upload",
        student.id,
        limit=_UPLOAD_RATE_LIMIT,
        window_seconds=_UPLOAD_RATE_WINDOW_SECONDS,
    ):
        raise _ApiError(429, "rate_limited")
    document = register(current_tenant_id(), student.id)
    presigned = presigned_upload(document)
    return JsonResponse(
        {
            "document_id": str(document.id),
            "url": presigned["url"],
            "fields": presigned["fields"],
        },
        status=201,
    )


@require_GET
@_student_endpoint
def upload_status(request: HttpRequest, student: Membership, document_id: UUID) -> HttpResponse:
    """The poll target, and the only place BLOCKED is visible.

    Without this endpoint a student whose file carried malware sees exactly
    what a student whose file yielded no facts sees -- ingest_uploaded_cv
    returns () for both. The candidates list cannot stand in for it.
    """
    document = DocumentVersion.objects.filter(id=document_id, student=student).first()
    if document is None:
        raise _ApiError(404, "not_found")
    return JsonResponse({"state": document.state, "scan_result": document.scan_result})
```

Add the routes to `apps/documents/urls.py`:

```python
    path("api/documents/uploads", api.uploads, name="api-documents-uploads"),
    path(
        "api/documents/uploads/<uuid:document_id>",
        api.upload_status,
        name="api-documents-upload-status",
    ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/api.py apps/documents/urls.py tests/documents/test_api.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): issue an upload, and let the student see the verdict

The poll endpoint is not optional: ingest_uploaded_cv returns () both
when a file was blocked and when nothing extracted, so without it a
student whose upload carried malware is never told."
```

---

### Task 10: The fact endpoints — list candidates, confirm them

**Files:**
- Modify: `apps/documents/api.py`, `apps/documents/urls.py`
- Test: `tests/documents/test_api.py`

**Interfaces:**
- Consumes: `confirm_facts`, `FactNotFound` (Task 2); `apps.documents.verification.unsuperseded_facts`.
- Produces: `fact_candidates` (GET) and `confirm` (POST) views; routes `api-documents-fact-candidates` and `api-documents-fact-confirm`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_api.py`:

```python
from apps.documents.models import VerifiedFact

CANDIDATES = "/api/documents/facts/candidates"
CONFIRM = "/api/documents/facts/confirm"


def _candidate(student, name="Jane Doe"):
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": name},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="upload:test",
        confirmed_by=None,
        created_by=student,
    )


def test_the_candidate_list_is_unconfirmed_facts_only(
    client, domain_a, user_a, membership_a
):
    """A confirmed fact is not a candidate: showing it again invites a second
    click that means nothing."""
    with tenant_scope(domain_a.agency_id):
        pending = _candidate(membership_a)
        settled = _candidate(membership_a, name="Already Confirmed")
        settled.confirmed_by = membership_a
        settled.confirmed_at = pending.created_at
        settled.save(update_fields=["confirmed_by", "confirmed_at"])
    client.force_login(user_a)

    response = client.get(CANDIDATES, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [fact["id"] for fact in response.json()["facts"]] == [str(pending.id)]


def test_the_candidate_list_is_the_callers_ledger_only(
    client, domain_a, domain_b, user_a, membership_a, agency_b, membership_b
):
    with tenant_scope(agency_b.id):
        _candidate(membership_b, name="Someone Else")
    with tenant_scope(domain_a.agency_id):
        mine = _candidate(membership_a)
    client.force_login(user_a)

    response = client.get(CANDIDATES, HTTP_HOST=domain_a.host)

    assert [fact["id"] for fact in response.json()["facts"]] == [str(mine.id)]


def test_confirming_reports_how_many_changed(client, domain_a, user_a, membership_a):
    with tenant_scope(domain_a.agency_id):
        fact = _candidate(membership_a)
    client.force_login(user_a)

    response = _post(client, CONFIRM, {"fact_ids": [str(fact.id)]}, domain_a.host)

    assert response.status_code == 200
    assert response.json() == {"confirmed": 1}
    fact.refresh_from_db()
    assert fact.confirmed_by_id == membership_a.id


def test_confirming_another_students_fact_is_404(
    client, domain_a, user_a, membership_a, agency_b, membership_b
):
    """404, not 403 -- a 403 confirms the fact exists."""
    with tenant_scope(agency_b.id):
        theirs = _candidate(membership_b, name="Someone Else")
    client.force_login(user_a)

    response = _post(client, CONFIRM, {"fact_ids": [str(theirs.id)]}, domain_a.host)

    assert response.status_code == 404


def test_a_malformed_fact_id_is_a_400(client, domain_a, user_a, membership_a):
    client.force_login(user_a)

    response = _post(client, CONFIRM, {"fact_ids": ["not-a-uuid"]}, domain_a.host)

    assert response.status_code == 400
    assert response.json() == {"error": "fact_ids_invalid"}


def test_an_empty_or_missing_fact_id_list_is_a_400(client, domain_a, user_a, membership_a):
    client.force_login(user_a)

    assert _post(client, CONFIRM, {"fact_ids": []}, domain_a.host).status_code == 400
    assert _post(client, CONFIRM, {}, domain_a.host).status_code == 400


def test_an_oversized_batch_is_refused_before_the_query(
    client, domain_a, user_a, membership_a
):
    """A cap on the list length, not on what it costs to find out it was
    wrong: 10,000 ids is one request that becomes one enormous IN clause."""
    from uuid import uuid4

    client.force_login(user_a)

    response = _post(
        client, CONFIRM, {"fact_ids": [str(uuid4()) for _ in range(201)]}, domain_a.host
    )

    assert response.status_code == 400
    assert response.json() == {"error": "too_many_fact_ids"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -k "candidate or confirm or fact" -v`
Expected: FAIL — 404 from the URL resolver.

- [ ] **Step 3: Write the views**

Add to `apps/documents/api.py`'s imports:

```python
from .confirmation import FactNotFound, confirm_facts
from .verification import unsuperseded_facts
```

Add the constants:

```python
#: Confirmation is a write per fact plus an audit row per fact. The cap is on
#: the request, so an absurd batch is refused before it becomes a query.
_CONFIRM_RATE_LIMIT = 60
_CONFIRM_RATE_WINDOW_SECONDS = 3600
_MAX_CONFIRM_BATCH = 200
```

And the two views:

```python
@require_GET
@_student_endpoint
def fact_candidates(request: HttpRequest, student: Membership) -> HttpResponse:
    """What the student is being asked to stand behind.

    Unsuperseded and unconfirmed, in the ledger's own order (oldest first),
    which is the order the uploaded CV listed things in.
    """
    facts = unsuperseded_facts(student).filter(confirmed_by__isnull=True)
    return JsonResponse(
        {
            "facts": [
                {"id": str(fact.id), "category": fact.category, "payload": fact.payload}
                for fact in facts
            ]
        }
    )


@require_POST
@_student_endpoint
def confirm(request: HttpRequest, student: Membership) -> HttpResponse:
    """The click. Everything downstream of it treats these as the student's own.

    ``actor`` is the student: approval_mode defaults to PER_DOCUMENT, so the
    student confirms their own ledger and this door adds no staff path.
    """
    if rate_limited(
        "api-confirm",
        student.id,
        limit=_CONFIRM_RATE_LIMIT,
        window_seconds=_CONFIRM_RATE_WINDOW_SECONDS,
    ):
        raise _ApiError(429, "rate_limited")
    raw = _json_body(request).get("fact_ids")
    if not isinstance(raw, list) or not raw:
        raise _ApiError(400, "fact_ids_required")
    if len(raw) > _MAX_CONFIRM_BATCH:
        raise _ApiError(400, "too_many_fact_ids")
    try:
        fact_ids = [UUID(str(value)) for value in raw]
    except ValueError:
        raise _ApiError(400, "fact_ids_invalid") from None
    try:
        confirmed = confirm_facts(student=student, fact_ids=fact_ids, actor=student)
    except FactNotFound:
        raise _ApiError(404, "not_found") from None
    return JsonResponse({"confirmed": confirmed})
```

Add the routes:

```python
    path(
        "api/documents/facts/candidates",
        api.fact_candidates,
        name="api-documents-fact-candidates",
    ),
    path("api/documents/facts/confirm", api.confirm, name="api-documents-fact-confirm"),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/api.py apps/documents/urls.py tests/documents/test_api.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): show a student their candidates and take the click

An id belonging to another student is 404, resolved through student=,
because a 403 would confirm the fact exists."
```

---

### Task 11: The generate endpoint — a pre-flight instead of a job table

This is what replaces `GenerationRequest`. `generate_cv`'s own first three checks are all cheap — an indexed read, a field read and a cache read — so the endpoint runs the same three and answers 409/429 synchronously. What stays asynchronous is model refusal and `GenerationFailure`, which are rare and land in the dead-letter queue.

The rename in this task is why it is one task and not two: `generation._rate_limited` is private, and the endpoint must run the *same* check rather than a re-typed copy of its constants.

**Files:**
- Modify: `apps/documents/generation.py:83-89` (rename), `apps/documents/api.py`, `apps/documents/urls.py`
- Test: `tests/documents/test_api.py`

**Interfaces:**
- Consumes: `generatable_facts`; `VerifiedFact.Category`; `enqueue_document_work`, `DocumentWorkMessage` (Task 4); `settings.DOCUMENT_QUEUE_URL` (Task 7).
- Produces: `apps.documents.generation.generation_rate_limited(actor_id: UUID) -> bool` (was `_rate_limited`); the `generate` view; route `api-documents-generate`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_api.py`:

```python
GENERATE = "/api/documents/generate"


@pytest.fixture
def queued(monkeypatch):
    """Captures enqueued work instead of calling SQS."""
    import apps.documents.api as api

    messages = []
    monkeypatch.setattr(api, "enqueue_document_work", lambda message, **kw: messages.append(message))
    return messages


def _generatable_student(agency_a, membership_a):
    """A student who passes all three pre-flight checks."""
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        fact.confirmed_by = membership_a
        fact.confirmed_at = fact.created_at
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
        membership_a.application_email = "student@mail.example.test"
        membership_a.save(update_fields=["application_email"])
    return membership_a


def test_generate_enqueues_exactly_one_message(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 202
    assert len(queued) == 1
    assert queued[0].action == "generate"
    assert queued[0].student_id == membership_a.id
    assert queued[0].tenant_id == agency_a.id


def test_an_unconfirmed_identity_is_409_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """The predictable failure a job table was going to report asynchronously.
    Every check here is cheap, so the student is told at request time."""
    with tenant_scope(agency_a.id):
        _candidate(membership_a)
        membership_a.application_email = "student@mail.example.test"
        membership_a.save(update_fields=["application_email"])
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 409
    assert response.json() == {"error": "identity_not_confirmed"}
    assert queued == []


def test_a_missing_application_email_is_409_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        fact.confirmed_by = membership_a
        fact.confirmed_at = fact.created_at
        fact.save(update_fields=["confirmed_by", "confirmed_at"])
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 409
    assert response.json() == {"error": "application_email_missing"}
    assert queued == []


def test_generation_is_rate_limited_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)
    for _ in range(10):
        _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    response = _post(client, GENERATE, {"kind": "CV"}, domain_a.host)

    assert response.status_code == 429
    assert len(queued) == 10


def test_an_unsupported_kind_is_400(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """DocumentDraft.Kind already carries MOTIVATION_LETTER and CORE_NARRATIVE.
    The letter engine widens _SUPPORTED_KINDS -- until it does, this door does
    not pretend to build one."""
    _generatable_student(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, GENERATE, {"kind": "MOTIVATION_LETTER"}, domain_a.host)

    assert response.status_code == 400
    assert queued == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -k generate -v`
Expected: FAIL — 404 from the URL resolver.

- [ ] **Step 3: Rename the limiter and write the view**

In `apps/documents/generation.py`, rename `_rate_limited` to `generation_rate_limited` (definition at line 83, one call site inside `generate_cv`) and give it a docstring saying why it is public:

```python
def generation_rate_limited(actor_id: UUID) -> bool:
    """Public because the generate endpoint runs this exact check up front.

    The endpoint and generate_cv are different processes with their own
    LocMemCache, so these are two independent counters rather than one budget
    spent twice -- see apps/ratelimit.py's own ponytail note.
    """
    return rate_limited(
        "cv_generation",
        actor_id,
        limit=_CV_GENERATION_RATE_LIMIT,
        window_seconds=_CV_GENERATION_RATE_WINDOW_SECONDS,
    )
```

Add to `apps/documents/api.py`'s imports:

```python
from django.conf import settings

from .document_queue import DocumentWorkMessage, enqueue_document_work
from .generation import generation_rate_limited
from .models import DocumentDraft, VerifiedFact
```

And the view:

```python
@require_POST
@_student_endpoint
def generate(request: HttpRequest, student: Membership) -> HttpResponse:
    """Queue a generation, after running generate_cv's own preconditions here.

    This is what replaces a job-state table. All three checks are cheap -- an
    indexed read, a field read, a cache read -- so every *predictable* failure
    is answered at request time and the client needs no polling to learn about
    it. What stays asynchronous is model refusal and GenerationFailure, which
    are rare and land in the dead-letter queue the existing alarm pattern
    already covers.

    Nothing is enqueued when a check fails: a queued message that is certain
    to fail is a dead-letter entry someone has to read.
    """
    kind = str(_json_body(request).get("kind") or DocumentDraft.Kind.CV)
    if kind not in _SUPPORTED_KINDS:
        raise _ApiError(400, "unsupported_kind")
    if not generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists():
        raise _ApiError(409, "identity_not_confirmed")
    if not student.application_email:
        raise _ApiError(409, "application_email_missing")
    if generation_rate_limited(student.id):
        raise _ApiError(429, "rate_limited")
    enqueue_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=kind,
            tenant_id=current_tenant_id(),
            student_id=student.id,
        ),
        queue_url=settings.DOCUMENT_QUEUE_URL,
    )
    return JsonResponse({"status": "queued"}, status=202)
```

Add `from .verification import generatable_facts, unsuperseded_facts` (widening Task 10's import) and the route:

```python
    path("api/documents/generate", api.generate, name="api-documents-generate"),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/ -v`
Expected: PASS — the whole documents suite, which is what proves the `_rate_limited` rename broke nothing.

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/api.py apps/documents/generation.py apps/documents/urls.py tests/documents/test_api.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): queue a generation behind the checks that can answer now

The pre-flight is what replaces a job-state table: generate_cv's first
three checks are an indexed read, a field read and a cache read, so
every predictable failure is a synchronous 409/429 and nothing is
enqueued that is certain to fail."
```

---

### Task 12: The draft endpoints — list, read with verdicts, approve

`GET /api/documents/drafts` is how a client learns a generation finished; there is no job row to poll.

**Files:**
- Modify: `apps/documents/api.py`, `apps/documents/urls.py`
- Test: `tests/documents/test_api.py`

**Interfaces:**
- Consumes: `apps.documents.approval.ApprovalBlocked`, `mark_ready`, `verdicts_for`; `DocumentDraft`; `enqueue_document_work` (Task 4).
- Produces: `drafts`, `draft_detail`, `approve` views; routes `api-documents-drafts`, `api-documents-draft`, `api-documents-draft-approve`. This is the last endpoint; the door is complete after it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_api.py`:

```python
from apps.documents.drafts import create_draft
from apps.documents.models import DocumentDraft
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation

DRAFTS = "/api/documents/drafts"


def _cv_content(name="Jane Doe"):
    return CVContent(
        personal_information=PersonalInformation(full_name=name, email="jane@example.com"),
        education=(
            EducationEntry(
                degree_as_awarded="BSc",
                institution_original="Example U",
                city="Berlin",
                country="DE",
                start_date="2020-09-01",
            ),
        ),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _draft_for(agency, student, name="Jane Doe"):
    with tenant_scope(agency.id):
        return create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_cv_content(name)
        )


def test_the_draft_list_is_newest_first(client, domain_a, user_a, membership_a, agency_a):
    """This is how the client learns a generation finished -- there is no job
    row to poll, by design."""
    _draft_for(agency_a, membership_a)
    second = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(DRAFTS, HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    versions = [draft["version"] for draft in response.json()["drafts"]]
    assert versions == [2, 1]
    assert response.json()["drafts"][0]["id"] == str(second.id)


def test_a_draft_reads_back_with_its_verdicts(
    client, domain_a, user_a, membership_a, agency_a
):
    """Verdicts are computed against the live ledger, not stored: the review
    overlay must show what mark_ready will find, not what was true when the
    draft was written."""
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        identity.confirmed_by = membership_a
        identity.confirmed_at = identity.created_at
        identity.save(update_fields=["confirmed_by", "confirmed_at"])
    draft = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    body = response.json()
    assert body["content"]["personal_information"]["full_name"] == "Jane Doe"
    assert {verdict["claim_path"] for verdict in body["verdicts"]}


def test_another_students_draft_is_404(
    client, domain_a, user_a, membership_a, agency_b, membership_b
):
    draft = _draft_for(agency_b, membership_b)
    client.force_login(user_a)

    assert client.get(f"{DRAFTS}/{draft.id}", HTTP_HOST=domain_a.host).status_code == 404


def test_approve_marks_ready_and_enqueues_one_render(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    with tenant_scope(agency_a.id):
        identity = _candidate(membership_a)
        identity.confirmed_by = membership_a
        identity.confirmed_at = identity.created_at
        identity.save(update_fields=["confirmed_by", "confirmed_at"])
    draft = _draft_for(agency_a, membership_a)
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 202
    draft.refresh_from_db()
    assert draft.status == DocumentDraft.Status.APPROVED
    assert [message.action for message in queued] == ["render"]
    assert queued[0].draft_id == draft.id


def test_a_blocked_approval_is_409_with_its_verdicts_and_enqueues_nothing(
    client, domain_a, user_a, membership_a, agency_a, queued
):
    """A name nothing in the ledger supports blocks release. The student is
    shown which claims blocked it -- that list is the only actionable part of
    the refusal -- and no render is queued for a document that never
    approved."""
    draft = _draft_for(agency_a, membership_a, name="Unsupported Name")
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 409
    assert response.json()["error"] == "approval_blocked"
    assert response.json()["verdicts"]
    assert queued == []
    draft.refresh_from_db()
    assert draft.status == DocumentDraft.Status.DRAFT


def test_approving_another_students_draft_is_404(
    client, domain_a, user_a, membership_a, agency_b, membership_b, queued
):
    draft = _draft_for(agency_b, membership_b)
    client.force_login(user_a)

    response = _post(client, f"{DRAFTS}/{draft.id}/approve", {}, domain_a.host)

    assert response.status_code == 404
    assert queued == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/test_api.py -k draft -v`
Expected: FAIL — 404 from the URL resolver.

- [ ] **Step 3: Write the views**

Add to `apps/documents/api.py`'s imports:

```python
from .approval import ApprovalBlocked, mark_ready, verdicts_for
```

And the three views:

```python
@require_GET
@_student_endpoint
def drafts(request: HttpRequest, student: Membership) -> HttpResponse:
    """Newest first. This is how the client learns a generation finished.

    There is no job row: a generation that succeeded is a draft, and one that
    failed is a dead-letter message with an alarm on it.
    """
    kind = request.GET.get("kind") or DocumentDraft.Kind.CV
    if kind not in _SUPPORTED_KINDS:
        raise _ApiError(400, "unsupported_kind")
    rows = (
        DocumentDraft.objects.filter(student=student, kind=kind)
        .order_by("-version")
        .values("id", "version", "status")
    )
    return JsonResponse(
        {
            "drafts": [
                {"id": str(row["id"]), "version": row["version"], "status": row["status"]}
                for row in rows
            ]
        }
    )


@require_GET
@_student_endpoint
def draft_detail(request: HttpRequest, student: Membership, draft_id: UUID) -> HttpResponse:
    """The document, plus what the ledger currently says about each claim.

    claim_text is included: this is a response to the student's own browser,
    not a log line, and the review it drives is unusable without the text of
    the claim being judged. The rule it must not break is the other one --
    document text never reaches an exception message or a log.
    """
    draft = DocumentDraft.objects.filter(id=draft_id, student=student).first()
    if draft is None:
        raise _ApiError(404, "not_found")
    try:
        verdicts = verdicts_for(draft)
    except ApprovalBlocked:
        raise _ApiError(409, "malformed_content") from None
    return JsonResponse(
        {
            "id": str(draft.id),
            "version": draft.version,
            "status": draft.status,
            "content": draft.content,
            "verdicts": [
                {
                    "claim_path": verdict.claim_path,
                    "claim_text": verdict.claim_text,
                    "verdict": str(verdict.verdict),
                    "fact_id": str(verdict.fact_id) if verdict.fact_id else None,
                }
                for verdict in verdicts
            ],
        }
    )


@require_POST
@_student_endpoint
def approve(request: HttpRequest, student: Membership, draft_id: UUID) -> HttpResponse:
    """Consent, then a render.

    mark_ready recomputes verdicts under lock from the draft's own content --
    nothing the caller sends can assert a draft is clean, and this endpoint
    deliberately offers no field that could. The render is enqueued only
    after approval succeeds: the worker's render path refuses a draft that is
    not APPROVED anyway, so a message sent before that is a guaranteed
    dead letter.
    """
    draft = DocumentDraft.objects.filter(id=draft_id, student=student).first()
    if draft is None:
        raise _ApiError(404, "not_found")
    try:
        approved = mark_ready(document=draft, accepted_by=student)
    except ApprovalBlocked as error:
        return JsonResponse(
            {
                "error": "approval_blocked",
                "verdicts": [
                    {
                        "claim_path": verdict.claim_path,
                        "claim_text": verdict.claim_text,
                        "verdict": str(verdict.verdict),
                    }
                    for verdict in error.verdicts
                ],
            },
            status=409,
        )
    enqueue_document_work(
        DocumentWorkMessage(
            action="render",
            kind=approved.kind,
            tenant_id=current_tenant_id(),
            student_id=student.id,
            draft_id=approved.id,
        ),
        queue_url=settings.DOCUMENT_QUEUE_URL,
    )
    return JsonResponse({"status": "queued"}, status=202)
```

Add the routes:

```python
    path("api/documents/drafts", api.drafts, name="api-documents-drafts"),
    path("api/documents/drafts/<uuid:draft_id>", api.draft_detail, name="api-documents-draft"),
    path(
        "api/documents/drafts/<uuid:draft_id>/approve",
        api.approve,
        name="api-documents-draft-approve",
    ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/documents/ -v`
Expected: PASS (the whole documents suite, 29 tests in `test_api.py`)

- [ ] **Step 5: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add apps/documents/api.py apps/documents/urls.py tests/documents/test_api.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(documents): read a draft with its verdicts, and approve it into a render

The draft list is how a client learns a generation finished -- there is
no job row by design. A blocked approval returns the blocking verdicts
and queues nothing: the worker refuses a draft that never approved, so
that message would only ever be a dead letter."
```

---

### Task 13: Infrastructure — two queues, one worker service, and one changed trust boundary

Three of these change existing resources, and two of those break existing tests **on purpose**. Read this before editing:

1. **`WebTaskRole` gains `s3:PutObject` on `quarantine/*` — and nothing else.** A presigned POST is signed with the caller's own credentials and grants no more than the signer has, so without this every upload 403s. `test_web_task_role_can_enqueue_but_not_write_evidence` and `test_only_worker_task_role_may_read_quarantined_uploads` both assert the web role has *no* such grant today; they are narrowed rather than deleted, because what they were protecting is still true and still worth pinning: the web tier may not write `tenants/*` (the released artefacts) and may not **read** `quarantine/*` (an uploaded file's bytes). Write-only, one prefix.
2. **`config/settings/production.py` now requires two more variables**, so all five task definitions must supply them. `test_app_task_definitions_supply_every_production_required_env_var` is the structural test that catches a miss — extend `_PRODUCTION_REQUIRED_ENV_VARS` *and* its parametrize list.
3. **A new service log group must be watched.** `test_every_long_running_service_log_group_is_watched` fails on any `AWS::Logs::LogGroup` with no metric filter — that test exists because `BrowserLogGroup` shipped unmonitored and every render failed in silence.

**Files:**
- Modify: `infra/template.yaml`
- Test: `tests/infra/test_template.py`

**Interfaces:**
- Consumes: `settings.DOCUMENT_QUEUE_URL` / `DOCUMENT_SCAN_QUEUE_URL` (Task 7); the `run_document_worker` command (Task 7); `presigned_upload` (Task 3).
- Produces: `DocumentQueue`, `DocumentScanQueue` and their DLQs; `DocumentScanRule`; `DocumentWorkerTaskDefinition`/`Role`/`Service`/`LogGroup`. Nothing later consumes these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infra/test_template.py`:

```python
# --- The document engine's door ---------------------------------------------


@pytest.mark.parametrize("queue_id", ["DocumentQueue", "DocumentScanQueue"])
def test_the_document_queues_have_dead_letter_queues(template: Template, queue_id: str) -> None:
    queue = template.resource(queue_id)["Properties"]
    assert queue["KmsMasterKeyId"] == "alias/aws/sqs"
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3


@pytest.mark.parametrize(
    "alarm_id",
    [
        "DocumentQueueAgeAlarm",
        "DocumentDeadLetterDepthAlarm",
        "DocumentScanQueueAgeAlarm",
        "DocumentScanDeadLetterDepthAlarm",
    ],
)
def test_the_document_queues_are_alarmed(template: Template, alarm_id: str) -> None:
    """A wedged document queue is a student's CV that never generates, with no
    other signal: there is no job-state row for a frontend to report on."""
    assert template.resource(alarm_id)["Type"] == "AWS::CloudWatch::Alarm"


@pytest.mark.parametrize(
    ("alarm_id", "queue_id"),
    [
        ("DocumentQueueAgeAlarm", "DocumentQueue"),
        ("DocumentScanQueueAgeAlarm", "DocumentScanQueue"),
    ],
)
def test_a_document_age_alarm_outlasts_its_whole_retry_envelope(
    template: Template, alarm_id: str, queue_id: str
) -> None:
    """Same relationship the Europass alarm keeps: with maxReceiveCount 3, a
    message that fails twice legitimately ages VisibilityTimeout x 2 before it
    reaches the DLQ. An alarm tighter than that pages on ordinary redelivery.
    If you raise VisibilityTimeout, this has to move with it."""
    queue = template.resource(queue_id)["Properties"]
    alarm = template.resource(alarm_id)["Properties"]
    assert alarm["Threshold"] >= queue["VisibilityTimeout"] * 2


def test_the_scan_rule_matches_guardduty_object_scan_results(template: Template) -> None:
    """Pattern verified against AWS's published samples. detail-type and source
    are the whole match: the handler re-checks the bucket itself, because this
    rule is account-wide."""
    rule = template.resource("DocumentScanRule")["Properties"]
    assert rule["EventPattern"] == {
        "detail-type": ["GuardDuty Malware Protection Object Scan Result"],
        "source": ["aws.guardduty"],
    }
    (target,) = rule["Targets"]
    assert target["Arn"] == {"Fn::GetAtt": "DocumentScanQueue.Arn"}


def test_eventbridge_may_send_to_the_scan_queue(template: Template) -> None:
    """A rule with no queue policy is a rule whose deliveries are silently
    dropped -- the scan verdict simply never arrives, and the only symptom is
    documents stuck at QUARANTINED forever."""
    policy = template.resource("DocumentScanQueuePolicy")["Properties"]
    statement = policy["PolicyDocument"]["Statement"][0]
    assert statement["Principal"] == {"Service": "events.amazonaws.com"}
    assert statement["Action"] == "sqs:SendMessage"
    assert statement["Condition"]["ArnEquals"]["aws:SourceArn"] == {
        "Fn::GetAtt": "DocumentScanRule.Arn"
    }


def test_the_document_worker_reads_quarantine_and_writes_tenant_objects(
    template: Template,
) -> None:
    """One task holds both grants: quarantine/* read for the scan-and-ingest
    path, tenants/* write for the render path -- the shape WorkerTaskRole
    already has. Splitting into two task definitions is the named upgrade
    path, not a requirement today."""
    role = template.resource("DocumentWorkerTaskRole")
    assert _object_actions(role, "${EvidenceBucket.Arn}/quarantine/*") == {"s3:GetObject"}
    assert _object_actions(role, "${EvidenceBucket.Arn}/tenants/*") == {
        "s3:GetObject",
        "s3:PutObject",
    }
    assert "s3:DeleteObject" not in _policy_actions(role)


def test_the_document_worker_may_hand_off_to_the_europass_queue(template: Template) -> None:
    """A EUROPASS_API draft is enqueued, never rendered here: that queue is
    single-worker and pinned for the circuit breaker and the courtesy rate."""
    actions = _policy_actions(template.resource("DocumentWorkerTaskRole"))
    assert "sqs:SendMessage" in actions


def test_the_web_tier_may_write_an_upload_but_never_read_one(template: Template) -> None:
    """The presigned POST is signed with WebTaskRole's own credentials, so the
    upload cannot work without PutObject on quarantine/*. Read stays worker-only
    (ingestion opens the scanned-clean original), and tenants/* -- the released
    artefacts -- stays unwritable from the web tier entirely."""
    web = template.resource("WebTaskRole")
    assert _object_actions(web, "${EvidenceBucket.Arn}/quarantine/*") == {"s3:PutObject"}
    assert "s3:PutObject" not in _object_actions(web, "${EvidenceBucket.Arn}/tenants/*")
    assert "s3:GetObject" not in _object_actions(web, "${EvidenceBucket.Arn}/quarantine/*")


def test_the_document_worker_is_its_own_service(template: Template) -> None:
    assert template.resource("DocumentWorkerService")["Type"] == "AWS::ECS::Service"
```

Then **narrow** the two existing tests rather than deleting them:

```python
def test_web_task_role_can_enqueue_but_not_write_evidence(template: Template) -> None:
    """Narrowed, not weakened: the web tier signs uploads into quarantine/,
    which is why it holds PutObject there (see
    test_the_web_tier_may_write_an_upload_but_never_read_one). What it must
    never write is tenants/ -- the released, approved artefacts."""
    web_actions = _policy_actions(template.resource("WebTaskRole"))
    assert "sqs:SendMessage" in web_actions
    assert "s3:PutObject" not in _object_actions(
        template.resource("WebTaskRole"), "${EvidenceBucket.Arn}/tenants/*"
    )


def test_only_worker_task_role_may_read_quarantined_uploads(template: Template) -> None:
    """Ingestion (apps/documents/ingestion.py) opens the scanned-clean original
    worker-side; the web tier never READS a quarantined object. It signs
    uploads into that prefix, which is a write."""
    quarantine_objects = "${EvidenceBucket.Arn}/quarantine/*"
    worker = _object_actions(template.resource("WorkerTaskRole"), quarantine_objects)
    assert worker == {"s3:GetObject", "s3:GetObjectVersion"}
    assert "s3:GetObject" not in _object_actions(
        template.resource("WebTaskRole"), quarantine_objects
    )
    assert "s3:GetObjectVersion" not in _object_actions(
        template.resource("WebTaskRole"), quarantine_objects
    )
```

And extend the two production-env structures:

```python
_PRODUCTION_REQUIRED_ENV_VARS = frozenset(
    {
        "DJANGO_ALLOWED_HOSTS",
        "RESEARCH_QUEUE_URL",
        "EUROPASS_QUEUE_URL",
        "DOCUMENT_QUEUE_URL",
        "DOCUMENT_SCAN_QUEUE_URL",
        "DJANGO_SECRET_KEY",
    }
)
```

```python
@pytest.mark.parametrize(
    "task_definition_id",
    [
        "WebTaskDefinition",
        "WorkerTaskDefinition",
        "MigrationTaskDefinition",
        "EuropassWorkerTaskDefinition",
        "DocumentWorkerTaskDefinition",
    ],
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/infra/test_template.py -v`
Expected: FAIL — `DocumentQueue is not defined in infra/template.yaml`, plus the five env-var parametrizations and the two narrowed role tests.

- [ ] **Step 3: Add the queues, the rule and its policy**

In `infra/template.yaml`, after `EuropassDeadLetterDepthAlarm` (ends line 711), add:

```yaml
  # --- The document engine's two queues --------------------------------------
  #
  # DocumentScanQueue receives GuardDuty's object scan verdict via EventBridge.
  # Polling the S3 object tag instead would need a quarantine/ read grant for
  # WebTaskRole, which this template refuses on purpose; an HTTP webhook would
  # add a public trust boundary needing shared-secret auth and replay
  # protection, for no gain.
  #
  # VisibilityTimeout 900 on both: each handler holds one model call
  # (extraction on the scan path, generation on the work path, the latter
  # capped at 20,000 output tokens and able to make two calls).

  DocumentScanDeadLetterQueue:
    Type: AWS::SQS::Queue
    Properties:
      KmsMasterKeyId: alias/aws/sqs

  DocumentScanQueue:
    Type: AWS::SQS::Queue
    Properties:
      KmsMasterKeyId: alias/aws/sqs
      VisibilityTimeout: 900
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt DocumentScanDeadLetterQueue.Arn
        maxReceiveCount: 3

  DocumentDeadLetterQueue:
    Type: AWS::SQS::Queue
    Properties:
      KmsMasterKeyId: alias/aws/sqs

  DocumentQueue:
    Type: AWS::SQS::Queue
    Properties:
      KmsMasterKeyId: alias/aws/sqs
      VisibilityTimeout: 900
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt DocumentDeadLetterQueue.Arn
        maxReceiveCount: 3

  # detail-type and source only. The rule is account-wide, so the handler
  # re-checks the bucket name itself (apps/documents/document_worker.py) --
  # another bucket's scan is not ours to act on.
  #
  # Deliberately NOT subscribed: "GuardDuty Malware Protection Post Scan Action
  # Failed" (tagging failed) and the three Resource Status events. The verdict
  # is read from the event, never from the object tag, so a tagging failure
  # does not affect this path.
  DocumentScanRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Deliver GuardDuty object scan verdicts to the document worker
      EventPattern:
        detail-type: ["GuardDuty Malware Protection Object Scan Result"]
        source: ["aws.guardduty"]
      Targets:
        - Id: DocumentScanQueue
          Arn: !GetAtt DocumentScanQueue.Arn

  # Without this the rule's deliveries are dropped silently and every upload
  # stays QUARANTINED forever, with no failing alarm anywhere to say so.
  DocumentScanQueuePolicy:
    Type: AWS::SQS::QueuePolicy
    Properties:
      Queues: [!Ref DocumentScanQueue]
      PolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: {Service: events.amazonaws.com}
            Action: sqs:SendMessage
            Resource: !GetAtt DocumentScanQueue.Arn
            Condition:
              ArnEquals:
                aws:SourceArn: !GetAtt DocumentScanRule.Arn

  # Threshold governed by the RETRY envelope, not drain time: with
  # VisibilityTimeout 900 and maxReceiveCount 3, a message that fails twice
  # legitimately ages ~1800s before it reaches the DLQ, so anything tighter
  # pages on ordinary redelivery. tests/infra/test_template.py pins that
  # relationship -- if you raise VisibilityTimeout, these move with it.
  DocumentQueueAgeAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/SQS
      MetricName: ApproximateAgeOfOldestMessage
      Dimensions:
        - Name: QueueName
          Value: !GetAtt DocumentQueue.QueueName
      Statistic: Maximum
      Period: 60
      EvaluationPeriods: 5
      Threshold: 1800
      ComparisonOperator: GreaterThanThreshold

  DocumentScanQueueAgeAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/SQS
      MetricName: ApproximateAgeOfOldestMessage
      Dimensions:
        - Name: QueueName
          Value: !GetAtt DocumentScanQueue.QueueName
      Statistic: Maximum
      Period: 60
      EvaluationPeriods: 5
      Threshold: 1800
      ComparisonOperator: GreaterThanThreshold

  DocumentDeadLetterDepthAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions:
        - Name: QueueName
          Value: !GetAtt DocumentDeadLetterQueue.QueueName
      Statistic: Maximum
      Period: 60
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold

  DocumentScanDeadLetterDepthAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions:
        - Name: QueueName
          Value: !GetAtt DocumentScanDeadLetterQueue.QueueName
      Statistic: Maximum
      Period: 60
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
```

- [ ] **Step 4: Add the worker's role, log group, task definition and service**

After `EuropassWorkerTaskRole` (ends line 972), add:

```yaml
  # One task holds both grants: quarantine/* read for the scan-and-ingest path
  # and tenants/* write for the render path -- the shape WorkerTaskRole already
  # has. sqs:SendMessage on EuropassQueue is the hand-off for a EUROPASS_API
  # draft, which must go through that pinned worker rather than be rendered
  # here.
  #
  # ponytail: one worker holds both grants; split the task definition if the
  # scan path ever needs to run untrusted code.
  DocumentWorkerTaskRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: {Service: ecs-tasks.amazonaws.com}
            Action: sts:AssumeRole
      Policies:
        - PolicyName: ConsumeDocumentQueuesAndRenderTenantObjects
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action:
                  - sqs:ReceiveMessage
                  - sqs:DeleteMessage
                  - sqs:GetQueueAttributes
                Resource:
                  - !GetAtt DocumentQueue.Arn
                  - !GetAtt DocumentScanQueue.Arn
              - Effect: Allow
                Action: sqs:SendMessage
                Resource: !GetAtt EuropassQueue.Arn
              # Read only, and only the quarantined original: ingestion opens
              # the scanned-clean upload once (apps/documents/ingestion.py).
              - Effect: Allow
                Action: s3:GetObject
                Resource: !Sub "${EvidenceBucket.Arn}/quarantine/*"
              # The render path stores the artefact, and store_document also
              # reads when re-storing bytes under a draft's own key. Never
              # delete: erasure is WorkerTaskRole's, and only its.
              - Effect: Allow
                Action:
                  - s3:GetObject
                  - s3:PutObject
                Resource: !Sub "${EvidenceBucket.Arn}/tenants/*"
```

Add the log group next to `EuropassWorkerLogGroup` (line 1185):

```yaml
  DocumentWorkerLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/tehsil/app/${AWS::StackName}/document-worker"
      RetentionInDays: 30
```

Add `- !Sub "${DocumentWorkerLogGroup.Arn}:*"` to `AppExecutionRole`'s `logs:PutLogEvents` resource list (line 860).

Add the task definition and service after `EuropassWorkerService` (ends line 1263):

```yaml
  DocumentWorkerTaskDefinition:
    Type: AWS::ECS::TaskDefinition
    Properties:
      RequiresCompatibilities: [FARGATE]
      NetworkMode: awsvpc
      Cpu: "512"
      Memory: "1024"
      ExecutionRoleArn: !GetAtt AppExecutionRole.Arn
      TaskRoleArn: !GetAtt DocumentWorkerTaskRole.Arn
      ContainerDefinitions:
        - Name: document-worker
          Image: !Ref AppImage
          Essential: true
          Command: ["python", "manage.py", "run_document_worker"]
          Environment:
            - Name: DJANGO_SETTINGS_MODULE
              Value: config.settings.production
            - Name: DJANGO_ALLOWED_HOSTS
              Value: !Ref DjangoAllowedHosts
            - Name: DOCUMENT_QUEUE_URL
              Value: !Ref DocumentQueue
            - Name: DOCUMENT_SCAN_QUEUE_URL
              Value: !Ref DocumentScanQueue
            # The render path hands a EUROPASS_API draft to that queue.
            - Name: EUROPASS_QUEUE_URL
              Value: !Ref EuropassQueue
            # Ruling F-J: see WebTaskDefinition's identical comment above.
            - Name: RESEARCH_QUEUE_URL
              Value: !Ref ResearchQueue
            # Ingestion reads the quarantined original and the render path
            # writes the artefact; both go through settings.EVIDENCE_BUCKET_NAME.
            - Name: EVIDENCE_BUCKET_NAME
              Value: !Ref EvidenceBucket
            - Name: POSTGRES_HOST
              Value: !GetAtt Database.Endpoint.Address
            - Name: POSTGRES_PORT
              Value: !GetAtt Database.Endpoint.Port
            - Name: POSTGRES_DB
              Value: !Ref DBName
            - Name: DATABASE_ROLE
              Value: runtime
            - Name: POSTGRES_RUNTIME_USER
              Value: tehsil_runtime
          Secrets:
            - Name: POSTGRES_RUNTIME_PASSWORD
              ValueFrom: !Ref RuntimeDatabaseSecret
            - Name: DJANGO_SECRET_KEY
              ValueFrom: !Ref ValidationSecret
          LogConfiguration:
            LogDriver: awslogs
            Options:
              awslogs-group: !Ref DocumentWorkerLogGroup
              awslogs-region: !Ref AWS::Region
              awslogs-stream-prefix: document-worker

  # One task. Not a rate knob like the Europass worker's -- nothing here calls
  # a third party on a courtesy budget -- but generation is the expensive part
  # and ~100 documents a day drains from one task with room to spare. Raise it
  # when the queue age alarm says so, not before.
  DocumentWorkerService:
    Type: AWS::ECS::Service
    Properties:
      ServiceName: document-worker
      Cluster: !Ref ValidationCluster
      LaunchType: FARGATE
      DesiredCount: 1
      TaskDefinition: !Ref DocumentWorkerTaskDefinition
      NetworkConfiguration:
        AwsvpcConfiguration:
          AssignPublicIp: DISABLED
          Subnets: [!Ref WorkerPrivateSubnetA, !Ref WorkerPrivateSubnetB]
          SecurityGroups: [!Ref WorkerSecurityGroup]
```

- [ ] **Step 5: Watch the new log group, and grant the web tier its one write**

Add beside the other metric filters (near line 1557):

```yaml
  # No service ships unmonitored. A traceback here is a message going back on
  # the queue and, three redeliveries later, a student's CV in the DLQ.
  DocumentWorkerCrashFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref DocumentWorkerLogGroup
      FilterPattern: '"Traceback (most recent call last)"'
      MetricTransformations:
        - MetricNamespace: Tehsil/Documents
          MetricName: DocumentWorkerCrashes
          MetricValue: "1"
          DefaultValue: 0

  # AWS documents five scanResultStatus values. A sixth is survivable --
  # apply_scan_result puts it in REVIEW_REQUIRED -- but it means a human has to
  # decide what the new status means, and every affected upload is waiting.
  DocumentScanUnknownStatusFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref DocumentWorkerLogGroup
      FilterPattern: '"DocumentScanUnknownStatus"'
      MetricTransformations:
        - MetricNamespace: Tehsil/Documents
          MetricName: DocumentScanUnknownStatuses
          MetricValue: "1"
          DefaultValue: 0

  DocumentWorkerCrashAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: Tehsil/Documents
      MetricName: DocumentWorkerCrashes
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching

  DocumentScanUnknownStatusAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: Tehsil/Documents
      MetricName: DocumentScanUnknownStatuses
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
```

In `WebTaskRole`'s policy (line 884), add the one new statement and update the comment above the role:

```yaml
              # The presigned POST is signed with THIS role's credentials, so
              # an upload cannot work without it. Write only, and only into
              # quarantine/: reading an uploaded file's bytes stays worker-side
              # (ingestion, after GuardDuty marked it clean), and tenants/ --
              # the released artefacts -- stays unwritable from the web tier.
              - Effect: Allow
                Action: s3:PutObject
                Resource: !Sub "${EvidenceBucket.Arn}/quarantine/*"
```

Finally add both queue URLs to the `Environment` list of `WebTaskDefinition`, `WorkerTaskDefinition`, `MigrationTaskDefinition` and `EuropassWorkerTaskDefinition` (the same "Ruling F-J" reason the research queue URL is in all of them — `config/settings/production.py` reads every one of these at import, whatever command the task runs):

```yaml
            - Name: DOCUMENT_QUEUE_URL
              Value: !Ref DocumentQueue
            - Name: DOCUMENT_SCAN_QUEUE_URL
              Value: !Ref DocumentScanQueue
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_door uv run pytest tests/infra/test_template.py -v`
Expected: PASS (every test in the module, including the two narrowed ones)

- [ ] **Step 7: Run the full validation gate**

```bash
cd /home/orkhan/Desktop/tehsil-door
POSTGRES_DB=tehsil_door uv run pytest
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py makemigrations --check --dry-run
```

Expected: all pass; `makemigrations` reports no changes (this plan adds no model fields).

- [ ] **Step 8: Commit**

```bash
git -C /home/orkhan/Desktop/tehsil-door add infra/template.yaml tests/infra/test_template.py
git -C /home/orkhan/Desktop/tehsil-door commit -m "feat(infra): two document queues, a scan rule, and one worker to drain them

The web role gains PutObject on quarantine/ and nothing else: a
presigned POST is signed with the caller's own credentials, so the
upload cannot work without it. Reading an uploaded file stays
worker-side and tenants/ stays unwritable from the web tier -- both
narrowed in the tests rather than dropped.

The scan queue needs its own queue policy: an EventBridge rule with no
policy has its deliveries dropped silently, and the only symptom would
be uploads stuck at QUARANTINED forever."
```

---

## Self-Review

Run against the spec after the last commit, not before.

**Spec coverage.** Every row of the spec's endpoint table has a task: login/logout (8), uploads + poll (9), candidates + confirm (10), generate (11), drafts + draft + approve (12). Worker tier: scan handler (5), work handlers (6), command (7). Supporting: `resolve_variant` (1), `confirm_facts` (2), `presigned_upload` (3), `document_queue.py` (4), settings (7), infra (13). Every "Trust boundaries" bullet has a named test: presign conditions (3), `confirm_facts` resolution (2, 10), scan handler trusting only the key (5), ingestion idempotency (5), login rate limit (8), `rate_limited` on upload/confirm/generate (9, 10, 11). Every "Testing" bullet is covered in the task that introduces the behaviour.

**Three deliberate departures**, each argued in its task:
- The unknown-`scanResultStatus` guard lives in `apply_scan_result` rather than the handler (Task 3), because the handler-side version either duplicates that function or lies about what AWS sent. The handler still logs it.
- `POST /api/auth/login` also answers GET (Task 8), because a POST-only login route is unusable from a browser with CSRF enforced.
- The render worker refuses `FUNDER_TEMPLATE` and `FIELD_MAPPED` (Task 6): the first needs a `funder_template_id` no draft carries and the second produces a dict, not bytes. Both fail loudly to the DLQ rather than storing nothing and reporting success.

**Not built here, and not accidentally:** `GenerationRequest` and `GET /api/documents/requests/<id>` (the spec cut them); `create_draft` persisting a resolved variant (`europass_render.py:104` asks for it — it needs `create_draft` to accept `funding_opportunity` first, so it stays a follow-up); a shared cache backend for `apps/ratelimit.py`; splitting the document worker's two grants into two task definitions; the motivation-letter port.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-01-document-engine-door.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
