"""Rungs 3 and 4: the scrape.do GET API.

scrape.do is a TRANSPORT, not an extractor: it hands back what the origin
actually sent. That makes it the residue tier for hosts Firecrawl's own
escalation could not pass --
measured 2026-09-19, one host in 58, and only at render+super. Rung 3 is the
same call at render=false&super=false (1 credit); rung 4 adds render=true&
super=true (25 credits) plus a sticky session, because a residential address
that changes between pages of one site re-triggers the very challenge rung 4
exists to pass (spec §4 rungs 3-4, §9.2 layer 4).

Failed requests are free (only 2xx, 400, 404 and 410 are charged), so trying
this tier costs latency and nothing else when it loses. What it costs when it
WINS is read from the response header, never from a tariff in our code:
per-domain profiles are applied server-side with no request-time signal --
`_TARIFF` below is a FLOOR for a charged response whose cost header is absent
or unreadable, never a substitute for it.

**As of this task, a TARGET/vendor answer that yields nothing is a value
(`Outcome.DEAD`/`BLOCKED`/`UNREADABLE`/`INVALID`/`UNREACHABLE`) returned from
`scrape()`, never an exception** -- this is firecrawl.py's own contract
(2026-09-23 delta), brought here so both providers agree before Task 7's
ladder switches on `Outcome` instead of an exception type. `VendorUnavailable`
still covers the two cases nothing here can turn into an answer about the
target: no key, and a transport failure that never reached scrape.do at all.

**Redirects are followed by the vendor; `disableRedirection` is gone.**
Measured 2026-09-22 on `http://globed.eu/`: with redirects followed, scrape.do
charged 1 credit for the whole chain and named the final URL in
`Scrape.do-Resolved-Url` (with `Scrape.do-Initial-Status-Code`, logged only);
with `disableRedirection=true` it charged 1 credit PER HOP and named the next
hop in `Scrape.do-Target-Redirected-Location` -- the standard `Location`
header is not passed through. A hop-by-hop loop existed here because *our*
network used to do the fetching and a hop into 169.254.169.254 was our own
metadata service; the vendor's hops run on the vendor's network, so what
provenance needs is that the URL we RECORD is public, and `validate_public_url`
on `Scrape.do-Resolved-Url` gives exactly that at a third of the cost on a
two-hop chain (amends spec §10's "hop by hop" for the vendor tiers).

**An absent resolved-URL header is a FAILURE, never a fallback to the
requested URL** -- the same rule firecrawl.py applies to a missing
`metadata.url`. Falling back asserts "it did not move" on the one response
carrying no evidence for it, which is exactly the claim
`reader.require_same_origin` then checks (CLAUDE.md, "Decision B vouches for
the SOURCE ROW, not the BYTES").
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import urllib3
from django.conf import settings

from apps.research.egress import UnsafeTarget, validate_public_url

from .types import (
    REASON_FINAL_URL_MISSING,
    REASON_FINAL_URL_UNSAFE,
    REASON_ORIGIN_STATUS,
    Attempt,
    FetchedPage,
    Outcome,
    VendorUnavailable,
    usable,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.scrape.do/"
#: scrape.do's own failures, none of them billed -- their published status-code
#: table, read 2026-09-19: 401 no credits or suspended account, 429 concurrency
#: limit, 502 "please try again", 510 the client cancelled. None of these is
#: the target answering; they say nothing about the target and cost nothing.
#:
#: 401 and 429 are also codes a TARGET can answer with, and scrape.do returns
#: exactly one status code either way -- there is no request-time signal that
#: tells the two apart, unlike firecrawl.py's two-status shape (an outer 429
#: from Firecrawl itself vs. a target 401/403/429 relayed in the JSON body),
#: which is how firecrawl.py CAN escalate its own `_BLOCKING_TARGET_STATUS`.
#: Decision 5 (spec §4 rule 3) says a target's answer is final and a 401/403/
#: 429 that survives escalates; this module cannot honour that for 401/429
#: without risking a bad key or a concurrency limit spending the 25-credit rung
#: on every page of a sweep, which is exactly the overspend Important #3 (and
#: the 58-host measurement in CLAUDE.md) is about -- so these two stay
#: UNREACHABLE, non-escalating, unlike firecrawl's BLOCKED for the same codes.
#: 403 is unambiguous (scrape.do never uses it for its own failures) and
#: escalates below via `_BLOCKING`.
_SCRAPE_DO_OWN = frozenset({401, 429, 502, 510})
#: A different proxy would not change any of these -- the origin answered
#: (spec §4 rule 3). 404/410 mean the resource is gone; 400 means the origin
#: rejected THIS request as malformed -- a different fact, but the same
#: non-escalating property, since no proxy changes what we asked for either.
#: scrape.do's published billing counts all three as SUCCESSFUL, so a caller
#: escalating one pays 1 + 25 credits for an answer a second rung cannot
#: change. None of them escalate.
_DEAD = frozenset({400, 404, 410})
#: The bot-wall signature passed through from the target -- exactly what a
#: higher rung exists to try to pass. Escalates.
_BLOCKING = frozenset({403})
#: The published tariff PER RUNG -- a floor for a charged response (2xx, plus
#: DEAD's 400/404/410) whose cost header is absent or unreadable, never the
#: authority: per-domain profiles (10-200x) are applied server-side with no
#: request-time signal, so `Scrape.do-Request-Cost` is read first always.
_TARIFF = {3: 1, 4: 25}

Get = Callable[[str], tuple[int, bytes, Mapping[str, str]]]


def _get(url: str) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "GET", url, timeout=urllib3.Timeout(connect=10, read=120), retries=False
    )
    # response.headers, not dict(...): it is urllib3's case-insensitive
    # HTTPHeaderDict, and HTTP/2 lowercases header names on the wire, so
    # `scrape.do-resolved-url` and `Scrape.do-Resolved-Url` must both be found
    # by one lookup. firecrawl._post keeps it for the same reason.
    return response.status, response.data, response.headers


def _cost(headers: Mapping[str, str]) -> int:
    raw = headers.get("Scrape.do-Request-Cost")
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def scrape(
    url: str,
    *,
    api_key: str,
    rung: int = 3,
    profile: Any = None,
    session_id: int | None = None,
    screenshot: bool = False,
    get: Get = _get,
) -> FetchedPage:
    if not api_key:
        # About us, not the target -- the host was never asked. Escalating
        # would burn the 25-credit rung on every page of a sweep with a bad
        # key, exactly the argument firecrawl.py makes for its own outer
        # failures (CLAUDE.md, "not now" vs "this host beat us").
        raise VendorUnavailable("SCRAPEDO_API_KEY is not set", escalate=False)
    try:
        validate_public_url(url)
    except UnsafeTarget as error:
        # Also about us -- a misconfigured request, not a target that beat us.
        msg = f"refusing to hand a non-public url to a vendor: {error}"
        raise VendorUnavailable(msg, escalate=False) from error

    params: dict[str, Any] = {
        "token": api_key,
        "url": url,
        "timeout": getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS,
    }
    if rung >= 4:
        params["render"] = "true"
        params["super"] = "true"
        if session_id is not None:
            params["sessionId"] = session_id
        if getattr(profile, "wait_selector", ""):
            params["waitSelector"] = profile.wait_selector
        if getattr(profile, "custom_wait_ms", 0):
            params["customWait"] = profile.custom_wait_ms
    else:
        params["render"] = "false"
        params["super"] = "false"
    if getattr(profile, "geo_code", ""):
        params["geoCode"] = profile.geo_code
    if screenshot:
        params["fullScreenShot"] = "true"

    started = time.monotonic()
    try:
        status, body, headers = get(f"{ENDPOINT}?{urlencode(params)}")
    except urllib3.exceptions.HTTPError as error:
        # urllib3's own exceptions -- timeouts, TLS and DNS failures, resets --
        # all inherit from HTTPError, not OSError.
        #
        # type(error).__name__ alone, never str(error): the request URL above
        # carries the API token in its query string, and urllib3's exception
        # messages quote the URL.
        #
        # escalate=False: a dropped connection is about US, not the target --
        # the host was never asked, so a second (25-credit) rung answers a
        # question nobody asked. Mirrors firecrawl.py's identical handling of
        # its own transport failures (CLAUDE.md, "not now" vs "this host beat
        # us").
        raise VendorUnavailable(
            f"scrape.do transport: {type(error).__name__}", escalate=False
        ) from error
    elapsed_ms = int((time.monotonic() - started) * 1000)

    # For the record only. A 301 here is an ordinary proxy bounce at this tier
    # (measured: globed.eu reports 301 under render+super and 200 under a
    # direct request), so it decides nothing -- `scrape.do-resolved-url` says
    # where the bytes came from, and that is the value a caller needs.
    logger.debug(
        "scrape.do initial status for %s: %s", url,
        headers.get("Scrape.do-Initial-Status-Code"),
    )

    raw_cost = _cost(headers)

    def _result(outcome: Outcome, *, credits: int, reason: str = "", **extra: Any
                ) -> FetchedPage:
        status_code = extra.pop("status_code", status)
        return FetchedPage(
            final_url=extra.pop("final_url", url),
            redirects=extra.pop("redirects", ()),
            content_type=extra.pop("content_type", ""),
            body=extra.pop("body", b""),
            markdown="",
            outcome=outcome,
            fetched_via="SCRAPE_DO",
            rung=rung,
            cost_credits=credits,
            status_code=status_code,
            reason=reason,
            attempts=(
                Attempt(
                    rung=rung, vendor="SCRAPE_DO", outcome=outcome, credits=credits,
                    status_code=status_code, reason=reason, duration_ms=elapsed_ms,
                ),
            ),
            **extra,
        )

    if status in _DEAD:
        # Charged (2xx, 400, 404 and 410 are scrape.do's published "successful
        # request" set), so an absent/unreadable cost header still floors at
        # the tariff -- a success is not cheaper than a dead link.
        return _result(Outcome.DEAD, credits=raw_cost or _TARIFF.get(rung, 1),
                       reason=REASON_ORIGIN_STATUS.format(status=status))
    if status in _BLOCKING:
        return _result(Outcome.BLOCKED, credits=raw_cost,
                       reason=REASON_ORIGIN_STATUS.format(status=status))
    if status in _SCRAPE_DO_OWN:
        # Not charged: scrape.do's own reserved codes (none billed, per their
        # table). Checked BEFORE the >= 500 test below, which is what keeps 502
        # and 510 out of it. A miss here costs latency only.
        return _result(Outcome.UNREACHABLE, credits=raw_cost,
                       reason=REASON_ORIGIN_STATUS.format(status=status))
    if status >= 500:
        # Any 5xx that is not one of scrape.do's own reserved codes is
        # necessarily the TARGET's -- decision 5 applies and it escalates,
        # exactly like firecrawl.py's `site_status >= 500` -> BLOCKED
        # (Important #2a). A comparison, never an enumerated set: {500, 503,
        # 504} dropped Cloudflare's 521/522/525 origin-down family -- the very
        # bot-wall population the 25-credit residue rung exists for -- through
        # to the non-escalating catch-all below, so those hosts never reached
        # rung 4 while the comment claimed parity with firecrawl.py.
        # Not charged, per scrape.do's published table.
        return _result(Outcome.BLOCKED, credits=raw_cost,
                       reason=REASON_ORIGIN_STATUS.format(status=status))
    if status != 200:
        # Anything else this module has no more specific answer for.
        return _result(Outcome.UNREACHABLE, credits=raw_cost,
                       reason=REASON_ORIGIN_STATUS.format(status=status))

    # status == 200 from here. Charged; an absent/unreadable cost header
    # floors at the rung's own tariff, never zero -- a success is not cheaper
    # than a failure.
    credits = raw_cost or _TARIFF.get(rung, 1)
    content_type = (headers.get("Content-Type") or "text/html").split(";", 1)[0].strip()
    common: dict[str, Any] = dict(content_type=content_type, body=body, status_code=status)

    # The real status code, not a suppressed one: `usable()`'s own short-body
    # floor is `types.MIN_DOCUMENT_BYTES` (1,000 bytes), the SAME number
    # CLAUDE.md's mischolarship.com measurement (469 bytes, this module's own
    # evidence) was used to set -- deliberately higher than the 500-byte floor
    # this module used to keep as a second, looser number. A body between 500
    # and 999 bytes was FETCHED here and BLOCKED through firecrawl.py before
    # this fix; one floor now on both (Important #5).
    ok, reason = usable(content_type, body, status)
    if not ok:
        outcome = Outcome.UNREADABLE if reason == "shell" else Outcome.BLOCKED
        return _result(outcome, credits=credits, reason=reason, **common)

    final_url = headers.get("Scrape.do-Resolved-Url")
    if not final_url:
        # Never `or url`, and never **common: falling back to the requested
        # URL asserts "it did not move" on the one response carrying no
        # evidence for it -- exactly what reader.require_same_origin then
        # checks -- and **common carries the response BODY, which must not
        # be archived under a final_url this module could not validate
        # (Critical #1). status_code is the only piece of `common` kept.
        return _result(Outcome.INVALID, credits=credits, reason=REASON_FINAL_URL_MISSING,
                       status_code=status)
    try:
        validate_public_url(final_url)
    except UnsafeTarget:
        # Same reasoning as the missing-final_url case just above: no
        # **common, so neither the unsafe address nor the body it came with
        # reaches the FetchedPage record. Mirrors firecrawl.py's own
        # REASON_FINAL_URL_UNSAFE handling.
        return _result(Outcome.INVALID, credits=credits, reason=REASON_FINAL_URL_UNSAFE,
                       status_code=status)

    redirects = (final_url,) if final_url != url else ()
    return _result(Outcome.FETCHED, credits=credits, final_url=final_url,
                   redirects=redirects, **common)
