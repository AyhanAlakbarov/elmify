"""What a vendor fetch returns, and the two ways it fails.

FetchedPage extends FetchResult rather than replacing it because every consumer
in this repo -- snapshot.py, harvest.py, reader.py, registers.py -- already
speaks FetchResult, and a parallel type would mean touching all of them to gain
three fields.

Outcome is the fetch engine's vocabulary (spec 2026-09-22-fetch-engine-design.md
§6). Eleven of the twelve outcomes are VALUES, not exceptions -- before this, a
blocked fetch and a page that genuinely states nothing both arrived as "no
rules found", and CLAUDE.md records this repo meeting that failure twice.
Nothing here wires Outcome into firecrawl.py/scrapedo.py/__init__.py's
fetch_page yet -- that is a later task in this plan; this module only defines
the names every task after it imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from apps.research.egress import (
    ALLOWED_CONTENT_TYPES,
    MAX_RESPONSE_BYTES,
    FetchResult,
    SourceBlocked,
    looks_unrendered,
)

#: The only labels that may reach OfficialSource provenance. EGRESS survives for
#: europa.eu alone (student PII, its own pinned transport in documents/europass.py).
#: ARCHIVE (rung 6, apps/research/fetch/archive.py) is a capture, not a live
#: fetch -- Outcome.ARCHIVED is the signal a caller must read before trusting
#: its content as current.
FETCHED_VIA = frozenset({"FIRECRAWL", "SCRAPE_DO", "EGRESS", "ARCHIVE"})


class Outcome(StrEnum):
    """The closed set of terminal fetch states (spec §6), plus the one
    intermediate state. A thirteenth member is a design change, not an
    implementation detail -- every caller of fetch_page switches on this set."""

    FETCHED = "FETCHED"
    FETCHED_PARTIAL = "FETCHED_PARTIAL"
    UNCHANGED = "UNCHANGED"
    ARCHIVED = "ARCHIVED"
    UNREADABLE = "UNREADABLE"
    BLOCKED = "BLOCKED"
    UNREACHABLE = "UNREACHABLE"
    DEAD = "DEAD"
    OFF_SITE = "OFF_SITE"
    INVALID = "INVALID"
    BUDGET = "BUDGET"
    #: The one intermediate state, and the one outcome fetch_page() returns that
    #: a content caller cannot act on: it means "nobody answered, ask again after
    #: the FetchAttempt row's retry_after". fetch_page() DOES return it -- the
    #: translation into a raised SourceBlocked for the legacy callers is Task 9's
    #: wrapper (discovery.retrieve_official_source), not this enum's promise.
    RETRY_SCHEDULED = "RETRY_SCHEDULED"


#: Outcomes a caller can read content from.
SERVED = frozenset({Outcome.FETCHED, Outcome.FETCHED_PARTIAL, Outcome.ARCHIVED})

#: A 200 carrying one of these is a challenge interstitial, not a document.
#: Lowercased substring match against the first 4 KiB of the body.
CHALLENGE_MARKERS = (
    b"just a moment",
    b"enable javascript and cookies to continue",
    b"checking your browser",
    b"attention required! | cloudflare",
    b"ddos protection by",
    b"verifying you are human",
)

#: `FetchedPage.reason` values BOTH providers set, defined here once so a
#: caller need not know which vendor produced them -- which is the whole claim,
#: and two identical string literals in two modules cannot guarantee it.
#: `usable()` below contributes its own vocabulary ("too_large", "challenge",
#: "short_body", "shell", "content_type:...").
REASON_FINAL_URL_MISSING = "final_url_missing"
REASON_FINAL_URL_UNSAFE = "final_url_unsafe"
#: Formatted with the ORIGIN's own status code -- never the vendor's outer one.
#: The ladder needs this rather than `outcome` alone to tell a 429 (escalate:
#: the enhanced proxy may still clear it) from a 401 (a credential problem no
#: proxy fixes).
REASON_ORIGIN_STATUS = "origin_{status}"

#: Below this, a 200 is not a document whatever it claims. Measured 2026-09-19:
#: mischolarship.com, HTTP 200, 469 bytes, billed 1 credit.
MIN_DOCUMENT_BYTES = 1_000

#: Types a VENDOR turns into markdown for us (measured 2026-09-22: a PNG is
#: OCR'd through /scrape for 1 credit; DOCX/XLSX/PPTX parse by URL). Usable only
#: when `markdown` is non-empty -- the bytes themselves are unreadable to us.
VENDOR_PARSED_TYPES = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/rtf", "application/epub+zip", "text/csv",
})


class VendorUnavailable(SourceBlocked):
    """A vendor was reachable and refused, or was itself down.

    Subclasses SourceBlocked so every existing caller's except clause still
    catches it -- this plan must not change how a failed fetch propagates.

    ``escalate`` is the second axis, orthogonal to cost: does trying the next
    (25-credit) rung have any chance of a different answer? A 429 or a 502 is
    the VENDOR saying "not now", and the next rung answers a question nobody
    asked -- see the router's docstring for what that cost in a real sweep.
    """

    def __init__(self, message: str, *, escalate: bool = True) -> None:
        super().__init__(message)
        self.escalate = escalate


class ChargedFailure(SourceBlocked):
    """The TARGET failed and the vendor billed us for the attempt anyway.

    The sibling of VendorUnavailable, not a kind of it: a vendor's own failure
    (down, out of credits, rate-limited) costs nothing, and a 404 or a block
    page relayed from the origin costs the full call. The budget below is wrong
    by exactly the failures if the two are one class -- and the failures are the
    half of a sweep nobody plans for.

    ``escalate`` as above. A 404 is dead on every tier and scrape.do's published
    billing counts 404 as a SUCCESS, so escalating one costs 1 + 25 credits for
    a page that does not exist; a 403 is the bot-wall signature and is exactly
    what the residue tier is for.
    """

    def __init__(self, message: str, *, credits: int, escalate: bool = True) -> None:
        super().__init__(message)
        self.credits = credits
        self.escalate = escalate


class FetchBudgetExhausted(SourceBlocked):
    """The sweep's credit budget is spent for this vendor."""


def usable(
    content_type: str, body: bytes, status_code: int, *, markdown: str = ""
) -> tuple[bool, str]:
    """Is this a document a reader can read? Returns (ok, reason-if-not).

    Order matters: the cheapest, most certain refusals first, so the reason a
    caller records is the most specific true one. A vendor-parsed type (an
    image, an office file) is readable only through the markdown the vendor
    made of it; with no markdown there is nothing to read.
    """
    if content_type in VENDOR_PARSED_TYPES and markdown.strip():
        return True, ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        return False, f"content_type:{content_type or 'missing'}"
    if len(body) > MAX_RESPONSE_BYTES:
        return False, "too_large"
    head = body[:4096].lower()
    if any(marker in head for marker in CHALLENGE_MARKERS):
        return False, "challenge"
    if status_code == 200 and len(body) < MIN_DOCUMENT_BYTES:
        return False, "short_body"
    if looks_unrendered(content_type, body):
        return False, "shell"
    return True, ""


@dataclass(frozen=True)
class Attempt:
    """One vendor call. The trail is a tuple of these, oldest first."""

    rung: int
    vendor: str
    outcome: Outcome
    credits: int = 0
    status_code: int | None = None
    reason: str = ""
    duration_ms: int = 0


@dataclass(frozen=True)
class FetchedPage(FetchResult):
    fetched_via: str = "EGRESS"
    cost_credits: int = 0
    #: Firecrawl changeTracking: new | same | changed | removed. None when the
    #: vendor did not report one -- which is not the same as "same", and a caller
    #: that treats it as "same" skips a reader run the page earned.
    change_status: str | None = None
    #: Fetch-engine-core task 1: the vocabulary a later task in this plan wires
    #: into firecrawl.py/scrapedo.py/__init__.py's fetch_page. Defaulted so
    #: today's constructors (which predate Outcome/rung/attempts) keep working
    #: unchanged -- FETCHED at rung 1 is the correct default for a page a
    #: vendor call already returned successfully.
    markdown: str = ""
    outcome: Outcome = Outcome.FETCHED
    rung: int = 1
    status_code: int | None = None
    captured_at: str = ""
    page_count: int | None = None
    total_pages: int | None = None
    screenshot: bytes | None = None
    #: Firecrawl's `json` format answer, when one was asked for (item 15's
    #: first-read gate only). Unverified vendor output: nothing may take a quote
    #: from it without apps.research.first_read's check against `markdown`.
    json_extract: Mapping[str, Any] | None = None
    #: The part of `cost_credits` the json format added, on EVERY result that billed it
    #: (DEAD/BLOCKED/INVALID/shell pages included), so a first-read cost misses none.
    json_credits: int = 0
    reason: str = ""
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.fetched_via not in FETCHED_VIA:
            raise ValueError(f"unknown fetched_via {self.fetched_via!r}")

    @property
    def ok(self) -> bool:
        """True when a reader may read this page's content."""
        return self.outcome in SERVED
