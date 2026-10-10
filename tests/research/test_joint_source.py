from collections.abc import Iterator
from dataclasses import dataclass

from apps.research.discovery import DiscoveryQuery, ResearchLead, _tagged
from apps.research.seeds import EACEA_ERASMUS_MUNDUS

QUERY = DiscoveryQuery(field="robotics", country_code="DE", degree_level="MASTER")


@dataclass(frozen=True)
class _FakeSource:
    name: str
    one_programme_per_link: bool
    awards_jointly: bool

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        yield ResearchLead.from_url(
            "https://example.org/programme",
            source_type="PROGRAM",
            funding_family="MULTILATERAL",
        )


def test_a_lead_from_a_joint_awarding_source_is_marked_joint() -> None:
    source = _FakeSource("seed:fake", one_programme_per_link=True, awards_jointly=True)

    (lead,) = _tagged(source, QUERY, None)

    assert lead.awards_jointly is True


def test_a_registry_source_is_one_programme_per_link_but_not_joint() -> None:
    """The distinction Korea and Finland will need (pipeline.py:422): a registry
    promises one programme per link while listing single-provider programmes.
    Conflating the two flags marks every Korean programme joint."""
    source = _FakeSource("seed:registry", one_programme_per_link=True, awards_jointly=False)

    (lead,) = _tagged(source, QUERY, None)

    assert lead.one_programme_per_site is True
    assert lead.awards_jointly is False


def test_a_lead_cannot_promote_itself() -> None:
    source = _FakeSource("seed:fake", one_programme_per_link=False, awards_jointly=False)

    (lead,) = _tagged(source, QUERY, None)

    assert lead.awards_jointly is False


def test_the_eacea_seed_awards_jointly() -> None:
    """EACEA's listing is one row per Erasmus Mundus consortium, so every
    programme on it is jointly awarded."""
    assert EACEA_ERASMUS_MUNDUS.awards_jointly is True
