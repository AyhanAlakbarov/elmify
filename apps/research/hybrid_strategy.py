"""3-Tier Sufficiency-Gated Hybrid Retrieval & Discovery Engine.

Balances shared-catalog PostgreSQL retrieval against live web discovery across
five measurable variables per `(country_code, field, MASTER)` cell:

1. Cell Coverage Depth (`program_count`, `served_award_count` in PostgreSQL).
2. Cycle Freshness & Seasonality (`due_verification_ids` on matched awards for
   `profile.intended_intake.year`).
3. Field Specificity (`is_ambiguous_or_interdisciplinary` and
   `exact_subfield_count` matching canonical degree titles / sub-fields).
4. Student Financial Need (`affordable_count` with `funding_gap == 0` or a
   winnable attached scholarship).
5. Prior Pass Marginal Yield (`past_economic_stop` from `PassStates` /
   `AreaSweep` cooldowns).
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from functools import reduce
from uuid import UUID

from django.db.models import Max
from django.utils import timezone

from apps.accounts.field_taxonomy import resolve_field_taxonomy
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.eligibility import _normalize_language
from apps.funding.fx import RateTable
from apps.funding.models import (
    CycleState,
    FundingCycleVerification,
    FundingOpportunity,
    FundingOpportunityProgram,
    Institution,
    PackCandidate,
    PackVersion,
    Program,
    ProgramEvidenceClaim,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.pool import _word_or_substring_q, candidate_pool
from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.research.destinations import anywhere
from apps.research.hosts import registrable_domain
from apps.research.national_databases import NationalDatabasesSource
from apps.research.providers import SearchRequest
from apps.research.seam_bindings import build_university_funding_queries
from apps.research.spine import POOL_LIMIT
from apps.research.tap_seams import PassStates, TapQueryInputs, bound_pass_states

_PROGRAMME_FAMILY = "UNIVERSITY_WIDE"
_VERIFIED_CYCLE_STATES = frozenset({CycleState.OPEN, CycleState.UPCOMING})


class DiscoveryTier(StrEnum):
    """Decision tier for a country cell or an overall student request."""

    TIER_1_DB_COMPLETE = "TIER_1_DB_COMPLETE"
    TIER_2_TARGETED_DELTA = "TIER_2_TARGETED_DELTA"
    TIER_3_COLD_CELL_SWEEP = "TIER_3_COLD_CELL_SWEEP"


@dataclass(frozen=True)
class CountryCellAssessment:
    """Measured catalog sufficiency for one `(country_code, field, MASTER)` cell."""

    country_code: str
    tier: DiscoveryTier
    program_count: int
    exact_subfield_count: int
    interest_match_count: int
    affordable_count: int
    served_award_count: int
    due_verification_ids: tuple[UUID, ...]
    past_economic_stop: bool
    unfunded_university_domains: tuple[str, ...]
    needs_exploration: bool = False
    cycle_refresh_only: bool = False


@dataclass(frozen=True)
class HybridRetrievalPlan:
    """Complete retrieval and discovery plan across all destination countries."""

    overall_tier: DiscoveryTier
    is_interdisciplinary: bool
    canonical_degree_titles: tuple[str, ...]
    assessments: tuple[CountryCellAssessment, ...]
    hot_countries: tuple[str, ...]
    delta_countries: tuple[str, ...]
    cold_countries: tuple[str, ...]
    active_search_destinations: tuple[str, ...]
    due_verification_ids: tuple[UUID, ...]
    missing_verification_opportunity_ids: tuple[UUID, ...]
    targeted_queries: tuple[SearchRequest, ...]
    portal_seed_urls: dict[str, tuple[str, ...]]
    cycle_refresh_only_countries: tuple[str, ...] = ()


@dataclass(frozen=True)
class HybridExecutionReport:
    """Outcome of running the 3-tier hybrid retrieval and discovery engine."""

    plan: HybridRetrievalPlan
    pack_version_id: UUID | None
    cycles_reverified: int
    countries_discovered: tuple[str, ...]
    queries_executed: int


def _exact_subfield_matches(
    programs: Sequence[Program],
    target_field: str,
    research_interests: Sequence[str],
) -> set[UUID]:
    resolution = resolve_field_taxonomy(target_field, research_interests)
    if not programs:
        return set()
    exact_q = _word_or_substring_q(target_field)
    for title in resolution.canonical_degree_titles:
        exact_q |= _word_or_substring_q(title)
    if resolution.parent_fields and resolution.preferred_track_keywords:
        parent_q = reduce(
            operator.or_, (_word_or_substring_q(p) for p in resolution.parent_fields)
        )
        track_q = reduce(
            operator.or_, (_word_or_substring_q(kw) for kw in resolution.preferred_track_keywords)
        )
        exact_q |= parent_q & track_q
    prog_ids = [p.id for p in programs]
    return set(
        Program.objects.filter(id__in=prog_ids).filter(exact_q).values_list("id", flat=True)
    )


def _interest_matches(
    programs: Sequence[Program],
    research_interests: Sequence[str],
) -> set[UUID]:
    cleaned = [i.strip() for i in research_interests if i and i.strip()]
    if not programs or not cleaned:
        return set()
    interest_q = reduce(operator.or_, (_word_or_substring_q(term) for term in cleaned))
    prog_ids = [p.id for p in programs]
    return set(
        Program.objects.filter(id__in=prog_ids).filter(interest_q).values_list("id", flat=True)
    )


def _teaching_language_matches(
    program: Program,
    acceptable_languages: Sequence[str],
) -> bool:
    if not acceptable_languages:
        return True
    accepted = {
        _normalize_language(lang)
        for lang in acceptable_languages
        if lang and lang.strip()
    }
    if not accepted:
        return True
    prog_langs = {
        _normalize_language(lang)
        for lang in (program.teaching_languages or [])
        if lang and lang.strip()
    }
    return bool(accepted & prog_langs)


def plan_hybrid_retrieval(
    profile: StudentProfileSnapshot,
    *,
    pack: PackVersion | None = None,
    passes: PassStates | None = None,
    now: datetime | None = None,
    min_programs_per_country: int = 5,
    min_warm_programs_per_country: int = 2,
    min_exact_subfield_programs: int = 2,
    min_interest_programs: int = 1,
    min_affordable_per_country: int = 2,
    deep_saturation_count: int = 15,
    exploration_cooldown_days: int = 30,
) -> HybridRetrievalPlan:
    """Evaluate the shared PostgreSQL catalog across all 5 governing variables
    and classify each destination country into Tier 1, Tier 2, or Tier 3."""
    current_time = now or timezone.now()
    pass_states = passes or bound_pass_states()
    resolution = resolve_field_taxonomy(profile.target_field, profile.research_interests)

    if profile.allowed_countries:
        destinations = tuple(
            c for c in profile.allowed_countries if c and c not in profile.excluded_countries
        )
        non_dest = tuple(sorted(set(ISO_3166_ALPHA2_CODES) - set(destinations)))
        scoped_profile = profile.model_copy(update={"excluded_countries": non_dest})
    else:
        destinations = anywhere(profile.excluded_countries)
        scoped_profile = profile

    pool_limit = max(POOL_LIMIT, len(destinations) * min_programs_per_country * 2)
    pool = candidate_pool(scoped_profile, limit=pool_limit)

    admissible_programs = tuple(
        p
        for p in pool.programs
        if _teaching_language_matches(p, profile.acceptable_teaching_languages)
    )

    exact_ids = _exact_subfield_matches(
        admissible_programs, profile.target_field, profile.research_interests
    )
    interest_ids = _interest_matches(admissible_programs, profile.research_interests)
    has_interests = any(i and i.strip() for i in profile.research_interests)

    programs_by_country: dict[str, list[Program]] = {c: [] for c in destinations}
    for prog in admissible_programs:
        if prog.country_code in programs_by_country:
            programs_by_country[prog.country_code].append(prog)

    # Check affordable and eligible packed programmes per country from `pack` when available.
    affordable_by_country: dict[str, int] = dict.fromkeys(destinations, 0)
    eligible_packed_by_country: dict[str, int] = dict.fromkeys(destinations, 0)
    admissible_by_id = {p.id: p for p in admissible_programs}
    if pack is not None:
        packed_cands = [
            pc.candidate
            for pc in PackCandidate.objects.filter(
                pack_version=pack,
                candidate__program_id__isnull=False,
            ).select_related("candidate")
        ]
        packed_cand_ids = {c.id for c in packed_cands}
        overflow_cands = [
            c
            for c in RecommendationCandidate.objects.filter(
                run_id=pack.run_id,
                program_id__isnull=False,
                eligible=True,
            )
            .exclude(id__in=packed_cand_ids)
            .exclude(state=RecommendationCandidate.State.REJECTED)
            if (c.calibration_features or {}).get("over_budget_reason")
            != "ELIGIBLE_BELOW_FIT_BAR"
        ]
        for cand in (*packed_cands, *overflow_cands):
            matched_prog = (
                admissible_by_id.get(cand.program_id) if cand.program_id is not None else None
            )
            cc = str(
                cand.country_code
                or (matched_prog.country_code if matched_prog is not None else "")
            )
            if cc not in affordable_by_country:
                continue
            if cand.eligible:
                eligible_packed_by_country[cc] += 1
            is_covered = (
                not cand.funding_gap_is_placeholder and cand.funding_gap <= 0
            ) or bool(cand.funding_condition)
            if is_covered:
                affordable_by_country[cc] += 1
    # Check attached funding per institution so Tier 2 can target universities
    # whose programmes are in the DB but whose funding pages have not been read.
    inst_ids = {p.institution_id for p in admissible_programs if p.institution_id is not None}
    inst_domains: dict[UUID, str] = {}
    if inst_ids:
        for inst_id, website in Institution.objects.filter(id__in=inst_ids).values_list(
            "id", "official_website"
        ):
            dom = registrable_domain(website)
            if dom:
                inst_domains[inst_id] = dom

    funded_inst_ids = (
        set(
            FundingOpportunity.objects.filter(
                institution_id__in=inst_ids,
                served=True,
                suspension_quote="",
            ).values_list("institution_id", flat=True)
        )
        | set(
            FundingOpportunity.objects.filter(
                program__institution_id__in=inst_ids,
                served=True,
                suspension_quote="",
            ).values_list("program__institution_id", flat=True)
        )
        | set(
            FundingOpportunityProgram.objects.filter(
                program__institution_id__in=inst_ids,
                opportunity__served=True,
                opportunity__suspension_quote="",
            ).values_list("program__institution_id", flat=True)
        )
    ) - {None}

    intake_year = profile.intended_intake.year
    shut_cycle_opp_ids = set(
        FundingCycleVerification.objects.filter(
            intake_start_year=intake_year,
            state__in=(CycleState.SUSPENDED, CycleState.ENDED),
        ).values_list("opportunity_id", flat=True)
    )

    prog_ids = [p.id for p in admissible_programs]
    funded_prog_ids = (
        set(
            FundingOpportunityProgram.objects.filter(
                program_id__in=prog_ids,
                opportunity__served=True,
                opportunity__suspension_quote="",
            )
            .exclude(opportunity_id__in=shut_cycle_opp_ids)
            .values_list("program_id", flat=True)
        )
        | set(
            FundingOpportunity.objects.filter(
                program_id__in=prog_ids,
                served=True,
                suspension_quote="",
            )
            .exclude(id__in=shut_cycle_opp_ids)
            .values_list("program_id", flat=True)
        )
    ) - {None}

    if pack is None:
        # When no pack is passed, treat low/zero self-funding gaps or attached
        # scholarships on matched programmes as the affordability signal.
        inst_only_funded_ids = set(
            FundingOpportunity.objects.filter(
                institution_id__in=inst_ids,
                scope_type="INSTITUTION",
                served=True,
                suspension_quote="",
            )
            .exclude(id__in=shut_cycle_opp_ids)
            .values_list("institution_id", flat=True)
        ) - {None}
        for prog in admissible_programs:
            if (
                prog.id in funded_prog_ids
                or (prog.institution_id is not None and prog.institution_id in inst_only_funded_ids)
            ) and prog.country_code in affordable_by_country:
                affordable_by_country[prog.country_code] += 1

    # Check cycle verifications for matched awards and attached opportunities.
    matched_opp_ids: set[UUID] = {a.id for a in pool.awards}
    opp_countries: dict[UUID, set[str]] = {}
    for a in pool.awards:
        a_cc = a.country_code or (
            a.organisation.country_code if a.organisation is not None else ""
        )
        if a_cc:
            opp_countries.setdefault(a.id, set()).add(a_cc)

    if admissible_programs:
        admissible_prog_ids = [p.id for p in admissible_programs]
        for opp_id, prog_cc in FundingOpportunityProgram.objects.filter(
            program_id__in=admissible_prog_ids,
            opportunity__served=True,
            opportunity__suspension_quote="",
        ).values_list("opportunity_id", "program__country_code"):
            matched_opp_ids.add(opp_id)
            if prog_cc:
                opp_countries.setdefault(opp_id, set()).add(prog_cc)
        for opp_id, prog_cc in FundingOpportunity.objects.filter(
            program_id__in=admissible_prog_ids,
            served=True,
            suspension_quote="",
        ).values_list("id", "program__country_code"):
            matched_opp_ids.add(opp_id)
            if prog_cc:
                opp_countries.setdefault(opp_id, set()).add(prog_cc)
        if inst_ids:
            for opp_id, inst_cc in FundingOpportunity.objects.filter(
                institution_id__in=inst_ids,
                scope_type="INSTITUTION",
                served=True,
                suspension_quote="",
            ).values_list("id", "institution__country_code"):
                matched_opp_ids.add(opp_id)
                if inst_cc:
                    opp_countries.setdefault(opp_id, set()).add(inst_cc)

    intake_year = profile.intended_intake.year
    verifications = list(
        FundingCycleVerification.objects.filter(
            opportunity_id__in=matched_opp_ids,
            intake_start_year=intake_year,
        )
    )
    fallback_opp_cc: dict[UUID, str] = {}
    if verifications:
        for opp_id, c_direct, c_prog, c_inst, c_org in FundingOpportunity.objects.filter(
            id__in={v.opportunity_id for v in verifications}
        ).values_list(
            "id",
            "country_code",
            "program__country_code",
            "institution__country_code",
            "organisation__country_code",
        ):
            fallback_opp_cc[opp_id] = str(c_direct or c_prog or c_inst or c_org or "")
    verified_opp_ids = {v.opportunity_id for v in verifications}
    missing_verification_opp_ids = tuple(sorted(matched_opp_ids - verified_opp_ids))

    due_verifications_by_country: dict[str, list[UUID]] = {c: [] for c in destinations}
    all_due_verification_ids: list[UUID] = []
    for v in verifications:
        is_due = (
            v.state not in _VERIFIED_CYCLE_STATES
            or v.next_check_at is None
            or v.next_check_at <= current_time
        )
        if not is_due:
            continue
        all_due_verification_ids.append(v.id)
        candidate_ccs = set(opp_countries.get(v.opportunity_id, set()))
        fallback_cc = fallback_opp_cc.get(v.opportunity_id, "")
        if fallback_cc:
            candidate_ccs.add(fallback_cc)
        for opp_cc in candidate_ccs:
            if opp_cc in due_verifications_by_country:
                due_verifications_by_country[opp_cc].append(v.id)

    awards_by_country: dict[str, int] = dict.fromkeys(destinations, 0)
    for ccs in opp_countries.values():
        for cc in ccs:
            if cc in awards_by_country:
                awards_by_country[cc] += 1

    # Check most recent evidence timestamp per country for time-decayed exploration
    # on cells with 5..14 programmes (`< deep_saturation_count`) and not past stop.
    latest_checked_by_country: dict[str, datetime] = {}
    if admissible_programs:
        for row in (
            ProgramEvidenceClaim.objects.filter(
                program_id__in=[p.id for p in admissible_programs]
            )
            .values("program__country_code")
            .annotate(latest=Max("evidence_claim__last_checked_at"))
        ):
            cc_key = row["program__country_code"]
            latest_dt = row["latest"]
            if cc_key and latest_dt is not None:
                latest_checked_by_country[cc_key] = latest_dt
    exploration_cutoff = current_time - timedelta(days=exploration_cooldown_days)

    assessments: list[CountryCellAssessment] = []
    hot: list[str] = []
    delta: list[str] = []
    cold: list[str] = []
    cycle_refresh_only_list: list[str] = []
    targeted_queries: list[SearchRequest] = []
    portal_seed_urls: dict[str, tuple[str, ...]] = {}

    def _unfunded_domains(progs: Sequence[Program]) -> tuple[str, ...]:
        domains: list[str] = []
        for p in progs:
            if p.institution_id and p.institution_id not in funded_inst_ids:
                dom = inst_domains.get(p.institution_id, "")
            elif p.institution_id is None and p.id not in funded_prog_ids:
                dom = registrable_domain(p.origin_domain or p.evidence_domain)
            else:
                dom = ""
            if dom and dom not in domains:
                domains.append(dom)
        return tuple(domains)

    for cc in destinations:
        progs = programs_by_country.get(cc, [])
        prog_count = len(progs)
        exact_count = sum(1 for p in progs if p.id in exact_ids)
        interest_count = sum(1 for p in progs if p.id in interest_ids)
        affordable_count = affordable_by_country.get(cc, 0)
        award_count = awards_by_country.get(cc, 0)
        due_ids = tuple(sorted(due_verifications_by_country.get(cc, [])))
        past_stop = pass_states.state(cc, _PROGRAMME_FAMILY).past_economic_stop
        unfunded_domains = _unfunded_domains(progs)

        effective_prog_count = (
            eligible_packed_by_country.get(cc, 0)
            if (pack is not None and not pack.empty_reason)
            else prog_count
        )
        depth_ok = effective_prog_count >= min_programs_per_country or (
            past_stop and effective_prog_count >= min_warm_programs_per_country
        )
        subfield_ok = (
            not resolution.is_ambiguous_or_interdisciplinary
            or exact_count >= min_exact_subfield_programs
            or (past_stop and exact_count >= 1)
        )
        interests_ok = not has_interests or interest_count >= min_interest_programs
        affordability_ok = (
            profile.funding_dependency == "OPTIONAL"
            or affordable_count >= min_affordable_per_country
            or (past_stop and affordable_count >= 1)
        )
        cycles_ok = len(due_ids) == 0
        latest_checked = latest_checked_by_country.get(cc)
        exploration_ok = (
            past_stop
            or effective_prog_count >= deep_saturation_count
            or latest_checked is None
            or latest_checked >= exploration_cutoff
        )
        static_gates_ok = (
            depth_ok and subfield_ok and interests_ok and affordability_ok and exploration_ok
        )
        needs_exploration = bool(depth_ok and not exploration_ok)
        is_cycle_refresh_only = bool(static_gates_ok and not cycles_ok)
        if is_cycle_refresh_only:
            cycle_refresh_only_list.append(cc)

        if static_gates_ok and cycles_ok:
            tier = DiscoveryTier.TIER_1_DB_COMPLETE
            hot.append(cc)
        elif prog_count >= min_warm_programs_per_country:
            tier = DiscoveryTier.TIER_2_TARGETED_DELTA
            delta.append(cc)
        else:
            tier = DiscoveryTier.TIER_3_COLD_CELL_SWEEP
            cold.append(cc)

        assessments.append(
            CountryCellAssessment(
                country_code=cc,
                tier=tier,
                program_count=prog_count,
                exact_subfield_count=exact_count,
                interest_match_count=interest_count,
                affordable_count=affordable_count,
                served_award_count=award_count,
                due_verification_ids=due_ids,
                past_economic_stop=past_stop,
                unfunded_university_domains=unfunded_domains,
                needs_exploration=needs_exploration,
                cycle_refresh_only=is_cycle_refresh_only,
            )
        )

        if tier in (DiscoveryTier.TIER_2_TARGETED_DELTA, DiscoveryTier.TIER_3_COLD_CELL_SWEEP):
            from apps.research.discovery import DiscoveryQuery

            db_leads = list(
                NationalDatabasesSource().find(
                    DiscoveryQuery(field=profile.target_field, country_code=cc)
                )
            )
            portal_seed_urls[cc] = tuple(lead.canonical_url for lead in db_leads)

        if tier == DiscoveryTier.TIER_2_TARGETED_DELTA:
            for dom in unfunded_domains[:5]:
                for q_str in build_university_funding_queries(
                    dom, field=profile.target_field, country_code=cc
                ):
                    targeted_queries.append(
                        SearchRequest(
                            query=q_str,
                            country_code=cc.lower(),
                            language="en",
                            max_results=10,
                        )
                    )

    if cold or not destinations:
        overall_tier = DiscoveryTier.TIER_3_COLD_CELL_SWEEP
    elif delta or all_due_verification_ids:
        overall_tier = DiscoveryTier.TIER_2_TARGETED_DELTA
    else:
        overall_tier = DiscoveryTier.TIER_1_DB_COMPLETE

    return HybridRetrievalPlan(
        overall_tier=overall_tier,
        is_interdisciplinary=resolution.is_ambiguous_or_interdisciplinary,
        canonical_degree_titles=resolution.canonical_degree_titles[:4],
        assessments=tuple(assessments),
        hot_countries=tuple(hot),
        delta_countries=tuple(delta),
        cold_countries=tuple(cold),
        active_search_destinations=tuple((*cold, *delta)),
        due_verification_ids=tuple(sorted(set(all_due_verification_ids))),
        missing_verification_opportunity_ids=missing_verification_opp_ids,
        targeted_queries=tuple(targeted_queries),
        portal_seed_urls=portal_seed_urls,
        cycle_refresh_only_countries=tuple(cycle_refresh_only_list),
    )


def apply_hybrid_plan_to_tap_inputs(
    inputs: TapQueryInputs,
    plan: HybridRetrievalPlan,
) -> TapQueryInputs:
    """Narrow `TapQueryInputs` using `HybridRetrievalPlan`:

    - Prunes `hot_countries` (Tier 1) from `inputs.destinations` when at least
      one destination is already DB-complete.
    - When all remaining active destinations are Tier 2 (`delta_countries`) and
      the field is interdisciplinary, promotes `canonical_degree_titles` into
      `interest_words` so Stage 1 targets the missing specialization.
    """
    hot_set = frozenset(plan.hot_countries)
    if hot_set and inputs.destinations:
        remaining_dests = tuple(d for d in inputs.destinations if d not in hot_set)
    else:
        remaining_dests = inputs.destinations

    updated = replace(inputs, destinations=remaining_dests)
    if (
        plan.is_interdisciplinary
        and plan.canonical_degree_titles
        and not plan.cold_countries
        and plan.delta_countries
    ):
        merged_interests = tuple(
            dict.fromkeys(
                (
                    *(t.casefold() for t in plan.canonical_degree_titles if t.strip()),
                    *updated.interest_words,
                )
            )
        )
        updated = replace(updated, interest_words=merged_interests[:6])
    return updated


def execute_hybrid_discovery(
    profile: StudentProfileSnapshot,
    *,
    tenant_id: UUID,
    run: RecommendationRun | None = None,
    rates: RateTable | None = None,
    passes: PassStates | None = None,
    verify_due_fn: Callable[[Sequence[UUID]], int] | None = None,
    discover_country_fn: Callable[[str, DiscoveryTier, HybridRetrievalPlan], int] | None = None,
) -> HybridExecutionReport:
    """Run the 3-tier sufficiency-gated retrieval and discovery flow:

    1. Build or rebuild the student's pack from the shared PostgreSQL catalog.
    2. Compute `HybridRetrievalPlan` across the 5 governing variables.
    3. If matched awards have due `FundingCycleVerification` rows, re-verify
       only those rows via `verify_due_fn`.
    4. If `overall_tier == TIER_1_DB_COMPLETE`, return immediately from the
       database (`0` search queries).
    5. Otherwise run `discover_country_fn` only on `active_search_destinations`
       (`delta_countries` at Tier 2, `cold_countries` at Tier 3) and rebuild the
       pack when new rows are written.
    """
    from apps.research.services import rebuild_pack

    pack: PackVersion | None = None
    if run is not None:
        pack = rebuild_pack(run, rates=rates)

    plan = plan_hybrid_retrieval(profile, pack=pack, passes=passes)
    cycles_reverified = 0
    if plan.due_verification_ids and verify_due_fn is not None:
        original_due_ids = plan.due_verification_ids
        cycles_reverified = verify_due_fn(original_due_ids)
        if cycles_reverified > 0:
            if run is not None:
                pack = rebuild_pack(run, rates=rates)
            refreshed = plan_hybrid_retrieval(profile, pack=pack, passes=passes)
            plan = replace(refreshed, due_verification_ids=original_due_ids)

    if plan.overall_tier == DiscoveryTier.TIER_1_DB_COMPLETE:
        return HybridExecutionReport(
            plan=plan,
            pack_version_id=pack.id if pack is not None else None,
            cycles_reverified=cycles_reverified,
            countries_discovered=(),
            queries_executed=0,
        )

    discovered_countries: list[str] = []
    queries_executed = 0
    tier_by_country = {a.country_code: a.tier for a in plan.assessments}
    if discover_country_fn is not None:
        for cc in plan.active_search_destinations:
            cc_tier = tier_by_country.get(cc, DiscoveryTier.TIER_3_COLD_CELL_SWEEP)
            queries_executed += discover_country_fn(cc, cc_tier, plan)
            discovered_countries.append(cc)

    if (cycles_reverified > 0 or discovered_countries) and run is not None:
        pack = rebuild_pack(run, rates=rates)

    return HybridExecutionReport(
        plan=plan,
        pack_version_id=pack.id if pack is not None else None,
        cycles_reverified=cycles_reverified,
        countries_discovered=tuple(discovered_countries),
        queries_executed=queries_executed,
    )
