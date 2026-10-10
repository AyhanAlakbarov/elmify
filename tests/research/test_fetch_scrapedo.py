import socket

import pytest
import urllib3

from apps.research.egress import MAX_RESPONSE_BYTES
from apps.research.fetch import scrapedo
from apps.research.fetch.types import Outcome, VendorUnavailable
from apps.research.models import HostProfile


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def _ok(body=b"<html><body>" + b"x" * 1000 + b"</body></html>", cost="25", status=200,
        resolved="https://example.test/a", headers=None):
    base = urllib3.HTTPHeaderDict({"Scrape.do-Request-Cost": cost,
                                   "scrape.do-resolved-url": resolved})
    if headers:
        base.update(headers)
    return lambda url: (status, body, base)


def test_rung_three_is_the_default_and_asks_for_neither_render_nor_super(public_dns):
    """Rung 3 is the plain 1-credit call (spec 4.1b): render/super explicit
    false, never omitted, so a future default change on scrape.do's side
    cannot silently turn every rung-3 call into a 25-credit one."""
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict(
            {"scrape.do-resolved-url": "https://example.test/a"})

    page = scrapedo.scrape("https://example.test/a", api_key="k", get=get)

    assert "render=false" in seen["url"]
    assert "super=false" in seen["url"]
    assert page.rung == 3


def test_rung_four_asks_for_render_super_and_a_sticky_session(public_dns):
    """Rung 4 -- render+super -- is the residue tier scrape.do escalates to
    when the plain tier below could not pass (spec 4.1b). A residential
    address that changes between pages of one site re-triggers the very
    challenge this rung exists to pass, hence the sticky session."""
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict(
            {"scrape.do-resolved-url": "https://example.test/a"})

    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", rung=4, session_id=4242, get=get
    )

    assert "render=true" in seen["url"]
    assert "super=true" in seen["url"]
    assert "sessionId=4242" in seen["url"]
    assert page.rung == 4


def test_the_cost_header_is_recorded_not_the_tariff(public_dns):
    """scrape.do applies per-domain multipliers of 10-200 credits server-side with
    no request-time signal. The header is the only authority."""
    page = scrapedo.scrape("https://example.test/a", api_key="k", get=_ok(cost="200"))

    assert page.cost_credits == 200
    assert page.fetched_via == "SCRAPE_DO"
    assert page.outcome is Outcome.FETCHED


def test_a_thin_body_is_a_block_not_a_page(public_dns):
    """A block page returns HTTP 200 and charges. Measured: mischolarship.com came
    back 200 with 469 bytes of nothing, billed 1 credit. This used to raise
    ChargedFailure; Task 4 brings scrape.do to the value-returning contract
    firecrawl.py already has for a target failure -- BLOCKED is a value a
    caller reads, never an exception it must catch."""
    page = scrapedo.scrape("https://example.test/a", api_key="k", get=_ok(body=b"blocked"))

    assert page.outcome is Outcome.BLOCKED
    assert page.cost_credits == 25


def test_the_measured_469_byte_block_page_is_blocked(public_dns):
    """Measured 2026-09-19: mischolarship.com, HTTP 200, 469 bytes of nothing,
    billed 1 credit (CLAUDE.md, Web fetching)."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", get=_ok(body=b"x" * 469, cost="1")
    )

    assert page.outcome is Outcome.BLOCKED
    assert page.cost_credits == 1


def test_a_block_with_no_cost_header_is_billed_the_tariff_not_zero(public_dns):
    """An unreadable cost header is not evidence the call was free -- a charged
    status (2xx among them) floors at the rung's own tariff, never zero."""
    page = scrapedo.scrape("https://example.test/a", api_key="k", get=_ok(body=b"x", cost=""))

    assert page.outcome is Outcome.BLOCKED
    assert page.cost_credits == 1


@pytest.mark.parametrize("status", [401, 429, 502, 510])
def test_scrape_dos_own_failures_are_free_and_unreachable(public_dns, status):
    """Their published status-code table (read 2026-09-19): 401 no credits or
    suspended, 429 concurrency limit, 502 'please try again', 510 the client
    cancelled. None of them is billed. This used to raise VendorUnavailable;
    Task 4 brings scrape.do to the value-returning contract firecrawl.py
    already has -- UNREACHABLE is a value the caller reads, and it must not
    shrink the sweep budget (it costs nothing)."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k",
        get=_ok(body=b"x" * 1000, cost="0", status=status),
    )

    assert page.outcome is Outcome.UNREACHABLE
    assert page.cost_credits == 0


def test_a_four_oh_three_is_a_block_that_may_escalate(public_dns):
    """403 is the bot-wall signature passed through from the target -- exactly
    what a higher rung exists to try to pass (spec §4 rule 3)."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", get=_ok(status=403, body=b"forbidden")
    )

    assert page.outcome is Outcome.BLOCKED


def test_a_four_ten_is_dead(public_dns):
    """404 and 410 do not escalate -- scrape.do's published billing counts them
    as successful requests, so trying the next rung on a dead link costs
    1 + 25 credits for a page that does not exist."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", get=_ok(status=410, body=b"Gone")
    )

    assert page.outcome is Outcome.DEAD


def test_a_four_hundred_is_dead_charged_and_floored(public_dns):
    """scrape.do's published billing counts 400 as a SUCCESSFUL request
    alongside 2xx/404/410 (CLAUDE.md, Web fetching) -- a different proxy would
    not change the origin rejecting THIS request as malformed, so it gets the
    same non-escalating DEAD outcome as 404/410 (Important #4), and an
    absent/unreadable cost header floors at the tariff rather than recording
    a spend of 0 that SweepBudget cannot see."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", get=_ok(status=400, body=b"Bad Request", cost="")
    )

    assert page.outcome is Outcome.DEAD
    assert page.cost_credits == 1


@pytest.mark.parametrize("status", [500, 503, 504])
def test_a_target_five_xx_is_a_block_that_may_escalate(public_dns, status):
    """500/503/504 are not among scrape.do's own reserved codes (401, 429,
    502, 510), so they are necessarily the TARGET answering -- decision 5
    applies and this escalates, exactly like firecrawl.py's own
    `site_status >= 500` -> BLOCKED (Important #2a)."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", get=_ok(status=status, body=b"server error")
    )

    assert page.outcome is Outcome.BLOCKED


@pytest.mark.parametrize("status", [521, 522, 525])
def test_a_cloudflare_origin_down_five_xx_is_a_block_that_may_escalate(public_dns, status):
    """521 web server is down, 522 connection timed out, 525 SSL handshake
    failed -- Cloudflare's origin-down family, and precisely the bot-wall
    population the 25-credit residue rung exists for. An enumerated
    {500, 503, 504} set let them fall through to the `status != 200`
    catch-all as a NON-escalating UNREACHABLE, so those hosts never reached
    rung 4 -- while the comment above the set claimed it behaved "exactly like
    firecrawl.py's `site_status >= 500`", which escalates all of them."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", get=_ok(status=status, body=b"origin down")
    )

    assert page.outcome is Outcome.BLOCKED


def test_a_missing_key_raises_before_any_request():
    def explode(url):
        raise AssertionError("no request may be made without a key")

    with pytest.raises(VendorUnavailable) as excinfo:
        scrapedo.scrape("https://example.test/a", api_key="", get=explode)

    # Important #3: a bad key is about US, not the target -- the host was
    # never asked, so a sweep-wide bad key must not spend the 25-credit rung
    # on every page trying to escalate a question about our own credential.
    assert excinfo.value.escalate is False


def test_a_private_network_url_is_refused_before_any_request():
    """scrape.do reports no final url of its own -- scrapedo.scrape validates
    the url it is GIVEN and sets final_url to it (the asymmetry with firecrawl,
    whose vendor-reported final url is validated instead). A URL pointing
    inside the network must never reach the vendor at all: handing a metadata
    or VPC-internal address to a third party is a different failure from a
    vendor merely lying about where it landed. Mirrors the deleted browser
    tier's test_a_final_url_pointing_inside_the_network_is_refused
    (CLAUDE.md, Web fetching).

    A `get` that raises would not prove this on its own: `scrape`'s own
    `except Exception` around the request converts *any* exception from `get`
    into VendorUnavailable, so a raising stub passes whether or not the guard
    ran. A called-flag is the only signal that cannot be laundered that way.
    """
    called = False

    def get(url):
        nonlocal called
        called = True
        return 200, b"x" * 1000, urllib3.HTTPHeaderDict()

    with pytest.raises(VendorUnavailable) as excinfo:
        scrapedo.scrape("http://169.254.169.254/latest/meta-data/", api_key="k", get=get)

    assert called is False, "the vendor must never see a non-public url"
    # Important #3: a misconfigured requested URL is about US, not a target
    # that beat us -- never worth spending the residue rung on.
    assert excinfo.value.escalate is False


def test_a_url_carrying_userinfo_is_refused_before_any_request():
    """Same guard, the credentials-in-url case. No DNS stub needed:
    validate_public_url refuses on username/password before it ever resolves a
    host. Mirrors the deleted browser tier's
    test_a_final_url_carrying_userinfo_is_refused (CLAUDE.md, Web fetching).
    See test_a_private_network_url_is_refused_before_any_request for why a
    called-flag, not a raising stub, is the guard that cannot be laundered by
    scrape's own `except Exception` around the request."""
    called = False

    def get(url):
        nonlocal called
        called = True
        return 200, b"x" * 1000, urllib3.HTTPHeaderDict()

    with pytest.raises(VendorUnavailable):
        scrapedo.scrape("https://evil@vouched.host/x", api_key="k", get=get)

    assert called is False, "the vendor must never see a url carrying credentials"


def test_a_transport_failure_does_not_escalate(public_dns):
    """A dropped connection is about US, not the target -- the host was never
    asked, so escalating to the 25-credit rung answers a question nobody
    asked (Important #3, mirroring firecrawl.py's identical transport-failure
    handling)."""
    def explode(url):
        raise urllib3.exceptions.TimeoutError("connect timed out")

    with pytest.raises(VendorUnavailable) as excinfo:
        scrapedo.scrape("https://example.test/a", api_key="k", get=explode)

    assert excinfo.value.escalate is False


def test_a_profile_with_no_override_honours_the_setting(public_dns, settings):
    """`timeout_ms` is a per-host OVERRIDE, so its column default must be 0.

    Defaulted to 60_000, every host with a profile row -- i.e. every host after
    its first fetch -- always had a truthy `timeout_ms`, so
    `getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS`
    could never reach the setting and the operator's env override silently did
    nothing. A comment claimed the two "cannot diverge silently"; nothing
    pinned it. Unsaved on purpose: the claim is about the COLUMN's default.
    """
    settings.FETCH_DEFAULT_TIMEOUT_MS = 45_000
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict(
            {"scrape.do-resolved-url": "https://example.test/a"})

    profile = HostProfile(host="example.test")
    assert profile.timeout_ms == 0
    scrapedo.scrape("https://example.test/a", api_key="k", profile=profile, get=get)

    assert "timeout=45000" in seen["url"]


def test_lowercase_cost_header_is_read(public_dns):
    """HTTP/2 normalizes header names to lowercase. A real scrape.do response
    carries 'scrape.do-request-cost', not the 'Scrape.do-Request-Cost' of
    _ok()."""
    def get_lowercase(url):
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict({
            "scrape.do-request-cost": "175",
            "scrape.do-resolved-url": "https://example.test/a",
        })

    page = scrapedo.scrape("https://example.test/a", api_key="k", get=get_lowercase)
    assert page.cost_credits == 175


def test_body_just_under_threshold_is_blocked(public_dns):
    """Body size must be >= types.MIN_DOCUMENT_BYTES (1,000), the same floor
    firecrawl.py's usable() call enforces -- one shared number, not a second,
    looser one for this vendor (Important #5). One byte under is a soft
    block -- a value now, never a raised ChargedFailure."""
    page = scrapedo.scrape("https://example.test/a", api_key="k", get=_ok(body=b"x" * 999))

    assert page.outcome is Outcome.BLOCKED

def test_a_malformed_cost_header_degrades_to_the_tariff_not_to_zero(public_dns):
    """It must not crash -- and it must not degrade to free either. An
    unreadable header is no more evidence the call cost nothing than an absent
    one is; a rung-4 call was billed 25 whatever the header said."""
    page = scrapedo.scrape(
        "https://example.test/a",
        api_key="k",
        rung=4,
        get=_ok(cost="not-a-number"),
    )
    assert page.cost_credits == 25


def test_redirection_is_left_on_and_the_landed_url_is_read_back(public_dns):
    """Measured 2026-09-19 against https://globed.eu/how-to-apply/: the response
    carries `scrape.do-resolved-url` and `scrape.do-target-url`, headers the
    earlier fix wave assumed did not exist, and reports initial status 301 (a
    Cloudflare bounce landing on the identical URL). Redirection is left ON,
    one call, one credit for the whole chain -- disableRedirection plus a
    non-2xx refusal rejected a page that answers 200 to a direct request and
    was billed 25 credits for rejecting it. Reading the landed URL is what
    makes reader.require_same_origin a real comparison on this tier instead of
    a tautology."""
    seen = {}

    def get(url):
        seen["url"] = url
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict(
            {"scrape.do-resolved-url": "https://example.test/moved"})

    page = scrapedo.scrape("https://example.test/a", api_key="k", get=get)

    assert "disableRedirection" not in seen["url"]
    assert page.final_url == "https://example.test/moved"


def test_redirects_tuple_carries_the_landed_url(public_dns):
    """One call, one credit -- the vendor followed the chain server-side, and
    `redirects` records where it landed for a caller that logs the chain."""
    hops = []

    def get(url):
        hops.append(url)
        return 200, b"y" * 1000, urllib3.HTTPHeaderDict({
            "scrape.do-resolved-url": "https://example.test/b",
            "scrape.do-initial-status-code": "301",
        })

    page = scrapedo.scrape("https://example.test/a", api_key="k", get=get)

    assert page.final_url == "https://example.test/b"
    assert page.redirects == ("https://example.test/b",)
    assert len(hops) == 1


@pytest.mark.parametrize("initial", ["301", "302", "404", "not-a-number"])
def test_the_initial_status_is_recorded_not_enforced(public_dns, initial):
    """301 under render+super is an ordinary proxy bounce on a URL that answers
    200 directly. It decides nothing now; the resolved url does."""
    page = scrapedo.scrape(
        "https://example.test/a",
        api_key="k",
        get=lambda url: (200, b"y" * 1000, urllib3.HTTPHeaderDict({
            "scrape.do-initial-status-code": initial,
            "scrape.do-resolved-url": "https://example.test/a",
        })),
    )

    assert page.final_url == "https://example.test/a"


def test_an_absent_resolved_url_is_invalid_never_the_requested_url(public_dns):
    """The same rule firecrawl.py applies to a missing metadata.url. Falling back
    to the URL we asked for asserts "it did not move" on the one response
    carrying no evidence for it -- and that is exactly the claim
    reader.require_same_origin then checks, so the off-site-redirect guard would
    pass by construction. This used to raise VendorUnavailable; INVALID is now
    the value, matching firecrawl's own final-url-missing case."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k",
        get=lambda url: (200, b"y" * 1000, urllib3.HTTPHeaderDict()),
    )

    assert page.outcome is Outcome.INVALID
    # Critical #1: the two INVALID returns used to pass **common (including
    # the response body) while final_url silently defaulted to the requested
    # URL -- so a body scrape.do reported without a resolved URL to vouch for
    # it was archived under a URL that never validated it. No bytes must
    # survive an INVALID outcome.
    assert page.body == b""


def test_an_off_origin_resolved_url_is_reported_honestly_not_coerced(public_dns):
    """A vendor that landed somewhere else must SAY so here. Flattening it to the
    requested URL is what turns reader.require_same_origin -- the guard that
    keeps an attacker's page out of ProgramStatement, which every tenant reads --
    into a comparison of a value against itself."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k",
        get=lambda url: (200, b"y" * 1000,
                         urllib3.HTTPHeaderDict(
                             {"SCRAPE.DO-RESOLVED-URL": "https://elsewhere.test/x"})),
    )

    assert page.final_url == "https://elsewhere.test/x"


def test_a_resolved_url_pointing_inside_the_network_is_invalid(monkeypatch):
    """The vendor reports where it landed and that value becomes
    OfficialSource.canonical_url. A private address there is provenance pointing
    inside our own VPC -- the same guard firecrawl.py runs on metadata.url.
    This used to raise VendorUnavailable; INVALID is now the value.

    The resolver is stubbed PER HOST, not globally: the requested URL is
    validated first, so a blanket "nothing resolves" stub would make this pass
    on the wrong guard entirely."""
    def getaddrinfo(host, port, *_a, **_k):
        address = "169.254.169.254" if host == "internal.test" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    page = scrapedo.scrape(
        "https://example.test/a", api_key="k",
        get=lambda url: (200, b"y" * 1000,
                         urllib3.HTTPHeaderDict(
                             {"scrape.do-resolved-url": "https://internal.test/x"})),
    )

    assert page.outcome is Outcome.INVALID
    # Critical #1: `require_same_origin` never runs on this outcome, so the
    # only thing that kept the origin's bytes out of persist_snapshot was
    # this outcome carrying no body at all -- must never regress to leaking
    # the body scrape.do fetched from an address it could not validate.
    assert page.body == b""


def test_a_disallowed_content_type_is_blocked(public_dns):
    """Restores the browser tier's deleted test_a_disallowed_content_type_is_refused.
    scrape.do passes the origin's own Content-Type through, and it lands
    unfiltered in OfficialSourceSnapshot.content_type. This used to raise
    VendorUnavailable; BLOCKED is now the value."""
    page = scrapedo.scrape(
        "https://example.test/a",
        api_key="k",
        get=lambda url: (200, b"y" * 1000, urllib3.HTTPHeaderDict({"Content-Type": "image/png"})),
    )

    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "content_type:image/png"


def test_a_body_over_the_cap_is_blocked(public_dns):
    """Restores the browser tier's deleted test_a_body_over_the_cap_is_refused."""
    page = scrapedo.scrape(
        "https://example.test/a",
        api_key="k",
        get=lambda url: (200, b"y" * (MAX_RESPONSE_BYTES + 1), urllib3.HTTPHeaderDict()),
    )

    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "too_large"


def test_a_success_with_no_cost_header_is_billed_the_tariff_not_zero(public_dns):
    """The mirror of the block-with-no-cost-header case, which has always
    floored at the rung's own tariff. A successful rung-4 call is 25 credits;
    recorded as 0 it is invisible to SweepBudget, and a ceiling that cannot see
    a spend is not a ceiling."""
    page = scrapedo.scrape(
        "https://example.test/a", api_key="k", rung=4,
        get=lambda url: (200, b"y" * 1000, urllib3.HTTPHeaderDict(
            {"scrape.do-resolved-url": "https://example.test/a"})),
    )

    assert page.cost_credits == 25
