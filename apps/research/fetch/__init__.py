"""The fetch engine: one seam, six rungs, twelve outcomes.

Design: docs/superpowers/specs/2026-09-22-fetch-engine-design.md §4.

Firecrawl first, scrape.do after it, the Internet Archive last, nothing else.
Our own client is not a tier here: anti-bot handling, challenge solving and JS
rendering are a vendor's job (owner decision 2026-09-19), and europa.eu -- the
one path carrying student PII -- never comes through this module at all. It
keeps its own pinned transport in apps/documents/europass.py.

**Nothing here raises for a failed fetch.** Eleven of the twelve outcomes are
values, because before this engine a blocked fetch and a page that genuinely
states nothing arrived at the reader as the same thing, and CLAUDE.md records
this repo meeting that failure twice. `FetchBudgetExhausted` is turned into the
`BUDGET` outcome rather than allowed to escape -- it subclasses `SourceBlocked`,
so one escaping would reach a caller's `except SourceBlocked` as "this host is
blocked" and be retried forever. Only a programming error leaves this function.

Three rules decide the code (spec §4):

1. **Nothing is a dead end without a recorded reason.** Every rung writes a
   `FetchAttempt`; the returned page's `attempts` is the whole trail, oldest
   first.
2. **A rung is skipped only because the host profile learned it was useless**,
   never because a heuristic guessed. Rung 1 *is* the classifier.
3. **The origin's answer is final where it is an answer.** `DEAD` stops the
   ladder -- a different proxy will not change a 404 -- and so do `INVALID` and
   `OFF_SITE`, which are our own refusals: retrying them spends money to be
   refused again.

**Not every failure earns the next rung, and the two providers do not agree on
which.** A vendor failure answers one of two different questions:

* *"this host beat us"* -- a relayed 403, Firecrawl's HTTP 200 + ``success:
  false`` ("all scraping engines failed"), a shell that survived a render. A
  residential browser is a genuinely different attempt, so the 25 credits are
  the point. This escalates.
* *"not now"* -- an outer 429, a 502, a dropped connection, a 402, a missing
  key. The host was never asked, so a second vendor answers a question about
  *us*. Firecrawl's free tier is 10 requests/minute and a ``discover`` sweep
  paces per DOMAIN, so 58 distinct hosts go out at 30-60/minute: without this
  rule most of that sweep 429s and **each 429 spends 25 credits on a page
  Firecrawl would have served for 1 a minute later**. It may fall to rung 3 (a
  different network, 1 credit) or to rung 5's retry queue. It never buys rung 4.

`firecrawl.py` gets two status codes -- its own and the target's -- so it can
separate those two questions, and reports a relayed 401/403/429 as `BLOCKED`.
`scrapedo.py` gets one, and cannot: its 401 is "bad key or suspended account"
and its 429 is "concurrency limit", both indistinguishable from a target
answering with the same code. So its 401/429 stay `UNREACHABLE` and
non-escalating by ruling. `_escalates` below is where those two contracts are
reconciled; the ladder cannot switch on `Outcome` alone.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.conf import settings
from django.utils import timezone

from ..egress import (
    OffSiteRedirect,
    SourceBlocked,
    UnsafeTarget,
    require_same_origin,
    validate_public_url,
)
from . import archive as archive_module
from . import firecrawl as firecrawl_module
from . import scrapedo as scrapedo_module
from .types import (
    SERVED,
    Attempt,
    ChargedFailure,
    FetchBudgetExhausted,
    FetchedPage,
    Outcome,
    VendorUnavailable,
)

__all__ = [
    "CATALOG_ROLE_NOTE",
    "RUNTIME_ENGINE_WRITE_REFUSED",
    "USD_PER_CREDIT",
    "VENDOR_UNAVAILABLE",
    "ChargedFailure",
    "FetchBudgetExhausted",
    "FetchedPage",
    "SweepBudget",
    "VendorUnavailable",
    "default_budget",
    "fetch_page",
    "remember",
]

#: Firecrawl Standard $83 / 100k credits; scrape.do Hobby $29 / 250k. The plans the
#: owner priced on 2026-09-19 -- change both together when a plan is bought.
#: A credit is not a unit: Firecrawl's is 7.16x scrape.do's, so a single shared
#: credit pool silently makes one vendor's ceiling seven times the other's.
USD_PER_CREDIT: dict[str, float] = {"FIRECRAWL": 83 / 100_000, "SCRAPE_DO": 29 / 250_000}

#: Appended to the `help` of every management command that fetches. One
#: definition: three verbatim copies is three places to update when the
#: catalogue's writer changes again, and two of them will be missed.
CATALOG_ROLE_NOTE = (
    " Every fetch writes a FetchAttempt/HostProfile row, both writable only by the "
    "catalogue's writer: run with DATABASE_ROLE=runtime_engine, as every worker "
    "task does."
)

#: Raised as a CommandError (with .format(error=...)) when a discovery run's write
#: is refused under ProgrammingError. Two commands (discover, read_closed_list)
#: carried this verbatim; one definition here for the same reason as CATALOG_ROLE_NOTE.
RUNTIME_ENGINE_WRITE_REFUSED = (
    "a database write was refused. Two causes look alike here: the shared "
    "catalog is writable only by the runtime_engine role (run with "
    "DATABASE_ROLE=runtime_engine), and "
    "research_consultantresearchtask is under FORCE row-level security keyed "
    "on app.tenant_id. The message says which: ({error})"
)

#: The prefix of an attempt's `reason` when the VENDOR failed (VendorUnavailable)
#: rather than the host. The returned page's own reason says only "unreachable"
#: or "blocked"; the attempt trail is where whose fault it was survives.
VENDOR_UNAVAILABLE = "vendor_unavailable:"

#: Outcomes that end the ladder wherever they occur. DEAD, INVALID and OFF_SITE
#: are ANSWERS -- the origin's or our own -- and no later rung changes them.
_TERMINAL = SERVED | {Outcome.UNCHANGED, Outcome.DEAD, Outcome.INVALID, Outcome.OFF_SITE}

#: Outcomes whose page carries vendor bytes and a vendor-reported final URL, so
#: `require_origin` must be checked against them. UNCHANGED is in here because
#: firecrawl.py builds it from the same `common` as a FETCHED page -- body and
#: all. "No new bytes are trusted" is false for this implementation, and
#: `page.ok` being False is the CALLER's discipline, not this function's
#: guarantee: a caller that asked for provenance gets provenance.
_CARRIES_BYTES = SERVED | {Outcome.UNCHANGED}

#: A block's cool-off doubles from six hours and stops at a week. A host that
#: means it is not persuaded by a fourth attempt an hour later.
_BLOCK_BASE = timedelta(hours=6)
_BLOCK_CAP = timedelta(days=7)

#: Which vendor's cap a rung spends against. Rung 6 fetches its capture through
#: scrape.do (archive.py), so it spends there too.
_VENDOR_BY_RUNG = {1: "FIRECRAWL", 2: "FIRECRAWL", 3: "SCRAPE_DO", 4: "SCRAPE_DO", 6: "SCRAPE_DO"}


class SweepBudget:
    """Credits a sweep may spend, per vendor, reportable in dollars.

    Per vendor because credits do not compare across vendors (USD_PER_CREDIT
    above); ``usd()`` is the number that does, and it is what a run prints.

    The cap is checked AFTER the vendor reports the cost, because scrape.do's
    per-domain multiplier (10-200 credits) is applied server-side and is not
    knowable before the request. So one surprise lands, is recorded, and stops
    the next fetch -- ``check`` refuses the rung before a request is made once a
    cap is passed, so the overspend is paid once rather than on every page left
    in the sweep.
    # ponytail: post-hoc check; reserve-then-settle if one 200-credit call ever matters.
    """

    def __init__(self, credits: dict[str, int]) -> None:
        self.caps = dict(credits)
        self.spent: dict[str, int] = dict.fromkeys(self.caps, 0)
        #: Stamped onto every FetchAttempt this budget pays for, so one sweep's
        #: rows can be totalled without guessing at timestamps.
        self.sweep_id: UUID = uuid4()

    def check(self, vendor: str) -> None:
        if self.spent[vendor] >= self.caps[vendor]:
            raise FetchBudgetExhausted(
                f"{vendor}: {self.spent[vendor]} of {self.caps[vendor]} credits spent"
            )

    def spend(self, vendor: str, credits: int) -> None:
        # Recorded before the refusal, unlike the branch this came from: the
        # credits are gone whether or not the call was within the cap, and a
        # ceiling that forgets the overspend reports it again on the next page.
        self.spent[vendor] += credits
        if self.spent[vendor] > self.caps[vendor]:
            raise FetchBudgetExhausted(
                f"{vendor}: {self.spent[vendor]} credits exceeds the sweep cap {self.caps[vendor]}"
            )

    # There was an `observe_remaining(vendor, credits)` here, lowering a cap to
    # the balance a vendor reports. Nothing reads `Scrape.do-Remaining-Credits`
    # or Firecrawl's credit endpoint, so it had no possible input -- a
    # cap-lowering method with no producer reads as done and is not. It comes
    # back with its producer, in one change.

    def usd(self) -> float:
        return sum(USD_PER_CREDIT[vendor] * credits for vendor, credits in self.spent.items())


def default_budget() -> SweepBudget:
    """The budget a `fetch_page` call gets when the caller passes none.

    A per-call budget bounds one page rather than a sweep, which is the point:
    an unbudgeted call has no ceiling at all, and the reader path (CLAUDE.md,
    `retrieve_official_source`) passes None by design.
    """
    return SweepBudget(settings.FETCH_SWEEP_CREDITS)


def _default_providers() -> dict[str, Callable[..., FetchedPage]]:
    return {
        "firecrawl": firecrawl_module.scrape,
        "scrapedo": scrapedo_module.scrape,
        "archive": archive_module.latest_capture,
    }


def _escalates(page: FetchedPage) -> bool:
    """May this failure buy the 25-credit rung?

    `BLOCKED` is the host's own refusal and `UNREADABLE` is the host's own
    shell -- exactly what a residential browser exists to pass. `UNREACHABLE`
    is where the two providers stop agreeing, and it is decided per provider
    rather than on the outcome (see the module docstring):

    * scrape.do reports its OWN 401/429/502/510 as `UNREACHABLE` with an
      `origin_<status>` reason and cannot tell them from a target's. Never
      escalates -- a bad key or a concurrency limit would otherwise spend 25
      credits on every page of a sweep.
    * Firecrawl's `UNREACHABLE` carries the vendor's own failure code, and only
      "all scraping engines failed" means the host beat `proxy: auto`. A DNS
      failure, or any code this module has not read the docs for, does not --
      rung 3 still runs, and it is rung 3's verdict that buys rung 4.
    """
    if page.outcome in {Outcome.BLOCKED, Outcome.UNREADABLE}:
        return True
    if page.outcome is not Outcome.UNREACHABLE:
        return False
    if page.fetched_via == "SCRAPE_DO":
        return False
    return page.reason == firecrawl_module.REASON_ALL_ENGINES_FAILED


def _rung_plan(profile: Any) -> list[int]:
    """Which rungs to walk, in order, before any escalation is known.

    Rung 2 is never a plan entry: it is reached from rung 1's shell inside the
    walk below, and a profile remembering 2 is remembering "Firecrawl, with
    actions", which still starts at 1.
    """
    start = getattr(profile, "start_rung", 1) or 1
    if start > 1:
        last_probe = getattr(profile, "last_probe_at", None)
        if last_probe is None or timezone.now() - last_probe > timedelta(
            days=settings.FETCH_REPROBE_DAYS
        ):
            # A memory that can only entrench a cost is a tariff, not a memory.
            start = 1
    # Clamped at both ends. `start_rung` is a bare PositiveSmallIntegerField
    # with no validator, so a 5 written by Task 8 (or by hand) would otherwise
    # yield an EMPTY plan: no vendor called, `blocked` False, RETRY_SCHEDULED
    # returned silently three times over before the archive is read.
    start = 1 if start <= 2 else min(start, 4)
    return [rung for rung in (1, 3, 4) if rung >= start]


def _session_id(url: str) -> int:
    """A residential address that changes between pages of one site re-triggers
    the very challenge rung 4 exists to pass, so this is stable ACROSS
    PROCESSES -- `hash()` is salted per process and a retry in a later task
    would land on a different session."""
    return zlib.crc32((urlsplit(url).hostname or "").encode()) % 100_000


def _call(
    rung: int,
    url: str,
    *,
    tag: str | None,
    profile: Any,
    providers: dict[str, Callable[..., FetchedPage]],
) -> FetchedPage:
    """Exactly one vendor call. The walk records every one of them, so a rung
    that escalates within a vendor (1 -> 2) is a second trip round the loop, not
    a second call hidden in here."""
    if rung in {1, 2}:
        return providers["firecrawl"](
            url, api_key=settings.FIRECRAWL_API_KEY, tag=tag, actions=rung == 2,
            profile=profile, request_id=str(uuid4()),
        )
    return providers["scrapedo"](
        url, api_key=settings.SCRAPEDO_API_KEY, rung=rung, profile=profile,
        session_id=_session_id(url),
    )


def _refuse(url: str, outcome: Outcome, reason: str, trail: list[Attempt]) -> FetchedPage:
    """A page carrying no bytes. Every refusal below returns one of these, so a
    caller never has to tell "the fetch failed" from "the page was empty"."""
    # `fetched_via` is a placeholder here and nothing more: FETCHED_VIA admits
    # no "nobody" label, and a page with no bytes has no provenance to lie
    # about. The attempt trail names who was actually asked.
    return FetchedPage(
        final_url=url, redirects=(), content_type="", body=b"", markdown="",
        outcome=outcome, fetched_via="EGRESS", rung=trail[-1].rung if trail else 0,
        cost_credits=sum(attempt.credits for attempt in trail), reason=reason,
        attempts=tuple(trail),
    )


def _record(
    url: str,
    host: str,
    purpose: str,
    page: FetchedPage,
    attempt: Attempt,
    *,
    sweep_id: UUID,
    attempt_no: int,
    retry_after: datetime | None = None,
) -> None:
    from ..models import FetchAttempt

    FetchAttempt.objects.create(
        # `purpose` is truncated like every other free-text column here: the row
        # is a record, and a caller passing a longer one must not raise a
        # DataError out of a function whose contract is that only a programming
        # error leaves it. FetchAttempt.purpose is max_length=10.
        # `host` (253) and `change_status` (10) are bounded for the same reason:
        # the UnsafeTarget -> stop(INVALID) path below records whatever hostname
        # the caller handed us, and nothing bounds that.
        url=url[:2048], host=host[:253], purpose=purpose[:10], rung=attempt.rung,
        vendor=attempt.vendor,
        status_code=attempt.status_code, content_type=page.content_type[:100],
        byte_size=len(page.body), credits=attempt.credits, duration_ms=attempt.duration_ms,
        outcome=str(attempt.outcome), reason=attempt.reason[:300],
        final_url=page.final_url[:2048], change_status=(page.change_status or "")[:10],
        captured_at=page.captured_at, page_count=page.page_count,
        total_pages=page.total_pages, retry_after=retry_after, attempt_no=attempt_no,
        sweep_id=sweep_id,
    )


def _retries_spent(url: str) -> int:
    """Rounds spent in the CURRENT failure episode, not over the URL's lifetime.

    An episode ends when the ladder finally gets an ANSWER for this URL -- any
    `_TERMINAL` outcome, served or refused. Counted unbounded, the three rounds
    were a per-URL lifetime budget that nothing ever cleared: `retry_due_fetches`
    nulls `retry_after` on a served retry and leaves `outcome` at
    `RETRY_SCHEDULED`, and no other writer touches it. So a URL that had once
    spent three rounds skipped rung 5 for the rest of its life and bought the
    25-credit archive rung on its next transient failure.

    The boundary is a TERMINAL row rather than "any non-RETRY_SCHEDULED row":
    this call's own walk has already written an UNREACHABLE/BLOCKED row for
    every rung it just tried, so that wider rule resets the budget on every
    single call and removes the ceiling altogether.
    """
    from ..models import FetchAttempt

    rows = FetchAttempt.objects.filter(url=url)
    answered = (
        rows.filter(outcome__in=[str(outcome) for outcome in _TERMINAL])
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    if answered is not None:
        rows = rows.filter(created_at__gt=answered)
    return rows.filter(outcome=str(Outcome.RETRY_SCHEDULED)).count()


def remember(host: str, page: FetchedPage) -> Any:
    """Teach the profile what this fetch learned (spec §5).

    Only EXPENSIVE rungs (3, 4) ever set start_rung -- a rung 1 or 2 result
    RESETS it to the cheap default instead, so the
    memory can only ever save money and never entrench a cost (`_rung_plan`'s
    re-probe is what notices a host got EASIER; this is only ever the other
    direction). Rung 6 -- the archive -- is a capture, not a live vendor tier
    `_rung_plan` ever starts at, so an ARCHIVED success updates last_success/the
    ledger but never touches start_rung: writing 6 there would be both outside
    the column's contracted 1-4 range and a lie, since the archive answering
    says nothing about whether rung 3 or 4 would have.

    The start_rung branch keys on `_CARRIES_BYTES`
    (SERVED | UNCHANGED), not on strict `SERVED`: `UNCHANGED` is the host
    answering in full -- firecrawl.py builds it from the same `common` as a
    FETCHED page, body and all -- and `_rung_plan`'s re-probe re-stamps
    `last_probe_at` on ANY outcome at rung<=1, UNCHANGED included. Keying the
    memory-lowering on strict SERVED left the clock reset without the memory
    following it: a host learned at rung 4, re-probed 30 days later, answering
    UNCHANGED for 1 credit at rung 1, kept start_rung=4 -- so the very next
    fetch, inside the fresh 30-day window, planned straight back to the
    25-credit rung, forever. `last_success_rung`/`last_success_at` stay on
    strict `SERVED`: "success" (new content read) and "answered" (bytes, maybe
    unchanged) are different claims, and only the first should be a "success".
    `DEAD` and `INVALID` are deliberately excluded from this lowering even
    though they can occur at rung<=1: `INVALID` is OUR OWN refusal of a
    vendor-reported URL, not the host answering anything, and `DEAD` is rare
    enough that leaving the memory stale until the next re-probe costs little.

    A BLOCKED outcome sets a doubling cool-off capped at a week, and the
    cool-off clears on `_CARRIES_BYTES` -- the same split, for the same reason:
    UNCHANGED is the host answering in full, so a cool-off it survives is
    stale. That was harmless while `blocked_until` had no reader; Task 10's
    retry runner is the reader, and now a stale one delays every queued retry
    for that host by up to a whole window (6h-7d) while a lingering
    `consecutive_blocks` doubles the next block's window from a count that
    already ended. Deciding WHEN to call fetch_page for a host again is a
    scheduling question, which is why it lives in that runner and not in the
    ladder -- the ladder cannot answer it without corrupting `_retries_spent`'s
    three-round budget the way an unconditional RETRY_SCHEDULED write would.

    `host` is lowercased here rather than trusted from the caller: this is the
    one function that writes the row, so it is where "Example.test and
    example.test are the same profile" (the model's own docstring) is kept
    true regardless of who calls it.
    """
    from ..models import HostProfile

    host = host.lower()
    profile, _created = HostProfile.objects.get_or_create(host=host)
    now = timezone.now()

    # The TRAIL, not just the final page: `remember` is called once per
    # `fetch_page`, with the page the ladder ENDED on. Keyed on `page.rung`
    # alone, the two branches below were mutually exclusive -- the very call
    # that learned "this host needs rung 4" left `last_probe_at` NULL, and
    # `_rung_plan` forces `start = 1` on a NULL clock. So the memory was
    # written and never read: measured, `_rung_plan(profile(start_rung=4,
    # last_probe_at=None))` plans [1, 3, 4]. Rung 1 was PROBED in that walk;
    # the trail is where that fact survives.
    if page.rung <= 1 or any(attempt.rung <= 1 for attempt in page.attempts):
        profile.last_probe_at = now

    if page.outcome in SERVED:
        profile.last_success_rung = page.rung
        profile.last_success_at = now
    elif page.outcome is Outcome.BLOCKED:
        profile.consecutive_blocks += 1
        # Exponent clamped to 5 (2**5 = 32x base = 192h, already past the 7-day
        # cap) before the multiply, not after: `timedelta` raises OverflowError
        # past ~999999999 days, which `_BLOCK_BASE * (2 ** n)` reaches at the
        # 33rd consecutive block -- a host with ~33 URLs, or one URL retried 33
        # times, would otherwise crash the first exception ever allowed to
        # escape fetch_page (module docstring: "only a programming error leaves
        # this function").
        window = min(_BLOCK_BASE * (2 ** min(profile.consecutive_blocks - 1, 5)), _BLOCK_CAP)
        profile.blocked_until = now + window

    if page.outcome in _CARRIES_BYTES:
        profile.blocked_until = None
        profile.consecutive_blocks = 0
        if page.rung in (1, 2):
            profile.start_rung = 1
        elif page.rung in (3, 4):
            profile.start_rung = page.rung

    profile.save()
    return profile


def fetch_page(
    url: str,
    *,
    purpose: str = "read",
    tag: str | None = None,
    require_origin: str | None = None,
    budget: SweepBudget | None = None,
    profile: Any = None,
    providers: dict[str, Callable[..., FetchedPage]] | None = None,
) -> FetchedPage:
    """Walk the ladder and return the first usable document, or a named refusal.

    `require_origin` is the URL the catalog vouched for. When it is given, any
    page CARRYING BYTES whose final URL left that ORIGIN is refused with
    `OFF_SITE` and its bytes are dropped -- off-site bytes must reach neither the
    model nor the evidence bucket (CLAUDE.md, "Decision B vouches for the SOURCE
    ROW, not the BYTES"). `UNCHANGED` is one of those pages (`_CARRIES_BYTES`),
    not an exemption. Origin, never the whole URL: official pages redirect `/x`
    to `/x/` as housekeeping.

    Engine-only: every call writes FetchAttempt/HostProfile, catalogue tables
    the web role (`runtime_web`) holds no grant on. A student-facing action
    that needs a fetch QUEUES it to the worker (catalog-read-split spec §6);
    called from a web request it fails with "permission denied".
    """
    from ..models import HostProfile

    providers = providers or _default_providers()
    budget = budget or default_budget()
    host = (urlsplit(url).hostname or "").lower()
    trail: list[Attempt] = []

    def stop(
        outcome: Outcome,
        reason: str,
        rung: int,
        *,
        vendor: str = "NONE",
        attempt_no: int | None = None,
        retry_after: datetime | None = None,
    ) -> FetchedPage:
        attempt = Attempt(rung=rung, vendor=vendor, outcome=outcome, reason=reason[:300])
        trail.append(attempt)
        page = _refuse(url, outcome, attempt.reason, trail)
        _record(url, host, purpose, page, attempt, sweep_id=budget.sweep_id,
                attempt_no=attempt_no or len(trail), retry_after=retry_after)
        return page

    def bill(page: FetchedPage, rung: int) -> None:
        try:
            # Against the RUNG's vendor, not the page's label: rung 6 reports
            # `fetched_via="ARCHIVE"` while spending scrape.do's credits to
            # fetch the capture, and a cap that cannot see them is not a cap.
            budget.spend(_VENDOR_BY_RUNG[rung], page.cost_credits)
        except FetchBudgetExhausted:
            # The credits are already gone; throwing the page away would be the
            # second loss. `spend` has recorded the overspend, so the next
            # rung's `check` is what stops the ladder.
            pass
        attempt = page.attempts[0] if page.attempts else Attempt(
            rung=rung, vendor=page.fetched_via, outcome=page.outcome,
            credits=page.cost_credits, status_code=page.status_code, reason=page.reason,
        )
        trail.append(attempt)
        _record(url, host, purpose, page, attempt, sweep_id=budget.sweep_id,
                attempt_no=len(trail))

    try:
        validate_public_url(url)
    except UnsafeTarget:
        # Refused by us, before a vendor is paid to refuse it too.
        return stop(Outcome.INVALID, "requested_url_unsafe", 0)

    if profile is None:
        profile = HostProfile.objects.filter(host=host).first()

    queue = _rung_plan(profile)
    escalated = False
    while queue:
        rung = queue.pop(0)
        if rung == 4 and trail and not escalated:
            # The ruling this engine exists to keep: `escalate=False` never buys
            # the 25-credit tier. Rung 5 answers "not now" instead.
            break
        vendor = _VENDOR_BY_RUNG[rung]
        try:
            budget.check(vendor)
        except FetchBudgetExhausted as error:
            return stop(Outcome.BUDGET, str(error), rung,
                        retry_after=timezone.now()
                        + timedelta(hours=settings.FETCH_BUDGET_RETRY_HOURS))

        try:
            page = _call(rung, url, tag=tag, profile=profile, providers=providers)
        except VendorUnavailable as error:
            # THEIR API failed, not the site. Recording this as a block would
            # teach the host profile a lie and send every later fetch to rung 4.
            reason = f"{VENDOR_UNAVAILABLE}{error}"
            attempt = Attempt(rung=rung, vendor=vendor, outcome=Outcome.UNREACHABLE,
                              reason=reason[:300])
            trail.append(attempt)
            _record(url, host, purpose, _refuse(url, Outcome.UNREACHABLE, reason, trail),
                    attempt, sweep_id=budget.sweep_id, attempt_no=len(trail))
            escalated = error.escalate
            continue

        bill(page, rung)

        if page.outcome in _CARRIES_BYTES and require_origin is not None:
            try:
                require_same_origin(require_origin, page)
            except OffSiteRedirect as error:
                return stop(Outcome.OFF_SITE, str(error), rung, vendor=page.fetched_via)

        if page.outcome in _TERMINAL:
            result = replace(
                page, cost_credits=sum(a.credits for a in trail), attempts=tuple(trail)
            )
            remember(host, result)
            return result

        escalated = _escalates(page)
        if page.outcome is Outcome.UNREADABLE and rung == 1:
            # A shell escalates WITHIN Firecrawl before it changes vendor: the
            # page is reachable, it just has not run its JavaScript yet.
            queue.insert(0, 2)
        elif page.outcome is Outcome.UNREADABLE and rung == 2:
            # Rung 2 rendered and still got a shell, so rung 3 -- a transport
            # with render=false -- cannot do better. Spec §4 sends it to rung 4.
            queue = [pending for pending in queue if pending != 3]

    blocked = any(attempt.outcome is Outcome.BLOCKED for attempt in trail)

    # Rung 5 before rung 6: a host that is merely down must not be answered from
    # a year-old capture on the first failure.
    rounds_spent = _retries_spent(url)
    if rounds_spent < settings.FETCH_MAX_RETRIES:
        schedule = settings.FETCH_RETRY_HOURS["blocked" if blocked else "unreachable"]
        hours = schedule[min(rounds_spent, len(schedule) - 1)]
        return stop(
            Outcome.RETRY_SCHEDULED, "blocked" if blocked else "unreachable", 5,
            attempt_no=rounds_spent + 1, retry_after=timezone.now() + timedelta(hours=hours),
        )

    try:
        budget.check(_VENDOR_BY_RUNG[6])
    except FetchBudgetExhausted as error:
        return stop(Outcome.BUDGET, str(error), 6,
                    retry_after=timezone.now()
                    + timedelta(hours=settings.FETCH_BUDGET_RETRY_HOURS))
    try:
        # `require_origin` is NOT applied to this rung, and that is safe only
        # because `archive.py` runs its own two origin checks against `url` and
        # returns `archived.final_url == url`. It has no production call site
        # today; spec §7.0 names its consumer in plan 2. The day a caller
        # passes a `require_origin` that DIFFERS from `url`, this branch
        # silently stops honouring it -- a capture would be served under a
        # provenance nobody checked. A comment, not a guard: adding one now
        # would be a check with no caller to exercise it.
        #
        # archive.py has a mixed contract on purpose -- its probe raises, its
        # capture fetch returns a value -- and handles both shapes internally.
        # This catch is for what escapes that: an UnsafeTarget out of the probe
        # transport, or a vendor failure it did not classify.
        archived = providers["archive"](url, api_key=settings.SCRAPEDO_API_KEY)
    except (SourceBlocked, UnsafeTarget) as error:
        return stop(Outcome.UNREACHABLE, f"archive_unavailable:{error}", 6)

    bill(archived, 6)
    if archived.outcome is Outcome.ARCHIVED:
        result = replace(
            archived, cost_credits=sum(a.credits for a in trail), attempts=tuple(trail)
        )
        remember(host, result)
        return result

    # Deliberately NOT record_blocked_source, here or on any other refusal path.
    # That row is tenant-scoped under FORCE RLS and this function runs on the
    # TENANTLESS catalog read as well, where current_tenant_id() raises -- a
    # bare call would crash every catalog read of a blocked page. The outcome
    # and the FetchAttempt trail are the ledger; the discovery pipeline, which
    # knows it is a lead, turns a BLOCKED/UNREACHABLE refusal into one
    # HOST_UNREACHABLE question in the platform's resolution queue, with that
    # trail as its evidence (resolution/writers.py::file_host_unreachable).
    #
    # The archive missing is not what the caller needs to be told about: BLOCKED
    # and UNREACHABLE are different fixes, and the rung that earned the label is
    # one of 1-4, not 6.
    outcome = Outcome.BLOCKED if blocked else Outcome.UNREACHABLE
    refused = _refuse(url, outcome, archived.reason or str(outcome).lower(), trail)
    remember(host, refused)
    return refused
