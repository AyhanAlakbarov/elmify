# tests/documents/test_tenant_isolation.py
import pytest

from apps.documents.approval import mark_ready
from apps.documents.drafts import create_draft
from apps.documents.models import (
    ConsentEvent,
    DocumentDraft,
    DocumentDraftFact,
    NarrativeInput,
    RevisionRequest,
    VerifiedFact,
)
from apps.documents.revisions import request_revision
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.verification import fact_payload
from apps.tenancy.context import TenantContextMissing, tenant_scope
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

_MODELS = (
    VerifiedFact,
    DocumentDraft,
    DocumentDraftFact,
    RevisionRequest,
    ConsentEvent,
    NarrativeInput,
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


def _populate(agency, django_user_model, name):
    """Create one row in every model in this app, for one tenant."""
    from django.utils import timezone

    user = django_user_model.objects.create(username=name)
    student = Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )
    make_identity_fact(student)
    fact = VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload=fact_payload(_EDUCATION, category=VerifiedFact.Category.EDUCATION),
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref=f"consult-{name}",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        created_by=student,
    )
    draft = create_draft(
        student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
    )
    request_revision(
        document=draft,
        kind=RevisionRequest.Kind.STYLE_STRUCTURE,
        requested_by=student,
        note="tighten",
    )
    mark_ready(document=draft, accepted_by=student)
    NarrativeInput.objects.create(
        student=student,
        kind=NarrativeInput.Kind.RESEARCH_PLAN,
        text="plan",
        proposed_by=NarrativeInput.ProposedBy.ENGINE,
    )
    return student


def test_every_model_is_scoped_to_the_active_tenant(agency_a, agency_b, django_user_model):
    with tenant_scope(agency_a.id):
        _populate(agency_a, django_user_model, "ti-a")
    with tenant_scope(agency_b.id):
        _populate(agency_b, django_user_model, "ti-b")
        for model in _MODELS:
            rows = list(model.objects.all())
            assert rows, f"{model.__name__} has no row to check"
            assert all(row.tenant_id == agency_b.id for row in rows)


def test_cross_tenant_save_raises(agency_a, agency_b, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="ti-cross")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
    with tenant_scope(agency_b.id):
        with pytest.raises(ValueError):
            VerifiedFact.objects.create(
                tenant=agency_a,  # explicit wrong tenant under agency_b's scope
                student=student,
                category=VerifiedFact.Category.SKILL,
                payload={"skill": "x"},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="x",
                created_by=student,
            )


def test_no_operation_proceeds_without_a_tenant_context(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="ti-none")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
    with pytest.raises(TenantContextMissing):
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.SKILL,
            payload={},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="x",
            created_by=student,
        )
