"""Exa: the primary index for the families no register covers."""

from typing import Any

from apps.research.providers import SearchRequest
from apps.research.providers.exa import ExaProvider

_RESPONSE: dict[str, Any] = {
    "results": [
        {"url": "https://www.zeit-stiftung.de/", "title": "ZEIT-Stiftung", "score": 0.4},
        {"url": "https://www.daad.de/en/", "title": "DAAD"},
    ],
    "costDollars": {"total": 0.097},
}


class _Recorder:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = response if response is not None else _RESPONSE

    def __call__(self, url: str, *, payload: dict[str, Any], headers: dict[str, str]) -> dict:
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        return self.response


def _request(**kwargs: Any) -> SearchRequest:
    defaults: dict[str, Any] = {
        "query": "Stiftung Stipendium",
        "country_code": "DE",
        "language": "de",
    }
    defaults.update(kwargs)
    return SearchRequest(**defaults)


def test_only_urls_are_returned() -> None:
    """Title and score are in the response and must not survive the adapter."""
    post = _Recorder()
    urls = list(ExaProvider(api_key="k", post=post).search(_request()))
    assert urls == ["https://www.zeit-stiftung.de/", "https://www.daad.de/en/"]


def test_the_page_voiced_depth_is_sent() -> None:
    post = _Recorder()
    list(ExaProvider(api_key="k", post=post).search(_request()))
    assert post.calls[0]["payload"]["numResults"] == 15


def test_no_category_and_no_include_text_are_sent() -> None:
    """Measured losses: category="company" -2.7 pts, includeText -0.8. The
    vendor's docs recommend the first; the measurement rejects it."""
    post = _Recorder()
    list(ExaProvider(api_key="k", post=post).search(_request()))
    payload = post.calls[0]["payload"]
    assert "category" not in payload
    assert "includeText" not in payload


def test_the_denylist_is_the_only_filter() -> None:
    post = _Recorder()
    list(ExaProvider(api_key="k", post=post).search(_request()))
    payload = post.calls[0]["payload"]
    assert "daad.de" in payload["excludeDomains"]
    assert payload["type"] == "auto"
    assert set(payload) == {"query", "type", "numResults", "excludeDomains"}


def test_the_api_key_travels_in_the_header_and_not_the_payload() -> None:
    post = _Recorder()
    list(ExaProvider(api_key="secret", post=post).search(_request()))
    assert post.calls[0]["headers"]["x-api-key"] == "secret"
    assert "secret" not in str(post.calls[0]["payload"])


def test_a_result_without_a_url_is_skipped_not_yielded_empty() -> None:
    post = _Recorder({"results": [{"title": "no url here"}, {"url": "https://ok.example/"}]})
    assert list(ExaProvider(api_key="k", post=post).search(_request())) == ["https://ok.example/"]


def test_an_empty_response_yields_nothing_and_does_not_raise() -> None:
    post = _Recorder({})
    assert list(ExaProvider(api_key="k", post=post).search(_request())) == []


def test_the_billed_cost_is_charged_to_the_meter() -> None:
    from apps.research.providers import SearchMeter

    meter = SearchMeter()
    list(ExaProvider(api_key="k", post=_Recorder()).search(_request(), meter=meter))
    assert meter.spent_usd == {"exa": 0.097}
    assert meter.calls == {"exa": 1}


def test_a_response_with_no_cost_charges_zero_and_still_counts_the_call() -> None:
    from apps.research.providers import SearchMeter

    meter = SearchMeter()
    list(ExaProvider(api_key="k", post=_Recorder({"results": []})).search(_request(), meter=meter))
    assert meter.spent_usd == {"exa": 0.0}
    assert meter.calls == {"exa": 1}
