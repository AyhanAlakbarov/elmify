"""Tavily: name-to-site resolution, and the local-language leg."""

from typing import Any

import pytest

from apps.research.providers import SearchRequest
from apps.research.providers.tavily import TavilyProvider


class _Recorder:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return self.response


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {
        "query": "burs veren vakıflar",
        "country_code": "TR",
        "language": "tr",
    }
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_no_language_and_no_filter_by_language_are_sent() -> None:
    """-1.0 point on the German key, -2.3 with filter_by_language, harmful in
    three of four countries. The local language goes in the query text."""
    post = _Recorder({"results": [{"url": "https://vgm.gov.tr/"}]})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    payload = post.calls[0]["payload"]
    assert "language" not in payload
    assert "filter_by_language" not in payload
    assert "country" not in payload


def test_basic_depth_is_sent_not_advanced() -> None:
    """Advanced costs 2 credits against 1 and measured 5x WORSE at resolution
    (spec 4.13a: basic 10/30, advanced 2/30, advanced returning the Wikipedia
    article instead of the foundation's own site). Depth for the discovery leg
    is unmeasured, so basic is the default there too: the cost is certain and
    the benefit is not."""
    post = _Recorder({"results": []})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    assert post.calls[0]["payload"]["max_results"] == 15
    assert post.calls[0]["payload"]["search_depth"] == "basic"


def test_the_denylist_is_sent() -> None:
    post = _Recorder({"results": []})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    assert "mastersportal.com" in post.calls[0]["payload"]["exclude_domains"]


def test_the_denylist_is_cut_to_tavilys_cap() -> None:
    """Over 150 domains Tavily rejects the call, and every sweep with it."""
    post = _Recorder({"results": []})
    list(TavilyProvider(api_key="k", post=post).search(_request()))
    TavilyProvider(api_key="k", post=post).candidates("Stiftung")
    assert all(len(call["payload"]["exclude_domains"]) <= 150 for call in post.calls)


def test_only_urls_are_returned() -> None:
    post = _Recorder(
        {"results": [{"url": "https://vgm.gov.tr/", "content": "snippet", "score": 1}]}
    )
    assert list(TavilyProvider(api_key="k", post=post).search(_request())) == [
        "https://vgm.gov.tr/"
    ]


def test_candidates_returns_the_top_ten_urls_and_chooses_none_of_them() -> None:
    """Spec 4.13a: the right site was in the top 10 for 22 of 25 names and at
    rank 1 for 3. Selection is a lexical match done beside the register writer;
    the adapter's only job is to hand back the ten, in rank order, as URLs."""
    post = _Recorder(
        {"results": [{"url": f"https://r{i}.example/", "score": 1} for i in range(10)]}
    )
    urls = TavilyProvider(api_key="k", post=post).candidates("Türk Eğitim Vakfı")
    assert urls == [f"https://r{i}.example/" for i in range(10)]
    payload = post.calls[0]["payload"]
    assert payload["query"] == '"Türk Eğitim Vakfı"'
    assert payload["max_results"] == 10
    assert payload["search_depth"] == "basic"
    assert "exact_match" not in payload  # measured neutral (6/25 either way)
    assert "mastersportal.com" in payload["exclude_domains"]


def test_candidates_is_empty_when_nothing_matches() -> None:
    post = _Recorder({"results": []})
    assert TavilyProvider(api_key="k", post=post).candidates("No Such Foundation") == []


def test_the_name_lookup_never_returns_an_aggregator() -> None:
    """The guard lives in the lookup, so the resolver and any later caller
    inherit it: Tavily may ignore the exclusion list, and it is cut to 150."""
    post = _Recorder({"results": [
        {"url": "https://www.scholars4dev.com/hrant-dink"},
        {"url": "https://www.studyinnl.org/x"},
        {"url": "https://hrantdink.org/"},
    ]})
    assert TavilyProvider(api_key="k", post=post).candidates("Hrant Dink Vakfı") == [
        "https://hrantdink.org/"
    ]


def test_each_call_is_charged_one_credit() -> None:
    from apps.research.providers import SearchMeter
    from apps.research.providers.tavily import TAVILY_CREDIT_USD

    meter = SearchMeter()
    post = _Recorder({"results": []})
    list(TavilyProvider(api_key="k", post=post).search(_request(), meter=meter))
    assert meter.spent_usd == {"tavily": TAVILY_CREDIT_USD}


def test_a_cut_denylist_is_logged_by_name_once(caplog: pytest.LogCaptureFixture) -> None:
    from apps.research.domains import AGGREGATOR_DOMAINS
    from apps.research.providers import tavily

    tavily._log_cut.cache_clear()
    post = _Recorder({"results": []})
    with caplog.at_level("INFO", logger="apps.research.providers.tavily"):
        TavilyProvider(api_key="k", post=post).candidates("Stiftung")
        TavilyProvider(api_key="k", post=post).candidates("Vakıf")
    assert caplog.text.count("excluded domains not sent (cap 150)") == 1
    assert AGGREGATOR_DOMAINS[-1] in caplog.text
