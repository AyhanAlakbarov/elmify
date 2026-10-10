# Concierge, Audit, Report, and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Execution ledger — reconciled 2026-08-16

- **Implementation:** Tasks 13-18 were implemented directly against the codebase (not through this skill's SDD ledger — no `.superpowers/sdd/2026-08-15-concierge-audit-report-deployment/` directory exists) across commits `7c99a2f` (Task 13), `75dfd7f` (Task 14), `2c5d0a2` (Task 15), `70f3bcf` (Task 16), `adf80e8` (Task 17), and `741773e` (Task 18), followed by nine fix-round commits (`9e09fba`..`d6d6d7a`, `303c6ef`, `bc2d450`, `ffca1ae`, `17b6ead`, `75e756e`) addressing review findings: mandatory staff MFA, MFA rate-limiting, RLS/tenant-FK gaps on `CounselorAssignment`/`EvaluationExample`, 403-not-500 on role mismatch, GuardDuty scope alignment, and payment/pack student verification.
- **This file's checkboxes were never ticked at the time** — this session (2026-08-16) confirmed the work against the codebase (all named test files present, `apps/audit`/`apps/concierge`/`apps/reports` all exist with migrations applied, full suite passing) and checked them off retroactively.
- **Independent security review:** a read-only application-code review ran on 2026-08-16 (`docs/security/2026-08-16-tasks-13-18-review.md`), the first recorded independent sign-off on this range. It found and fixed nine issues — none launch-blocking, all merged to `master` as `4f1a5ba`..`910b04f` (fast-forward, no conflicts). One of the nine (`910b04f`) was a stale Task 7 test assertion unrelated to Tasks 13-18, broken since Task 9.
- **Gate status:** all 34 steps across Tasks 13-18 complete. Full suite: 557 passed, 2 skipped, 0 failed. Bandit/pip-audit/mypy/ruff clean. Real Phase 1 acceptance remains blocked on non-synthetic benchmark/consultant-review data (Task 18's own finding, unrelated to this reconciliation) — see `docs/validation/phase1-scorecard.md` and `docs/runbooks/shadow-pilot.md`.

**Goal:** Implement Tasks 13–18 of the Phase 1 plan — append-only counselor review and audit, the paid Consultation Recommendation Report, white-label concierge roles and roadmap, quarantined-document/audit-dossier/export/deletion handling, the one-region CloudFormation deployment, and the Phase 1 acceptance/benchmark gates.

**Architecture:** Extends the existing Django monolith (`apps/funding`, `apps/tenancy`, `apps/research`) rather than the speculative multi-app split the parent plan sketched before Tasks 1–12 landed. `Approval` and `AuditEvent` already live in `apps/funding/models.py` — this plan hardens them in place instead of recreating them in a new `apps/audit` app. Three genuinely new apps are still needed because nothing today covers their responsibility: `apps/concierge` (roles, roadmap, documents, fees), `apps/reports` (paid report generation), and `apps/audit` (dossier/export/deletion — a thin app over the funding audit trail and concierge records, not a new home for `AuditEvent` itself).

**Tech Stack:** Python 3.12, Django 5.2 LTS, Django templates, HTMX, PostgreSQL, psycopg 3, boto3, Amazon SQS/S3/RDS/ECS Fargate/ALB/CloudWatch/GuardDuty, CloudFormation, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/plans/2026-08-10-phase-1-funding-intelligence-concierge-mvp.md` (Tasks 13–18, lines 1928–2409; Global Constraints, lines 11–27; Approved-requirement traceability, lines 2411–2435). This plan implements those tasks against the codebase as it actually exists after Tasks 1–12, correcting draft names that changed during implementation. Read both documents — this plan does not restate constraints already fixed there.

## Global Constraints

(Copied verbatim from the parent plan — every task below implicitly includes these.)

- Establish verified-host and authenticated-membership tenant context before tenant-owned ORM access. Missing, invalid, expired, or conflicting context must fail closed in requests, jobs, administrator paths, object keys, and exports.
- Every tenant-owned row and relationship carries `tenant_id`; tenant-aware uniqueness and foreign-key constraints prevent cross-tenant references. PostgreSQL RLS is secondary defense, uses transaction-scoped `SET LOCAL`, and denies access when the setting is absent.
- Deterministic Python owns eligibility gates, affordability arithmetic, score thresholds, duration rules, budget limits, and pack construction.
- Require counselor approval of every initial recommendation pack. Publication is atomic, exact-version bound, and leaves the last reviewed result available if replacement research fails.
- Phase 1 acceptance requires at least `90%` published-recommendation precision, at least `80%` recall on the five-profile benchmark, `100%` official-source support for material claims, zero unsupported funding claims, and zero cross-tenant access in the specified tests.
- Do not implement Phase 2–4 automation, Redis, Kubernetes, microservices, a graph/vector database, a separate JavaScript frontend, autonomous portal submission, application-fee collection, payment execution, or cross-tenant training/ETL.
- Consultants may record approved manual concierge work in the roadmap and audit trail; Phase 1 contains no dormant browser-submission, payment, inbox-monitoring, document-generation, or CAPTCHA-solving code.
- Use downloadable, versioned HTML for the Consultation Recommendation Report and audit dossier; add PDF only after an approved visual/format decision (parent plan, "Deliberate Phase 1 simplifications").

## Codebase corrections to the original Task 13–18 draft

The parent plan's Task 13–18 text was written before Tasks 1–12 existed. These are the load-bearing differences; every task below is written against the corrected names.

| Draft assumed | Actual (verified `2026-08-15`) |
|---|---|
| `apps/audit/models.py` creates `Approval`/`AuditEvent` from scratch | `Approval` (`apps/funding/models.py:136`) and `AuditEvent` (`apps/funding/models.py:155`) already exist and are in active use by `apps/funding/services.py:approve_pack`/`publish_pack`. No append-only DB trigger exists on `funding_auditevent` yet — that part of Task 13 is still real work. |
| `approve_version(actor, object_type, object_id, version_id, decision, reason)` | `approve_pack(pack: PackVersion, actor: Membership) -> PackVersion` (`apps/funding/services.py:50`) exists but has no assignment check beyond "any active counselor in the tenant", no `reason`, and no conflict/confidence gate. `Approval` has no `reason` field yet. |
| A generic `require_assigned_counselor` already exists | It does not. `apps/funding/views.py:_current_counselor` fetches *any* active `COUNSELOR` membership — there is no `CounselorAssignment` model anywhere in the codebase. Any counselor in an agency can currently approve any student's pack. |
| `RecommendationCandidate`/evidence carries a stored confidence field | Only the Pydantic evaluation-time schema (`apps/funding/evaluation.py:CandidateFacts.evidence_confidence: Literal["HIGH","MEDIUM","LOW"]`) carries confidence; the persisted `RecommendationCandidate` (`apps/funding/models.py:47`) does not. Escalation logic needs a persisted field. |
| `apps.owner`/`AGENCY_OWNER`/`PLATFORM_ADMIN` roles exist | `Membership.Role` (`apps/tenancy/models.py:75`) has exactly `OWNER`, `COUNSELOR`, `STUDENT`. There is no platform-admin concept (no cross-tenant staff role) anywhere yet. |
| A boto3 S3 client wrapper already exists to copy | Only a `Protocol` exists: `apps/research/snapshot.py:ObjectStore` (`put(key, body) -> str`). No concrete boto3-backed implementation exists anywhere in the codebase yet — `apps/research/queue.py` shows the established `boto3.client(...)` construction pattern for SQS; report/document storage should mirror it for S3. |
| `apps/audit`, `apps/reports`, `apps/concierge` exist in some form | Confirmed absent. `ls apps/` today: `accounts`, `funding`, `reference_data.py`, `research`, `tenancy`. |
| `infra/template.yaml` is a placeholder | It exists (Tasks 4/5 added the queue/egress boundary resources) but has no ALB, Fargate services, RDS, GuardDuty, or web/worker container definitions yet — Task 17 completes it, doesn't start it. |

## Planned file map

| Area | Files | Responsibility |
|---|---|---|
| Funding (hardened) | `apps/funding/models.py`, `apps/funding/services.py`, `apps/funding/migrations/0010+`, `templates/counselor/review.html` | Assignment-checked approval, append-only audit trigger, correction examples |
| Reports | `apps/reports/{apps,models,services,views,urls}.py`, `templates/reports/consultation_report.html` | Paid Consultation Recommendation Report generation and download |
| Concierge | `apps/concierge/{apps,models,services,views,urls,documents}.py`, `apps/tenancy/models.py` (roles), templates | Roles, roadmap, manual operations, ledger/receipts, quarantined documents |
| Audit reporting | `apps/audit/{apps,models,services,exports,deletion}.py`, `templates/audit/dossier.html` | Dossier rendering, tenant/student export, deletion state machine |
| Storage | `apps/research/storage.py` | First concrete boto3 S3-backed `ObjectStore`, shared by reports and documents |
| Infrastructure | `infra/template.yaml`, `infra/parameters/*.json`, `scripts/{deploy,smoke,restore_backup}.sh`, `docs/runbooks/*.md` | Complete one-region CloudFormation stack |
| Validation | `tests/acceptance/`, `tests/benchmarks/`, `docs/validation/phase1-scorecard.md` | Phase 1 gates and scorecard |

---

## Milestone 2 — Human oversight and concierge operations

### Task 13: Make counselor review, publication, and audit append-only

**Files:**
- Modify: `apps/tenancy/models.py` (add `CounselorAssignment`)
- Create: `apps/tenancy/migrations/0005_counselor_assignment.py`
- Modify: `apps/funding/models.py` (add `reason` to `Approval`, add `evidence_confidence` to `RecommendationCandidate`, add `EvaluationExample`)
- Create: `apps/funding/migrations/0010_review_hardening.py`
- Create: `apps/funding/migrations/0011_audit_event_append_only.py`
- Modify: `apps/funding/services.py` (`approve_pack`, new `request_changes`, new `require_assigned_counselor`)
- Modify: `apps/funding/views.py` (`review` view uses `require_assigned_counselor`, renders conflicts/confidence)
- Modify: `templates/counselor/review.html`
- Test: `tests/funding/test_review_publication.py`
- Test: `tests/tenancy/test_counselor_assignment.py`

**Interfaces:**
- Consumes: `PackVersion` (`apps/funding/models.py:73`), `Approval` (`apps/funding/models.py:136`), `AuditEvent` (`apps/funding/models.py:155`), `Membership` (`apps/tenancy/models.py:75`), `set_local_tenant` (`apps/tenancy/db.py`).
- Produces: `CounselorAssignment(tenant, counselor: Membership, student: Membership, active)`, `require_assigned_counselor(actor: Membership, student_id: UUID) -> CounselorAssignment`, `EvaluationExample(tenant, source_event: AuditEvent, input_schema_version: int, expected_structured_result: dict, allowed_purposes: list[str])`, `approve_pack(pack: PackVersion, actor: Membership, reason: str) -> PackVersion` (now assignment- and confidence-gated), `request_changes(pack: PackVersion, actor: Membership, reason: str) -> Approval`.

- [x] **Step 1: Write the assignment-gate and append-only tests**

```python
# tests/tenancy/test_counselor_assignment.py
import pytest
from django.db import IntegrityError

from apps.tenancy.models import CounselorAssignment


@pytest.mark.django_db
def test_unassigned_counselor_cannot_be_looked_up_for_student(
    agency_a, counselor_membership, membership_a
):
    with pytest.raises(CounselorAssignment.DoesNotExist):
        CounselorAssignment.objects.get(
            counselor=counselor_membership, student=membership_a, active=True
        )


@pytest.mark.django_db
def test_assignment_is_unique_per_student(agency_a, counselor_membership, membership_a):
    CounselorAssignment.objects.create(
        tenant=agency_a, counselor=counselor_membership, student=membership_a
    )
    with pytest.raises(IntegrityError):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
```

```python
# tests/funding/test_review_publication.py (new assertions added to the existing file)
import pytest
from django.db import DatabaseError
from django.db import transaction

from apps.funding.models import Approval, AuditEvent
from apps.funding.services import PublicationBlocked, approve_pack, request_changes
from apps.tenancy.models import CounselorAssignment


@pytest.mark.django_db
def test_unassigned_counselor_cannot_approve(agency_a, counselor_membership, make_published_pack):
    pack = make_published_pack(agency_a)
    with pytest.raises(PublicationBlocked):
        approve_pack(pack, counselor_membership, reason="looks good")


@pytest.mark.django_db
def test_assigned_counselor_can_approve(agency_a, counselor_membership, membership_a, make_run):
    from apps.funding.pack import build_pack  # noqa: local import mirrors existing test style
    from apps.funding.models import PackVersion

    run = make_run(agency_a, membership_a)
    pack = PackVersion.objects.create(run=run, version=1)
    CounselorAssignment.objects.create(
        tenant=agency_a, counselor=counselor_membership, student=membership_a
    )
    approved = approve_pack(pack, counselor_membership, reason="matches goals")
    assert approved.published_at is not None


@pytest.mark.django_db
def test_low_confidence_candidate_blocks_publication(
    agency_a, counselor_membership, membership_a, make_run, make_db_candidate
):
    from apps.funding.models import PackCandidate, PackVersion

    run = make_run(agency_a, membership_a)
    candidate = make_db_candidate(run, evidence_confidence="LOW")
    pack = PackVersion.objects.create(run=run, version=1)
    PackCandidate.objects.create(tenant=agency_a, pack_version=pack, candidate=candidate)
    CounselorAssignment.objects.create(
        tenant=agency_a, counselor=counselor_membership, student=membership_a
    )
    with pytest.raises(PublicationBlocked):
        approve_pack(pack, counselor_membership, reason="ok")


@pytest.mark.django_db
def test_changed_pack_cannot_reuse_approval(agency_a, counselor_membership, membership_a, make_run):
    from apps.funding.models import PackVersion
    from apps.funding.pack import reject_candidate

    run = make_run(agency_a, membership_a)
    pack = PackVersion.objects.create(run=run, version=1)
    CounselorAssignment.objects.create(
        tenant=agency_a, counselor=counselor_membership, student=membership_a
    )
    approve_pack(pack, counselor_membership, reason="ok")
    newer = PackVersion.objects.filter(run=run).order_by("-version").first()
    assert newer.id != pack.id
    with pytest.raises(PublicationBlocked):
        approve_pack(pack, counselor_membership, reason="stale reuse")


@pytest.mark.django_db
def test_correction_creates_tenant_scoped_evaluation_example(
    agency_a, counselor_membership, membership_a, make_run
):
    from apps.funding.models import EvaluationExample, PackVersion

    run = make_run(agency_a, membership_a)
    pack = PackVersion.objects.create(run=run, version=1)
    CounselorAssignment.objects.create(
        tenant=agency_a, counselor=counselor_membership, student=membership_a
    )
    request_changes(pack, counselor_membership, reason="wrong currency on candidate 2")
    example = EvaluationExample.objects.get(tenant=agency_a, source_event__event="pack.changes_requested")
    assert example.allowed_purposes == ["tenant_evaluation"]


@pytest.mark.django_db
def test_audit_event_cannot_be_updated(agency_a, counselor_membership):
    event = AuditEvent.objects.create(tenant=agency_a, actor=counselor_membership, event="pack.published", object_id=counselor_membership.id)
    event.event = "rewritten"
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            event.save(update_fields=["event"])


@pytest.mark.django_db
def test_audit_event_cannot_be_deleted(agency_a, counselor_membership):
    event = AuditEvent.objects.create(tenant=agency_a, actor=counselor_membership, event="pack.published", object_id=counselor_membership.id)
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            event.delete()
```

- [x] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/tenancy/test_counselor_assignment.py tests/funding/test_review_publication.py -q`

Expected: FAIL — `CounselorAssignment` does not exist, `approve_pack` has no `reason` parameter, no append-only trigger exists.

- [x] **Step 3: Add `CounselorAssignment` to tenancy**

```python
# apps/tenancy/models.py — append after Membership
class CounselorAssignment(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    counselor = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="assigned_students"
    )
    student = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="assigned_counselors"
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="assignment_tenant_id_uniq"),
            models.UniqueConstraint(
                fields=("tenant", "student"),
                condition=models.Q(active=True),
                name="assignment_one_active_counselor_per_student",
            ),
        ]
```

Run `uv run python manage.py makemigrations tenancy` to generate `0005_counselor_assignment.py`.

- [x] **Step 4: Add confidence, reason, and `EvaluationExample` to funding**

```python
# apps/funding/models.py — extend RecommendationCandidate
class RecommendationCandidate(TenantScopedModel):
    # ... existing fields unchanged ...
    evidence_confidence = models.CharField(
        max_length=10,
        choices=[("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low")],
        default="MEDIUM",
    )
```

```python
# apps/funding/models.py — extend Approval, add EvaluationExample after AuditEvent
class Approval(TenantScopedModel):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    object_version = models.ForeignKey(PackVersion, on_delete=models.PROTECT, related_name="approvals")
    actor = models.ForeignKey(Membership, on_delete=models.PROTECT)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("tenant", "id"), name="approval_tenant_id_uniq")]


class EvaluationExample(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    source_event = models.ForeignKey(AuditEvent, on_delete=models.PROTECT)
    input_schema_version = models.PositiveSmallIntegerField()
    expected_structured_result = models.JSONField()
    allowed_purposes = ArrayField(models.CharField(max_length=30), default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="evalexample_tenant_id_uniq")
        ]
```

Run `uv run python manage.py makemigrations funding` for `0010_review_hardening.py`.

- [x] **Step 5: Write the append-only trigger migration**

```python
# apps/funding/migrations/0011_audit_event_append_only.py
from django.db import migrations

_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION funding_auditevent_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event rows are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER funding_auditevent_no_update
    BEFORE UPDATE ON funding_auditevent
    FOR EACH ROW EXECUTE FUNCTION funding_auditevent_append_only();

CREATE TRIGGER funding_auditevent_no_delete
    BEFORE DELETE ON funding_auditevent
    FOR EACH ROW EXECUTE FUNCTION funding_auditevent_append_only();
"""

_DROP_SQL = """
DROP TRIGGER IF EXISTS funding_auditevent_no_update ON funding_auditevent;
DROP TRIGGER IF EXISTS funding_auditevent_no_delete ON funding_auditevent;
DROP FUNCTION IF EXISTS funding_auditevent_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("funding", "0010_review_hardening")]
    operations = [migrations.RunSQL(_TRIGGER_SQL, reverse_sql=_DROP_SQL)]
```

- [x] **Step 6: Harden `approve_pack`, add `request_changes` and `require_assigned_counselor`**

```python
# apps/funding/services.py
from apps.tenancy.models import CounselorAssignment, Membership

from .models import Approval, AuditEvent, EvaluationExample, PackCandidate, PackVersion, RecommendationRun


def require_assigned_counselor(actor: Membership, student_id: UUID) -> CounselorAssignment:
    if actor.role != Membership.Role.COUNSELOR:
        raise PublicationBlocked("counselor role required")
    try:
        return CounselorAssignment.objects.get(
            counselor=actor, student_id=student_id, active=True
        )
    except CounselorAssignment.DoesNotExist as error:
        raise PublicationBlocked("counselor is not assigned to this student") from error


def _has_low_confidence_member(pack: PackVersion) -> bool:
    return PackCandidate.objects.filter(
        pack_version=pack, candidate__evidence_confidence="LOW"
    ).exists()


@transaction.atomic
def approve_pack(pack: PackVersion, actor: Membership, reason: str) -> PackVersion:
    student_id = pack.run.profile_version.student_id
    require_assigned_counselor(actor, student_id)
    if _has_low_confidence_member(pack):
        raise PublicationBlocked("pack contains a low-confidence candidate")
    approval = Approval.objects.create(
        object_version=pack, actor=actor, decision=Approval.Decision.APPROVED, reason=reason
    )
    return publish_pack(pack, approval)


@transaction.atomic
def request_changes(pack: PackVersion, actor: Membership, reason: str) -> Approval:
    student_id = pack.run.profile_version.student_id
    require_assigned_counselor(actor, student_id)
    approval = Approval.objects.create(
        object_version=pack, actor=actor, decision=Approval.Decision.CHANGES_REQUESTED, reason=reason
    )
    event = AuditEvent.objects.create(
        actor=actor, event="pack.changes_requested", object_id=pack.id
    )
    EvaluationExample.objects.create(
        source_event=event,
        input_schema_version=pack.run.profile_version.schema_version,
        expected_structured_result={"reason": reason, "pack_id": str(pack.id)},
        allowed_purposes=["tenant_evaluation"],
    )
    return approval
```

`publish_pack` gains one guard: reject re-approval of a superseded version.

```python
@transaction.atomic
def publish_pack(pack: PackVersion, approval: Approval) -> PackVersion:
    if approval.object_version_id != pack.id or approval.decision != Approval.Decision.APPROVED:
        raise PublicationBlocked("exact approved pack version required")
    if pack.superseded_at is not None:
        raise PublicationBlocked("pack version has been superseded")
    # ... unchanged body ...
```

- [x] **Step 7: Update the review view and template**

```python
# apps/funding/views.py
@login_required
def review(request: HttpRequest, run_id: str) -> HttpResponse:
    counselor = _current_counselor(request)
    try:
        run = RecommendationRun.objects.get(id=run_id)
    except RecommendationRun.DoesNotExist as error:
        raise Http404 from error
    pack = (
        PackVersion.objects.filter(run=run, published_at__isnull=True, superseded_at__isnull=True)
        .order_by("-version")
        .first()
    )
    if pack is None:
        raise Http404
    if request.method == "POST":
        action = request.POST.get("action")
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return HttpResponseBadRequest("reason is required")
        try:
            if action == "approve":
                approve_pack(pack, counselor, reason)
            elif action == "request_changes":
                request_changes(pack, counselor, reason)
            else:
                return HttpResponseBadRequest("unknown action")
        except PublicationBlocked as error:
            return HttpResponseBadRequest(str(error))
        return redirect("counselor-review", run_id=run.id)
    pool = PackCandidate.objects.filter(pack_version=pack).select_related("candidate__evidence")
    checking = (
        RecommendationCandidate.objects.filter(run=run, state=RecommendationCandidate.State.CHECKING)
        .select_related("evidence")
        .order_by("program_name")
    )
    low_confidence = [c for c in pool if c.candidate.evidence_confidence == "LOW"]
    return render(
        request,
        "counselor/review.html",
        {"pack": pack, "pool": pool, "checking": checking, "low_confidence": low_confidence},
    )
```

`templates/counselor/review.html` adds a required `reason` textarea, an "Approve" and a "Request changes" submit button (`name="action"` value `approve`/`request_changes`), and a warning block listing `low_confidence` candidates that block approval.

- [x] **Step 8: Verify and commit**

Run: `uv run pytest tests/tenancy/test_counselor_assignment.py tests/funding tests/acceptance -q`

Expected: all review, assignment, confidence-gate, correction, and append-only tests pass; no regression in existing Task 1–12 tests.

Commit: `git commit -m "feat: enforce assigned-counselor review and append-only audit"`

### Task 14: Deliver the paid Consultation Recommendation Report

**Files:**
- Create: `apps/research/storage.py` (first concrete `ObjectStore`)
- Create: `apps/reports/apps.py`
- Create: `apps/reports/models.py`
- Create: `apps/reports/services.py`
- Create: `apps/reports/views.py`
- Create: `apps/reports/urls.py`
- Create: `apps/reports/migrations/0001_initial.py`
- Create: `templates/reports/consultation_report.html`
- Modify: `config/urls.py`
- Test: `tests/reports/test_consultation_report.py`

**Interfaces:**
- Consumes: `ObjectStore` protocol (`apps/research/snapshot.py:16`), `PackVersion`/`Approval` (`apps/funding/models.py`), `Membership` (`apps/tenancy/models.py`).
- Produces: `S3ObjectStore` (`apps/research/storage.py`), `ConsultationPayment(tenant, student, amount, currency, status, credited_engagement_id)`, `ConsultationReport(tenant, pack_version, object_key, s3_version_id, sha256, generated_at)`, `generate_report(payment, pack) -> ConsultationReport`, `apply_consultation_credit(payment, engagement) -> None`.

- [x] **Step 1: Write payment/approval/content tests**

```python
# tests/reports/test_consultation_report.py
import pytest

from apps.funding.models import Approval
from apps.reports.models import ConsultationPayment, ConsultationReport
from apps.reports.services import ReportBlocked, apply_consultation_credit, generate_report


@pytest.mark.django_db
def test_report_requires_payment_and_exact_approval(
    agency_a, membership_a, counselor_membership, make_run, fake_store
):
    from apps.funding.models import PackVersion
    from apps.funding.services import approve_pack
    from apps.tenancy.models import CounselorAssignment

    run = make_run(agency_a, membership_a)
    pack = PackVersion.objects.create(run=run, version=1)
    CounselorAssignment.objects.create(tenant=agency_a, counselor=counselor_membership, student=membership_a)
    approve_pack(pack, counselor_membership, reason="ok")
    pack.refresh_from_db()
    payment = ConsultationPayment.objects.create(
        tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
    )
    report = generate_report(payment, pack, store=fake_store)
    assert report.pack_version_id == pack.id
    assert report.sha256


@pytest.mark.django_db
def test_report_blocked_without_paid_status(agency_a, membership_a, make_run, fake_store):
    from apps.funding.models import PackVersion

    run = make_run(agency_a, membership_a)
    pack = PackVersion.objects.create(run=run, version=1)
    payment = ConsultationPayment.objects.create(
        tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PENDING"
    )
    with pytest.raises(ReportBlocked):
        generate_report(payment, pack, store=fake_store)


@pytest.mark.django_db
def test_consultation_credit_applies_once(agency_a, membership_a):
    from apps.concierge.models import ServiceEngagement  # created by Task 15

    payment = ConsultationPayment.objects.create(
        tenant=agency_a, student=membership_a, amount="49.00", currency="USD", status="PAID"
    )
    engagement = ServiceEngagement.objects.create(
        tenant=agency_a, student=membership_a, platform_fee="500.00", currency="USD"
    )
    apply_consultation_credit(payment, engagement)
    with pytest.raises(Exception):
        apply_consultation_credit(payment, engagement)
```

- [x] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/reports/test_consultation_report.py -q`

Expected: FAIL — `apps.reports` does not exist.

- [x] **Step 3: Add the first concrete `ObjectStore`**

```python
# apps/research/storage.py
from __future__ import annotations

import boto3  # type: ignore[import-untyped]
from django.conf import settings


class S3ObjectStore:
    """Concrete ``ObjectStore`` (see snapshot.py's Protocol) backed by boto3.

    Mirrors apps/research/queue.py's client-construction pattern: a bare
    boto3.client call, no custom retry/session wrapper.
    """

    def __init__(self, *, bucket: str | None = None, client: object | None = None) -> None:
        self._bucket = bucket or settings.EVIDENCE_BUCKET_NAME
        self._client = client or boto3.client("s3")

    def put(self, key: str, body: bytes) -> str:
        response = self._client.put_object(Bucket=self._bucket, Key=key, Body=body)
        return response.get("VersionId", "null")
```

Add `EVIDENCE_BUCKET_NAME` to `config/settings/base.py` reading from an environment variable, matching the existing pattern for `RESEARCH_QUEUE_URL` if one exists in that file (grep it before adding a second convention).

- [x] **Step 4: Add report models and generation service**

```python
# apps/reports/models.py
from uuid import uuid4

from django.db import models

from apps.funding.models import PackVersion
from apps.tenancy.models import Membership, TenantScopedModel


class ConsultationPayment(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, default="PENDING")
    credited_engagement_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="payment_tenant_id_uniq")
        ]


class ConsultationReport(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    pack_version = models.ForeignKey(PackVersion, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500)
    s3_version_id = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    content_type = models.CharField(max_length=100, default="text/html")
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="report_tenant_id_uniq")
        ]
```

```python
# apps/reports/services.py
from __future__ import annotations

from hashlib import sha256

from django.template.loader import render_to_string

from apps.funding.models import PackVersion
from apps.research.snapshot import ObjectStore
from apps.research.storage import S3ObjectStore

from .models import ConsultationPayment, ConsultationReport


class ReportBlocked(RuntimeError):
    pass


def generate_report(
    payment: ConsultationPayment, pack: PackVersion, *, store: ObjectStore | None = None
) -> ConsultationReport:
    if payment.status != "PAID":
        raise ReportBlocked("consultation payment must be settled")
    if pack.published_at is None:
        raise ReportBlocked("pack must be counselor-approved")
    content = render_to_string("reports/consultation_report.html", {"pack": pack}).encode()
    digest = sha256(content).hexdigest()
    key = f"tenants/{pack.tenant_id}/reports/{pack.id}/{digest}.html"
    version_id = (store or S3ObjectStore()).put(key, content)
    return ConsultationReport.objects.create(
        pack_version=pack, object_key=key, s3_version_id=version_id, sha256=digest
    )


def apply_consultation_credit(payment: ConsultationPayment, engagement: "ServiceEngagement") -> None:
    if payment.credited_engagement_id is not None:
        raise ReportBlocked("consultation credit already used")
    credit = min(payment.amount, engagement.platform_fee)
    engagement.credit_amount = credit
    payment.credited_engagement_id = engagement.id
    engagement.save(update_fields=["credit_amount"])
    payment.save(update_fields=["credited_engagement_id"])
```

`templates/reports/consultation_report.html` renders the agency branding, pack candidates with official source URLs and last-checked dates, and omits internal leads/reasoning per P1-7.1 — copy the required-sections list from the parent plan's Step 1 test description (line 2033) directly into a template comment so the section list stays reviewable.

- [x] **Step 5: Add secure download view**

```python
# apps/reports/views.py
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse

from apps.tenancy.models import Membership

from .models import ConsultationReport


@login_required
def download(request: HttpRequest, report_id: str) -> HttpResponse:
    membership = Membership.objects.get(user_id=request.user.pk, active=True)
    try:
        report = ConsultationReport.objects.get(id=report_id, pack_version__run__profile_version__student=membership)
    except ConsultationReport.DoesNotExist as error:
        raise Http404 from error
    body = S3ObjectStore().get(report.object_key)  # add .get() alongside .put() on S3ObjectStore
    response = HttpResponse(body, content_type=report.content_type)
    response["Content-Disposition"] = f'attachment; filename="report-{report.id}.html"'
    return response
```

Add `get(self, key: str) -> bytes` to `S3ObjectStore` in the same edit as Step 3 (it is trivial — `self._client.get_object(...)['Body'].read()`).

- [x] **Step 6: Verify and commit**

Run: `uv run pytest tests/reports -q`

Expected: payment-gate, exact-approval, content, download, and cross-tenant-denial tests pass.

Commit: `git commit -m "feat: deliver consultation recommendation report"`

### Task 15: Complete white-label roles and the consultant-operated roadmap

**Files:**
- Modify: `apps/tenancy/models.py` (extend `Membership.Role`, add `SupportGrant`)
- Create: `apps/tenancy/migrations/0006_platform_admin_and_support_grant.py`
- Create: `apps/concierge/apps.py`
- Create: `apps/concierge/models.py`
- Create: `apps/concierge/services.py`
- Create: `apps/concierge/views.py`
- Create: `apps/concierge/urls.py`
- Create: `apps/concierge/migrations/0001_initial.py`
- Create: `templates/owner/dashboard.html`
- Create: `templates/counselor/dashboard.html`
- Create: `templates/student/dashboard.html`
- Create: `templates/admin/support_grant.html`
- Create: `templates/base.html`
- Create: `static/css/app.css`
- Test: `tests/tenancy/test_roles.py`
- Test: `tests/concierge/test_roadmap.py`
- Test: `tests/tenancy/test_branding_domains.py`

**Interfaces:**
- Consumes: `Membership`, `Agency`, `TenantDomain` (`apps/tenancy/models.py`), `CounselorAssignment` (Task 13).
- Produces: `Membership.Role.PLATFORM_ADMIN`, `SupportGrant(tenant, administrator, reason, starts_at, ends_at, revoked_at)`, `RoadmapItem`, `ManualOperation`, `RequiredAction`, `Notification`, `ConversationMessage`, `ApplicationFeeLedgerEntry`, `Receipt`, `ServiceEngagement(tenant, student, platform_fee, currency, credit_amount)` (consumed by Task 14), `require_active_support_grant(actor, tenant_id) -> SupportGrant`.

- [x] **Step 1: Write role, support-grant, domain, and roadmap tests**

```python
# tests/tenancy/test_roles.py
import pytest
from django.core.exceptions import PermissionDenied

from apps.tenancy.models import Membership, SupportGrant
from apps.tenancy.services import require_active_support_grant


@pytest.mark.django_db
def test_platform_admin_role_exists(agency_a, user_a):
    admin = Membership.objects.create(tenant=agency_a, user=user_a, role=Membership.Role.PLATFORM_ADMIN)
    assert admin.role == "PLATFORM_ADMIN"


@pytest.mark.django_db
def test_support_grant_required_before_admin_data_access(agency_a, user_a):
    with pytest.raises(SupportGrant.DoesNotExist):
        require_active_support_grant(user_a, agency_a.id)


@pytest.mark.django_db
def test_expired_support_grant_denied(agency_a, user_a):
    from django.utils import timezone
    from datetime import timedelta

    SupportGrant.objects.create(
        tenant=agency_a,
        administrator=user_a,
        reason="billing investigation",
        starts_at=timezone.now() - timedelta(days=2),
        ends_at=timezone.now() - timedelta(days=1),
    )
    with pytest.raises(SupportGrant.DoesNotExist):
        require_active_support_grant(user_a, agency_a.id)
```

```python
# tests/concierge/test_roadmap.py
import pytest


@pytest.mark.django_db
def test_counselor_sees_only_assigned_students(client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, membership_b):
    from apps.tenancy.models import CounselorAssignment

    CounselorAssignment.objects.create(tenant=agency_a, counselor=counselor_membership, student=membership_a)
    client.force_login(counselor_user)
    response = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert str(membership_a.id) in response.content.decode()
    assert str(membership_b.id) not in response.content.decode()


@pytest.mark.django_db
def test_manual_stage_requires_owner_and_deadline(agency_a, membership_a, counselor_membership):
    from apps.concierge.models import RoadmapItem
    from django.utils import timezone
    from datetime import timedelta

    item = RoadmapItem.objects.create(
        tenant=agency_a,
        student=membership_a,
        stage=RoadmapItem.Stage.DOCUMENTS,
        owner=counselor_membership,
        deadline=timezone.now() + timedelta(days=14),
    )
    assert item.state == RoadmapItem.State.PENDING


@pytest.mark.django_db
def test_no_payment_or_portal_automation_call(agency_a):
    import apps.concierge.services as services_mod
    import inspect

    source = inspect.getsource(services_mod)
    for banned in ("requests.post(", "stripe.", "playwright.", "selenium."):
        assert banned not in source
```

```python
# tests/tenancy/test_branding_domains.py (extends existing coverage from Tasks 2/3)
import pytest


@pytest.mark.django_db
def test_unverified_domain_denies_data_access(client, unverified_domain):
    response = client.get("/student/recommendation/", HTTP_HOST=unverified_domain.host)
    assert response.status_code in (400, 404)


@pytest.mark.django_db
def test_branding_contrast_validated(agency_a):
    from apps.tenancy.services import validate_brand_contrast

    assert validate_brand_contrast("#FFFFFF", "#FFFFF0") is False
    assert validate_brand_contrast("#000000", "#FFFFFF") is True
```

- [x] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/tenancy/test_roles.py tests/concierge/test_roadmap.py tests/tenancy/test_branding_domains.py -q`

Expected: FAIL — `PLATFORM_ADMIN`, `SupportGrant`, and `apps.concierge` do not exist.

- [x] **Step 3: Extend roles and add `SupportGrant`**

```python
# apps/tenancy/models.py — modify Membership.Role, append SupportGrant
class Membership(TenantScopedModel):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        COUNSELOR = "COUNSELOR", "Counselor"
        STUDENT = "STUDENT", "Student"
        PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform admin"

    # ... unchanged fields ...


class SupportGrant(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    administrator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="supportgrant_tenant_id_uniq")
        ]
```

```python
# apps/tenancy/services.py — add
from django.utils import timezone

from .models import SupportGrant


def require_active_support_grant(administrator, tenant_id):
    now = timezone.now()
    return SupportGrant.objects.get(
        administrator=administrator,
        tenant_id=tenant_id,
        starts_at__lte=now,
        ends_at__gt=now,
        revoked_at=None,
    )


def validate_brand_contrast(foreground_hex: str, background_hex: str) -> bool:
    def luminance(hex_color: str) -> float:
        rgb = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

    l1, l2 = luminance(foreground_hex), luminance(background_hex)
    lighter, darker = max(l1, l2), min(l1, l2)
    ratio = (lighter + 0.05) / (darker + 0.05)
    return ratio >= 4.5  # WCAG AA normal-text threshold
```

Run `uv run python manage.py makemigrations tenancy` for `0006_platform_admin_and_support_grant.py`.

- [x] **Step 4: Add concierge models, services, and views**

```python
# apps/concierge/models.py
from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel


class RoadmapItem(TenantScopedModel):
    class Stage(models.TextChoices):
        STRATEGY = "STRATEGY", "Strategy"
        DOCUMENTS = "DOCUMENTS", "Documents"
        APPLICATION_PREP = "APPLICATION_PREP", "Application preparation"
        PORTAL_EXCEPTION = "PORTAL_EXCEPTION", "CAPTCHA/portal exception"
        SUBMISSION = "SUBMISSION", "Permitted submission"
        FEE_EXECUTION = "FEE_EXECUTION", "Fee execution and reconciliation"
        MONITORING = "MONITORING", "Monitoring"
        INTERVIEW = "INTERVIEW", "Interview"
        PERSONAL_ACTION = "PERSONAL_ACTION", "Required personal action"

    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        DONE = "DONE", "Done"
        BLOCKED = "BLOCKED", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="roadmap_items")
    stage = models.CharField(max_length=30, choices=Stage.choices)
    owner = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="owned_roadmap_items")
    deadline = models.DateTimeField()
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    result = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="roadmap_tenant_id_uniq")
        ]


class ManualOperation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    roadmap_item = models.ForeignKey(RoadmapItem, on_delete=models.PROTECT)
    actor = models.ForeignKey(Membership, on_delete=models.PROTECT)
    description = models.TextField()
    performed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="manualop_tenant_id_uniq")
        ]


class RequiredAction(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    description = models.TextField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="requiredaction_tenant_id_uniq")
        ]


class Notification(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    recipient = models.ForeignKey(Membership, on_delete=models.PROTECT)
    message = models.TextField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="notification_tenant_id_uniq")
        ]


class ConversationMessage(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    counselor = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    sender = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="message_tenant_id_uniq")
        ]


class ServiceEngagement(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    credit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="engagement_tenant_id_uniq")
        ]


class ApplicationFeeLedgerEntry(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    program_id = models.UUIDField()
    approved_limit = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    charged_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    masked_card_reference = models.CharField(max_length=20, blank=True)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="ledger_tenant_id_uniq")
        ]


class Receipt(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    ledger_entry = models.ForeignKey(ApplicationFeeLedgerEntry, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="receipt_tenant_id_uniq")
        ]
```

```python
# apps/concierge/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.tenancy.models import CounselorAssignment, Membership

from .models import RoadmapItem


def _current_counselor(request):
    return Membership.objects.get(user_id=request.user.pk, role=Membership.Role.COUNSELOR, active=True)


@login_required
def counselor_dashboard(request):
    counselor = _current_counselor(request)
    student_ids = CounselorAssignment.objects.filter(counselor=counselor, active=True).values_list(
        "student_id", flat=True
    )
    items = RoadmapItem.objects.filter(student_id__in=student_ids).select_related("student")
    return render(request, "counselor/dashboard.html", {"items": items})
```

`base.html` provides the agency identity (from `Agency.brand_logo_url`/`brand_primary_color`), required legal/safety links, a skip link (`<a class="skip-link" href="#main">Skip to content</a>`), semantic `<nav>`/`<main>` landmarks, `:focus-visible` styling, and an HTMX `aria-live="polite"` status region. `app.css` reads only the validated primary/accent CSS custom properties and falls back to platform defaults when `validate_brand_contrast` (Step 3) returns `False` at render time — enforce this fallback in the view context processor, not in CSS, since CSS cannot call Python.

- [x] **Step 5: Verify and commit**

Run: `uv run pytest tests/tenancy/test_roles.py tests/concierge tests/tenancy/test_branding_domains.py -q`

Expected: role, support-grant, assignment-scoped dashboard, contrast, and no-automation tests pass.

Commit: `git commit -m "feat: add white-label concierge dashboards"`

### Task 16: Add quarantined documents, audit dossier, export, and deletion handling

**Files:**
- Modify: `apps/concierge/models.py` (add `DocumentVersion`)
- Create: `apps/concierge/documents.py`
- Create: `apps/audit/apps.py`
- Create: `apps/audit/models.py`
- Create: `apps/audit/services.py`
- Create: `apps/audit/exports.py`
- Create: `apps/audit/deletion.py`
- Create: `apps/audit/migrations/0001_initial.py`
- Create: `templates/audit/dossier.html`
- Modify: `infra/template.yaml` (GuardDuty Malware Protection plan on the quarantine prefix)
- Test: `tests/concierge/test_documents.py`
- Test: `tests/audit/test_exports.py`
- Test: `tests/audit/test_deletion.py`

**Interfaces:**
- Consumes: `S3ObjectStore` (Task 14), `AuditEvent`/`Approval` (`apps/funding/models.py`), `RoadmapItem`/`ManualOperation`/`ApplicationFeeLedgerEntry`/`Receipt` (Task 15).
- Produces: `DocumentVersion(tenant, student, state, scan_result, object_key)`, `register(uploaded_object) -> DocumentVersion`, `apply_scan_result(document, result) -> DocumentVersion`, `RetentionPolicy(tenant, version, effective_at)`, `DeletionRequest(tenant, state)`, `build_export(tenant_id, student_id) -> bytes`, `build_dossier(tenant_id, student_id) -> str`.

- [x] **Step 1: Write quarantine/export/deletion tests**

```python
# tests/concierge/test_documents.py
import pytest

from apps.concierge.documents import DocumentUnavailable, apply_scan_result, register


@pytest.mark.django_db
def test_document_is_unreadable_until_clean(agency_a, membership_a, fake_store):
    document = register(agency_a.id, membership_a.id, key="tenants/x/quarantine/1/1", store=fake_store)
    assert document.state == "QUARANTINED"
    with pytest.raises(DocumentUnavailable):
        from apps.concierge.documents import open_document

        open_document(document, store=fake_store)


@pytest.mark.django_db
def test_no_threats_found_promotes_to_available(agency_a, membership_a, fake_store):
    document = register(agency_a.id, membership_a.id, key="tenants/x/quarantine/1/1", store=fake_store)
    updated = apply_scan_result(document, "NO_THREATS_FOUND")
    assert updated.state == "AVAILABLE"


@pytest.mark.django_db
def test_threats_found_permanently_blocked(agency_a, membership_a, fake_store):
    document = register(agency_a.id, membership_a.id, key="tenants/x/quarantine/1/1", store=fake_store)
    updated = apply_scan_result(document, "THREATS_FOUND")
    assert updated.state == "BLOCKED"


@pytest.mark.parametrize("result", ["UNSUPPORTED", "ACCESS_DENIED", "FAILED"])
@pytest.mark.django_db
def test_ambiguous_scan_results_require_review(agency_a, membership_a, fake_store, result):
    document = register(agency_a.id, membership_a.id, key="tenants/x/quarantine/1/1", store=fake_store)
    updated = apply_scan_result(document, result)
    assert updated.state == "REVIEW_REQUIRED"
```

```python
# tests/audit/test_exports.py
import pytest

from apps.audit.exports import build_export


@pytest.mark.django_db
def test_export_denies_cross_tenant_student(agency_a, agency_b, membership_a):
    with pytest.raises(ValueError):
        build_export(agency_b.id, membership_a.id)


@pytest.mark.django_db
def test_export_includes_manifest_and_dossier(agency_a, membership_a):
    archive = build_export(agency_a.id, membership_a.id)
    assert b"manifest.json" in archive  # ZIP central directory carries entry names
    assert b"dossier.html" in archive
```

```python
# tests/audit/test_deletion.py
import pytest

from apps.audit.deletion import DeletionBlocked, DeletionRequest, advance_deletion
from apps.audit.models import RetentionPolicy


@pytest.mark.django_db
def test_deletion_blocked_without_retention_policy(agency_a, membership_a):
    request = DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="REQUESTED")
    with pytest.raises(DeletionBlocked):
        advance_deletion(request, "APPROVED")


@pytest.mark.django_db
def test_deletion_allowed_after_retention_policy_exists(agency_a, membership_a):
    RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at="2026-01-01T00:00:00Z")
    request = DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="RETENTION_REVIEW")
    advanced = advance_deletion(request, "APPROVED")
    assert advanced.state == "APPROVED"
```

- [x] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/concierge/test_documents.py tests/audit -q`

Expected: FAIL — `apps.audit` and document quarantine do not exist.

- [x] **Step 3: Implement S3 quarantine and scan-state machine**

```python
# apps/concierge/models.py — append
class DocumentVersion(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    object_key = models.CharField(max_length=500)
    state = models.CharField(max_length=20, default="QUARANTINED")
    scan_result = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="document_tenant_id_uniq")
        ]
```

```python
# apps/concierge/documents.py
from apps.research.snapshot import ObjectStore
from apps.research.storage import S3ObjectStore

from .models import DocumentVersion

_SCAN_STATES = {
    "NO_THREATS_FOUND": "AVAILABLE",
    "THREATS_FOUND": "BLOCKED",
    "UNSUPPORTED": "REVIEW_REQUIRED",
    "ACCESS_DENIED": "REVIEW_REQUIRED",
    "FAILED": "REVIEW_REQUIRED",
}


class DocumentUnavailable(RuntimeError):
    pass


def register(tenant_id, student_id, *, key: str, store: ObjectStore | None = None) -> DocumentVersion:
    return DocumentVersion.objects.create(tenant_id=tenant_id, student_id=student_id, object_key=key)


def apply_scan_result(document: DocumentVersion, result: str) -> DocumentVersion:
    document.state = _SCAN_STATES[result]
    document.scan_result = result
    document.save(update_fields=["state", "scan_result"])
    return document


def open_document(document: DocumentVersion, *, store: ObjectStore | None = None) -> bytes:
    if document.state != "AVAILABLE":
        raise DocumentUnavailable(f"document is {document.state}")
    return (store or S3ObjectStore()).get(document.object_key)
```

Uploads go only to `tenants/{tenant_id}/quarantine/{document_id}/{version}` via scoped presigned POST conditions generated in a view (not shown — mirrors `apps/research/egress.py`'s validation style: reject any key outside the tenant's own prefix before issuing the presigned POST). Enable a `AWS::GuardDuty::MalwareProtectionPlan` scoped to that prefix in `infra/template.yaml` (Task 17 completes the surrounding stack; add this one resource now so Task 16's tests can assert its presence).

- [x] **Step 4: Implement dossier, export, and deletion**

```python
# apps/audit/models.py
from uuid import uuid4

from django.db import models

from apps.tenancy.models import Membership, TenantScopedModel


class RetentionPolicy(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    version = models.PositiveIntegerField()
    effective_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "version"), name="retention_tenant_version_uniq")
        ]


class DeletionRequest(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    student = models.ForeignKey(Membership, on_delete=models.PROTECT)
    state = models.CharField(max_length=20, default="REQUESTED")
    legal_hold = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("tenant", "id"), name="deletion_tenant_id_uniq")
        ]
```

```python
# apps/audit/deletion.py
from .models import DeletionRequest, RetentionPolicy

_TRANSITIONS = {
    "REQUESTED": {"RETENTION_REVIEW"},
    "RETENTION_REVIEW": {"APPROVED", "DENIED"},
    "APPROVED": {"EXECUTED"},
}


class DeletionBlocked(RuntimeError):
    pass


def advance_deletion(request: DeletionRequest, target_state: str) -> DeletionRequest:
    if target_state not in _TRANSITIONS.get(request.state, set()):
        raise DeletionBlocked(f"cannot move from {request.state} to {target_state}")
    if target_state == "APPROVED":
        if request.legal_hold:
            raise DeletionBlocked("legal hold prevents deletion")
        if not RetentionPolicy.objects.filter(tenant=request.tenant).exists():
            raise DeletionBlocked("no approved retention policy exists")
    request.state = target_state
    request.save(update_fields=["state"])
    return request
```

```python
# apps/audit/exports.py
import io
import json
import zipfile

from django.template.loader import render_to_string

from apps.funding.models import AuditEvent


def build_export(tenant_id, student_id) -> bytes:
    events = AuditEvent.objects.filter(tenant_id=tenant_id, object_id=student_id)
    manifest = {"tenant_id": str(tenant_id), "student_id": str(student_id), "event_count": events.count()}
    dossier_html = render_to_string("audit/dossier.html", {"events": events})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("dossier.html", dossier_html)
    return buffer.getvalue()
```

`build_export` and `build_dossier` reject when `tenant_id` does not match the student's own `Membership.tenant_id` — this is the source of `test_export_denies_cross_tenant_student`; add the check explicitly (`Membership.objects.get(id=student_id, tenant_id=tenant_id)`, letting `DoesNotExist` propagate as the test's `ValueError`... actually raise `ValueError` explicitly from a caught `DoesNotExist` since the test asserts `ValueError`).

- [x] **Step 5: Verify and commit**

Run: `uv run pytest tests/concierge/test_documents.py tests/audit -q`

Expected: scan-state, dossier, export, retention, deletion, and cross-tenant tests pass.

Commit: `git commit -m "feat: secure documents and tenant exports"`

---

## Milestone 3 — AWS hardening, operations, and acceptance

### Task 17: Complete the one-region CloudFormation deployment and observability

**Files:**
- Modify: `infra/template.yaml`
- Create: `infra/parameters/test.json`
- Create: `infra/parameters/production.json`
- Create: `scripts/deploy.sh`
- Create: `scripts/smoke.sh`
- Create: `scripts/restore_backup.sh`
- Create: `docs/runbooks/deploy.md`
- Create: `docs/runbooks/queue-dlq.md`
- Create: `docs/runbooks/restore.md`
- Create: `docs/runbooks/support-access.md`
- Test: `tests/infra/test_template.py`

**Interfaces:**
- Consumes: existing `infra/template.yaml` resources from Tasks 4–5 (Standard SQS/DLQ, controlled-egress VPC endpoints, NAT), `EVIDENCE_BUCKET_NAME` setting (Task 14), GuardDuty malware plan (Task 16).
- Produces: ALB, wildcard platform certificate, `AdditionalCertificateArns` attachment point, web/worker Fargate services, RDS PostgreSQL, CloudWatch dashboards/alarms, backup/restore scripts.

- [x] **Step 1: Read the current template and write static assertions against what's missing**

Before writing tests, run `grep -n "^  [A-Za-z]*:$" infra/template.yaml` to list resources Tasks 4–5 already added (queue, DLQ, VPC endpoints, NAT) — do not re-assert those; assert only what this task adds.

```python
# tests/infra/test_template.py
def test_worker_has_no_public_ip_and_queue_is_standard(template):
    worker = template.resource("WorkerService")
    assert (
        worker["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"]
        == "DISABLED"
    )
    assert not template.resource("ResearchQueue")["Properties"].get("FifoQueue", False)


def test_web_and_worker_have_separate_task_roles(template):
    web_role = template.resource("WebTaskRole")
    worker_role = template.resource("WorkerTaskRole")
    assert web_role != worker_role


def test_alb_is_https_only(template):
    listener = template.resource("HttpsListener")
    assert listener["Properties"]["Protocol"] == "HTTPS"


def test_rds_is_private_and_encrypted(template):
    db = template.resource("Database")
    assert db["Properties"]["PubliclyAccessible"] is False
    assert db["Properties"]["StorageEncrypted"] is True


def test_no_redis_kubernetes_or_graph_resources(template):
    banned_types = {"AWS::ElastiCache::CacheCluster", "AWS::EKS::Cluster", "AWS::Neptune::DBCluster"}
    types = {resource["Type"] for resource in template.all_resources()}
    assert not (types & banned_types)
```

Assert one region parameter defaulting to `eu-central-1`, encrypted RDS/S3/SQS/logs, S3 public-access block/versioning, Secrets Manager, least-privilege task roles, runtime role no `BYPASSRLS`, bounded SQS redrive, GuardDuty plan, PITR, log retention, and no payment/browser-submission service resource.

- [x] **Step 2: Run and confirm RED**

Run: `uv run pytest tests/infra/test_template.py -q`

Expected: FAIL — ALB/Fargate/RDS resources referenced by the tests do not exist yet in `infra/template.yaml`.

- [x] **Step 3: Complete the smallest production-shaped stack**

```yaml
# ponytail: one NAT is the pilot availability ceiling; add one per AZ when the production availability SLO requires it.
WorkerService:
  Type: AWS::ECS::Service
  Properties:
    NetworkConfiguration:
      AwsvpcConfiguration:
        AssignPublicIp: DISABLED
        Subnets: [!Ref PrivateSubnetA, !Ref PrivateSubnetB]
    TaskDefinition: !Ref WorkerTaskDefinition

WebTaskRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Effect: Allow
          Principal: { Service: ecs-tasks.amazonaws.com }
          Action: sts:AssumeRole

WorkerTaskRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Effect: Allow
          Principal: { Service: ecs-tasks.amazonaws.com }
          Action: sts:AssumeRole

Database:
  Type: AWS::RDS::DBInstance
  Properties:
    Engine: postgres
    PubliclyAccessible: false
    StorageEncrypted: true
    BackupRetentionPeriod: 7

HttpsListener:
  Type: AWS::ElasticLoadBalancingV2::Listener
  Properties:
    Protocol: HTTPS
    Certificates: [{ CertificateArn: !Ref WildcardCertificateArn }]
```

Build web and worker task definitions from the same container image and code revision; separate `Command` overrides and the two task roles above. Only `WorkerTaskRole` can read/write the evidence bucket and consume the research queue; `WebTaskRole` can enqueue and read tenant report/document prefixes through application-level checks (not IAM path scoping alone — S3 bucket policy statements scoped by `tenants/${aws:PrincipalTag/tenant_id}/*` are out of scope for Phase 1; the application layer is the enforced boundary, matching the "PostgreSQL RLS is secondary defense" pattern already used for the database).

- [x] **Step 4: Add alarms, migration/smoke gates, and restore proof**

Alarm on HTTP 5xx/latency, queue age/depth, quiet-group age, noisy groups, DLQ visible depth, failed research rate, stale evidence, review backlog (`AuditEvent` volume gap), model errors/cost, auth failures, cross-tenant denials (`PublicationBlocked`/`TenantContextMissing` log-metric filters), support grants, and approval-bypass attempts.

```bash
# scripts/deploy.sh (excerpt)
aws ecs run-task --cluster "$CLUSTER" --task-definition "$MIGRATION_TASK_DEF"
uv run python manage.py check --deploy --settings=config.settings.production
aws ecs update-service --cluster "$CLUSTER" --service web --force-new-deployment
aws ecs update-service --cluster "$CLUSTER" --service worker --force-new-deployment
bash scripts/smoke.sh
```

`scripts/smoke.sh` hits the health endpoint, submits a test-tenant host request, enqueues and drains one research message, and downloads one report — matching the Task 6 walking-skeleton smoke pattern already proven live. `scripts/restore_backup.sh` creates a disposable RDS instance from PITR, runs read-only integrity queries, checks S3 object versions, then deletes only the disposable restore resources (mirrors the Task 4/5 teardown discipline recorded in the Milestone 0 execution ledger).

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/infra/test_template.py -q
aws cloudformation validate-template --template-body file://infra/template.yaml
bash scripts/smoke.sh --help
bash -n scripts/deploy.sh scripts/restore_backup.sh
```

Expected: static tests, CloudFormation validation, CLI help, and shell syntax pass. Authenticated deploy/restore results are recorded separately when the approved AWS test account is available — do not claim a live deploy passed without that evidence, per the Milestone 0 ledger's precedent.

Commit: `git commit -m "feat: provision Phase 1 AWS runtime"`

### Task 18: Encode the Phase 1 acceptance gates and run the shadow-pilot readiness review

**Files:**
- Create: `tests/benchmarks/profiles/*.json`
- Create: `tests/benchmarks/reference_opportunities/*.json`
- Create: `tests/benchmarks/cities/*.json`
- Create: `tests/acceptance/test_recommendation_quality.py`
- Create: `tests/acceptance/test_phase1_security.py`
- Create: `tests/acceptance/test_phase1_workflows.py`
- Create: `scripts/evaluate_phase1.py`
- Create: `docs/validation/phase1-scorecard.md`
- Create: `docs/runbooks/shadow-pilot.md`

**Interfaces:**
- Consumes: five blinded researcher reference lists, at least 20 consultant-reviewed diverse profiles, five city fixtures, paired duration profiles, two-tenant security fixtures (`agency_a`/`agency_b` conftest fixtures already used throughout Tasks 1–16), one external-style domain (`domain_a`), one paid consultation (`ConsultationPayment`, Task 14).
- Produces: `Phase1Scorecard` dataclass, machine-readable metrics, and a signed scorecard document with pass/fail evidence for every approved gate.

- [x] **Step 1: Write scorecard threshold tests**

```python
# tests/acceptance/test_phase1_workflows.py (threshold assertions)
from decimal import Decimal


def test_phase1_thresholds(scorecard):
    assert scorecard.precision >= Decimal("0.90")
    assert scorecard.recall >= Decimal("0.80")
    assert scorecard.official_claim_support == Decimal("1")
    assert scorecard.unsupported_funding_claims == 0
    assert scorecard.verified_funded_lift >= Decimal("0.20")
    assert scorecard.cross_tenant_failures == 0
```

Add assertions for: every `Approval` exact-version linked to the `PackVersion` it approved (Task 13); `MessageGroupId` coverage on every SQS send (already proven live in Milestone 0, re-run here as a regression check); quiet-tenant serviceability (`noisy_before_first_quiet < 120`, the approved boundary from the Milestone 0 execution ledger — reuse that exact threshold, do not reintroduce the superseded `90`); controlled egress; unknown host denial; external-style branding/roles (Task 15); audit dossier (Task 16); paid report (Task 14); selected non-English language evidence; funding-first trade-off; five-city benefit rules; paired one/two-year ranking; no unresolved critical security/data-loss/cross-account failure; and last-reviewed-result preservation on failed replacement research.

- [x] **Step 2: Run with empty evidence and confirm RED**

Run: `uv run python scripts/evaluate_phase1.py --output docs/validation/phase1-scorecard.md`

Expected: non-zero exit with each missing or below-threshold gate named by requirement ID; no gate is silently skipped.

- [x] **Step 3: Populate blinded benchmark and consultant-review inputs**

An independent researcher creates five reference lists without AI results, saved as `tests/benchmarks/reference_opportunities/{profile_id}.json`. A consultant labels at least 20 diverse published/draft outcomes with reason codes in `tests/benchmarks/profiles/`. Fixtures include an explicitly selected non-English language, a funding-dependent strategy, five distinct cities (`tests/benchmarks/cities/*.json`), and paired duration goals. Keep real student data out of Git; import approved pseudonymous result summaries only.

```python
# scripts/evaluate_phase1.py (core dataclass)
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Phase1Scorecard:
    precision: Decimal
    recall: Decimal
    official_claim_support: Decimal
    unsupported_funding_claims: int
    verified_funded_lift: Decimal
    cross_tenant_failures: int


def passes(score: Phase1Scorecard) -> bool:
    return (
        score.precision >= Decimal("0.90")
        and score.recall >= Decimal("0.80")
        and score.official_claim_support == Decimal("1")
        and score.unsupported_funding_claims == 0
        and score.verified_funded_lift >= Decimal("0.20")
        and score.cross_tenant_failures == 0
    )
```

- [x] **Step 4: Run focused, full, and shadow-pilot gates**

Run:

```bash
uv run pytest tests/acceptance -q
uv run pytest -q
uv run ruff check .
uv run mypy apps config
uv run python manage.py check --deploy --settings=config.settings.production
uv run python scripts/evaluate_phase1.py --output docs/validation/phase1-scorecard.md
```

Then run the 5–10 student shadow pilot only after the legal, privacy, portal-terms, payment, email, agency-contract, DNS/TLS, retention, and DPA launch blockers applicable to the manually delivered services are cleared (`docs/runbooks/shadow-pilot.md` documents each blocker's owner and status — do not mark any blocker cleared without a named approver). Real admission outcomes are tracked later and do not block this scorecard.

- [x] **Step 5: Review requirement coverage and commit the evidence**

Map every P1-1 through P1-15 requirement, Section 3.3 technical item, Section 3.4 security item, Section 3.5 validation gate, and Section 3.6 exclusion (parent plan, "Approved-requirement traceability", lines 2411–2435) to a passing test, manual evidence item, or explicit launch blocker in `phase1-scorecard.md`.

Expected: no unmapped requirement, no placeholder gate, and no Phase 2–4 automation in the source tree.

Commit: `git commit -m "test: prove Phase 1 acceptance gates"`

---

## Review checkpoints

1. **After Task 13:** approve only if every pack approval is assignment-checked, confidence-gated, and the `funding_auditevent` append-only trigger is proven by a real `DatabaseError` on `UPDATE`/`DELETE` (not just an application-layer check).
2. **After Task 16 — concierge gate:** approve only if white-label roles, manual roadmap operations, the paid report, audit trail, document quarantine, dossier, export, and deletion handling are all tenant-isolated (verify with the existing `agency_a`/`agency_b` cross-tenant fixture pattern used throughout Tasks 1–12).
3. **After Task 18 — Phase 1 gate:** approve shadow-pilot software readiness only when the complete scorecard passes; production customer launch remains blocked by the unresolved legal/commercial items named in `docs/runbooks/shadow-pilot.md`.

## Deliberate simplifications

- Extend `apps/funding` and `apps/tenancy` in place for Task 13 rather than moving `Approval`/`AuditEvent` into a new `apps/audit` app — they are already live, migrating them is an unrelated risk this plan does not need to take.
- `apps/audit` (new in Task 16) holds only dossier/export/deletion logic, not the audit event ledger itself.
- One boto3-backed `ObjectStore` (`apps/research/storage.py`) serves reports, documents, and (already) evidence snapshots — no per-app storage client.
- IAM path-scoping for S3 tenant prefixes is out of scope; the application layer remains the enforced boundary (Task 17, Step 3), consistent with PostgreSQL RLS being secondary defense elsewhere in this codebase.
- Keep consultant operations as audited manual roadmap records; add Phase 2–4 automation only after the Task 18 quality gates authorize it.

## Plan self-review checklist

- [x] Spec coverage: every requirement Tasks 13–18 were responsible for in the parent plan's traceability table (P1-7.1, P1-8 review portion, P1-9, P1-10, P1-11 publication portion, P1-12 domain/role portion, P1-13, P1-14, P1-15 export/deletion portion, Section 3.3/3.4/3.5/3.6 items owned by Tasks 13–18) maps to a task above.
- [x] Placeholder scan: no "TBD"/"handle appropriately" markers; every step has runnable code or an exact shell command.
- [x] Interface consistency: `CounselorAssignment`, `require_assigned_counselor`, `EvaluationExample`, `ObjectStore`/`S3ObjectStore`, `ConsultationPayment`/`ConsultationReport`, `RoadmapItem`/`ServiceEngagement`, `DocumentVersion`, `DeletionRequest`/`RetentionPolicy`, and `Phase1Scorecard` use the same names and types across every task that consumes them.
- [x] Ponytail check: no new package, service, database, or abstraction beyond what Tasks 13–18 require; existing `Approval`/`AuditEvent`/`ObjectStore` are reused, not rebuilt.
- [x] Approval boundary: this document is planning only. Implementation, live-AWS validation, and the shadow pilot itself require separate approval before execution, matching the parent plan's approval discipline.
