import socket
from dataclasses import replace
from uuid import UUID

import pytest
from django.core.cache import cache

from apps.research.discovery import DiscoveryQuery, LeadBudgetExceeded, RunBudget
from apps.research.domains import CATALOGUE_DOMAINS
from apps.research.egress import FetchResult, SourceBlocked, UnsafeTarget, fetch_json_api
from apps.research.search import (
    TAVILY_CRAWL_URL,
    TAVILY_EXTRACT_URL,
    TAVILY_SEARCH_URL,
    SearchSource,
    funding_links,
    tavily_crawl,
    tavily_extract,
)

QUERY = DiscoveryQuery(field="robotics", country_code="JP", max_leads=5)


class FakeResponse:
    def __init__(
        self, status: int = 200, headers: dict[str, str] | None = None, body: bytes = b"{}"
    ) -> None:
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self._body = body

    def read(self, amount: int, decode_content: bool = True) -> bytes:
        chunk, self._body = self._body[:amount], self._body[amount:]
        return chunk

    def release_conn(self) -> None:
        pass


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def test_json_api_posts_the_payload_and_returns_the_parsed_body(public_dns) -> None:
    calls: list[dict[str, object]] = []

    def transport(target, path, *, method="GET", body=None, extra_headers=None):
        calls.append({"host": target.host, "path": path, "method": method, "body": body,
                      "headers": extra_headers})
        return FakeResponse(body=b'{"results": [{"url": "https://i.kyoto-u.ac.jp/x"}]}')

    data = fetch_json_api(
        "https://api.exa.ai/search",
        payload={"query": "robotics"},
        headers={"x-api-key": "k"},
        transport=transport,
    )

    assert data == {"results": [{"url": "https://i.kyoto-u.ac.jp/x"}]}
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/search"
    assert calls[0]["body"] == b'{"query": "robotics"}'
    assert calls[0]["headers"]["x-api-key"] == "k"
    assert calls[0]["headers"]["Content-Type"] == "application/json"


def test_json_api_passes_a_read_timeout_only_when_asked(public_dns) -> None:
    calls: list[dict[str, object]] = []

    def transport(target, path, *, method="GET", body=None, extra_headers=None, **kw):
        calls.append(kw)
        return FakeResponse()

    fetch_json_api("https://api.exa.ai/search", payload={}, headers={}, transport=transport)
    assert calls[0] == {}

    fetch_json_api(
        "https://api.exa.ai/search",
        payload={},
        headers={},
        transport=transport,
        read_timeout=120.0,
    )
    assert calls[1] == {"read_timeout": 120.0}


def test_a_caller_cannot_override_the_validated_host_header(public_dns) -> None:
    """The Host header is pinned to the validated target, not to the caller.

    A caller-supplied "host" (or any other casing) must not survive as a
    second, distinct dict key either -- two Host headers on one HTTP/1.1
    request is a vhost-routing primitive (whole-branch review, Fix 6).
    """
    seen: dict[str, str] = {}

    def transport(target, path, *, method="GET", body=None, extra_headers=None):
        seen.update(extra_headers or {})
        return FakeResponse()

    fetch_json_api(
        "https://api.exa.ai/search",
        payload={},
        headers={"Host": "evil.example", "x-api-key": "k"},
        transport=transport,
    )

    assert seen["Host"] == "api.exa.ai"

    seen.clear()
    fetch_json_api(
        "https://api.exa.ai/search",
        payload={},
        headers={"host": "evil.example", "x-api-key": "k"},
        transport=transport,
    )

    assert seen["Host"] == "api.exa.ai"
    assert "host" not in seen


def test_json_api_refuses_plain_http_and_non_json_and_error_status(public_dns) -> None:
    with pytest.raises(UnsafeTarget):
        fetch_json_api("http://api.exa.ai/search", payload={}, headers={},
                       transport=lambda *a, **k: FakeResponse())
    with pytest.raises(SourceBlocked):
        fetch_json_api(
            "https://api.exa.ai/search",
            payload={},
            headers={},
            transport=lambda *a, **k: FakeResponse(headers={"Content-Type": "text/html"}),
        )
    with pytest.raises(SourceBlocked):
        fetch_json_api("https://api.exa.ai/search", payload={}, headers={},
                       transport=lambda *a, **k: FakeResponse(status=429))
    with pytest.raises(SourceBlocked):
        fetch_json_api("https://api.exa.ai/search", payload={}, headers={},
                       transport=lambda *a, **k: FakeResponse(status=302,
                                                              headers={"Location": "https://elsewhere.example"}))


def _fake_post(results: list[dict[str, str]], sent: list[dict[str, object]]):
    def post(url: str, *, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
        sent.append({"url": url, "payload": payload, "headers": headers})
        return {"results": results}

    return post


@pytest.mark.django_db
def test_search_results_become_leads_and_catalogue_hits_cannot_claim() -> None:
    cache.clear()
    sent: list[dict[str, object]] = []
    post = _fake_post(
        [
            {"url": "https://i.kyoto-u.ac.jp/programs/x"},
            {"url": "https://www.mastersportal.com/studies/1"},
            {"url": "https://www2.daad.de/detail/9894/"},
            {"url": "http://insecure.example/x"},
            {"url": ""},
        ],
        sent,
    )

    leads = list(SearchSource(api_key="k", post=post).find(QUERY))

    # mastersportal is dropped at the boundary; DAAD survives as a lead but as
    # an AGGREGATOR one -- it routes research and cannot support a claim.
    assert [lead.canonical_url for lead in leads] == [
        "https://i.kyoto-u.ac.jp/programs/x",
        "https://www2.daad.de/detail/9894",
    ]
    assert leads[0].can_support_claim is True
    assert leads[1].source_type == "AGGREGATOR"
    assert leads[1].can_support_claim is False
    assert leads[0].discovered_by == "search"
    assert sent[0]["url"] == TAVILY_SEARCH_URL
    assert set(sent[0]["payload"]["exclude_domains"]) == set(CATALOGUE_DOMAINS)
    assert "include_domains" not in sent[0]["payload"]
    assert sent[0]["headers"]["Authorization"] == "Bearer k"
    assert "robotics" in sent[0]["payload"]["query"]
    assert "Japan" in sent[0]["payload"]["query"]


@pytest.mark.django_db
def test_find_charges_the_one_metered_tavily_client() -> None:
    """SearchSource.find posted its own uncharged Tavily request (audit finding 3);
    it must now route through providers.tavily.TavilyProvider, the one metered
    client, so a search's dollar cost is recorded and its denylist is capped like
    every other caller's."""
    cache.clear()
    sent: list[dict[str, object]] = []
    post = _fake_post([{"url": "https://i.kyoto-u.ac.jp/programs/x"}], sent)

    source = SearchSource(api_key="k", post=post)
    leads = list(source.find(QUERY))

    assert leads[0].canonical_url == "https://i.kyoto-u.ac.jp/programs/x"
    assert source.meter.calls.get("tavily") == 1
    assert source.meter.total() > 0
    # Sent through TavilyProvider._exclusions, the same capping every other
    # caller of TavilyProvider gets -- under the cap here, so unsliced, but the
    # same code path, not a second uncapped list.
    assert set(sent[0]["payload"]["exclude_domains"]) == set(CATALOGUE_DOMAINS)
    assert len(sent[0]["payload"]["exclude_domains"]) <= 150


@pytest.mark.django_db
def test_the_per_run_budget_stops_the_source_even_with_a_cold_cache() -> None:
    cache.clear()
    sent: list[dict[str, object]] = []
    budget = RunBudget(searches=2)
    source = SearchSource(api_key="k", budget=budget, post=_fake_post([], sent))

    list(source.find(QUERY))
    list(source.find(QUERY))
    with pytest.raises(LeadBudgetExceeded):
        list(source.find(QUERY))

    assert len(sent) == 2


@pytest.mark.django_db
def test_the_hourly_limit_also_stops_the_source() -> None:
    cache.clear()
    sent: list[dict[str, object]] = []
    actor = UUID("00000000-0000-0000-0000-0000000000ff")
    source = SearchSource(api_key="k", actor_id=actor, calls_per_hour=1, post=_fake_post([], sent))

    list(source.find(QUERY))
    with pytest.raises(LeadBudgetExceeded):
        list(source.find(QUERY))


def test_the_api_key_is_not_in_the_repr() -> None:
    assert "sk-secret" not in repr(SearchSource(api_key="sk-secret"))


WOCC_HOME = b"""<html><body>
<a href="/">Accueil</a>
<a href="/candidature-et-admission/bourses-detudes">Bourses d'etudes</a>
<a href="/candidature-et-admission/cout-de-la-formation">Cout de la formation</a>
<a href="/candidature-et-admission/bourses-detudes">Bourses (again)</a>
<a href="/actualites">Actualites</a>
<a href="https://www.ucm.es/becas-admission">Partner scholarships</a>
<a href="http://www.master-wocc.eu/admission-http">Insecure</a>
</body></html>"""


def _page(final_url: str, body: bytes) -> FetchResult:
    return FetchResult(final_url, (), "text/html", body)


def test_funding_links_takes_the_hosts_own_funding_pages_once_each() -> None:
    links = funding_links(_page("https://www.master-wocc.eu/", WOCC_HOME))

    assert links == [
        "https://www.master-wocc.eu/candidature-et-admission/bourses-detudes",
        "https://www.master-wocc.eu/candidature-et-admission/cout-de-la-formation",
    ]


def test_funding_links_never_leaves_the_host_that_was_vouched_for() -> None:
    """A consortium page links to its partners; their provenance is not this one's."""
    links = funding_links(_page("https://www.master-wocc.eu/", WOCC_HOME))

    assert not any("ucm.es" in link for link in links)
    assert not any(link.startswith("http://") for link in links)


def test_funding_links_are_capped() -> None:
    body = b"<html><body>" + b"".join(
        f'<a href="/scholarship/{index}">S</a>'.encode() for index in range(20)
    ) + b"</body></html>"

    assert len(funding_links(_page("https://x.example/", body), limit=3)) == 3


def test_a_page_never_hops_onto_itself() -> None:
    body = b'<html><body><a href="/admission/">Admission</a></body></html>'

    assert funding_links(_page("https://x.example/admission", body)) == []


def test_json_api_gets_with_a_query_string_when_params_are_given(public_dns) -> None:
    """Brave's API is a GET. The GET path stays inside fetch_json_api so it
    keeps validate_public_url, the HTTPS-only rule, the pinned Host and the
    no-redirect rule -- a provider calling urllib3 directly would have none
    of them, which is the whole reason egress.py exists."""
    calls: list[dict[str, object]] = []

    def transport(target, path, *, method="GET", body=None, extra_headers=None):
        calls.append({"path": path, "method": method, "body": body, "headers": extra_headers})
        return FakeResponse(body=b'{"web": {"results": []}}')

    data = fetch_json_api(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": "Stiftung", "count": 20, "offset": 0},
        headers={"X-Subscription-Token": "k"},
        transport=transport,
    )

    assert data == {"web": {"results": []}}
    assert calls[0]["method"] == "GET"
    assert calls[0]["body"] is None
    assert calls[0]["path"] == "/res/v1/web/search?q=Stiftung&count=20&offset=0"
    assert calls[0]["headers"]["X-Subscription-Token"] == "k"
    # No JSON body, so no Content-Type claiming there is one.
    assert "Content-Type" not in calls[0]["headers"]


def test_json_api_refuses_both_a_payload_and_params(public_dns) -> None:
    """One request is either a POST body or a query string. Accepting both
    would leave which-one-wins to argument order."""
    with pytest.raises(ValueError, match="payload"):
        fetch_json_api(
            "https://api.exa.ai/search",
            payload={"a": 1},
            params={"b": 2},
            headers={},
            transport=lambda *a, **k: FakeResponse(),
        )
def test_extract_returns_markdown_keyed_by_the_url_that_was_asked_for() -> None:
    sent: list[dict[str, object]] = []

    def post(url, *, payload, headers, read_timeout=None):
        sent.append({
            "url": url, "payload": payload, "headers": headers, "read_timeout": read_timeout,
        })
        return {
            "results": [{"url": "https://x.example/apply/", "raw_content": "# Apply\n- CV"}],
            "failed_results": [{"url": "https://y.example/", "error": "403"}],
        }

    got = tavily_extract(["https://x.example/apply", "https://y.example/"], api_key="k", post=post)

    # Keyed as passed (no trailing slash) even though Tavily echoed one back.
    assert got == {"https://x.example/apply": "# Apply\n- CV"}
    assert sent == [{
        "url": TAVILY_EXTRACT_URL,
        "payload": {
            "urls": ["https://x.example/apply", "https://y.example/"],
            "extract_depth": "advanced",
            "format": "markdown",
        },
        "headers": {"Authorization": "Bearer k"},
        "read_timeout": 60.0,
    }]


def test_extract_chunks_twenty_urls_per_call_and_makes_no_call_for_none() -> None:
    calls: list[int] = []
    timeouts: list[float | None] = []

    def post(url, *, payload, headers, read_timeout=None):
        calls.append(len(payload["urls"]))
        timeouts.append(read_timeout)
        return {"results": [{"url": u, "raw_content": "x"} for u in payload["urls"]]}

    urls = [f"https://h.example/p{i}" for i in range(25)]
    assert len(tavily_extract(urls, api_key="k", post=post)) == 25
    assert calls == [20, 5]
    assert timeouts == [60.0, 60.0]

    def never(*_a, **_k):
        raise AssertionError("no call expected for an empty list")

    assert tavily_extract([], api_key="k", post=never) == {}


def test_crawl_returns_every_page_and_sends_the_instructions() -> None:
    sent: list[dict[str, object]] = []

    def post(url, *, payload, headers, read_timeout=None):
        sent.append({"url": url, "payload": payload, "read_timeout": read_timeout})
        return {"results": [
            {"url": "https://h.example/", "raw_content": "home"},
            {"url": "https://h.example/apply", "raw_content": "## Documents\n- CV"},
        ]}

    got = tavily_crawl(
        "https://h.example",
        api_key="k",
        instructions="find the CV rules",
        limit=7,
        post=post,
    )

    assert got == {"https://h.example/": "home", "https://h.example/apply": "## Documents\n- CV"}
    assert sent == [{
        "url": TAVILY_CRAWL_URL,
        "payload": {
            "url": "https://h.example",
            "instructions": "find the CV rules",
            "max_depth": 2,
            "limit": 7,
            "extract_depth": "advanced",
            "format": "markdown",
            "allow_external": False,
        },
        "read_timeout": 120.0,
    }]


@pytest.mark.django_db
def test_the_search_payload_stays_inside_tavilys_documented_result_ceiling() -> None:
    """20 is Tavily's documented maximum for `max_results`, and
    `DiscoveryQuery.max_leads` defaults to 50 -- so nothing may pass it through
    unclamped. The old cap was 25, i.e. over the limit on every call."""
    cache.clear()
    sent: list[dict[str, object]] = []
    source = SearchSource(api_key="k", post=_fake_post([], sent))

    list(source.find(replace(QUERY, max_leads=50)))

    assert sent[0]["payload"]["max_results"] == 20


def test_a_country_off_the_old_corridor_list_is_searched_by_name() -> None:
    source = SearchSource(api_key="k")
    query = DiscoveryQuery(field="robotics", country_code="NL", degree_level="MASTER")
    assert "Netherlands" in source.query_text(query)
