"""The sweep harness -- one (host country, family) pass, spec 6.7.

A pass runs AFTER the register ladder (spec 6.2) and is charged for its
set-difference against it: every URL is keyed on its registrable domain and
checked against `OrganisationDomain` before anything is fetched. It asks the
pass's stored angle set (angles.py) breadth first -- every angle of one
(sample, language) is one batch -- classifies each host no route held
(classify.py, spec 6.6), and counts a host as a NEW VERIFIED HOST only when
the classifier says it funds students and its classified family is the
pass's: a foundation pass that surfaces a ministry gets no credit for it, or
the tally rewards the pass for noise.

Two stop rules, whichever fires first: no new verified host for three
consecutive batches (the set-expansion literature's rule, SetExpan /
GenExpan), and the economic one -- cost per new verified award above what the
option is worth. A decaying provider is dropped mid-pass on the same window.

The output is a curve, never a completeness claim: `SweepRun` + its
`SweepQuery` and `SweepDiscovery` rows are "swept to N queries, plateau R per
batch at precision P, spend S".
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from .angles import PASS_SHAPES, active_angles
from .domains import is_catalogue
from .fetch import SweepBudget
from .funding_reader import FAMILY_BY_HOLDER
from .hosts import registrable_domain
from .models import (
    ANGLE_KINDS,
    ClosedList,
    Organisation,
    OrganisationDomain,
    RegisterEntry,
    SweepAngle,
    SweepDiscovery,
    SweepQuery,
    SweepRun,
)
from .providers import SearchMeter, SearchProvider, SearchRequest
from .register import record_organisation

logger = logging.getLogger(__name__)

#: The plateau rule's window, and the economic and decay rules' too -- one
#: window so the three cannot disagree about what "recently" means.
STOP_WINDOW = 3

#: Decision 30: 10-15 per angle on Exa. Brave pages to its first empty page
#: on its own; Tavily caps at 20.
ANGLE_RESULTS = 15

#: classify_organisation outcomes after which no further host can be
#: verified, so the plateau rule would read an empty batch that is really an
#: unasked one.
_HALTING = {
    "budget": SweepRun.StopReason.BUDGET,
    "rate_limited": SweepRun.StopReason.CLASSIFIER_LIMIT,
}

_ANGLE_ORDER = {kind: i for i, kind in enumerate(ANGLE_KINDS)}


@dataclass(frozen=True)
class BatchResult:
    number: int
    #: Search spend plus classification-fetch spend, this batch.
    spend_usd: float
    novel: int
    verified: int
    verified_by_provider: Mapping[str, int] = field(default_factory=dict)


def _plateau(batches: Sequence[BatchResult]) -> bool:
    recent = batches[-STOP_WINDOW:]
    return len(recent) == STOP_WINDOW and all(b.verified == 0 for b in recent)


def _economic(
    batches: Sequence[BatchResult], *, value_per_award_usd: float, awards_per_verified_host: float
) -> bool:
    recent = batches[-STOP_WINDOW:]
    verified = sum(b.verified for b in recent)
    if verified == 0:
        # Nothing verified is the plateau rule's case; reading it here would
        # make "one empty first batch" an economic stop at infinite cost.
        return False
    cost_per_award = sum(b.spend_usd for b in recent) / (verified * awards_per_verified_host)
    return cost_per_award > value_per_award_usd


def stop_reason(
    batches: Sequence[BatchResult], *, value_per_award_usd: float, awards_per_verified_host: float
) -> str | None:
    if _plateau(batches):
        return "PLATEAU"
    if _economic(
        batches,
        value_per_award_usd=value_per_award_usd,
        awards_per_verified_host=awards_per_verified_host,
    ):
        return "ECONOMIC"
    return None


def decayed(batches: Sequence[BatchResult], providers: Sequence[str]) -> set[str]:
    recent = batches[-STOP_WINDOW:]
    if len(recent) < STOP_WINDOW or sum(b.verified for b in recent) == 0:
        return set()
    return {
        name
        for name in providers
        if all(b.verified_by_provider.get(name, 0) == 0 for b in recent)
    }


def ladder_rung(country_code: str, family: str) -> tuple[int, str]:
    """The register-ladder rung this pass runs after (spec 6.2, rulings R6, R12).

    The rung is a row, never a branch: it reads `ClosedList` for rows of this
    country (rung 1-4; rung 0 is an enumerator and no rung) holding one of the
    kinds the pass SEARCHES FOR, `PASS_SHAPES[family].kinds`, and returns the
    lowest rung, ties broken by slug. Not every kind `FAMILY_BY_HOLDER` files
    under the family: banks and professional bodies map to the foundation
    family but are reached by register and domain call, never open-web search
    (spec 6.3), so their lists are not this pass's denominator -- and an
    UNSTATED list wins nothing. "Verified" credit stays family-wide
    (`verified_for`, spec 6.7): a bank host a foundation pass finds still
    counts. No matching row means rung 4 (open search only, no register to
    diff against). Recapture is counted against the one winning list.

    A winning rung below 4 must already have been read: a rung claiming a
    register nothing has surveyed would report a set-difference against
    nothing, so an empty `RegisterEntry` table for that slug is refused.
    """
    candidates = [
        row
        for row in ClosedList.objects.filter(country_code=country_code, rung__gte=1, rung__lte=4)
        if any(kind in PASS_SHAPES[family].kinds for kind in row.holder_kinds)
    ]
    if not candidates:
        return 4, ""
    winner = min(candidates, key=lambda row: (row.rung, row.slug))
    if winner.rung <= 3 and not RegisterEntry.objects.filter(register=winner.slug).exists():
        raise ValueError(
            f"no RegisterEntry rows for {winner.slug!r}: read the register first (spec 6.7, "
            f"'the register ladder runs first') -- {country_code}/{family}"
        )
    return winner.rung, winner.slug


def verified_for(org: Organisation, family: str) -> bool:
    """A new verified host FOR THIS PASS (spec 6.7): classified, funds
    students, and of the pass's family by its CLASSIFIED kind. UNSTATED is
    excluded outright -- `FAMILY_BY_HOLDER` files it under PRIVATE_FOUNDATION
    for the reader's sake, and a foundation pass must not be credited with
    news sites the classifier could not place."""
    return (
        org.classified_at is not None
        and org.funds_students is True
        and org.kind != "UNSTATED"
        and FAMILY_BY_HOLDER.get(org.kind) == family
    )


@dataclass(frozen=True)
class PassConfig:
    country_code: str
    family: str
    languages: tuple[str, ...]
    rung: int
    register: str
    cycle: str
    budget_usd: float
    #: A diaspora pass's key (decision 37); "" for every other family.
    home_language: str = ""


def _batches(
    angles: Sequence[SweepAngle], languages: Sequence[str], rng: random.Random
) -> list[list[SweepAngle]]:
    """Breadth first: every angle of sample 0 in each language (local first,
    English last), then sample 1, and so on. One (sample, language) is one
    batch, shuffled by `rng` -- seeded with the run's id, so an angle's
    position changes between passes and a run is reproducible from its row.
    Under a fixed order the per-angle tally would measure position, not
    yield (spec 6.7)."""
    order = {language: i for i, language in enumerate(languages)}
    groups: dict[tuple[int, int], list[SweepAngle]] = {}
    for angle in angles:
        groups.setdefault((angle.sample, order[angle.language]), []).append(angle)
    batches: list[list[SweepAngle]] = []
    for key in sorted(groups):
        # Canonical first, so the shuffle does not depend on the DB's row order.
        group = sorted(groups[key], key=lambda a: _ANGLE_ORDER[a.angle])
        rng.shuffle(group)
        batches.append(group)
    return batches


@dataclass
class _PassState:
    run: SweepRun
    meter: SearchMeter
    fetch_budget: SweepBudget
    seen_this_run: set[str] = field(default_factory=set)
    recaptured: set[str] = field(default_factory=set)
    #: This run's discovery per novel domain, so a later provider that
    #: returns the host is appended to its `returned_by`.
    discoveries: dict[str, SweepDiscovery] = field(default_factory=dict)

    def spent(self) -> float:
        return self.meter.total() + self.fetch_budget.usd()


def _ask(
    state: _PassState,
    config: PassConfig,
    batch_number: int,
    angle: SweepAngle,
    provider: SearchProvider,
) -> list[tuple[Organisation, SweepQuery, SweepDiscovery]]:
    request = SearchRequest(
        query=angle.query,
        terms=angle.brave_terms,
        country_code=config.country_code,
        language=angle.language,
        phrasing="english" if angle.language == "en" else "local",
        max_results=ANGLE_RESULTS,
    )
    before = state.meter.total()
    # Created before the search runs, and updated after: a novel host's
    # SweepDiscovery row (below) needs a query to point at the moment it is
    # found, which may be before this call -- or this whole pass -- finishes.
    query = SweepQuery.objects.create(
        run=state.run, batch_number=batch_number, angle=angle, provider=provider.name,
    )
    seen = denied = 0
    novel: list[tuple[Organisation, SweepDiscovery]] = []
    for url in provider.search(request, meter=state.meter):
        seen += 1
        if is_catalogue(urlsplit(url).hostname or ""):
            # The exclusion parameter is a request, not a guarantee (the first
            # live TR sweep wrote twelve denylisted hosts as funders).
            denied += 1
            continue
        domain = registrable_domain(url)
        if not domain:
            continue
        held = domain in state.seen_this_run or OrganisationDomain.objects.filter(
            registrable_domain=domain
        ).exists()
        # Always recorded, so a second provider's route tag is appended even
        # on a host the first one already found -- the per-route tally of
        # spec 15 counts organisations per route.
        org = record_organisation(
            domain=domain, name=domain, kind="UNSTATED", country_code="",
            status=Organisation.Status.CANDIDATE, found_via=f"R4_SEARCH:{provider.name}",
        )
        if domain in state.seen_this_run:
            prior = state.discoveries.get(domain)
            if prior is not None and provider.name not in prior.returned_by:
                prior.returned_by.append(provider.name)
                prior.save(update_fields=["returned_by"])
            continue
        state.seen_this_run.add(domain)
        if held:
            if config.register and RegisterEntry.objects.filter(
                register=config.register, organisation=org
            ).exists():
                state.recaptured.add(domain)
            continue
        # Written the moment the host is known novel -- never after
        # classification, which may not run this batch (a halt) or this pass
        # at all (a crash): a credit that waited for batch-end classification
        # was orphaned by either, and a clean re-run then found the domain
        # already in OrganisationDomain and gave it no credit at all.
        discovery = SweepDiscovery.objects.create(
            run=state.run, query=query, organisation=org, verified_in_pass=False,
            returned_by=[provider.name],
        )
        state.discoveries[domain] = discovery
        novel.append((org, discovery))
    query.seen, query.denied, query.novel = seen, denied, len(novel)
    query.cost_usd = state.meter.total() - before
    query.save(update_fields=["seen", "denied", "novel", "cost_usd"])
    return [(org, query, discovery) for org, discovery in novel]


def run_pass(
    config: PassConfig,
    *,
    providers: Sequence[SearchProvider],
    classify: Callable[[Organisation], str],
    fetch_budget: SweepBudget,
    now: datetime,
    meter: SearchMeter | None = None,
) -> SweepRun:
    angles = active_angles(
        config.country_code, config.family, config.languages, config.home_language
    )
    if not angles:
        raise ValueError(
            f"no active angles for {config.country_code}/{config.family}"
            f"{'/' + config.home_language if config.home_language else ''} in "
            f"{config.languages}: run generate_sweep_angles first"
        )
    if stale := sorted({a.cycle for a in angles} - {config.cycle}):
        # Lever 6: a new cycle is a regeneration, never last cycle's time words.
        raise ValueError(
            f"angles for {config.country_code}/{config.family} name cycle {stale}, not "
            f"{config.cycle}: run generate_sweep_angles for this cycle first"
        )
    state = _PassState(
        run=SweepRun.objects.create(
            country_code=config.country_code, family=config.family,
            home_language=config.home_language, languages=list(config.languages),
            rung=config.rung, register=config.register,
            cycle=config.cycle, started_at=now,
        ),
        meter=meter or SearchMeter(),
        fetch_budget=fetch_budget,
    )
    live: dict[str, SearchProvider] = {p.name: p for p in providers}
    results: list[BatchResult] = []
    reason: str = SweepRun.StopReason.EXHAUSTED
    # Not a security use: a reproducible shuffle keyed on the run.
    rng = random.Random(state.run.id.int)  # nosec B311
    for number, group in enumerate(_batches(angles, config.languages, rng), start=1):
        spend_before = state.spent()
        found: list[tuple[Organisation, SweepQuery, SweepDiscovery]] = []
        halted: str | None = None
        for angle in group:
            # Provider order is immaterial: every provider that returns a host
            # is on its `returned_by`, and credit reads that, not who asked first.
            for provider in live.values():
                if state.spent() >= config.budget_usd:
                    halted = SweepRun.StopReason.BUDGET
                    break
                found.extend(_ask(state, config, number, angle, provider))
            if halted:
                break

        verified = 0
        by_provider: dict[str, int] = {}
        for org, _query, discovery in found:
            # Once halted, no further classify call this batch -- in the real
            # classify_organisation the rate-limit check comes after the page
            # fetch, so calling it anyway fetches and bills every remaining
            # host. Its SweepDiscovery row already exists (unverified) from
            # _ask, and classify_organisations fills it in later.
            if halted is None and state.spent() >= config.budget_usd:
                # Classification fetches pages and bills them, so it is spend
                # the budget answers for as much as a search is.
                halted = SweepRun.StopReason.BUDGET
            if halted is not None:
                continue
            outcome = classify(org)
            if outcome in _HALTING:
                halted = _HALTING[outcome]
            org.refresh_from_db()
            ok = verified_for(org, config.family)
            if ok:
                discovery.verified_in_pass = True
                discovery.save(update_fields=["verified_in_pass"])
                verified += 1
                # Decay asks "is this provider still adding NEW hosts", so
                # credit is scoped to `found` -- this batch's novel
                # discoveries only. A provider that re-returns in a LATER
                # batch a host this run already found gets appended to
                # `returned_by` (in `_ask`) but that discovery is not in
                # `found` again, so it earns no decay credit here -- it
                # found nothing new. The tally (`tally.found_by`) answers a
                # different question, "which engine can reach which hosts",
                # and reads every `returned_by` entry regardless of batch.
                for name in discovery.returned_by:
                    by_provider[name] = by_provider.get(name, 0) + 1
        results.append(BatchResult(
            number=number, spend_usd=state.spent() - spend_before, novel=len(found),
            verified=verified, verified_by_provider=by_provider,
        ))
        if halted:
            reason = halted
            break
        stop = stop_reason(
            results,
            value_per_award_usd=settings.SWEEP_VALUE_PER_AWARD_USD,
            awards_per_verified_host=settings.SWEEP_AWARDS_PER_VERIFIED_HOST,
        )
        if stop:
            reason = stop
            break
        for name in sorted(decayed(results, tuple(live))):
            logger.info("sweep %s: dropping decayed provider %s", state.run.id, name)
            state.run.dropped_providers.append(name)
            del live[name]

    run = state.run
    run.stop_reason = reason
    run.batches = len(results)
    run.search_usd = state.meter.total()
    run.fetch_usd = fetch_budget.usd()
    run.recaptured = len(state.recaptured)
    run.finished_at = timezone.now()
    run.save()
    return run
