import pytest
from django.db import IntegrityError, transaction

from apps.documents.drafts import attach_source_facts, create_draft
from apps.documents.models import DocumentDraft, DocumentDraftFact, VerifiedFact
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


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


def _fact(student, ref):
    return VerifiedFact.objects.create(
        student=student,
        category=VerifiedFact.Category.EDUCATION,
        payload={"institution_original": "Example U", "degree_as_awarded": "BSc"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
        source_ref=ref,
        created_by=student,
    )


def test_create_draft_allocates_sequential_versions(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "d1")
        v1 = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        v2 = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        assert (v1.version, v2.version) == (1, 2)


def test_create_draft_links_source_facts_through_tenant_scoped_rows(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "d2")
        fact = _fact(student, "consult-d2")
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=_content(), facts=[fact]
        )
        link = DocumentDraftFact.objects.get(document=draft, fact=fact)
        assert link.tenant_id == agency_a.id
        assert list(draft.source_facts.all()) == [fact]


def test_attach_source_facts_is_idempotent(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "d3")
        fact = _fact(student, "consult-d3")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        attach_source_facts(document=draft, facts=[fact])
        attach_source_facts(document=draft, facts=[fact])
        assert DocumentDraftFact.objects.filter(document=draft).count() == 1


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_draft_fact_link_rejected_by_composite_fk(
    agency_a, agency_b, django_user_model
):
    """A raw INSERT linking agency_b's draft to agency_a's fact must fail."""
    from uuid import uuid4

    from django.db import connection

    with tenant_scope(agency_a.id):
        student_a = _student(agency_a, django_user_model, "d4a")
        fact_a = _fact(student_a, "consult-d4")
    with tenant_scope(agency_b.id):
        student_b = _student(agency_b, django_user_model, "d4b")
        draft_b = create_draft(student=student_b, kind=DocumentDraft.Kind.CV, content=_content())
    with connection.cursor() as cursor, pytest.raises(IntegrityError), transaction.atomic():
        cursor.execute(
            """
            INSERT INTO documents_documentdraftfact
                (id, tenant_id, document_id, fact_id, created_at)
            VALUES (%s, %s, %s, %s, now())
            """,
            [uuid4(), agency_b.id, draft_b.id, fact_a.id],
        )


def test_a_draft_records_which_scholarship_it_is_for(agency_a, django_user_model):
    """Empty is meaningful: it means self-funded, and the resolver then has one
    fewer scope layer rather than no rules at all."""
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "d-funder")
        draft = DocumentDraft.objects.create(
            tenant=agency_a,
            student=student,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content=_content().model_dump(mode="json"),
        )
        assert draft.funding_opportunity is None


def test_approved_draft_content_is_never_mutated(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "d5")
        draft = create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        DocumentDraft.objects.filter(id=draft.id).update(status=DocumentDraft.Status.APPROVED)
        draft.refresh_from_db()
        original_content = draft.content
        create_draft(student=student, kind=DocumentDraft.Kind.CV, content=_content())
        draft.refresh_from_db()
        assert draft.content == original_content
