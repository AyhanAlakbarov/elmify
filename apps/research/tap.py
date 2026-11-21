"""The tap (spec 10.5): catalogue first, stage 1 search, stage 2 read, republish.

Two kinds (amended 2026-10-14). A FIRST search runs once, when the intake is
finished, in three stages of value -- coverage (every programme and money
angle in English and each teaching language, no query cap), local (each
destination's own languages), deep (the coverage queries that found most,
re-run at FIRST_SEARCH_DEEP_RESULTS on Exa) -- and stops on the plateau rule,
on the wallet less SEARCH_FOLLOWUP_RESERVE_USD; a job that reaches
FIRST_SEARCH_MAX_SECONDS saves its place on the tap and the tap continues in a
new job (FIRST_SEARCH_MAX_CONTINUATIONS is a runaway guard, ending TIME_CAP).
A FOLLOW_UP searches only a changed profile's new part, under TAP_MAX_QUERIES,
TAP_MAX_PROVIDER_CALLS, TAP_MAX_SECONDS and TAP_WALLET_SHARE of the wallet.

Runs in the research worker, NOT inside one transaction: every wallet charge
commits on its own (wallet.charge), every database touch is its own
`tenant_transaction`, and no transaction is held across a provider call or a
read. Up to TAP_PARALLEL_CALLS requests are in flight at once, in worker
threads that touch no database: a thread's new connection has no
app.tenant_id, so under row-level security its every query would silently
return nothing. Every charge, record and reuse check runs on the main thread,
in submission order. Stage 1 fetches and reads nothing; every hit is deduped against the
register by registrable domain before stage 2 is asked to read it. Exa and
Brave only -- the one search index with a perpetual licence over query text
is never a tap provider (tap_query's docstring).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
from functools import lru_cache
from itertools import islice
from typing import Any, NamedTuple, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from babel import Locale
from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.fx import RateTable
from apps.funding.models import PackVersion, RecommendationRun, update_exactly
from apps.funding.rates import latest_table
from apps.tenancy.context import current_tenant_id
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from .angles import cycle_label
from .cells import LEVEL
from .coverage import area_exhausted
from .destinations import TARGET_COUNTRIES, anywhere
from .domains import is_catalogue
from .egress import SourceBlocked
from .funding_reader import FAMILY_BY_HOLDER
from .hosts import registrable_domain
from .hybrid_strategy import (
    DiscoveryTier,
    apply_hybrid_plan_to_tap_inputs,
    plan_hybrid_retrieval,
)
from .languages import CldrLanguages
from .models import (
    SWEEP_FAMILIES,
    AreaSweep,
    CellCoverage,
    Organisation,
    OrganisationDomain,
    SearchTap,
    SearchWallet,
    TapQueryRun,
    WalletCharge,
)
from .providers import SearchMeter, SearchProvider, SearchRequest, default_providers
from .queue import enqueue_research
from .register import record_organisation
from .schemas import ResearchMessage
from .services import _profile_for, rebuild_pack
from .tap_query import QUERY_WORDS, inputs_from, render_tap_queries
from .tap_seams import (
    AngleRow,
    AngleSource,
    HostReader,
    PassStates,
    TapQueryInputs,
    bound_angles,
    bound_host_reader,
    bound_pass_states,
)
from .wallet import (
    TapRefused,
    WalletExhausted,
    charge,
    check_tap_permitted,
    open_wallet,
    page_backstop,
    preflight,
    remaining,
    spendable,
    tap_allowance,
    tap_spent,
)

logger = logging.getLogger(__name__)

_Kind, _Ending = SearchTap.Kind, SearchTap.Ending
#: The programme pass's family: the area a tap's step-4 decision reads.
_PROGRAMME_FAMILY = "UNIVERSITY_WIDE"
#: The deep stage re-runs this share of the coverage queries, those that found most.
_DEEP_SHARE = 0.2
#: PROVIDER_CALL_PREFLIGHT_USD["exa"] prices a call of up to 15 results; Exa's
#: list price adds $0.001 per result beyond (roster spec §4.13), so a deep
#: 100-result call is preflighted at 0.012 + 85 x 0.001 = $0.097.
_EXA_PRICED_RESULTS = 15
_EXA_USD_PER_RESULT = Decimal("0.001")


class TapSeams(AngleSource, PassStates, HostReader, Protocol):
    """The three seams a tap reads, as one object (tests pass a scripted one)."""


class _WalletMeter(SearchMeter):
    """Every billed call becomes a WalletCharge the moment the provider reports it.

    A charge that crosses a ceiling is recorded (wallet.charge writes it first)
    and NOT raised into the provider: the call is paid for, so its URLs are
    still read. `exhausted` carries the ending for the stage to act on after.
    """

    def __init__(self, tap: SearchTap) -> None:
        super().__init__()
        self.tap = tap
        self.exhausted = ""

    def charge(self, provider: str, usd: float) -> None:
        super().charge(provider, usd)
        try:
            charge(
                self.tap, kind=WalletCharge.Kind.SEARCH, provider=provider, usd=Decimal(str(usd))
            )
        except WalletExhausted as spent:
            self.exhausted = self.exhausted or spent.ending


# --- 1. request (web side or operator: enqueue only) ---------------------------


class ReserveOnly(TapRefused):
    """A FIRST search was refused because only the follow-up reserve is left."""


def request_tap(
    student: Membership, *, kind: str, inputs: TapQueryInputs | None = None
) -> SearchTap:
    """Open the cycle's wallet, check the tap is permitted, record it, queue it.

    `inputs` is a follow-up's new part; None searches the whole profile's
    query words. Raises TapRefused, whose message is shown to the student.
    Call it outside a transaction (Task 4c calls it from on_commit): the tap
    row commits before its message is sent, so the worker always finds it.
    """
    with tenant_transaction(student.tenant_id):
        run = (
            RecommendationRun.objects.filter(
                profile_version__student=student, profile_version__schema_version=3
            )
            .order_by("-created_at")
            .first()
        )
        profile = _profile_for(run) if run is not None else None
    if run is None or profile is None:
        raise TapRefused("finish the consultation first")
    wallet = open_wallet(student, profile.intended_intake)
    check_tap_permitted(student, wallet, now=timezone.now())
    if kind == _Kind.FIRST:
        # The reserve keeps follow-ups possible after one big first search.
        allowance = remaining(wallet) - settings.SEARCH_FOLLOWUP_RESERVE_USD
        if allowance <= 0:
            raise ReserveOnly("this cycle's search budget is kept for follow-up searches")
    else:
        allowance = tap_allowance(wallet)
    with tenant_transaction(student.tenant_id):
        tap = SearchTap.objects.create(
            student=student, wallet=wallet, run_id=run.id, kind=kind, allowance_usd=allowance
        )
    message = ResearchMessage(
        kind="search_tap", tenant_id=student.tenant_id, run_id=run.id, tap_id=tap.id,
        inputs=inputs,
    )
    try:
        enqueue_research(message, queue_url=settings.RESEARCH_QUEUE_URL)
    except Exception as error:
        # A tap nothing will run must not stand QUEUED and count toward
        # TAP_PER_DAY. Not folded into recover_undispatched_runs: a follow-up's
        # new part lives only on the message, so a re-sent tap would search
        # the wrong words.
        logger.exception("search tap %s not queued; removed", tap.id)
        with tenant_transaction(student.tenant_id):
            SearchTap.objects.filter(id=tap.id).delete()
        raise TapRefused("the search could not be started; try again") from error
    return tap


#: A change to any of these alters words a query prints beside the field,
#: interests and destinations, so those go out whole, not just their new part.
_SHAPING = (
    "acceptable_teaching_languages", "funding_dependency", "strategy", "intended_intake",
    "duration_preference", "career_intent",
)


def _new_part(
    previous: StudentProfileSnapshot, current: StudentProfileSnapshot, *, whole: bool = False
) -> TapQueryInputs | None:
    """What a follow-up searches after `previous` became `current`, or None when
    nothing new could render a query.

    The dimension that gained values (field, interests, destinations) carries
    only its ADDED values; every other goes WHOLE, so an added country is asked
    with the student's field and an added interest in every destination. A
    changed field is the new field whole. When more than one dimension gained,
    or a shaping key changed (`whole`), everything goes whole. Combinations
    already asked cost nothing: TapQueryRun reuse skips them. Both sides go
    through `inputs_from`, so the student's own schools and home country are
    filtered out exactly as from every other query."""
    old, new = inputs_from(previous), inputs_from(current)
    if whole:
        # A new teaching language leads the query; otherwise the current ones.
        added_languages = tuple(
            w for w in new.teaching_languages if w not in old.teaching_languages
        )
        delta = replace(new, teaching_languages=added_languages or new.teaching_languages)
    else:
        field = new.field_words if new.field_words != old.field_words else ()
        interests = tuple(w for w in new.interest_words if w not in old.interest_words)
        destinations = tuple(d for d in new.destinations if d not in old.destinations)
        if not new.destinations and old.destinations:
            # "DE" -> anywhere: the target countries not already searched. Raw and
            # catalogue-free (the worker orders nothing here, it is an explicit list).
            excluded = set(current.excluded_countries)
            destinations = tuple(
                c for c in TARGET_COUNTRIES if c not in old.destinations and c not in excluded
            )
        gained = sum(map(bool, (field, interests, destinations)))
        if not gained:
            return None  # e.g. a country only removed: nothing new to search
        delta = new if gained > 1 else replace(
            new,
            field_words=field or new.field_words,
            interest_words=interests or new.interest_words,
            destinations=destinations or new.destinations,
        )
    # Every stored template needs {field} or {interest}: without both, nothing renders.
    return delta if delta.field_words or delta.interest_words else None


#: A FIRST search that ended in one of these did not search the student's
#: profile, so it does not count as their first search.
_FIRST_FAILED = (_Ending.FAILED, _Ending.NO_PROVIDER, _Ending.NO_ANGLES, _Ending.NO_QUERIES)


def _first_search_owed(student: Membership, current: StudentProfileSnapshot) -> bool:
    """True unless the current cycle's wallet holds a FIRST search that ran or
    is running. A tap still QUEUED or in STAGE1 after twice its time cap was
    lost (no worker took it, or one died mid-run) and is owed again; one that
    has continued (`resume` set) has twice its time cap for every job it may run."""
    wallet = open_wallet(student, current.intended_intake)
    cap = timedelta(seconds=2 * settings.FIRST_SEARCH_MAX_SECONDS)
    now, unfinished = timezone.now(), (SearchTap.State.QUEUED, SearchTap.State.STAGE1)
    failed = (
        Q(ending__in=_FIRST_FAILED)
        | Q(state__in=unfinished, resume__isnull=True, requested_at__lt=now - cap)
        | Q(
            state__in=unfinished, resume__isnull=False,
            requested_at__lt=now - cap * (settings.FIRST_SEARCH_MAX_CONTINUATIONS + 1),
        )
    )
    with tenant_transaction(student.tenant_id):
        return not (
            SearchTap.objects.filter(wallet=wallet, kind=_Kind.FIRST).exclude(failed).exists()
        )


def on_saved_versions(
    previous_version_id: UUID | None, current: StudentProfileSnapshot, student: Membership
) -> None:
    """The on_commit entry: loads and validates the previous snapshot HERE, so a
    stored row that no longer validates can never roll the intake back. An
    unreadable one is not "no previous" (that would run a FIRST search again,
    up to $90): a warning is logged and nothing is searched."""
    if not settings.TAP_AUTOMATIC:
        return
    previous: StudentProfileSnapshot | None = None
    try:
        if previous_version_id is not None:
            with tenant_transaction(student.tenant_id):
                stored = StudentProfileVersion.objects.get(id=previous_version_id)
            previous = StudentProfileSnapshot.model_validate(stored.snapshot)
    except Exception:
        logger.warning("previous profile %s unreadable; no search", previous_version_id,
                       exc_info=True)
        return
    on_profile_saved(previous, current, student)


def on_profile_saved(
    previous: StudentProfileSnapshot | None, current: StudentProfileSnapshot, student: Membership
) -> None:
    """What starts a search (called from finalize_consultation's on_commit).

    Nothing unless TAP_AUTOMATIC. Never raises: the intake has already
    finished. A FIRST search while the cycle's wallet has none that ran (spec
    10.5: a first search that failed is owed again), else a FOLLOW_UP for the
    new part. The pack is not rebuilt here: every finalize creates a run the
    view sends to the worker, and the web role cannot read the catalogue.
    ponytail: a second follow-up the same day is refused by TAP_PER_DAY rather
    than coalesced; add a coalescing queue if students edit often.
    """
    if not settings.TAP_AUTOMATIC:
        return
    try:
        if previous is None or _first_search_owed(student, current):
            try:
                request_tap(student, kind=_Kind.FIRST)
                return
            except ReserveOnly:
                # Nothing above the reserve, which a follow-up may spend: a
                # first search that crashed after spending the budget would
                # otherwise leave the student with no search all cycle.
                if previous is None:
                    raise
        before, after = previous.model_dump(mode="json"), current.model_dump(mode="json")
        queried = [key for key in QUERY_WORDS if before.get(key) != after.get(key)]
        delta = (
            _new_part(previous, current, whole=any(key in _SHAPING for key in queried))
            if queried else None
        )
        if delta is None:
            logger.info("profile saved for %s: nothing new to search", student.id)
            return
        request_tap(student, kind=_Kind.FOLLOW_UP, inputs=delta)
    except TapRefused as refused:
        logger.info("search not started for %s: %s", student.id, refused)
    except Exception:
        logger.exception("search not started for %s", student.id)


# --- 2. run (worker side) -------------------------------------------------------


def run_tap(
    tap_id: UUID,
    *,
    inputs: TapQueryInputs | None = None,
    seams: TapSeams | None = None,
    providers: Sequence[SearchProvider] | None = None,
) -> None:
    """Run one tap, once. Called inside the message's `tenant_scope`.

    Claimed QUEUED -> STAGE1 atomically, so a redelivered message spends
    nothing twice. A FIRST search that ran out of time is handed back QUEUED
    with `resume` set and sent again (`_continue`); that message's claim
    continues it. Any unexpected exception ends the tap FAILED and is
    re-raised for the queue to dead-letter; charges already made stay
    committed (each is its own transaction).
    """
    with tenant_transaction(current_tenant_id()):
        claimed = SearchTap.objects.filter(id=tap_id, state=SearchTap.State.QUEUED).update(
            state=SearchTap.State.STAGE1
        )
        tap = SearchTap.objects.get(id=tap_id)
    if not claimed:
        logger.warning("search tap %s is %s, not QUEUED: not run again", tap.id, tap.state)
        return
    try:
        if _run(tap, inputs, seams, providers):
            return  # continued: the tap is QUEUED again and belongs to the next job
    except Exception as error:
        if tap.state == SearchTap.State.QUEUED:
            # Saved and QUEUED, but not sent: this message stays undeleted, and
            # SQS redelivering it continues the tap.
            raise
        logger.error("search tap %s failed: %s", tap.id, type(error).__name__)
        tap.ending = _Ending.FAILED
        _finish(tap)
        raise
    tap.ending = tap.ending or _Ending.COMPLETE
    _finish(tap)


def _run(
    tap: SearchTap,
    inputs: TapQueryInputs | None,
    seams: TapSeams | None,
    providers: Sequence[SearchProvider] | None,
) -> bool:
    """True when the tap continues in a new job (it was saved and sent again)."""
    angles: AngleSource = seams or bound_angles()
    passes: PassStates = seams or bound_pass_states()
    first = tap.kind == _Kind.FIRST
    # The newest stored table, read once, as the worker's own pack build does
    # (run_research_worker): without it every rebuild below publishes the
    # "No exchange-rate table is loaded" empty pack.
    rates = latest_table()

    # Step 1: the catalogue serves first, before any provider is asked.
    with tenant_transaction(tap.tenant_id):
        run = RecommendationRun.objects.get(id=tap.run_id)
        profile = _profile_for(run)
        # A continuation read nothing yet, so it serves the pack its first job published.
        if tap.resume and tap.pack_version_id is not None:
            pack = PackVersion.objects.get(id=tap.pack_version_id)
        else:
            pack = rebuild_pack(run, rates=rates)
    tap.pack_version_id = pack.id
    if profile is None:  # request_tap refuses these; a run edited since is a bug
        raise ValueError("the tap's run has no full profile")
    asked = inputs or inputs_from(profile)
    reader: HostReader = seams or bound_host_reader()
    if hasattr(reader, "field") and not getattr(reader, "field", ""):
        reader.field = profile.target_field
    # No country picked means every target country, thinnest catalogue first; the
    # web hook's delta stays raw, so the expansion happens here, in the worker.
    destinations = inputs_from(profile).destinations
    if not (asked.destinations and destinations):
        with tenant_transaction(tap.tenant_id):
            everywhere = anywhere(profile.excluded_countries)
        # A delta to "anywhere" (DE -> 52 new) is ordered the same way, so a
        # follow-up's query cap goes to the thinnest countries, not the EU head.
        rank = {code: index for index, code in enumerate(everywhere)}
        ordered = tuple(sorted(asked.destinations, key=lambda c: rank.get(c, len(rank))))
        asked = replace(asked, destinations=ordered or everywhere)
        destinations = destinations or everywhere

    effective_profile = profile
    if inputs is not None and inputs.interest_words:
        merged_interests = tuple(
            dict.fromkeys((*profile.research_interests, *inputs.interest_words))
        )
        effective_profile = profile.model_copy(update={"research_interests": merged_interests})

    with tenant_transaction(tap.tenant_id):
        hybrid_plan = plan_hybrid_retrieval(effective_profile, pack=pack, passes=passes)
        verify_due_cb = getattr(seams, "verify_due_cycles", None)
        if not tap.resume and hybrid_plan.due_verification_ids and callable(verify_due_cb):
            reverified = verify_due_cb(hybrid_plan.due_verification_ids)
            if reverified:
                pack = rebuild_pack(run, rates=rates)
                tap.pack_version_id = pack.id
                hybrid_plan = plan_hybrid_retrieval(effective_profile, pack=pack, passes=passes)
    if (
        not tap.resume
        and hybrid_plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE
        and asked.destinations
        and set(asked.destinations) <= set(hybrid_plan.hot_countries)
    ):
        maybe_queue_area_sweep(tap, pack, passes)
        tap.ending = _Ending.COMPLETE
        return False
    if not tap.resume and hybrid_plan.hot_countries:
        narrowed = apply_hybrid_plan_to_tap_inputs(asked, hybrid_plan)
        if narrowed.destinations:
            asked = narrowed
            destinations = narrowed.destinations

    # Step 4: an area past its economic stop (or needing only cycle refresh)
    # asks only this cycle's recency angles.
    areas = [(code, _PROGRAMME_FAMILY) for code in destinations]
    cycle_only_set = frozenset(hybrid_plan.cycle_refresh_only_countries)
    with tenant_transaction(tap.tenant_id):
        tap.recency_only = bool(areas) and (
            all(passes.state(country, family).past_economic_stop for country, family in areas)
            or (bool(cycle_only_set) and set(destinations) <= cycle_only_set)
        )
    get = angles.recency_angles if tap.recency_only else angles.programme_angles

    # Step 2: stage 1.
    seconds = settings.FIRST_SEARCH_MAX_SECONDS if first else settings.TAP_MAX_SECONDS
    stage = _Stage1(
        tap=tap, providers=list(providers if providers is not None else default_providers()),
        meter=_WalletMeter(tap), deadline=time.monotonic() + seconds,
    )
    if tap.resume:
        stage.restore(tap.resume)
    languages = _teaching_languages(profile)
    if first:
        _first_stages(
            stage,
            asked,
            get,
            languages,
            targeted_queries=hybrid_plan.targeted_queries,
        )
    else:
        _follow_up_stage(
            stage,
            asked,
            get,
            languages,
            targeted_queries=hybrid_plan.targeted_queries,
        )
    if stage.out_of_time and not tap.ending:  # an ending found while draining wins
        _continue(tap, stage)
        return True

    # Step 3: stage 2 reads only the hosts the register lacked.
    tap.state = SearchTap.State.STAGE2
    with tenant_transaction(tap.tenant_id):
        SearchTap.objects.filter(id=tap.id).update(state=tap.state)
    republished, read = _stage_two(tap, run, stage.new, reader, rates, seed_urls=stage.seed_urls)
    pack = republished or pack
    tap.pack_version_id = pack.id
    # A search counts as done only once every new host it found was actually read.
    stage.write_query_runs(read)

    # Step 5: a thin area is a cell's problem -- one bounded, platform-paid sweep.
    maybe_queue_area_sweep(tap, pack, passes)
    return False


def _continue(tap: SearchTap, stage: _Stage1) -> None:
    """Save the place, hand the tap back QUEUED, and send it again.

    Saved first, sent second. A crash (or a failed send) between the two
    leaves a QUEUED tap and THIS message undeleted, so SQS redelivers it and
    its claim continues the tap. Sent first, a crash before the save would
    leave the tap in STAGE1, which every later claim refuses. Stage 2 waits
    for the job that ends the search: `resume` carries this job's new hosts."""
    resume = stage.resume()
    with tenant_transaction(tap.tenant_id):
        SearchTap.objects.filter(id=tap.id).update(
            state=SearchTap.State.QUEUED, resume=resume, recency_only=tap.recency_only,
            pack_version_id=tap.pack_version_id, provider_calls=tap.provider_calls,
            hosts_seen=tap.hosts_seen, hosts_new=tap.hosts_new,
            queries_reused=tap.queries_reused,
        )
    # Only once saved: a save that failed leaves the tap STAGE1, and run_tap
    # ends it FAILED rather than leave it to a claim that would refuse it.
    tap.resume, tap.state = resume, SearchTap.State.QUEUED
    logger.info(
        "search tap %s out of time: continuation %d queued", tap.id, tap.resume["continuations"]
    )
    enqueue_research(
        ResearchMessage(
            kind="search_tap", tenant_id=tap.tenant_id, run_id=tap.run_id, tap_id=tap.id
        ),
        queue_url=settings.RESEARCH_QUEUE_URL,
    )


def _follow_up_stage(
    stage: _Stage1,
    inputs: TapQueryInputs,
    get: _AngleGetter,
    languages: tuple[str, ...],
    *,
    targeted_queries: Sequence[SearchRequest] = (),
) -> None:
    angles = _angles_for(stage.tap, get, languages)
    if not angles:
        stage.tap.ending = _Ending.NO_ANGLES
        return
    # Render every query, drop those every live provider already ran inside the
    # reuse window, THEN cap: a repeat must not spend a cap slot a new query needs
    # (a save adding a country and an interest rendered 61, 21 new, 7 fit).
    # ponytail: no combined tail query -- a country past the cap is simply not
    # asked in this follow-up; the next follow-up or the cell sweep picks it up.
    rendered = stage.render(inputs, angles)
    if not rendered:
        stage.tap.ending = _Ending.NO_QUERIES
        return
    dest_codes = {c.lower() for c in inputs.destinations}
    for tq in targeted_queries:
        if dest_codes and tq.country_code and tq.country_code.lower() not in dest_codes:
            continue
        stage.kinds.setdefault(tq.query, "MONEY")
        if tq not in rendered:
            rendered.append(tq)
    live = stage._live()
    requests = []
    for request in rendered:
        if live and all(stage._reused(p.name, request) for p in live):
            stage.tap.queries_reused += len(live)
        else:
            requests.append(request)
    stage.ask_all(requests[: settings.TAP_MAX_QUERIES])


def _first_stages(
    stage: _Stage1,
    inputs: TapQueryInputs,
    get: _AngleGetter,
    languages: tuple[str, ...],
    *,
    targeted_queries: Sequence[SearchRequest] = (),
) -> None:
    """Coverage, then local, then deep; each stage only if the last did not stop."""
    coverage_angles = _angles_for(stage.tap, get, languages)
    local: list[SearchRequest] = []
    any_local = False
    for code in inputs.destinations:
        own = tuple(lang for lang in CldrLanguages().languages(code) if lang not in languages)
        found = _angles_for(stage.tap, get, own)
        any_local = any_local or bool(found)
        one = replace(inputs, destinations=(code,))
        local += stage.render(one, found)
    if not coverage_angles and not any_local:
        stage.tap.ending = _Ending.NO_ANGLES
        return
    coverage = stage.render(inputs, coverage_angles)
    if not coverage and not local:
        stage.tap.ending = _Ending.NO_QUERIES
        return
    dest_codes = {c.lower() for c in inputs.destinations}
    for tq in targeted_queries:
        if dest_codes and tq.country_code and tq.country_code.lower() not in dest_codes:
            continue
        stage.kinds.setdefault(tq.query, "MONEY")
        if tq not in coverage:
            coverage.append(tq)
    # A continued search starts at the stage it stopped in; what it already
    # asked is skipped (`asked`), and the coverage ranking it built is kept.
    while stage.step < 3:
        if stage.step == 0:
            asked_now = stage.ask_all(coverage, found=stage.ranking)
        elif stage.step == 1:
            asked_now = stage.ask_all(local)
        else:
            top = sorted(stage.ranking, key=lambda request: -stage.ranking[request])
            deep = settings.FIRST_SEARCH_DEEP_RESULTS
            asked_now = stage.ask_all(
                [replace(r, max_results=deep) for r in top[: math.ceil(len(top) * _DEEP_SHARE)]],
                exa_only=True,
            )
        if asked_now is None:
            return
        stage.step += 1
        stage.window.clear()  # the plateau window is per stage
    if stage.plateaued:
        stage.tap.ending = _Ending.PLATEAU


_AngleGetter = Callable[..., tuple[AngleRow, ...]]
#: What a provider call raises when the index refuses or the network fails
#: (fetch_json_api: SourceBlocked for an HTTP 429/5xx, a bad body or urllib3;
#: UnsafeTarget/JSON decode are ValueErrors; DNS is an OSError). A database
#: error is none of these, so a failed charge is never mistaken for a provider.
_PROVIDER_ERRORS = (SourceBlocked, OSError, ValueError)


@dataclass
class _CallMeter(SearchMeter):
    """A worker thread's meter: notes each charge for the main thread to record."""

    charges: list[tuple[str, float]] = field(default_factory=list)

    def charge(self, provider: str, usd: float) -> None:
        super().charge(provider, usd)
        self.charges.append((provider, usd))


class _Answer(NamedTuple):
    """One provider's answer to one request, as a worker thread returns it."""

    provider: str
    urls: list[str]
    meter: _CallMeter
    error: Exception | None


def _call(providers: list[SearchProvider], request: SearchRequest) -> list[_Answer]:
    """A worker thread's whole job: ask each provider, one after another. No
    database, no settings, no tap: the main thread records what comes back."""
    answers = []
    for provider in providers:
        meter = _CallMeter()
        try:
            # islice: a paging provider (Brave) is never asked for a page
            # past the results this request wants.
            urls = list(islice(provider.search(request, meter), request.max_results))
        except Exception as error:
            answers.append(_Answer(provider.name, [], meter, error))
            if not isinstance(error, _PROVIDER_ERRORS):
                break  # not the index refusing: the main thread raises it
            continue
        answers.append(_Answer(provider.name, urls, meter, None))
    return answers


def _request_json(request: SearchRequest) -> dict[str, Any]:
    # The tap never sets a denylist: the default is restored, not stored.
    return {k: v for k, v in asdict(request).items() if k != "denylist"}


@dataclass
class _Stage1:
    """Stage 1's running state: what was asked, seen and new, and why it stopped."""

    tap: SearchTap
    providers: list[SearchProvider]
    meter: _WalletMeter
    deadline: float
    seen: set[str] = field(default_factory=set)
    new: list[str] = field(default_factory=list)
    #: Deep URLs returned by Stage 1 per novel domain, preserved so Stage 2 reads
    #: the specific programme/scholarship page rather than only `https://<domain>/`.
    seed_urls: dict[str, list[str]] = field(default_factory=dict)
    asked: set[tuple[str, int]] = field(default_factory=set)
    window: deque[int] = field(
        default_factory=lambda: deque(maxlen=settings.FIRST_SEARCH_PLATEAU_BATCH)
    )
    #: Providers that failed this job: not asked again by it (one 429 must not
    #: end a student's only first search, and must not be asked 300 more times).
    #: Not carried into `resume`: the next job asks every provider again.
    dropped: set[str] = field(default_factory=set)
    #: A FIRST stage stopped on the plateau rule; the next stage still runs.
    plateaued: bool = False
    #: Calls made this tap, written as reuse rows only after stage 2 handled their hosts.
    #: Each with the registrable domains it hit.
    calls: list[tuple[str, SearchRequest, set[str]]] = field(default_factory=list)
    #: Angle kind by query text, filled as requests are rendered (a deep re-ask
    #: keeps the text, so it keeps the kind). Absent means PROGRAMME.
    kinds: dict[str, str] = field(default_factory=dict)
    #: FIRST: the stage running (0 coverage, 1 local, 2 deep), the coverage
    #: queries' new hosts (the deep stage's ranking), the jobs this tap continued
    #: from, and whether this job ran out of time with a continuation left.
    step: int = 0
    ranking: dict[SearchRequest, int] = field(default_factory=dict)
    continuations: int = 0
    out_of_time: bool = False

    def resume(self) -> dict[str, Any]:
        """Where a FIRST search stopped, as JSON, for the job that continues it."""
        return {
            "continuations": self.continuations + 1,
            "step": self.step,
            "window": list(self.window),
            "plateaued": self.plateaued,
            "ranking": [[_request_json(r), n] for r, n in self.ranking.items()],
            "asked": sorted([query, n] for query, n in self.asked),
            "seen": sorted(self.seen),
            "new": self.new,
            "seed_urls": self.seed_urls,
            "calls": [[p, _request_json(r), sorted(hit)] for p, r, hit in self.calls],
        }

    def restore(self, saved: dict[str, Any]) -> None:
        """The inverse of `resume`; JSON's lists become tuples and sets again."""
        self.continuations, self.step = saved["continuations"], saved["step"]
        self.window.extend(saved["window"])
        self.plateaued = saved["plateaued"]
        self.ranking = {SearchRequest(**r): n for r, n in saved["ranking"]}
        self.asked = {(query, n) for query, n in saved["asked"]}
        self.seen, self.new = set(saved["seen"]), list(saved["new"])
        self.seed_urls = {k: list(v) for k, v in saved.get("seed_urls", {}).items()}
        self.calls = [(p, SearchRequest(**r), set(hit)) for p, r, hit in saved["calls"]]

    def render(self, inputs: TapQueryInputs, angles: tuple[AngleRow, ...]) -> list[SearchRequest]:
        kind_of = {a.id: a.kind for a in angles}
        rendered = render_tap_queries(inputs, angles)
        for angle_id, request in rendered:
            # Same text from two kinds: the shorter window (non-PROGRAMME) wins.
            if self.kinds.get(request.query, "PROGRAMME") == "PROGRAMME":
                self.kinds[request.query] = kind_of[angle_id]
        return [request for _, request in rendered]

    @property
    def first(self) -> bool:
        return self.tap.kind == _Kind.FIRST

    def ask_all(
        self, requests: Sequence[SearchRequest], *, exa_only: bool = False,
        found: dict[SearchRequest, int] | None = None,
    ) -> dict[SearchRequest, int] | None:
        """New hosts per request asked (added to `found` when given), or None
        once an ending stopped the whole search or this job ran out of time.
        A plateau stops only this stage, so a FIRST search's next stage still
        runs. A request this tap already asked (the same text at the same
        depth) is skipped.

        Up to TAP_PARALLEL_CALLS requests in flight. Whatever stops the stage
        stops only the submitting: calls already in flight were paid for, so
        they are drained and recorded, in submission order."""
        found = {} if found is None else found
        width = settings.TAP_PARALLEL_CALLS
        todo = iter(requests)
        pending: deque[tuple[SearchRequest, Decimal, Future[list[_Answer]]]] = deque()
        in_flight = Decimal("0")
        full = False  # this stage plateaued
        with ThreadPoolExecutor(max_workers=width, thread_name_prefix="tap") as pool:
            try:
                while True:
                    while len(pending) < width and not (
                        full or self.tap.ending or self.out_of_time
                    ):
                        request = next(todo, None)
                        if request is None:
                            break
                        key = (request.query, request.max_results)
                        if key in self.asked:
                            continue
                        planned = self._plan(request, exa_only=exa_only, in_flight=in_flight)
                        if planned is None:
                            break  # out of time before it was asked: a continuation asks it
                        self.asked.add(key)
                        asking, price = planned
                        if asking:
                            in_flight += price
                            pending.append((request, price, pool.submit(_call, asking, request)))
                    if not pending:
                        break
                    request, price, future = pending.popleft()
                    in_flight -= price
                    new = self._take(request, future.result())
                    if new < 0:  # no provider answered: the plateau window does not move
                        continue
                    found[request] = new
                    if self.first:
                        self.window.append(new)
                        if (
                            len(self.window) == self.window.maxlen
                            and sum(self.window) < settings.FIRST_SEARCH_PLATEAU_MIN_NEW
                        ):
                            self.plateaued = full = True
            finally:
                # An error stopped the stage with calls in flight: still charge them.
                for _, _, future in pending:
                    for answer in future.result():
                        for provider, usd in answer.meter.charges:
                            try:
                                self.meter.charge(provider, usd)
                            except DatabaseError:
                                logger.exception(
                                    "search tap %s: %s charge not recorded", self.tap.id, provider
                                )
        # A plateau found while draining still ends the stage: the next job
        # starts at the next one.
        return None if self.tap.ending or (self.out_of_time and not full) else found

    def _plan(
        self, request: SearchRequest, *, exa_only: bool, in_flight: Decimal
    ) -> tuple[list[SearchProvider], Decimal] | None:
        """On the main thread, before a request is sent: the providers to ask
        and their worst-case price, every check made and every count moved.
        None when time ran out first; an ending set here stops the stage after
        the providers already approved are asked."""
        if time.monotonic() >= self.deadline:
            if self.first and self.continuations < settings.FIRST_SEARCH_MAX_CONTINUATIONS:
                self.out_of_time = True
            else:
                self.tap.ending = _Ending.TIME_CAP
            return None
        asking: list[SearchProvider] = []
        price = Decimal("0")
        if not self._live():
            self.tap.ending = _Ending.NO_PROVIDER
        for provider in self._live():
            if exa_only and provider.name != "exa":
                continue  # Brave returns at most 20 a query: no deep stage there
            if self._reused(provider.name, request):
                self.tap.queries_reused += 1
                continue
            if not self.first and self.tap.provider_calls >= settings.TAP_MAX_PROVIDER_CALLS:
                self.tap.ending = _Ending.CALL_CAP
                break
            try:
                # Calls in flight are not charged yet: their worst case counts as spent.
                price += preflight(
                    self.tap, provider.name, worst=_worst(provider.name, request),
                    in_flight=in_flight + price,
                )
            except WalletExhausted as spent:
                self.tap.ending = _money_ending(spent.ending, first=self.first)
                break
            self.tap.provider_calls += 1
            asking.append(provider)
        return asking, price

    def _take(self, request: SearchRequest, answers: list[_Answer]) -> int:
        """On the main thread: charge, record and drop from one request's
        answers. New hosts it found; -1 when no provider answered it."""
        for answer in answers:  # every charge first: nothing below may lose one
            for provider, usd in answer.meter.charges:
                self.meter.charge(provider, usd)
        found, answered = 0, False
        for answer in answers:
            if answer.error is not None:
                if not isinstance(answer.error, _PROVIDER_ERRORS):
                    raise answer.error
                logger.warning(
                    "search tap %s: %s failed (%s: %s); not asked again by this tap",
                    self.tap.id, answer.provider, type(answer.error).__name__, answer.error,
                )
                self.dropped.add(answer.provider)
                continue
            answered = True
            hit: set[str] = set()
            self.calls.append((answer.provider, request, hit))
            for_scholarship = self.kinds.get(request.query, "PROGRAMME") == "MONEY"
            found += self._record(
                answer.urls, answer.provider, hit, for_scholarship=for_scholarship
            )
        if self.meter.exhausted and not self.tap.ending:  # recorded what it paid for; now stop
            self.tap.ending = _money_ending(self.meter.exhausted, first=self.first)
        if not self._live() and not self.tap.ending:
            self.tap.ending = _Ending.NO_PROVIDER
        return found if answered else -1

    def _reused(self, provider: str, request: SearchRequest) -> bool:
        """A PROGRAMME query counts for the whole academic cycle, whatever its age;
        a MONEY or RECENCY one only within TAP_QUERY_REUSE_DAYS. An earlier cycle
        never counts."""
        now = timezone.now()
        kind = self.kinds.get(request.query, "PROGRAMME")
        rows = TapQueryRun.objects.filter(
            query_sha256=_query_hash(provider, request), provider=provider,
            results=request.max_results, kind=kind, cycle=cycle_label(now),
        )
        if kind != "PROGRAMME":
            rows = rows.filter(ran_at__gte=now - timedelta(days=settings.TAP_QUERY_REUSE_DAYS))
        with tenant_transaction(self.tap.tenant_id):
            return rows.exists()

    def write_query_runs(self, read: set[str]) -> None:
        """The one place a call becomes a reuse row: only when every host this tap
        found new that the call hit was read. A call with no new host needs no reading."""
        unread = set(self.new) - read
        for provider, request, hit in self.calls:
            if not hit & unread:
                self._remember(provider, request)
        self.calls.clear()

    def _remember(self, provider: str, request: SearchRequest) -> None:
        """Note the query for reuse. Runs after a PAID call: failing to note it
        costs a repeat later, while raising would lose the URLs paid for."""
        try:
            with tenant_transaction(self.tap.tenant_id):
                now = timezone.now()
                TapQueryRun.objects.update_or_create(
                    query_sha256=_query_hash(provider, request), provider=provider,
                    results=request.max_results,
                    kind=self.kinds.get(request.query, "PROGRAMME"),
                    defaults={"ran_at": now, "cycle": cycle_label(now)},
                )
        except DatabaseError:
            logger.exception("search tap %s: query not remembered for reuse", self.tap.id)

    def _live(self) -> list[SearchProvider]:
        return [p for p in self.providers if p.name not in self.dropped]

    def _record(
        self,
        urls: list[str],
        provider: str,
        hit: set[str],
        *,
        for_scholarship: bool = False,
    ) -> int:
        """Dedupe every hit against the register BEFORE anything is fetched;
        record each new domain as a CANDIDATE for stage 2 and preserve its deep URLs."""
        new = 0
        for url in urls:
            host = urlsplit(url).hostname or ""
            domain = (
                registrable_domain(host)
                if host and not is_catalogue(host, for_scholarship=for_scholarship)
                else ""
            )
            if not domain:
                continue
            hit.add(domain)
            domain_seeds = self.seed_urls.setdefault(domain, [])
            if url not in domain_seeds and len(domain_seeds) < 3:
                domain_seeds.append(url)
            if domain in self.seen:
                continue
            self.seen.add(domain)
            self.tap.hosts_seen += 1
            with tenant_transaction(self.tap.tenant_id):
                # Known unless an earlier search recorded it and nothing ever read it.
                owners = list(
                    OrganisationDomain.objects.filter(registrable_domain=domain).values_list(
                        "organisation__status", "organisation__last_verified"
                    )
                )
                unread = (Organisation.Status.CANDIDATE, None)
                if any(owner != unread for owner in owners):
                    continue
                if not owners:
                    record_organisation(
                        domain=domain, name=domain, kind="UNSTATED", country_code="",
                        status=Organisation.Status.CANDIDATE, found_via=f"TAP:{provider}",
                    )
            self.new.append(domain)
            self.tap.hosts_new += 1
            new += 1
        return new


def _query_hash(provider: str, request: SearchRequest) -> str:
    """HMAC-sha256 of the text the provider receives (Brave sends `terms` when set)."""
    sent = (request.terms or request.query) if provider == "brave" else request.query
    # Keyed: TapQueryRun is shared and outlives a student's erasure, and the text can
    # carry their interest words -- a plain sha256 is reversible by guessing queries.
    return hmac.new(settings.SECRET_KEY.encode(), sent.encode(), hashlib.sha256).hexdigest()


def _worst(provider: str, request: SearchRequest) -> Decimal | None:
    """A worst case the price table does not hold: Exa beyond 15 results."""
    if provider != "exa" or request.max_results <= _EXA_PRICED_RESULTS:
        return None
    extra = request.max_results - _EXA_PRICED_RESULTS
    return settings.PROVIDER_CALL_PREFLIGHT_USD["exa"] + extra * _EXA_USD_PER_RESULT


def _money_ending(ending: str, *, first: bool) -> str:
    """A first search's allowance IS the wallet less the reserve, so running it
    out is the wallet spent, not a tap's share."""
    if first and ending == _Ending.TAP_SHARE_SPENT:
        return _Ending.WALLET_SPENT
    return ending


def _stage_two(
    tap: SearchTap,
    run: RecommendationRun,
    new: list[str],
    reader: HostReader,
    rates: RateTable | None,
    *,
    seed_urls: dict[str, list[str]] | None = None,
) -> tuple[PackVersion | None, set[str]]:
    """Read each new host while money is left; republish after each served award.
    Returns the latest pack (None when nothing was republished) and the
    domains actually read."""
    pack = None
    done: set[str] = set()
    accepts_seeds = bool(getattr(reader, "accepts_seed_urls", False))
    for domain in new:
        with tenant_transaction(tap.tenant_id):
            wallet = SearchWallet.objects.get(id=tap.wallet_id)
            left = spendable(tap, wallet)
        cap = page_backstop(remaining(wallet))
        if tap.kind == _Kind.FOLLOW_UP:
            cap = min(cap, settings.TAP_MAX_PAGES)
        if left <= 0 or tap.pages_fetched >= cap:
            break
        if accepts_seeds:
            read = reader.read(  # type: ignore[call-arg]
                domain,
                max_usd=left,
                seed_urls=tuple((seed_urls or {}).get(domain, ())),
            )
        else:
            read = reader.read(domain, max_usd=left)
        if read is None:
            tap.ending = tap.ending or _Ending.STAGE2_UNAVAILABLE
            break
        done.add(domain)
        tap.pages_fetched += 1
        tap.awards_served += read.awards_served
        try:
            charge(tap, kind=WalletCharge.Kind.READ, provider="reader", usd=read.cost_usd)
        except WalletExhausted as spent:
            tap.ending = tap.ending or _money_ending(spent.ending, first=tap.kind == _Kind.FIRST)
            break
        finally:
            if read.awards_served:
                with tenant_transaction(tap.tenant_id):
                    pack = rebuild_pack(run, rates=rates)
    return pack, done


def _finish(tap: SearchTap) -> None:
    tap.state = SearchTap.State.DONE
    tap.finished_at = timezone.now()
    tap.resume = None  # the student's query text: kept no longer than the search
    with tenant_transaction(tap.tenant_id):
        tap.save(update_fields=[
            "state", "ending", "finished_at", "recency_only", "pack_version_id",
            "provider_calls", "pages_fetched", "hosts_seen", "hosts_new", "awards_served",
            "queries_reused", "resume",
        ])
        spent = tap_spent(tap)
    logger.info(
        "search tap %s %s: %d calls, %d new hosts, %d served, $%s, ending %s, pack %s",
        tap.id, tap.kind, tap.provider_calls, tap.hosts_new, tap.awards_served, spent,
        tap.ending, tap.pack_version_id,
    )


@lru_cache(maxsize=1)
def _language_names() -> dict[str, str]:
    """CLDR's English language names -> code ("German" -> "de")."""
    return {
        name.casefold(): code.split("_")[0] for code, name in Locale("en").languages.items()
    }


def _teaching_languages(profile: StudentProfileSnapshot) -> tuple[str, ...]:
    """English, then each teaching language as a code. A name CLDR does not
    know is skipped and counted in the log, never echoed (it is free text)."""
    names = _language_names()
    codes = [
        names.get(name.strip().casefold(), "") for name in profile.acceptable_teaching_languages
    ]
    if unknown := codes.count(""):
        logger.info("%d teaching language(s) with no language code: no angles asked", unknown)
    return tuple(dict.fromkeys(["en", *(code for code in codes if code)]))


def _angles_for(
    tap: SearchTap, get: _AngleGetter, languages: Sequence[str]
) -> tuple[AngleRow, ...]:
    """Every angle stored for these languages, deduped by id. A language with
    none is logged and asked nothing -- never English text in its place."""
    rows: dict[str, AngleRow] = {}
    with tenant_transaction(tap.tenant_id):
        for language in languages:
            found = get(level=LEVEL, language=language)
            if not found:
                logger.info("no programme angles stored for language %s", language)
            for row in found:
                rows.setdefault(row.id, row)
    return tuple(rows.values())


# --- 3. the thin-area trigger (spec 10.5 step 5) ---------------------------------


def maybe_queue_area_sweep(
    tap: SearchTap, pack: PackVersion, passes: PassStates
) -> AreaSweep | None:
    """Queue (or add demand to) ONE bounded sweep of the student's thinnest area.

    Thin: zero eligible options in the pack just published, in a family with a
    sweep pass, whose pass has not finished with it. Ordered by this tenant's
    CellCoverage aiming priority, summed over the area's cells -- a read that
    stays inside the tenant. The row carries no tenant, student or count: it is
    shared catalogue. An area swept within CELL_SWEEP_COOLDOWN_DAYS is not swept
    again on demand. A blocked catalogue write (CatalogWriteBlocked) propagates
    to the tap's FAILED path; it is never swallowed.
    """
    with tenant_transaction(tap.tenant_id):
        areas = pack.coverage.get("areas", []) if isinstance(pack.coverage, dict) else []
        thin = sorted(
            (area["country"], area["family"])
            for area in areas
            if area.get("eligible") == 0 and area.get("family") in SWEEP_FAMILIES
            and not area_exhausted(passes.state(area["country"], area["family"]))
        )
        if not thin:
            return None
        priority: dict[tuple[str, str], float] = dict.fromkeys(thin, 0.0)
        for cell in CellCoverage.objects.filter(host_country__in={c for c, _ in thin}):
            key = (cell.host_country, FAMILY_BY_HOLDER.get(cell.holder, ""))
            if key in priority:
                priority[key] += cell.aiming_priority
    country, family = min(thin, key=lambda area: (-priority[area], area))
    return _queue_area(tap.tenant_id, country, family)


def _queue_area(tenant_id: UUID, country: str, family: str) -> AreaSweep | None:
    with tenant_transaction(tenant_id):
        open_ = AreaSweep.objects.filter(
            country_code=country, family=family,
            state__in=(AreaSweep.State.QUEUED, AreaSweep.State.RUNNING),
        )
        if (existing := open_.first()) is not None:
            update_exactly(
                AreaSweep.objects.filter(id=existing.id), demand=F("demand") + 1,
                error="area sweep demand not recorded: run as runtime_engine",
            )
            return existing
        cooldown = timezone.now() - timedelta(days=settings.CELL_SWEEP_COOLDOWN_DAYS)
        if AreaSweep.objects.filter(
            country_code=country, family=family, finished_at__gte=cooldown
        ).exists():
            return None  # just swept: demand does not buy a second sweep
        try:
            with transaction.atomic():
                return AreaSweep.objects.create(country_code=country, family=family)
        except IntegrityError:
            # Another tap queued it between the read and the write: add demand.
            update_exactly(
                open_, demand=F("demand") + 1,
                error="area sweep demand not recorded: run as runtime_engine",
            )
            return open_.first()
