"""Rung 6: the Internet Archive.

Measured 2026-09-15: this is what recovered DAAD's PRIME FAQ (captured
2026-06-25) and Sciences Po's application-file page (2026-02-01) -- two hosts
that refuse our connections and every vendor tier alike.

The window is an OWNER DECISION (2026-09-22): twelve months
(`FETCH_ARCHIVE_MAX_AGE_DAYS`, added in Task 1), because a rule captured within
the current admissions cycle is the rule applicants are held to. An older
capture is `archive_stale` and reaches a person, never the catalog.

A capture is a DIFFERENT claim about the world than a live fetch -- "this page
looked like this on some past date", never "this is what the page says now" --
which is why every result here is `Outcome.ARCHIVED`, not `Outcome.FETCHED`,
and carries `captured_at`.

The availability PROBE is a keyless JSON data lookup, not a page, and it is
fetched through `egress.fetch_data_file` -- our own DATA transport -- never
through a vendor. Two reasons: a real Wayback payload is ~202 bytes, and
`scrapedo.scrape`'s `usable()` floor refuses any 200 under
`types.MIN_DOCUMENT_BYTES` (1,000) -- routing the probe through that floor
made every `latest_capture` call return UNREACHABLE regardless of the URL,
invisibly, because every prior test hand-built its `FetchedPage` and never
exercised the real predicate. It is also the same principle CLAUDE.md states
for XML sitemaps: "a file meant to be parsed as data is fetched as bytes, not
read as a page." The CAPTURE bytes stay on `scrapedo.scrape` at rung 3 -- that
part is a page, and it goes through the vendor for the same reason every
other fetch does.

This gives the module a genuinely mixed error contract, on purpose: `probe`
(`egress.fetch_data_file`) RAISES (`SourceBlocked`/`UnsafeTarget`) on failure;
`fetch` (`scrapedo.scrape`) RETURNS a value (a non-FETCHED `Outcome`) for a
target-side failure and RAISES `VendorUnavailable` only for a vendor-side one.
`latest_capture` handles both shapes at both call sites -- a future ladder
composing this rung with others must do the same, never assume one shape.

The same-origin check compares the WRAPPED url -- the original URL the archive
claims a capture is of -- against the URL we asked for, never against
web.archive.org's own origin. It runs twice: once against the availability
API's `closest.url` before any capture bytes are fetched, and again against
the raw capture fetch's own `final_url` afterward, because Wayback's `id_`
redirect (or a compromised hop) can legitimately land the bytes somewhere
other than what the index claimed. A capture whose claimed URL cannot even be
parsed out is refused rather than assumed same-origin -- fail closed, never
open. Separately, and as hardening rather than a fix for a demonstrated hole,
the raw fetch's own host must be web.archive.org: the wrapped-url check alone
cannot tell an archive capture from any host willing to serve a path shaped
like one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from django.conf import settings

from apps.research.egress import (
    FetchResult,
    OffSiteRedirect,
    SourceBlocked,
    UnsafeTarget,
    fetch_data_file,
    require_same_origin,
)

from .scrapedo import scrape
from .types import Attempt, FetchedPage, Outcome, VendorUnavailable

AVAILABILITY = "https://archive.org/wayback/available"

#: The original URL a Wayback capture wraps sits after "/web/<timestamp><flags>/"
#: in the `url` a capture record reports -- pulled by pattern rather than by
#: splitting on the exact `timestamp` field, because that field and the URL's
#: own timestamp are not guaranteed to share the same width.
_CAPTURED_URL = re.compile(r"/web/\d+[a-zA-Z_]*/(https?://.+)$")

#: A Wayback timestamp is exactly fourteen digits (YYYYMMDDHHMMSS). Validated
#: as a whole before use anywhere: the raw capture URL interpolates this value
#: unsliced, so a value carrying a path separator (e.g.
#: "20260625120000/https://evil.test/p?") would otherwise route the fetch to a
#: different host while a separately crafted `closest.url` satisfies the
#: origin gate above it.
#: `[0-9]`, never `\d`: in Python `\d` matches every Unicode decimal digit, so
#: fourteen Arabic-Indic digits ("٢٠٢٦٠٦٢٥١٢٠٠٠٠") passed `fullmatch` and then
#: raised ValueError out of `strptime` below -- escaping this function AND
#: `fetch_page`, whose contract is that only a programming error leaves it. No
#: injection was possible (no separator matches either class); the broken
#: contract was the whole defect.
_TIMESTAMP = re.compile(r"[0-9]{14}")

#: The only host a capture may be served from. See the second origin check.
_ARCHIVE_HOST = "web.archive.org"

Fetch = Callable[..., FetchedPage]
Probe = Callable[[str], FetchResult]


def _as_dict(value: Any) -> dict[str, Any]:
    """`closest`, `archived_snapshots` and the whole payload are all untrusted
    vendor JSON -- valid JSON that is a string or a list (not a dict) must not
    raise `AttributeError` on the next `.get()` in the chain."""
    return value if isinstance(value, dict) else {}


def _refused(url: str, outcome: Outcome, reason: str, credits: int) -> FetchedPage:
    return FetchedPage(
        final_url=url, redirects=(), content_type="", body=b"", markdown="",
        outcome=outcome, fetched_via="ARCHIVE", rung=6, cost_credits=credits, reason=reason,
        attempts=(Attempt(rung=6, vendor="ARCHIVE", outcome=outcome, credits=credits,
                          reason=reason),),
    )


def _closest(url: str, *, timestamp: datetime, probe: Probe) -> dict[str, Any] | FetchedPage:
    """Ask the availability API for the capture closest to `timestamp`.

    Returns the validated `closest` record with its parsed `captured` datetime
    added, or the refusal page. Shared by `latest_capture` (closest to now) and
    `capture_near` (closest to a past date); neither adds a check of its own
    here -- the age rule is each caller's, passed to `_from_closest`.
    """
    # Measured 2026-09-22: the availability API found DAAD's 2026-06-25 capture
    # under the BARE form (host/path[?query]) and returned nothing for the same
    # URL with its https:// scheme. Strip the scheme before asking.
    bare = urlsplit(url)._replace(scheme="", fragment="").geturl().lstrip("/")
    lookup = f"{AVAILABILITY}?url={quote(bare, safe='')}&timestamp={timestamp:%Y%m%d}"

    try:
        probe_result = probe(lookup)
    except (SourceBlocked, UnsafeTarget):
        # The archive itself is down or refused the probe -- measured
        # 2026-09-22, its CDX index served "Temporarily Offline" for the whole
        # probe window. That is a retry, never "no capture exists": the ladder
        # re-enters rung 6 on the next retry round. fetch_data_file's own
        # contract already turns a non-2xx/throttled/redirect-looped response
        # into exactly one of these two exceptions, so there is no separate
        # status-code check to make here.
        return _refused(url, Outcome.UNREACHABLE, "archive_unavailable", 0)

    try:
        payload = _as_dict(json.loads(probe_result.body))
    except ValueError:
        return _refused(url, Outcome.UNREACHABLE, "archive_unavailable", 0)

    closest = _as_dict(_as_dict(payload.get("archived_snapshots")).get("closest"))
    if not closest.get("available"):
        return _refused(url, Outcome.BLOCKED, "archive_absent", 0)

    raw_timestamp = str(closest.get("timestamp", ""))
    if not _TIMESTAMP.fullmatch(raw_timestamp):
        # An unparseable capture is not an absent one -- do not report this as
        # "archive_absent", which tells a person the wrong thing.
        return _refused(url, Outcome.BLOCKED, "archive_timestamp_invalid", 0)
    captured = datetime.strptime(raw_timestamp[:8], "%Y%m%d").replace(tzinfo=UTC)
    return {**closest, "timestamp": raw_timestamp, "captured": captured}


def latest_capture(
    url: str, *, api_key: str, now: datetime | None = None,
    fetch: Fetch = scrape, probe: Probe = fetch_data_file,
) -> FetchedPage:
    now = now or datetime.now(UTC)
    closest = _closest(url, timestamp=now, probe=probe)
    if isinstance(closest, FetchedPage):
        return closest
    max_age = timedelta(days=settings.FETCH_ARCHIVE_MAX_AGE_DAYS)
    return _from_closest(
        url, closest, api_key=api_key, fetch=fetch,
        age_check=lambda captured: (
            f"archive_stale:{captured:%Y-%m-%d}" if now - captured > max_age else None
        ),
    )


def capture_near(
    url: str, *, at: date, api_key: str,
    fetch: Fetch = scrape, probe: Probe = fetch_data_file,
) -> FetchedPage:
    """The capture closest to `at` -- evidence of an EARLIER cycle (spec 9.2, step 1b).

    Not subject to FETCH_ARCHIVE_MAX_AGE_DAYS, which bounds how old a capture
    may be when it stands in for the page as it is NOW (rung 6). A capture
    asked for as history is meant to be old; it must only be near the date
    asked for, or it describes a different cycle.
    """
    moment = datetime(at.year, at.month, at.day, tzinfo=UTC)
    closest = _closest(url, timestamp=moment, probe=probe)
    if isinstance(closest, FetchedPage):
        return closest
    skew = timedelta(days=settings.CYCLE_ARCHIVE_SKEW_DAYS)
    return _from_closest(
        url, closest, api_key=api_key, fetch=fetch,
        age_check=lambda captured: (
            f"archive_skew:{captured:%Y-%m-%d}" if abs(captured - moment) > skew else None
        ),
    )


def _from_closest(
    url: str, closest: dict[str, Any], *, api_key: str, fetch: Fetch,
    age_check: Callable[[datetime], str | None],
) -> FetchedPage:
    """Everything after the probe: the age rule, both origin checks, the fetch."""
    raw_timestamp: str = closest["timestamp"]
    captured: datetime = closest["captured"]
    captured_at = f"{captured:%Y-%m-%d}"

    refusal = age_check(captured)
    if refusal is not None:
        return _refused(url, Outcome.BLOCKED, refusal, 0)

    # The URL the capture claims to be is what a caller of this function would
    # actually be trusting -- never web.archive.org's own origin, which is only
    # ever the transport. A capture whose claimed URL cannot even be parsed out
    # is refused rather than assumed same-origin.
    match = _CAPTURED_URL.search(str(closest.get("url", "")))
    captured_url = match.group(1) if match else str(closest.get("url", ""))
    try:
        require_same_origin(
            url, FetchResult(final_url=captured_url, redirects=(), content_type="", body=b"")
        )
    except OffSiteRedirect:
        return _refused(url, Outcome.OFF_SITE, f"archive_origin:{captured_url}"[:300], 0)

    # `id_` returns the original bytes without the archive's own toolbar; without
    # it every archived page carries injected markup the reader would have to
    # strip. `raw_timestamp` is the value validated above, never the field read
    # a second time.
    raw = f"https://web.archive.org/web/{raw_timestamp}id_/{url}"
    try:
        page = fetch(raw, api_key=api_key, rung=3)
    except VendorUnavailable as error:
        # scrape.do transport failures and configuration errors (no key, an
        # unsafe url) raise rather than return a value -- this is that
        # module's own contract, and it must not escape this one.
        return _refused(url, Outcome.UNREACHABLE, f"archive_unfetchable:{error}"[:300], 0)

    credits = page.cost_credits
    if page.outcome not in {Outcome.FETCHED, Outcome.FETCHED_PARTIAL}:
        return _refused(url, Outcome.BLOCKED, f"archive_unfetchable:{page.reason}"[:300], credits)

    # The bytes' OWN final_url, not an assumption that they landed where we
    # asked: Wayback's id_ redirect can legitimately serve the nearest
    # snapshot rather than the exact one probed for, and nothing upstream of
    # this line has checked where the fetch actually ended up.
    wrapped_match = _CAPTURED_URL.search(page.final_url)
    wrapped_final = wrapped_match.group(1) if wrapped_match else ""
    # HARDENING, not a fix for a known hole: no path to this has been
    # demonstrated. The check above reads the WRAPPED url out of `final_url`
    # and never asks whose host served it, so
    # "https://evil.test/web/20260101id_/https://daad.de/prime" satisfies it.
    # Reaching that needs Wayback to redirect off-archive with a crafted path,
    # and it rewrites `Location` to stay on its own host. The reason the line
    # is here anyway: this rung has two origin checks precisely so that a
    # capture cannot launder provenance onto the original URL, and a transport
    # we never verified is exactly that laundering.
    if urlsplit(page.final_url).hostname != _ARCHIVE_HOST:
        return _refused(url, Outcome.OFF_SITE, f"archive_transport:{page.final_url}"[:300], credits)
    try:
        require_same_origin(
            url, FetchResult(final_url=wrapped_final, redirects=(), content_type="", body=b"")
        )
    except OffSiteRedirect:
        return _refused(url, Outcome.OFF_SITE, f"archive_unwrapped:{page.final_url}"[:300], credits)

    attempt = Attempt(rung=6, vendor="ARCHIVE", outcome=Outcome.ARCHIVED, credits=credits,
                      status_code=page.status_code, reason=f"captured:{captured_at}")
    return FetchedPage(
        # Provenance is the ORIGINAL url, not the archive's wrapper -- the
        # capture is a copy of that page, and every rule derived from it carries
        # the capture date so a person can see how old the evidence is.
        final_url=url, redirects=page.redirects, content_type=page.content_type,
        body=page.body, markdown=page.markdown, outcome=Outcome.ARCHIVED,
        fetched_via="ARCHIVE", rung=6, cost_credits=credits, status_code=page.status_code,
        captured_at=captured_at, attempts=(attempt,),
    )
