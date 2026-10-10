"""Cycle verification: the evidence ladder of master spec 9.2, per (award, intake).

The DECISION is `apps.funding.validity.cycle_validity` -- pure, model-free and
not edited here. This module only gathers what it decides on, cheapest first,
and stops as soon as the answer is not UNVERIFIED:

    0  the award's own pages, already read (their dates were stored by the
       reader's writer) and re-checked through changeTracking
    1  a site crawl on the cycle vocabulary, limit 15
    1b Wayback captures of the call page from the previous two cycles
    1c the register's cadence row
    2  one hop from an own page to an apply link ON THE ORGANISATION'S OWN
       DOMAINS (plan decision 1: never a portal, never another host)
    3  one Exa search restricted to the registrable domain; Brave `site:` only
       when Exa returns nothing

What each step costs is recorded as billed (`metering.Meter`). What it looked
at is the row's `trail`, so "not found" always says what was searched.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings as _settings
from django.db import transaction
from django.utils import timezone

from apps.funding.cycle_evidence import EvidenceEntry, observations, to_evidence
from apps.funding.cycle_schedule import next_check, projection_lapsed, tracked_intakes
from apps.funding.deadline_conditions import normalise_condition
from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.funding.validity import (
    RegisterCadence,
    Validity,
    cycle_validity,
    intake_start_year,
    projected_window,
)
from apps.ratelimit import rate_limited
from apps.research import cycle_vocabulary
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import FetchBudgetExhausted
from apps.research.fetch.site import FirecrawlSiteError, crawl_ceiling
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.funding_judge import FUNDING_READS, FundingDecision, funding_chunks, read_funding
from apps.research.hosts import registrable_domain
from apps.research.metering import Meter
from apps.research.model_cost import CostMeter, ReadingTier
from apps.research.providers.base import ProviderUnavailable, on_domain
from apps.research.reader import _MIN_BYTES_FOR_FLOOR, _MIN_READABLE_CHARS, readable_text
from apps.research.snapshot import ObjectStore

_ORDER = ("0", "1", "1b", "1c", "2", "3")


def _iso(value: str) -> str | None:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def entries_from_decision(
    decision: FundingDecision,
    *,
    step: str,
    url: str,
    sha256: str,
    at: dt.date,
    captured_at: str = "",
) -> list[EvidenceEntry]:
    return [
        EvidenceEntry(
            step=step,
            url=url,
            sha256=sha256,
            at=at.isoformat(),
            archived=bool(captured_at),
            captured_at=captured_at,
            offered=decision.offered,
            applies_to=decision.applies_to,
            intake_year=intake_start_year(decision.applies_to),
            stated_on=_iso(decision.stated_on),
            deadlines=[
                [iso, whose, normalise_condition(whose)]
                for date, whose in decision.deadlines
                if (iso := _iso(date)) is not None
            ],
            quote=(decision.suspension_quote or " / ".join(decision.quotes))[:600],
            agreement=decision.agreement,
        )
    ]


def _merge(
    existing: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """A re-read of a URL supersedes that URL's live entries; captures stay."""
    replaced = {e["url"] for e in new if not e["archived"]}
    new_shas = {e["sha256"] for e in new}
    kept = [
        dict(e) for e in existing
        if e["archived"] or e["url"] not in replaced or e["sha256"] in new_shas
    ]
    seen = {_key(e) for e in kept}
    return kept + [dict(e) for e in new if _key(e) not in seen]


def _key(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    return (entry["url"], entry["sha256"], entry["quote"], entry["offered"], entry["applies_to"],
            str(entry["deadlines"]))


def _cadence(opportunity: FundingOpportunity) -> RegisterCadence | None:
    org = opportunity.organisation
    if org is None:
        return None
    if (
        org.cadence_open_month is None
        or org.cadence_deadline_month is None
        or not org.cadence_source
        or org.cadence_verified_for_cycle is None
    ):
        return None
    return RegisterCadence(open_month=org.cadence_open_month,
                           deadline_month=org.cadence_deadline_month,
                           source=org.cadence_source,
                           verified_for_cycle=org.cadence_verified_for_cycle)


@transaction.atomic
def record_read_evidence(
    opportunity: FundingOpportunity,
    decision: FundingDecision,
    *,
    url: str,
    sha256: str,
    at: dt.date,
    today: dt.date,
) -> None:
    """Step 0, stored: the reader already read these dates -- keep them.

    Written on every tracked intake's row, because a line naming no intake is
    evidence for each of them and `to_evidence` decides which intake a dated
    line speaks to. The row's first ladder run is due at once.
    """
    new = entries_from_decision(decision, step="0", url=url, sha256=sha256, at=at)
    cadence = _cadence(opportunity)
    for year in tracked_intakes(today):
        row, _ = FundingCycleVerification.objects.select_for_update().get_or_create(
            opportunity=opportunity, intake_start_year=year
        )
        row.evidence = _merge(row.evidence, new)
        evidence = to_evidence(row.evidence, target_year=year, cadence=cadence,
                               page_removed=row.page_removed, lapsed=row.projection_lapsed)
        row.state = cycle_validity(evidence, student={}, target_intake=str(year), today=today)
        if row.next_check_at is None:
            row.next_check_at = timezone.now()
        row.save()


@dataclass(frozen=True)
class Subject:
    """What the ladder knows about one award -- from a catalog row (`subject_for`)
    or from a truth-set row (Task 12). Never a student."""

    name: str
    kind: str
    scope: str
    own_urls: tuple[str, ...]
    #: Registrable domains that count as the award's own site (plan decision 1).
    domains: frozenset[str]
    primary_domain: str
    #: True when the organisation holds another award of the same kind, so a
    #: decision must also name this one to join it.
    ambiguous: bool
    cadence: RegisterCadence | None
    languages: tuple[str, ...] = ()
    #: The page heading the award was read under -- the identity the writers
    #: key a catalog row on (`canonical_key`), as `funding_judge` says `name`
    #: is not. "" when unknown (a truth-set row, an unparseable key).
    heading: str = ""


@dataclass(frozen=True)
class Seams:
    fetch: Callable[..., FetchedPage]
    crawl: Callable[..., Any]
    capture_near: Callable[..., FetchedPage]
    read: Callable[[FetchedPage], tuple[FundingDecision, ...]]
    site_search: Callable[..., Any]
    fallback_search: Callable[..., Any]
    store: ObjectStore


@dataclass(frozen=True)
class Verdict:
    state: Validity
    step: str
    entries: list[dict[str, Any]]
    trail: list[dict[str, str]]
    page_removed: bool
    own_page_silent: bool
    projected_open: dt.date | None
    projected_deadline: dt.date | None
    lapsed: bool
    #: The `_key`s of the evidence the run started from. `persist_verdict`
    #: keeps any entry on the row NOT among these -- written by the reader
    #: while the ladder ran -- and never resurrects one the run dropped.
    started_from: frozenset[tuple[Any, ...]] = frozenset()


def _as_entries(entries: list[dict[str, Any]]) -> list[EvidenceEntry]:
    """Stored rows are JSON; every one was written by `entries_from_decision`."""
    return cast("list[EvidenceEntry]", entries)


@dataclass
class _Run:
    subject: Subject
    year: int
    today: dt.date
    seams: Seams
    meter: Meter
    entries: list[dict[str, Any]]
    trail: list[dict[str, str]] = field(default_factory=list)
    fetched: dict[str, FetchedPage] = field(default_factory=dict)
    #: Earlier runs' trail rows -- their `1b` lookups are never repeated.
    looked: list[dict[str, str]] = field(default_factory=list)
    #: This row's earlier trail, for what step 0 last saw of each own URL.
    history: list[dict[str, str]] = field(default_factory=list)
    page_removed: bool = False
    own_page_silent: bool = False

    def note(self, step: str, url: str, outcome: str, note: str = "") -> None:
        self.trail.append({"step": step, "url": url, "outcome": outcome, "note": note[:200]})

    def state(self, through: str) -> Validity:
        use_cadence = _ORDER.index(through) >= _ORDER.index("1c")
        evidence = to_evidence(_as_entries(self.entries), target_year=self.year,
                               cadence=self.subject.cadence if use_cadence else None,
                               page_removed=self.page_removed, lapsed=False)
        return cycle_validity(evidence, student={}, target_intake=str(self.year),
                              today=self.today)


def joins(decision: FundingDecision, subject: Subject) -> bool:
    """Does this decision, read off some page, describe THIS award?

    Kind and scope must match -- the judge's own award identity minus the page
    and heading, which differ on every page the ladder reads. When the
    organisation holds another award of the same kind, the decision must also
    name this one; otherwise it joins nothing and is counted, never guessed
    onto the wrong award. That applies to negations too: a NO that cannot be
    placed suspends nothing.

    The HEADING is tried first: it is the award's identity in its catalog key,
    while `name` is a model's label that varies between reads (funding_judge),
    so a re-read that relabels the award still joins it by the heading it sits
    under. Then naming, which is conservative, because a sibling's name often
    CONTAINS this one's ("Example Fellowship for Women" beside "Example
    Fellowship"): the decision's own label -- its `name`, else its `heading` --
    must equal the award's name (casefolded, whitespace-normalised); a label
    naming anything else joins nothing. Only a decision with no label at all is
    placed by its quotes, and then by the whole name between word boundaries.
    """
    if not _same_kind(decision, subject):
        return False
    if not subject.ambiguous:
        return True
    heading = _normalised(subject.heading)
    if heading and _normalised(decision.heading) == heading:
        return True
    name = _normalised(subject.name)
    if not name:
        return False
    label = _normalised(decision.name) or _normalised(decision.heading)
    if label:
        return label == name
    bounded = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)")
    return any(bounded.search(_normalised(quote)) for quote in decision.quotes)


def _same_kind(decision: FundingDecision, subject: Subject) -> bool:
    return decision.kind == subject.kind and decision.scope == subject.scope


def _normalised(text: str) -> str:
    return " ".join(text.casefold().split())


@dataclass(frozen=True)
class _Read:
    #: Decisions the read returned, for any award. 0 is the READER's silence
    #: (refused, unpaid, a shell, a failed call), never the page's.
    returned: int
    #: Of those, the decisions that join this award.
    joined: int
    #: Of those, the decisions of this award's kind and scope, joined or not.
    #: Page silence is decided on this, never on names: a name is a model's
    #: label, and a relabelled read must not read as the page moving on.
    same_kind: int = 0


def _absorb(run: _Run, page: FetchedPage, *, step: str) -> _Read:
    """Read one page, keep the decisions that join this award, archive its bytes."""
    read = run.seams.read(page)
    decisions = [d for d in read if joins(d, run.subject)]
    same_kind = sum(1 for d in read if _same_kind(d, run.subject))
    if not read:
        # The READER was silent (refused, unpaid, a shell, a failed call).
        # Named, so a later UNCHANGED fetch of these bytes reads them again.
        run.note(step, page.final_url, READ_SILENT, "the read returned no decision")
        return _Read(returned=0, joined=0)
    if not decisions:
        run.note(step, page.final_url, "read",
                 f"no decision joins this award ({len(read)} read, {same_kind} of its kind)")
        return _Read(returned=len(read), joined=0, same_kind=same_kind)
    sha256 = hashlib.sha256(page.body).hexdigest()
    run.seams.store.put(f"cycle-evidence/{sha256}", page.body)
    new: list[EvidenceEntry] = []
    for decision in decisions:
        new += entries_from_decision(decision, step=step, url=page.final_url, sha256=sha256,
                                     at=run.today, captured_at=page.captured_at)
    run.entries = _merge(run.entries, new)
    run.note(step, page.final_url, "evidence", f"{len(decisions)} decision(s)")
    return _Read(returned=len(read), joined=len(decisions), same_kind=same_kind)


def _tag(year: int) -> str:
    # Never the monitors' `<cycle>:<host>`: two consumers on one tag would each
    # see the other's `changed` as `same` (spec 7.6).
    return f"cycle-verify:{year}"


#: The trail outcome of a read that returned no decision at all.
READ_SILENT = "READ_SILENT"
#: A URL's last step-0 outcomes that mean its current bytes were read (or found
#: unchanged since they were). Anything else -- READ_SILENT, a failed fetch --
#: leaves an UNCHANGED page to be read again.
_READ_OUTCOMES = frozenset({"evidence", "read", "UNCHANGED", "SUPERSEDED"})


def _already_read(run: _Run, url: str, page: FetchedPage) -> bool:
    """Is an UNCHANGED page's content already what the stored entries say?

    Only when a live entry for it carries these very bytes' digest, or this
    row's last step-0 look at the URL was a read that spoke (or an UNCHANGED
    after one). "Some live entry exists" is not enough: a read that failed on
    the changed page left the OLD entries standing, and every later UNCHANGED
    would then keep them forever. The trail fallback is there because a
    vendor's HTML need not be byte-stable while its change tracking says "same".
    """
    urls = {url, page.final_url}
    live = [e for e in run.entries if e["url"] in urls and not e["archived"]]
    if not live:
        return False
    digest = hashlib.sha256(page.body).hexdigest()
    if any(e["sha256"] == digest for e in live):
        return True
    last = next((t["outcome"] for t in reversed(run.history)
                 if t.get("step") == "0" and t.get("url") in urls), "")
    return last in _READ_OUTCOMES


def _step_zero(run: _Run) -> None:
    dead = 0
    for url in run.subject.own_urls:
        page = run.seams.fetch(url, tag=_tag(run.year), require_origin=url,
                               budget=run.meter.run)
        run.fetched[url] = page
        if page.outcome == Outcome.DEAD:
            dead += 1
            run.note("0", url, "DEAD")
            continue
        # Stored entries carry the URL the page LANDED on (`_absorb` writes
        # `page.final_url`), so the requested URL alone misses a redirect.
        urls = {url, page.final_url}
        stored = any(e["url"] in urls and not e["archived"] for e in run.entries)
        if page.outcome == Outcome.UNCHANGED and _already_read(run, url, page):
            run.note("0", url, "UNCHANGED")
            continue
        if not page.ok and page.outcome != Outcome.UNCHANGED:
            run.note("0", url, str(page.outcome), page.reason)
            continue
        read = _absorb(run, page, step="0")
        # Only a fresh, FULL, live read that returned decisions -- none of them
        # even of this award's kind and scope -- says the page no longer
        # describes it. A capture is the page as it was, a partial fetch is not
        # the whole page, and a read returning nothing is the reader's silence,
        # not the page's. Names play no part: a same-kind decision the ladder
        # cannot place may be this award relabelled.
        moved_on = (page.outcome == Outcome.FETCHED and read.returned > 0
                    and read.same_kind == 0)
        if moved_on and stored:
            # Its old live entries would otherwise go on deciding the state
            # from bytes the page no longer serves. Captures stay: they were
            # always about the past.
            run.entries = [e for e in run.entries if e["archived"] or e["url"] not in urls]
            run.note("0", url, "SUPERSEDED", "changed page no longer describes the award")
            if len(run.subject.own_urls) == 1:
                # The award's only page, changed, no longer describes it (Task 11).
                run.own_page_silent = True
    run.page_removed = bool(run.subject.own_urls) and dead == len(run.subject.own_urls)


def verify_cycle(
    subject: Subject,
    *,
    intake_year: int,
    today: dt.date,
    seams: Seams,
    meter: Meter,
    stored: list[dict[str, Any]],
    looked: Sequence[dict[str, str]] = (),
    history: Sequence[dict[str, str]] = (),
) -> Verdict:
    run = _Run(subject=subject, year=intake_year, today=today, seams=seams, meter=meter,
               entries=list(stored), looked=list(looked), history=list(history))
    started_from = frozenset(_key(e) for e in stored)
    reached = "0"
    _step_zero(run)
    state = run.state("0")
    for step, action in _LATER_STEPS:
        if state != "UNVERIFIED" or run.page_removed or meter_exhausted(run):
            break
        reached = step
        action(run)
        state = run.state(step)
    return replace(_finish(run, state, reached), started_from=started_from)


def meter_exhausted(run: _Run) -> bool:
    from django.conf import settings

    usd, _detail, _complete = run.meter.total()
    if float(usd) >= settings.CYCLE_VERIFY_MAX_USD_PER_AWARD:
        run.note("budget", "", "STOP", f"per-award ceiling reached at ${usd}")
        return True
    return False


def _finish(run: _Run, state: Validity, reached: str) -> Verdict:
    entries = _as_entries(run.entries)
    evidence = to_evidence(entries, target_year=run.year, cadence=run.subject.cadence,
                           page_removed=run.page_removed, lapsed=False)
    window = projected_window(evidence, target_intake=str(run.year), today=run.today)
    opened, deadline = window if window else (None, None)
    call_seen = any(e["intake_year"] == run.year for e in run.entries) or bool(evidence.deadlines)
    lapsed = projection_lapsed(opened, today=run.today, call_seen=call_seen)
    if lapsed:
        evidence = to_evidence(entries, target_year=run.year, cadence=run.subject.cadence,
                               page_removed=run.page_removed, lapsed=True)
        state = cycle_validity(evidence, student={}, target_intake=str(run.year), today=run.today)
    return Verdict(state=state, step=reached, entries=run.entries, trail=run.trail,
                   page_removed=run.page_removed, own_page_silent=run.own_page_silent,
                   projected_open=opened, projected_deadline=deadline, lapsed=lapsed)


#: Filled by Tasks 8-10, in spec order. Each entry runs only while the state is
#: still UNVERIFIED.
_LATER_STEPS: list[tuple[str, Callable[[_Run], None]]] = []


def _own(url: str, subject: Subject) -> bool:
    """Is `url` on one of the organisation's own registrable domains (plan decision 1)?

    Host-suffix match against the domains, not `registrable_domain(url) in
    domains`: that answers "" for any host whose suffix the public-suffix list
    does not know, and "" is never a domain here -- so it would call a real own
    page foreign. For a known suffix the two agree, because a registrable domain
    is never itself a public suffix. Fails closed: an IP host or an empty domain
    matches nothing.
    """
    return any(domain and on_domain(url, domain) for domain in subject.domains)


def _read_url(run: _Run, url: str, *, step: str, filtered: bool = True) -> None:
    if url in run.fetched or not _own(url, run.subject):
        return
    page = run.seams.fetch(url, tag=_tag(run.year), require_origin=url, budget=run.meter.run)
    run.fetched[url] = page
    if not page.ok:
        run.note(step, url, str(page.outcome), page.reason)
        return
    text = page.markdown or page.body.decode("utf-8", "ignore")
    if filtered and not cycle_vocabulary.mentions_award(
        text, name=run.subject.name, years=cycle_vocabulary.year_tokens(run.today)
    ):
        run.note(step, url, "filtered", "names neither the award nor a year")
        return
    _absorb(run, page, step=step)


def _step_crawl(run: _Run) -> None:
    run_budget = run.meter.run
    remaining = run_budget.caps["FIRECRAWL"] - run_budget.spent["FIRECRAWL"]
    limit = _settings.CYCLE_CRAWL_LIMIT
    if crawl_ceiling(limit) > remaining:
        run.note("1", run.subject.own_urls[0] if run.subject.own_urls else "", "SKIPPED",
                 f"crawl ceiling {crawl_ceiling(limit)} credits > {remaining} left in the run")
        return
    if not run.subject.own_urls:
        return
    try:
        result = run.seams.crawl(
            run.subject.own_urls[0], limit=limit, tag=_tag(run.year),
            include_paths=cycle_vocabulary.include_paths(run.subject.languages, today=run.today),
        )
    except FirecrawlSiteError as error:
        run.note("1", run.subject.own_urls[0], "CRAWL_FAILED", str(error))
        return
    try:
        run_budget.spend("FIRECRAWL", result.credits)
    except FetchBudgetExhausted as error:
        run.note("1", "", "BUDGET", str(error))
        return
    for url in result.urls:
        if run.state("1") != "UNVERIFIED" or meter_exhausted(run):
            return
        _read_url(run, url, step="1")


_LATER_STEPS.append(("1", _step_crawl))


def _years_back(today: dt.date, back: int) -> dt.date:
    try:
        return today.replace(year=today.year - back)
    except ValueError:  # 29 February
        return today.replace(year=today.year - back, day=28)


#: `archive.capture_near` refusals that ANSWER the question -- the archive has
#: no capture, none near the date, or only one of another site. Every other
#: refusal (`archive_unavailable`, `archive_unfetchable:*`,
#: `archive_timestamp_invalid`) is the archive or the vendor failing, and is
#: asked again next run.
_DEFINITE_REFUSALS = (
    "archive_absent", "archive_skew:", "archive_origin:", "archive_unwrapped:",
    "archive_transport:",
)
#: The trail outcome of a lookup that is cached for good; anything else is retried.
LOOKED = "LOOKED"


def _definite(page: FetchedPage, read: _Read | None) -> bool:
    if page.ok:
        # A capture found AND read. A read returning nothing is the reader's
        # silence (unpaid, refused, a shell) -- asked again, like a failure.
        return read is not None and read.returned > 0
    return page.reason.startswith(_DEFINITE_REFUSALS)


def _step_wayback(run: _Run) -> None:
    looked = {t["url"] for t in run.looked if t["step"] == "1b" and t["outcome"] == LOOKED}
    for url in run.subject.own_urls[:1]:  # the call page: the award's first own page
        for back in range(1, _settings.CYCLE_ARCHIVE_YEARS_BACK + 1):
            at = _years_back(run.today, back)
            key = f"{url}@{at.year}"
            if key in looked:
                continue  # a definite answer is cached for good (spec 9.2)
            try:
                # Before the paid call: `spend` alone would refuse only after it.
                run.meter.run.check("SCRAPE_DO")
            except FetchBudgetExhausted as error:
                run.note("1b", key, "BUDGET", str(error))
                return
            page = run.seams.capture_near(url, at=at)
            exhausted = ""
            try:
                run.meter.run.spend("SCRAPE_DO", page.cost_credits)
            except FetchBudgetExhausted as error:
                exhausted = str(error)  # paid for already: read it, then stop
            read = _absorb(run, page, step="1b") if page.ok else None
            run.note("1b", key, LOOKED if _definite(page, read) else "RETRY",
                     page.reason or str(page.outcome))
            if exhausted:
                run.note("1b", key, "BUDGET", exhausted)
                return


def _step_cadence(run: _Run) -> None:
    """No work: `run.state("1c")` includes the cadence from 1c onward. The step
    exists so the trail and `ladder_step` say which evidence settled the state."""
    run.note("1c", "", "CADENCE",
             "register cadence considered" if run.subject.cadence else "no register cadence")


_LATER_STEPS.extend((("1b", _step_wayback), ("1c", _step_cadence)))


def _step_hop(run: _Run) -> None:
    candidates: list[str] = []
    for page in list(run.fetched.values()):
        if not page.body:
            continue
        for link in cycle_vocabulary.apply_links(page.body, base_url=page.final_url,
                                                 languages=run.subject.languages):
            if link in run.fetched or link in candidates:
                continue
            if not _own(link, run.subject):
                # Plan decision 1: an apply link off the organisation's own
                # domains may be a portal, and no vendor is ever pointed at one.
                # Every such link is noted, not only the first, so the gate can
                # count what the rule withheld.
                run.note("2", link, "hop_withheld", "off the organisation's own domains")
                continue
            candidates.append(link)
    if candidates:
        _read_url(run, candidates[0], step="2", filtered=False)  # one hop, never further


def _step_search(run: _Run) -> None:
    if not run.subject.primary_domain:
        # A search restricted to no domain is a search of the web.
        run.note("3", "", "SKIPPED", "no primary domain")
        return
    query = f"{run.subject.name} {run.year} call for applications deadline"
    urls: tuple[str, ...] = ()
    for search in (run.seams.site_search, run.seams.fallback_search):
        try:
            result = search(query=query, domain=run.subject.primary_domain)
        except ProviderUnavailable as error:
            run.note("3", "", "SEARCH_UNAVAILABLE", str(error))
            continue
        run.meter.add_search(result.provider, result.cost_usd)
        urls = result.urls
        if urls:
            break
    for url in urls[: _settings.CYCLE_SEARCH_RESULTS]:
        if run.state("3") != "UNVERIFIED" or meter_exhausted(run):
            return
        _read_url(run, url, step="3")


_LATER_STEPS.extend((("2", _step_hop), ("3", _step_search)))



# --- Task 11: the catalog row -> Subject, the real seams, persisting a verdict --

#: No tenant asks for a verification, so a per-tenant limiter would limit
#: nothing; the platform is the actor (plan decision 8).
PLATFORM_ACTOR = UUID(int=0)

#: The judge's scope vocabulary (funding_judge._Scope, minus POINTER, which
#: never becomes a row). The writers key a row `read:<judge scope>:...`, so the
#: key is read first; `scope_type` is the fallback, and it cannot tell
#: PROGRAMS from PROGRAM (write_funding_decision stores both as PROGRAM).
_JUDGE_SCOPES = frozenset({"PROGRAM", "PROGRAMS", "INSTITUTION", "HOLDER_OWN"})
_SCOPE_BY_TYPE = {"HOLDER": "HOLDER_OWN"}


def _judge_scope(opportunity: FundingOpportunity) -> str:
    parts = opportunity.canonical_key.split(":")
    if len(parts) > 2 and parts[0] == "read" and parts[1].upper() in _JUDGE_SCOPES:
        return parts[1].upper()
    return _SCOPE_BY_TYPE.get(opportunity.scope_type, opportunity.scope_type)


def _heading(opportunity: FundingOpportunity) -> str:
    """The heading the writers put in the key: `read:<scope>:<anchor>:<heading>:<kind>`,
    and for HOLDER_OWN `read:holder_own:<organisation>:<source>:<heading>:<kind>`
    (`funding_reader.write_funding_decision` / `write_holder_decision`, via
    `catalog_key`, which casefolds). A heading may itself hold colons, so it is
    everything between the fixed prefix and the kind. "" whenever the key is not
    of that shape or its last part is not this row's kind -- then the ladder
    falls back to the name, as it did before the heading was carried."""
    parts = opportunity.canonical_key.split(":")
    if len(parts) < 2 or parts[0] != "read" or parts[1].upper() not in _JUDGE_SCOPES:
        return ""
    prefix = 4 if parts[1].upper() == "HOLDER_OWN" else 3
    if len(parts) < prefix + 2 or parts[-1] != opportunity.kind.casefold():
        return ""
    return ":".join(parts[prefix:-1])


def subject_for(opportunity: FundingOpportunity) -> Subject:
    """What the ladder knows about a catalog row: its own pages are the pages
    its quotes came from, and its own site is those pages' registrable domains
    plus the organisation's."""
    from apps.research.models import HostProfile

    urls = tuple(
        sorted(
            set(
                opportunity.evidence_claims.values_list("source__canonical_url", flat=True)
            )
        )
    )
    org = opportunity.organisation
    domains = {registrable_domain(url) for url in urls}
    if org is not None:
        domains |= set(org.domains.values_list("registrable_domain", flat=True))
        domains.add(org.primary_domain)
        siblings = FundingOpportunity.objects.filter(organisation=org, kind=opportunity.kind)
    else:
        siblings = FundingOpportunity.objects.filter(
            institution=opportunity.institution, program=opportunity.program,
            kind=opportunity.kind,
        )
    # Host matching (`_own`) is exact on labels: "F.Example." would own nothing.
    domains = {_domain(d) for d in domains}
    hosts = [urlsplit(url).hostname or "" for url in urls]
    languages: tuple[str, ...] = ()
    for profile in HostProfile.objects.filter(host__in=hosts):
        languages += tuple(profile.languages or ())
    primary = _domain(
        org.primary_domain if org else (registrable_domain(urls[0]) if urls else "")
    )
    return Subject(
        name=opportunity.name,
        kind=opportunity.kind,
        scope=_judge_scope(opportunity),
        own_urls=urls,
        domains=frozenset(d for d in domains if d),
        primary_domain=primary,
        ambiguous=siblings.exclude(pk=opportunity.pk).exclude(agreement="WITHDRAWN").exists(),
        cadence=_cadence(opportunity),
        languages=tuple(dict.fromkeys(languages)),
        heading=_heading(opportunity),
    )


def _domain(value: str) -> str:
    return (value or "").strip().lower().rstrip(".")


def stored_evidence(
    opportunity: FundingOpportunity,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """The award's evidence and earlier Wayback lookups, over all its intake rows.

    `record_read_evidence` writes the same entries onto every tracked row, so
    they are deduplicated here: unmerged, each run would store every entry once
    per sibling row and the evidence would double on every run.
    """
    rows = list(FundingCycleVerification.objects.filter(opportunity=opportunity))
    entries = list({_key(e): dict(e) for row in rows for e in row.evidence}.values())
    looked = list(
        {
            t["url"]: t
            for row in rows
            for t in row.trail
            if t.get("step") == "1b" and t.get("outcome") == LOOKED
        }.values()
    )
    return entries, looked


def funding_reader_for(
    parser: ResponsesAPI,
    claude: MessagesAPI,
    *,
    pay: Callable[[int], bool],
    source_id: str,
    meter: CostMeter,
) -> Callable[[FetchedPage], tuple[FundingDecision, ...]]:
    """The `read` seam: the funding reader over one page, paid for up front.

    Mirrors `pipeline._fund_page`'s read path: the shell floor on the WHOLE page
    (never on one vocabulary's selection), the funding-vocabulary chunks,
    every call paid for before the first, and the tie-break paid on its own.
    Every reading's usage goes to `meter` (the verification's
    `Meter.models`), where the funding reader records it everywhere else.
    STANDARD tier: Batch (item 15) is not wired to the ladder.
    """
    # Imported here, not at module top: funding_reader imports this module
    # (record_read_evidence), so a top-level import back into it is a cycle.
    from apps.research.funding_reader import _FUNDING_TERMS

    def read(page: FetchedPage) -> tuple[FundingDecision, ...]:
        whole_page = readable_text(page, terms=None)
        if len(whole_page) < _MIN_READABLE_CHARS and len(page.body) >= _MIN_BYTES_FOR_FLOOR:
            return ()  # a shell: never read as "no funding"
        chunks = funding_chunks(
            readable_text(page, terms=_FUNDING_TERMS, select_only_over_cap=False)
        )
        if not chunks or not pay(FUNDING_READS * len(chunks)):
            return ()  # a page that cannot be paid for in full makes no call at all
        return read_funding(
            parser, claude, source_id=source_id, chunks=chunks, meter=meter,
            tier=ReadingTier.STANDARD, pay_for_tie_break=lambda: pay(1),
        ).decisions

    return read


def _pay_for(meter: Meter) -> Callable[[int], bool]:
    """Pay for `calls` model calls before the first: the platform's hourly
    limiter (the model-call circuit-breaker CLAUDE.md requires of any wired
    LLM call) and the per-award USD ceiling."""

    def pay(calls: int) -> bool:
        for _ in range(calls):
            if rate_limited(
                "cycle-verification", PLATFORM_ACTOR,
                limit=_settings.CYCLE_VERIFY_MODEL_CALLS_PER_HOUR, window_seconds=3_600,
            ):
                return False
        return float(meter.total()[0]) < _settings.CYCLE_VERIFY_MAX_USD_PER_AWARD

    return pay


def build_seams(
    meter: Meter,
    parser: ResponsesAPI,
    claude: MessagesAPI,
    *,
    source_id: str,
    store: ObjectStore | None = None,
) -> Seams:
    """The real vendors behind every seam, shared by `verify_due_cycles` and the
    `cycle_verify` gate so the gate measures exactly what the schedule runs."""
    from apps.research.fetch import archive, fetch_page, site
    from apps.research.providers.brave import brave_site_search
    from apps.research.providers.exa import exa_site_search

    if store is None:
        from apps.research.storage import S3ObjectStore

        store = S3ObjectStore()
    return Seams(
        fetch=fetch_page,
        # allow_external=False: Firecrawl would otherwise fetch off-domain
        # links matching a year token itself -- a vendor pointed at a portal
        # before `_own` ever sees the URL (CLAUDE.md, plan decision 1).
        crawl=lambda url, **kw: site.crawl(
            url, api_key=_settings.FIRECRAWL_API_KEY, allow_external=False, **kw
        ),
        capture_near=lambda url, *, at: archive.capture_near(
            url, at=at, api_key=_settings.SCRAPEDO_API_KEY
        ),
        read=funding_reader_for(parser, claude, pay=_pay_for(meter), source_id=source_id,
                                meter=meter.models),
        site_search=lambda *, query, domain: exa_site_search(
            query=query, domain=domain, num_results=_settings.CYCLE_SEARCH_RESULTS
        ),
        fallback_search=lambda *, query, domain: brave_site_search(
            query=query, domain=domain, count=_settings.CYCLE_SEARCH_RESULTS
        ),
        store=store,
    )


def _withdraw_if_sole_page_silent(opportunity: FundingOpportunity, verdict: Verdict) -> None:
    """Plan decision 6: the one award-row write the verifier makes.

    By `funding_reader.withdraw_unread`'s own rule, re-checked here against the
    database rather than trusted from a caller: never a row a human reviewed,
    and never a row whose quotes come from more than one page -- a vaguer read
    of this page may not unserve what another page states. Nor a row no longer
    AGREED: whatever changed it (a re-read, another withdrawal) is newer than
    this run. `opportunity` is the row LOCKED by `persist_verdict`, never the
    copy loaded before the ladder ran. Quotes are kept, so the withdrawal is
    readable.
    """
    if not verdict.own_page_silent or opportunity.review or opportunity.agreement != "AGREED":
        return
    sources = set(opportunity.evidence_claims.values_list("source_id", flat=True))
    if len(sources) != 1:
        return
    opportunity.agreement, opportunity.served = "WITHDRAWN", False
    opportunity.save(update_fields=["agreement", "served"])


#: How many trail rows a row keeps, besides its permanent Wayback answers.
TRAIL_LIMIT = 200


def _trim_trail(trail: Sequence[dict[str, str]], limit: int = TRAIL_LIMIT) -> list[dict[str, str]]:
    """The newest `limit` rows, and every definite `1b` answer whatever its age:
    those are the cache that keeps a Wayback lookup from ever being paid twice
    (spec 9.2), so trimming one away would re-buy it."""
    permanent = {i for i, t in enumerate(trail)
                 if t.get("step") == "1b" and t.get("outcome") == LOOKED}
    others = [i for i in range(len(trail)) if i not in permanent]
    room = max(0, limit - len(permanent))
    keep = permanent | set(others[len(others) - room:] if room else ())
    return [t for i, t in enumerate(trail) if i in keep]


@transaction.atomic
def persist_verdict(
    row: FundingCycleVerification,
    verdict: Verdict,
    *,
    meter: Meter,
    today: dt.date,
) -> None:
    """Write one run's verdict onto its (award, intake) row, and schedule the next.

    `cost_usd` accumulates across runs (the award's total verification spend
    for that intake); `cost_detail` is the latest run's breakdown, and
    `cost_complete` stays False once any run's spend could not be priced.

    The ladder ran for minutes on objects loaded before it started, so the
    award and the row are re-read here under lock -- the award first, as the
    reader's writers lock it before `record_read_evidence` locks the rows, so
    the two never wait on each other in opposite orders. Evidence the reader
    wrote meanwhile survives (anything on the row the run did not start from);
    evidence the run itself dropped stays dropped.
    """
    opportunity = FundingOpportunity.objects.select_for_update().get(pk=row.opportunity_id)
    locked = FundingCycleVerification.objects.select_for_update().get(pk=row.pk)
    usd, detail, complete = meter.total()
    written_meanwhile = [e for e in locked.evidence if _key(e) not in verdict.started_from]
    merged = _merge(verdict.entries, written_meanwhile)
    entries = _as_entries(merged)
    evidence = to_evidence(entries, target_year=row.intake_start_year, cadence=None,
                           page_removed=verdict.page_removed, lapsed=verdict.lapsed)
    observed = observations(entries)
    last_open = max(
        (dt.date.fromisoformat(o["open"]) for o in observed if o["open"]), default=None
    )
    state = verdict.state
    if written_meanwhile:
        # The verdict never saw these entries; decide on everything the row holds.
        state = cycle_validity(
            to_evidence(entries, target_year=locked.intake_start_year,
                        cadence=_cadence(opportunity), page_removed=verdict.page_removed,
                        lapsed=verdict.lapsed),
            student={}, target_intake=str(locked.intake_start_year), today=today,
        )
    locked.state = state
    locked.ladder_step = verdict.step
    locked.evidence = merged
    locked.cycles_observed = observed
    locked.trail = _trim_trail(list(locked.trail) + verdict.trail)
    locked.projected_open = verdict.projected_open
    locked.projected_deadline = verdict.projected_deadline
    locked.projection_lapsed = verdict.lapsed
    locked.page_removed = verdict.page_removed
    locked.cost_usd = Decimal(locked.cost_usd) + usd
    locked.cost_detail = detail
    locked.cost_complete = locked.cost_complete and complete
    locked.verified_at = timezone.now()
    due = next_check(today=today, deadlines=[d for d, _ in evidence.deadlines],
                     last_call_open=last_open, projected_open=verdict.projected_open)
    locked.next_check_at = timezone.make_aware(dt.datetime.combine(due, dt.time(6)))
    locked.save()
    _withdraw_if_sole_page_silent(opportunity, verdict)
    row.refresh_from_db()


@transaction.atomic
def record_run_error(
    row: FundingCycleVerification, error: Exception, *, meter: Meter, now: dt.datetime
) -> None:
    """One award's run raised: say so on its row, keep what it cost, back it off.

    The note is the exception's class and the first line of its message, cut
    short -- never a traceback, which is where a request's headers and keys end
    up. The row keeps its state and evidence: nothing the run found is trusted.
    """
    usd, _detail, _complete = meter.total()
    locked = FundingCycleVerification.objects.select_for_update().get(pk=row.pk)
    message = (str(error).splitlines() or [""])[0][:120]
    locked.trail = _trim_trail(list(locked.trail) + [
        {"step": "run", "url": "", "outcome": "ERROR",
         "note": f"{type(error).__name__}: {message}"[:200]}
    ])
    locked.cost_usd = Decimal(locked.cost_usd) + usd
    # The run stopped part-way: whatever it spent after the last meter read is lost.
    locked.cost_complete = False
    locked.next_check_at = now + dt.timedelta(days=_settings.CYCLE_ERROR_BACKOFF_DAYS)
    locked.save(update_fields=["trail", "cost_usd", "cost_complete", "next_check_at"])
    row.refresh_from_db()
