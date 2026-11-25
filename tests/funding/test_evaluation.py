"""Regression tests for `apps/funding/evaluation.py` and `apps/funding/facts.py`."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from apps.accounts.schemas import LanguageEvidence
from apps.funding.card import AwardCard
from apps.funding.evaluation import AwardCandidateFacts, scheme_pays_for, schemes_paying_for
from apps.funding.facts import score_program_fit
from apps.funding.models import Program
from apps.funding.validity import Evidence
from tests.funding.conftest import make_candidate, make_profile


def _make_home_award(
    *,
    name: str = "State Programme for Study Abroad",
    country_code: str = "AZ",
    scope: str = "HOLDER",
    pays_for_program_ids: frozenset[str] = frozenset(),
) -> AwardCandidateFacts:
    return AwardCandidateFacts(
        award_id=str(uuid4()),
        name=name,
        holder_name="Ministry of Science and Education",
        organisation_id=str(uuid4()),
        money_form="GRANT",
        route="STUDENT_APPLIES_SEPARATELY",
        unconfirmed=(),
        benefits=(),
        applicant_conditions=(),
        return_service=(),
        evidence_confidence="MEDIUM",
        evidence=Evidence(offered="YES", applies_to="2027-2028"),
        coverage_is_unstated=False,
        card=AwardCard(
            route="STUDENT_APPLIES_SEPARATELY",
            tuition="FULL",
            living="FULL",
            amounts=(),
            duration_text="",
            duration_months=None,
            timing="UNSTATED",
            cycle="2027-2028",
            unconfirmed=(),
        ),
        scope=scope,
        institution_id="",
        country_code=country_code,
        pays_for_program_ids=pays_for_program_ids,
    )


def test_scheme_pays_for_outbound_home_country_scholarship_parity_with_grouping() -> None:
    """Item 4: An outbound home-country scholarship (`award.country_code == home_country`,
    `scope in ('HOLDER', 'COUNTRY')`) with no restrictive `pays_for_program_ids` pays for
    foreign programmes (`candidate.program_country_code != home_country`) and never domestic
    programmes (`candidate.program_country_code == home_country`)."""
    home_award = _make_home_award(country_code="AZ", scope="HOLDER")
    foreign_cand = make_candidate(
        program_id="delft-msc",
        program_country_code="NL",
        location_key="NL-DELFT",
    )
    domestic_cand = make_candidate(
        program_id="baku-msc",
        program_country_code="AZ",
        location_key="AZ-BAKU",
    )

    assert scheme_pays_for(home_award, foreign_cand, home_country="AZ") is True
    assert scheme_pays_for(home_award, domestic_cand, home_country="AZ") is False

    profile = make_profile(nationality="AZ")
    assert schemes_paying_for(
        profile,
        foreign_cand,
        (home_award,),
        today=date(2026, 10, 24),
    ) == ("State Programme for Study Abroad",)
    assert (
        schemes_paying_for(
            profile,
            domestic_cand,
            (home_award,),
            today=date(2026, 10, 24),
        )
        == ()
    )

    # When pays_for_program_ids is explicitly populated, only listed programmes match
    listed_award = _make_home_award(
        country_code="AZ",
        scope="HOLDER",
        pays_for_program_ids=frozenset({"tum-msc"}),
    )
    assert scheme_pays_for(listed_award, foreign_cand, home_country="AZ") is False


def test_score_program_fit_normalizes_localized_teaching_languages() -> None:
    """Item 7: `score_program_fit` uses `_normalize_language` so localized teaching languages
    (`'Englisch'`, `'Anglais'`, `'Deutsch'`, `'en'`) receive the `+5` `ACADEMIC_FIT` bonus."""
    profile_en = make_profile(
        target_field="Computer Science",
        acceptable_teaching_languages=("English",),
        language_evidence=(),
    )
    prog_englisch = Program(
        id=uuid4(),
        canonical_key="prog:de-englisch",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE-MUNICH",
        degree_level="MASTER",
        teaching_languages=["Englisch"],
        duration_months=24,
    )
    prog_french_only = Program(
        id=uuid4(),
        canonical_key="prog:fr-francais",
        name="MSc Computer Science",
        campus_name="Main",
        city="Paris",
        country_code="FR",
        location_key="FR-PARIS",
        degree_level="MASTER",
        teaching_languages=["Français"],
        duration_months=24,
    )
    scores_en = score_program_fit(prog_englisch, profile_en)
    scores_fr = score_program_fit(prog_french_only, profile_en)
    assert scores_en["ACADEMIC_FIT"] == scores_fr["ACADEMIC_FIT"] + Decimal("5")

    profile_de_ev = make_profile(
        target_field="Computer Science",
        acceptable_teaching_languages=("German",),
        language_evidence=(
            LanguageEvidence(
                language="German",
                level="TestDaF 4",
                evidence_type="TEST",
                available_by=date(2026, 6, 1),
            ),
        ),
    )
    prog_deutsch = Program(
        id=uuid4(),
        canonical_key="prog:de-deutsch",
        name="MSc Computer Science",
        campus_name="Main",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["Deutsch"],
        duration_months=24,
    )
    scores_de = score_program_fit(prog_deutsch, profile_de_ev)
    assert scores_de["ACADEMIC_FIT"] == scores_fr["ACADEMIC_FIT"] + Decimal("5")
