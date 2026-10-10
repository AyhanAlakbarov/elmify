import pytest

from apps.research.providers.base import ProviderUnavailable, SiteSearchResult
from apps.research.providers.exa import EXA_SEARCH_URL, exa_site_search
from apps.research.providers.tavily import TAVILY_CREDIT_USD, tavily_site_search


def _post(reply, sent):
    def post(url, *, payload, headers):
        sent.append({"url": url, "payload": payload, "headers": headers})
        if isinstance(reply, Exception):
            raise reply
        return reply
    return post


def test_exa_restricts_to_the_domain_and_its_subdomains_with_no_contents():
    sent = []
    reply = {
        "results": [
            {"url": "https://www.tum.de/robotics", "title": "t"},
            {"url": "https://ai.tum.de/x"},
        ],
        "costDollars": {"total": 0.007},
    }
    result = exa_site_search(
        query="legged locomotion", domain="tum.de", api_key="k", post=_post(reply, sent)
    )
    assert result == SiteSearchResult(
        urls=("https://www.tum.de/robotics", "https://ai.tum.de/x"),
        cost_usd=0.007,
        provider="exa",
    )
    call = sent[0]
    assert call["url"] == EXA_SEARCH_URL == "https://api.exa.ai/search"
    assert call["headers"] == {"x-api-key": "k"}
    assert call["payload"] == {
        "query": "legged locomotion", "type": "auto", "numResults": 5,
        "includeDomains": ["tum.de", "*.tum.de"],
    }
    assert "contents" not in call["payload"]


def test_exa_drops_a_hit_off_the_domain():
    reply = {"results": [{"url": "https://evil.example/tum.de"}], "costDollars": {"total": 0.007}}
    result = exa_site_search(query="q", domain="tum.de", api_key="k", post=_post(reply, []))
    assert result.urls == () and result.cost_usd == 0.007


def test_exa_transport_failure_is_provider_unavailable():
    with pytest.raises(ProviderUnavailable):
        exa_site_search(
            query="q", domain="tum.de", api_key="k", post=_post(RuntimeError("503"), [])
        )


def test_exa_without_a_key_is_provider_unavailable(settings):
    settings.EXA_API_KEY = ""
    with pytest.raises(ProviderUnavailable):
        exa_site_search(query="q", domain="tum.de", post=_post({}, []))


def test_tavily_transport_failure_is_provider_unavailable():
    with pytest.raises(ProviderUnavailable):
        tavily_site_search(
            query="q", domain="tum.de", api_key="k", post=_post(RuntimeError("503"), [])
        )


def test_tavily_uses_basic_depth_and_include_domains_and_bills_one_credit():
    sent = []
    reply = {"results": [{"url": "https://www.tum.de/robotics"}]}
    result = tavily_site_search(
        query="legged locomotion", domain="tum.de", api_key="k", post=_post(reply, sent)
    )
    assert result == SiteSearchResult(
        urls=("https://www.tum.de/robotics",), cost_usd=TAVILY_CREDIT_USD, provider="tavily"
    )
    assert sent[0]["headers"] == {"Authorization": "Bearer k"}
    assert sent[0]["payload"] == {
        "query": "legged locomotion", "search_depth": "basic", "max_results": 5,
        "include_domains": ["tum.de"],
    }
    assert "language" not in sent[0]["payload"] and "filter_by_language" not in sent[0]["payload"]


def test_brave_site_search_asks_one_page_and_reports_its_list_price(settings):
    from apps.research.providers.brave import brave_site_search

    settings.BRAVE_USD_PER_REQUEST = 0.005
    seen = {}

    def get(url, *, params, headers):
        seen.update(params)
        return {"web": {"results": [{"url": "https://f.example/2027-call"},
                                    {"url": "https://aggregator.example/f"}]}}

    result = brave_site_search(query="Example Fellowship 2027", domain="f.example",
                               api_key="k", get=get)
    assert seen["q"] == "site:f.example Example Fellowship 2027" and seen["count"] == 10
    assert result.urls == ("https://f.example/2027-call",)  # off-domain dropped
    assert result.cost_usd == 0.005 and result.provider == "brave"
