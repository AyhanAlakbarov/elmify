"""FieldMap entries name "category.key". VerifiedFact stores a category and a
payload. This is the one place those two vocabularies meet."""

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _fact(agency, student, category, payload, *, confirmed=True, supersedes=None):
    from apps.documents.models import VerifiedFact

    return VerifiedFact.objects.create(
        tenant=agency,
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="passport.pdf",
        confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
        created_by=student,
        supersedes=supersedes,
    )


def test_confirmed_facts_flatten_to_dotted_names(agency_a, membership_a):
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(agency_a, membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "Ada Byron"})

        assert verified_values(membership_a)["identity.full_name"] == "Ada Byron"


def test_an_unconfirmed_fact_is_not_a_verified_value(agency_a, membership_a):
    """P1-14 and §5.2 both turn on "verified". An unconfirmed row is a claim,
    and typing it into an attested form is exactly what escalation prevents."""
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PERSONAL,
            {"city": "London"},
            confirmed=False,
        )

        assert "personal.city" not in verified_values(membership_a)


def test_a_correction_wins_over_what_it_supersedes(agency_a, membership_a):
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        original = _fact(
            agency_a, membership_a, VerifiedFact.Category.PERSONAL, {"city": "Londn"}
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PERSONAL,
            {"city": "London"},
            supersedes=original,
        )

        assert verified_values(membership_a)["personal.city"] == "London"


def test_non_string_payload_members_are_left_out(agency_a, membership_a):
    """A form field takes text. A list of publications is a document-generation
    input, not something to type into an input element, and silently
    str()-ing it would fill a portal with a Python repr."""
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PUBLICATION,
            {"titles": ["a", "b"], "count": 2, "venue": "Nature"},
        )

        values = verified_values(membership_a)
        assert values["publication.venue"] == "Nature"
        assert "publication.titles" not in values
        assert "publication.count" not in values


def test_a_gap_statement_is_a_portal_value(agency_a, membership_a):
    """A gap statement is printed on the CV and nowhere else -- typed into a
    portal field it would leave the one document it was written for."""
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.TIMELINE,
            {
                "start_date": "2023-06-30",
                "end_date": "2023-11-01",
                "statement": "Full-time carer for a family member.",
            },
        )
        _fact(agency_a, membership_a, VerifiedFact.Category.IDENTITY, {"full_name": "Ada Byron"})

        values = verified_values(membership_a)
        assert values["identity.full_name"] == "Ada Byron"
        assert values["timeline.statement"] == "Full-time carer for a family member."


def test_the_learnable_vocabulary_is_fixed_not_the_students_own() -> None:
    from apps.portals.profile import LEARNABLE_FIELDS

    assert "identity.full_name" in LEARNABLE_FIELDS
    assert "education.institution_original" in LEARNABLE_FIELDS
    assert len(set(LEARNABLE_FIELDS)) == len(LEARNABLE_FIELDS)


def test_each_degree_gets_its_own_index_oldest_first(agency_a, membership_a) -> None:
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import verified_values

    with tenant_scope(agency_a.id):
        _fact(agency_a, membership_a, VerifiedFact.Category.EDUCATION, {
            "institution_original": "ADA University", "degree_as_awarded": "MSc",
            "start_date": "2022-09",
        })
        _fact(agency_a, membership_a, VerifiedFact.Category.EDUCATION, {
            "institution_original": "Baku State University", "degree_as_awarded": "BSc",
            "start_date": "2018-09",
        })
        values = verified_values(membership_a)
    assert values["education.1.institution_original"] == "Baku State University"
    assert values["education.2.institution_original"] == "ADA University"
    assert "education.3.institution_original" not in values
    assert values["education.institution_original"] == "Baku State University"  # last row


def test_indexed_education_keys_are_learnable_and_classed() -> None:
    from apps.portals.profile import LEARNABLE_FIELDS, field_class

    assert "education.2.institution_original" in LEARNABLE_FIELDS
    assert "education.4.institution_original" not in LEARNABLE_FIELDS
    assert field_class("education.2.end_date") == "education.end_date"
    assert field_class("identity.full_name") == "identity.full_name"


def test_indexed_experience_reference_and_timeline_values_flatten_oldest_first(
    agency_a, membership_a
) -> None:
    from apps.documents.models import VerifiedFact
    from apps.portals.profile import LEARNABLE_FIELDS, verified_values

    assert "experience.2.employer" in LEARNABLE_FIELDS
    assert "reference.2.email" in LEARNABLE_FIELDS
    assert "timeline.2.statement" in LEARNABLE_FIELDS
    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.EXPERIENCE,
            {
                "employer": "SOCAR",
                "title": "Senior Analyst",
                "start_date": "2023-01",
                "bullets": ["Built forecasting pipeline", "Led 3 interns"],
            },
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.EXPERIENCE,
            {
                "employer": "PASHA Bank",
                "title": "Junior Analyst",
                "start_date": "2021-06",
                "bullets": ["Automated credit reports"],
            },
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.REFERENCE,
            {"name": "Prof. A", "email": "a@uni.edu"},
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.REFERENCE,
            {"name": "Prof. B", "email": "b@uni.edu"},
        )
        values = verified_values(membership_a)
    assert values["experience.1.employer"] == "PASHA Bank"
    assert values["experience.2.employer"] == "SOCAR"
    assert values["experience.2.bullets"] == "Built forecasting pipeline\nLed 3 interns"
    assert values["reference.1.name"] == "Prof. A"
    assert values["reference.2.name"] == "Prof. B"


def test_narrative_values_combine_confirmed_inputs_and_approved_letter_drafts(
    agency_a, membership_a, program_factory
) -> None:
    from apps.documents.models import DocumentDraft, NarrativeInput
    from apps.portals.profile import LEARNABLE_FIELDS, narrative_values

    assert "narrative.motivation_letter" in LEARNABLE_FIELDS
    assert "narrative.why_programme" in LEARNABLE_FIELDS
    program = program_factory()
    other_program = program_factory()
    with tenant_scope(agency_a.id):
        NarrativeInput.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=NarrativeInput.Kind.DEVELOPMENT_IMPACT,
            text="Lead energy transition policy in Azerbaijan.",
            proposed_by=NarrativeInput.ProposedBy.STUDENT,
            confirmed_at=timezone.now(),
        )
        NarrativeInput.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            provenance={"program_id": str(other_program.id)},
            text="Wrong programme fit.",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
            confirmed_at=timezone.now(),
        )
        NarrativeInput.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=NarrativeInput.Kind.RESEARCH_FIT,
            provenance={"program_id": str(program.id)},
            text="Work with the Power Systems Lab at TUM.",
            proposed_by=NarrativeInput.ProposedBy.ENGINE,
            confirmed_at=timezone.now(),
        )
        DocumentDraft.objects.create(
            tenant=agency_a,
            student=membership_a,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            programme=program,
            version=1,
            status=DocumentDraft.Status.APPROVED,
            content={
                "opening": "Dear Admissions Committee,",
                "why_programme": "TUM offers the exact grid-modelling curriculum I need.",
                "closing": "Sincerely, Ada Byron",
            },
        )
        values = narrative_values(membership_a, program_id=program.id)
    assert values["narrative.home_country_contribution"] == (
        "Lead energy transition policy in Azerbaijan."
    )
    assert values["narrative.research_plan"] == "Work with the Power Systems Lab at TUM."
    assert values["narrative.why_programme"] == (
        "TUM offers the exact grid-modelling curriculum I need."
    )
    assert "Dear Admissions Committee," in values["narrative.motivation_letter"]
    assert "Wrong programme fit." not in values.values()
