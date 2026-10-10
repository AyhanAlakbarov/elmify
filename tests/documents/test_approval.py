import pytest
from django.utils import timezone

from apps.documents.approval import (
    ApprovalBlocked,
    is_blocked,
    mark_ready,
    revoke_consent,
    verdicts_for,
)
from apps.documents.drafts import create_draft
from apps.documents.models import ConsentEvent, DocumentDraft, VerifiedFact
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.verification import ClaimVerdict, Verdict, fact_payload
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_identity_fact

pytestmark = pytest.mark.django_db

_EDUCATION = EducationEntry(
    degree_as_awarded="BSc",
    institution_original="Example U",
    city="Berlin",
    country="DE",
    start_date="2020-09-01",
)


def _content():
    return CVContent(
        personal_information=PersonalInformation(full_name="Jane Doe", email="jane@example.com"),
        education=(_EDUCATION,),
        experience=(),
        research=(),
        publications=(),
        awards=(),
        skills=(),
        languages=(),
        document_language="en",
    )


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    make_identity_fact(student)
    return student


def _supporting_fact(student, *, confirmed=True, **payload_overrides):
    """Build the fact as it should be, never mutate one afterwards.

    VerifiedFact is append-only; a test that edits a row in place contradicts
    the invariant it is here to protect.
    """
    payload = fact_payload(_EDUCATION, category=VerifiedFact.Category.EDUCATION)
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={**payload, **payload_overrides},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="consult-a",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
    )


def test_is_blocked_only_on_unsupported_and_conflicting():
    assert is_blocked((ClaimVerdict("education[0]", "x", Verdict.UNSUPPORTED, None),)) is True
    assert is_blocked((ClaimVerdict("education[0]", "x", Verdict.CONFLICTING, None),)) is True
    assert is_blocked((ClaimVerdict("education[0]", "x", Verdict.UNCERTAIN, None),)) is False
    assert is_blocked((ClaimVerdict("education[0]", "x", Verdict.SUPPORTED, None),)) is False


def test_unsupported_claim_blocks_even_when_the_caller_says_otherwise(
    agency_a, django_user_model
):
    """The old signature let a caller pass in verdicts. This asserts the gate
    is computed from the stored content, so there is nothing to pass."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a1")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        assert any(v.verdict == Verdict.UNSUPPORTED for v in verdicts_for(draft))
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_conflicting_claim_blocks(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a2")
        fact = _supporting_fact(student, start_date="1999-01-01")
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        assert any(v.verdict == Verdict.CONFLICTING for v in verdicts_for(draft))
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_uncertain_does_not_block_2026_08_23_amendment(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a3")
        fact = _supporting_fact(student, confirmed=False)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        assert any(v.verdict == Verdict.UNCERTAIN for v in verdicts_for(draft))
        approved = mark_ready(document=draft, accepted_by=student)
        assert approved.status == DocumentDraft.Status.APPROVED
        assert approved.approved_by_id == student.id


def test_clean_draft_auto_approves_and_records_consent(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a4")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        assert approved.status == DocumentDraft.Status.APPROVED
        consent = ConsentEvent.objects.get(document=approved)
        assert consent.mode == DocumentDraft.ApprovalMode.PER_DOCUMENT
        assert consent.granted_by_id == student.id
        assert consent.revoked_at is None


def test_per_document_mode_rejects_a_counselor_accepting_for_the_student(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a5")
        counselor_user = django_user_model.objects.create(username="a5c")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=True
        )
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=counselor)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_counselor_approves_mode_requires_a_counselor(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a6")
        counselor_user = django_user_model.objects.create(username="a6c")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=True
        )
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        DocumentDraft.objects.filter(id=draft.id).update(
            approval_mode=DocumentDraft.ApprovalMode.COUNSELOR_APPROVES
        )
        draft.refresh_from_db()
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        approved = mark_ready(document=draft, accepted_by=counselor)
        assert approved.approved_by_id == counselor.id


def test_mark_ready_is_idempotent_and_never_restamps_approval(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a7")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        first = mark_ready(document=draft, accepted_by=student)
        again = mark_ready(document=first, accepted_by=student)
        assert again.approved_at == first.approved_at
        assert ConsentEvent.objects.filter(document=first).count() == 1


def test_mark_ready_refuses_a_superseded_draft(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a8")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        DocumentDraft.objects.filter(id=draft.id).update(status=DocumentDraft.Status.SUPERSEDED)
        draft.refresh_from_db()
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.SUPERSEDED


def test_new_version_supersedes_the_approved_one(agency_a, django_user_model):
    from apps.documents.revisions import counselor_quick_edit

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a9")
        counselor_user = django_user_model.objects.create(username="a9c")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=True
        )
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        new_version = counselor_quick_edit(
            document=approved, content=_content(), counselor=counselor
        )
        approved.refresh_from_db()
        assert approved.status == DocumentDraft.Status.SUPERSEDED
        assert new_version.status == DocumentDraft.Status.DRAFT


def test_revoke_consent_returns_the_draft_to_draft_and_clears_approval(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a10")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        event = revoke_consent(document=approved, revoked_by=student)
        assert event is not None and event.revoked_at is not None
        approved.refresh_from_db()
        assert approved.status == DocumentDraft.Status.DRAFT
        assert approved.approved_by_id is None
        assert approved.approved_at is None
        # Already revoked: a second call is a no-op, not an error.
        assert revoke_consent(document=approved, revoked_by=student) is None


def test_revoke_consent_requires_the_student_or_a_counselor(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a17")
        other_user = django_user_model.objects.create(username="a17b")
        other_student = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT, active=True
        )
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        with pytest.raises(ApprovalBlocked):
            revoke_consent(document=approved, revoked_by=other_student)
        approved.refresh_from_db()
        assert approved.status == DocumentDraft.Status.APPROVED
        assert ConsentEvent.objects.get(document=approved).revoked_at is None


def test_mark_ready_after_revocation_approves_again_with_a_new_consent_event(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a18")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        revoke_consent(document=approved, revoked_by=student)
        approved.refresh_from_db()
        reapproved = mark_ready(document=approved, accepted_by=student)
        assert reapproved.status == DocumentDraft.Status.APPROVED
        assert ConsentEvent.objects.filter(document=reapproved).count() == 2
        assert (
            ConsentEvent.objects.filter(document=reapproved, revoked_at__isnull=True).count() == 1
        )


def test_counselor_approves_mode_rejects_a_counselor_from_another_tenant(
    agency_a, agency_b, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a14")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        DocumentDraft.objects.filter(id=draft.id).update(
            approval_mode=DocumentDraft.ApprovalMode.COUNSELOR_APPROVES
        )
        draft.refresh_from_db()
    with tenant_scope(agency_b.id):
        other_user = django_user_model.objects.create(username="a14c-other")
        other_counselor = Membership.objects.create(
            tenant=agency_b, user=other_user, role=Membership.Role.COUNSELOR, active=True
        )
    with tenant_scope(agency_a.id):
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=other_counselor)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_per_document_mode_rejects_an_inactive_student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a15")
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        Membership.objects.filter(id=student.id).update(active=False)
        student.refresh_from_db()
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_counselor_approves_mode_rejects_an_inactive_counselor(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a16")
        counselor_user = django_user_model.objects.create(username="a16c")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=False
        )
        fact = _supporting_fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        DocumentDraft.objects.filter(id=draft.id).update(
            approval_mode=DocumentDraft.ApprovalMode.COUNSELOR_APPROVES
        )
        draft.refresh_from_db()
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=counselor)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_approval_blocked_carries_blocking_verdicts_without_claim_text(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a12")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        with pytest.raises(ApprovalBlocked) as exc_info:
            mark_ready(document=draft, accepted_by=student)
        blocked = exc_info.value
        assert blocked.verdicts
        assert all(
            v.verdict in (Verdict.UNSUPPORTED, Verdict.CONFLICTING) for v in blocked.verdicts
        )
        # claim_text ("BSc at Example U") is document text -- it must never
        # land in the exception message, only on the structured attribute.
        assert "BSc" not in str(blocked)
        assert "Example U" not in str(blocked)
        assert any(v.claim_text for v in blocked.verdicts)


def test_malformed_content_raises_approval_blocked_not_validation_error(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a13")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        DocumentDraft.objects.filter(id=draft.id).update(content={})
        draft.refresh_from_db()
        with pytest.raises(ApprovalBlocked):
            verdicts_for(draft)
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT


def test_populated_summary_without_a_matching_fact_blocks(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "a19")
        fact = _supporting_fact(student)
        content = CVContent(
            personal_information=PersonalInformation(
                full_name="Jane Doe", email="jane@example.com"
            ),
            education=(_EDUCATION,),
            experience=(),
            research=(),
            publications=(),
            awards=(),
            skills=(),
            languages=(),
            summary="Ambitious engineer who ships fast and learns faster.",
            document_language="en",
        )
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=content, facts=[fact]
        )
        verdicts = verdicts_for(draft)
        assert any(
            v.claim_path == "summary[0]" and v.verdict == Verdict.UNSUPPORTED for v in verdicts
        )
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.DRAFT
