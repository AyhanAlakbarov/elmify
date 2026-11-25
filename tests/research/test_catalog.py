"""Tests for persisting and pooling official scraped selectivity claims in `catalog.py`."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.funding.facts import award_facts, program_facts
from apps.funding.models import (
    OfficialSource,
    OfficialSourceSnapshot,
)
from apps.funding.probability import (
    estimate_program_admission_chance,
    estimate_scholarship_chance,
)
from apps.funding.validity import Evidence
from apps.research.catalog import (
    ResolvedProgram,
    claim_rows,
    write_catalog_entry,
)
from apps.research.discovery import LeadIdentity, ResearchLead
from apps.research.extraction import (
    CountClaim,
    ExtractedClaims,
    FundingFamilyClaim,
    GradeEquivalenceRuleClaim,
    GradeThresholdClaim,
    KeyDateClaim,
    MoneyClaim,
    SelectionRateClaim,
    TeachingLanguageClaim,
)
from tests.funding.conftest import make_profile

pytestmark = pytest.mark.django_db


def test_claim_rows_preserves_baseline_count_when_selectivity_fields_absent() -> None:
    """When optional selectivity fields on `ExtractedClaims` are `None`/`()`, `claim_rows`
    emits the exact baseline rows with zero count regression."""
    program = ResolvedProgram(
        institution_name="University of Technology Nuremberg",
        country_code="DE",
        city="Nürnberg",
        program_name="AI & Robotics (MSc)",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        confidence=0.9,
    )
    rows = claim_rows(program, claims, now=datetime(2026, 8, 30))
    assert len(rows) == 3
    assert [r[0] for r in rows] == ["IDENTITY", "STRUCTURE", "STRUCTURE"]


def test_claim_rows_emits_all_six_selectivity_and_grade_equivalence_fields() -> None:
    """`claim_rows` emits `published_selection_rate`, `awards_per_cycle`, `applicants_per_cycle`,
    `published_minimum_grade`, `grade_equivalence_rules`, and `selectivity_signals` with their
    verbatim citations and machine-readable bracketed values."""
    program = ResolvedProgram(
        institution_name="ETH Zurich",
        country_code="CH",
        city="Zurich",
        program_name="MSc in Data Science",
        degree_level="MASTER",
        teaching_languages=("English",),
        duration_months=24,
    )
    claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        published_selection_rate=SelectionRateClaim(
            rate=Decimal("0.06"),
            cycle_label="2026/2027",
            evidence="Only 6% of international applicants were admitted in 2026/2027.",
        ),
        awards_per_cycle=CountClaim(
            value=25,
            cycle_label="2026/2027",
            evidence="Up to 25 excellence scholarships are awarded each cycle.",
        ),
        applicants_per_cycle=CountClaim(
            value=500,
            cycle_label="2026/2027",
            evidence="The programme received 500 eligible applications last cycle.",
        ),
        published_minimum_grade=GradeThresholdClaim(
            minimum="3.5",
            scale="4.0",
            evidence="Applicants must hold a minimum GPA of 3.5 on a 4.0 scale.",
        ),
        grade_equivalence_rules=(
            GradeEquivalenceRuleClaim(
                rule_text="UK First-Class Honours (70%) is treated as equivalent to 3.7/4.0.",
                scope="COUNTRY",
                evidence="First-Class Honours (70%+) equals 3.7/4.0 in our evaluation table.",
            ),
        ),
        selectivity_signals=("Competitive holistic dossier ranking", "Top 10% class rank"),
        confidence=0.95,
    )

    rows = claim_rows(program, claims, now=datetime(2026, 8, 30))
    by_class: dict[str, list[str]] = {}
    for cls, txt in rows:
        by_class.setdefault(cls, []).append(txt)

    struct_texts = by_class["STRUCTURE"]
    elig_texts = by_class["ELIGIBILITY"]
    assert any("Published selection rate (2026/2027) [0.06]" in t for t in struct_texts)
    assert any("Awards per cycle (2026/2027) [25]" in t for t in struct_texts)
    assert any("Applicants per cycle (2026/2027) [500]" in t for t in struct_texts)
    assert any(
        "Selectivity signal: Competitive holistic dossier ranking" in t for t in struct_texts
    )
    assert any("Selectivity signal: Top 10% class rank" in t for t in struct_texts)
    assert any("GRADE: Minimum grade 3.5 (4.0) [3.5 / 4.0]" in t for t in elig_texts)
    assert any("GRADE_EQUIVALENCE (COUNTRY):" in t for t in elig_texts)


def test_write_catalog_entry_selectivity_claims_feed_real_probability_callers() -> None:
    """End-to-end test: `write_catalog_entry` persists official selectivity claims onto
    `Program` and `FundingOpportunity`, and `estimate_program_admission_chance` /
    `estimate_scholarship_chance` pool `(K, N)` and `published_selection_rate` with regime
    baselines and tighten `epistemic_se_logit`."""
    source = OfficialSource.objects.create(
        canonical_url="https://www.utn.de/en/study/ai-robotics-fellowship",
        publisher="www.utn.de",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/utn/selectivity",
        s3_version_id="1",
        sha256="d" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=timezone.now(),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=512,
        discovery_technique="seed:daad-ip",
    )
    lead = ResearchLead.from_url(
        source.canonical_url,
        source_type="PROGRAM",
        funding_family="UNIVERSITY_WIDE",
        discovered_by="seed:daad-ip",
        identity=LeadIdentity(
            institution_name="University of Technology Nuremberg",
            country_code="DE",
            city="Nürnberg",
            program_name="MSc Autonomous Systems",
        ),
    )

    # First write without official selectivity claims to measure regime baseline prior
    base_claims = ExtractedClaims(
        duration_months=24,
        teaching_languages=(
            TeachingLanguageClaim(language="English", evidence="Taught in English."),
        ),
        key_dates=(
            KeyDateClaim(
                kind="APPLICATION_DEADLINE",
                on=date(2027, 5, 1),
                evidence="Application deadline: 1 May 2027.",
            ),
        ),
        costs=(
            MoneyClaim(
                label="tuition",
                amount=Decimal("0.00"),
                currency="EUR",
                period="annual",
                evidence="Tuition is 0.00 EUR per year.",
            ),
        ),
        funding_family=FundingFamilyClaim(
            family="UNIVERSITY_WIDE",
            evidence="University-wide merit fellowship for international Master's students.",
        ),
        confidence=0.95,
    )
    written_base = write_catalog_entry(
        lead=lead, claims=base_claims, source=source, snapshot=snapshot
    )
    assert written_base is not None and written_base.opportunity is not None
    profile = make_profile(nationality="AZ")
    prog_facts = program_facts(written_base.program, costs=(), benefits=(), rules=())
    opp_facts = award_facts(
        written_base.opportunity,
        benefits=(),
        rules=(),
        country_code="DE",
        evidence=Evidence(offered="YES", applies_to="2027-2028"),
    )
    est_prog_before = estimate_program_admission_chance(
        written_base.program, prog_facts, profile
    )
    est_opp_before = estimate_scholarship_chance(
        written_base.opportunity, opp_facts, profile
    )

    # Now re-write with official selectivity claims (30 awards out of 250 applicants = 12.0%)
    selectivity_claims = base_claims.model_copy(
        update={
            "published_selection_rate": SelectionRateClaim(
                rate=Decimal("0.12"),
                cycle_label="2026/2027",
                evidence="The acceptance rate was 12% in the 2026/2027 cycle.",
            ),
            "awards_per_cycle": CountClaim(
                value=30,
                cycle_label="2026/2027",
                evidence="30 fellowships are awarded each cycle.",
            ),
            "applicants_per_cycle": CountClaim(
                value=250,
                cycle_label="2026/2027",
                evidence="Out of 250 international applicants per cycle.",
            ),
            "selectivity_signals": ("Highly selective entrance ranking",),
        }
    )
    written_sel = write_catalog_entry(
        lead=lead, claims=selectivity_claims, source=source, snapshot=snapshot
    )
    assert written_sel is not None and written_sel.opportunity is not None

    est_prog_after = estimate_program_admission_chance(
        written_sel.program, prog_facts, profile
    )
    est_opp_after = estimate_scholarship_chance(
        written_sel.opportunity, opp_facts, profile
    )

    assert est_prog_after.features["base_prior"] < est_prog_before.features["base_prior"]
    assert est_opp_after.features["base_prior"] < est_opp_before.features["base_prior"]
    assert est_prog_after.chance_pct < est_prog_before.chance_pct
    assert est_opp_after.chance_pct < est_opp_before.chance_pct
    assert (est_prog_after.epistemic_se_logit or 1.0) < (est_prog_before.epistemic_se_logit or 0.0)
    assert (est_opp_after.epistemic_se_logit or 1.0) < (est_opp_before.epistemic_se_logit or 0.0)
