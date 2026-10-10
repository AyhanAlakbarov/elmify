import pytest

from apps.research.discovery import (
    ResearchLead,
    canonicalize_url,
    catalog_key,
    location_key,
    normalize_teaching_languages,
    retrieve_official_source,
)
from apps.research.fetch.types import FetchedPage


def test_aggregator_lead_routes_research_but_cannot_support_claims() -> None:
    lead = ResearchLead.from_url(
        "https://aggregator.example/program",
        source_type="AGGREGATOR",
        funding_family="UNIVERSITY_WIDE",
    )

    assert lead.can_route_research is True
    assert lead.can_support_claim is False


def test_ecosystem_clue_routes_research_but_stays_internal() -> None:
    lead = ResearchLead.from_url(
        "https://research.example/ecosystem",
        source_type="RESEARCH_ORGANIZATION",
        funding_family="RESEARCH_ECOSYSTEM_PATHWAY",
        evidence_strength="ECOSYSTEM_CLUE",
    )

    assert lead.can_route_research is True
    assert lead.can_support_claim is False
    assert lead.visibility == "INTERNAL"


def test_catalog_language_normalization_preserves_first_display_spelling() -> None:
    assert normalize_teaching_languages([" English ", "english", "Deutsch"]) == (
        "English",
        "Deutsch",
    )


def test_catalog_keys_are_stable_and_source_namespaced() -> None:
    assert catalog_key(" university ", " MSc Chemistry ") == "university:msc chemistry"
    assert location_key(country_code="DE", city=" Berlin ") == "de:berlin"


@pytest.mark.django_db  # the seam reads MovedPage and HostProfile.retired_at first
def test_retrieve_official_source_goes_to_the_vendor_path() -> None:
    """One seam, so the six callers that already pass `retrieve=` keep working
    unchanged -- reader.py, program_rules.py, pipeline.py, seeds.py, services.py,
    registers.py."""
    called = {}

    def fake_fetch(url: str, **kwargs: object) -> FetchedPage:
        called["url"] = url
        return FetchedPage(
            final_url=url, redirects=(), content_type="text/markdown",
            body=b"# page", fetched_via="FIRECRAWL", cost_credits=1,
        )

    page = retrieve_official_source("https://example.test/a", fetch=fake_fetch)

    assert called["url"] == "https://example.test/a"
    assert page.fetched_via == "FIRECRAWL"


def test_retrieve_official_source_requires_https() -> None:
    """canonicalize_url runs before the vendor is ever called -- an http:// lead
    must not spend a credit finding that out."""

    def must_not_be_called(_url: str, **_kwargs: object) -> FetchedPage:
        raise AssertionError("fetch should not run for a rejected URL")

    with pytest.raises(ValueError):
        retrieve_official_source(
            "http://official.example/program", fetch=must_not_be_called
        )


def test_canonicalize_url_strips_credentials_from_the_host() -> None:
    """A URL is an identity here, not just a string.

    `urlsplit().hostname` drops userinfo, so a same-host check passes for
    `https://evil@vouched.host/x` while the canonical URL kept the `evil@`
    intact. The fetch is refused by validate_public_url either way, but the
    retained string is written to ConsultantResearchTask.url and read by a
    consultant, where credentials-in-a-URL is the oldest deceptive-link trick
    there is. Strip it at the one place every caller routes through.
    """
    assert canonicalize_url("https://evil@example.org/a") == "https://example.org/a"
    assert canonicalize_url("https://user:pass@example.org/a") == "https://example.org/a"


def test_canonicalize_url_keeps_the_port_and_ipv6_brackets() -> None:
    """Stripping credentials must not eat the rest of the authority."""
    assert canonicalize_url("https://example.org:8443/a") == "https://example.org:8443/a"
    assert canonicalize_url("https://u@example.org:8443/a") == "https://example.org:8443/a"
    assert canonicalize_url("https://[2606:4700::1111]/a") == "https://[2606:4700::1111]/a"


def test_canonicalize_url_still_lowercases_and_refuses_a_hostless_url() -> None:
    assert canonicalize_url("https://EXAMPLE.org/A") == "https://example.org/A"
    with pytest.raises(ValueError):
        canonicalize_url("https://@/a")
