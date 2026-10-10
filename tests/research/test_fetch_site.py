import json

import pytest

from apps.research.fetch import site as fetch_site
from apps.research.fetch.site import (
    AGENT_KINDS,
    AGENT_SCHEMA,
    EXCLUDE_PATHS,
    FirecrawlSiteError,
    agent,
    crawl,
    crawl_ceiling,
    map_site,
)


def _post(responses):
    """A scripted Firecrawl transport. Records every request body."""
    sent = []

    def post(url, body, headers):
        sent.append((url, json.loads(body)))
        # Repeats the last scripted response past the end of the list: a
        # vendor 5xx retried by `_call` calls `post` more times than one
        # response covers, and a persistently-failing vendor is the case
        # under test here, not an exhausted fixture.
        return responses[min(len(sent) - 1, len(responses) - 1)]

    post.sent = sent
    return post


def _ok(links):
    payload = {"success": True, "links": [{"url": u} for u in links]}
    return 200, json.dumps(payload).encode(), {}


def test_a_filtered_map_returns_urls_and_costs_one_credit():
    post = _post([_ok(["https://uni.example.org/apply/documents/"])])

    result = map_site(
        "https://uni.example.org/msc-ai/", api_key="k", search=("documents", "bewerbung"), post=post
    )

    assert result.urls == ("https://uni.example.org/apply/documents/",)
    assert result.credits == 1
    sent_url, sent_body = post.sent[0]
    assert sent_url.endswith("/v2/map")
    assert sent_body["search"] == "documents bewerbung"
    assert sent_body["includeSubdomains"] is True
    assert sent_body["ignoreQueryParameters"] is True
    assert sent_body["limit"] == 500


def test_an_empty_filtered_map_falls_back_to_the_unfiltered_one():
    """Measured 2026-09-15: the `search` filter returned zero for a site the
    unfiltered call mapped at 76. Without the fallback that site is a
    programme with no pages -- which is not a fact about the site."""
    post = _post([_ok([]), _ok(["https://uni.example.org/a/", "https://uni.example.org/b/"])])

    result = map_site("https://uni.example.org/", api_key="k", search=("documents",), post=post)

    assert len(result.urls) == 2
    assert result.credits == 2, "1 credit per call whatever it returns"
    assert "search" not in post.sent[1]


def test_the_unfiltered_call_is_not_made_when_no_filter_was_asked_for():
    """Otherwise a genuinely empty site costs two credits to learn it is empty
    -- and every host in a sweep pays it."""
    post = _post([_ok([])])

    result = map_site("https://uni.example.org/", api_key="k", post=post)

    assert result.urls == ()
    assert result.credits == 1
    assert len(post.sent) == 1


def test_ignore_cache_is_sent_only_when_asked():
    """Firecrawl caches sitemaps for seven days. At the start of a cycle that
    cache is last cycle's site, so the first map of a cycle pays to bypass it;
    every map after that within the cycle must not, or the cache buys nothing."""
    post = _post([_ok(["https://uni.example.org/a/"])])
    map_site("https://uni.example.org/", api_key="k", ignore_cache=True, post=post)
    assert post.sent[0][1]["ignoreCache"] is True

    post = _post([_ok(["https://uni.example.org/a/"])])
    map_site("https://uni.example.org/", api_key="k", post=post)
    assert "ignoreCache" not in post.sent[0][1]


def test_a_missing_key_raises_rather_than_returning_nothing():
    """An absent key must never read as 'this site has no pages'. Same rule as
    both page providers: absent key -> raise at call time, never degrade."""
    with pytest.raises(FirecrawlSiteError, match="FIRECRAWL_API_KEY"):
        map_site("https://uni.example.org/", api_key="", post=_post([]))


def test_a_vendor_error_raises_and_names_the_status(monkeypatch):
    # map_site exposes no `sleep` param (it is not on this task's interface),
    # so the retry back-off inside `_call` is stubbed at the module level
    # instead of left to sleep in real time across three retries.
    monkeypatch.setattr(fetch_site.time, "sleep", lambda _seconds: None)
    post = _post([(500, b"upstream", {})])

    with pytest.raises(FirecrawlSiteError, match="500"):
        map_site("https://uni.example.org/", api_key="k", post=post)


def _crawl_transport(status_pages, errors, robots_blocked, *, states=("completed",)):
    """Scripted /crawl: one POST to start, N GETs for status, one GET for errors."""
    sent = {"post": [], "get": []}
    remaining = list(states)

    def post(url, body, headers):
        sent["post"].append((url, json.loads(body)))
        return 200, json.dumps({"success": True, "id": "job-1"}).encode(), {}

    def get(url, headers):
        sent["get"].append(url)
        if url.endswith("/errors"):
            payload = {"errors": errors, "robotsBlocked": robots_blocked}
            return 200, json.dumps(payload).encode(), {}
        state = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        payload = {
            "success": True, "status": state,
            "completed": len(status_pages), "total": len(status_pages),
            "data": status_pages,
        }
        return 200, json.dumps(payload).encode(), {}

    post.sent = sent["post"]
    get.sent = sent["get"]
    return post, get, sent


def test_the_errors_endpoint_is_called_on_every_crawl():
    """The status counters CANNOT report a failure: failed pages are excluded
    from both `completed` and `total`, so `completed == total` on every
    finished crawl. errors[] and robotsBlocked[] are the only record."""
    post, get, sent = _crawl_transport(
        [{"metadata": {"url": "https://uni.example.org/apply/", "statusCode": 200}}],
        [{"url": "https://uni.example.org/forms/", "error": "timeout"}],
        ["https://uni.example.org/private/"],
    )

    result = crawl(
        "https://uni.example.org/msc-ai/", api_key="k", limit=25, tag="2027",
        post=post, get=get, sleep=lambda _s: None,
    )

    assert any(url.endswith("/errors") for url in sent["get"])
    assert result.errors == ("https://uni.example.org/forms/",)
    assert result.robots_blocked == ("https://uni.example.org/private/",)
    assert result.urls == ("https://uni.example.org/apply/",)


def test_the_crawl_reaches_siblings_not_just_children():
    """crawlEntireDomain. The default follows children only, and a
    requirements page is usually a SIBLING of the programme page
    (/msc-ai/ and /application/documents/). Without it the crawl never
    reaches the most common location the 2026-09-15 site survey found."""
    post, get, _sent = _crawl_transport([], [], [])
    crawl("https://uni.example.org/msc-ai/", api_key="k", limit=25, tag="2027",
          post=post, get=get, sleep=lambda _s: None)

    body = _sent_body(post)
    assert body["crawlEntireDomain"] is True
    assert body["allowSubdomains"] is True
    assert body["allowExternalLinks"] is True
    assert body["maxDiscoveryDepth"] == 2
    assert body["sitemap"] == "include"
    assert body["ignoreQueryParameters"] is True
    assert body["limit"] == 25


def test_a_crawl_can_be_kept_off_other_hosts():
    """`allowExternalLinks` has Firecrawl itself fetch -- and bill -- any
    off-domain link whose path matches an include term; a year token makes
    `portal.other.example/2027/apply` qualify. A caller that must never point
    a vendor at a portal (CLAUDE.md) turns it off."""
    post, get, _sent = _crawl_transport([], [], [])
    crawl("https://uni.example.org/msc-ai/", api_key="k", limit=25, tag="2027",
          allow_external=False, post=post, get=get, sleep=lambda _s: None)

    assert _sent_body(post)["allowExternalLinks"] is False


def test_include_paths_is_one_short_pattern_per_term():
    """Firecrawl's own guidance: a long alternation is rejected or slow."""
    post, get, _sent = _crawl_transport([], [], [])
    crawl("https://uni.example.org/msc-ai/", api_key="k", limit=25, tag="2027",
          include_paths=("documents", "bewerbung"), post=post, get=get, sleep=lambda _s: None)

    body = _sent_body(post)
    assert body["includePaths"] == [".*documents.*", ".*bewerbung.*"]
    assert body["excludePaths"] == list(EXCLUDE_PATHS)


def test_the_scrape_options_are_rung_one_with_change_tracking():
    """Every crawled page is also a baseline for the monitor (spec 8). A
    crawl whose scrapeOptions differ from rung 1 produces pages the monitor
    then reports as `changed` on their first check, for nothing."""
    post, get, _sent = _crawl_transport([], [], [])
    crawl("https://uni.example.org/msc-ai/", api_key="k", limit=25, tag="2027",
          post=post, get=get, sleep=lambda _s: None)

    options = _sent_body(post)["scrapeOptions"]
    assert {"type": "changeTracking", "tag": "2027"} in options["formats"]
    assert "markdown" in options["formats"]
    assert options["onlyMainContent"] is False
    assert options["parsers"][0]["type"] == "pdf"


def test_a_page_the_site_answered_404_is_in_data_not_errors():
    """Firecrawl puts it in `data` with metadata.statusCode. Reading it as a
    page would archive a 404 body under the institution's provenance."""
    post, get, _sent = _crawl_transport(
        [
            {"metadata": {"url": "https://uni.example.org/gone/", "statusCode": 404}},
            {"metadata": {"url": "https://uni.example.org/apply/", "statusCode": 200}},
        ],
        [], [],
    )

    result = crawl("https://uni.example.org/", api_key="k", limit=25, tag="2027",
                   post=post, get=get, sleep=lambda _s: None)

    assert result.urls == ("https://uni.example.org/apply/",)
    assert result.dead == ("https://uni.example.org/gone/",)


def test_max_concurrency_is_one_for_a_corpus_run():
    """Firecrawl documents that crawl results vary between runs of the same
    configuration. A corpus score computed at 25 concurrent is a score of a
    configuration nobody can reproduce (spec 13)."""
    post, get, _sent = _crawl_transport([], [], [])
    crawl("https://uni.example.org/", api_key="k", limit=25, tag="2027",
          max_concurrency=1, post=post, get=get, sleep=lambda _s: None)

    assert _sent_body(post)["maxConcurrency"] == 1


def test_the_ceiling_is_the_worst_case_not_the_page_count(settings):
    """1 credit per page PLUS 1 per PDF page, so 25 pages of 60-page PDFs is
    1,525 credits, not 25. The sweep budget is checked against THIS before
    the job is submitted; Firecrawl's own pre-flight answers 402 for a limit
    the balance cannot cover, and a 402 mid-sweep is a bill nobody chose."""
    settings.FETCH_PDF_MAX_PAGES = 60

    assert crawl_ceiling(25) == 25 * 61


def _sent_body(post):
    return post.sent[0][1]


def test_max_credits_is_always_sent(settings):
    """The documented default is 2,500 credits a run -- about $2 a programme
    at Standard, roughly eighty times what this stage is meant to cost. This
    is the single most expensive omission available on this path."""
    settings.FETCH_AGENT_MAX_CREDITS = 300
    post = _post([(200, json.dumps({"success": True, "data": {"pages": []},
                                    "creditsUsed": 140}).encode(), {})])

    agent(api_key="k", urls=("https://uni.example.org/msc-ai/",), prompt="find it", post=post)

    body = post.sent[0][1]
    assert body["maxCredits"] == 300
    assert body["effort"] == "low"


def test_strict_constrain_is_never_sent():
    """Read from Firecrawl's own /agent page, 2026-09-23: it confines the run
    to EXACTLY the URLs given, which makes an agent whose job is to find
    pages useless. The 2026-09-22 text assumed it was the 'stay on the
    official site' setting; it is not, and there is none."""
    post = _post([(200, json.dumps({"success": True, "data": {"pages": []}}).encode(), {})])

    agent(api_key="k", urls=("https://uni.example.org/",), prompt="find it", post=post)

    assert "strictConstrainToURLs" not in post.sent[0][1]
    assert post.sent[0][1]["urls"] == ["https://uni.example.org/"]


def test_only_urls_and_a_kind_survive_the_answer():
    """Its answer is DISCARDED (spec 7.4). Firecrawl says the trace is 'not a
    page-by-page archive', so everything here is a lead to confirm, never a
    fact -- and the `why` never reaches a database column, only a log line."""
    payload = {
        "success": True,
        "creditsUsed": 210,
        "data": {
            "pages": [
                {"url": "https://uni.example.org/apply/documents/",
                 "kind": "documents_list", "why": "lists what to submit"},
                {"url": "https://uni.example.org/apply/documents/",
                 "kind": "faq", "why": "duplicate"},
                {"url": "", "kind": "other", "why": "empty"},
            ]
        },
    }
    post = _post([(200, json.dumps(payload).encode(), {})])

    result = agent(api_key="k", urls=("https://uni.example.org/",), prompt="find it", post=post)

    assert result.leads == (("https://uni.example.org/apply/documents/", "documents_list"),)
    assert result.credits == 210


def test_an_unknown_kind_becomes_other_rather_than_dropping_the_url():
    """The kind is the vendor's word and is never trusted; the URL is the
    only thing worth having. Dropping a lead because its label was not in our
    enum would throw away the one thing the call was paid for."""
    payload = {"success": True, "data": {"pages": [
        {"url": "https://uni.example.org/apply/", "kind": "admissions_hub", "why": "x"}]}}
    post = _post([(200, json.dumps(payload).encode(), {})])

    result = agent(api_key="k", urls=("https://uni.example.org/",), prompt="find it", post=post)

    assert result.leads == (("https://uni.example.org/apply/", "other"),)
    assert set(AGENT_KINDS) == {
        "documents_list", "cv_guideline", "letter_guideline", "template", "faq", "other"
    }


def test_the_schema_forbids_extra_properties():
    """The repo's LLM baseline: extra='forbid' on every schema. Here it also
    keeps the answer small, which is what Firecrawl bills on."""
    assert AGENT_SCHEMA["additionalProperties"] is False
    assert AGENT_SCHEMA["properties"]["pages"]["items"]["additionalProperties"] is False
