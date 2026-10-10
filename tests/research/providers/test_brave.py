"""Brave: the independent second index, and the deepest per query."""

from typing import Any

import pytest

from apps.research.providers import SearchRequest
from apps.research.providers.brave import BraveProvider


class _Pages:
    """Returns `pages[offset]`, then empty -- the real shape of exhaustion."""

    def __init__(self, pages: list[list[str]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, params: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "params": params, "headers": headers})
        offset = int(params.get("offset", 0))
        urls = self.pages[offset] if offset < len(self.pages) else []
        return {"web": {"results": [{"url": u, "title": "t", "description": "d"} for u in urls]}}


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {
        "query": "Stiftung Stipendium",
        "country_code": "DE",
        "language": "de",
    }
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_it_pages_until_the_first_empty_results_array() -> None:
    """more_results_available is NOT in the response (measured 2026-09-18 on
    the paid plan), so an empty page is the only stop signal there is."""
    get = _Pages([["https://a.example/"], ["https://b.example/"], ["https://c.example/"]])
    urls = list(BraveProvider(api_key="k", get=get).search(_request()))
    assert urls == ["https://a.example/", "https://b.example/", "https://c.example/"]
    # Three pages plus the empty one that stopped it.
    assert [c["params"]["offset"] for c in get.calls] == [0, 1, 2, 3]


def test_it_stops_at_the_offset_ceiling_even_if_pages_keep_coming() -> None:
    """Brave's documented maximum offset is 9. A provider that kept answering
    must not turn one query into an unbounded spend."""
    get = _Pages([[f"https://x.example/{i}"] for i in range(20)])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    assert [c["params"]["offset"] for c in get.calls] == list(range(10))


def test_only_urls_are_returned() -> None:
    get = _Pages([["https://a.example/"]])
    assert list(BraveProvider(api_key="k", get=get).search(_request())) == ["https://a.example/"]


def test_no_country_and_no_search_lang_are_sent() -> None:
    """country measured -8 local funders in Indonesia; search_lang measurably
    inert (Jaccard 1.000, 0.985, 1.000, 1.000)."""
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    params = get.calls[0]["params"]
    assert "country" not in params
    assert "search_lang" not in params


def test_the_count_is_the_maximum_page_size() -> None:
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    assert get.calls[0]["params"]["count"] == 20
    assert get.calls[0]["params"]["result_filter"] == "web"


def test_the_goggle_is_sent_only_when_one_is_configured() -> None:
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request()))
    assert "goggles" not in get.calls[0]["params"]

    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="k", get=get, goggle_url="https://x/g.goggle").search(_request()))
    assert get.calls[0]["params"]["goggles"] == "https://x/g.goggle"


def test_the_key_travels_in_the_subscription_header() -> None:
    get = _Pages([["https://a.example/"]])
    list(BraveProvider(api_key="secret", get=get).search(_request()))
    assert get.calls[0]["headers"]["X-Subscription-Token"] == "secret"


def test_every_request_is_charged_at_the_list_rate() -> None:
    from apps.research.providers import SearchMeter
    from apps.research.providers.brave import BRAVE_REQUEST_USD

    meter = SearchMeter()
    get = _Pages([["https://a.example/"], ["https://b.example/"]])
    list(BraveProvider(api_key="k", get=get).search(_request(), meter=meter))
    # Three requests went out -- the empty third page is billed too.
    assert meter.calls == {"brave": 3}
    assert meter.spent_usd["brave"] == pytest.approx(3 * BRAVE_REQUEST_USD)


def test_the_keyword_form_is_sent_when_the_angle_has_one() -> None:
    get = _Pages([])
    list(BraveProvider(api_key="k", get=get).search(
        _request(query="Unsere Stiftung vergibt Stipendien", terms='intitle:stiftung "stipendium"')
    ))
    assert get.calls[0]["params"]["q"] == 'intitle:stiftung "stipendium"'


def test_the_sentence_is_sent_when_there_is_no_keyword_form() -> None:
    get = _Pages([])
    list(BraveProvider(api_key="k", get=get).search(_request(query="Stiftung Stipendium")))
    assert get.calls[0]["params"]["q"] == "Stiftung Stipendium"
