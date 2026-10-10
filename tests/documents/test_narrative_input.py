import pytest

from apps.documents.models import DocumentDraft, NarrativeInput
from apps.documents.schemas import CVContent, EducationEntry, PersonalInformation
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def test_narrative_input_starts_engine_proposed_unconfirmed(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="n1")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        entry = NarrativeInput.objects.create(
            student=student,
            kind=NarrativeInput.Kind.RESEARCH_PLAN,
            text="Investigate transfer learning for low-resource NLP...",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
        )
        assert entry.confirmed_at is None
        assert entry.proposed_by == NarrativeInput.ProposedBy.ENGINE


def test_document_draft_derived_from_links_letter_to_core_narrative(agency_a, django_user_model):
    def _content():
        return CVContent(
            personal_information=PersonalInformation(
                full_name="Jane Doe", email="jane@example.com"
            ),
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

    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="n2")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        narrative = DocumentDraft.objects.create(
            student=student,
            kind=DocumentDraft.Kind.CORE_NARRATIVE,
            version=1,
            content=_content().model_dump(mode="json"),
            status=DocumentDraft.Status.APPROVED,
        )
        letter = DocumentDraft.objects.create(
            student=student,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            version=1,
            content=_content().model_dump(mode="json"),
            status=DocumentDraft.Status.DRAFT,
            derived_from=narrative,
        )
        assert letter.derived_from_id == narrative.id
