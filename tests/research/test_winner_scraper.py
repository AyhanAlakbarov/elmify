from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from apps.funding.models import FundingOpportunity, Institution, Program
from apps.research.models import WinnerCohortProfile
from apps.research.register import record_organisation
from apps.research.winner_scraper import (
    RawWinnerProfile,
    WinnerProviderError,
    aggregate_winner_cohort,
    sync_winner_cohort_for_opportunity,
    sync_winner_cohort_for_program,
)

pytestmark = pytest.mark.django_db


class _StubProvider:
    provider_name = "stub_linkedin_3p"

    def __init__(self, payloads: list[dict[str, Any] | RawWinnerProfile]) -> None:
        self._payloads = payloads

    def search_winners(
        self,
        *,
        query: str,
        target_name: str,
        holder_name: str,
        country_code: str,
        limit: int = 50,
    ) -> list[dict[str, Any] | RawWinnerProfile]:
        return list(self._payloads[:limit])


class _FailingProvider:
    provider_name = "broken_linkedin_3p"

    def search_winners(
        self,
        *,
        query: str,
        target_name: str,
        holder_name: str,
        country_code: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        raise WinnerProviderError("broken_linkedin_3p returned HTTP 503: Service Unavailable")


def test_aggregate_winner_cohort_strips_pii_and_computes_distributions() -> None:
    raw_payloads: list[dict[str, Any]] = [
        {
            "full_name": "Leyla Mammadova",
            "linkedin_url": "https://www.linkedin.com/in/leyla-mammadova-12345",
            "public_identifier": "leyla-mammadova-12345",
            "headline": "Erasmus Mundus ChEMoinformatics+ Scholar at University of Strasbourg",
            "origin_country": "AZ",
            "education": [
                {
                    "degree_name": "Bachelor of Science",
                    "field_of_study": "Chemistry",
                    "school": "Baku State University",
                }
            ],
            "work_experience_months": 12,
            "accomplishment_publications": [{"name": "QSAR modeling of kinase inhibitors"}],
        },
        {
            "full_name": "Mateo Rossi",
            "linkedin_url": "https://www.linkedin.com/in/mateo-rossi-999",
            "public_identifier": "mateo-rossi-999",
            "headline": "ChEMoinformatics+ Master Student",
            "origin_country": "IT",
            "education": [
                {
                    "degree_name": "BSc",
                    "field_of_study": "Computer Science",
                }
            ],
            "work_experience_months": 24,
            "accomplishment_publications": [],
        },
        {
            "full_name": "Nigar Aliyeva",
            "linkedin_url": "https://www.linkedin.com/in/nigar-aliyeva-777",
            "origin_country": "AZ",
            "prior_degree_fields": ["Cheminformatics", "Chemistry"],
            "prior_degree_level": "MASTER",
            "work_experience_months": 36,
            "has_research_signal": True,
        },
        {
            "full_name": "Omar Farooq",
            "linkedin_url": "https://www.linkedin.com/in/omar-farooq-888",
            "origin_country": "PK",
            "prior_degree_fields": ["Pharmacy"],
            "prior_degree_level": "BACHELOR",
            "work_experience_months": 6,
            "has_research_signal": False,
        },
    ]

    agg = aggregate_winner_cohort(raw_payloads)

    assert agg["sample_size"] == 4
    assert agg["origin_country_counts"] == {"AZ": 2, "IT": 1, "PK": 1}
    assert agg["prior_degree_fields"] == {
        "chemistry": 2,
        "computer science": 1,
        "cheminformatics": 1,
        "pharmacy": 1,
    }
    assert agg["prior_degree_levels"] == {"BACHELOR": 3, "MASTER": 1}
    assert agg["work_experience_months_p25"] == 10
    assert agg["work_experience_months_median"] == 18
    assert agg["work_experience_months_p75"] == 27
    assert agg["research_signal_rate"] == Decimal("0.5000")

    serialized = str(agg)
    for forbidden in (
        "Leyla",
        "Mammadova",
        "Mateo",
        "Nigar",
        "Omar",
        "linkedin.com",
        "leyla-mammadova",
    ):
        assert forbidden not in serialized


def test_sync_winner_cohort_upserts_program_and_opportunity_profiles() -> None:
    inst = Institution.objects.create(
        canonical_key="fr:unistra",
        name="University of Strasbourg",
        country_code="FR",
        official_website="https://www.unistra.fr",
    )
    program = Program.objects.create(
        canonical_key="fr:unistra:chemoinformatics",
        name="ChEMoinformatics+",
        institution=inst,
        campus_name="Main",
        city="Strasbourg",
        country_code="FR",
        location_key="FR-STRASBOURG",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    org = record_organisation(
        domain="daad.de",
        name="DAAD",
        kind="NATIONAL_GOVERNMENT",
        country_code="DE",
        found_via="REGISTER",
    )
    opportunity = FundingOpportunity.objects.create(
        canonical_key="read:holder:daad-stem",
        name="DAAD Study Scholarships for STEM Disciplines",
        holder="NATIONAL_GOVERNMENT",
        holder_domain="daad.de",
        holder_name="DAAD",
        family="GOVERNMENT_SCHOLARSHIP",
        organisation=org,
        scope_type="HOLDER",
        route="SEPARATE_APPLICATION",
        money_form="GRANT",
        tuition="NONE",
        living="FULL",
        agreement="AGREED",
        served=True,
    )

    provider = _StubProvider(
        [
            {
                "full_name": "Redacted Person",
                "linkedin_url": "https://www.linkedin.com/in/redacted",
                "origin_country": "AZ",
                "prior_degree_fields": ["Chemistry"],
                "prior_degree_level": "BACHELOR",
                "work_experience_months": 18,
                "has_research_signal": True,
            },
            {
                "full_name": "Second Redacted Person",
                "linkedin_url": "https://www.linkedin.com/in/redacted-2",
                "origin_country": "TR",
                "prior_degree_fields": ["Chemical Engineering"],
                "prior_degree_level": "BACHELOR",
                "work_experience_months": 6,
                "has_research_signal": False,
            },
        ]
    )

    prog_cohort = sync_winner_cohort_for_program(program, provider=provider)
    assert prog_cohort is not None
    assert prog_cohort.program_id == program.id
    assert prog_cohort.opportunity_id is None
    assert prog_cohort.target_kind == WinnerCohortProfile.TargetKind.PROGRAM
    assert prog_cohort.target_name == "ChEMoinformatics+"
    assert prog_cohort.holder_name == "University of Strasbourg"
    assert prog_cohort.country_code == "FR"
    assert prog_cohort.sample_size == 2
    assert prog_cohort.origin_country_counts == {"AZ": 1, "TR": 1}
    assert prog_cohort.source_provider == "stub_linkedin_3p"

    opp_cohort = sync_winner_cohort_for_opportunity(opportunity, provider=provider)
    assert opp_cohort is not None
    assert opp_cohort.opportunity_id == opportunity.id
    assert opp_cohort.program_id is None
    assert opp_cohort.target_kind == WinnerCohortProfile.TargetKind.OPPORTUNITY
    assert opp_cohort.target_name == "DAAD Study Scholarships for STEM Disciplines"
    assert opp_cohort.holder_name == "DAAD"
    assert opp_cohort.country_code == "DE"
    assert opp_cohort.sample_size == 2


def test_sync_winner_cohort_logs_and_returns_none_when_unconfigured_or_failing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("LINKEDIN_WINNER_PROVIDER_URL", raising=False)
    monkeypatch.delenv("LINKEDIN_WINNER_API_KEY", raising=False)

    inst = Institution.objects.create(
        canonical_key="de:tum",
        name="Technical University of Munich",
        country_code="DE",
        official_website="https://www.tum.de",
    )
    program = Program.objects.create(
        canonical_key="de:tum:informatics",
        name="M.Sc. Informatics",
        institution=inst,
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE-MUNICH",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )

    with caplog.at_level("INFO"):
        res_unconfigured = sync_winner_cohort_for_program(program)
    assert res_unconfigured is None
    assert not WinnerCohortProfile.objects.filter(program_id=program.id).exists()
    assert "LINKEDIN_WINNER_PROVIDER_URL" in caplog.text

    caplog.clear()
    with caplog.at_level("WARNING"):
        res_failed = sync_winner_cohort_for_program(program, provider=_FailingProvider())
    assert res_failed is None
    assert not WinnerCohortProfile.objects.filter(program_id=program.id).exists()
    assert "broken_linkedin_3p" in caplog.text
    assert "HTTP 503" in caplog.text


def test_http_provider_rejects_cleartext_private_and_loopback_urls() -> None:
    from apps.research.winner_scraper import HttpThirdPartyLinkedInProvider

    for bad_url in (
        "http://api.example.com/v1/winners",
        "https://user:secret@api.example.com/v1/winners",
        "https://127.0.0.1/v1/winners",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.0.0.1/v1/winners",
        "https://localhost/v1/winners",
        "https://metadata.google.internal/computeMetadata/v1/",
    ):
        with pytest.raises(ValueError):
            HttpThirdPartyLinkedInProvider(endpoint_url=bad_url, api_key="secret")
