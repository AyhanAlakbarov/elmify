"""Rungs 1 and 2: Firecrawl POST /v2/scrape.

Firecrawl is the ENGINE'S EXTRACTOR, not merely a proxy: it returns markdown
for HTML, PDF, DOCX, XLSX, PPTX and CSV alike, which is why every page a reader
will read starts here and why change tracking -- which only compares against
Firecrawl's own previous scrape of a URL -- can only work if this is the tier
that fetched it (spec §4.1d item 1).

This is a delta over the module PR #103 shipped, not a rewrite from scratch:
the retry/back-off loop on a throttled or erroring OUTER response (429, 5xx, a
dropped connection), the immediate refusal on 402, and "never `or url`" on a
missing final URL are all measured behaviour that stays. What changes here is
the TARGET's own answer -- a 404, a 403 that survived the enhanced proxy, a
short or challenge body -- which used to raise `ChargedFailure`/
`VendorUnavailable` and now returns an `Outcome` value instead, so a caller
reads "found nothing" from "could not look" without a try/except (spec §6).

Everything arriving here is untrusted in exactly the way the page it came from
was untrusted. `metadata.url` decides provenance and is validated like any
other final URL, never defaulted to the URL we requested -- a response
carrying no final URL is the one case with no evidence that the page did not
move, and defaulting there is exactly the claim `require_same_origin` then
checks (CLAUDE.md, "Decision B vouches for the SOURCE ROW, not the BYTES").

`body` is the `html` format, never `rawHtml`: `harvest.anchors`,
`search._sitemap`, `reader.readable_text` and `content_digest` all parse markup
off it, and `onlyMainContent: true` strips exactly the navigation links anchor
harvesting reads -- shipped once as markdown, this made every catalogue yield
zero leads in silence (CLAUDE.md, "Web fetching").

**Intermediate state, recorded rather than left implicit (review finding
Important #1, RULED):** as of this task, a TARGET failure is a value
(`Outcome.DEAD`/`BLOCKED`/`UNREADABLE`/`INVALID`/`UNREACHABLE`) returned from
`scrape()`, never an exception. Nothing downstream switches on that value yet
-- `fetch_page` in `.__init__` still returns `page` the moment this function
does not raise, so the escalate=True ladder (try Firecrawl, then scrape.do on
a host that beat it) is unreachable from here today. That is deliberate and
out of this task's file: `__init__.py`'s ladder is Task 7's to build.
`scrapedo.py` now agrees (Task 4, 2026-09-23): it also returns a target/vendor
failure as one of these values rather than raising `ChargedFailure`/
`VendorUnavailable`. **That does not mean Task 7's ladder can switch on
`Outcome` alone across both providers** (an earlier version of this note said
so; it was wrong). scrape.do returns exactly one status code for both its own
401 (bad key/suspended) and 429 (concurrency limit) and a TARGET answering
with the same code -- there is no request-time signal to tell them apart, so
`scrapedo.scrape` cannot escalate a 401/429 the way `_BLOCKING_TARGET_STATUS`
below does; it reports `Outcome.UNREACHABLE`, non-escalating, where this
module reports `Outcome.BLOCKED`, escalating, for the identical code. Every
other status the two providers now agree on: 403 and any 5xx the target sent
are `Outcome.BLOCKED` on both, 404/410 are `Outcome.DEAD` on both. A caller
that needs one switch across both vendors must special-case 401/429 rather
than trusting `Outcome` alone to carry the escalation decision.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

import urllib3
from django.conf import settings

from apps.research.egress import (
    _MIN_BYTES_FOR_FLOOR,
    _MIN_READABLE_CHARS,
    _RETRY_ATTEMPTS,
    UnsafeTarget,
    _backoff_seconds,
    validate_public_url,
)

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

ENDPOINT = "https://api.firecrawl.dev/v2/scrape"

#: Firecrawl escalates basic -> enhanced proxies on exactly these, at most once
#: per request, at no extra charge. What survives them is a block for us too --
#: a different proxy would not change a 401/403/429 that got this far.
_BLOCKING_TARGET_STATUS = frozenset({401, 403, 429})
#: The origin answered. A different proxy would not change it (spec §4 rule 3).
_DEAD_TARGET_STATUS = frozenset({404, 410})
#: Outer statuses -- Firecrawl's OWN answer, not the target's -- worth a
#: back-off retry. 503 is folded into the >=500 check below, matching
#: egress._THROTTLED's reasoning: "come back later", not "no".
_RETRYABLE_OUTER_STATUS = frozenset({429})

#: `FetchedPage.reason` values this module alone sets. The three both providers
#: set -- REASON_FINAL_URL_MISSING/_UNSAFE/_ORIGIN_STATUS -- live in types.py
#: and are imported above: a caller must not have to know which vendor produced
#: them, which two identical literals in two modules cannot guarantee.
REASON_SHELL = "shell"
REASON_PDF_TRUNCATED = "pdf_truncated"

#: Firecrawl's own failure vocabulary on a `success: false` response
#: (CLAUDE.md, "A vendor failure answers one of two different questions"):
#: "not now" versus "this host beat us -- escalate". Read verbatim out of
#: `payload["code"]`/`payload["error"]` into `reason`; named here because this
#: field is, as of this task, the ONLY place the distinction survives --
#: Task 7's ladder must switch on exactly these two strings, not re-derive
#: them from the vendor's docs a second time.
#: "no proxy resolves a name that does not exist" -- never worth a second vendor.
REASON_DNS_RESOLUTION_ERROR = "SCRAPE_DNS_RESOLUTION_ERROR"
#: "that host beat proxy:auto" -- exactly what the residue tier is for.
REASON_ALL_ENGINES_FAILED = "All scraping engines failed to retrieve content"
#: Firecrawl's own 408: its renderer ran out of time on THIS page. Raised as a
#: VendorUnavailable that escalates, because it is a question about the host;
#: named so a caller separating vendor outages from host failures (the
#: resolver gate) matches the same string this module raises.
REASON_RENDER_TIMEOUT = "firecrawl timed out rendering the page"

#: What the `json` format adds to a scrape (Firecrawl pricing, re-read
#: 2026-09-25; the response carries no per-call credit count, so this is a
#: tariff). Charged only when a json format was asked for AND a json object
#: came back; `manage.py reconcile_fetch_credits` catches it if the vendor
#: bills otherwise.
JSON_FORMAT_CREDITS = 4

Post = Callable[..., tuple[int, bytes, Mapping[str, str]]]


def _post(url: str, *, json_body: dict[str, Any], headers: dict[str, str], timeout: int
          ) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "POST", url, json=json_body, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=timeout / 1000 + 30), retries=False,
    )
    # response.headers, not dict(...): it is urllib3's case-insensitive
    # HTTPHeaderDict and _backoff_seconds looks up "Retry-After" by that exact
    # casing. HTTP/2 lowercases header names on the wire.
    return response.status, response.data, response.headers


def scrape(
    url: str,
    *,
    api_key: str,
    tag: str | None = None,
    actions: bool = False,
    profile: Any = None,
    request_id: str | None = None,
    screenshot: bool = False,
    json_format: Mapping[str, Any] | None = None,
    post: Post = _post,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchedPage:
    if not api_key:
        raise VendorUnavailable("FIRECRAWL_API_KEY is not set")

    rung = 2 if actions else 1
    # HostProfile.timeout_ms (models.py) carries the per-host override once one
    # is learned; with no profile yet, this reads a setting rather than a
    # second hardcoded literal that would silently diverge from the column's
    # own default (Task 2 obligation, CLAUDE.md).
    timeout_ms = getattr(profile, "timeout_ms", 0) or settings.FETCH_DEFAULT_TIMEOUT_MS
    formats: list[Any] = ["markdown", "links", "html"]
    if tag:
        # changeTracking compares pages via their MARKDOWN, so that format must
        # travel with it, and the request bypasses the index cache entirely --
        # every scrape under a tag is a fresh fetch, one credit against a
        # reader run avoided on an unchanged page.
        formats.append({"type": "changeTracking", "tag": tag})
    if screenshot:
        formats.append({"type": "screenshot", "fullPage": True})
    if json_format is not None:
        # Rides the same scrape as the html the judge reads, so the two readers
        # compare the same page version (spec §8.9). Appended last, so every
        # request without it is byte-for-byte what it was before.
        formats.append({"type": "json", **json_format})

    body: dict[str, Any] = {
        "url": url,
        "formats": formats,
        # False: anchor harvesting reads exactly the navigation links this
        # strips, and reader.readable_text does its own <main>/admission-
        # section narrowing on the way to the model.
        "onlyMainContent": False,
        "blockAds": True,
        # Reads Georgia's education ministry, whose broken TLS chain our own
        # client refused. True is the vendor's own default; set explicitly so
        # a future default change on their side does not silently narrow this.
        "skipTlsVerification": True,
        "removeBase64Images": True,
        "timeout": timeout_ms,
        "parsers": [
            {
                # A PDF is billed per page, so the read is capped and a
                # truncated one is FETCHED_PARTIAL, never a silent miss.
                "type": "pdf",
                "maxPages": settings.FETCH_PDF_MAX_PAGES,
                "pageMarkers": True,
            }
        ],
    }
    # `proxy` is dropped: deprecated, and `auto` -- the default -- already
    # escalates to enhanced proxies on 401/403/429 at no extra charge.
    # `location` stays unset unless the profile says the host is geo-gated;
    # sending it for an ungated host silently narrows cache and
    # change-tracking consistency to one country.
    if getattr(profile, "geo_code", ""):
        body["location"] = {
            "country": profile.geo_code,
            "languages": list(getattr(profile, "languages", []) or []),
        }
    if actions:
        wait_ms = getattr(profile, "custom_wait_ms", 0) or 3_000
        body["actions"] = [
            {"type": "wait", "milliseconds": wait_ms},
            {"type": "scroll", "direction": "down"},
            {"type": "wait", "milliseconds": 2_000},
        ]
        if getattr(profile, "wait_selector", ""):
            body["actions"].insert(0, {"type": "wait", "selector": profile.wait_selector})

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if request_id:
        # Measured 2026-09-22: reusing an id SEQUENTIALLY after the first call
        # completed was charged again (678 -> 677 credits) -- it only refuses a
        # CONCURRENT duplicate (409 request_in_flight). So a client-side
        # timeout must never be answered by re-issuing this call with the same
        # id; the header is sent anyway because a concurrent duplicate is the
        # one case it does prevent.
        headers["x-request-id"] = request_id

    started = time.monotonic()
    status = 0
    raw = b""
    response_headers: Mapping[str, str] = {}
    for attempt in range(_RETRY_ATTEMPTS + 1):
        last = attempt == _RETRY_ATTEMPTS
        try:
            status, raw, response_headers = post(
                ENDPOINT, json_body=body, headers=headers, timeout=timeout_ms
            )
        except urllib3.exceptions.HTTPError as error:
            # urllib3's own exceptions -- timeouts, TLS and DNS failures,
            # resets -- all inherit from HTTPError. A reset or a connect
            # timeout on OUR side says nothing about the host.
            if last:
                raise VendorUnavailable(
                    f"firecrawl transport: {type(error).__name__} -- "
                    "vendor throttled, retry later",
                    escalate=False,
                ) from error
            sleep(_backoff_seconds(None, attempt))
            continue
        if status in _RETRYABLE_OUTER_STATUS or status >= 500:
            # "Not now", not "no" -- the host was never asked. Firecrawl's free
            # tier is 10 requests/minute and a sweep paces per domain, so
            # without this back-off every 429 spent 25 credits on a page
            # Firecrawl would have served for 1 a minute later.
            if last:
                raise VendorUnavailable(
                    f"firecrawl answered HTTP {status} -- vendor throttled, retry later",
                    escalate=False,
                )
            sleep(_backoff_seconds(SimpleNamespace(headers=response_headers), attempt))
            continue
        break
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if status == 402:
        # The plan's credits are gone. Retrying cannot make them come back --
        # this is an invoice, not a host.
        raise VendorUnavailable(
            "firecrawl: payment required, the credit balance is spent", escalate=False
        )
    if status == 408:
        # Firecrawl's own timeout on a page it could not finish. A residential
        # browser is a different renderer with a different clock and may
        # finish, so this keeps escalate's default True.
        raise VendorUnavailable(REASON_RENDER_TIMEOUT)
    if status != 200:
        # Everything the table names is handled above, so this is Firecrawl
        # refusing OUR REQUEST -- a bad key, a URL it will not take. A bad key
        # hits every page of a sweep at once, so escalating here would turn a
        # free failure into 25 credits times the whole run.
        raise VendorUnavailable(f"firecrawl answered HTTP {status}", escalate=False)

    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise VendorUnavailable(
            f"firecrawl returned non-JSON (HTTP {status})", escalate=False
        ) from error

    def _result(outcome: Outcome, *, credits: int = 0, reason: str = "", **extra: Any
                ) -> FetchedPage:
        status_code = extra.pop("status_code", None)
        return FetchedPage(
            final_url=extra.pop("final_url", url),
            redirects=(),
            content_type=extra.pop("content_type", ""),
            body=extra.pop("body", b""),
            markdown=extra.pop("markdown", ""),
            outcome=outcome,
            fetched_via="FIRECRAWL",
            rung=rung,
            cost_credits=credits,
            status_code=status_code,
            reason=reason,
            attempts=(
                Attempt(
                    rung=rung, vendor="FIRECRAWL", outcome=outcome, credits=credits,
                    status_code=status_code, reason=reason, duration_ms=elapsed_ms,
                ),
            ),
            **extra,
        )

    if not payload.get("success"):
        # No document came back, so nothing was charged. Measured 2026-09-19:
        # 710 credits before and after a DNS failure -- trying this tier first
        # is free when it loses. `reason` carries the vendor's own code/error
        # verbatim -- it is the ONLY place REASON_DNS_RESOLUTION_ERROR is
        # distinguishable from REASON_ALL_ENGINES_FAILED, and Task 7's ladder
        # must switch on exactly that distinction (review finding Important #4).
        reason = str(payload.get("code") or payload.get("error") or "")[:300]
        return _result(Outcome.UNREACHABLE, reason=reason)

    data = payload.get("data") or {}
    metadata = data.get("metadata") or {}
    site_status = int(metadata.get("statusCode") or 200)
    content_type = (metadata.get("contentType") or "").split(";", 1)[0]
    markdown = data.get("markdown") or ""
    html = (data.get("html") or "").encode()
    page_count = metadata.get("numPages")
    total_pages = metadata.get("totalPages")
    # A PDF is billed per page; everything else is one credit for the call.
    credits = int(page_count) if content_type == "application/pdf" and page_count else 1
    # Kept only when it was asked for: an object nobody requested is neither
    # trusted nor billed.
    extract = data.get("json") if json_format is not None else None
    if not isinstance(extract, dict):
        extract = None
    # Carried on every result below, whatever its outcome: the surcharge is
    # billed before any status check, so a first-read cost that counted only
    # served pages would miss the dead, blocked, invalid and shell ones.
    json_credits = JSON_FORMAT_CREDITS if extract is not None else 0
    credits += json_credits

    # Never `or url`: falling back to the requested URL asserts "it did not
    # move" on the one response carrying no evidence for it, and that is
    # exactly the claim require_same_origin then checks.
    final_url = metadata.get("url") or ""
    if not final_url:
        return _result(Outcome.INVALID, credits=credits, reason=REASON_FINAL_URL_MISSING,
                       status_code=site_status, json_credits=json_credits)
    try:
        validate_public_url(final_url)
    except UnsafeTarget:
        return _result(Outcome.INVALID, credits=credits, reason=REASON_FINAL_URL_UNSAFE,
                       status_code=site_status, json_credits=json_credits)

    common: dict[str, Any] = dict(
        final_url=final_url, content_type=content_type, body=html, markdown=markdown,
        status_code=site_status,
        change_status=(data.get("changeTracking") or {}).get("changeStatus"),
        screenshot=str(data.get("screenshot") or "").encode() or None,
        page_count=page_count, total_pages=total_pages,
        json_extract=extract, json_credits=json_credits,
    )

    origin_reason = REASON_ORIGIN_STATUS.format(status=site_status)
    if site_status in _DEAD_TARGET_STATUS:
        return _result(Outcome.DEAD, credits=credits, reason=origin_reason, **common)
    if site_status in _BLOCKING_TARGET_STATUS or site_status >= 500:
        return _result(Outcome.BLOCKED, credits=credits, reason=origin_reason, **common)

    if common["change_status"] == "same":
        # The single largest saving on the whole path: a free comparison
        # against a reader run. Checked before the shell/usable rules below --
        # an unchanged page already proved itself readable last time.
        return _result(Outcome.UNCHANGED, credits=credits, **common)

    # The shell rule is the reader's own (spec §4): fewer than 1,500 readable
    # characters while the raw page is 20 kB or more, read against `html` --
    # whether `html`/`rawHtml` is pre- or post-render is not something the
    # vendor's docs settle (Step 0), so the rule stays keyed on markdown either
    # way, never on which DOM state produced it.
    if (
        content_type in {"", "text/html"}
        and len(markdown) < _MIN_READABLE_CHARS
        and len(html) >= _MIN_BYTES_FOR_FLOOR
    ):
        return _result(Outcome.UNREADABLE, credits=credits, reason=REASON_SHELL, **common)

    # `usable()`'s own vocabulary ("too_large", "challenge", "short_body",
    # "content_type:...") is pinned in types.py, not here -- REASON_SHELL is
    # compared, not reassigned, so a caller reading `reason` sees the same
    # string whichever check found the shell.
    ok, reason = usable(content_type or "text/html", html or markdown.encode(), site_status,
                        markdown=markdown)
    if not ok and reason != REASON_SHELL:
        return _result(Outcome.BLOCKED, credits=credits, reason=reason, **common)

    truncated = bool(total_pages and page_count and int(total_pages) > int(page_count))
    return _result(
        Outcome.FETCHED_PARTIAL if truncated else Outcome.FETCHED,
        credits=credits, reason=REASON_PDF_TRUNCATED if truncated else "", **common,
    )
