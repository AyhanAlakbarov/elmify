"""The contract every adapter meets: a request in, URLs out, nothing kept."""

from collections.abc import Iterable

import pytest

from apps.research.domains import AGGREGATOR_DOMAINS
from apps.research.providers import SearchMeter, SearchProvider, SearchRequest


class _Stub:
    name = "stub"

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterable[str]:
        return ["https://example.org/a"]


def test_a_stub_satisfies_the_protocol() -> None:
    provider: SearchProvider = _Stub()
    assert list(provider.search(SearchRequest(query="q", country_code="TR", language="tr"))) == [
        "https://example.org/a"
    ]


def test_a_request_carries_the_denylist_by_default() -> None:
    assert SearchRequest(query="q", country_code="TR", language="tr").denylist == AGGREGATOR_DOMAINS


def test_the_default_depth_is_the_page_voiced_one() -> None:
    """Decision 30: breadth, page-voiced -- 10-15 per angle, never one query
    at 100 ('never use numResults above 25 ... run more queries with different
    angles at n=10-15', Exa's own guidance)."""
    assert SearchRequest(query="q", country_code="TR", language="tr").max_results == 15


def test_a_request_is_frozen() -> None:
    request = SearchRequest(query="q", country_code="TR", language="tr")
    with pytest.raises(AttributeError):
        request.query = "other"  # type: ignore[misc]


def test_no_request_field_can_carry_a_student_fact() -> None:
    """Spec 8 / 10.5: queries are built from country, family and angle
    vocabulary only. `terms` is the same angle in Brave's keyword form."""
    assert set(SearchRequest.__dataclass_fields__) == {
        "query",
        "terms",
        "country_code",
        "language",
        "phrasing",
        "max_results",
        "denylist",
    }


def test_the_meter_totals_every_provider() -> None:
    meter = SearchMeter()
    meter.charge("exa", 0.012)
    meter.charge("brave", 0.005)
    meter.charge("brave", 0.005)
    assert meter.total() == pytest.approx(0.022)
    assert meter.calls == {"exa": 1, "brave": 2}
