from collections.abc import Iterable, Iterator

import pytest

from apps.research.discovery import (
    DiscoveryQuery,
    LeadBudgetExceeded,
    LeadIdentity,
    ResearchLead,
    collect_leads,
)
from apps.research.egress import SourceBlocked


class FixedSource:
    """A LeadSource that yields recorded URLs and counts how far it was consumed."""

    one_programme_per_link = False
    awards_jointly = False

    def __init__(self, name: str, urls: Iterable[str]) -> None:
        self.name = name
        self._urls = tuple(urls)
        self.yielded = 0

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        for url in self._urls:
            self.yielded += 1
            yield ResearchLead.from_url(url, source_type="PROGRAM", funding_family="")


QUERY = DiscoveryQuery(field="robotics", country_code="DE", max_leads=3)


def test_every_lead_records_the_technique_that_produced_it() -> None:
    source = FixedSource("seed:daad-ip", ["https://a.example/one"])

    leads = collect_leads([source], QUERY)

    assert [lead.discovered_by for lead in leads] == ["seed:daad-ip"]


def test_a_source_that_sets_its_own_lineage_keeps_it() -> None:
    class Tagged(FixedSource):
        def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
            yield ResearchLead.from_url(
                "https://a.example/one",
                source_type="PROGRAM",
                funding_family="",
                discovered_by="entity-expansion",
            )

    leads = collect_leads([Tagged("search", [])], QUERY)

    assert leads[0].discovered_by == "entity-expansion"


def test_sources_are_interleaved_so_the_cap_cannot_starve_a_later_source() -> None:
    first = FixedSource("first", [f"https://a.example/{index}" for index in range(10)])
    second = FixedSource("second", ["https://b.example/only"])

    leads = collect_leads([first, second], QUERY)

    assert [lead.canonical_url for lead in leads] == [
        "https://a.example/0",
        "https://b.example/only",
        "https://a.example/1",
    ]
    # Lazy: the cap stops consumption instead of draining every source first.
    assert first.yielded == 2


def test_a_vouching_source_stamps_its_leads() -> None:
    class Vouching(FixedSource):
        one_programme_per_link = True

    leads = collect_leads([Vouching("seed:eacea", ["https://a.example/one"])], QUERY)

    assert leads[0].one_programme_per_site is True


def test_a_source_that_does_not_vouch_leaves_its_leads_unpoolable() -> None:
    leads = collect_leads([FixedSource("search", ["https://a.example/one"])], QUERY)

    assert leads[0].one_programme_per_site is False


def test_a_lead_that_lands_on_a_catalogue_cannot_be_pooled() -> None:
    # A catalogue page is not one programme's site whatever the source promised,
    # and it cannot support a claim either -- the two must not disagree.
    lead = ResearchLead.from_url(
        "https://www.mastersportal.com/studies/1234",
        source_type="PROGRAM",
        funding_family="MULTILATERAL",
        one_programme_per_site=True,
    )

    assert lead.source_type == "AGGREGATOR"
    assert lead.can_support_claim is False
    assert lead.one_programme_per_site is False


def test_duplicate_urls_across_sources_collapse_to_the_first() -> None:
    first = FixedSource("first", ["https://a.example/same#overview"])
    second = FixedSource("second", ["https://a.example/same"])

    leads = collect_leads([first, second], QUERY)

    assert [lead.discovered_by for lead in leads] == ["first"]


def test_a_catalogue_host_is_an_aggregator_whoever_produced_the_lead() -> None:
    """The hole this closes: a search hit on DAAD must not become evidence.

    SearchSource asks for PROGRAM. The host decides otherwise.
    """
    search_hit = ResearchLead.from_url(
        "https://www2.daad.de/deutschland/studienangebote/international-programmes/en/detail/9894/",
        source_type="PROGRAM",
        funding_family="",
        discovered_by="search",
    )

    assert search_hit.source_type == "AGGREGATOR"
    assert search_hit.can_support_claim is False
    assert search_hit.can_route_research is True

    university_page = ResearchLead.from_url(
        "https://www.utn.de/en/study/ai-robotics-en",
        source_type="PROGRAM",
        funding_family="",
        discovered_by="search",
    )

    assert university_page.source_type == "PROGRAM"
    assert university_page.can_support_claim is True


@pytest.mark.parametrize(
    "error", [LeadBudgetExceeded("search budget exhausted"), SourceBlocked("HTTP 503")]
)
def test_a_failing_source_drops_out_without_killing_the_run(error: Exception) -> None:
    class Broke:
        name = "search"

        def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
            raise error
            yield  # pragma: no cover - generator marker

    degraded: list[str] = []
    seed = FixedSource("seed:daad-ip", ["https://a.example/one"])

    leads = collect_leads([seed, Broke()], QUERY, on_degraded=degraded.append)

    assert [lead.canonical_url for lead in leads] == ["https://a.example/one"]
    assert degraded == ["search"]


def test_identity_survives_from_url_and_carries_no_claims() -> None:
    identity = LeadIdentity(
        institution_name="University of Technology Nuremberg",
        country_code="DE",
        city="Nürnberg",
        program_name="AI & Robotics (MSc)",
    )

    lead = ResearchLead.from_url(
        "https://www2.daad.de/detail/9894/",
        source_type="AGGREGATOR",
        funding_family="",
        identity=identity,
    )

    assert lead.identity == identity
    assert not hasattr(identity, "teaching_languages")
    assert not hasattr(identity, "duration_months")
