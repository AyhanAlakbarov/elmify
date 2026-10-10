"""The rung is EARNED, not automatic -- proved through the real providers.

Asserting on a provider alone would prove `escalate`'s value; only the router
proves nobody spends the 25 credits. Every test below that is about escalation
drives `firecrawl.scrape` / `scrapedo.scrape` for real with only their
transports faked, because a hand-built `FetchedPage` cannot be wrong about what
the provider would actually have returned -- and this plan has already shipped
one whole rung that was dead on arrival with all seven of its tests passing.
"""

import json
import socket
from ipaddress import ip_address

import pytest

from apps.research.fetch import (
    USD_PER_CREDIT,
    FetchBudgetExhausted,
    SweepBudget,
    default_budget,
    fetch_page,
    firecrawl,
    scrapedo,
)
from apps.research.fetch.types import FetchedPage, Outcome

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _resolve_test_hosts(monkeypatch):
    """`*.test` does not resolve in this sandbox (RFC 2606), and every URL here
    goes through `validate_public_url` twice -- once as the request, once as the
    vendor's reported final URL."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ip_address(host)
            address = host
        except ValueError:
            address = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


_URL = "https://example.test/a"
_PROSE = "A CV of no more than two pages is required. " * 60


def _firecrawl_payload(status=200, *, markdown=_PROSE, final_url=_URL, success=True, **extra):
    data = {
        "markdown": markdown,
        "html": f"<html><body><p>{markdown}</p></body></html>",
        "metadata": {"url": final_url, "statusCode": status, "contentType": "text/html"},
    }
    return json.dumps({"success": success, "data": data, **extra}).encode()


def _firecrawl(post):
    """The REAL provider behind the REAL ladder, with only its HTTP call faked."""

    def call(url, *, api_key, **kwargs):
        return firecrawl.scrape(url, api_key="k", post=post, sleep=lambda _seconds: None,
                                **kwargs)

    return call


def _scrapedo(get):
    def call(url, *, api_key, **kwargs):
        return scrapedo.scrape(url, api_key="k", get=get, **kwargs)

    return call


def _never(*args, **kwargs):  # pragma: no cover - the assertion is the point
    raise AssertionError("no vendor call may be made here")


def _providers(*, firecrawl_post=None, scrapedo_get=None, archive=None):
    return {
        "firecrawl": _firecrawl(firecrawl_post) if firecrawl_post else _never,
        "scrapedo": _scrapedo(scrapedo_get) if scrapedo_get else _never,
        "archive": archive or _never,
    }


# --- the type and the ceiling --------------------------------------------------


def test_a_fetched_page_records_which_vendor_produced_it() -> None:
    """Provenance is per-fetch, not per-deployment: two pages in one sweep can come
    from different vendors and the evidence chain has to say which."""
    page = FetchedPage(
        final_url=_URL, redirects=(), content_type="text/html", body=b"<html></html>",
        fetched_via="FIRECRAWL", cost_credits=1,
    )

    assert page.fetched_via == "FIRECRAWL"
    assert page.cost_credits == 1
    assert page.change_status is None


def test_an_unknown_vendor_label_is_refused() -> None:
    """The label reaches the snapshot and a typo there is a silent provenance lie."""
    with pytest.raises(ValueError):
        FetchedPage(
            final_url=_URL, redirects=(), content_type="text/html", body=b"",
            fetched_via="FIRECRAWLL", cost_credits=1,
        )


def test_each_vendor_has_its_own_cap_because_a_credit_is_not_a_unit() -> None:
    """Firecrawl's credit is 7.16x scrape.do's, so one shared pool is seven
    different ceilings depending on which vendor happened to answer."""
    budget = SweepBudget({"FIRECRAWL": 5, "SCRAPE_DO": 30})

    budget.spend("SCRAPE_DO", 25)
    budget.spend("FIRECRAWL", 5)  # the other vendor's cap is untouched by the first

    assert budget.spent == {"FIRECRAWL": 5, "SCRAPE_DO": 25}
    budget.check("SCRAPE_DO")  # 25 of 30: still open
    with pytest.raises(FetchBudgetExhausted):
        budget.check("FIRECRAWL")


def test_a_budget_reports_dollars_not_credits() -> None:
    """Credits do not compare across vendors; dollars do, and dollars are what a
    sweep is actually capped in (spec 4.1b)."""
    budget = SweepBudget({"FIRECRAWL": 1_000, "SCRAPE_DO": 1_000})
    budget.spend("SCRAPE_DO", 25)
    budget.spend("FIRECRAWL", 1)

    assert budget.usd() == pytest.approx(
        25 * USD_PER_CREDIT["SCRAPE_DO"] + USD_PER_CREDIT["FIRECRAWL"]
    )
    ratio = USD_PER_CREDIT["FIRECRAWL"] / USD_PER_CREDIT["SCRAPE_DO"]
    assert ratio == pytest.approx(7.16, abs=0.01)


def test_an_unknown_vendor_is_refused_not_ignored() -> None:
    """A typo'd vendor name that silently spent nothing would make the ceiling
    unbounded for exactly the tier nobody checked."""
    with pytest.raises(KeyError):
        SweepBudget({"SCRAPE_DO": 1}).spend("TAVILY", 1)


def test_an_unbudgeted_call_still_gets_the_settings_ceiling(settings) -> None:
    """`budget=None` is the reader path (CLAUDE.md), and a call with no ceiling
    at all is how a per-domain multiplier drains a plan in one page."""
    settings.FETCH_SWEEP_CREDITS = {"FIRECRAWL": 7, "SCRAPE_DO": 11}

    assert default_budget().caps == {"FIRECRAWL": 7, "SCRAPE_DO": 11}


# --- a refusal of OUR request never buys the residue tier -----------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_an_outer_status_firecrawl_refuses_our_request_with_never_escalates(status) -> None:
    """A host block is reported at 200 + success:false (measured); an outer
    status is Firecrawl refusing OUR request -- a revoked or misconfigured key,
    a URL it will not take. A bad key is the one cause that hits every page of a
    sweep at once, so escalating here is 25 credits times the whole run."""
    rungs = []

    def scrapedo_get(url):
        rungs.append("render=true" in url)
        return 429, b"", {}  # scrape.do's own concurrency limit: no rung 4 either

    page = fetch_page(
        _URL,
        providers=_providers(firecrawl_post=lambda *a, **k: (status, b"nope", {}),
                             scrapedo_get=scrapedo_get),
    )

    assert rungs == [False]  # rung 3 ran, rung 4 never did
    assert page.outcome is Outcome.RETRY_SCHEDULED
    assert page.attempts[0].reason.startswith("vendor_unavailable")
    assert str(status) in page.attempts[0].reason


def test_a_non_json_body_is_firecrawl_malfunctioning_not_a_hard_host() -> None:
    """Nothing about an unparseable 200 says the page is hard to fetch."""
    page = fetch_page(
        _URL,
        providers=_providers(firecrawl_post=lambda *a, **k: (200, b"<html>gateway</html>", {}),
                             scrapedo_get=lambda url: (429, b"", {})),
    )

    assert page.outcome is Outcome.RETRY_SCHEDULED
    assert "non-JSON" in page.attempts[0].reason


def test_a_throttled_vendor_does_not_buy_a_25_credit_answer() -> None:
    """The regression this branch shipped with. Firecrawl's free tier is 10
    requests/minute and a `discover` sweep paces per DOMAIN: 58 hosts go out at
    30-60/minute, most 429, and each 429 escalated to a 25-credit scrape.do call
    for a page Firecrawl would have served for 1 a minute later. The provider
    already backed off and retried by the time it gives up -- the host was never
    asked, so there is nothing for the residue tier to answer."""
    budget = SweepBudget({"FIRECRAWL": 5, "SCRAPE_DO": 30})
    rungs = []

    def scrapedo_get(url):
        rungs.append("render=true" in url)
        return 429, b"", {}

    page = fetch_page(
        _URL, budget=budget,
        providers=_providers(firecrawl_post=lambda *a, **k: (429, b"slow down", {}),
                             scrapedo_get=scrapedo_get),
    )

    assert "retry later" in page.attempts[0].reason
    assert rungs == [False]  # rung 3 is a different network for 1 credit; rung 4 is not
    assert budget.spent == {"FIRECRAWL": 0, "SCRAPE_DO": 0}


def test_rung_four_is_never_reached_from_an_escalate_false_failure() -> None:
    """The twin of the test above, taken at the other end of the ladder: the
    vendor that failed non-escalating is the one rung 4 would be bought from.
    `escalate=False` means the host was never asked -- so a SECOND request to
    the same vendor answers a question about us, at 25 credits."""
    seen = []

    def scrapedo_get(url):
        if "render=true" in url:  # pragma: no cover - the assertion is the point
            raise AssertionError("escalate=False bought the 25-credit rung")
        seen.append(url)
        return 502, b"please try again", {}  # scrape.do's own, non-escalating

    page = fetch_page(
        _URL,
        providers=_providers(
            firecrawl_post=lambda *a, **k: (200, _firecrawl_payload(
                success=False, code=firecrawl.REASON_DNS_RESOLUTION_ERROR), {}),
            scrapedo_get=scrapedo_get,
        ),
    )

    assert len(seen) == 1
    assert page.outcome is Outcome.RETRY_SCHEDULED
    assert [attempt.rung for attempt in page.attempts] == [1, 3, 5]


# --- obligation 1: the same status code, two different answers ------------------


def test_a_scrapedo_401_is_its_own_failure_and_stops_short_of_rung_four() -> None:
    """scrape.do returns ONE status code for its own 401 (bad key, suspended
    account) and for a target answering 401, with no request-time signal to tell
    them apart. Firecrawl gets two codes and CAN, which is why the ladder
    special-cases this instead of switching on `Outcome` alone."""
    rungs = []

    def scrapedo_get(url):
        rungs.append("render=true" in url)
        return 401, b"", {}

    page = fetch_page(
        _URL,
        providers=_providers(
            # A relayed 403 from Firecrawl: the preceding rung DID escalate, so
            # only scrape.do's own verdict can be what stops rung 4 here.
            firecrawl_post=lambda *a, **k: (200, _firecrawl_payload(403), {}),
            scrapedo_get=scrapedo_get,
        ),
    )

    assert rungs == [False]
    assert page.outcome is Outcome.RETRY_SCHEDULED


def test_a_scrapedo_403_is_the_targets_answer_and_earns_rung_four() -> None:
    """The other half: 403 is unambiguous -- scrape.do never uses it for its own
    failures -- so it is the bot wall the residue tier is bought for."""
    rungs = []

    def scrapedo_get(url):
        rungs.append("render=true" in url)
        if "render=true" in url:
            return 200, f"<html><body><p>{_PROSE}</p></body></html>".encode(), {
                "Content-Type": "text/html", "Scrape.do-Resolved-Url": _URL,
                "Scrape.do-Request-Cost": "25",
            }
        return 403, b"", {}

    page = fetch_page(
        _URL,
        providers=_providers(firecrawl_post=lambda *a, **k: (200, _firecrawl_payload(403), {}),
                             scrapedo_get=scrapedo_get),
    )

    assert rungs == [False, True]
    assert page.outcome is Outcome.FETCHED
    assert (page.rung, page.fetched_via) == (4, "SCRAPE_DO")


def test_an_unchanged_page_that_moved_off_origin_is_still_refused() -> None:
    """UNCHANGED is not "no bytes". The real provider builds it from the same
    `common` as a FETCHED page -- body, markdown and the vendor's own final URL
    -- so a caller that asked for provenance would otherwise be handed a full
    vendor body from an origin nothing ever compared. Driven through the real
    Firecrawl classifier, not a hand-built page, because the claim under test is
    exactly that the provider fills the body on this path."""

    def post(*args, **kwargs):
        payload = {
            "success": True,
            "data": {
                "markdown": _PROSE,
                "html": f"<html><body><p>{_PROSE}</p></body></html>",
                "changeTracking": {"changeStatus": "same"},
                "metadata": {"url": "https://elsewhere.test/a", "statusCode": 200,
                             "contentType": "text/html"},
            },
        }
        return 200, json.dumps(payload).encode(), {}

    unchecked = fetch_page(_URL, tag="2027", providers=_providers(firecrawl_post=post))
    assert unchecked.outcome is Outcome.UNCHANGED
    assert unchecked.body  # the bytes the old gate let through unexamined

    page = fetch_page(_URL, tag="2027", require_origin=_URL,
                      providers=_providers(firecrawl_post=post))

    assert page.outcome is Outcome.OFF_SITE
    assert page.body == b""


def test_a_dead_link_is_paid_for_once_not_twice() -> None:
    """scrape.do's published billing counts 2XX, 400, 404 and 410 as SUCCESSFUL
    requests, so a dead catalogue link escalated costs 1 + 25 credits and yields
    a 404 page. The credit Firecrawl already billed still reaches the budget."""
    budget = SweepBudget({"FIRECRAWL": 5, "SCRAPE_DO": 30})

    page = fetch_page(
        _URL, budget=budget,
        providers=_providers(firecrawl_post=lambda *a, **k: (200, _firecrawl_payload(404), {})),
    )

    assert page.outcome is Outcome.DEAD
    assert budget.spent == {"FIRECRAWL": 1, "SCRAPE_DO": 0}


def test_a_charged_failure_is_paid_for_and_the_next_vendor_still_runs() -> None:
    """Firecrawl bills the credit for a target's block page. The budget has to
    see it -- a sweep over a catalogue of walled links costs real money and
    would otherwise look free -- and it is the TARGET that failed, so scrape.do
    still gets its turn."""
    budget = SweepBudget({"FIRECRAWL": 5, "SCRAPE_DO": 30})

    def scrapedo_get(url):
        return 200, f"<html><body><p>{_PROSE}</p></body></html>".encode(), {
            "Content-Type": "text/html", "Scrape.do-Resolved-Url": _URL,
            "Scrape.do-Request-Cost": "1",
        }

    page = fetch_page(
        _URL, budget=budget,
        providers=_providers(firecrawl_post=lambda *a, **k: (200, _firecrawl_payload(403), {}),
                             scrapedo_get=scrapedo_get),
    )

    assert page.fetched_via == "SCRAPE_DO"
    assert budget.spent == {"FIRECRAWL": 1, "SCRAPE_DO": 1}


def test_every_rung_it_walked_is_named_in_the_trail() -> None:
    """"all vendors failed" with no rung named is a debugging dead end: a missing
    key, a 404 and a block page are three different fixes."""
    page = fetch_page(
        _URL,
        providers=_providers(
            firecrawl_post=lambda *a, **k: (200, _firecrawl_payload(
                success=False, error=firecrawl.REASON_ALL_ENGINES_FAILED), {}),
            scrapedo_get=lambda url: (403, b"", {}),
        ),
    )

    assert [(a.rung, a.vendor) for a in page.attempts] == [
        (1, "FIRECRAWL"), (3, "SCRAPE_DO"), (4, "SCRAPE_DO"), (5, "NONE"),
    ]
    assert page.attempts[0].reason == firecrawl.REASON_ALL_ENGINES_FAILED
