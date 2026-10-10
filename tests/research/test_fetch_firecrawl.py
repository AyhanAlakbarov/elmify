import json
import socket
from ipaddress import ip_address

import pytest
import urllib3

from apps.research.egress import MAX_RESPONSE_BYTES
from apps.research.fetch import firecrawl
from apps.research.fetch.types import Outcome, VendorUnavailable
from apps.research.harvest import anchors


@pytest.fixture(autouse=True)
def _resolve_test_hosts(monkeypatch):
    """`*.test` domains do not resolve in this sandbox (RFC 2606, no
    delegation) -- validate_public_url would raise UnsafeTarget on the bare
    NXDOMAIN before a test ever reaches the check it means to exercise. This
    stub is host-aware: a literal IP (the VPC/private-address tests) is
    returned unchanged, exactly like a real resolver would, so those tests
    still exercise the is_global refusal rather than being silently
    rerouted to a public address."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ip_address(host)
            address = host
        except ValueError:
            address = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _ok(**data):
    """A stubbed Firecrawl 200. `changeTracking` sits in `data`, beside
    markdown -- NOT in `metadata`. `html` is what this module reads for
    `body`, never `rawHtml` (CLAUDE.md, "Web fetching") -- rawHtml is still
    sent back by the vendor in these fixtures because it costs nothing to
    include and pins that the module does not accidentally start reading it."""
    body = {
        "success": True,
        "data": {
            "markdown": "# Requirements\n\nApplicants must submit a CV." * 40,
            "html": "<html><body>" + "<p>Applicants must submit a CV.</p>" * 200 + "</body></html>",
            "rawHtml": "<html><body>" + "<p>raw</p>" * 5 + "</body></html>",
            "links": ["https://example.test/apply"],
            "metadata": {"url": "https://example.test/a", "statusCode": 200,
                         "contentType": "text/html"},
            **data,
        },
    }

    def post(url, *, json_body, headers, timeout):
        return 200, json.dumps(body).encode(), {}

    return post


def test_a_good_scrape_is_fetched_at_one_credit():
    page = firecrawl.scrape("https://example.test/a", api_key="k", post=_ok())
    assert page.outcome is Outcome.FETCHED
    assert page.fetched_via == "FIRECRAWL"
    assert page.rung == 1
    assert page.cost_credits == 1
    assert page.markdown.startswith("# Requirements")


def test_the_body_is_html_because_four_consumers_parse_markup():
    """The defect this branch shipped with once: body was the vendor's
    markdown, and markdown has no <a href>. harvest.anchors (every
    HtmlCatalogue in seeds.py, and the aggregator hop in harvest.py),
    search._sitemap's ElementTree, reader.readable_text and
    harvest.content_digest all parse markup off `page.body` -- shipped once as
    markdown, this made every HtmlCatalogue yield zero leads in silence and
    left content_sha256 permanently empty, so the unchanged-page short-circuit
    never fired (CLAUDE.md, "Web fetching"). `rawHtml` must never be read
    either -- the `_ok()` fixture carries an unread `rawHtml` payload for
    exactly this purpose."""
    html = (
        '<html><body><nav><a href="/p/1">Programme</a></nav>'
        "<main><h1>Admission</h1>" + "<p>Applicants must submit a CV.</p>" * 60
        + "</main></body></html>"
    )
    page = firecrawl.scrape("https://example.test/a", api_key="k", post=_ok(html=html))

    assert page.content_type == "text/html"
    assert [anchor.href for anchor in anchors(page.body)] == ["/p/1"]
    assert b"raw" not in page.body


def test_the_request_asks_for_html_and_for_the_whole_page():
    """`html` is what this module reads for `body`, never `rawHtml`; and
    `onlyMainContent` stays False because anchor harvesting reads exactly the
    navigation links it would strip -- reader.readable_text does its own
    <main>/admission-section narrowing on the way to the model, so nothing
    downstream needs Firecrawl's own narrowing too."""
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    firecrawl.scrape("https://e.test/a", api_key="k", post=post)

    assert "html" in sent["formats"]
    assert sent["onlyMainContent"] is False
    # markdown stays in the request because changeTracking is only accepted
    # alongside it, not because anything reads it.
    assert "markdown" in sent["formats"]


def test_change_tracking_requires_markdown_and_carries_the_tag():
    """Firecrawl's own caveat: change tracking compares pages via their
    markdown, and the format must travel with it. Sent without markdown the
    comparison is silently unreliable."""
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000, "metadata": {"url": "https://e.test/a", "statusCode": 200,
                                                 "contentType": "text/html"},
            "changeTracking": {"changeStatus": "same"}}}).encode(), {}

    page = firecrawl.scrape("https://e.test/a", api_key="k", tag="2027", post=post)
    assert "markdown" in sent["formats"]
    tracking = next(f for f in sent["formats"] if isinstance(f, dict)
                    and f.get("type") == "changeTracking")
    assert tracking["tag"] == "2027"
    assert page.change_status == "same"


def test_an_unchanged_page_short_circuits_the_reader():
    """The single largest saving on the whole path: one free comparison against
    a $0.35 reader run."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k", tag="2027",
        post=_ok(changeTracking={"changeStatus": "same"}),
    )
    assert page.outcome is Outcome.UNCHANGED


def test_the_proxy_parameter_is_never_sent():
    """Deprecated; `auto` is the default and escalates to enhanced proxies on
    401/403/429 at no extra charge. Passing it pins us to yesterday's names."""
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    firecrawl.scrape("https://e.test/a", api_key="k", post=post)
    assert "proxy" not in sent
    assert "location" not in sent
    assert sent["skipTlsVerification"] is True
    assert sent["parsers"][0]["maxPages"] == 60
    assert sent["parsers"][0]["pageMarkers"] is True


def test_a_truncated_pdf_is_partial_and_says_how_much_it_read():
    """A PDF is billed per page, so the read is capped -- and a rule on page 61
    must be a bounded miss, never a silent one."""
    page = firecrawl.scrape(
        "https://e.test/handbook.pdf", api_key="k",
        post=_ok(metadata={"url": "https://e.test/handbook.pdf", "statusCode": 200,
                           "contentType": "application/pdf", "numPages": 60,
                           "totalPages": 200}),
    )
    assert page.outcome is Outcome.FETCHED_PARTIAL
    assert (page.page_count, page.total_pages) == (60, 200)
    assert page.cost_credits == 60


@pytest.mark.parametrize("status", [404, 410])
def test_a_dead_target_status_is_dead_and_still_costs_a_credit(status):
    """Firecrawl bills for a returned document even when the site said the
    page is gone, and a different proxy would not change the answer -- so the
    ladder stops. Restores the 410 case the review's Important #3 found
    dropped from the old file's {404, 410, 403, 401, 429, 503} parametrize."""
    page = firecrawl.scrape(
        "https://e.test/gone", api_key="k",
        post=_ok(markdown="Not found",
                 metadata={"url": "https://e.test/gone", "statusCode": status,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.DEAD
    assert page.cost_credits == 1
    assert page.reason == firecrawl.REASON_ORIGIN_STATUS.format(status=status)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_relayed_block_status_survives_the_enhanced_proxy_and_is_blocked(status):
    """401/403/429 are what survives Firecrawl's own basic->enhanced proxy
    escalation, so a different vendor is unlikely to fare better. Restores the
    401 and 429 cases dropped from the same parametrize (Important #3)."""
    page = firecrawl.scrape(
        "https://e.test/x", api_key="k",
        post=_ok(markdown="Forbidden",
                 metadata={"url": "https://e.test/x", "statusCode": status,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == firecrawl.REASON_ORIGIN_STATUS.format(status=status)


def test_a_hard_failure_returns_no_document_and_costs_nothing():
    """Measured 2026-09-19: 710 credits before and after a DNS failure. Trying
    this tier first is free when it loses."""
    def post(url, *, json_body, headers, timeout):
        return 200, json.dumps({"success": False, "error": "DNS resolution failed"}).encode(), {}

    page = firecrawl.scrape("https://nope.test/a", api_key="k", post=post)
    assert page.outcome is Outcome.UNREACHABLE
    assert page.cost_credits == 0


def test_a_dead_dns_name_names_the_reason_the_ladder_will_read():
    """No proxy resolves a name that does not exist -- Task 7's ladder must
    tell this apart from test_all_engines_failed below, and today `reason` is
    the only place that survives (review finding Important #4)."""
    payload = json.dumps(
        {"success": False, "code": firecrawl.REASON_DNS_RESOLUTION_ERROR, "error": "dns"}
    ).encode()

    page = firecrawl.scrape(
        "https://nope.test/a", api_key="k",
        post=lambda url, *, json_body, headers, timeout: (200, payload, {}),
    )
    assert page.outcome is Outcome.UNREACHABLE
    assert page.reason == firecrawl.REASON_DNS_RESOLUTION_ERROR


def test_all_engines_failed_names_the_reason_the_ladder_will_read():
    """That host beat proxy:auto -- exactly what the residue tier is for, and
    the opposite answer from a dead DNS name."""
    payload = json.dumps(
        {"success": False, "error": firecrawl.REASON_ALL_ENGINES_FAILED}
    ).encode()

    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=lambda url, *, json_body, headers, timeout: (200, payload, {}),
    )
    assert page.outcome is Outcome.UNREACHABLE
    assert page.reason == firecrawl.REASON_ALL_ENGINES_FAILED


def test_a_shell_is_unreadable_at_rung_one():
    """Spec §4 rung 2: rung 1 returning a SHELL is the one thing that earns
    `actions`. Fewer than 1,500 readable characters while the raw page is
    20 kB or more, read against `html`."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(markdown="short", html="<html><body>" + "x" * 20_000 + "</body></html>"),
    )
    assert page.outcome is Outcome.UNREADABLE
    assert page.rung == 1
    assert page.reason == firecrawl.REASON_SHELL


def test_a_target_five_hundred_is_blocked_too():
    """Grouped with 401/403/429: ambiguous enough that a different network may
    answer differently, so it keeps the rung rather than being dead on arrival
    like 404/410."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(metadata={"url": "https://e.test/a", "statusCode": 503,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.BLOCKED


def test_a_final_url_inside_the_vpc_is_invalid():
    """The vendor reports the final URL and it decides provenance. It arrives
    from the untrusted side exactly as X-Final-Url did."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(metadata={"url": "http://169.254.170.2/creds", "statusCode": 200,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.INVALID
    assert page.reason == firecrawl.REASON_FINAL_URL_UNSAFE


def test_a_final_url_carrying_userinfo_is_refused():
    """The direct replacement for the deleted browser tier's
    test_a_final_url_carrying_userinfo_is_refused (CLAUDE.md, "Web fetching":
    "X-Final-Url is validated now, and provenance depends on that"). Firecrawl's
    reported final url becomes OfficialSource.canonical_url exactly the way the
    browser task's X-Final-Url used to, so a credential-carrying URL there is
    the same provenance hole -- read by a human, not just a machine. No DNS
    stub needed: validate_public_url refuses on username/password before it
    ever resolves a host. Restores the old file's exception-based test as an
    Outcome.INVALID value (review finding Important #3): a private address is
    covered by test_a_final_url_inside_the_vpc_is_invalid above, but userinfo
    is a distinct branch of validate_public_url that nothing else here covers."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(metadata={"url": "https://evil@vouched.host/x", "statusCode": 200,
                           "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.INVALID
    assert page.reason == firecrawl.REASON_FINAL_URL_UNSAFE


def test_an_absent_final_url_is_a_failure_never_the_requested_url():
    """`metadata.get("url") or url` would degrade a missing final URL to "it
    did not move" -- which is exactly the claim require_same_origin then
    checks, so the off-site-redirect guard would pass on the one response that
    carries no evidence for it. Preserved from the module this task edits
    (PR #103); not in the brief's own list, dropped there by omission."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(metadata={"statusCode": 200, "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.INVALID
    assert page.reason == firecrawl.REASON_FINAL_URL_MISSING


def test_the_request_id_travels_so_a_concurrent_duplicate_is_refused():
    """Measured 2026-09-22: a SEQUENTIAL reuse of the same x-request-id after
    the first call completed was charged again (678 -> 677 credits). The id
    protects against a concurrent duplicate only -- Firecrawl answers 409
    request_in_flight -- so a retry after a client-side timeout must NOT be
    re-issued against Firecrawl; the ladder falls through to rung 3 instead."""
    sent_headers = {}

    def post(url, *, json_body, headers, timeout):
        sent_headers.update(headers)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    firecrawl.scrape("https://e.test/a", api_key="k", request_id="abc-123", post=post)
    assert sent_headers["x-request-id"] == "abc-123"
    assert sent_headers["Authorization"] == "Bearer k"


def test_an_absent_key_raises_rather_than_degrading():
    def explode(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("called the vendor without a key")

    with pytest.raises(VendorUnavailable):
        firecrawl.scrape("https://e.test/a", api_key="", post=explode)


def test_an_image_is_served_through_the_vendors_ocr():
    """Measured 2026-09-22: eurotext.png -> 438 characters of markdown, 1
    credit. A requirements poster is an artifact like any other."""
    page = firecrawl.scrape(
        "https://e.test/duyuru.png", api_key="k",
        post=_ok(markdown="Başvuru için özgeçmiş (CV) İngilizce ve en fazla 2 sayfa olmalıdır.",
                 html="",
                 metadata={"url": "https://e.test/duyuru.png", "statusCode": 200,
                           "contentType": "image/png"}),
    )
    assert page.outcome is Outcome.FETCHED
    assert page.cost_credits == 1
    assert "özgeçmiş" in page.markdown


def test_rung_two_asks_for_actions_and_costs_more():
    sent = {}

    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return 200, json.dumps({"success": True, "data": {
            "markdown": "x" * 3000,
            "metadata": {"url": "https://e.test/a", "statusCode": 200,
                         "contentType": "text/html"}}}).encode(), {}

    page = firecrawl.scrape("https://e.test/a", api_key="k", actions=True, post=post)
    assert [a["type"] for a in sent["actions"]] == ["wait", "scroll", "wait"]
    assert page.rung == 2


# --- preserved from PR #103: a vendor's own failure never buys the residue
# tier. These stay exceptions (VendorUnavailable, `escalate`) because that is
# the axis fetch_page's ladder (a later task) switches on -- see CLAUDE.md and
# reconciliation item 5. -------------------------------------------------------


def _slept():
    waits: list[float] = []
    return waits, waits.append


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_throttle_or_a_vendor_5xx_is_retried_and_never_escalates(status):
    """Firecrawl's free tier is 10 requests/minute and a sweep paces per
    domain, so 58 distinct hosts go out at 30-60/minute: every 429 became a
    25-credit scrape.do call for a page Firecrawl would have served for 1 a
    minute later without this back-off."""
    calls = []
    waits, sleep = _slept()

    def post(url, *, json_body, headers, timeout):
        calls.append(1)
        return status, b"{}", {}

    with pytest.raises(VendorUnavailable) as error:
        firecrawl.scrape("https://e.test/a", api_key="k", post=post, sleep=sleep)

    assert len(calls) == 4, "one attempt plus egress._RETRY_ATTEMPTS retries"
    assert len(waits) == 3
    assert error.value.escalate is False
    assert "retry later" in str(error.value)


def test_a_retry_after_header_is_honoured_not_guessed():
    waits, sleep = _slept()

    with pytest.raises(VendorUnavailable):
        firecrawl.scrape(
            "https://e.test/a", api_key="k", sleep=sleep,
            post=lambda url, *, json_body, headers, timeout: (429, b"{}", {"Retry-After": "15"}),
        )

    assert waits == [15.0, 15.0, 15.0]


def test_a_throttle_that_clears_returns_the_page():
    answers = [(429, b"{}", {}), (429, b"{}", {})]
    waits, sleep = _slept()

    def post(url, *, json_body, headers, timeout):
        return answers.pop(0) if answers else _ok()(url, json_body=json_body, headers=headers,
                                                     timeout=timeout)

    page = firecrawl.scrape("https://e.test/a", api_key="k", post=post, sleep=sleep)
    assert page.fetched_via == "FIRECRAWL"
    assert len(waits) == 2


def test_a_transport_failure_is_retried_and_never_escalates():
    waits, sleep = _slept()

    def post(url, *, json_body, headers, timeout):
        raise urllib3.exceptions.ProtocolError("connection reset")

    with pytest.raises(VendorUnavailable) as error:
        firecrawl.scrape("https://e.test/a", api_key="k", post=post, sleep=sleep)

    assert error.value.escalate is False
    assert len(waits) == 3


def test_payment_required_raises_at_once_and_never_escalates():
    calls = []
    waits, sleep = _slept()

    def post(url, *, json_body, headers, timeout):
        calls.append(1)
        return 402, b"{}", {}

    with pytest.raises(VendorUnavailable) as error:
        firecrawl.scrape("https://e.test/a", api_key="k", post=post, sleep=sleep)

    assert len(calls) == 1 and waits == []
    assert error.value.escalate is False
    assert "credit balance" in str(error.value)


def test_firecrawls_own_timeout_still_earns_the_browser_rung():
    """408 is Firecrawl's clock, not the host's refusal: a residential browser
    is a different renderer and may finish."""
    with pytest.raises(VendorUnavailable) as error:
        firecrawl.scrape(
            "https://e.test/a", api_key="k",
            post=lambda url, *, json_body, headers, timeout: (408, b"{}", {}),
        )

    assert error.value.escalate is True


def test_a_non_json_body_is_firecrawl_malfunctioning_not_a_hard_host():
    with pytest.raises(VendorUnavailable) as error:
        firecrawl.scrape(
            "https://e.test/a", api_key="k",
            post=lambda url, *, json_body, headers, timeout: (200, b"<html>gateway</html>", {}),
        )

    assert error.value.escalate is False


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_an_outer_status_firecrawl_refuses_our_request_with_never_escalates(status):
    """A revoked or misconfigured key, a URL it will not take. A bad key hits
    every page of a sweep at once, so escalating here is 25 credits times the
    whole run. Restores the 400/403/404 cases dropped from the old file's
    {400, 401, 403, 404} parametrize (review finding Important #3) -- these are
    Firecrawl's OWN outer HTTP status refusing the request, never the target's,
    so a 404 here is distinct from a target 404 relayed inside a 200 envelope
    (test_a_dead_target_status_is_dead_and_still_costs_a_credit above)."""
    with pytest.raises(VendorUnavailable) as error:
        firecrawl.scrape(
            "https://e.test/a", api_key="k",
            post=lambda url, *, json_body, headers, timeout: (status, b"nope", {}),
        )

    assert error.value.escalate is False


def test_a_body_over_the_cap_is_refused():
    """Restores PR #103's cap test as a value: `usable()` carries the
    too-large refusal, on MAX_RESPONSE_BYTES -- the same ceiling our own
    egress client enforces, so the vendor path and ours cannot diverge."""
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k",
        post=_ok(html="<html>" + "x" * (MAX_RESPONSE_BYTES + 1) + "</html>"),
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "too_large"


def _recording(answer, sent):
    def post(url, *, json_body, headers, timeout):
        sent.update(json_body)
        return answer(url, json_body=json_body, headers=headers, timeout=timeout)

    return post


def test_a_json_read_rides_the_same_scrape_and_costs_four_more_credits():
    sent = {}
    page = firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_recording(_ok(json={"verdicts": []}), sent),
        json_format={"schema": {"type": "object"}, "prompt": "p"},
    )
    assert {"type": "json", "schema": {"type": "object"}, "prompt": "p"} in sent["formats"]
    assert "html" in sent["formats"]  # the judge still reads the same page's html
    assert page.cost_credits == 5
    assert page.json_extract == {"verdicts": []}


def test_no_json_format_asks_for_none_and_pays_for_none():
    sent = {}
    page = firecrawl.scrape("https://example.test/a", api_key="k", post=_recording(_ok(), sent))
    assert not any(isinstance(f, dict) and f.get("type") == "json" for f in sent["formats"])
    assert page.cost_credits == 1 and page.json_extract is None


def test_a_json_answer_nobody_asked_for_is_neither_kept_nor_billed():
    page = firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_ok(json={"verdicts": []})
    )
    assert page.cost_credits == 1 and page.json_extract is None


def test_an_asked_json_read_that_never_came_back_is_not_billed():
    page = firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_ok(),
        json_format={"schema": {"type": "object"}, "prompt": "p"},
    )
    assert page.cost_credits == 1 and page.json_extract is None


def test_the_default_request_is_unchanged_and_json_only_appends_one_format(settings):
    """The opt-in must not move a single field of the request every other
    caller sends: `html` stays the body's source and `onlyMainContent` stays
    False (CLAUDE.md, "Web fetching")."""
    default, with_json = {}, {}
    firecrawl.scrape("https://example.test/a", api_key="k", post=_recording(_ok(), default))
    firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_recording(_ok(), with_json),
        json_format={"schema": {"type": "object"}, "prompt": "p"},
    )
    assert default == {
        "url": "https://example.test/a",
        "formats": ["markdown", "links", "html"],
        "onlyMainContent": False,
        "blockAds": True,
        "skipTlsVerification": True,
        "removeBase64Images": True,
        "timeout": settings.FETCH_DEFAULT_TIMEOUT_MS,
        "parsers": [
            {"type": "pdf", "maxPages": settings.FETCH_PDF_MAX_PAGES, "pageMarkers": True}
        ],
    }
    assert json.dumps(default) == json.dumps(_default_body_via_none())
    extra = with_json.pop("formats")
    assert extra == [*default["formats"], {"type": "json", "schema": {"type": "object"},
                                            "prompt": "p"}]
    assert with_json == {k: v for k, v in default.items() if k != "formats"}


def _default_body_via_none():
    sent = {}
    firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_recording(_ok(), sent), json_format=None
    )
    return sent


_JSON = {"schema": {"type": "object"}, "prompt": "p"}


@pytest.mark.parametrize(("status", "outcome"), [(404, Outcome.DEAD), (403, Outcome.BLOCKED)])
def test_a_json_surcharge_on_a_dead_or_blocked_page_is_reported(status, outcome):
    """The json credits are billed before any status check, so a page that
    reads nothing still carried them -- and a first-read cost must see them."""
    page = firecrawl.scrape(
        "https://e.test/x", api_key="k", json_format=_JSON,
        post=_ok(markdown="Nope", json={"verdicts": []},
                 metadata={"url": "https://e.test/x", "statusCode": status,
                           "contentType": "text/html"}),
    )
    assert page.outcome is outcome
    assert page.json_credits == firecrawl.JSON_FORMAT_CREDITS
    assert page.cost_credits == 1 + firecrawl.JSON_FORMAT_CREDITS


def test_a_json_surcharge_on_an_invalid_final_url_is_reported():
    page = firecrawl.scrape(
        "https://e.test/a", api_key="k", json_format=_JSON,
        post=_ok(json={"verdicts": []}, metadata={"statusCode": 200, "contentType": "text/html"}),
    )
    assert page.outcome is Outcome.INVALID
    assert page.json_credits == firecrawl.JSON_FORMAT_CREDITS


def test_no_json_asked_or_none_returned_reports_no_json_credits():
    assert firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_ok(json={"verdicts": []})
    ).json_credits == 0
    assert firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_ok(), json_format=_JSON
    ).json_credits == 0
    served = firecrawl.scrape(
        "https://example.test/a", api_key="k", post=_ok(json={"verdicts": []}), json_format=_JSON
    )
    assert served.outcome is Outcome.FETCHED and served.json_credits == 4
