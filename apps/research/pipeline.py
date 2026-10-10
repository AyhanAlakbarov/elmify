"""DiscoveryQuery -> catalog rows (design §2.4).

Every stage but the writer already existed: this module is the wiring, the
budget, and the place where a refused lead is never a silence. A host the
ladder could not open becomes one HOST_UNREACHABLE question in the platform's
resolution queue (`apps/research/resolution/`); every other refusal -- a dead
link, a safety refusal, a "not now", our own defect -- goes to the run's
`degraded` list, which `manage.py discover` prints. Nothing here writes a
tenant's ConsultantResearchTask any more: a catalogue question is not one
agency's work (plan 2026-09-25, "The writers today").
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from functools import partial
from typing import NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

from django.utils import timezone

from apps.funding.models import (
    OfficialEvidenceClaim,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramAwardingInstitution,
)
from apps.ratelimit import rate_limited

from .batch_reading import BatchClients, PageRead, read_funding_batched
from .catalog import pool_claims, resolve_program, write_catalog_entry
from .discovery import (
    DiscoveryQuery,
    LeadBudgetExceeded,
    LeadSource,
    ResearchLead,
    RunBudget,
    canonicalize_url,
    collect_leads,
    retrieve_official_source,
)
from .egress import FetchResult, SourceBlocked, looks_unrendered
from .extraction import (
    ExtractedClaims,
    ExtractionError,
    ExtractionResult,
    MessagesAPI,
    ResponsesAPI,
    SourceSnapshot,
    extract_claims,
)
from .fetch import SweepBudget
from .funding_judge import (
    FUNDING_READS,
    FundingReadResult,
    PointerLead,
    funding_chunks,
    read_funding,
)
from .funding_reader import (
    _FUNDING_TERMS,
    withdraw_unread,
    write_funding_decision,
    write_holder_decision,
)
from .harvest import content_digest, official_url_from_catalogue_page
from .hosts import registrable_domain
from .model_cost import CostMeter, ReadingTier
from .reader import is_shell, readable_text
from .resolution.writers import file_host_unreachable, withdraw_host_unreachable
from .search import EntityExpansionSource, SearchSource, funding_links
from .seeds import EACEA_ERASMUS_MUNDUS
from .services import DomainBusy, acquire_domain_lease
from .snapshot import ObjectStore, archive_marker, persist_snapshot, touch_claims

FETCH_CALLS_PER_HOUR = 500
EXTRACTION_CALLS_PER_HOUR = 200
LEASE_INTERVAL = timedelta(seconds=5)
#: lead.source_type -> OfficialSource.Type. AGGREGATOR never reaches here: a
#: catalogue lead is hopped to the institution's own page first.
SOURCE_TYPES = {
    "PROGRAM": "PROGRAM",
    "SCHOLARSHIP": "SCHOLARSHIP",
    "UNIVERSITY": "UNIVERSITY",
    "RESEARCH_ORGANIZATION": "RESEARCH_ORGANIZATION",
}

#: Path words that name a *degree level* rather than a page's topic. Three of
#: the four overlap FUNDING_PATH_TERMS (search.py); "postdoc" does not appear
#: there and is included anyway, so the guard is deliberately wider than the
#: hop that motivates it -- "phd"/"doctoral"/"postdoc" name a different degree
#: level outright, and "graduate" routes the hop into a university's graduate
#: school generally, which is not the one programme a vouched front door names.
#: A page whose own URL carries one of these must never pool: eusmat.net's
#: front door is the AMASE MASTER's programme, and the hop -- doing exactly
#: what FUNDING_PATH_TERMS is for -- pulls in /international-studies/phd and
#: its children, which would otherwise write a doctoral stipend and a
#: "Master's required" eligibility claim onto the master's row.
_DEGREE_LEVEL_PATH_TERMS = frozenset({"phd", "doctoral", "postdoc", "graduate"})


def _names_another_degree(url: str) -> bool:
    """Whether ``url``'s path names a degree level other than the front door's.

    Word matching on path segments split at any non-alphanumeric character,
    not a substring check -- this branch already fixed one bug of exactly that
    kind (``"eur"`` inside "European"). A naive ``in`` would also match
    "graduate" inside "undergraduate"/"postgraduate", ordinary words on an
    admissions page that name no other degree at all. Splitting still catches
    "phd" inside a hyphenated segment like "dfh-phd-track".
    """
    words = re.split(r"[^a-z0-9]+", urlsplit(url).path.casefold())
    return any(word in _DEGREE_LEVEL_PATH_TERMS for word in words)


@dataclass
class FundingCounts:
    served: int = 0
    unagreed: int = 0
    abstained: int = 0
    pointers: int = 0
    unreadable: int = 0
    negations: int = 0
    noise: int = 0
    #: Pointer lines carried back as names for the register, not counted away.
    pointer_leads: int = 0
    #: Awards shown WITH a caveat -- agreed on existence, split on a detail
    #: (spec 8.6). Every one of these was a hidden award before tiered
    #: agreement, so this is the number that says what the change bought.
    unconfirmed: int = 0
    #: Rows unserved because the one page supporting them stopped saying so.
    withdrawn: int = 0
    #: What the funding reads cost (item 15): calls made, dollars at list price
    #: over the priced ones, and how many could not be priced.
    model_calls: int = 0
    model_usd: float = 0.0
    unpriced_readings: int = 0

    def record(self, read: FundingReadResult) -> None:
        self.pointers += read.pointers
        self.negations += read.negations
        self.noise += read.noise
        for decision in read.decisions:
            # served is counted from the written row, in _fund_page.
            if decision.agreement == "UNAGREED":
                self.unagreed += 1
            elif decision.agreement == "ABSTAINED":
                self.abstained += 1
            if decision.unconfirmed:
                self.unconfirmed += 1

    def add_cost(self, meter: CostMeter) -> None:
        self.model_calls += len(meter.usages) + meter.unmetered
        self.model_usd = round(self.model_usd + meter.usd, 6)
        self.unpriced_readings += meter.unpriced


@dataclass(frozen=True)
class DiscoveryReport:
    leads: int
    written: int
    unchanged: int
    blocked: int
    degraded: tuple[str, ...] = ()
    funding: FundingCounts = field(default_factory=FundingCounts)
    #: Bodies named on a funder's page as holding money of their own: a name
    #: and its holder, for the Organisation register. A pointer is a NAME --
    #: resolving one to its site is the resolver's job, and a URL printed in
    #: page text is never trusted as a body's own site.
    pointer_names: tuple[tuple[str, str], ...] = ()


@dataclass
class PacedFetch:
    """The single fetch path for a discovery run: budget, bucket, lease, fetch.

    Injected into the seed adapters and the sitemap reader as well as used by
    the pipeline, so nothing reaches the network around the accounting. The
    lease *waits* rather than skipping: every lead from one catalogue shares one
    host, and skipping on DomainBusy would reduce a 25-lead run to one fetch.
    """

    actor_id: UUID
    budget: RunBudget
    #: The sweep's COST ceiling, per vendor, distinct from `budget`, which caps
    #: the NUMBER of fetches. A count ceiling cannot bound cost: scrape.do
    #: applies per-domain multipliers of 10-200 credits server-side with no
    #: request-time signal, so 200 fetches is anywhere between 200 and 40,000
    #: credits. Do not merge the two.
    credits: SweepBudget | None = None
    calls_per_hour: int = FETCH_CALLS_PER_HOUR
    interval: timedelta = LEASE_INTERVAL
    attempts: int = 3
    fetch: Callable[..., FetchResult] = field(default=retrieve_official_source)
    sleep: Callable[[float], None] = field(default=time.sleep)

    def __call__(self, url: str, **_kwargs: object) -> FetchResult:
        # No require_https kwarg here: the vendor seam's canonicalize_url
        # already refuses anything but https unconditionally, and
        # retrieve_official_source (the default fetch) takes no such kwarg.
        self.budget.spend("fetches")
        if rate_limited(
            "discovery-fetch", self.actor_id, limit=self.calls_per_hour, window_seconds=3_600
        ):
            raise LeadBudgetExceeded("discovery fetch budget exhausted")
        host = urlsplit(url).hostname or ""
        for attempt in range(self.attempts):
            try:
                acquire_domain_lease(host, interval=self.interval)
                break
            except DomainBusy:
                if attempt == self.attempts - 1:
                    raise
                self.sleep(self.interval.total_seconds())
        return self.fetch(url, budget=self.credits)


def default_sources(
    *, api_key: str, fetch: Callable[..., FetchResult], budget: RunBudget, actor_id: UUID
) -> list[LeadSource]:
    # No DAAD International Programmes adapter: the 2026-08-27 access-terms
    # review could not establish that DAAD's published terms permit automated
    # retrieval, and the design's rule is that such an adapter is not written
    # at all. See docs/superpowers/research/2026-08-27-seed-source-access-terms.md.
    sources: list[LeadSource] = [replace(EACEA_ERASMUS_MUNDUS, fetch=fetch)]
    if api_key:
        # Search supplies ORGANISATIONS to entity expansion; it is never a source in
        # its own right. Entity expansion demotes the organisation query to
        # ECOSYSTEM_CLUE and takes its claim-capable leads from each organisation's
        # own host, so provenance follows from where the lead was found. Added here
        # standalone it emitted PROGRAM/DIRECT leads straight from open-web results --
        # a live run on 2026-08-30 returned eight content farms out of ten, all marked
        # can_support_claim=True. See the 2026-08-28 funding-led design, tiers 0 and 2.
        search = SearchSource(api_key=api_key, actor_id=actor_id, budget=budget)
        # No fetch= : entity expansion reads SITEMAPS, which are data files on our
        # own transport (search.sitemap_urls). The vendor fetcher is for pages.
        sources.append(EntityExpansionSource(search=search))
    return sources


#: Ladder outcomes that are a question an operator can answer in the console:
#: the host would not open (BLOCKED, UNREACHABLE) or opened only as a rendered
#: shell (UNREADABLE -- the ladder's own form of the empty-shell case below).
#: Every other refusal is a known answer (DEAD), a safety refusal a person must
#: not be sent to open (OFF_SITE, INVALID, UnsafeTarget), a "not now" the retry
#: queue owns (RETRY_SCHEDULED, BUDGET, DomainBusy), or a vendor defect
#: (UNCHANGED with no bytes), and is reported, not asked.
_ASK_ABOUT_HOST = frozenset({"BLOCKED", "UNREACHABLE", "UNREADABLE"})


def _degrade(degraded: list[str], url: str, reason: str) -> None:
    """A refusal nobody is asked about is still never a silence (§2.6)."""
    degraded.append(f"{url}: {reason}"[:300])


def _extraction_failure_reason(error: ExtractionError) -> str:
    """Name the cause, not only the wrapper.

    2026-08-30: one schema defect answered HTTP 400 on every call and was read
    as N page-specific failures, because the task kept only "ExtractionFailure".
    Class and status only, never the cause's message: that is third-party text
    of unbounded length headed for the run's degraded report, which a person
    reads.
    """
    reason = f"extraction failed: {type(error).__name__}"
    cause = error.__cause__
    if cause is None:
        return reason
    status = getattr(cause, "status_code", None)
    suffix = f" (HTTP {status})" if isinstance(status, int) else ""
    return f"{reason} <- {type(cause).__name__}{suffix}"


class _HeldPage(NamedTuple):
    """A page that failed the gate alone, kept until its group is resolved."""

    lead: ResearchLead
    claims: ExtractedClaims
    source: OfficialSource
    snapshot: OfficialSourceSnapshot
    #: Read for funding only once the group resolves.
    page: FetchResult


def _pay_for_funding(
    calls: int,
    *,
    budget: RunBudget,
    degraded: list[str],
    actor: UUID,
    extraction_calls_per_hour: int,
) -> bool:
    """Pay for every model call a page's funding read needs, before the first one.

    One extractions unit and one discovery-extraction rate-limit count per
    call (CLAUDE.md: an LLM call wired into a task is rate limited in the same
    change). A page that cannot be paid for in full makes no call at all.
    """
    for _ in range(calls):
        try:
            budget.spend("extractions")
        except LeadBudgetExceeded as error:
            degraded.append(str(error))
            return False
        if rate_limited(
            "discovery-extraction", actor, limit=extraction_calls_per_hour, window_seconds=3_600
        ):
            degraded.append("extraction budget exhausted")
            return False
    return True


@dataclass(frozen=True)
class _PendingRead:
    """A page paid for and chunked, waiting on its batch (item 15). `finish` is
    everything the synchronous path does with the read; it returns the page's
    pointer leads (none, for a programme page)."""

    url: str
    page: PageRead
    finish: Callable[[FundingReadResult], list[PointerLead]]


def _stamp_read(
    snapshot: OfficialSourceSnapshot,
    meter: CostMeter,
    now: datetime | None,
    counters: FundingCounts,
) -> None:
    """Mark the page read and leave what the read cost beside the mark."""
    snapshot.funding_read_at = now or timezone.now()
    snapshot.funding_read_cost = meter.as_json()
    snapshot.save(update_fields=["funding_read_at", "funding_read_cost"])
    counters.add_cost(meter)


def _fund_page(
    parser: ResponsesAPI | None,
    claude: MessagesAPI | None,
    page: FetchResult,
    *,
    program: Program,
    lead: ResearchLead,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    budget: RunBudget,
    degraded: list[str],
    actor: UUID,
    extraction_calls_per_hour: int,
    now: datetime | None,
    counters: FundingCounts,
    tier: ReadingTier = ReadingTier.STANDARD,
    deferred: list[_PendingRead] | None = None,
) -> None:
    """Read one written page for funding and write what the line judge decides.

    Called only once the page has a catalog row, so a blocked page never
    pays for a model call. In a batch run (`deferred` is a list) the paid-for
    read is queued, and `finish` writes it once the batch returns.
    """
    # Catalogue leads only: a search lead's page could serve a real
    # institution's award from any host. Lift this only once an
    # INSTITUTION-scope row's origin is checked against official_website.
    if parser is None or claude is None:
        return
    if not (lead.can_support_claim and lead.one_programme_per_site):
        return
    # The shell floor is a property of the whole page, not of one vocabulary's selection.
    whole_page = readable_text(page, terms=None)
    if is_shell(whole_page, page.body):
        counters.unreadable += 1  # a shell: recorded, never read as "no funding"
        # SHELL, not a bare "unreadable" flag: the reader distinguishes four
        # causes now (see OfficialSourceSnapshot.Readability), and this floor
        # is the one that means a client-rendered shell. Spec 7.5; never
        # marked funding-read.
        snapshot.readability = OfficialSourceSnapshot.Readability.SHELL
        snapshot.save(update_fields=["readability"])
        return
    chunks = funding_chunks(readable_text(page, terms=_FUNDING_TERMS, select_only_over_cap=False))
    if not _pay_for_funding(
        FUNDING_READS * len(chunks), budget=budget, degraded=degraded, actor=actor,
        extraction_calls_per_hour=extraction_calls_per_hour,
    ):
        # A cut-short read would overwrite a served row with a partial one.
        degraded.append(f"funding read cut short, nothing written: {source.canonical_url}")
        return
    meter = CostMeter()

    def finish(read: FundingReadResult) -> list[PointerLead]:
        # Even a read that finds nothing lets funding_recall say MISSED, not PENDING.
        _stamp_read(snapshot, meter, now, counters)
        counters.record(read)
        decided: set[str] = set()
        for decision in read.decisions:
            opportunity = write_funding_decision(
                decision, program=program, lead=lead, source=source, snapshot=snapshot, now=now
            )
            # None: an INSTITUTION-scope award on a jointly-provided programme,
            # with no single institution to anchor to (funding_reader.py).
            if opportunity is None:
                continue
            decided.add(opportunity.canonical_key)
            if opportunity.served:
                counters.served += 1
        # A row this page alone supported and this read no longer decides is the
        # page having changed, not an award that still stands (spec 3.5.4).
        counters.withdrawn += withdraw_unread(source, snapshot, decided)
        return []

    if deferred is not None:
        deferred.append(
            _PendingRead(source.canonical_url, PageRead(str(source.id), chunks, meter), finish)
        )
        return
    finish(
        read_funding(
            parser, claude, source_id=str(source.id), chunks=chunks, meter=meter, tier=tier,
            # The tie-break call cannot be reserved with the other three: whether a
            # chunk split on `offered` is only known after them. Unpaid, the tie stands.
            pay_for_tie_break=lambda: _pay_for_funding(
                1, budget=budget, degraded=degraded, actor=actor,
                extraction_calls_per_hour=extraction_calls_per_hour,
            ),
        )
    )


def _is_funder_lead(lead: ResearchLead) -> bool:
    """A lead whose page belongs to the body that holds the money -- a
    foundation, ministry, employer -- rather than to a programme."""
    return lead.source_type == "FUNDER"


def _fund_holder_page(
    parser: ResponsesAPI | None,
    claude: MessagesAPI | None,
    page: FetchResult,
    *,
    lead: ResearchLead,
    source: OfficialSource,
    snapshot: OfficialSourceSnapshot,
    holder_domain: str,
    holder_name: str,
    budget: RunBudget,
    degraded: list[str],
    actor: UUID,
    extraction_calls_per_hour: int,
    now: datetime | None,
    counters: FundingCounts,
    tier: ReadingTier = ReadingTier.STANDARD,
    deferred: list[_PendingRead] | None = None,
) -> list[PointerLead]:
    """Read one funder page; write HOLDER_OWN awards; return its pointers as leads.

    Mirrors _fund_page: the shell floor, the chunking, the budget, the
    funding_read_at stamp. Differs in the writer (holder-anchored) and in what
    happens to pointers (returned, not counted away). In a batch run the read
    is queued on `deferred` and its pointers come back from `finish` instead.
    """
    if parser is None or claude is None or not lead.can_support_claim:
        return []
    if not holder_domain:
        # No key to anchor a row to, and guessing one merges two funders.
        degraded.append(f"no registrable domain for a funder page: {source.canonical_url}")
        return []
    whole_page = readable_text(page, terms=None)
    if is_shell(whole_page, page.body):
        counters.unreadable += 1  # a shell: recorded, never read as "no funding"
        snapshot.readability = OfficialSourceSnapshot.Readability.SHELL
        snapshot.save(update_fields=["readability"])
        return []
    chunks = funding_chunks(readable_text(page, terms=_FUNDING_TERMS, select_only_over_cap=False))
    if not _pay_for_funding(
        FUNDING_READS * len(chunks), budget=budget, degraded=degraded, actor=actor,
        extraction_calls_per_hour=extraction_calls_per_hour,
    ):
        degraded.append(f"funding read cut short, nothing written: {source.canonical_url}")
        return []
    meter = CostMeter()

    def finish(read: FundingReadResult) -> list[PointerLead]:
        _stamp_read(snapshot, meter, now, counters)
        counters.record(read)
        decided: set[str] = set()
        for decision in read.decisions:
            if decision.scope != "HOLDER_OWN":
                continue  # an institution-shaped award on a funder page has no anchor here
            row = write_holder_decision(
                decision, holder_domain=holder_domain, holder_name=holder_name, lead=lead,
                source=source, snapshot=snapshot, now=now,
            )
            if row is None:
                continue
            decided.add(row.canonical_key)
            if row.served:
                counters.served += 1
        counters.withdrawn += withdraw_unread(source, snapshot, decided)
        counters.pointer_leads += len(read.pointer_leads)
        # Ten per page: one Turkish page named 31 funders, and a page that lists
        # a hundred is a directory, not a funder describing its neighbours.
        return list(read.pointer_leads)[:10]

    if deferred is not None:
        deferred.append(
            _PendingRead(source.canonical_url, PageRead(str(source.id), chunks, meter), finish)
        )
        return []
    return finish(
        read_funding(
            parser, claude, source_id=str(source.id), chunks=chunks, meter=meter, tier=tier,
            pay_for_tie_break=lambda: _pay_for_funding(
                1, budget=budget, degraded=degraded, actor=actor,
                extraction_calls_per_hour=extraction_calls_per_hour,
            ),
        )
    )


def run_discovery(
    query: DiscoveryQuery,
    sources: Iterable[LeadSource],
    *,
    tenant_id: UUID,
    store: ObjectStore,
    admissions_cycle: str,
    fetch: Callable[..., FetchResult],
    extract: Callable[..., ExtractionResult] = extract_claims,
    render: Callable[[str], FetchResult] | None = None,
    budget: RunBudget | None = None,
    actor_id: UUID | None = None,
    extraction_calls_per_hour: int = EXTRACTION_CALLS_PER_HOUR,
    funding_parser: ResponsesAPI | None = None,
    funding_claude: MessagesAPI | None = None,
    reading_tier: ReadingTier = ReadingTier.STANDARD,
    funding_batch: BatchClients | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> DiscoveryReport:
    if (funding_parser is None) != (funding_claude is None):
        raise ValueError(
            "funding needs both readers: a row is served only when two model "
            "families agree"
        )
    if reading_tier is ReadingTier.BATCH and funding_parser is not None and funding_batch is None:
        raise ValueError("a batch read needs the batch clients: pass funding_batch")
    run_budget = budget if budget is not None else RunBudget()
    # Cost is attributed to the tenant that asked for the run (CLAUDE.md).
    actor = actor_id or tenant_id
    degraded: list[str] = []
    leads = written = unchanged = blocked = unreadable_dates = 0
    funding = FundingCounts()
    # A batch run queues every paid-for read here and decides them after the
    # queue drains (item 15); a synchronous run reads inline and never uses it.
    deferred: list[_PendingRead] | None = [] if reading_tier is ReadingTier.BATCH else None
    fund = partial(
        _fund_page, funding_parser, funding_claude, budget=run_budget, degraded=degraded,
        actor=actor, extraction_calls_per_hour=extraction_calls_per_hour, now=now,
        counters=funding, tier=reading_tier, deferred=deferred,
    )
    # A set, not a counter: one programme routinely arrives on several pages
    # and must be queued for provider resolution once.
    joint_programs: set[UUID] = set()
    # Names a funder's pages point at, deduped by name within the run.
    pointer_names: list[tuple[str, str]] = []
    pointer_seen: set[str] = set()

    def take_pointers(pointers: list[PointerLead]) -> None:
        for pointer in pointers:
            if pointer.name.casefold() not in pointer_seen:
                pointer_seen.add(pointer.name.casefold())
                pointer_names.append((pointer.name, pointer.holder))

    # A queue, not a list: a fetched page can add funding pages from its own
    # host to the back of it (see the hop below).
    queue = deque(collect_leads(sources, query, on_degraded=degraded.append))
    hopped: set[str] = set()
    # Pages of one programme in queue order (front door first), and the ones
    # that could not resolve alone. Only sources that vouch populate these.
    pooled: dict[tuple[str, str], list[ExtractedClaims]] = defaultdict(list)
    held: dict[tuple[str, str], list[_HeldPage]] = defaultdict(list)
    # The lead of the first poolable page seen per group -- the front door,
    # queue order. Recorded separately from `held` because the front door
    # itself may resolve on its own and never be held (Fix 4b below).
    front_door_lead: dict[tuple[str, str], ResearchLead] = {}
    # Split rather than one "conflicted" count: pool_claims returning None is a
    # genuine contradiction between pages, resolve_program still refusing after
    # a clean pool is an absence (no page ever stated the field) -- see the
    # degraded-message comments below for why that distinction is worth code.
    contradicted = incomplete = 0
    while queue:
        lead = queue.popleft()
        leads += 1
        if dry_run:
            continue  # count what would be fetched; touch neither network nor DB
        # The URL being fetched when a refusal is raised: the hop's target, not
        # the catalogue page, once the hop has started.
        attempted = lead.canonical_url
        try:
            page = fetch(attempted)
            if lead.source_type == "AGGREGATOR":
                hop_target = official_url_from_catalogue_page(page)
                if hop_target is None:
                    # A name without a site: the resolver's question (spec 6.4),
                    # not a queue item per catalogue page.
                    _degrade(degraded, lead.canonical_url, "no official programme link")
                    blocked += 1
                    continue
                attempted = hop_target
                page = fetch(hop_target)
                # The hop lands on the institution's own claimed page: that is
                # DIRECT evidence regardless of the catalogue lead's own strength.
                rebuild_type, rebuild_strength = "PROGRAM", "DIRECT"
            else:
                rebuild_type, rebuild_strength = lead.source_type, lead.evidence_strength
            # Rebuild from where the fetch actually landed on EVERY path, not
            # only the hop's: the vendor fetch follows redirects too, so a
            # direct institution URL that 301s onto a catalogue host must be
            # caught here -- from_url re-applies the catalogue guard -- rather
            # than written under a can_support_claim computed from the
            # pre-redirect host (whole-branch review, Fix 3). This also means a
            # hopped lead is rebuilt exactly once: the hop branch above never
            # reassigns `lead`, so `lead.funding_family` etc. below still read
            # the pre-hop seed lead either way.
            lead = ResearchLead.from_url(
                page.final_url,
                source_type=rebuild_type,
                funding_family=lead.funding_family,
                evidence_strength=rebuild_strength,
                discovered_by=lead.discovered_by,
                identity=lead.identity,
                one_programme_per_site=lead.one_programme_per_site,
                awards_jointly=lead.awards_jointly,
            )
            if lead.source_type == "AGGREGATOR":
                _degrade(degraded, lead.canonical_url, "the fetched page landed on a catalogue")
                blocked += 1
                continue
            if page.browser_required or looks_unrendered(page.content_type, page.body):
                # The vendor already rendered: Firecrawl's proxy:"auto" and
                # scrape.do's render=true both run a browser, and neither sets
                # browser_required, so `render` is None on every production
                # path and this is where a shell ends. The question must not
                # name a browser tier -- that tier was deleted on this branch,
                # and an operator sent to start one finds nothing.
                if render is None:
                    file_host_unreachable(
                        page.final_url,
                        "the vendor rendered this page and it is still an empty shell: "
                        "no readable content",
                    )
                    blocked += 1
                    continue
                # Render the URL the fetch LANDED on, never the pre-redirect
                # one, so the catalogue guard's verdict above still describes
                # the page being rendered.
                attempted = page.final_url
                page = render(page.final_url)
            # The host answered with a readable page: any open question about
            # it answered itself. Both hosts, since a redirect can land on
            # another one; never a DECIDED item (withdraw_item's own rule).
            withdraw_host_unreachable(attempted)
            withdraw_host_unreachable(page.final_url)
            # The catalogue vouched for this host, so a funding page one hop
            # *inside* it inherits that provenance -- and a consortium's front
            # door routinely carries no funding text at all, which is why five
            # live leads produced no row (shadow run 2, §2.2). The links come
            # off the response already in hand, so the hop costs no extra
            # retrieval to find them, and once per host bounds it to depth 1:
            # a hopped page is on a host already in `hopped`.
            host = urlsplit(page.final_url).hostname or ""
            if lead.can_support_claim and host and host not in hopped:
                hopped.add(host)
                # replace(), not from_url(): same host, so the catalogue guard
                # two lines above has already ruled on it. identity is dropped
                # because the catalogue vouched for the front door, not for every
                # page behind it -- resolve_program prefers seed identity over the
                # extracted claims, so carrying it here would write this page's
                # funding facts under the parent's institution and programme, and
                # one university host serves many programmes.
                # identity is dropped but one_programme_per_site is kept: the
                # catalogue vouched for the site being one programme, and a page
                # inside it is still that programme's page.
                queue.extend(
                    replace(lead, canonical_url=url, identity=None)
                    for url in funding_links(page)
                )
        except LeadBudgetExceeded as error:
            degraded.append(str(error))
            break
        except SourceBlocked as error:
            blocked += 1
            if error.outcome in _ASK_ABOUT_HOST:
                file_host_unreachable(attempted, str(error))
            else:
                # Includes a bare SourceBlocked (no ladder: the renderer, the
                # first-party transport) -- nothing says the host refused.
                _degrade(degraded, attempted, str(error))
            continue
        except (DomainBusy, ValueError) as error:
            # UnsafeTarget subclasses ValueError, as does canonicalize_url's
            # refusal: a safety refusal, never a page to send a person to.
            # DomainBusy is "not now".
            _degrade(degraded, attempted, str(error) or type(error).__name__)
            blocked += 1
            continue
        source, _created = OfficialSource.objects.get_or_create(
            canonical_url=canonicalize_url(page.final_url),
            defaults={
                "publisher": urlsplit(page.final_url).hostname or "",
                "source_type": SOURCE_TYPES.get(lead.source_type, "PROGRAM"),
            },
        )
        # persist_snapshot digests the body itself; this one is to find out
        # whether the page changed *before* writing a duplicate snapshot row --
        # (source, sha256) is unique, so an unconditional create raises.
        digest = hashlib.sha256(page.body).hexdigest()
        seen = OfficialSourceSnapshot.objects.filter(source=source, sha256=digest).first()
        # The claims check is load-bearing, not a stray filter: a snapshot row
        # is written further below *before* extraction is attempted, so a run
        # that dies mid-extraction (a 429, a missing OPENAI_API_KEY) leaves a
        # snapshot with zero claims. Without this check that snapshot alone
        # makes every later run treat the byte-identical page as "seen" and
        # `continue` -- the page is never extracted again, forever. Do not
        # simplify this back to `if seen is not None:`.
        if seen is not None and OfficialEvidenceClaim.objects.filter(snapshot=seen).exists():
            touch_claims(seen, now=now)  # revalidation, not new evidence (§7.1)
            unchanged += 1
            continue
        if seen is None:
            # Different bytes are not a different page. A CSRF token, a rotating
            # news panel or a "last reviewed" footer moves the raw digest on a
            # programme page that says exactly what it said last week, and
            # extraction is the expensive step. Compare the content region
            # before paying for it again.
            revalidated = (
                OfficialSourceSnapshot.objects.filter(
                    source=source, content_sha256=content_digest(page.body)
                )
                .exclude(content_sha256="")
                .order_by("-retrieved_at")
                .first()
            )
            # Only ever a revalidation shortcut, never a snapshot to reuse: these
            # bytes were not the ones stored on that row, so attaching new claims
            # to it would cite evidence that does not match what was extracted.
            if (
                revalidated is not None
                and OfficialEvidenceClaim.objects.filter(snapshot=revalidated).exists()
            ):
                touch_claims(revalidated, now=now)
                unchanged += 1
                continue
        # A snapshot row can already exist here with zero claims -- a prior run
        # that fetched this same byte-identical page and then failed extraction
        # (see the comment above). Reuse it instead of persisting a duplicate:
        # (source, sha256) is unique, so persist_snapshot's create() would raise.
        snapshot = seen or persist_snapshot(
            source=source,
            fetch=page,
            store=store,
            admissions_cycle=admissions_cycle,
            discovery_technique=lead.discovered_by[:50] or None,
            # Every claim written below cites this snapshot and carries
            # `retrieved_at=now`. `retrieve_official_source` returns ARCHIVED as
            # SERVED under the ORIGINAL url, so without this marker a capture up
            # to a year old becomes evidence dated today. Same marker as the
            # reader's, from one producer (snapshot.archive_marker).
            render_metadata=archive_marker(page),
        ).snapshot
        if _is_funder_lead(lead):
            # A funder page has no programme to extract, so it never reaches
            # the claims extractor: it is read for the money the body holds.
            holder_domain = registrable_domain(page.final_url)
            take_pointers(
                _fund_holder_page(
                    funding_parser, funding_claude, page, lead=lead, source=source,
                    snapshot=snapshot, holder_domain=holder_domain,
                    # The hostname until the register supplies a curated name.
                    holder_name=urlsplit(page.final_url).hostname or holder_domain,
                    budget=run_budget, degraded=degraded, actor=actor,
                    extraction_calls_per_hour=extraction_calls_per_hour, now=now,
                    counters=funding, tier=reading_tier, deferred=deferred,
                )
            )
            continue
        try:
            run_budget.spend("extractions")
        except LeadBudgetExceeded as error:
            degraded.append(str(error))
            break
        if rate_limited(
            "discovery-extraction", actor, limit=extraction_calls_per_hour, window_seconds=3_600
        ):
            degraded.append("extraction budget exhausted")
            break
        try:
            claims = extract(
                SourceSnapshot(
                    # terms=None: this extractor reads for general programme
                    # claims, not only admission, so the admission-vocabulary
                    # section selection readable_text applies by default would
                    # drop sections (e.g. funding) it doesn't recognise.
                    relevant_text=readable_text(page, terms=None),
                    evidence_metadata={"source_url": source.canonical_url},
                    privacy_safe_identifier=str(source.id),
                )
            ).claims
        except ExtractionError as error:
            # Our defect, not a question an operator can answer.
            _degrade(degraded, source.canonical_url, _extraction_failure_reason(error))
            blocked += 1
            continue
        # one_programme_per_site is a promise about the LINK that produced this
        # lead (§2.2 of the design doc); this group key is per HOST, because the
        # hop above follows funding links across the whole site. That gap is
        # real -- a hop can land on a different degree's own page on the same
        # host -- so a page naming another degree level in its own URL is
        # excluded from pooling here, even though its lead still carries the
        # promise (whole-branch review, Fix 1).
        group = (lead.discovered_by, urlsplit(source.canonical_url).hostname or "")
        poolable = lead.one_programme_per_site and not _names_another_degree(
            source.canonical_url
        )
        if poolable:
            pooled[group].append(claims)
            front_door_lead.setdefault(group, lead)
        result = write_catalog_entry(
            lead=lead, claims=claims, source=source, snapshot=snapshot, now=now
        )
        if result is None:
            if poolable:
                # Not blocked yet: another page of this same programme may state
                # the field this one lacks. Resolved once, after the queue drains.
                held[group].append(_HeldPage(lead, claims, source, snapshot, page))
                continue
            _degrade(degraded, source.canonical_url, "no evidence for a catalog row")
            blocked += 1
            continue
        written += 1
        unreadable_dates += result.unreadable_dates
        fund(page, program=result.program, lead=lead, source=source, snapshot=snapshot)
        if result.program.provision_type == Program.ProvisionType.JOINT:
            joint_programs.add(result.program.id)
    for group, pages in held.items():
        merged = pool_claims(tuple(pooled[group]))
        # The group's front door, not pages[0]'s: the front door can resolve
        # on its own and never appear in `held` at all, so `pages[0]` is only
        # ever the first HELD page, which is not the same thing. Harmless on
        # the current corpus (lead.identity is always None here), but a
        # registry lead (one_programme_per_link=True, Korea/Finland) can carry
        # seed names on the front door that a hopped, identity-less held page
        # does not -- resolve_program prefers seed identity over extracted
        # claims, so reading it off the wrong lead would silently drop it and
        # fall back to degree_level="MASTER" (whole-branch review, Fix 4b).
        facts = resolve_program(front_door_lead[group], merged) if merged is not None else None
        if merged is None:
            contradicted += 1
        elif facts is None:
            incomplete += 1
        for held_page in pages:
            result = (
                write_catalog_entry(
                    lead=held_page.lead,
                    claims=held_page.claims,
                    source=held_page.source,
                    snapshot=held_page.snapshot,
                    now=now,
                    program_facts=facts,
                )
                if facts is not None
                else None
            )
            if result is None:
                _degrade(degraded, held_page.source.canonical_url, "no evidence for a catalog row")
                blocked += 1
                continue
            written += 1
            unreadable_dates += result.unreadable_dates
            fund(
                held_page.page, program=result.program, lead=held_page.lead,
                source=held_page.source, snapshot=held_page.snapshot,
            )
            if result.program.provision_type == Program.ProvisionType.JOINT:
                joint_programs.add(result.program.id)
    if deferred and funding_batch is not None:
        # Possibly hours. Nothing in this function holds a transaction open
        # (autocommit between writes), and nothing may start one around this.
        results = read_funding_batched(
            funding_batch,
            [pending.page for pending in deferred],
            pay_for_tie_break=lambda: _pay_for_funding(
                1, budget=run_budget, degraded=degraded, actor=actor,
                extraction_calls_per_hour=extraction_calls_per_hour,
            ),
        )
        for pending, read in zip(deferred, results, strict=True):
            if read is None:
                # Never ABSTAINED rows: withdraw_unread would unserve awards the
                # page still states. funding_recall reports this page PENDING.
                degraded.append(f"funding batch did not finish, nothing written: {pending.url}")
                # Readings that did come back were billed: they count in the
                # run's cost even though the page decides nothing.
                if pending.page.meter is not None:
                    funding.add_cost(pending.page.meter)
                continue
            take_pointers(pending.finish(read))
    if contradicted:
        # A refusal is never a silence (§2.6): these are hosts whose own pages
        # state different facts, which is a page problem for a human to read.
        degraded.append(f"{contradicted} programmes' pages disagreed on a gate fact")
    if incomplete:
        # Counted apart from contradicted, not folded into it. On the
        # 2026-08-30 corpus replay, once _names_another_degree stops other-degree
        # pages pooling, NO group contradicts and 110 are incomplete. The two
        # apparent contradictions before that guard (life.univ-cotedazur.eu and
        # www.ntnu.edu) were both a master's duration against a doctorate's on
        # the same host -- a symptom of that bug, not a page disagreeing with
        # itself. The split still earns its code: a real contradiction is a page
        # problem a human must read, an absence is not, and they must not arrive
        # under one number. The absent ones -- 110 that
        # pooled cleanly but still never stated a required field between them --
        # are an institution or country most often, on joint degrees where four
        # universities in four countries each publish their own partial page.
        # That is an absence, not a disagreement, and reporting it as one
        # sends a human hunting for a data-quality bug that isn't there.
        degraded.append(f"{incomplete} programmes' pages never stated a required gate fact")
    if unreadable_dates:
        # A third of extracted dates carried a fabricated year on the
        # 2026-08-30 run. Passing that over quietly would hide it. The row
        # itself survives with its quotation; only the parsed date is withheld.
        degraded.append(f"{unreadable_dates} dates unreadable, citations kept")
    if joint_programs:
        # A curator resolving a genuinely multi-provider programme leaves it
        # JOINT by design -- it really is jointly awarded -- so counting every
        # JOINT row written this run would re-queue already-resolved
        # programmes on every later run. Only ones with no
        # ProgramAwardingInstitution row yet are still awaiting a curator.
        resolved = set(
            ProgramAwardingInstitution.objects.filter(program_id__in=joint_programs).values_list(
                "program_id", flat=True
            )
        )
        awaiting = len(joint_programs - resolved)
        if awaiting:
            degraded.append(f"{awaiting} joint programmes await provider resolution")
    return DiscoveryReport(
        leads=leads,
        written=written,
        unchanged=unchanged,
        blocked=blocked,
        degraded=tuple(degraded),
        funding=funding,
        pointer_names=tuple(pointer_names),
    )
