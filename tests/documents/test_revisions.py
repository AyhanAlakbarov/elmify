import pytest

from apps.documents.drafts import create_draft
from apps.documents.models import DocumentDraft, RevisionRequest, VerifiedFact
from apps.documents.revisions import RevisionRejected, counselor_quick_edit, request_revision
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


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


def _student_and_draft(agency, django_user_model, username):
    user = django_user_model.objects.create(username=username)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
    return student, draft


def test_third_style_structure_request_rejected(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _student_and_draft(agency_a, django_user_model, "r1")
        for _ in range(2):
            request_revision(
                document=draft,
                kind=RevisionRequest.Kind.STYLE_STRUCTURE,
                requested_by=student,
                note="tighten the wording",
            )
        with pytest.raises(RevisionRejected):
            request_revision(
                document=draft,
                kind=RevisionRequest.Kind.STYLE_STRUCTURE,
                requested_by=student,
                note="one more pass",
            )


def test_factual_correction_requires_superseding_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _student_and_draft(agency_a, django_user_model, "r2")
        with pytest.raises(RevisionRejected):
            request_revision(
                document=draft,
                kind=RevisionRequest.Kind.FACTUAL_CORRECTION,
                requested_by=student,
                note="my grade was wrong",
                superseding_fact=None,
            )


def test_factual_correction_rejects_an_already_superseded_fact(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _student_and_draft(agency_a, django_user_model, "r2b")
        old = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade_native": "3.5"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="consult-old",
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={"grade_native": "3.8"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="consult-new",
            supersedes=old,
            created_by=student,
        )
        with pytest.raises(RevisionRejected):
            request_revision(
                document=draft,
                kind=RevisionRequest.Kind.FACTUAL_CORRECTION,
                requested_by=student,
                note="correction",
                superseding_fact=old,
            )


def test_factual_correction_unlimited_with_valid_superseding_facts(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _student_and_draft(agency_a, django_user_model, "r3")
        for i in range(5):
            fact = VerifiedFact.objects.create(
                student=student,
                category=VerifiedFact.Category.EDUCATION,
                payload={"grade_native": str(i)},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref=f"consult-{i}",
                created_by=student,
            )
            request_revision(
                document=draft,
                kind=RevisionRequest.Kind.FACTUAL_CORRECTION,
                requested_by=student,
                note="correction",
                superseding_fact=fact,
            )
        assert (
            RevisionRequest.objects.filter(
                document=draft, kind=RevisionRequest.Kind.FACTUAL_CORRECTION
            ).count()
            == 5
        )


def test_counselor_quick_edit_does_not_count_toward_style_round_cap(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _student_and_draft(agency_a, django_user_model, "r4")
        counselor_user = django_user_model.objects.create(username="counselor4")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=True
        )
        for _ in range(2):
            request_revision(
                document=draft,
                kind=RevisionRequest.Kind.STYLE_STRUCTURE,
                requested_by=student,
                note="tighten",
            )
        edited = counselor_quick_edit(document=draft, content=_content(), counselor=counselor)
        assert edited.version == draft.version + 1
        assert edited.status == DocumentDraft.Status.DRAFT
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.SUPERSEDED
        # the cap is still exhausted for the student, but the quick edit worked
        with pytest.raises(RevisionRejected):
            request_revision(
                document=edited,
                kind=RevisionRequest.Kind.STYLE_STRUCTURE,
                requested_by=student,
                note="one more",
            )


def test_counselor_quick_edit_supersedes_an_approved_document(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student, draft = _student_and_draft(agency_a, django_user_model, "r5")
        counselor_user = django_user_model.objects.create(username="counselor5")
        counselor = Membership.objects.create(
            tenant=agency_a, user=counselor_user, role=Membership.Role.COUNSELOR, active=True
        )
        DocumentDraft.objects.filter(id=draft.id).update(status=DocumentDraft.Status.APPROVED)
        edited = counselor_quick_edit(document=draft, content=_content(), counselor=counselor)
        assert edited.status == DocumentDraft.Status.DRAFT
        draft.refresh_from_db()
        assert draft.status == DocumentDraft.Status.SUPERSEDED
