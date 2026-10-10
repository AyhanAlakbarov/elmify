"""The site-level Firecrawl endpoints: /map, /crawl, its errors, /agent.

Page fetches live in firecrawl.py; this module never fetches a page. It
returns ADDRESSES, which is the whole shape of the funnel (spec 7.0): every
URL any of these endpoints produces goes back through `fetch_page` and is
validated against the institution's origin before anything is read or stored.

One credit per /map call whatever it returns, 1 per crawled page plus 1 per
PDF page, dynamic billing on /agent with `maxCredits` set on every call.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import urllib3
from django.conf import settings

from apps.research.egress import _RETRY_ATTEMPTS, _backoff_seconds

logger = logging.getLogger(__name__)

_BASE = "https://api.firecrawl.dev/v2"
#: Firecrawl's documented /map ceiling and this repo's default.
_MAP_LIMIT = 500
Post = Callable[[str, bytes, dict[str, str]], tuple[int, bytes, Mapping[str, str]]]
Get = Callable[[str, dict[str, str]], tuple[int, bytes, Mapping[str, str]]]


class FirecrawlSiteError(RuntimeError):
    """A site-level call failed. Never a fact about the site.

    Separate from `VendorUnavailable` on purpose: that class subclasses
    `SourceBlocked`, and every caller in this repo treats `SourceBlocked` as
    "this source is blocked, degrade and carry on". A /map that 500s is not a
    blocked source, and laundering it into one is how a stage failure becomes
    a programme recorded `not found`.
    """


@dataclass(frozen=True)
class MapResult:
    urls: tuple[str, ...]
    credits: int


def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "POST", url, body=body, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=200), retries=False,
    )
    # response.headers, not dict(...): it is urllib3's case-insensitive
    # HTTPHeaderDict and `_backoff_seconds` looks "Retry-After" up by that
    # casing. HTTP/2 lowercases header names on the wire.
    return response.status, response.data, response.headers


def _get(url: str, headers: dict[str, str]) -> tuple[int, bytes, Mapping[str, str]]:
    response = urllib3.request(
        "GET", url, headers=headers,
        timeout=urllib3.Timeout(connect=10, read=120), retries=False,
    )
    return response.status, response.data, response.headers


def _headers(api_key: str) -> dict[str, str]:
    if not api_key:
        # Absent key -> raise at call time. A site-level call that returned an
        # empty list here would read as "this site has no pages", which is the
        # silent dead end the whole engine exists to remove.
        raise FirecrawlSiteError("FIRECRAWL_API_KEY is not set")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _call(
    path: str,
    payload: Mapping[str, object],
    *,
    api_key: str,
    post: Post,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, object]:
    """One POST with the 429/5xx back-off of spec 9.3 (1s, 2s, 4s ... 60s).

    Shared with /crawl and /agent because a site-level 429 is the same event
    as a page-level one and `firecrawl.py` already owns the schedule; a second
    back-off with its own numbers would drift from it silently.
    """
    headers = _headers(api_key)
    body = json.dumps(payload).encode()
    for attempt in range(_RETRY_ATTEMPTS + 1):
        try:
            status, raw, response_headers = post(f"{_BASE}{path}", body, headers)
        except urllib3.exceptions.HTTPError as error:
            # Narrow on purpose: urllib3's timeouts, TLS and DNS failures all
            # inherit HTTPError. A bare `except Exception` would turn our own
            # TypeError into a vendor problem and hide the defect.
            if attempt == _RETRY_ATTEMPTS:
                raise FirecrawlSiteError(f"{path}: {type(error).__name__}") from error
            sleep(_backoff_seconds(None, attempt))
            continue
        if status == 429 or status >= 500:
            if attempt == _RETRY_ATTEMPTS:
                raise FirecrawlSiteError(f"{path} answered HTTP {status}")
            sleep(_backoff_seconds(SimpleNamespace(headers=response_headers), attempt))
            continue
        if status != 200:
            raise FirecrawlSiteError(f"{path} answered HTTP {status}")
        try:
            document = json.loads(raw)
        except ValueError as error:
            raise FirecrawlSiteError(f"{path} returned non-JSON") from error
        if not isinstance(document, dict):
            raise FirecrawlSiteError(f"{path} returned a non-object body")
        if not document.get("success", True):
            raise FirecrawlSiteError(f"{path}: {str(document.get('error'))[:120]}")
        return cast(dict[str, object], document)
    raise FirecrawlSiteError(f"{path}: retries exhausted")


def map_site(
    url: str,
    *,
    api_key: str,
    search: Sequence[str] = (),
    limit: int = _MAP_LIMIT,
    ignore_cache: bool = False,
    post: Post = _post,
) -> MapResult:
    """POST /v2/map -- every address the site publishes. 1 credit per call.

    The unfiltered fallback is not defensive coding: measured 2026-09-15, the
    `search` filter returned ZERO for a site the unfiltered call mapped at 76.
    A stage that answers "no pages" for a site with 76 is worse than one that
    costs a second credit. It runs only when a filter was actually asked for --
    otherwise a genuinely empty site pays twice to prove it is empty, on every
    host in a sweep.

    `ignoreCache` is passed at the start of a cycle only: Firecrawl caches
    sitemaps for seven days, so the first map of a cycle is reading last
    cycle's site, and every map after that within the cycle must use the cache
    or bypassing it buys nothing.
    """
    payload: dict[str, object] = {
        "url": url,
        "includeSubdomains": True,
        "ignoreQueryParameters": True,
        "limit": limit,
        # `skip` misses PDFs listed only in the sitemap -- and a PDF listed
        # only in the sitemap is precisely the application-documents checklist
        # nothing on the site links to from a crawlable page.
        "sitemap": "include",
    }
    if ignore_cache:
        payload["ignoreCache"] = True
    filtered = dict(payload)
    if search:
        filtered["search"] = " ".join(search)
    document = _call("/map", filtered, api_key=api_key, post=post)
    urls = _links(document)
    credits = 1
    if not urls and search:
        document = _call("/map", payload, api_key=api_key, post=post)
        urls = _links(document)
        credits = 2
    return MapResult(urls=urls, credits=credits)


def _as_list(document: Mapping[str, object], key: str) -> list[object]:
    """A vendor JSON field read as a list, or empty -- never `object`, which
    is what `Mapping[str, object].get(...) or []` types as and is not
    iterable to mypy."""
    value = document.get(key)
    return value if isinstance(value, list) else []


def _links(document: Mapping[str, object]) -> tuple[str, ...]:
    found: list[str] = []
    for entry in _as_list(document, "links"):
        url = str(entry.get("url") or "") if isinstance(entry, dict) else str(entry)
        if url and url not in found:
            found.append(url)
    return tuple(found)


#: A list of what to SKIP is easy to complete; a list of what to keep is not
#: (typed-decisions 7). One short RE2 pattern per term, Firecrawl's own
#: guidance -- a long alternation is rejected or slow.
EXCLUDE_PATHS = (
    ".*/news.*", ".*/event.*", ".*/staff.*", ".*/people.*",
    ".*/login.*", ".*/press.*", ".*/blog.*",
)
#: How long a crawl may take before the job is abandoned and its URLs are
#: fetched one at a time. A sweep that blocks forever on one host's crawl is
#: a sweep that never reaches the other 57.
_CRAWL_DEADLINE_SECONDS = 600
_CRAWL_POLL_SECONDS = 5


@dataclass(frozen=True)
class CrawlResult:
    job_id: str
    #: Pages the site served, ready for the per-page triage.
    urls: tuple[str, ...]
    #: In `data` with a 4xx of their own -- never read as pages.
    dead: tuple[str, ...]
    #: From the errors endpoint. Each re-enters the per-URL ladder at rung 3.
    errors: tuple[str, ...]
    #: From the errors endpoint. Written to the host profile and never fetched
    #: by any tier.
    robots_blocked: tuple[str, ...]
    credits: int
    status: str


def crawl_ceiling(limit: int) -> int:
    """The worst-case credits one crawl can cost: 1 per page plus 1 per PDF
    page. Checked against the sweep budget BEFORE the job is submitted --
    Firecrawl's own pre-flight answers 402 for a limit the balance cannot
    cover, and a 402 arriving mid-sweep is a bill nobody chose."""
    return limit * (1 + int(settings.FETCH_PDF_MAX_PAGES))


def crawl(
    url: str,
    *,
    api_key: str,
    limit: int,
    tag: str,
    include_paths: Sequence[str] = (),
    allow_external: bool = True,
    max_concurrency: int | None = None,
    delay: float | None = None,
    post: Post = _post,
    get: Get = _get,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> CrawlResult:
    """POST /v2/crawl, wait for it, and ALWAYS read the errors endpoint.

    `crawlEntireDomain` because the default follows children only and a
    requirements page is usually a SIBLING of the programme page (`/msc-ai/`
    and `/application/documents/`) -- without it the crawl never reaches the
    most common location the 2026-09-15 site survey found.

    `scrapeOptions` is rung 1 with `changeTracking`, so every crawled page is
    also a monitor baseline (spec 8); a crawl whose options differ produces
    pages the monitor reports as `changed` on their first check, for nothing.

    Raises `FirecrawlSiteError` rather than returning a `CrawlResult` unless
    the job itself reported `completed`. Two ways it does not: the
    `_CRAWL_DEADLINE_SECONDS` poll budget runs out with the job still
    `scraping` (or `data`/`status` at their initial placeholder if the
    deadline was already past on entry -- the `while ... else` below covers
    both), or the job finishes `failed`/`cancelled`. Both used to fall
    through to an ordinary `CrawlResult` built from whatever partial `data`
    the last poll held, under a `status` of "scraping" or "failed" that
    nothing read -- a crawl read from its status alone "reports a perfect
    run over a site it half-read" (CLAUDE.md), and silently returning a
    partial result on a **known-incomplete** job is that same failure with
    extra steps. A job that did not finish has no page list this function is
    willing to vouch for -- the caller retries or escalates, it does not
    triage a partial crawl as if it were a complete one.

    `allow_external=False` for any caller that must never point a vendor at a
    portal (CLAUDE.md): with `allowExternalLinks` on, Firecrawl ITSELF fetches
    -- and bills -- an off-domain link whose path matches an include term, and
    a year token makes `portal.other.example/2027/apply` qualify. The caller's
    own-domain filter runs on the returned URLs, after that fetch was made.
    """
    payload: dict[str, object] = {
        "url": url,
        "limit": limit,
        "crawlEntireDomain": True,
        "allowSubdomains": True,
        # The one-hop linked PDF on a CDN or a funder's site. External
        # HOMEPAGES are skipped by Firecrawl and reported as EXTERNAL_LINK,
        # so this does not open the crawl onto the web -- but it does fetch
        # any external page whose path matches `includePaths` (see above).
        "allowExternalLinks": allow_external,
        "maxDiscoveryDepth": 2,
        "sitemap": "include",
        "ignoreQueryParameters": True,
        "excludePaths": list(EXCLUDE_PATHS),
        "maxConcurrency": int(
            max_concurrency if max_concurrency is not None else settings.FIRECRAWL_CONCURRENCY
        ),
        "scrapeOptions": {
            "formats": ["markdown", "html", {"type": "changeTracking", "tag": tag}],
            "onlyMainContent": False,
            "parsers": [
                {
                    "type": "pdf",
                    "maxPages": int(settings.FETCH_PDF_MAX_PAGES),
                    "pageMarkers": True,
                }
            ],
            "skipTlsVerification": True,
            "blockAds": True,
        },
    }
    if include_paths:
        payload["includePaths"] = [f".*{re.escape(term)}.*" for term in include_paths]
    if delay is not None:
        payload["delay"] = delay
    started = _call("/crawl", payload, api_key=api_key, post=post, sleep=sleep)
    job_id = str(started.get("id") or "")
    if not job_id:
        raise FirecrawlSiteError("/crawl returned no job id")
    headers = _headers(api_key)
    deadline = now() + _CRAWL_DEADLINE_SECONDS
    status = "scraping"
    data: list[Mapping[str, object]] = []
    while now() < deadline:
        state = _get_json(f"{_BASE}/crawl/{job_id}", headers, get=get)
        status = str(state.get("status") or "")
        data = [entry for entry in _as_list(state, "data") if isinstance(entry, dict)]
        if status in {"completed", "failed", "cancelled"}:
            break
        sleep(_CRAWL_POLL_SECONDS)
    else:
        # The poll budget ran out with the job never reaching a terminal
        # status -- including the case where `deadline` was already past on
        # entry, in which case `status` is still its "scraping" placeholder.
        raise FirecrawlSiteError(
            f"/crawl/{job_id} did not finish within {_CRAWL_DEADLINE_SECONDS}s "
            f"(last status {status!r})"
        )
    if status != "completed":
        raise FirecrawlSiteError(f"/crawl/{job_id} ended {status!r}, not completed")
    served: list[str] = []
    dead: list[str] = []
    for page in data:
        metadata = page.get("metadata") or {} if isinstance(page, dict) else {}
        page_url = str(metadata.get("url") or "")
        if not page_url:
            continue
        # A page the site answered 404 is in `data`, not `errors`, with its own
        # statusCode. Reading it as a page archives a 404 body under the
        # institution's provenance and quotes it into the shared catalog.
        code = metadata.get("statusCode")
        (dead if isinstance(code, int) and code >= 400 else served).append(page_url)
    errors_document = _get_json(f"{_BASE}/crawl/{job_id}/errors", headers, get=get)
    errors = tuple(
        str(entry.get("url") or "")
        for entry in _as_list(errors_document, "errors")
        if isinstance(entry, dict) and entry.get("url")
    )
    robots = tuple(str(entry) for entry in _as_list(errors_document, "robotsBlocked"))
    return CrawlResult(
        job_id=job_id,
        urls=tuple(served),
        dead=tuple(dead),
        errors=errors,
        robots_blocked=robots,
        credits=len(served) + len(dead),
        status=status,
    )


def _get_json(url: str, headers: dict[str, str], *, get: Get) -> Mapping[str, object]:
    try:
        status, raw, _headers_out = get(url, headers)
    except urllib3.exceptions.HTTPError as error:
        raise FirecrawlSiteError(f"{url}: {type(error).__name__}") from error
    if status != 200:
        raise FirecrawlSiteError(f"{url} answered HTTP {status}")
    try:
        document = json.loads(raw)
    except ValueError as error:
        raise FirecrawlSiteError(f"{url} returned non-JSON") from error
    # Matches `_call`, which raises on exactly this rather than degrading:
    # a 200 carrying a JSON array from `/crawl/{id}/errors` used to come back
    # as `{}` here, reporting zero errors and zero robots-blocked from the
    # ONE endpoint that records anything in a crawl failed.
    if not isinstance(document, dict):
        raise FirecrawlSiteError(f"{url} returned a non-object body")
    return document


#: The vendor's own label for a lead. Never trusted, never stored -- it only
#: orders the leads so the likeliest documents list is fetched first.
AGENT_KINDS = (
    "documents_list", "cv_guideline", "letter_guideline", "template", "faq", "other",
)
#: extra="forbid" on every schema (the repo's LLM baseline), and here it also
#: keeps the answer small -- which is what Firecrawl bills on.
AGENT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pages"],
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url", "kind", "why"],
                "properties": {
                    "url": {"type": "string"},
                    "kind": {"type": "string", "enum": list(AGENT_KINDS)},
                    "why": {"type": "string"},
                },
            },
        }
    },
}


@dataclass(frozen=True)
class AgentResult:
    #: (url, kind) pairs, deduplicated, in the order the agent returned them.
    leads: tuple[tuple[str, str], ...]
    credits: int


def agent(
    *,
    api_key: str,
    urls: Sequence[str],
    prompt: str,
    max_credits: int | None = None,
    effort: str = "low",
    post: Post = _post,
) -> AgentResult:
    """POST /v2/agent -- the navigator. Its answer is discarded.

    **WARNING, read before wiring this into anything: this function returns
    ARBITRARY OPEN-WEB URLs today.** `urls` SEEDS the run; it does not
    confine it. Read from Firecrawl's own /agent page 2026-09-23: the agent
    can still use web search and navigate beyond those sites, and
    `strictConstrainToURLs: true` confines it to EXACTLY the URLs given,
    which makes an agent whose job is to find pages useless. So there is no
    "stay on the official site" setting and the 2026-09-22 text that assumed
    one was wrong.

    The entire safety argument for calling this function is that every URL
    it returns is re-fetched through the ladder and checked with
    `require_origin` before anything is read or stored -- **and that check
    does not exist anywhere on this branch.** The funnel seam that would call
    `agent()` and then apply it is a separate, unexecuted plan; until that
    seam exists and enforces `require_origin`, any caller of this function
    is handing whoever wrote the seed page's content an unchecked list of
    URLs to whatever the platform does with `AgentResult.leads` next. Do not
    wire a caller onto this function without `require_origin` (or
    equivalent) sitting between it and any read/write/storage. What makes
    the open-web search safe is the funnel's `require_origin` check, not a
    vendor flag (owner decision 2026-09-23): only URLs are taken from the
    answer, every one goes through the ladder and must pass `require_origin`
    against the institution's or the funder's site, and nothing else it
    produced is stored -- the standing rule for Exa and Brave, whose
    upstream indexes we have likewise not read.

    `maxCredits` is SET ON EVERY CALL. The documented default is 2,500
    credits a run, about $2 at Standard.
    """
    payload = {
        "urls": list(urls),
        "prompt": prompt,
        "schema": AGENT_SCHEMA,
        "effort": effort,
        "maxCredits": int(
            max_credits if max_credits is not None else settings.FETCH_AGENT_MAX_CREDITS
        ),
    }
    document = _call("/agent", payload, api_key=api_key, post=post)
    data = document.get("data") or {}
    pages = data.get("pages") or [] if isinstance(data, dict) else []
    leads: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        url = str(page.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        kind = str(page.get("kind") or "other")
        # An unknown kind becomes `other` rather than dropping the lead: the
        # kind is the vendor's word and is never trusted, while the URL is the
        # only thing the call was paid for.
        leads.append((url, kind if kind in AGENT_KINDS else "other"))
        logger.info("navigator lead %s (%s): %s", url, kind, str(page.get("why") or "")[:120])
    credits_used = document.get("creditsUsed")
    credits = int(credits_used) if isinstance(credits_used, (int, float)) else 0
    return AgentResult(leads=tuple(leads), credits=credits)


#: Below this, `concurrencyLimited` means "you waited", which every busy
#: minute produces. Halving on that would walk a sweep down to 1 and keep it
#: there for the rest of the run.
_QUEUE_BACKPRESSURE_MS = 10_000


@dataclass
class Pressure:
    """One sweep's concurrency, lowered by the vendor's own queue signal.

    Mutable and process-local on purpose. Spec 9.3: no distributed semaphore
    -- the vendors queue over-limit work themselves, and a counter shared
    across ECS tasks would be a second implementation of what they already
    enforce, with its own failure modes and none of their information.
    """

    concurrency: int = 0

    def __post_init__(self) -> None:
        if not self.concurrency:
            self.concurrency = int(settings.FIRECRAWL_CONCURRENCY)


def note_concurrency(metadata: Mapping[str, object], pressure: Pressure) -> None:
    """Halve the sweep's concurrency when the vendor says it queued us long.

    Per SWEEP, not per call: a limit that reset on the next page would
    re-learn the same lesson on every page of the run.
    """
    if not metadata.get("concurrencyLimited"):
        return
    queued = metadata.get("concurrencyQueueDurationMs")
    if not isinstance(queued, (int, float)) or queued < _QUEUE_BACKPRESSURE_MS:
        return
    before = pressure.concurrency
    pressure.concurrency = max(1, before // 2)
    if pressure.concurrency != before:
        logger.info(
            "firecrawl queued us %sms; concurrency %d -> %d for the rest of the sweep",
            queued, before, pressure.concurrency,
        )
