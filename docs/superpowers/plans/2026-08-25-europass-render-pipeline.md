# Europass Render Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Europass render off the web request onto a single-worker SQS queue, so the outbound rate to europa.eu becomes deterministic arithmetic instead of a per-process counter that silently breaks on a second task.

**Architecture:** The web tier enqueues; one pinned worker task drains the queue, sleeping a fixed delay between calls. Rate = `tasks × (1/delay)`, with no distributed counter. A content-hash cache in front doubles as the SQS idempotency key, and a global circuit-breaker row honours `429`/`Retry-After`.

**Tech Stack:** Django 5.2, pydantic v2, boto3/SQS, CloudFormation, pytest + pytest-django, `uv`.

**Spec:** `docs/superpowers/specs/2026-08-25-europass-render-pipeline-design.md`

## Global Constraints

- Branch: `claude/cv-render-fidelity`, worktree `/home/orkhan/Desktop/tehsil_agent/.worktrees/phase2-cv-engine`.
- Every command runs through `uv run`. Never invoke `python` or `pytest` bare.
- Gates before any commit: `uv run ruff check apps tests`, `uv run mypy apps`, `uv run pytest -q`, `uv run bandit -c pyproject.toml -r apps config` (0 findings, no `# nosec`), and `uv run python manage.py makemigrations --check --dry-run`.
- Line length is 100; ruff enforces it. `target-version = "py312"`.
- **No new dependency.** boto3, pydantic and the stdlib cover everything.
- **No test may hit the network.** `tests/documents/test_europass.py` has an autouse fixture stubbing `validate_public_url`; new tests must not perform real I/O, and must never call europa.eu.
- Schema models are frozen pydantic with `extra="forbid"`. Never assign to an attribute; use `model_copy(update=...)`.
- `VerifiedFact` is append-only. Never mutate one in place.
- **There is no fallback.** No code path may render a non-Europass artefact when europa.eu fails. An outage is a delay.
- Do NOT modify `apps/documents/migrations/0008_identity_category.py` — it carries a deliberately-deleted `('tenancy', '0009')` dependency and regenerating it breaks six migration tests.
- KNOWN FLAKE, not yours: `tests/test_aws_boundary_run_controller.py::test_image_publication_uses_substituted_commands_without_printing_registry` fails intermittently and passes on re-run. If it is the ONLY failure, re-run once and proceed.

## Two refinements this plan makes to the spec

1. **The queue message carries no payload hash.** The spec lists `(tenant, draft id, payload hash)`. The hash is derivable from the draft inside the worker, and a hash in the message can go stale if the draft changes between enqueue and consume. Message is `tenant_id` + `draft_id` only — which also keeps it trivially PII-free.
2. **`render_draft`'s existing per-student rate limiter stays, and becomes correct.** It uses `django.core.cache`, which is per-process `LocMemCache`. That was the bug at web-tier scale. Once the *only* caller is a single pinned worker process, a per-process counter is exactly right for its actual job — stopping one student triggering a hundred renders. The **global** control is the worker's drain rate. Both are correct, and neither needs a shared cache. Task 5 adds the comment saying so.

---

### Task 1: Honour `429` and `Retry-After`

**Files:**
- Modify: `apps/documents/europass.py`
- Test: `tests/documents/test_europass.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EuropassThrottled(EuropassUnavailable)` with a `retry_after_seconds: int` attribute. Task 3 catches it to open the circuit.

**Why first:** `429` is currently swallowed by the generic `status >= 400` branch and raised as an anonymous failure, so we cannot tell "you are going too fast" from "something broke". Honouring `Retry-After` is the strongest available signal that we are a well-behaved client; ignoring it is how a throttle becomes a ban.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_europass.py`:

```python
def test_a_429_raises_throttled_with_the_retry_after_seconds():
    from apps.documents.europass import EuropassThrottled

    transport = _transport(status=429, headers={"Retry-After": "120"})
    with pytest.raises(EuropassThrottled) as excinfo:
        _call({}, "GET", "/x", transport=transport)
    assert excinfo.value.retry_after_seconds == 120


def test_a_429_without_retry_after_uses_the_default():
    """A throttle with no hint still has to pause us, or we keep hammering."""
    from apps.documents.europass import _DEFAULT_RETRY_AFTER_SECONDS, EuropassThrottled

    transport = _transport(status=429)
    with pytest.raises(EuropassThrottled) as excinfo:
        _call({}, "GET", "/x", transport=transport)
    assert excinfo.value.retry_after_seconds == _DEFAULT_RETRY_AFTER_SECONDS


def test_a_garbage_retry_after_uses_the_default():
    from apps.documents.europass import _DEFAULT_RETRY_AFTER_SECONDS, EuropassThrottled

    transport = _transport(status=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    with pytest.raises(EuropassThrottled) as excinfo:
        _call({}, "GET", "/x", transport=transport)
    assert excinfo.value.retry_after_seconds == _DEFAULT_RETRY_AFTER_SECONDS


def test_throttled_is_still_a_europass_unavailable():
    """Callers written against the documented contract must keep working."""
    from apps.documents.europass import EuropassThrottled, EuropassUnavailable

    assert issubclass(EuropassThrottled, EuropassUnavailable)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass.py -k "429 or throttled" -q`
Expected: FAIL with `ImportError: cannot import name 'EuropassThrottled'`.

- [ ] **Step 3: Implement**

In `apps/documents/europass.py`, below `EuropassProvenanceMissing`:

```python
#: Used when europa.eu throttles us without saying for how long. Two minutes
#: is long enough to matter and short enough that a spurious 429 does not
#: park the queue for an hour.
_DEFAULT_RETRY_AFTER_SECONDS = 120


class EuropassThrottled(EuropassUnavailable):
    """europa.eu asked us to slow down.

    Distinguished from a generic failure because the response is different:
    a failure is retried, a throttle pauses every caller. Subclasses
    EuropassUnavailable so callers written against the module's documented
    contract keep working unchanged.
    """

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


def _retry_after_seconds(headers: object) -> int:
    """Only the delta-seconds form is honoured.

    RFC 7231 also permits an HTTP-date, but parsing one buys a timezone bug
    for a value we would clamp anyway -- the default is a safe read of any
    header we do not understand.
    """
    raw = _header(headers, "Retry-After")
    if raw is None or not raw.strip().isdigit():
        return _DEFAULT_RETRY_AFTER_SECONDS
    return min(int(raw.strip()), 3600)
```

Then in `_call`, **before** the existing `if response.status >= 400:` branch:

```python
        if response.status == 429:
            raise EuropassThrottled(
                "europa.eu throttled the request",
                retry_after_seconds=_retry_after_seconds(response.headers),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass.py -q`
Expected: PASS

- [ ] **Step 5: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 6: Commit**

```bash
git add apps/documents/europass.py tests/documents/test_europass.py
git commit -m "feat(documents): honour 429 and Retry-After from europa.eu

A 429 was swallowed by the generic status >= 400 branch, so we could not
tell 'you are going too fast' from 'something broke' -- and we retried
identically in both cases, which is how a throttle becomes a ban.

EuropassThrottled carries retry_after_seconds so the circuit breaker can
pause every caller for exactly as long as we were asked to. It subclasses
EuropassUnavailable, so callers written against the module's documented
contract are unchanged.

Only the delta-seconds form of Retry-After is parsed. The HTTP-date form
is legal but buys a timezone bug for a value we clamp anyway; anything
unparseable falls back to the default."
```

---

### Task 2: The cache and circuit models

**Files:**
- Modify: `apps/documents/models.py`
- Create: `apps/documents/migrations/0010_europass_pipeline.py`
- Create: `apps/documents/migrations/0011_europass_render_cache_tenant_guards.py`
- Test: `tests/documents/test_europass_models.py` (new), `tests/migrations/test_documents_tenant_guards.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `EuropassRenderCache(TenantScopedModel)` — fields `id`, `payload_hash: str(64)`, `object_key: str(512)`, `created_at`. Unique on `(tenant, payload_hash)`.
  - `EuropassCircuit(models.Model)` — **global, not tenant-scoped**. Fields `id` (fixed pk 1), `paused_until: datetime | None`, `reason: str(200)`, `consecutive_failures: int`.

**Why the circuit is global:** all egress leaves through one NAT Elastic IP, so when europa.eu throttles us they throttle *us*, not a customer. A per-tenant circuit would let 49 other agencies keep calling an endpoint that just asked us to stop. It therefore sits outside the RLS pattern, and holds no tenant or student data — only a timestamp, a reason and a counter.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_europass_models.py`:

```python
import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.documents.models import EuropassCircuit, EuropassRenderCache
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_the_cache_is_unique_per_tenant_and_hash(agency_a):
    with tenant_scope(agency_a.id):
        EuropassRenderCache.objects.create(payload_hash="a" * 64, object_key="k1")
        with pytest.raises(IntegrityError):
            EuropassRenderCache.objects.create(payload_hash="a" * 64, object_key="k2")


def test_the_same_hash_in_two_tenants_is_allowed(agency_a, agency_b):
    """The key is scoped per tenant: a shared artefact across tenants would
    be a cross-tenant data leak, so the uniqueness must not be global."""
    with tenant_scope(agency_a.id):
        EuropassRenderCache.objects.create(payload_hash="b" * 64, object_key="k1")
    with tenant_scope(agency_b.id):
        EuropassRenderCache.objects.create(payload_hash="b" * 64, object_key="k2")
    with tenant_scope(agency_b.id):
        assert EuropassRenderCache.objects.filter(payload_hash="b" * 64).count() == 1


def test_the_circuit_is_a_singleton_readable_without_a_tenant():
    """Global on purpose: one NAT IP means a throttle applies to everyone."""
    circuit = EuropassCircuit.load()
    assert circuit.pk == 1
    assert circuit.paused_until is None
    assert EuropassCircuit.load().pk == 1


def test_the_circuit_reports_whether_it_is_open():
    circuit = EuropassCircuit.load()
    assert circuit.is_open() is False
    circuit.paused_until = timezone.now() + timezone.timedelta(seconds=60)
    assert circuit.is_open() is True
    circuit.paused_until = timezone.now() - timezone.timedelta(seconds=60)
    assert circuit.is_open() is False


def test_the_circuit_model_carries_no_tenant_or_student_columns():
    """Pins the design decision. A tenant column here would invite someone to
    scope it per tenant, which would let other tenants keep calling an
    endpoint that asked us all to stop."""
    names = {field.name for field in EuropassCircuit._meta.get_fields()}
    assert "tenant" not in names
    assert "student" not in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'EuropassRenderCache'`.

If the `agency_b` fixture does not exist in `tests/conftest.py`, add it beside `agency_a`:

```python
@pytest.fixture
def agency_b(db):
    return Agency.objects.create(
        name="Agency B",
        brand_logo_url="https://assets.example.test/agency-b.svg",
        brand_primary_color="#654321",
    )
```

- [ ] **Step 3: Add the models**

Append to `apps/documents/models.py`:

```python
class EuropassRenderCache(TenantScopedModel):
    """Payload hash -> stored artefact, so an unchanged CV is never re-rendered.

    Also the idempotency key: SQS is at-least-once, so the worker will
    occasionally see a message twice, and the second delivery finds this row
    and makes no call. One mechanism, two jobs -- which is why there is no
    separate dedupe table.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: sha256 hex of the canonical europass_payload JSON.
    payload_hash = models.CharField(max_length=64)
    object_key = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("tenant", "payload_hash"), name="europassrendercache_tenant_hash_uniq"
            ),
            models.UniqueConstraint(
                fields=("tenant", "id"), name="europassrendercache_tenant_id_uniq"
            ),
        ]


class EuropassCircuit(models.Model):
    """Global breaker for outbound Europass calls. Deliberately NOT tenant-scoped.

    All egress leaves through one NAT Elastic IP, so when europa.eu throttles
    us they throttle *us*, not one customer. A per-tenant circuit would let
    every other tenant keep calling an endpoint that just asked us all to
    stop. It holds no tenant or student data -- only a timestamp, a reason
    and a counter -- and a test pins that.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    paused_until = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=200, blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)

    @classmethod
    def load(cls) -> "EuropassCircuit":
        circuit, _created = cls.objects.get_or_create(pk=1)
        return circuit

    def is_open(self) -> bool:
        from django.utils import timezone

        return self.paused_until is not None and self.paused_until > timezone.now()
```

`uuid4` and `models` are already imported in that module.

- [ ] **Step 4: Generate the migration**

```bash
uv run python manage.py makemigrations documents --name europass_pipeline
```
Expected: creates `apps/documents/migrations/0010_europass_pipeline.py` with `CreateModel` for both models. **Read it** and confirm it touches nothing else. If `0008_identity_category.py` shows as modified in `git status`, stop and report BLOCKED.

- [ ] **Step 5: Add the tenant guard migration**

`EuropassRenderCache` is tenant-scoped, so it needs the same RLS treatment every other tenant table has. Read `apps/documents/migrations/0006_consent_event_tenant_guards.py` and mirror it exactly for the new table. Create `apps/documents/migrations/0011_europass_render_cache_tenant_guards.py` applying, for `documents_europassrendercache`:

- `ALTER TABLE ... ENABLE ROW LEVEL SECURITY;`
- `ALTER TABLE ... FORCE ROW LEVEL SECURITY;`
- the `tenant_isolation` policy, in the same form the 0006 migration uses.

**Do not** add RLS to `documents_europasscircuit`. It is global by design. Confirm the runtime database role can still `SELECT` and `UPDATE` it — a table with no policy is unrestricted, but verify rather than assume:

```bash
uv run pytest tests/migrations/ -q
```

- [ ] **Step 6: Extend the guard test**

`tests/migrations/test_documents_tenant_guards.py` enumerates the tenant-scoped tables. Add `documents_europassrendercache` to whatever collection it asserts over, so a future table without guards fails the same way.

- [ ] **Step 7: Run tests and gates**

```bash
uv run pytest tests/documents/test_europass_models.py tests/migrations/ -q
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config \
  && uv run python manage.py makemigrations --check --dry-run
```
Expected: all pass; `makemigrations --check` reports **No changes detected** after Step 4.

- [ ] **Step 8: Commit**

```bash
git add apps/documents/models.py apps/documents/migrations/0010_europass_pipeline.py \
        apps/documents/migrations/0011_europass_render_cache_tenant_guards.py \
        tests/documents/test_europass_models.py tests/migrations/test_documents_tenant_guards.py \
        tests/conftest.py
git commit -m "feat(documents): cache and circuit models for the Europass pipeline

EuropassRenderCache maps a payload hash to a stored artefact, so an
unchanged CV is never re-rendered. It doubles as the SQS idempotency key:
at-least-once delivery means the worker will see a message twice, and the
second delivery finds this row and makes no call.

EuropassCircuit is deliberately global rather than tenant-scoped. All
egress leaves through one NAT Elastic IP, so a throttle applies to us,
not to a customer -- a per-tenant breaker would let every other tenant
keep calling an endpoint that just asked us all to stop. It carries no
tenant or student columns and a test pins that, because adding one is
exactly the change that would quietly make it per-tenant."
```

---

### Task 3: The unit of work

**Files:**
- Create: `apps/documents/europass_render.py`
- Test: `tests/documents/test_europass_render.py` (new)

**Interfaces:**
- Consumes: `EuropassThrottled` (Task 1), `EuropassRenderCache` / `EuropassCircuit` (Task 2), `render_draft` and `store_document` (existing).
- Produces:
  - `payload_hash(content: CVContent) -> str` — sha256 hex of canonical payload JSON.
  - `RenderOutcome` — frozen dataclass, `object_key: str`, `called_remote: bool`.
  - `render_and_store(*, draft: DocumentDraft, store: object | None = None) -> RenderOutcome`.
  - `CircuitOpen(EuropassUnavailable)`.

This is where the pipeline's logic lives, deliberately free of AWS concerns so it is testable without SQS.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_europass_render.py`:

```python
import pytest
from django.utils import timezone

from apps.documents import europass_render
from apps.documents.europass import EuropassThrottled, EuropassUnavailable
from apps.documents.europass_render import (
    CircuitOpen,
    payload_hash,
    render_and_store,
)
from apps.documents.models import DocumentDraft, EuropassCircuit, EuropassRenderCache
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _approved_draft(agency, django_user_model, name):
    from apps.documents.drafts import create_draft

    from .test_render import _content

    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
    DocumentDraft.objects.filter(id=draft.id).update(
        status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
    )
    draft.refresh_from_db()
    return draft


class _FakeStore:
    def __init__(self):
        self.puts = []

    def put(self, key, content):
        self.puts.append((key, content))


def _genuine_pdf():
    import pathlib

    return pathlib.Path("tests/documents/fixtures/europass_api.pdf").read_bytes()


def test_the_payload_hash_is_stable_and_content_derived():
    from .test_europass import _content as _cv

    assert payload_hash(_cv()) == payload_hash(_cv())
    changed = _cv(document_language="fr")
    assert payload_hash(changed) != payload_hash(_cv())


def test_a_cache_hit_makes_no_remote_call(agency_a, django_user_model, monkeypatch):
    monkeypatch.setattr(
        europass_render, "render_draft", lambda **kw: pytest.fail("called europa.eu")
    )
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "cache-hit")
        from apps.documents.schemas import CVContent

        content = CVContent.model_validate(draft.content)
        EuropassRenderCache.objects.create(
            payload_hash=payload_hash(content), object_key="already/there.pdf"
        )
        outcome = render_and_store(draft=draft, store=_FakeStore())
    assert outcome.object_key == "already/there.pdf"
    assert outcome.called_remote is False


def test_a_second_delivery_of_the_same_message_renders_once(
    agency_a, django_user_model, monkeypatch
):
    """SQS is at-least-once. The cache is the idempotency key."""
    calls = []

    class _Artifact:
        pdf_bytes = _genuine_pdf()

    def _render(**kwargs):
        calls.append(1)
        return _Artifact()

    monkeypatch.setattr(europass_render, "render_draft", _render)
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "idem")
        first = render_and_store(draft=draft, store=store)
        second = render_and_store(draft=draft, store=store)
    assert len(calls) == 1
    assert first.object_key == second.object_key
    assert second.called_remote is False


def test_an_open_circuit_refuses_without_calling(agency_a, django_user_model, monkeypatch):
    monkeypatch.setattr(
        europass_render, "render_draft", lambda **kw: pytest.fail("called europa.eu")
    )
    circuit = EuropassCircuit.load()
    circuit.paused_until = timezone.now() + timezone.timedelta(seconds=300)
    circuit.save()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "open-circuit")
        with pytest.raises(CircuitOpen):
            render_and_store(draft=draft, store=_FakeStore())


def test_a_throttle_opens_the_circuit_for_the_retry_after(
    agency_a, django_user_model, monkeypatch
):
    def _throttled(**kwargs):
        raise EuropassThrottled("slow down", retry_after_seconds=180)

    monkeypatch.setattr(europass_render, "render_draft", _throttled)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "throttled")
        with pytest.raises(EuropassThrottled):
            render_and_store(draft=draft, store=_FakeStore())
    circuit = EuropassCircuit.load()
    assert circuit.is_open() is True
    assert 170 <= (circuit.paused_until - timezone.now()).total_seconds() <= 180


def test_three_consecutive_failures_open_the_circuit(agency_a, django_user_model, monkeypatch):
    def _down(**kwargs):
        raise EuropassUnavailable("europa.eu is down")

    monkeypatch.setattr(europass_render, "render_draft", _down)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "consecutive")
        for _ in range(3):
            with pytest.raises(EuropassUnavailable):
                render_and_store(draft=draft, store=_FakeStore())
    assert EuropassCircuit.load().is_open() is True


def test_a_success_resets_the_failure_counter(agency_a, django_user_model, monkeypatch):
    class _Artifact:
        pdf_bytes = _genuine_pdf()

    circuit = EuropassCircuit.load()
    circuit.consecutive_failures = 2
    circuit.save()
    monkeypatch.setattr(europass_render, "render_draft", lambda **kw: _Artifact())
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "reset")
        render_and_store(draft=draft, store=_FakeStore())
    assert EuropassCircuit.load().consecutive_failures == 0


def test_a_provenance_failure_does_not_trip_the_breaker(
    agency_a, django_user_model, monkeypatch
):
    """europa.eu is UP -- it just returned something that is not a Europass
    document. Counting that as an availability failure would park every other
    student's CV over a problem no retry can fix."""
    from apps.documents.europass import EuropassProvenanceMissing

    def _not_europass(**kwargs):
        raise EuropassProvenanceMissing("no attachment.xml")

    monkeypatch.setattr(europass_render, "render_draft", _not_europass)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "provenance")
        for _ in range(3):
            with pytest.raises(EuropassProvenanceMissing):
                render_and_store(draft=draft, store=_FakeStore())
    circuit = EuropassCircuit.load()
    assert circuit.consecutive_failures == 0
    assert circuit.is_open() is False


def test_a_successful_render_stores_and_caches(agency_a, django_user_model, monkeypatch):
    class _Artifact:
        pdf_bytes = _genuine_pdf()

    monkeypatch.setattr(europass_render, "render_draft", lambda **kw: _Artifact())
    store = _FakeStore()
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "stored")
        outcome = render_and_store(draft=draft, store=store)
        assert EuropassRenderCache.objects.filter(object_key=outcome.object_key).exists()
    assert outcome.called_remote is True
    assert len(store.puts) == 1
```

Add a `document_language` keyword to `tests/documents/test_europass.py::_content` if it does not accept one, so `test_the_payload_hash_is_stable_and_content_derived` can vary it. That helper already takes `**overrides`, so it works unchanged.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass_render.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.europass_render'`.

- [ ] **Step 3: Write the module**

Create `apps/documents/europass_render.py`:

```python
"""One Europass render, start to finish: cache, circuit, render, store.

Deliberately free of AWS concerns. The worker owns SQS; this owns the
decision of whether to call europa.eu at all and what to do with the bytes,
which is the part worth testing without a queue.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from django.utils import timezone

from .europass import (
    EuropassProvenanceMissing,
    EuropassThrottled,
    EuropassUnavailable,
    europass_payload,
)
from .models import DocumentDraft, EuropassCircuit, EuropassRenderCache
from .render import render_draft
from .schemas import CVContent
from .storage import store_document

#: Three in a row means it is europa.eu, not this request. Below that a single
#: transient failure should not park every other student's CV.
_FAILURE_THRESHOLD = 3
#: How long a run of plain failures parks the queue. Shorter than a throttle:
#: we were not asked to wait, we are guessing.
_FAILURE_PAUSE_SECONDS = 300


class CircuitOpen(EuropassUnavailable):
    """We are paused. The caller should return the message to the queue."""


@dataclass(frozen=True)
class RenderOutcome:
    object_key: str
    called_remote: bool


def payload_hash(content: CVContent) -> str:
    """Hash what we would SEND, not the draft row.

    Two drafts differing only in a field Europass never receives produce the
    same payload and should share an artefact rather than cost two calls.
    """
    canonical = json.dumps(europass_payload(content), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _open_circuit(seconds: int, reason: str) -> None:
    circuit = EuropassCircuit.load()
    circuit.paused_until = timezone.now() + timezone.timedelta(seconds=seconds)
    circuit.reason = reason[:200]
    circuit.save(update_fields=["paused_until", "reason"])


def render_and_store(*, draft: DocumentDraft, store: object | None = None) -> RenderOutcome:
    """Render one approved draft through europa.eu and store the artefact.

    Raises CircuitOpen when paused, EuropassThrottled when europa.eu asks us
    to slow down, and EuropassUnavailable for everything else. It never
    returns a non-Europass artefact -- there is no fallback.
    """
    content = CVContent.model_validate(draft.content)
    digest = payload_hash(content)

    cached = EuropassRenderCache.objects.filter(payload_hash=digest).first()
    if cached is not None:
        return RenderOutcome(object_key=cached.object_key, called_remote=False)

    circuit = EuropassCircuit.load()
    if circuit.is_open():
        raise CircuitOpen(f"Europass rendering paused: {circuit.reason}")

    try:
        artifact = render_draft(draft=draft)
    except EuropassThrottled as error:
        _open_circuit(error.retry_after_seconds, "throttled by europa.eu")
        raise
    except EuropassProvenanceMissing:
        # NOT an availability problem, so it must not count toward the
        # breaker: europa.eu is up, it just handed us something that is not
        # a Europass document. Re-raised so SQS redelivers it to the DLQ,
        # which is the alarm that means "go read the canary".
        raise
    except EuropassUnavailable:
        circuit.consecutive_failures += 1
        if circuit.consecutive_failures >= _FAILURE_THRESHOLD:
            circuit.paused_until = timezone.now() + timezone.timedelta(
                seconds=_FAILURE_PAUSE_SECONDS
            )
            circuit.reason = "consecutive failures"
        circuit.save(update_fields=["consecutive_failures", "paused_until", "reason"])
        raise

    if circuit.consecutive_failures:
        circuit.consecutive_failures = 0
        circuit.save(update_fields=["consecutive_failures"])

    pdf = artifact.pdf_bytes
    if pdf is None:  # pragma: no cover - EUROPASS_API always yields bytes
        raise EuropassUnavailable("Europass render produced no PDF")
    object_key = store_document(
        draft=draft, filename="cv-europass.pdf", content=pdf, store=store
    )
    EuropassRenderCache.objects.create(payload_hash=digest, object_key=object_key)
    return RenderOutcome(object_key=object_key, called_remote=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass_render.py -q`
Expected: PASS

- [ ] **Step 5: Prove the cache test discriminates**

The cache-hit test passes trivially if the cache lookup is wrong in a way that still avoids the call. Temporarily change the lookup to `.filter(payload_hash="never")`, and confirm `test_a_cache_hit_makes_no_remote_call` and `test_a_second_delivery_of_the_same_message_renders_once` both go RED. Revert. Paste the evidence in your report; do not commit the temporary change.

- [ ] **Step 6: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config \
  && uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 7: Commit**

```bash
git add apps/documents/europass_render.py tests/documents/test_europass_render.py
git commit -m "feat(documents): the Europass render unit of work

Cache, circuit, render, store -- with no AWS concerns, so the decision of
whether to call europa.eu at all is testable without a queue.

The hash is of the PAYLOAD, not the draft row: two drafts differing only
in a field Europass never receives should share an artefact rather than
cost two calls. That same row is the SQS idempotency key, since
at-least-once delivery means the worker will see a message twice.

A throttle opens the circuit for exactly the Retry-After we were given; a
run of three plain failures opens it for five minutes, because below three
a single transient failure should not park every other student's CV. A
success resets the counter."
```

---

### Task 4: The queue

**Files:**
- Create: `apps/documents/europass_queue.py`
- Modify: `config/settings/base.py`, `config/settings/production.py`
- Test: `tests/documents/test_europass_queue.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `EuropassRenderMessage` — frozen pydantic, `schema_version: Literal[1] = 1`, `tenant_id: UUID`, `draft_id: UUID`.
  - `enqueue_europass_render(message, *, client=None, queue_url) -> None`
  - `consume_once(*, client, queue_url, handler) -> int`
  - `settings.EUROPASS_QUEUE_URL`

This mirrors `apps/research/queue.py` closely and on purpose — that pattern is already in production with alarms and tests. Read it first.

**One deliberate difference:** `enqueue_research` passes `MessageGroupId`, which is a FIFO-queue parameter. This queue is **standard**, not FIFO: there is exactly one worker, so ordering is meaningless, and standard queues have no throughput ceiling to reason about. Do not pass `MessageGroupId`.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_europass_queue.py`:

```python
import json
from uuid import uuid4

import pytest

from apps.documents.europass_queue import (
    EuropassRenderMessage,
    consume_once,
    enqueue_europass_render,
)


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


def _message():
    return EuropassRenderMessage(tenant_id=uuid4(), draft_id=uuid4())


def test_the_message_carries_no_pii_fields():
    """Pins a privacy decision. A queue is a durable store with its own
    retention; a student's employment history must not get a second copy
    there with different rules from the first."""
    fields = set(EuropassRenderMessage.model_fields)
    assert fields == {"schema_version", "tenant_id", "draft_id"}


def test_the_message_rejects_extra_fields():
    with pytest.raises(ValueError):
        EuropassRenderMessage(tenant_id=uuid4(), draft_id=uuid4(), full_name="Jane Doe")


def test_enqueue_sends_the_serialised_message():
    client = _FakeSQS()
    message = _message()
    enqueue_europass_render(message, client=client, queue_url="q")
    body = json.loads(client.sent[0]["MessageBody"])
    assert body["draft_id"] == str(message.draft_id)
    assert client.sent[0]["QueueUrl"] == "q"


def test_enqueue_does_not_send_a_message_group_id():
    """This is a standard queue, not FIFO. MessageGroupId is a FIFO-only
    parameter and SQS rejects it on a standard queue."""
    client = _FakeSQS()
    enqueue_europass_render(_message(), client=client, queue_url="q")
    assert "MessageGroupId" not in client.sent[0]


def test_consume_once_invokes_the_handler_and_deletes():
    message = _message()
    client = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-1"}])
    seen = []
    count = consume_once(client=client, queue_url="q", handler=seen.append)
    assert count == 1
    assert seen[0].draft_id == message.draft_id
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"


def test_a_failing_handler_does_not_delete_the_message():
    """The message must return to the queue so SQS can retry it. Deleting on
    failure silently loses a student's CV."""
    message = _message()
    client = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-2"}])

    def _boom(_message):
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError):
        consume_once(client=client, queue_url="q", handler=_boom)
    assert client.deleted == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass_queue.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.europass_queue'`.

- [ ] **Step 3: Write the module**

Create `apps/documents/europass_queue.py`:

```python
"""SQS transport for Europass render work.

Mirrors apps/research/queue.py deliberately: that pattern is already in
production with its own alarms and tests, and a second queueing idiom in one
codebase is the expensive choice.

Unlike the research queue this one is STANDARD, not FIFO. There is exactly
one worker, so ordering is meaningless, and a standard queue has no
throughput ceiling to reason about.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol
from uuid import UUID

import boto3  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict


class SQSClient(Protocol):
    def send_message(self, **kwargs: str) -> object: ...

    def receive_message(self, **kwargs: object) -> dict[str, object]: ...

    def delete_message(self, **kwargs: str) -> object: ...


class EuropassRenderMessage(BaseModel):
    """Identifiers only -- never content.

    A queue is a durable store with its own retention policy. Putting a
    student's name or employment history here would create a second copy of
    their personal data governed by different rules from the first, so the
    worker reads the content from the database instead, under tenant scope.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    tenant_id: UUID
    draft_id: UUID


def enqueue_europass_render(
    message: EuropassRenderMessage, *, client: SQSClient | None = None, queue_url: str
) -> None:
    sqs = client or boto3.client("sqs")
    sqs.send_message(QueueUrl=queue_url, MessageBody=message.model_dump_json())


def consume_once(
    *,
    client: SQSClient,
    queue_url: str,
    handler: Callable[[EuropassRenderMessage], None],
) -> int:
    """Receive at most one message, hand it to ``handler``, delete on success.

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
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        body = raw.get("Body")
        receipt = raw.get("ReceiptHandle")
        if not isinstance(body, str) or not isinstance(receipt, str):
            continue
        handler(EuropassRenderMessage.model_validate_json(body))
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
    return len(messages)
```

- [ ] **Step 4: Add the setting**

In `config/settings/base.py`, beside `RESEARCH_QUEUE_URL`:

```python
EUROPASS_QUEUE_URL = os.getenv("EUROPASS_QUEUE_URL", "test-europass-queue")
```

In `config/settings/production.py`, beside the existing required one:

```python
EUROPASS_QUEUE_URL = os.environ["EUROPASS_QUEUE_URL"]
```

Production reads it with `os.environ[...]` on purpose, matching `RESEARCH_QUEUE_URL`: a missing queue URL should fail at boot, not silently enqueue into a string.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass_queue.py -q`
Expected: PASS

- [ ] **Step 6: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 7: Commit**

```bash
git add apps/documents/europass_queue.py config/settings/base.py \
        config/settings/production.py tests/documents/test_europass_queue.py
git commit -m "feat(documents): SQS transport for Europass render work

Mirrors apps/research/queue.py, which is already in production with its
own alarms and tests -- a second queueing idiom in one codebase would be
the expensive choice.

Standard queue, not FIFO: there is exactly one worker so ordering is
meaningless, and MessageGroupId is a FIFO-only parameter SQS rejects on a
standard queue. A test pins that we do not send one.

The message carries identifiers only. A queue is a durable store with its
own retention, so putting a student's employment history in it would
create a second copy of their data under different rules; the worker
reads content from the database under tenant scope instead."
```

---

### Task 5: The worker, and the rate guarantee

**Files:**
- Create: `apps/documents/management/commands/run_europass_worker.py`
- Create: `apps/documents/europass_worker.py`
- Modify: `apps/documents/render.py` (comment only, on the existing rate limiter)
- Test: `tests/documents/test_europass_worker.py` (new)

**Interfaces:**
- Consumes: `EuropassRenderMessage`, `consume_once` (Task 4); `render_and_store`, `CircuitOpen` (Task 3).
- Produces: `process_europass_message(message, *, sleep=time.sleep) -> None` and the management command.

**The point of this task.** The outbound rate is `worker_tasks × (60 / delay)`. With one task and a 2-second delay that is a ceiling of 30 requests/minute — roughly 17× headroom over 1,000/day averaged across a working day, and a 500-student deadline burst drains in about 17 minutes. **The delay is the only knob that should ever change the rate**, and it should be turned up on europa.eu's request, never down for our convenience.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_europass_worker.py`:

```python
from uuid import uuid4

import pytest

from apps.documents import europass_worker
from apps.documents.europass_queue import EuropassRenderMessage
from apps.documents.europass_render import CircuitOpen, RenderOutcome
from apps.documents.europass_worker import process_europass_message
from apps.documents.models import DocumentDraft
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def _approved_draft(agency, django_user_model, name):
    from apps.documents.drafts import create_draft

    from .test_render import _content

    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
    DocumentDraft.objects.filter(id=draft.id).update(
        status=DocumentDraft.Status.APPROVED, render_variant="EUROPASS_API"
    )
    draft.refresh_from_db()
    return draft


def test_a_remote_call_is_followed_by_the_delay(agency_a, django_user_model, monkeypatch):
    """THE rate guarantee. If the delay stops being applied, the rate limiter
    silently ceases to exist -- there is no counter anywhere to catch it."""
    slept = []
    monkeypatch.setattr(
        europass_worker,
        "render_and_store",
        lambda **kw: RenderOutcome(object_key="k", called_remote=True),
    )
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-1")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        process_europass_message(message, sleep=slept.append)
    assert slept == [europass_worker._INTER_CALL_DELAY_SECONDS]


def test_a_cache_hit_does_not_sleep(agency_a, django_user_model, monkeypatch):
    """The delay paces calls to europa.eu, not work. Sleeping on a cache hit
    would throttle the queue for no reason."""
    slept = []
    monkeypatch.setattr(
        europass_worker,
        "render_and_store",
        lambda **kw: RenderOutcome(object_key="k", called_remote=False),
    )
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-2")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        process_europass_message(message, sleep=slept.append)
    assert slept == []


def test_the_configured_rate_is_at_most_thirty_per_minute():
    """Pins the agreed ceiling. Lowering the delay raises the rate at a public
    EU service, so it should require changing this test on purpose."""
    assert europass_worker._INTER_CALL_DELAY_SECONDS >= 2
    assert 60 / europass_worker._INTER_CALL_DELAY_SECONDS <= 30


def test_an_open_circuit_propagates_so_sqs_redelivers(
    agency_a, django_user_model, monkeypatch
):
    def _open(**kwargs):
        raise CircuitOpen("paused")

    monkeypatch.setattr(europass_worker, "render_and_store", _open)
    with tenant_scope(agency_a.id):
        draft = _approved_draft(agency_a, django_user_model, "rate-3")
        message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=draft.id)
        with pytest.raises(CircuitOpen):
            process_europass_message(message, sleep=lambda _s: None)


def test_a_missing_draft_raises_rather_than_silently_succeeding(agency_a):
    message = EuropassRenderMessage(tenant_id=agency_a.id, draft_id=uuid4())
    with pytest.raises(DocumentDraft.DoesNotExist):
        process_europass_message(message, sleep=lambda _s: None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/documents/test_europass_worker.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.europass_worker'`.

- [ ] **Step 3: Write the worker body**

Create `apps/documents/europass_worker.py`:

```python
"""Process one Europass render message under tenant scope, then pace.

The delay here IS the rate limiter. Outbound rate is
``worker_tasks x (60 / delay)``, so it is a property of the deployment
rather than a counter that can drift from what the code intends. The
corollary is in infra/template.yaml: this worker's task count is a rate
knob, not a throughput knob, and must never be autoscaled.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from django.db import transaction

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

from .europass_queue import EuropassRenderMessage
from .europass_render import render_and_store
from .models import DocumentDraft

#: 2 seconds => a ceiling of 30 requests/minute from one task. That is ~17x
#: headroom over 1,000 renders/day averaged across a working day, and a
#: 500-student deadline burst drains in about 17 minutes.
#: Turn this UP if europa.eu asks. Never down for our own convenience.
_INTER_CALL_DELAY_SECONDS = 2

logger = logging.getLogger(__name__)


def process_europass_message(
    message: EuropassRenderMessage, *, sleep: Callable[[int], None] = time.sleep
) -> None:
    with transaction.atomic(), tenant_scope(message.tenant_id):
        set_local_tenant(message.tenant_id)
        draft = DocumentDraft.objects.get(id=message.draft_id)
        outcome = render_and_store(draft=draft)
    if outcome.called_remote:
        # One line per real call. A CloudWatch metric filter turns these into
        # EuropassCallsTotal (infra Task 6) -- no put_metric_data code, which
        # is how this repo already produces its other custom metrics. This is
        # the number that makes our volume answerable to europa.eu.
        logger.info("EuropassCallMade draft=%s", message.draft_id)
        # Pace only actual calls: a cache hit costs europa.eu nothing, and
        # sleeping on it would throttle the queue for no reason.
        sleep(_INTER_CALL_DELAY_SECONDS)
```

- [ ] **Step 4: Write the management command**

Create `apps/documents/management/commands/run_europass_worker.py`:

```python
"""Drain the Europass render queue.

Runs as its OWN ECS service, pinned to one task. It is not folded into
run_research_worker because scaling that service for research throughput
would multiply this worker's request rate at europa.eu as a side effect.
"""

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.documents.europass_queue import consume_once
from apps.documents.europass_worker import process_europass_message


class Command(BaseCommand):
    help = "Consume Europass render work from SQS, paced to a fixed rate"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *_args: object, **options: object) -> None:
        client = boto3.client("sqs")
        while True:
            consume_once(
                client=client,
                queue_url=settings.EUROPASS_QUEUE_URL,
                handler=process_europass_message,
            )
            if options["once"]:
                return
```

- [ ] **Step 5: Comment the existing rate limiter**

In `apps/documents/render.py`, above the `rate_limited(...)` block in `render_draft`, replace the existing comment with:

```python
    # Per-STUDENT abuse guard only. django.core.cache is per-process
    # LocMemCache, which was wrong when the web tier called this; now that the
    # only caller is the single pinned Europass worker, one process is exactly
    # the right scope for "one student cannot trigger a hundred renders".
    # The GLOBAL rate control is not here -- it is the worker's drain rate
    # (apps/documents/europass_worker.py). Do not add a shared cache for this.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/documents/test_europass_worker.py -q`
Expected: PASS

- [ ] **Step 7: Prove the rate guarantee test discriminates**

Temporarily delete the `if outcome.called_remote: sleep(...)` block, confirm `test_a_remote_call_is_followed_by_the_delay` goes RED, then revert. This is the single most important test in the plan: with no counter anywhere, a removed delay means the rate limiter silently ceases to exist. Paste the evidence; do not commit the temporary change.

- [ ] **Step 8: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config
```

- [ ] **Step 9: Commit**

```bash
git add apps/documents/europass_worker.py \
        apps/documents/management/commands/run_europass_worker.py \
        apps/documents/render.py tests/documents/test_europass_worker.py
git commit -m "feat(documents): the paced Europass worker

The delay in this worker IS the rate limiter. Outbound rate is
tasks x (60/delay), so it is a property of the deployment rather than a
counter that can drift from what the code intends. Two seconds from one
task is a ceiling of 30/minute -- about 17x headroom over 1,000/day
averaged across a working day, with a 500-student burst draining in
roughly 17 minutes.

Pacing applies to actual calls, not to work: a cache hit costs europa.eu
nothing, so sleeping on one would throttle the queue for no reason.

Also documents why render_draft's per-process rate limiter is now
correct rather than broken. It was wrong when the web tier called it; with
the single pinned worker as the only caller, one process is exactly the
right scope for a per-student abuse guard. The global control is the drain
rate, and a shared cache would add nothing."
```

---

### Task 6: Infrastructure and the canary schedule

**Files:**
- Modify: `infra/template.yaml`
- Test: `tests/infra/test_template.py`

**Interfaces:**
- Consumes: `run_europass_worker` (Task 5), `europass_canary` (existing command).
- Produces: nothing other tasks use. This is the last task.

Read `tests/infra/test_template.py` first — it parses the YAML with the CloudFormation tag list already defined there and asserts on structure. Follow that idiom; do not call AWS.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infra/test_template.py`:

```python
def test_europass_queue_has_a_dead_letter_queue(template: dict[str, Any]) -> None:
    queue = template["Resources"]["EuropassQueue"]["Properties"]
    assert queue["KmsMasterKeyId"] == "alias/aws/sqs"
    assert queue["RedrivePolicy"]["maxReceiveCount"] == 3


def test_the_europass_worker_is_pinned_to_one_task(template: dict[str, Any]) -> None:
    """The task count is a RATE knob, not a throughput knob: outbound rate is
    tasks x (1/delay). Scaling this silently multiplies traffic to a public
    EU service, so the count is a literal 1 and not a parameter."""
    service = template["Resources"]["EuropassWorkerService"]["Properties"]
    assert service["DesiredCount"] == 1


def test_the_europass_worker_is_never_autoscaled(template: dict[str, Any]) -> None:
    scalable = [
        name
        for name, resource in template["Resources"].items()
        if resource["Type"] == "AWS::ApplicationAutoScaling::ScalableTarget"
        and "Europass" in name
    ]
    assert scalable == []


def test_the_europass_worker_is_its_own_service(template: dict[str, Any]) -> None:
    """Not folded into the research worker: scaling that service for research
    throughput would multiply this worker's request rate as a side effect."""
    assert "EuropassWorkerService" in template["Resources"]
    assert template["Resources"]["EuropassWorkerService"]["Type"] == "AWS::ECS::Service"


def test_the_europass_canary_is_scheduled(template: dict[str, Any]) -> None:
    """The spec calls the canary 'the entire early-warning system' for an
    undocumented API. Unscheduled, the first sign europa.eu changed shape
    would be a dead-letter queue full of students' CVs."""
    rules = [
        resource
        for name, resource in template["Resources"].items()
        if resource["Type"] == "AWS::Events::Rule" and "Canary" in name
    ]
    assert rules, "no EventBridge rule schedules the Europass canary"
    assert any("ScheduleExpression" in rule["Properties"] for rule in rules)


def test_the_calls_metric_filter_matches_what_the_worker_logs(template: dict[str, Any]) -> None:
    """EuropassCallsTotal is the number that makes our volume answerable to
    europa.eu. A filter whose pattern drifts from the worker's log line is a
    metric that silently reads zero, which is worse than no metric."""
    filters = [
        resource["Properties"]
        for name, resource in template["Resources"].items()
        if resource["Type"] == "AWS::Logs::MetricFilter" and "EuropassCalls" in name
    ]
    assert len(filters) == 1
    assert "EuropassCallMade" in filters[0]["FilterPattern"]
    assert filters[0]["MetricTransformations"][0]["MetricName"] == "EuropassCallsTotal"


def test_alarms_exist_for_the_europass_backlog_and_dlq(template: dict[str, Any]) -> None:
    alarms = {
        name: resource["Properties"]
        for name, resource in template["Resources"].items()
        if resource["Type"] == "AWS::CloudWatch::Alarm"
    }
    metrics = {
        name: props["MetricName"] for name, props in alarms.items() if "Europass" in name
    }
    assert "ApproximateAgeOfOldestMessage" in metrics.values()
    assert "ApproximateNumberOfMessagesVisible" in metrics.values()
```

If `tests/infra/test_template.py` has no `template` fixture, add one that loads and parses `TEMPLATE_PATH` with the module's existing `_CFN_TAGS` loader, and reuse it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infra/test_template.py -q`
Expected: FAIL with `KeyError: 'EuropassQueue'`.

- [ ] **Step 3: Add the queues and alarms**

In `infra/template.yaml`, immediately after the `ResearchQueue` block, mirroring its shape:

```yaml
  EuropassDeadLetterQueue:
    Type: AWS::SQS::Queue
    Properties:
      KmsMasterKeyId: alias/aws/sqs

  # Standard, not FIFO: one worker means ordering is meaningless, and a
  # standard queue has no throughput ceiling to reason about.
  EuropassQueue:
    Type: AWS::SQS::Queue
    Properties:
      KmsMasterKeyId: alias/aws/sqs
      VisibilityTimeout: 300
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt EuropassDeadLetterQueue.Arn
        maxReceiveCount: 3

  EuropassQueueAgeAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/SQS
      MetricName: ApproximateAgeOfOldestMessage
      Dimensions:
        - Name: QueueName
          Value: !GetAtt EuropassQueue.QueueName
      Statistic: Maximum
      Period: 60
      EvaluationPeriods: 5
      Threshold: 1800
      ComparisonOperator: GreaterThanThreshold

  EuropassDeadLetterDepthAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions:
        - Name: QueueName
          Value: !GetAtt EuropassDeadLetterQueue.QueueName
      Statistic: Maximum
      Period: 60
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
```

**On the worker health check.** The spec's DevOps section asks for one that reflects queue
processing rather than process liveness. `EuropassQueueAgeAlarm` **is** that health check, and a
better one than a liveness probe: a worker wedged on a hung HTTP call is "running" by any naive
measure, but its backlog grows and this alarm fires. No separate probe is added, deliberately —
an ECS health check that only proves the process exists would be worse than none, because it
would look like coverage.

The 1800-second backlog threshold is deliberately looser than the research queue's 300: a paced queue is *expected* to hold a spike for ~17 minutes, so alarming at 5 minutes would page someone every deadline day. It alarms when the backlog is not draining, which is the real failure.

- [ ] **Step 4: Add the worker service and log group**

After the existing worker service definition, mirroring its shape (same cluster, subnets, security group, execution role, task role and log configuration — copy them from `WorkerService`/`WorkerTaskDefinition`):

```yaml
  EuropassWorkerLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/tehsil/app/${AWS::StackName}/europass-worker"
      RetentionInDays: 30

  EuropassWorkerService:
    Type: AWS::ECS::Service
    Properties:
      # DesiredCount is a RATE control, not a throughput control. Outbound
      # rate to europa.eu is tasks x (60 / _INTER_CALL_DELAY_SECONDS), so
      # raising this multiplies traffic to a public European Commission
      # service. It is a literal 1, never a parameter, and never autoscaled.
      # If throughput must rise, lower the delay -- and only to a rate
      # europa.eu has agreed to.
      DesiredCount: 1
```

with `TaskDefinition` pointing at a new `EuropassWorkerTaskDefinition` whose container runs:

```yaml
          Command: ["python", "manage.py", "run_europass_worker"]
```

and whose environment includes `EUROPASS_QUEUE_URL: !Ref EuropassQueue` alongside the same variables the research worker already receives. Grant its task role `sqs:ReceiveMessage`, `sqs:DeleteMessage` and `sqs:GetQueueAttributes` on `EuropassQueue` only — mirror the narrow prefixing style of the existing `ConsumeResearchQueueAndOwnEvidenceBucket` policy rather than widening an existing one.

- [ ] **Step 5: Schedule the canary**

```yaml
  EuropassCanaryRule:
    Type: AWS::Events::Rule
    Properties:
      Description: Exercise the live Europass API so a shape change pages us
      ScheduleExpression: "rate(6 hours)"
      State: ENABLED
      Targets:
        - Id: europass-canary
          Arn: !GetAtt Cluster.Arn
          RoleArn: !GetAtt EventsInvokeEcsRole.Arn
          EcsParameters:
            TaskDefinitionArn: !Ref EuropassWorkerTaskDefinition
            LaunchType: FARGATE
            NetworkConfiguration:
              AwsVpcConfiguration:
                Subnets: [!Ref PrivateSubnetA, !Ref PrivateSubnetB]
                SecurityGroups: [!Ref AppSecurityGroup]
          Input: !Sub |
            {"containerOverrides":[{"name":"europass-worker",
             "command":["python","manage.py","europass_canary"]}]}
```

Use the actual logical names this template already uses for the cluster, subnets and security group. If no `EventsInvokeEcsRole` exists, add one whose policy permits `ecs:RunTask` on this task definition and `iam:PassRole` on the task and execution roles only.

Then add a metric filter and alarm so a failing canary pages someone, following the existing `FailedResearchMessages` pattern:

```yaml
  EuropassCallsFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref EuropassWorkerLogGroup
      FilterPattern: '"EuropassCallMade"'
      MetricTransformations:
        - MetricNamespace: Tehsil/App
          MetricName: EuropassCallsTotal
          MetricValue: "1"
          DefaultValue: 0

  EuropassCanaryFailureFilter:
    Type: AWS::Logs::MetricFilter
    Properties:
      LogGroupName: !Ref EuropassWorkerLogGroup
      FilterPattern: '?"Europass API failed" ?"Traceback (most recent call last)"'
      MetricTransformations:
        - MetricNamespace: Tehsil/App
          MetricName: EuropassCanaryFailures
          MetricValue: "1"
          DefaultValue: 0

  EuropassCanaryFailureAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Namespace: Tehsil/App
      MetricName: EuropassCanaryFailures
      Statistic: Sum
      Period: 3600
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/infra/test_template.py -q`
Expected: PASS

- [ ] **Step 7: Validate the template parses**

The `tests/infra/test_template.py` tests you just ran already parse the whole template with the
CloudFormation tag list defined at the top of that module, so a YAML syntax error or an unknown
`!Tag` fails them. There is no separate validation step to run, and no AWS call to make.

- [ ] **Step 8: Run the gates**

```bash
uv run ruff check apps tests && uv run mypy apps && uv run pytest -q \
  && uv run bandit -c pyproject.toml -r apps config \
  && uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 9: Commit**

```bash
git add infra/template.yaml tests/infra/test_template.py
git commit -m "feat(infra): Europass queue, pinned worker service and canary schedule

The queue mirrors ResearchQueue -- KMS, DLQ, maxReceiveCount 3 -- with a
looser backlog threshold: a paced queue is expected to hold a deadline
spike for ~17 minutes, so alarming at 5 would page someone every deadline
day. It alarms when the backlog is not draining, which is the real
failure.

The worker is its own ECS service pinned to DesiredCount 1, with a
comment saying why and tests that fail if anyone autoscales it or turns
the count into a parameter. Outbound rate is tasks x (60/delay), so the
count is a rate control; folding this into the research worker would mean
scaling for research throughput silently multiplied traffic to a public
European Commission service.

The canary now actually runs. The previous spec called it 'the entire
early-warning system' for an undocumented API and nothing scheduled it --
so the first sign europa.eu changed shape would have been a dead-letter
queue full of students' CVs."
```

---

## Verification

After Task 6, from a clean tree:

```bash
uv run ruff check apps tests
uv run mypy apps
uv run pytest -q
uv run bandit -c pyproject.toml -r apps config
uv run python manage.py makemigrations --check --dry-run
```

Expected: all pass, `makemigrations --check` reports no changes, and only the known AWS flake may fail intermittently.

Then the thing no test can tell you — that the worker actually drains:

```bash
uv run python manage.py run_europass_worker --once
```

Against a local queue with no messages this returns immediately. It is a smoke test that the command wires up, not a functional one.

## What this plan does NOT build

- **The trigger.** Nothing enqueues yet. `render_draft` still has no production caller, so this pipeline is inert until the surface that calls `enqueue_europass_render` is built — its own spec, deliberately.
- **Student-facing status.** No "your CV is being generated" UI.
- **A deploy pipeline.** The largest operational gap in this repo — every release is a human running CloudFormation by hand — but out of scope here and worth its own task.
- **Web-tier autoscaling.** Unrelated to this path, and a real gap at 50+ agencies.
- **Redis / ElastiCache.** The drain rate bounds the request rate, so exact shared counters buy precision nothing needs. If europa.eu answers with a contractual ceiling, that is when exact counting starts to matter.

## The dependency this plan cannot close

`EMPL-ELM-SUPPORT@ec.europa.eu` is still unwritten. The 2-second delay in Task 5 is an estimate until they supply a real number, and a block takes the feature down for every tenant at once. Build this regardless — it is the right shape either way, and `EuropassQueueAgeAlarm` plus the worker's logs are what make the volume answerable in that email.
