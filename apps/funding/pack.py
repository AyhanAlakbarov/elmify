from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

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
    #: Exact multi-funder common-shock portfolio success probability percentage
    #: (1..99), i.e. probability of securing at least one affordable/funded offer
    #: across active programmes in `fee_free + paid + fee_not_known`.
    pack_success_probability_pct: int | None = None


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


_INDEPENDENT_SCHEME_LABELS: frozenset[str] = frozenset(
    {
        "",
        "none",
        "affordable",
        "self-funded",
        "self funded",
        "tuition waiver",
        "university scholarship",
        "university merit scholarship",
        "departmental scholarship",
    }
)


@dataclass(frozen=True)
class FunderRiskTerms:
    """Decomposition of a candidate's funded success indicator Z_i = F_k * A_i.

    For independent candidates (`funder_key is None`):
        - `q_funder == 1.0`
        - `cond_admission_prob == effective_prob == p_i`
    For shared external scholarship candidates (`funder_key == k`):
        - `F_k ~ Bernoulli(q_funder)` is shared across all candidates in group `k`
        - `A_i ~ Bernoulli(cond_admission_prob)` is conditionally independent given `F_k = 1`
        - `q_funder * cond_admission_prob == effective_prob == p_i`
    """

    funder_key: str | None
    q_funder: float
    cond_admission_prob: float
    effective_prob: float
    has_known_prob: bool = True


def _normalize_shared_funder_key(
    scheme_name: str | None,
    *,
    uses_external_scheme: bool,
) -> str | None:
    if not uses_external_scheme or not scheme_name:
        return None
    cleaned = scheme_name.strip()
    lowered = cleaned.lower()
    if lowered in _INDEPENDENT_SCHEME_LABELS:
        return None
    if lowered.startswith("university ") or lowered.endswith(" university scholarship"):
        return None
    return lowered


def _soft_fit_score(scores: EvaluationScores) -> Decimal:
    fit_scores = [d.score for d in scores.dimensions if d.dimension != "AFFORDABILITY"]
    if not fit_scores:
        return Decimal("0")
    return sum(fit_scores, Decimal("0")) / Decimal(len(fit_scores))


def _effective_shortfall_for(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    affordability: AffordabilityResult,
    schemes: Mapping[str, tuple[str, ...]],
) -> Decimal:
    if schemes.get(candidate.program_id) or post_admission_gov_scheme_for_candidate(
        profile, candidate
    ):
        return Decimal("0.00")
    return max(
        Decimal("0.00"),
        affordability.shortfall - affordability.conditional_savings,
    )


def _candidate_effective_score(
    profile: StudentProfileSnapshot,
    candidate: CandidateFacts,
    effective_cand: CandidateFacts,
    scores: EvaluationScores,
    affordability: AffordabilityResult,
    *,
    schemes: Mapping[str, tuple[str, ...]],
    probabilities: Mapping[str, int] | None = None,
    funded_probabilities: Mapping[str, int | None] | None = None,
    coursework_warnings: Mapping[str, tuple[str, ...]] | None = None,
    today: date | None = None,
) -> Decimal:
    top_only = _wants_top_universities_only(profile)
    post_admit_gov = has_post_admission_gov_scholarship(profile)
    avoids_bond = _avoids_return_bond(profile)
    score = (
        _soft_fit_score(scores)
        if (
            (top_only or post_admit_gov)
            and _effective_shortfall_for(profile, candidate, affordability, schemes)
            == Decimal("0.00")
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
    if top_only:
        raw_baseline = getattr(candidate, "admission_baseline_pct", None)
        if raw_baseline is None:
            raw_baseline = getattr(candidate, "admission_Baseline_pct", None)
        if raw_baseline is not None:
            score += (Decimal("50") - Decimal(str(raw_baseline))) * Decimal("0.15")
        elif is_selective_candidate(candidate):
            score += Decimal("4.5")
        acad_prog_fit = (
            candidate.dimension_scores.get("ACADEMIC_FIT", Decimal("50"))
            + candidate.dimension_scores.get("PROGRAM_FIT", Decimal("50"))
        ) / Decimal("2")
        score += (acad_prog_fit - Decimal("50")) * Decimal("0.05")
        if eff_chance is not None:
            score += (Decimal(eff_chance) - Decimal("50")) * Decimal("0.05")
    elif eff_chance is not None:
        score += (Decimal(eff_chance) - Decimal("50")) * Decimal("0.15")
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


def _decompose_portfolio_funder_risk(
    profile: StudentProfileSnapshot,
    candidates: Sequence[CandidateFacts],
    rates: RateTable,
    *,
    schemes: Mapping[str, tuple[str, ...]] | None = None,
    probabilities: Mapping[str, int] | None = None,
    funded_probabilities: Mapping[str, int | None] | None = None,
    award_probabilities: Mapping[str, int] | None = None,
    awards: Sequence[AwardCandidateFacts] = (),
    today: date | None = None,
) -> dict[str, FunderRiskTerms]:
    """Decompose each candidate's standalone probability into `(funder_key, q_funder, a_i, p_i)`.

    Uses `schemes` (`HOLDER`/`COUNTRY` external scholarships and post-admission government
    scholarships) with exact identity `q_funder * cond_admission_prob == effective_prob`
    on singletons and across shared funder groups.
    """
    schemes_map = dict(schemes or {})
    award_prob_by_key: dict[str, float] = {}
    if award_probabilities:
        for aw in awards:
            aw_pct = award_probabilities.get(aw.award_id)
            if aw_pct is not None:
                award_prob_by_key[aw.name.strip().lower()] = max(
                    0.01, min(0.99, float(aw_pct) / 100.0)
                )
        for k_raw, pct_val in award_probabilities.items():
            key_norm = k_raw.strip().lower()
            if key_norm not in award_prob_by_key:
                award_prob_by_key[key_norm] = max(
                    0.01, min(0.99, float(pct_val) / 100.0)
                )

    prelim: dict[str, tuple[str | None, float, float, bool]] = {}
    raw_groups: dict[str, list[tuple[str, float, float]]] = {}
    resolved_today = today if today is not None else date.today()

    for candidate in candidates:
        pid = candidate.program_id
        cand_schemes = list(schemes_map.get(pid, ()))
        for name in schemes_paying_for(
            profile, candidate, awards, today=resolved_today
        ):
            if name not in cand_schemes:
                cand_schemes.append(name)
        gov_scheme = post_admission_gov_scheme_for_candidate(profile, candidate)
        if gov_scheme is not None and gov_scheme not in cand_schemes:
            cand_schemes.append(gov_scheme)
        cand_schemes_tuple = tuple(cand_schemes)

        try:
            effective_cand = _strip_undecidable_secondary_routes(
                profile,
                candidate,
                rates,
                schemes=cand_schemes_tuple,
                today=today,
            )
            aff = calculate_affordability(profile, effective_cand, rates, today=today)
            prog_closes_gap = _programme_money_closes_the_gap(
                profile, effective_cand, rates, today=today
            )
            conditional = needs_selective_funding(profile, effective_cand, today=today)
        except UnconvertibleCurrency:
            continue

        eff_chance_pct = _effective_chance_for(
            profile,
            pid,
            aff,
            probabilities=probabilities,
            funded_probabilities=funded_probabilities,
            conditional=conditional,
        )
        if eff_chance_pct is None:
            prelim[pid] = (None, 0.0, 0.0, False)
            continue

        p_i = max(0.0, min(0.9999, float(eff_chance_pct) / 100.0))
        admit_pct = (
            probabilities.get(pid) if probabilities is not None else None
        )
        a_raw = (
            max(p_i, min(0.9999, float(admit_pct) / 100.0))
            if admit_pct is not None
            else p_i
        )

        has_distinct_funded = (
            funded_probabilities is not None
            and funded_probabilities.get(pid) is not None
            and (admit_pct is None or funded_probabilities.get(pid) != admit_pct)
        )
        uses_external_scheme = bool(cand_schemes_tuple) and (
            not prog_closes_gap or has_distinct_funded
        ) and (
            conditional
            or profile.funding_dependency == "MANDATORY"
            or aff.shortfall > 0
            or has_distinct_funded
            or has_post_admission_gov_scholarship(profile)
        )

        primary_scheme: str | None = None
        if uses_external_scheme:
            # Prefer a scheme with an explicit award probability if multiple exist
            best_scheme = cand_schemes_tuple[0]
            best_aw_prob = -1.0
            for s_name in cand_schemes_tuple:
                s_prob = award_prob_by_key.get(s_name.strip().lower(), -1.0)
                if s_prob > best_aw_prob:
                    best_aw_prob = s_prob
                    best_scheme = s_name
            primary_scheme = best_scheme

        funder_key = _normalize_shared_funder_key(
            primary_scheme,
            uses_external_scheme=uses_external_scheme,
        )
        prelim[pid] = (funder_key, p_i, a_raw, True)
        if funder_key is not None:
            raw_groups.setdefault(funder_key, []).append((pid, p_i, a_raw))

    result: dict[str, FunderRiskTerms] = {}
    group_q: dict[str, float] = {}
    for funder_key, group in raw_groups.items():
        max_p = max((g_p for _g_pid, g_p, _g_a in group), default=0.0)
        if max_p <= 0.0:
            group_q[funder_key] = 1.0
            continue
        if funder_key in award_prob_by_key:
            q_val = award_prob_by_key[funder_key]
        else:
            implied: list[float] = []
            for _g_pid, g_p, g_a_raw in group:
                if g_p <= 0.0:
                    continue
                if g_a_raw > g_p + 1e-6:
                    implied.append(g_p / g_a_raw)
                else:
                    implied.append(min(0.95, math.sqrt(g_p)))
            q_val = max(implied) if implied else 1.0
        # Ensure q_val >= max_p / 0.99 so every conditional admission a_i = p_i / q_val <= 0.99,
        # unless group is a singleton with explicit a_raw > p_i where q_val = p_i / a_raw is exact.
        if (
            len(group) == 1
            and group[0][2] > group[0][1] + 1e-6
            and funder_key not in award_prob_by_key
        ):
            q_val = group[0][1] / group[0][2]
        else:
            q_val = max(q_val, min(0.9999, max_p / 0.99))
        group_q[funder_key] = max(0.0001, min(1.0, q_val))

    for pid, (funder_key, p_i, a_raw, has_prob) in prelim.items():
        if not has_prob or p_i <= 0.0:
            result[pid] = FunderRiskTerms(
                funder_key=None,
                q_funder=1.0,
                cond_admission_prob=0.0,
                effective_prob=0.0,
                has_known_prob=has_prob,
            )
            continue
        if funder_key is None:
            result[pid] = FunderRiskTerms(
                funder_key=None,
                q_funder=1.0,
                cond_admission_prob=p_i,
                effective_prob=p_i,
                has_known_prob=True,
            )
            continue
        q_k = group_q.get(funder_key, 1.0)
        if q_k >= 0.9999:
            result[pid] = FunderRiskTerms(
                funder_key=None,
                q_funder=1.0,
                cond_admission_prob=p_i,
                effective_prob=p_i,
                has_known_prob=True,
            )
        else:
            a_i = p_i / q_k
            result[pid] = FunderRiskTerms(
                funder_key=funder_key,
                q_funder=q_k,
                cond_admission_prob=a_i,
                effective_prob=p_i,
                has_known_prob=True,
            )

    return result


def compute_portfolio_failure_probability(
    active_pids: Sequence[str],
    risk_map: Mapping[str, FunderRiskTerms],
) -> float:
    """Compute exact multi-funder common-shock failure probability `P_fail(S)`.

    `P_fail(S) = (prod_{i in S_0}(1 - p_i)) * prod_k ((1 - q_k) + q_k * prod_{i in S_k}(1 - a_i))`
    """
    indep_fail = 1.0
    funder_groups: dict[str, tuple[float, float]] = {}

    for pid in active_pids:
        terms = risk_map.get(pid)
        if terms is None or not terms.has_known_prob:
            continue
        if terms.funder_key is None:
            indep_fail *= 1.0 - terms.effective_prob
        else:
            q_k, prod_fail = funder_groups.get(terms.funder_key, (terms.q_funder, 1.0))
            funder_groups[terms.funder_key] = (
                q_k,
                prod_fail * (1.0 - terms.cond_admission_prob),
            )

    total_fail = indep_fail
    for _k, (q_k, prod_fail) in funder_groups.items():
        total_fail *= (1.0 - q_k) + q_k * prod_fail

    return max(0.0, min(1.0, total_fail))


def compute_pack_success_probability_pct(
    active_items: Sequence[PackedApplication | str | Mapping[str, Any]],
    risk_map: Mapping[str, FunderRiskTerms],
) -> int | None:
    """Return rounded integer percentage `100 * (1 - P_fail(S))`, or `None` when unknown/empty."""
    known_pids: list[str] = []
    for item in active_items:
        if isinstance(item, str):
            pid = item
        elif isinstance(item, PackedApplication):
            pid = item.program_id
        elif isinstance(item, Mapping):
            prog = item.get("program")
            if isinstance(prog, Mapping):
                pid = str(prog.get("id", ""))
            else:
                pid = str(item.get("program_id", ""))
        else:
            pid = getattr(item, "program_id", "")
        if not pid:
            continue
        terms = risk_map.get(pid)
        if terms is not None and terms.has_known_prob:
            known_pids.append(pid)

    if not known_pids:
        return None
    p_fail = compute_portfolio_failure_probability(known_pids, risk_map)
    p_succ_pct = int(round((1.0 - p_fail) * 100.0))
    if p_fail < 1.0:
        return max(1, min(99, p_succ_pct))
    return 0


def _marginal_survival_factor(
    candidate_pid: str,
    active_pids: Sequence[str],
    risk_map: Mapping[str, FunderRiskTerms],
) -> float:
    """Exact Proposition 3(2) survival factor `Phi(i | S)` for adding `candidate_pid`.

    `Phi(i | S) = P_fail(S \\ S_{k(i)}) * prod_{j in S_{k(i)} cap S}(1 - a_j)`.
    """
    cand_terms = risk_map.get(candidate_pid)
    cand_key = cand_terms.funder_key if cand_terms is not None else None

    indep_fail = 1.0
    funder_groups: dict[str, tuple[float, float]] = {}

    for pid in active_pids:
        terms = risk_map.get(pid)
        if terms is None or not terms.has_known_prob:
            continue
        if terms.funder_key is None:
            indep_fail *= 1.0 - terms.effective_prob
        else:
            q_k, prod_fail = funder_groups.get(terms.funder_key, (terms.q_funder, 1.0))
            funder_groups[terms.funder_key] = (
                q_k,
                prod_fail * (1.0 - terms.cond_admission_prob),
            )

    phi = indep_fail
    for k, (q_k, prod_fail) in funder_groups.items():
        if cand_key is not None and k == cand_key:
            phi *= prod_fail
        else:
            phi *= (1.0 - q_k) + q_k * prod_fail

    return max(0.0, min(1.0, phi))


def _marginal_portfolio_utility(
    candidate_or_pid: str | RankedCandidate | PackedApplication | Mapping[str, Any],
    active_pids_or_score: Sequence[str] | float | Decimal,
    risk_map: Mapping[str, FunderRiskTerms] | Sequence[str],
    maybe_risk_map: Mapping[str, FunderRiskTerms] | None = None,
    *,
    effective_score: float | Decimal | None = None,
) -> float:
    """Evaluate Chade-Smith / Ali-Shorrer marginal utility `Phi(i | S) * max(0, score_i)`."""
    if maybe_risk_map is not None:
        # 4-positional-argument form: (pid, effective_score, active_pids, risk_map)
        pid = str(candidate_or_pid)
        raw_score = float(active_pids_or_score)  # type: ignore[arg-type]
        act_pids = list(risk_map)
        r_map = maybe_risk_map
    else:
        # 3-positional-argument form: (item_or_pid, active_pids, risk_map, *, effective_score=...)
        act_pids = list(active_pids_or_score)  # type: ignore[arg-type]
        r_map = risk_map  # type: ignore[assignment]
        if isinstance(candidate_or_pid, str):
            pid = candidate_or_pid
            raw_score = float(effective_score) if effective_score is not None else 0.0
        elif isinstance(candidate_or_pid, Mapping):
            prog = candidate_or_pid.get("program")
            if isinstance(prog, Mapping):
                pid = str(prog.get("id", ""))
            else:
                pid = str(candidate_or_pid.get("program_id", ""))
            score_val = (
                effective_score
                if effective_score is not None
                else candidate_or_pid.get("effective_score", 0.0)
            )
            raw_score = float(score_val)
        elif isinstance(candidate_or_pid, RankedCandidate):
            pid = candidate_or_pid.program_id
            if effective_score is not None:
                raw_score = float(effective_score)
            elif candidate_or_pid.scores is not None:
                raw_score = float(candidate_or_pid.scores.overall)
            else:
                raw_score = 0.0
        else:
            pid = getattr(candidate_or_pid, "program_id", "")
            raw_score = float(effective_score) if effective_score is not None else 0.0

    base_score = max(0.0, raw_score)
    if not pid or base_score <= 0.0:
        return 0.0
    phi = _marginal_survival_factor(pid, act_pids, r_map)
    return phi * base_score


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
    best_soft_fit = max(_soft_fit_score(scores) for _, _, scores, _ in evaluated)

    top_only = _wants_top_universities_only(profile)
    avoids_bond = _avoids_return_bond(profile)

    def effective_shortfall(
        candidate: CandidateFacts, affordability: AffordabilityResult
    ) -> Decimal:
        return _effective_shortfall_for(profile, candidate, affordability, schemes)

    def effective_score(
        candidate: CandidateFacts,
        effective_cand: CandidateFacts,
        scores: EvaluationScores,
        affordability: AffordabilityResult,
    ) -> Decimal:
        return _candidate_effective_score(
            profile,
            candidate,
            effective_cand,
            scores,
            affordability,
            schemes=schemes,
            probabilities=probabilities,
            funded_probabilities=funded_probabilities,
            coursework_warnings=coursework_warnings,
            today=today,
        )

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
        if _soft_fit_score(scores) < best_soft_fit:
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


@dataclass(frozen=True)
class _SelectionEntry:
    orig_idx: int
    ranked_item: RankedCandidate
    candidate: CandidateFacts
    effective_cand: CandidateFacts
    packed: PackedApplication
    fee: Decimal
    currency: str
    fee_in_base: Decimal
    effective_score: Decimal
    funding_bucket: tuple[Decimal, int]


@dataclass(frozen=True)
class _SelectionPassResult:
    fee_free: list[PackedApplication]
    paid: list[PackedApplication]
    fee_not_known: list[PackedApplication]
    over_budget: list[PackedApplication]
    excluded: list[ExcludedCandidate]
    total_utility: float


def _run_portfolio_selection_pass(
    entries: Sequence[_SelectionEntry],
    *,
    by_id: Mapping[str, CandidateFacts],
    profile: StudentProfileSnapshot,
    rates: RateTable,
    schemes: Mapping[str, tuple[str, ...]],
    probabilities: Mapping[str, int] | None,
    funded_probabilities: Mapping[str, int | None] | None,
    risk_map: Mapping[str, FunderRiskTerms],
    budget_total: Decimal,
    enforce_institution_cap: bool,
    top_only: bool,
    cost_scaled: bool,
    today: date,
) -> _SelectionPassResult:
    """Run one submodular selection pass (`cost_scaled=False` MIA or `cost_scaled=True` density)."""
    fee_free: list[PackedApplication] = []
    paid: list[PackedApplication] = []
    fee_not_known: list[PackedApplication] = []
    over_budget: list[PackedApplication] = []
    excluded: list[ExcludedCandidate] = []
    budget_remaining = budget_total
    spent_plain_in_base = Decimal("0")
    packed_per_institution: dict[str, int] = {}
    active_pids: list[str] = []
    selected_entries: list[_SelectionEntry] = []

    def _active_count() -> int:
        return len(fee_free) + len(paid) + len(fee_not_known)

    def _has_anchor_in_active() -> bool:
        return any(
            app.risk_tier in ("SAFETY", "TARGET")
            for app in (*fee_free, *paid, *fee_not_known)
        )

    def _can_afford_paid(entry: _SelectionEntry) -> bool:
        if entry.fee_in_base * BANK_MARGIN > budget_remaining:
            return False
        if not paid or all(
            p.application_fee_currency == entry.currency for p in paid
        ):
            return (spent_plain_in_base + entry.fee_in_base) * BANK_MARGIN <= budget_total
        return True

    def _fee_deduction_for(entry: _SelectionEntry) -> Decimal:
        if (
            entry.currency == profile.application_budget.currency
            and rates.base != profile.application_budget.currency
            and not paid
        ):
            return entry.fee_in_base
        return entry.fee_in_base * BANK_MARGIN

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

    remaining_pool: list[_SelectionEntry] = list(entries)

    while remaining_pool:
        # Evaluate unscaled marginal utility Delta U(i | S) for all remaining candidates
        marg_by_pos: list[float] = [
            _marginal_portfolio_utility(
                entry.packed.program_id,
                entry.effective_score,
                active_pids,
                risk_map,
            )
            for entry in remaining_pool
        ]

        # Best unscaled candidate overall (Pass 1 order)
        best_unscaled_pos = max(
            range(len(remaining_pool)),
            key=lambda pos: (
                -remaining_pool[pos].funding_bucket[0],
                -remaining_pool[pos].funding_bucket[1],
                round(marg_by_pos[pos], 9),
                -remaining_pool[pos].orig_idx,
            ),
        )

        chosen_pos = best_unscaled_pos
        if cost_scaled and _active_count() < MAX_ACTIVE_PROGRAMS:
            best_entry = remaining_pool[best_unscaled_pos]
            # When the next slot's unscaled leader is a paid candidate that is currently
            # budget-feasible, compare all currently feasible paid candidates in the same
            # funding bucket by marginal utility per unit fee: Delta U(i | S) / max(c_i, 1.0).
            if best_entry.packed.fee_known and best_entry.fee > 0 and _can_afford_paid(best_entry):
                best_density_pos: int | None = None
                best_density_key: tuple[Decimal, int, float, float, int] | None = None
                for pos, cand_entry in enumerate(remaining_pool):
                    if not (cand_entry.packed.fee_known and cand_entry.fee > 0):
                        continue
                    if not _can_afford_paid(cand_entry):
                        continue
                    inst_id_c = cand_entry.candidate.institution_id
                    if (
                        enforce_institution_cap
                        and inst_id_c
                        and packed_per_institution.get(inst_id_c, 0) >= MAX_PER_INSTITUTION
                    ):
                        continue
                    fee_denom = max(float(cand_entry.fee_in_base), 1.0)
                    density = marg_by_pos[pos] / fee_denom
                    d_key = (
                        -cand_entry.funding_bucket[0],
                        -cand_entry.funding_bucket[1],
                        round(density, 9),
                        round(marg_by_pos[pos], 9),
                        -cand_entry.orig_idx,
                    )
                    if best_density_key is None or d_key > best_density_key:
                        best_density_key = d_key
                        best_density_pos = pos
                if best_density_pos is not None:
                    chosen_pos = best_density_pos

        entry = remaining_pool.pop(chosen_pos)
        packed = entry.packed
        tier = packed.risk_tier
        inst_id = entry.candidate.institution_id
        fee = entry.fee
        fee_in_base = entry.fee_in_base

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
                active_pids.append(packed.program_id)
                selected_entries.append(entry)
                if inst_id:
                    packed_per_institution[inst_id] = (
                        packed_per_institution.get(inst_id, 0) + 1
                    )
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
            active_pids.append(packed.program_id)
            selected_entries.append(entry)
            if inst_id:
                packed_per_institution[inst_id] = (
                    packed_per_institution.get(inst_id, 0) + 1
                )
        elif _can_afford_paid(entry):
            fee_deduction = _fee_deduction_for(entry)
            later_ranked = [rem.ranked_item for rem in remaining_pool]
            reserve_for_anchor = (
                tier == "REACH"
                and not top_only
                and not _has_anchor_in_active()
                and _should_reserve_budget_for_anchor(
                    later_ranked,
                    by_id=by_id,
                    profile=profile,
                    rates=rates,
                    schemes=schemes,
                    probabilities=probabilities,
                    funded_probabilities=funded_probabilities,
                    budget_remaining=budget_remaining,
                    remaining_after=budget_remaining - fee_deduction,
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
                active_pids.append(packed.program_id)
                selected_entries.append(entry)
                spent_plain_in_base += fee_in_base
                budget_remaining -= fee_deduction
                if inst_id:
                    packed_per_institution[inst_id] = (
                        packed_per_institution.get(inst_id, 0) + 1
                    )
        else:
            _record_overflow(
                packed,
                over_budget_reason="APPLICATION_BUDGET_EXCEEDED",
                excluded_code="APPLICATION_BUDGET_EXCEEDED",
                excluded_reason="the application fee would exceed the remaining application budget",
            )

    # Evaluate canonical set-function portfolio utility U(S) over the selected active set S
    canonical_pids: list[str] = []
    total_utility = 0.0
    for sel in sorted(selected_entries, key=lambda e: e.orig_idx):
        total_utility += _marginal_portfolio_utility(
            sel.packed.program_id,
            sel.effective_score,
            canonical_pids,
            risk_map,
        )
        canonical_pids.append(sel.packed.program_id)

    return _SelectionPassResult(
        fee_free=fee_free,
        paid=paid,
        fee_not_known=fee_not_known,
        over_budget=over_budget,
        excluded=excluded,
        total_utility=total_utility,
    )


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
                    funding_is_conditional=True,
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

    budget_total = convert(
        profile.application_budget.amount,
        profile.application_budget.currency,
        rates.base,
        rates,
    )
    distinct_institutions = {
        c.institution_id for c in candidates if c.institution_id
    }
    enforce_institution_cap = len(distinct_institutions) > 1

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

    risk_schemes = dict(schemes)
    if attached_schemes:
        for pid, s_names in attached_schemes.items():
            if pid not in risk_schemes and s_names:
                risk_schemes[pid] = tuple(s_names)

    risk_map = _decompose_portfolio_funder_risk(
        profile,
        [by_id[item.program_id] for item in ranked],
        rates,
        schemes=risk_schemes,
        probabilities=probabilities,
        funded_probabilities=funded_probabilities,
        award_probabilities=award_probabilities,
        awards=awards,
        today=today,
    )

    selection_entries: list[_SelectionEntry] = []
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
        fee_in_base = convert(fee, currency, rates.base, rates)
        packed = _make_packed_application(
            candidate,
            effective_cand,
            item.affordability,
            rank=position,
            tradeoffs=item.tradeoffs,
        )
        assert item.scores is not None
        eff_score = _candidate_effective_score(
            profile,
            candidate,
            effective_cand,
            item.scores,
            item.affordability,
            schemes=schemes,
            probabilities=probabilities,
            funded_probabilities=funded_probabilities,
            coursework_warnings=coursework_warnings,
            today=today,
        )
        if profile.strategy == "FUNDING_FIRST":
            eff_sf = _effective_shortfall_for(profile, candidate, item.affordability, schemes)
            sf_tier = 0 if (top_only or item.affordability.shortfall == Decimal("0.00")) else 1
            f_bucket = (eff_sf, sf_tier)
        else:
            f_bucket = (Decimal("0.00"), 0)

        selection_entries.append(
            _SelectionEntry(
                orig_idx=idx,
                ranked_item=item,
                candidate=candidate,
                effective_cand=effective_cand,
                packed=packed,
                fee=fee,
                currency=currency,
                fee_in_base=fee_in_base,
                effective_score=eff_score,
                funding_bucket=f_bucket,
            )
        )

    unit_res = _run_portfolio_selection_pass(
        selection_entries,
        by_id=by_id,
        profile=profile,
        rates=rates,
        schemes=schemes,
        probabilities=probabilities,
        funded_probabilities=funded_probabilities,
        risk_map=risk_map,
        budget_total=budget_total,
        enforce_institution_cap=enforce_institution_cap,
        top_only=top_only,
        cost_scaled=False,
        today=today,
    )
    density_res = _run_portfolio_selection_pass(
        selection_entries,
        by_id=by_id,
        profile=profile,
        rates=rates,
        schemes=schemes,
        probabilities=probabilities,
        funded_probabilities=funded_probabilities,
        risk_map=risk_map,
        budget_total=budget_total,
        enforce_institution_cap=enforce_institution_cap,
        top_only=top_only,
        cost_scaled=True,
        today=today,
    )
    if density_res.total_utility > unit_res.total_utility + 1e-6:
        chosen_res = density_res
    else:
        chosen_res = unit_res

    fee_free = chosen_res.fee_free
    paid = chosen_res.paid
    fee_not_known = chosen_res.fee_not_known
    over_budget = chosen_res.over_budget
    excluded.extend(chosen_res.excluded)

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

    active_apps: tuple[PackedApplication, ...] = (*fee_free, *paid, *fee_not_known)
    pack_success_pct = compute_pack_success_probability_pct(active_apps, risk_map)

    return Pack(
        fee_free=tuple(fee_free),
        paid=tuple(paid),
        awards=tuple(packed_awards),
        excluded=tuple(excluded),
        over_budget=tuple(over_budget),
        fee_not_known=tuple(fee_not_known),
        pack_success_probability_pct=pack_success_pct,
    )
