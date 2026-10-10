import pytest
from django.utils import timezone

from apps.documents.approval import mark_ready, revoke_consent
from apps.documents.drafts import create_draft
from apps.documents.models import DocumentDraft, RevisionRequest, VerifiedFact
from apps.documents.revisions import request_revision
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.verification import fact_payload
from apps.funding.models import AuditEvent
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


def _fact(student):
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload=fact_payload(_EDUCATION, category=VerifiedFact.Category.EDUCATION),
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref="consult-ae",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        created_by=student,
    )


def test_creating_a_draft_records_document_generated(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ae1")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        assert AuditEvent.objects.filter(
            object_id=draft.id, event="document.generated"
        ).count() == 1


def test_approval_and_revocation_record_events(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ae2")
        fact = _fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        event = AuditEvent.objects.get(object_id=approved.id, event="document.approved")
        assert event.actor_id == student.id
        revoke_consent(document=approved, revoked_by=student)
        assert AuditEvent.objects.filter(
            object_id=approved.id, event="document.consent_revoked"
        ).count() == 1


def test_idempotent_approval_does_not_record_a_second_event(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ae3")
        fact = _fact(student)
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        approved = mark_ready(document=draft, accepted_by=student)
        mark_ready(document=approved, accepted_by=student)
        assert AuditEvent.objects.filter(
            object_id=approved.id, event="document.approved"
        ).count() == 1


def test_revision_request_records_an_event(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ae4")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        request_revision(
            document=draft,
            kind=RevisionRequest.Kind.STYLE_STRUCTURE,
            requested_by=student,
            note="tighten",
        )
        assert AuditEvent.objects.filter(
            object_id=draft.id, event="document.revision_requested"
        ).count() == 1


def test_audit_events_never_contain_document_text(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "ae6")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        for event in AuditEvent.objects.filter(object_id=draft.id):
            # AuditEvent has no free-text content column other than `event`
            # (a short label) -- assert the label itself never embeds prose.
            assert len(event.event) < 100
            assert "Jane Doe" not in event.event
