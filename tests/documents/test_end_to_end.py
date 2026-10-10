# tests/documents/test_end_to_end.py
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.documents.approval import mark_ready
from apps.documents.drafts import create_draft
from apps.documents.generation import generate_cv
from apps.documents.models import DocumentDraft, RevisionRequest, VerifiedFact
from apps.documents.render import render_draft
from apps.documents.revisions import request_revision
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.documents.storage import store_document
from apps.documents.verification import Verdict, fact_payload
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_identity_fact

pytestmark = pytest.mark.django_db

_EDUCATION = EducationEntry(
    degree_as_awarded="BSc",
    institution_original="Example University",
    city="Berlin",
    country="DE",
    start_date="2020-09-01",
    end_date="2024-06-30",
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


def _client():
    client = MagicMock()
    response = MagicMock()
    response.output_parsed = _content()
    response.output = []
    client.responses.parse.return_value = response
    return client


def test_facts_to_generation_to_gate_to_approval_to_render_to_storage(
    agency_a, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="e2e1")
        student = Membership.objects.create(
            tenant=agency_a,
            user=user,
            role=Membership.Role.STUDENT,
            active=True,
            application_email="e2e1@applications.example",
        )
        make_identity_fact(student)
        fact = VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload=fact_payload(_EDUCATION, category=VerifiedFact.Category.EDUCATION),
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="transcript-1",
            confirmed_by=student,
            confirmed_at=timezone.now(),
            created_by=student,
        )

        result = generate_cv(student=student, client=_client())
        assert result.retried is False
        assert all(verdict.verdict == Verdict.SUPPORTED for verdict in result.verdicts)

        draft = create_draft(
            student=student,
            kind=DocumentDraft.Kind.CV,
            content=result.content,
            facts=[fact],
            render_variant=DocumentDraft.RenderVariant.STANDARD,
        )
        assert list(draft.source_facts.all()) == [fact]

        approved = mark_ready(document=draft, accepted_by=student)
        assert approved.status == DocumentDraft.Status.APPROVED

        artifact = render_draft(draft=approved)
        key = store_document(
            draft=approved, filename="cv-v1.pdf", content=artifact.pdf_bytes, store=fake_store
        )
        assert key.startswith(f"tenants/{agency_a.id}/")

        request_revision(
            document=approved,
            kind=RevisionRequest.Kind.STYLE_STRUCTURE,
            requested_by=student,
            note="tighten the education section wording",
        )
        result_v2 = generate_cv(student=student, client=_client())
        draft_v2 = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=result_v2.content, facts=[fact]
        )
        assert draft_v2.version == approved.version + 1

        # regeneration never touches the approved row
        approved.refresh_from_db()
        assert approved.content == draft.content
        assert approved.status == DocumentDraft.Status.APPROVED


def test_a_fabricated_claim_never_reaches_storage(agency_a, django_user_model, fake_store):
    """The whole point of the engine, asserted end to end: no facts, no artefact."""
    from apps.documents.approval import ApprovalBlocked
    from apps.documents.render import DraftNotApproved
    from apps.documents.storage import DocumentStoreRefused

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="e2e2")
        student = Membership.objects.create(
            tenant=agency_a,
            user=user,
            role=Membership.Role.STUDENT,
            active=True,
            application_email="e2e2@applications.example",
        )
        # Identity satisfies the precondition; nothing else is in the ledger,
        # so every substantive claim the model makes is fabricated. That is
        # what this test is about, and the gate must not obscure it.
        make_identity_fact(student)
        result = generate_cv(student=student, client=_client())
        assert result.retried is True
        draft = create_draft(
            student=student, kind=DocumentDraft.Kind.CV, content=result.content
        )
        with pytest.raises(ApprovalBlocked):
            mark_ready(document=draft, accepted_by=student)
        with pytest.raises(DraftNotApproved):
            render_draft(draft=draft)
        with pytest.raises(DocumentStoreRefused):
            store_document(
                draft=draft, filename="cv-v1.pdf", content=b"%PDF-1.4", store=fake_store
            )
