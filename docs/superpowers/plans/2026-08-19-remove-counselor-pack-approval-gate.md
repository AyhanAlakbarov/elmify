# Remove Counselor Pack-Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI-generated recommendation pack publish automatically the moment the research pipeline finishes, removing the counselor-approval gate that currently blocks every pack from reaching the student until a counselor manually approves it.

**Architecture:** `RecommendationRun` moves straight from `QUEUED` to `PUBLISHED` inside `handle_research_message` (the worker task that already builds the pack) instead of stopping at `DRAFT_READY` to await a counselor's `approve_pack` call. A new `auto_publish_pack()` replaces `publish_pack()` (which required an `Approval` row) and is the only thing that ever sets `PackVersion.published_at` going forward. A candidate whose `evidence_confidence` is `"LOW"` is excluded from the pool at construction time instead of blocking the whole pack (the old `approve_pack` behavior) — this is the "low-confidence exclusion check moves into the pack-construction path" from the approved edit. The counselor's `review()` page loses its approve/request-changes form (there is nothing left to approve) but keeps its read-only pool view and its named-program-resolution tool, which is a separate, still-valid workflow (P1-8's "consider a named program" chat command still needs a human to verify a program the AI hasn't researched yet).

**Deviation from the approved wording:** the approved edit said the low-confidence check "moves into pack.py's pack-construction path." Having read `apps/funding/pack.py`, it is a pure pydantic/dataclass module (`CandidateFacts`, `build_pack`, `rank_candidates`) with zero Django import and zero production caller — it is a separate, not-yet-wired evaluation pipeline (confirmed: `CandidateFacts` is never instantiated outside tests). The actual Django-ORM pack construction that `approve_pack` gated — the one that creates real `PackVersion`/`PackCandidate` rows students see — lives in `apps/research/services.py::handle_research_message`. Moving ORM logic into `pack.py` would introduce a Django dependency into a currently framework-agnostic module for no benefit; the exclusion goes into `handle_research_message` instead, which is where "pack construction" actually happens today. `apps/funding/pack.py` already enforces the equivalent rule transitively (its `evaluate()` call has a `evidence_confidence != "LOW"` hard gate) — nothing there needs to change.

**Tech Stack:** Django 5, PostgreSQL, pytest-django. No new dependencies.

**Spec:** `phased requirements.md` (already amended this session: §2.1's new bullet, P1-4, P1-7.1, P1-10 "Internal reviewer QA", P1-11, P1-13, P1-14, §3.3, §3.5, §6, §8 — all now describe auto-published, ungated packs). DESIGN.md §8's "Approved v{n}" badge contract is **not** amended by this plan — see Task 7.

## Global Constraints

- No human actor anywhere in the recommendation-pack pipeline: pack construction → publication is fully automatic, with no `Approval` row and no counselor action in between.
- A candidate's `evidence_confidence == "LOW"` never enters a published pack's pool — this exclusion happens once, at pack construction, not as a whole-pack blocking gate.
- The named-program resolution workflow (P1-8: student asks about an unrecognized program, a human verifies it) is untouched — it is not part of "the recommendation pack stage," it is a separate research-verification step the corrected spec never touched.
- Every automated action still gets an `AuditEvent` (append-only, `actor=None` for system actions) — P1-14's audit requirement applies to automated actions too, not just human ones.
- Do not touch `templates/components/_approval_badge.html`'s copy or DESIGN.md §8 — that's Task 7, blocked on separate explicit user sign-off, same pattern as this session's earlier `phased requirements.md` amendment.
- Do not drop the `Approval` model, its table, or the `approved_version_id` column — no migration in this plan. `Approval` may be reused for Phase 2's document-approval workflow (§4.2.1); dropping and potentially re-adding it later is unnecessary churn for a plan that isn't touching documents.
- Do not touch `resolve_named_program`/`resolve_named_program_view`/`consider_named_program` — a pre-existing, separate workflow, not part of this change.

---

## File Structure

- **Modify `apps/funding/services.py`**: delete `publish_pack`, `require_assigned_counselor`, `_has_low_confidence_member`, `approve_pack`, `request_changes`; add `auto_publish_pack`.
- **Modify `apps/funding/models.py`**: delete the now-dead `PackVersion.approval` property.
- **Modify `apps/research/services.py`**: `handle_research_message` calls `auto_publish_pack` instead of stopping at `DRAFT_READY`; excludes low-confidence candidates from the pool via a new `_is_publishable_confidence` helper.
- **Modify `apps/funding/views.py`**: delete `_run_and_pack` (dead once `review()` stops needing "unpublished only"); simplify `review()` to a GET-only read view using `_run_and_latest_pack`; drop `low_confidence` from `_review_page`'s context; update the stale `_current_pack` comment.
- **Modify `apps/reports/services.py`**: reword the `ReportBlocked` message.
- **Modify `templates/counselor/review.html`**: remove the approve/request-changes form and the low-confidence warning block; keep the read-only pool and the named-program-resolution section.
- **Modify `templates/reports/consultation_report.html`**: replace the counselor-approval section with a pack-version/published-date line.
- **Modify `templates/student/_pack.html`**: reword "Research or counselor review is pending." to drop the counselor-review framing.
- **Modify `tests/acceptance/helpers.py`**: delete `SliceDriver.counselor_reviews_and_approves`.
- **Modify `tests/acceptance/test_vertical_slice.py`, `tests/acceptance/test_swap_render.py`, `tests/acceptance/test_phase1_workflows.py`**: drop the manual-approval step; add auto-publish coverage.
- **Modify `tests/funding/test_pack_service.py`, `tests/funding/test_review_publication.py`**: replace `Approval`-binding tests with `auto_publish_pack` supersession tests.
- **Modify `tests/reports/test_consultation_report.py`**: switch every test off `approve_pack` onto the `make_published_pack` fixture helper.
- **Create `tests/research/test_handle_research_message.py`**: new unit coverage for auto-publish and low-confidence exclusion at the source.

---

### Task 1: `auto_publish_pack` replaces the counselor-approval service functions

**Files:**
- Modify: `apps/funding/services.py`
- Modify: `apps/funding/models.py:130-132` (delete `PackVersion.approval` property)
- Test: `tests/funding/test_review_publication.py`

**Interfaces:**
- Produces: `auto_publish_pack(pack: PackVersion) -> PackVersion` in `apps/funding/services.py`, raising `PublicationBlocked` if `pack.superseded_at is not None`. Sets `pack.published_at`, flips the run's state to `PUBLISHED`, writes an `AuditEvent` with `actor=None`, `event="pack.published"`.
- Removes: `publish_pack`, `require_assigned_counselor`, `_has_low_confidence_member`, `approve_pack`, `request_changes` (no longer importable from `apps.funding.services`).

- [ ] **Step 1: Write the failing tests**

Replace the four obsolete tests in `tests/funding/test_review_publication.py` (`test_unassigned_counselor_cannot_approve`, `test_assigned_counselor_can_approve`, `test_low_confidence_candidate_blocks_publication`, `test_superseded_pack_cannot_be_approved`, `test_correction_creates_tenant_scoped_evaluation_example`, `test_view_logs_publication_blocked_denials`) with:

```python
import logging

import pytest
from django.db import DatabaseError, transaction

from apps.funding.models import AuditEvent, PackCandidate, PackVersion
from apps.funding.services import PublicationBlocked, auto_publish_pack, revise_pack
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_db_candidate, make_run


@pytest.fixture
def run(agency_a, membership_a):
    return make_run(agency_a, membership_a)


@pytest.fixture
def candidate(agency_a, run):
    return make_db_candidate(agency_a, run, program_name="MSc Chemistry", funding_gap="500.00")


@pytest.mark.django_db
def test_auto_publish_sets_published_at_and_run_state(agency_a, run, candidate):
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        published = auto_publish_pack(pack)
        assert published.published_at is not None
        run.refresh_from_db()
        assert run.state == run.State.PUBLISHED


@pytest.mark.django_db
def test_auto_publish_records_an_actorless_audit_event(agency_a, run, candidate):
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
        event = AuditEvent.objects.get(event="pack.published", object_id=pack.id)
        assert event.actor_id is None


@pytest.mark.django_db
def test_superseded_pack_cannot_be_auto_published(agency_a, run, candidate):
    """Once a newer version of a run's pack is published, the old version it
    superseded must never be publishable again."""
    with tenant_scope(agency_a.id):
        pack_v1 = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack_v1, candidate=candidate)
        pack_v2 = revise_pack(pack_v1)
        auto_publish_pack(pack_v2)
        stale_pack_v1 = PackVersion.objects.get(id=pack_v1.id)
        assert stale_pack_v1.superseded_at is not None
        with pytest.raises(PublicationBlocked, match="superseded"):
            auto_publish_pack(stale_pack_v1)


@pytest.mark.django_db
def test_audit_event_cannot_be_updated(agency_a, counselor_membership):
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.create(
            tenant=agency_a,
            actor=counselor_membership,
            event="pack.published",
            object_id=counselor_membership.id,
        )
        event.event = "rewritten"
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                event.save(update_fields=["event"])


@pytest.mark.django_db
def test_audit_event_cannot_be_deleted(agency_a, counselor_membership):
    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.create(
            tenant=agency_a,
            actor=counselor_membership,
            event="pack.published",
            object_id=counselor_membership.id,
        )
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                event.delete()
```

(`test_view_logs_publication_blocked_denials` is deleted outright, not replaced — the `/counselor/runs/<id>/approve/` POST branch it exercised is gone; Task 3 covers the view.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/funding/test_review_publication.py -v`
Expected: FAIL — `ImportError: cannot import name 'auto_publish_pack'`

- [ ] **Step 3: Replace the service functions**

In `apps/funding/services.py`, delete `require_assigned_counselor` (lines 52-64), `_has_low_confidence_member` (lines 67-70), `approve_pack` (lines 73-85), `request_changes` (lines 88-109), and replace `publish_pack` (lines 31-49) with:

```python
@transaction.atomic
def auto_publish_pack(pack: PackVersion) -> PackVersion:
    """Publish ``pack`` the moment the pipeline that built it finishes.

    No counselor approval, no ``Approval`` row: the recommendation pack is
    AI-generated and student-controlled from the start (see phased
    requirements.md §2.1). This is the only path that ever sets
    ``published_at``.
    """
    if pack.superseded_at is not None:
        raise PublicationBlocked("pack version has been superseded")
    PackVersion.objects.filter(run_id=pack.run_id, published_at__isnull=True).exclude(
        id=pack.id
    ).update(superseded_at=timezone.now())
    pack.published_at = timezone.now()
    pack.save(update_fields=["published_at"])
    RecommendationRun.objects.filter(id=pack.run_id).update(state=RecommendationRun.State.PUBLISHED)
    AuditEvent.objects.create(actor=None, event="pack.published", object_id=pack.id)
    return pack
```

Update the import block at the top of the file to drop `Approval` and `EvaluationExample` (no longer referenced) and `CounselorAssignment` (only `require_assigned_counselor` used it):

```python
from decimal import Decimal
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from apps.research.models import ConsultantResearchTask
from apps.tenancy.models import Membership

from .models import (
    AuditEvent,
    EvidenceClaim,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
    StudentDecision,
)
```

In `apps/funding/models.py`, delete the `approval` property (lines 130-132):

```python
    @property
    def current_version_id(self) -> UUID:
        return self.id
```

(the `approval` property that followed it is removed; `approved_version_id` stays as an unused nullable column — no migration).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/funding/test_review_publication.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/funding/services.py apps/funding/models.py tests/funding/test_review_publication.py
git commit -m "feat: auto-publish recommendation packs, remove counselor approval gate"
```

---

### Task 2: Wire auto-publish into the research worker, exclude low-confidence candidates at construction

**Files:**
- Modify: `apps/research/services.py`
- Test: `tests/research/test_handle_research_message.py` (new)

**Interfaces:**
- Consumes: `auto_publish_pack(pack: PackVersion) -> PackVersion` from Task 1.
- Produces: `_is_publishable_confidence(evidence_confidence: str) -> bool` in `apps/research/services.py` — `True` unless `evidence_confidence == "LOW"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_handle_research_message.py`:

```python
from decimal import Decimal

import pytest

from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import MinimalProfile
from apps.funding.models import PackCandidate, PackVersion, RecommendationCandidate, RecommendationRun
from apps.research.egress import FetchResult
from apps.research.schemas import ResearchMessage
from apps.research.services import _is_publishable_confidence, handle_research_message
from apps.tenancy.context import tenant_scope

_FIXTURE_BODY = (
    b'{"program_name":"MSc Chemistry","annual_cost":"12000.00",'
    b'"funding_coverage":"12000.00","currency":"EUR","eligible":true}'
)


def _fixture() -> FetchResult:
    return FetchResult(
        final_url="https://official.example.test/program.json",
        redirects=(),
        content_type="application/json",
        body=_FIXTURE_BODY,
    )


def _run(agency, membership) -> RecommendationRun:
    with tenant_scope(agency.id):
        profile = create_profile_version(
            student=membership,
            snapshot=MinimalProfile.model_validate(
                {
                    "target_field": "Chemistry",
                    "intended_intake": "2027-09-01",
                    "funding_dependency": "MANDATORY",
                    "strategy": "FUNDING_FIRST",
                    "application_budget": "150",
                }
            ),
        )
        return RecommendationRun.objects.create(profile_version=profile)


def test_is_publishable_confidence_excludes_only_low():
    assert _is_publishable_confidence("HIGH") is True
    assert _is_publishable_confidence("MEDIUM") is True
    assert _is_publishable_confidence("LOW") is False


@pytest.mark.django_db(transaction=True)
def test_handle_research_message_auto_publishes_the_pack(agency_a, membership_a):
    run = _run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)

    pack = handle_research_message(message, _fixture())

    with tenant_scope(agency_a.id):
        assert pack.published_at is not None
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.PUBLISHED
        assert PackCandidate.objects.filter(pack_version=pack).count() == 1


@pytest.mark.django_db(transaction=True)
def test_low_confidence_candidate_is_excluded_from_the_pool(agency_a, membership_a, monkeypatch):
    """The candidate created by handle_research_message never has LOW confidence
    today (OfficialFixture carries no such signal), so this drives the same
    exclusion path a future richer extraction pipeline will hit: a candidate
    whose confidence is LOW never becomes a PackCandidate."""
    run = _run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)

    original_create = RecommendationCandidate.objects.create

    def _create_as_low_confidence(*args, **kwargs):
        kwargs["evidence_confidence"] = "LOW"
        return original_create(*args, **kwargs)

    monkeypatch.setattr(RecommendationCandidate.objects, "create", _create_as_low_confidence)

    pack = handle_research_message(message, _fixture())

    with tenant_scope(agency_a.id):
        assert PackCandidate.objects.filter(pack_version=pack).count() == 0
        assert pack.published_at is None
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.DRAFT_READY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/research/test_handle_research_message.py -v`
Expected: FAIL — `ImportError: cannot import name '_is_publishable_confidence'`

- [ ] **Step 3: Implement**

In `apps/research/services.py`, add the import and helper, and replace the tail of `handle_research_message`:

```python
from apps.funding.evaluation import funding_gap
from apps.funding.models import (
    EvidenceClaim,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import auto_publish_pack
```

```python
def _is_publishable_confidence(evidence_confidence: str) -> bool:
    """P1-6's hard gate at the point a candidate would enter a pack's pool.

    A LOW-confidence candidate is excluded here rather than blocking the whole
    pack — there is no counselor left to unblock it (phased requirements.md
    §2.1, P1-6).
    """
    return evidence_confidence != "LOW"
```

Replace the final four lines of `handle_research_message` (from `pack = PackVersion.objects.create(...)` to `return pack`):

```python
    pack = PackVersion.objects.create(run=run, version=1)
    if _is_publishable_confidence(candidate.evidence_confidence):
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
    else:
        run.state = RecommendationRun.State.DRAFT_READY
        run.save(update_fields=["state"])
    return pack
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/research/test_handle_research_message.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/research/services.py tests/research/test_handle_research_message.py
git commit -m "feat: auto-publish the pack when the research pipeline finishes"
```

---

### Task 3: Simplify the counselor review view and template

**Files:**
- Modify: `apps/funding/views.py`
- Modify: `templates/counselor/review.html`
- Test: `tests/funding/test_review_publication.py` (append)

**Interfaces:**
- Consumes: `_run_and_latest_pack` (already exists, `apps/funding/views.py:300-315`).
- Removes: `_run_and_pack` (`apps/funding/views.py:280-297`).

- [ ] **Step 1: Write the failing test**

Append to `tests/funding/test_review_publication.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_review_page_shows_the_published_pack_without_an_approval_form(
    client, agency_a, domain_a, counselor_user, run, candidate
):
    from tests.conftest import verify_mfa_session

    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        auto_publish_pack(pack)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)

    response = client.get(f"/counselor/runs/{run.id}/approve/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert b'name="action" value="approve"' not in response.content
    assert b"MSc Chemistry" in response.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/funding/test_review_publication.py::test_review_page_shows_the_published_pack_without_an_approval_form -v`
Expected: FAIL — `Http404` (`_run_and_pack` only finds an unpublished, non-superseded version; the pack here is already published)

- [ ] **Step 3: Simplify `review()` and its context**

In `apps/funding/views.py`, delete `_run_and_pack` (lines 280-297) entirely.

Replace the `review()` function (lines 363-403):

```python
@login_required
def review(request: HttpRequest, run_id: str) -> HttpResponse:
    _current_counselor(request)
    run, pack = _run_and_latest_pack(run_id)
    return _review_page(request, run, pack)
```

In `_review_page` (lines 318-360), drop the `low_confidence` computation (it is always empty now — Task 2 excludes low-confidence candidates before they ever join a pool) and its context key:

```python
def _review_page(
    request: HttpRequest,
    run: RecommendationRun,
    pack: PackVersion,
    *,
    status: int = 200,
    error: str | None = None,
    error_form: str | None = None,
    error_field: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    """Render the counselor's read-only recommendation context and the
    named-program-resolution tool.

    Recommendation packs auto-publish (phased requirements.md §2.1); this page
    no longer has an approval action, only P1-13's read-only context for
    document tailoring plus P1-8's named-program resolution.
    """
    pool = PackCandidate.objects.filter(pack_version=pack).select_related("candidate__evidence")
    checking = (
        RecommendationCandidate.objects.filter(
            run=run, state=RecommendationCandidate.State.CHECKING
        )
        .select_related("evidence")
        .order_by("program_name")
    )
    return render(
        request,
        "counselor/review.html",
        {
            "pack": pack,
            "pool": pool,
            "checking": checking,
            "error": error,
            "error_form": error_form,
            "error_field": error_field,
            "form_values": form_values or {},
        },
        status=status,
    )
```

Update the `.services` import (drop `approve_pack`, `request_changes`):

```python
from .services import (
    PackCommandError,
    PublicationBlocked,
    consider_named_program,
    pool_funding_gap_totals,
    reject_candidate,
    replace_candidate,
    resolve_named_program,
)
```

Update the stale comment on `_current_pack` (lines 89-93):

```python
def _current_pack(student: Membership) -> PackVersion | None:
    # Once a run's *initial* pack has been auto-published (run.state becomes
    # PUBLISHED — apps/funding/services.py::auto_publish_pack), later student
    # commands (reject/replace) create newer pack versions that supersede it
    # for display purposes. The run's PUBLISHED state gates visibility, not
    # each version's own published_at, so the student always sees the latest
    # version once the run has published once. ``version`` is only unique
    # *within* a run, so the run must be picked first (most recently created
    # PUBLISHED run) before ranking versions inside it.
```

Also update `_run_and_latest_pack`'s docstring (it no longer contrasts with a "pre-publication-only" review page):

```python
def _run_and_latest_pack(run_id: str | UUID) -> tuple[RecommendationRun, PackVersion]:
    """The latest pack version for a run, published or not.

    Used by the counselor review page and by resolve_named_program_view's
    error re-render — both need the latest version regardless of publish
    state, since packs publish automatically and there is no unpublished
    "awaiting review" version to prefer.
    """
```

In `templates/counselor/review.html`, remove the low-confidence warning block and the approve/request-changes form (old lines 8-30), replacing them with the badge:

```html
{% extends "base.html" %}
{% block title %}Counselor review{% endblock %}
{% block content %}
<h1>Review recommendation</h1>
{% for item in pool %}
  {% include "student/_candidate.html" with item=item commands=False %}
{% endfor %}
<p>{% include "components/_approval_badge.html" with pack=pack %}</p>
{% if checking %}
<section>
  <h2>Named program requests awaiting research</h2>
  {% for candidate in checking %}
  <article class="panel">
    <h3>{{ candidate.program_name }}</h3>
    {% with cid=candidate.id|stringformat:"s" %}
    <form method="post" action="{% url 'counselor-resolve-named-program' pack.run_id candidate.id %}">
      {% csrf_token %}
      {% include "components/_form_errors.html" with error=error error_form=error_form error_field=error_field error_match=cid only %}
      {% if error_form == cid %}
      {% include "components/_field.html" with kind="url" label="Official source URL" name="source_url" required=True input_id="source-url-"|add:cid helper="Must be an https:// URL." value=form_values.source_url error=error error_match=cid error_form=error_form error_field=error_field only %}
      {% include "components/_field.html" with label="Rationale" name="reason" required=True input_id="rationale-"|add:cid value=form_values.reason error=error error_match=cid error_form=error_form error_field=error_field only %}
      {% else %}
      {% include "components/_field.html" with kind="url" label="Official source URL" name="source_url" required=True input_id="source-url-"|add:cid helper="Must be an https:// URL." only %}
      {% include "components/_field.html" with label="Rationale" name="reason" required=True input_id="rationale-"|add:cid only %}
      {% endif %}
      <label class="field-choice"><input type="checkbox" name="eligible" value="true"> Eligible</label>
      <button type="submit">Resolve</button>
    </form>
    {% endwith %}
  </article>
  {% endfor %}
</section>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/funding/test_review_publication.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/funding/views.py templates/counselor/review.html tests/funding/test_review_publication.py
git commit -m "refactor: counselor review page is read-only, no approval action left"
```

---

### Task 4: Report service no longer references counselor approval

**Files:**
- Modify: `apps/reports/services.py:33-34`
- Modify: `templates/reports/consultation_report.html`
- Modify: `tests/reports/test_consultation_report.py`

**Interfaces:**
- No signature changes — `generate_report(payment, pack, *, store=None)` keeps blocking on `pack.published_at is None`, just with corrected wording.

- [ ] **Step 1: Write the failing test**

In `tests/reports/test_consultation_report.py`, replace `test_report_blocked_without_counselor_approval`:

```python
@pytest.mark.django_db
def test_report_blocked_when_pack_not_yet_published(agency_a, membership_a, make_run, fake_store):
    from apps.funding.models import PackVersion

    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
        )
        with pytest.raises(ReportBlocked, match="published"):
            generate_report(payment, pack, store=fake_store)
```

Replace every other test in the file that calls `approve_pack` (`test_report_requires_payment_and_exact_approval`, `test_report_blocked_when_payment_student_does_not_match_pack_student`, `test_report_content_has_required_sections_and_no_internal_reasoning`, `test_report_suppresses_placeholder_funding_gap`, `test_download_view_serves_report_to_the_student`, `test_download_view_denies_cross_tenant_access`) — drop their `CounselorAssignment`/`approve_pack` block and use the `make_published_pack`/`make_db_candidate`/`make_run` helpers from `tests/funding/conftest.py` instead. Example (`test_report_requires_payment_and_exact_approval`, renamed):

```python
@pytest.mark.django_db
def test_report_requires_payment_and_a_published_pack(agency_a, membership_a, fake_store):
    from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
        )
        report = generate_report(payment, pack, store=fake_store)
        assert report.pack_version_id == pack.id
        assert report.sha256
```

Apply the same `make_run` + `make_db_candidate` + `make_published_pack` substitution to the other five tests, dropping their now-unused `counselor_membership` fixture parameter and `CounselorAssignment`/`approve_pack` imports and calls.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/reports/test_consultation_report.py -v`
Expected: FAIL — `ReportBlocked` message no longer matches `"published"` (still says "counselor-approved")

- [ ] **Step 3: Implement**

In `apps/reports/services.py`, line 34:

```python
    if pack.published_at is None:
        raise ReportBlocked("pack must be published")
```

In `templates/reports/consultation_report.html`, replace the `id="approval"` section (old lines 53-57):

```html
    <section id="publication">
      <h2>Report and pack version</h2>
      <p>Pack version {{ pack.version }}, published {{ pack.published_at }}.</p>
    </section>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/reports/test_consultation_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/reports/services.py templates/reports/consultation_report.html tests/reports/test_consultation_report.py
git commit -m "fix: report blocks on pack publication, not counselor approval"
```

---

### Task 5: Fix acceptance-level tests and the student-facing pending copy

**Files:**
- Modify: `tests/acceptance/helpers.py`
- Modify: `tests/acceptance/test_vertical_slice.py`
- Modify: `tests/acceptance/test_swap_render.py`
- Modify: `tests/acceptance/test_phase1_workflows.py`
- Modify: `templates/student/_pack.html`
- Modify: `tests/funding/test_pack_service.py`

**Interfaces:**
- Consumes: `auto_publish_pack` (Task 1).

- [ ] **Step 1: Write the failing tests**

In `tests/acceptance/helpers.py`, delete `SliceDriver.counselor_reviews_and_approves` (lines 104-131) entirely.

Rewrite `tests/acceptance/test_vertical_slice.py`:

```python
import pytest

from apps.funding.models import PackVersion
from apps.funding.services import PublicationBlocked, auto_publish_pack, revise_pack
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db(transaction=True)
def test_thin_slice_publishes_automatically_after_research(slice_driver) -> None:
    run = slice_driver.student_submits_profile_and_starts_research()
    message = slice_driver.receive_message()
    assert message.tenant_id == run.tenant_id
    pending = slice_driver.student_opens_dashboard()
    assert pending.contains('hx-trigger="every 5s"')
    slice_driver.worker_processes(message)
    page = slice_driver.student_opens_dashboard()
    with tenant_scope(run.tenant_id):
        pack = PackVersion.objects.get(run=run, published_at__isnull=False)
    assert pack.published_at is not None
    assert page.contains("Official source")
    assert page.contains("Funding gap")
    assert page.contains("Approved v")  # DESIGN.md §8 approval badge
    assert page.contains('src="/static/vendor/htmx.min.js"')
    # 4xx validation re-renders must actually swap in the browser; without
    # this config htmx 2 drops them silently.
    assert page.contains('name="htmx-config"')
    assert page.contains("--brand-primary: #123456")
    assert page.contains('src="https://assets.example.test/agency-a.svg"')


@pytest.mark.django_db(transaction=True)
def test_superseded_pack_cannot_be_republished(slice_driver) -> None:
    run = slice_driver.student_submits_profile_and_starts_research()
    slice_driver.worker_processes(slice_driver.receive_message())
    with tenant_scope(run.tenant_id):
        published = PackVersion.objects.get(run=run, published_at__isnull=False)
        changed = revise_pack(published)
        auto_publish_pack(changed)
        stale = PackVersion.objects.get(id=published.id)
        assert stale.superseded_at is not None
        with pytest.raises(PublicationBlocked, match="superseded"):
            auto_publish_pack(stale)
```

In `tests/acceptance/test_swap_render.py`, delete line 30 (`slice_driver.counselor_reviews_and_approves(run)`).

In `tests/acceptance/test_phase1_workflows.py`:

Replace `test_every_approval_is_exact_version_linked_to_its_pack` (lines 36-54):

```python
@pytest.mark.django_db(transaction=True)
def test_every_publication_is_an_audit_event(agency_a, membership_a) -> None:
    """Regression check for Task 13, updated for auto-publish: every pack
    publication still leaves an append-only audit event, even with no human
    actor (P1-14 applies to automated actions too)."""
    from apps.funding.models import AuditEvent, PackCandidate, PackVersion

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        published = auto_publish_pack(pack)
        event = AuditEvent.objects.get(event="pack.published", object_id=published.id)
        assert event.actor_id is None
```

Update the import block (lines 14-19) to drop `approve_pack`, `publish_pack` and add `auto_publish_pack`:

```python
from apps.funding.services import (
    PublicationBlocked,
    auto_publish_pack,
    revise_pack,
)
```

`CounselorAssignment` import (line 23) is now unused in this file — remove it too.

Replace `test_paid_consultation_produces_a_versioned_report_tied_to_the_approved_pack` (lines 152-188), renamed:

```python
@pytest.mark.django_db
def test_paid_consultation_produces_a_versioned_report_tied_to_the_pack_version(
    agency_a, membership_a
) -> None:
    from apps.reports.models import ConsultationPayment
    from apps.reports.services import generate_report

    class FakeObjectStore:
        def __init__(self) -> None:
            self._data: dict[str, bytes] = {}

        def put(self, key: str, body: bytes) -> str:
            self._data[key] = body
            return "test-version-1"

        def get(self, key: str) -> bytes:
            return self._data[key]

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(agency_a, run)
    pack = make_published_pack(agency_a, run, (candidate,))
    with tenant_scope(agency_a.id):
        payment = ConsultationPayment.objects.create(
            tenant=agency_a,
            student=membership_a,
            amount="49.00",
            currency="USD",
            status="PAID",
        )
        report = generate_report(payment, pack, store=FakeObjectStore())
        assert report.pack_version_id == pack.id
        assert report.sha256
```

(`counselor_membership` parameter and `CounselorAssignment.objects.create(...)` block are dropped along with it.)

In `templates/student/_pack.html`, line 32:

```html
  <p>Research is in progress.
    <span class="htmx-indicator">Checking for updates&hellip;</span></p>
```

In `tests/funding/test_pack_service.py`: delete `test_rejecting_invalidates_the_prior_approval_by_exact_version_binding` (lines 177-188) — its subject, `Approval`-exact-version binding, no longer exists; `test_superseded_pack_cannot_be_auto_published` (Task 1) is the equivalent coverage in the file that actually owns publish mechanics. Drop the now-unused `Approval` import (line 6) and `publish_pack` import (line 17).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/acceptance/test_vertical_slice.py tests/acceptance/test_swap_render.py tests/acceptance/test_phase1_workflows.py tests/funding/test_pack_service.py -v`
Expected: FAIL — `AttributeError: 'SliceDriver' object has no attribute 'counselor_reviews_and_approves'` and `ImportError` on `approve_pack`/`publish_pack`/`Approval`

- [ ] **Step 3: Confirm the implementation (already done in Tasks 1-2) satisfies these**

No production code changes in this task — it only depends on Task 1's `auto_publish_pack` and Task 2's wiring already being in place.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/acceptance/test_vertical_slice.py tests/acceptance/test_swap_render.py tests/acceptance/test_phase1_workflows.py tests/funding/test_pack_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/helpers.py tests/acceptance/test_vertical_slice.py tests/acceptance/test_swap_render.py tests/acceptance/test_phase1_workflows.py templates/student/_pack.html tests/funding/test_pack_service.py
git commit -m "test: update acceptance suite for auto-published packs, drop counselor-review copy"
```

---

### Task 6: Full-suite verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: All tests pass (no `approve_pack`/`request_changes`/`require_assigned_counselor`/`publish_pack`/`_has_low_confidence_member` references remain anywhere).

- [ ] **Step 2: Confirm no dangling references**

Run: `grep -rn "approve_pack\|request_changes\|require_assigned_counselor\|_has_low_confidence_member\|publish_pack\b" apps/ templates/ tests/`
Expected: No matches (`publish_pack` as a substring of `auto_publish_pack` will match — check each hit is `auto_publish_pack`).

`tests/infra/test_template.py::test_web_task_role_can_enqueue_but_not_write_evidence` — checked, no change: it asserts the web IAM role can't `s3:PutObject` (an infra/CloudFormation-template test unrelated to `approve_pack`), and is only referenced from `apps/reports/services.py::generate_report`'s docstring as a reason `generate_report` must stay worker-side. Task 4 doesn't touch that docstring's reasoning, only the `ReportBlocked` message text below it — this test needs no edit, just a run to confirm it still passes.

- [ ] **Step 3: Lint, type-check, security-scan**

Run: `uv run ruff check . && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config && uv run python manage.py check && uv run python manage.py makemigrations --check --dry-run`
Expected: All clean. `makemigrations --check` must show no pending migration — this plan deliberately makes no model field changes.

- [ ] **Step 4: `ponytail:ponytail-review` the full diff**

Run the `ponytail-review` skill against `git diff master...HEAD` (or the working branch diff) before opening a PR.

- [ ] **Step 5: `security-review` the diff**

Dispatch the `security-review` skill specifically flagging: (a) `require_assigned_counselor`'s removal — confirm no other code path silently relied on it for cross-student authorization, since `resolve_named_program_view` was already unguarded by it before this change (pre-existing, not introduced here — verify, don't fix, unless the review finds it's now worse); (b) the low-confidence exclusion in `apps/research/services.py` — confirm a LOW-confidence candidate genuinely never reaches `PackCandidate`/the student.

---

### Task 7 — NOT part of this plan, requires separate explicit sign-off

`templates/components/_approval_badge.html` and DESIGN.md §8's "Approved v{n} / Awaiting approval / Approval invalidated" contract still describe **counselor** approval. After this plan, `published_at` is set automatically, so the badge will show "Approved v{n}" to students and counselors for a pack no counselor ever approved — technically functional (the template still branches correctly on `published_at`), but the copy now asserts something false.

Do not change this in the same pass as Tasks 1-6. When the user gives explicit sign-off (same pattern as this session's `phased requirements.md` → DESIGN.md contract amendment), the follow-up work is:
- Reword DESIGN.md §8's badge contract (drop "counselor approval is a first-class badge"; decide new copy — e.g. "Published v{n}" / something for a not-yet-published state, which under auto-publish is now only transient).
- Update `templates/components/_approval_badge.html`'s copy and its `{% comment %}` header to match.
- Update `docs/validation/design-lint-baseline.md`'s §8 approval-vocabulary entries (lines ~48, ~57, ~105, ~233-235) — a project tracking doc, not authoritative, but directly documents the vocabulary this plan makes stale.
- `docs/superpowers/plans/2026-08-10-phase-1-funding-intelligence-concierge-mvp.md` and `docs/validation/phase1-scorecard.md` still label a traceability row "P1-10 Consultant review" — historical planning artifacts, harmless to leave as-is, but worth a one-line note if anyone re-reads them.
