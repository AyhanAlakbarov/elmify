import pytest
from django.utils import timezone

from apps.documents.models import VerifiedFact
from apps.portals.profile import _payload_str, verified_values
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _fact(agency, student, category, payload):
    return VerifiedFact.objects.create(
        tenant=agency,
        student=student,
        category=category,
        payload=payload,
        source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
        source_ref="cv.pdf",
        confirmed_by=student,
        confirmed_at=timezone.now(),
        created_by=student,
    )


def test_payload_str_converts_numeric_scalars_and_string_lists_excluding_bools() -> None:
    assert _payload_str(VerifiedFact.Category.EDUCATION, "ects_credits", 240) == "240"
    assert _payload_str(VerifiedFact.Category.EDUCATION, "grade_native", 3.85) == "3.85"
    assert _payload_str(VerifiedFact.Category.EXPERIENCE, "unpaid", True) is None
    assert _payload_str(VerifiedFact.Category.EXPERIENCE, "unpaid", False) is None
    assert (
        _payload_str(
            VerifiedFact.Category.RESEARCH,
            "methods",
            ["DFT", "Molecular Dynamics"],
        )
        == "DFT, Molecular Dynamics"
    )
    assert (
        _payload_str(
            VerifiedFact.Category.RESEARCH,
            "outcomes",
            ("First-author preprint", "Conference talk"),
        )
        == "First-author preprint, Conference talk"
    )


def test_verified_values_preserves_scalar_and_list_fields_and_indexes_multi_row_categories(
    agency_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.EDUCATION,
            {
                "institution_original": "Baku State University",
                "degree_as_awarded": "BSc",
                "ects_credits": 240,
                "relevant_coursework": ["Linear Algebra", "Optimization"],
            },
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.AWARD,
            {"title": "Presidential Scholar", "date": 2023},
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.AWARD,
            {"title": "Best Thesis Award", "date": "2024"},
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.PUBLICATION,
            {
                "title": "Graph Networks for Grids",
                "year": 2024,
                "authors": ["Ada Byron", "Charles Babbage"],
                "venue": "IEEE PES",
            },
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.RESEARCH,
            {
                "thesis_title": "Smart Grid Stability",
                "methods": ["Time-series forecasting", "Optimal power flow"],
                "outcomes": ["Open-source solver", "Journal submission"],
            },
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.LANGUAGE,
            {"language": "English", "cefr_level": "C1", "test_score": 7.5},
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.SKILL,
            {"name": "Python", "category": "Programming", "evidence": ["Built solver"]},
        )
        _fact(
            agency_a,
            membership_a,
            VerifiedFact.Category.CERTIFICATION,
            {"title": "AWS Solutions Architect", "issuer": "AWS", "date": 2024},
        )

        values = verified_values(membership_a)

    assert values["education.ects_credits"] == "240"
    assert values["education.1.ects_credits"] == "240"
    assert values["education.relevant_coursework"] == "Linear Algebra, Optimization"
    assert values["award.1.title"] == "Presidential Scholar"
    assert values["award.1.date"] == "2023"
    assert values["award.2.title"] == "Best Thesis Award"
    assert values["award.title"] == "Best Thesis Award"
    assert values["publication.1.title"] == "Graph Networks for Grids"
    assert values["publication.1.year"] == "2024"
    assert values["publication.1.authors"] == "Ada Byron, Charles Babbage"
    assert values["publication.venue"] == "IEEE PES"
    assert values["research.1.thesis_title"] == "Smart Grid Stability"
    assert values["research.1.methods"] == "Time-series forecasting, Optimal power flow"
    assert values["research.1.outcomes"] == "Open-source solver, Journal submission"
    assert values["research.methods"] == "Time-series forecasting, Optimal power flow"
    assert values["language.1.language"] == "English"
    assert values["language.1.test_score"] == "7.5"
    assert values["skill.1.name"] == "Python"
    assert values["skill.1.evidence"] == "Built solver"
    assert values["certification.1.title"] == "AWS Solutions Architect"
    assert values["certification.1.date"] == "2024"


def test_learnable_fields_and_verified_values_cap_all_indexed_categories_and_mirror_given_name(
    agency_a, membership_a
) -> None:
    from apps.portals.profile import LEARNABLE_FIELDS, document_sources
    from tests.portals.test_packet import _clean_upload

    for prefix in ("award", "publication", "research", "language", "skill", "certification"):
        assert any(f.startswith(f"{prefix}.1.") for f in LEARNABLE_FIELDS)
        assert any(f.startswith(f"{prefix}.3.") for f in LEARNABLE_FIELDS)
        assert not any(f.startswith(f"{prefix}.4.") for f in LEARNABLE_FIELDS)

    with tenant_scope(agency_a.id):
        for idx in range(1, 5):
            _fact(
                agency_a,
                membership_a,
                VerifiedFact.Category.AWARD,
                {"title": f"Award {idx}"},
            )
        doc = _clean_upload(agency_a, membership_a, "PASSPORT")
        VerifiedFact.objects.create(
            tenant=agency_a,
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"given_names": "Nərmin"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref=f"document:{doc.id}",
            confirmed_by=membership_a,
            confirmed_at=timezone.now(),
            created_by=membership_a,
        )
        values = verified_values(membership_a)
        sources = document_sources(membership_a, values)

    assert values["award.1.title"] == "Award 1"
    assert values["award.3.title"] == "Award 3"
    assert "award.4.title" not in values
    assert values["identity.given_names"] == "Nərmin"
    assert values["identity.given_name"] == "Nərmin"
    assert sources["identity.given_names"] == "passport"
    assert sources["identity.given_name"] == "passport"
