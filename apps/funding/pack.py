from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.affordability import AffordabilityResult, calculate_affordability
from apps.funding.conditions import (
    closed_route_reasons,
    return_service_disclosures,
    unevaluable_condition_reasons,
)
from apps.funding.evaluation import (
    AwardCandidateFacts,
    CandidateFacts,
    EvaluationScores,
    _has_profile_flag,
    _programme_money_closes_the_gap,
    _strip_undecidable_secondary_routes,
    _wants_top_universities_only,
    evaluate,
    evaluate_award,
    has_post_admission_gov_scholarship,
    needs_selective_funding,
    post_admission_gov_scheme_for_candidate,
    schemes_paying_for,
)
from apps.funding.fx import BANK_MARGIN, RateTable, UnconvertibleCurrency, convert
from apps.funding.probability import (
    POST_ADMISSION_GOV_CORRELATION,
    is_post_admission_gov_scholarship,
    is_selective_candidate,
    joint_admission_and_funding_chance_pct,
    post_admission_gov_conditional_pct,
)

if TYPE_CHECKING:
    from apps.funding.card import AwardCard

PackOrdering = Literal["SCHOLARSHIP_FIRST", "PARALLEL_OR_UNIVERSITY_FIRST"]
RiskTier = Literal["SAFETY", "TARGET", "REACH"]


def risk_tier_for(effective_chance_pct: int | None) -> RiskTier | None:
    if effective_chance_pct is None:
        return None
    if effective_chance_pct >= 50:
        return "SAFETY"
    if effective_chance_pct >= 20:
        return "TARGET"
    return "REACH"


@dataclass(frozen=True)
class RankedCandidate:
    program_id: str
    scores: EvaluationScores | None
    affordability: AffordabilityResult
    tradeoffs: tuple[str, ...]


@dataclass(frozen=True)
class PackedApplication:
    program_id: str
    #: Payable as-is, in ``application_fee_currency`` — not the comparison currency.
    application_fee: Decimal
    application_fee_currency: str
    #: What this programme still costs the student after every funding route
    #: they can actually use, in `gap_currency`. Carried here because the
    #: evaluator has already computed it -- reading it back meant ranking twice.
    gap: Decimal
    gap_currency: str
    ordering: PackOrdering
    ordering_reason: str
    #: Place in rank_candidates order, 1 = best. The pool's order for "New for
    #: you" and the stretch rule "ranks above the last paid item" (spec §7.7).
    rank: int | None = None
    #: False when the programme states no application fee. Its fee then arrives
    #: as 0.00 from affordability, which is "not known", never "no fee" (§7.4).
    fee_known: bool = True
    #: False when the catalogue holds no cost row besides the application fee:
    #: the gap is then unknown, shown "not yet costed", never a 0.00.
    costed: bool = True
    #: What the student said they can pay themselves, over the programme, in
    #: `gap_currency` (affordability.self_funded); never more than `gap`.
    self_funded: Decimal = Decimal("0.00")
    #: Affordable for a mandatory-funding student only by winning selective
    #: funding (owner, 2026-10-24): shown as conditional, ordered scholarship-first.
    needs_selective_funding: bool = False
    #: The scholarships that would pay for it in full if won, by name. Empty
    #: when it is the programme's own selective funding that would.
    winnable_with: tuple[str, ...] = ()
    #: Estimated admission chance percentage (1..95), when computed by the spine.
    estimated_chance_pct: int | None = None
    #: Estimated joint admission and selective-scholarship funding chance percentage
    #: (1..95), when one or more selective scholarships apply to this programme.
    estimated_funded_chance_pct: int | None = None
    #: Portfolio risk tier derived from effective admission/funded probability.
    risk_tier: RiskTier | None = None
    #: Risk and tradeoff disclosures surfaced on the candidate card.
    tradeoffs: tuple[str, ...] = ()
    #: Why the candidate sits in `over_budget` ("Other options"), when it does.
    over_budget_reason: str = ""


@dataclass(frozen=True)
class ExcludedCandidate:
    program_id: str
    reason_code: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PackedAward:
    """A scholarship the student applies for, as its own application.

    **An award is an application, not a discount** (owner decision 2026-09-19).
    Its money is deliberately NOT subtracted from any programme's cost: counting
    money not yet won understates the gap by exactly the amount at risk, which
    is the amount that decides whether the student can go at all.
    """

    award_id: str
    name: str
    holder_name: str
    deadline: date | None
    ordering: PackOrdering
    ordering_reason: str
    #: Details the readings split on, shown beside the award (spec 8.6). Never
    #: filtered on, and never silently dropped: a served award whose caveat was
    #: lost presents a model's coin-flip as a fact.
    unconfirmed: tuple[str, ...]
    card: AwardCard | None = None
    #: Estimated scholarship win chance percentage (1..100), when computed by the spine.
    estimated_chance_pct: int | None = None


@dataclass(frozen=True)
class Pack:
    fee_free: tuple[PackedApplication, ...]
    paid: tuple[PackedApplication, ...]
    #: Award applications. A second list rather than more entries in the first
    #: two, because those are partitioned by an application FEE and an award
    #: does not charge one -- folding awards in would make "fee_free" mean two
    #: different things.
    awards: tuple[PackedAward, ...]
    excluded: tuple[ExcludedCandidate, ...]
    #: Why the pool was empty, when it was. P1-7: a short pack always says so.
    #: Set by the spine's own empty-pack path -- `build_pack` never runs on an
    #: empty pool, so it has nothing to say here.
    empty_reason: str = ""
    #: Ranked and eligible, refused by the application budget or the cap on
    #: unknown fees. Kept so the worker writes them into the pool (never the
    #: pack): a raised budget or a stretch offers them as "New for you" (spec
    #: §7.8, §7.9). Each also stays in `excluded` (APPLICATION_BUDGET_EXCEEDED or
    #: FEE_NOT_KNOWN_LIMIT), so coverage reads it unchanged.
    over_budget: tuple[PackedApplication, ...] = ()
    #: Programmes stating no application fee: never "free", never charged an
    #: invented fee, at most MAX_FEE_NOT_KNOWN of them (owner, 2026-10-24).
    fee_not_known: tuple[PackedApplication, ...] = ()


#: The most programmes with no stated application fee one pack holds (owner,
#: 2026-10-24). They cost the budget nothing we could name, so the cap is what
#: keeps a pack from filling up with them.
MAX_FEE_NOT_KNOWN = 3
#: Maximum active programmes in the primary pack before overflow moves into
#: "Other options" (`over_budget`), keeping the shortlist focused.
MAX_ACTIVE_PROGRAMS = 10
#: Maximum active programmes from a single institution when multiple
#: institutions exist in the pool.
MAX_PER_INSTITUTION = 2


def _effective_chance_for(
    profile: StudentProfileSnapshot,
    program_id: str,
    affordability: AffordabilityResult,
    *,
    probabilities: Mapping[str, int] | None,
    funded_probabilities: Mapping[str, int | None] | None,
    conditional: bool = False,
) -> int | None:
    if funded_probabilities is not None:
        funded = funded_probabilities.get(program_id)
        if funded is not None and (
            conditional
            or profile.funding_dependency == "MANDATORY"
            or affordability.shortfall > 0
        ):
            return funded
    if probabilities is not None:
        return probabilities.get(program_id)
    return None


def _ignores_funding_options(profile: StudentProfileSnapshot) -> bool:
    return (
        profile.funding_dependency == "OPTIONAL" and profile.self_funding_capacity is None
    ) or (
        profile.funding_dependency in {"OPTIONAL", "IMPORTANT"}
        and _has_profile_flag(profile, "NO_FUNDING_NEEDED")
    )


def _avoids_return_bond(profile: StudentProfileSnapshot) -> bool:
    return profile.career_intent == "WORK_ABROAD" or _has_profile_flag(
        profile, "NO_RETURN_BOND"
    )


def rank_candidates(
    profile: StudentProfileSnapshot,
    candidates: Sequence[CandidateFacts],
    rates: RateTable,
    *,
    schemes: Mapping[str, tuple[str, ...]] | None = None,
    probabilities: Mapping[str, int] | None = None,
    funded_probabilities: Mapping[str, int | None] | None = None,
    coursework_warnings: Mapping[str, tuple[str, ...]] | None = None,
    today: date | None = None,
) -> tuple[RankedCandidate, ...]:
    """`schemes`: per programme id, the scholarships that would pay for it in
    full (`evaluation.schemes_paying_for`); none when omitted."""
    schemes = schemes or {}
    evaluated: list[
        tuple[CandidateFacts, CandidateFacts, EvaluationScores, AffordabilityResult]
    ] = []
    for candidate in candidates:
        try:
            cand_schemes = schemes.get(candidate.program_id, ())
            gov_scheme = post_admission_gov_scheme_for_candidate(profile, candidate)
            if gov_scheme is not None and gov_scheme not in cand_schemes:
                cand_schemes = (*cand_schemes, gov_scheme)
            outcome = evaluate(
                profile,
                candidate,
                rates,
                schemes=cand_schemes,
                today=today,
            )
            if outcome.outcome != "ELIGIBLE":
                continue
            effective_cand = _strip_undecidable_secondary_routes(
                profile, candidate, rates, schemes=cand_schemes, today=today
            )
            affordability = calculate_affordability(
                profile, effective_cand, rates, today=today
            )
        except UnconvertibleCurrency:
            # One programme in a currency the table lacks never stops the pack;
            # build_pack lists it as NO_EXCHANGE_RATE.
            continue
        assert outcome.scores is not None
        evaluated.append((candidate, effective_cand, outcome.scores, affordability))

    if not evaluated:
        return ()

    # "weaker fit" disclosure compares soft-fit only, excluding AFFORDABILITY: a
    # funding-first pick can legitimately have the higher blended overall score
    # purely because it is more affordable, which is the tradeoff being disclosed,
    # not evidence that its underlying program fit is actually stronger.
    def soft_fit(scores: EvaluationScores) -> Decimal:
        fit_scores = [d.score for d in scores.dimensions if d.dimension != "AFFORDABILITY"]
        if not fit_scores:
            return Decimal("0")
        return sum(fit_scores, Decimal("0")) / Decimal(len(fit_scores))

    best_soft_fit = max(soft_fit(scores) for _, _, scores, _ in evaluated)

    def effective_shortfall(
        candidate: CandidateFacts, affordability: AffordabilityResult
    ) -> Decimal:
        if schemes.get(candidate.program_id) or post_admission_gov_scheme_for_candidate(
            profile, candidate
        ):
            return Decimal("0.00")
        return max(
            Decimal("0.00"),
            affordability.shortfall - affordability.conditional_savings,
        )

    top_only = _wants_top_universities_only(profile)
    post_admit_gov = has_post_admission_gov_scholarship(profile)
    avoids_bond = _avoids_return_bond(profile)

    def effective_score(
        candidate: CandidateFacts,
        effective_cand: CandidateFacts,
        scores: EvaluationScores,
        affordability: AffordabilityResult,
    ) -> Decimal:
        score = (
            soft_fit(scores)
            if (
                (top_only or post_admit_gov)
                and effective_shortfall(candidate, affordability) == Decimal("0.00")
            )
            else scores.overall
        )
        eff_chance = _effective_chance_for(
            profile,
            candidate.program_id,
            affordability,
            probabilities=probabilities,
            funded_probabilities=funded_probabilities,
            conditional=needs_selective_funding(profile, effective_cand, today=today),
        )
        if eff_chance is not None:
            if top_only:
                score += (Decimal("50") - Decimal(eff_chance)) * Decimal("0.15")
            else:
                score += (Decimal(eff_chance) - Decimal("50")) * Decimal("0.15")
        elif top_only and is_selective_candidate(candidate):
            score += Decimal("4.5")
        if avoids_bond and return_service_disclosures(
            profile, effective_cand, today=today
        ):
            score -= Decimal("5")
        warnings_for_prog = (coursework_warnings or {}).get(candidate.program_id, ())
        if warnings_for_prog:
            is_mild_only = all(
                "conditional bridge" in w.lower() or "portfolio required:" in w.lower()
                for w in warnings_for_prog
            )
            score -= Decimal("1") if is_mild_only else Decimal("3")
        return score

    if profile.strategy == "FUNDING_FIRST":
        # What is left after winnable funding, then guaranteed shortfall (unless top_only,
        # which puts selective flagship + scholarship routes ahead of low-tier waivers),
        # then risk-adjusted fit.
        if top_only:
            ordered = sorted(
                evaluated,
                key=lambda item: (
                    effective_shortfall(item[0], item[3]),
                    -effective_score(item[0], item[1], item[2], item[3]),
                    item[3].shortfall,
                ),
            )
        else:
            ordered = sorted(
                evaluated,
                key=lambda item: (
                    effective_shortfall(item[0], item[3]),
                    item[3].shortfall,
                    -effective_score(item[0], item[1], item[2], item[3]),
                ),
            )
    else:
        ordered = sorted(
            evaluated,
            key=lambda item: -effective_score(item[0], item[1], item[2], item[3]),
        )

    ranked = []
    for candidate, effective_cand, scores, affordability in ordered:
        # "tradeoffs" is now everything the student must be told before accepting this
        # candidate, not only the fit comparison: a shut scheme, an unverified secondary
        # scheme, a coursework prerequisite warning, and a bond all belong.
        bonds = return_service_disclosures(profile, effective_cand, today=today)
        bond_conflict = (
            (
                "conflicts with your preference to work abroad after graduation "
                "(return-service bond applies)",
            )
            if (avoids_bond and bonds)
            else ()
        )
        tradeoffs = tuple(
            dict.fromkeys(
                (
                    *closed_route_reasons(profile, candidate, today=today),
                    *unevaluable_condition_reasons(profile, candidate, today=today),
                    *bonds,
                    *bond_conflict,
                    *((coursework_warnings or {}).get(candidate.program_id, ())),
                )
            )
        )
        if soft_fit(scores) < best_soft_fit:
            tradeoffs = tuple(
                dict.fromkeys(("weaker fit than another recommended candidate", *tradeoffs))
            )
        ranked.append(
            RankedCandidate(
                program_id=candidate.program_id,
                scores=scores,
                affordability=affordability,
                tradeoffs=tradeoffs,
            )
        )
    return tuple(ranked)


def _ordering_for(candidate: CandidateFacts) -> tuple[PackOrdering, str]:
    deadline = candidate.application_deadline
    scholarship_deadline = candidate.scholarship_decision_deadline
    if (
        scholarship_deadline is not None
        and deadline is not None
        and scholarship_deadline <= deadline
    ):
        return (
            "SCHOLARSHIP_FIRST",
            "the scholarship decision is due before the university fee deadline, so paying "
            "the fee is deferred until the scholarship decision arrives",
        )
    return (
        "PARALLEL_OR_UNIVERSITY_FIRST",
        "official timelines do not prove the scholarship decision arrives safely before the "
        "university fee deadline",
    )


def _award_ordering(
    award: AwardCandidateFacts,
    earliest_fee_deadline: date | None,
    *,
    home_country: str = "",
) -> tuple[PackOrdering, str]:
    """Same question `_ordering_for` asks of a programme, from the award's side.

    `_ordering_for` is untouched: it reads a CandidateFacts and an award is not
    one. The rule is the same and so is the wording -- if the scholarship
    decides first, paying a fee can wait for it.
    """
    if is_post_admission_gov_scholarship(
        award.name,
        country_code=award.country_code,
        home_country=home_country,
        applicant_conditions=award.applicant_conditions,
    ):
        return (
            "PARALLEL_OR_UNIVERSITY_FIRST",
            "apply to the university first to secure your admission offer, which is "
            "required to apply for this government scholarship",
        )
    deadline = award.evidence.deadline
    if (
        deadline is not None
        and earliest_fee_deadline is not None
        and deadline <= earliest_fee_deadline
    ):
        return (
            "SCHOLARSHIP_FIRST",
            "the scholarship decision is due before the university fee deadline, so paying "
            "the fee is deferred until the scholarship decision arrives",
        )
    return (
        "PARALLEL_OR_UNIVERSITY_FIRST",
        "official timelines do not prove the scholarship decision arrives safely before the "
        "university fee deadline",
    )


def _should_reserve_budget_for_anchor(
    later_ranked: Sequence[RankedCandidate],
    *,
    by_id: Mapping[str, CandidateFacts],
    profile: StudentProfileSnapshot,
    rates: RateTable,
    schemes: Mapping[str, tuple[str, ...]],
    probabilities: Mapping[str, int] | None,
    funded_probabilities: Mapping[str, int | None] | None,
    budget_remaining: Decimal,
    remaining_after: Decimal,
    active_count: int,
    fee_not_known_count: int,
    packed_per_institution: Mapping[str, int],
    enforce_institution_cap: bool,
    today: date,
) -> bool:
    """Return True if spending a REACH programme's application fee now would leave too little
    budget for a subsequent TARGET/SAFETY anchor programme."""
    sim_active = active_count
    sim_fnk = fee_not_known_count
    sim_inst = dict(packed_per_institution)
    for later_item in later_ranked:
        if sim_active >= MAX_ACTIVE_PROGRAMS:
            break
        later_cand = by_id[later_item.program_id]
        if (
            enforce_institution_cap
            and later_cand.institution_id
            and sim_inst.get(later_cand.institution_id, 0) >= MAX_PER_INSTITUTION
        ):
            continue
        later_eff_cand = _strip_undecidable_secondary_routes(
            profile,
            later_cand,
            rates,
            schemes=schemes.get(later_cand.program_id, ()),
            today=today,
        )
        later_cond = needs_selective_funding(profile, later_eff_cand, today=today)
        later_eff = _effective_chance_for(
            profile,
            later_item.program_id,
            later_item.affordability,
            probabilities=probabilities,
            funded_probabilities=funded_probabilities,
            conditional=later_cond,
        )
        later_tier = risk_tier_for(later_eff)
        later_fee_known = any(
            c.kind == "APPLICATION_FEE" for c in later_cand.cost_components
        )
        if not later_fee_known:
            if sim_fnk >= MAX_FEE_NOT_KNOWN:
                continue
            if later_tier in ("SAFETY", "TARGET"):
                return False
            sim_fnk += 1
            sim_active += 1
            if later_cand.institution_id:
                sim_inst[later_cand.institution_id] = (
                    sim_inst.get(later_cand.institution_id, 0) + 1
                )
            continue
        if later_item.affordability.application_fee == 0:
            if later_tier in ("SAFETY", "TARGET"):
                return False
            sim_active += 1
            if later_cand.institution_id:
                sim_inst[later_cand.institution_id] = (
                    sim_inst.get(later_cand.institution_id, 0) + 1
                )
            continue
        if later_tier not in ("SAFETY", "TARGET"):
            continue
        later_fee_base = convert(
            later_item.affordability.application_fee,
            later_item.affordability.application_fee_currency,
            rates.base,
            rates,
        )
        if later_fee_base * BANK_MARGIN <= remaining_after:
            return False
        if (
            later_fee_base * BANK_MARGIN <= budget_remaining
            and later_fee_base * BANK_MARGIN > remaining_after
        ):
            return True
    return False


def build_pack(
    profile: StudentProfileSnapshot,
    candidates: Sequence[CandidateFacts],
    rates: RateTable,
    *,
    awards: Sequence[AwardCandidateFacts] = (),
    attached_schemes: Mapping[str, tuple[str, ...]] | None = None,
    attached_selective_names: Mapping[str, tuple[str, ...]] | None = None,
    probabilities: Mapping[str, int] | None = None,
    funded_probabilities: Mapping[str, int | None] | None = None,
    coursework_warnings: Mapping[str, tuple[str, ...]] | None = None,
    award_probabilities: Mapping[str, int] | None = None,
    today: date | None = None,
) -> Pack:
    by_id = {candidate.program_id: candidate for candidate in candidates}
    today = today or date.today()
    awards_by_name = {aw.name: aw for aw in awards}

    def _is_post_admit_scheme(name: str) -> bool:
        aw = awards_by_name.get(name)
        if aw is not None:
            return is_post_admission_gov_scholarship(
                aw.name,
                country_code=aw.country_code,
                home_country=profile.nationality,
                applicant_conditions=aw.applicant_conditions,
            )
        return is_post_admission_gov_scholarship(name, home_country=profile.nationality)

    # Only a mandatory-funding student's gate (or post-admission gov scholarship route)
    # reads them, so only then are they worked out.
    schemes: dict[str, tuple[str, ...]] = {}
    if (
        profile.funding_dependency == "MANDATORY"
        or has_post_admission_gov_scholarship(profile)
        or any(_is_post_admit_scheme(aw.name) for aw in awards)
    ):
        for candidate in candidates:
            combined = list((attached_schemes or {}).get(candidate.program_id, ()))
            for name in schemes_paying_for(profile, candidate, awards, today=today):
                if name not in combined:
                    combined.append(name)
            schemes[candidate.program_id] = tuple(combined)
    if probabilities is not None and any(
        _is_post_admit_scheme(name)
        for names in schemes.values()
        for name in names
    ):
        resolved_funded: dict[str, int | None] = (
            dict(funded_probabilities) if funded_probabilities is not None else {}
        )
        for candidate in candidates:
            pid = candidate.program_id
            if resolved_funded.get(pid) is not None:
                continue
            admit_pct = probabilities.get(pid)
            if admit_pct is None:
                continue
            if any(
                _is_post_admit_scheme(name)
                for name in schemes.get(pid, ())
            ):
                cond_pct = post_admission_gov_conditional_pct(
                    admit_chance_pct=admit_pct, candidate=candidate
                )
                resolved_funded[pid] = joint_admission_and_funding_chance_pct(
                    admit_pct,
                    [cond_pct],
                    correlation=POST_ADMISSION_GOV_CORRELATION,
                )
        funded_probabilities = resolved_funded
    ranked = rank_candidates(
        profile,
        candidates,
        rates,
        schemes=schemes,
        probabilities=probabilities,
        funded_probabilities=funded_probabilities,
        coursework_warnings=coursework_warnings,
        today=today,
    )
    ranked_ids = {item.program_id for item in ranked}

    excluded: list[ExcludedCandidate] = []
    below_fit_candidates: list[tuple[CandidateFacts, tuple[str, ...]]] = []
    for candidate in candidates:
        if candidate.program_id in ranked_ids:
            continue
        try:
            outcome = evaluate(
                profile,
                candidate,
                rates,
                schemes=schemes.get(candidate.program_id, ()),
                today=today,
            )
        except UnconvertibleCurrency as error:
            excluded.append(
                ExcludedCandidate(
                    program_id=candidate.program_id,
                    reason_code="NO_EXCHANGE_RATE",
                    reasons=(str(error),),
                )
            )
            continue
        excluded.append(
            ExcludedCandidate(
                program_id=candidate.program_id,
                reason_code=outcome.outcome,
                reasons=outcome.reasons,
            )
        )
        if outcome.outcome == "ELIGIBLE_BELOW_FIT_BAR":
            below_fit_candidates.append((candidate, outcome.reasons))

    fee_free: list[PackedApplication] = []
    paid: list[PackedApplication] = []
    over_budget: list[PackedApplication] = []
    fee_not_known: list[PackedApplication] = []
    budget_remaining = convert(
        profile.application_budget.amount,
        profile.application_budget.currency,
        rates.base,
        rates,
    )
    distinct_institutions = {
        c.institution_id for c in candidates if c.institution_id
    }
    enforce_institution_cap = len(distinct_institutions) > 1
    packed_per_institution: dict[str, int] = {}

    def _active_count() -> int:
        return len(fee_free) + len(paid) + len(fee_not_known)

    def _has_anchor_in_active() -> bool:
        return any(
            app.risk_tier in ("SAFETY", "TARGET")
            for app in (*fee_free, *paid, *fee_not_known)
        )

    top_only = _wants_top_universities_only(profile)
    avoids_bond = _avoids_return_bond(profile)

    def _make_packed_application(
        candidate: CandidateFacts,
        effective_cand: CandidateFacts,
        aff: AffordabilityResult,
        *,
        rank: int,
        tradeoffs: tuple[str, ...],
        over_budget_reason: str = "",
    ) -> PackedApplication:
        conditional = needs_selective_funding(profile, effective_cand, today=today)
        winnable_names: tuple[str, ...] = ()
        if conditional or has_post_admission_gov_scholarship(profile):
            merged = list(schemes.get(candidate.program_id, ()))
            if (
                conditional
                and attached_selective_names
                and _programme_money_closes_the_gap(profile, effective_cand, rates, today=today)
            ):
                for name in attached_selective_names.get(candidate.program_id, ()):
                    if name not in merged:
                        merged.append(name)
            winnable_names = tuple(merged)
        is_post_admit_gov = any(_is_post_admit_scheme(name) for name in winnable_names)
        ordering: PackOrdering
        if is_post_admit_gov and (conditional or aff.shortfall > 0):
            ordering, reason = (
                "PARALLEL_OR_UNIVERSITY_FIRST",
                "apply to the university first to secure your admission offer, which is "
                "required to apply for the government scholarship",
            )
        elif conditional:
            ordering, reason = (
                "SCHOLARSHIP_FIRST",
                "this programme is affordable only if the scholarship is won, so apply for "
                "the scholarship before paying this programme's fees",
            )
        else:
            ordering, reason = _ordering_for(candidate)
        est_chance = (
            probabilities.get(candidate.program_id) if probabilities is not None else None
        )
        est_funded = (
            funded_probabilities.get(candidate.program_id)
            if funded_probabilities is not None
            else None
        )
        eff_chance = _effective_chance_for(
            profile,
            candidate.program_id,
            aff,
            probabilities=probabilities,
            funded_probabilities=funded_probabilities,
            conditional=conditional,
        )
        return PackedApplication(
            candidate.program_id,
            aff.application_fee,
            aff.application_fee_currency,
            aff.gap,
            aff.currency,
            ordering,
            reason,
            rank=rank,
            fee_known=any(c.kind == "APPLICATION_FEE" for c in candidate.cost_components),
            costed=any(c.kind != "APPLICATION_FEE" for c in candidate.cost_components),
            self_funded=aff.self_funded,
            needs_selective_funding=conditional,
            winnable_with=winnable_names,
            estimated_chance_pct=est_chance,
            estimated_funded_chance_pct=est_funded,
            risk_tier=risk_tier_for(eff_chance),
            tradeoffs=tradeoffs,
            over_budget_reason=over_budget_reason,
        )

    for idx, item in enumerate(ranked):
        position = idx + 1
        candidate = by_id[item.program_id]
        effective_cand = _strip_undecidable_secondary_routes(
            profile,
            candidate,
            rates,
            schemes=schemes.get(candidate.program_id, ()),
            today=today,
        )
        fee = item.affordability.application_fee
        currency = item.affordability.application_fee_currency
        # The fee is quoted in the destination's currency and the budget in the student's,
        # so budgeting compares them in the base currency while the packed figure stays
        # the amount actually payable.
        fee_in_base = convert(fee, currency, rates.base, rates)
        packed = _make_packed_application(
            candidate,
            effective_cand,
            item.affordability,
            rank=position,
            tradeoffs=item.tradeoffs,
        )
        tier = packed.risk_tier
        inst_id = candidate.institution_id
        def _record_overflow(
            app: PackedApplication,
            *,
            over_budget_reason: str,
            excluded_code: str,
            excluded_reason: str,
            tradeoff_note: str | None = None,
        ) -> None:
            updated_tradeoffs = (
                (*app.tradeoffs, tradeoff_note) if tradeoff_note is not None else app.tradeoffs
            )
            over_budget.append(
                replace(
                    app,
                    tradeoffs=updated_tradeoffs,
                    over_budget_reason=over_budget_reason,
                )
            )
            excluded.append(
                ExcludedCandidate(
                    program_id=app.program_id,
                    reason_code=excluded_code,
                    reasons=(excluded_reason,),
                )
            )

        if _active_count() >= MAX_ACTIVE_PROGRAMS:
            note = (
                f"the pack already holds {MAX_ACTIVE_PROGRAMS} active programmes; "
                "kept in Other options"
            )
            _record_overflow(
                packed,
                over_budget_reason="PACK_DIVERSITY_LIMIT",
                excluded_code="PACK_DIVERSITY_LIMIT",
                excluded_reason=note,
                tradeoff_note=note,
            )
            continue
        if (
            enforce_institution_cap
            and inst_id
            and packed_per_institution.get(inst_id, 0) >= MAX_PER_INSTITUTION
        ):
            _record_overflow(
                packed,
                over_budget_reason="PACK_DIVERSITY_LIMIT",
                excluded_code="PACK_DIVERSITY_LIMIT",
                excluded_reason=(
                    f"the pack already holds {MAX_PER_INSTITUTION} programmes at this "
                    "institution; kept in Other options for portfolio diversity"
                ),
                tradeoff_note=(
                    f"the pack already holds {MAX_PER_INSTITUTION} programmes at the "
                    "same institution; kept in Other options for portfolio diversity"
                ),
            )
            continue

        if not packed.fee_known:
            if len(fee_not_known) < MAX_FEE_NOT_KNOWN:
                fee_not_known.append(packed)
                if inst_id:
                    packed_per_institution[inst_id] = packed_per_institution.get(inst_id, 0) + 1
            else:
                _record_overflow(
                    packed,
                    over_budget_reason="FEE_NOT_KNOWN_LIMIT",
                    excluded_code="FEE_NOT_KNOWN_LIMIT",
                    excluded_reason=(
                        f"the pack already holds {MAX_FEE_NOT_KNOWN} programmes "
                        "whose application fee is not known"
                    ),
                    tradeoff_note=(
                        f"the pack already holds {MAX_FEE_NOT_KNOWN} programmes "
                        "whose application fee is not known; kept in Other options"
                    ),
                )
        elif fee == 0:
            fee_free.append(packed)
            if inst_id:
                packed_per_institution[inst_id] = packed_per_institution.get(inst_id, 0) + 1
        elif fee_in_base * BANK_MARGIN <= budget_remaining:
            # Portfolio anti-lottery guard: do not let a REACH (<20%) programme spend the
            # last application-fee budget needed by a later TARGET/SAFETY (>=25%) programme
            # when the active pack has no TARGET/SAFETY anchor yet.
            reserve_for_anchor = (
                tier == "REACH"
                and not top_only
                and not _has_anchor_in_active()
                and _should_reserve_budget_for_anchor(
                    ranked[idx + 1 :],
                    by_id=by_id,
                    profile=profile,
                    rates=rates,
                    schemes=schemes,
                    probabilities=probabilities,
                    funded_probabilities=funded_probabilities,
                    budget_remaining=budget_remaining,
                    remaining_after=budget_remaining - fee_in_base,
                    active_count=_active_count(),
                    fee_not_known_count=len(fee_not_known),
                    packed_per_institution=packed_per_institution,
                    enforce_institution_cap=enforce_institution_cap,
                    today=today,
                )
            )
            if reserve_for_anchor:
                anchor_note = (
                    "application budget reserved for a higher-probability "
                    "target or safety programme"
                )
                _record_overflow(
                    packed,
                    over_budget_reason="ANCHOR_BUDGET_RESERVED",
                    excluded_code="APPLICATION_BUDGET_EXCEEDED",
                    excluded_reason=anchor_note,
                    tradeoff_note=anchor_note,
                )
            else:
                paid.append(packed)
                # The margin is a check, not a charge: the budget is spent at the fee.
                budget_remaining -= fee_in_base
                if inst_id:
                    packed_per_institution[inst_id] = packed_per_institution.get(inst_id, 0) + 1
        else:
            _record_overflow(
                packed,
                over_budget_reason="APPLICATION_BUDGET_EXCEEDED",
                excluded_code="APPLICATION_BUDGET_EXCEEDED",
                excluded_reason="the application fee would exceed the remaining application budget",
            )

    # Awards are evaluated and packed AFTER the programme budget arithmetic
    # above, and touch none of it: `budget_remaining` is an application-fee
    # budget and an award charges no fee.
    earliest_fee_deadline = min(
        (
            candidate.application_deadline
            for candidate in candidates
            if candidate.application_deadline is not None
        ),
        default=None,
    )
    packed_awards: list[PackedAward] = []
    for award in (() if _ignores_funding_options(profile) else awards):
        outcome = evaluate_award(profile, award, today=today)
        if outcome.outcome in ("NOT_ELIGIBLE", "ELIGIBLE_BELOW_FIT_BAR"):
            # P1-7: visible with the reason, never a silently short pack.
            excluded.append(
                ExcludedCandidate(
                    program_id=award.award_id,
                    reason_code=outcome.outcome,
                    reasons=outcome.reasons,
                )
            )
            continue
        ordering, reason = _award_ordering(
            award, earliest_fee_deadline, home_country=profile.nationality
        )
        packed_awards.append(
            PackedAward(
                award_id=award.award_id,
                name=award.name,
                holder_name=award.holder_name,
                deadline=award.evidence.deadline,
                ordering=ordering,
                ordering_reason=reason,
                unconfirmed=award.unconfirmed,
                card=award.card,
                estimated_chance_pct=(
                    award_probabilities.get(award.award_id)
                    if award_probabilities is not None
                    else None
                ),
            )
        )

    # When the pack has at least one active item, include ELIGIBLE_BELOW_FIT_BAR
    # programmes in `over_budget` so `_publish` writes them into "Other options"
    # (`considered`) with their fit-bar explanation (evaluation.py:54-60).
    if (fee_free or paid or fee_not_known or packed_awards) and below_fit_candidates:
        next_rank = len(ranked) + 1
        for candidate, fit_reasons in below_fit_candidates:
            try:
                effective_cand = _strip_undecidable_secondary_routes(
                    profile,
                    candidate,
                    rates,
                    schemes=schemes.get(candidate.program_id, ()),
                    today=today,
                )
                aff = calculate_affordability(profile, effective_cand, rates, today=today)
                convert(aff.application_fee, aff.application_fee_currency, rates.base, rates)
            except UnconvertibleCurrency:
                continue
            bonds_bf = return_service_disclosures(profile, effective_cand, today=today)
            bond_conflict_bf = (
                (
                    "conflicts with your preference to work abroad after graduation "
                    "(return-service bond applies)",
                )
                if (avoids_bond and bonds_bf)
                else ()
            )
            tradeoffs_bf = tuple(
                dict.fromkeys(
                    (
                        *fit_reasons,
                        *closed_route_reasons(profile, candidate, today=today),
                        *unevaluable_condition_reasons(profile, candidate, today=today),
                        *bonds_bf,
                        *bond_conflict_bf,
                        *((coursework_warnings or {}).get(candidate.program_id, ())),
                    )
                )
            )
            over_budget.append(
                _make_packed_application(
                    candidate,
                    effective_cand,
                    aff,
                    rank=next_rank,
                    tradeoffs=tradeoffs_bf,
                    over_budget_reason="ELIGIBLE_BELOW_FIT_BAR",
                )
            )
            next_rank += 1

    return Pack(
        fee_free=tuple(fee_free),
        paid=tuple(paid),
        awards=tuple(packed_awards),
        excluded=tuple(excluded),
        over_budget=tuple(over_budget),
        fee_not_known=tuple(fee_not_known),
    )
