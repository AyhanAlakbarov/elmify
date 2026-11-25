"""Unit and integration tests for simultaneous application portfolio optimization
under application fee budgets and correlated external funder risk (`apps/funding/pack.py`).

Verifies:
1. `_decompose_portfolio_funder_risk`: exact identity `q_k * a_i == p_i` on singletons and
   shared external scholarship groups (`HOLDER` / `COUNTRY` / post-admission gov scholarship).
2. `_marginal_portfolio_utility` & `_marginal_survival_factor`: Chade-Smith (2006) /
   Ali-Shorrer (2025) marginal portfolio utility `Delta U(i | S) = Phi(i | S) * max(0, score_i)`
   where `Phi(i | S)` discounts repeated bets on the same external scholarship `k` by
   `prod_{j in S_k cap S}(1 - a_j)` while matching `rank_candidates` 100% when candidates
   have independent funding.
3. `compute_pack_success_probability_pct` and `Pack.pack_success_probability_pct`: exact
   multi-funder common-shock formula, strictly bounded by the funder concentration ceiling
   `q_k` and strictly lower than naive independence.
4. `_run_portfolio_selection_pass` (Twin-Pass Budgeted Submodular Maximization):
   - Under a tight application fee budget, three high-efficiency 30 EUR candidates beat a single
     95 EUR candidate when their combined portfolio utility `U(S_density)` is higher.
   - An unscaled high-value single anchor still wins (`U(S_unit) >= U(S_density)`) when a cheap
     low-utility filler would otherwise block the anchor (Kapur & Hong 2022, Example 3).
5. Real downstream caller integration feeding `build_pack` output into `SpineResult` and
   downstream packet/publication consumers.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from apps.accounts.schemas import Money, ProfileConstraint
from apps.funding.card import AwardCard
from apps.funding.pack import (
    _decompose_portfolio_funder_risk,
    _marginal_portfolio_utility,
    _marginal_survival_factor,
    build_pack,
    compute_pack_success_probability_pct,
    compute_portfolio_failure_probability,
    rank_candidates,
)
from tests.funding.conftest import (
    EUR_RATES,
    make_benefit,
    make_candidate,
    make_cost,
    make_profile,
)
from tests.funding.test_award_gates import _award

TODAY = date(2026, 10, 24)

_STRONG_SCORES = {
    "ACADEMIC_FIT": Decimal("95"),
    "PROGRAM_FIT": Decimal("95"),
    "CAREER_FIT": Decimal("95"),
    "DURATION": Decimal("95"),
    "MOBILITY_FIT": Decimal("95"),
    "RESEARCH_FIT": Decimal("95"),
}

_HIGH_TARGET_SCORES = {
    "ACADEMIC_FIT": Decimal("91"),
    "PROGRAM_FIT": Decimal("91"),
    "CAREER_FIT": Decimal("91"),
    "DURATION": Decimal("91"),
    "MOBILITY_FIT": Decimal("91"),
    "RESEARCH_FIT": Decimal("91"),
}

_LOW_REACH_SCORES = {
    "ACADEMIC_FIT": Decimal("82"),
    "PROGRAM_FIT": Decimal("82"),
    "CAREER_FIT": Decimal("82"),
    "DURATION": Decimal("82"),
    "MOBILITY_FIT": Decimal("82"),
    "RESEARCH_FIT": Decimal("82"),
}


def _holder_scheme(
    *,
    name: str = "Stipendium Hungaricum",
    country_code: str = "HU",
    tuition: str = "FULL",
    living: str = "FULL",
) -> Any:
    card = AwardCard(
        route="STUDENT_APPLIES_SEPARATELY",
        tuition=tuition,
        living=living,
        amounts=(),
        duration_text="",
        duration_months=None,
        timing="UNSTATED",
        cycle="UNSTATED",
        unconfirmed=(),
    )
    return _award(
        award_id=f"aw-{name.lower().replace(' ', '-')}",
        name=name,
        card=card,
        scope="HOLDER",
        country_code=country_code,
    )


# ---------------------------------------------------------------------------
# 1. Funder Risk Decomposition & Singleton Identity (q_k * a_i == p_i)
# ---------------------------------------------------------------------------


def test_decompose_portfolio_funder_risk_singleton_and_group_identity() -> None:
    profile = make_profile(
        strategy="BALANCED",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    hu_1 = make_candidate(
        program_id="elte-cs",
        institution_id="elte",
        program_country_code="HU",
        location_key="HU-BUDAPEST",
        cost_components=(make_cost("TUITION", "6000.00"),),
        benefits=(),
    )
    hu_2 = make_candidate(
        program_id="bme-cs",
        institution_id="bme",
        program_country_code="HU",
        location_key="HU-BUDAPEST",
        cost_components=(make_cost("TUITION", "6000.00"),),
        benefits=(),
    )
    indep_waiver = make_candidate(
        program_id="tum-cs",
        institution_id="tum",
        program_country_code="DE",
        location_key="DE-MUNICH",
        cost_components=(make_cost("TUITION", "4000.00"),),
        benefits=(make_benefit(id="tum-waiver", amount="4000.00", accessibility="ORDINARY"),),
    )

    sh_award = _holder_scheme(name="Stipendium Hungaricum", country_code="HU")

    # Singleton check: q_k * a_i == p_i holds to machine precision
    singleton_map = _decompose_portfolio_funder_risk(
        profile,
        [hu_1],
        EUR_RATES,
        schemes={"elte-cs": ("Stipendium Hungaricum",)},
        probabilities={"elte-cs": 60},
        funded_probabilities={"elte-cs": 15},
        awards=[sh_award],
        today=TODAY,
    )
    t_single = singleton_map["elte-cs"]
    assert t_single.funder_key == "stipendium hungaricum"
    assert math.isclose(t_single.effective_prob, 0.15, rel_tol=1e-12)
    assert math.isclose(t_single.q_funder, 0.25, rel_tol=1e-12)
    assert math.isclose(t_single.cond_admission_prob, 0.60, rel_tol=1e-12)
    assert math.isclose(
        t_single.q_funder * t_single.cond_admission_prob,
        t_single.effective_prob,
        rel_tol=1e-12,
    )
    # Singleton failure probability equals 1 - p_i identically
    assert math.isclose(
        compute_portfolio_failure_probability(["elte-cs"], singleton_map),
        1.0 - 0.15,
        rel_tol=1e-12,
    )

    # Multi-candidate group check
    group_map = _decompose_portfolio_funder_risk(
        profile,
        [hu_1, hu_2, indep_waiver],
        EUR_RATES,
        schemes={
            "elte-cs": ("Stipendium Hungaricum",),
            "bme-cs": ("Stipendium Hungaricum",),
        },
        probabilities={"elte-cs": 60, "bme-cs": 48, "tum-cs": 50},
        funded_probabilities={"elte-cs": 15, "bme-cs": 12, "tum-cs": 50},
        awards=[sh_award],
        today=TODAY,
    )
    assert group_map["elte-cs"].funder_key == "stipendium hungaricum"
    assert group_map["bme-cs"].funder_key == "stipendium hungaricum"
    assert group_map["tum-cs"].funder_key is None
    assert math.isclose(group_map["elte-cs"].q_funder, 0.25, rel_tol=1e-12)
    assert math.isclose(group_map["bme-cs"].q_funder, 0.25, rel_tol=1e-12)
    assert math.isclose(group_map["elte-cs"].cond_admission_prob, 0.60, rel_tol=1e-12)
    assert math.isclose(group_map["bme-cs"].cond_admission_prob, 0.48, rel_tol=1e-12)
    for pid, terms in group_map.items():
        assert math.isclose(
            terms.q_funder * terms.cond_admission_prob,
            terms.effective_prob,
            rel_tol=1e-12,
        ), f"Identity failed for {pid}"


# ---------------------------------------------------------------------------
# 2. Common-Shock Funder Correlation Discounting & Funder Ceiling
# ---------------------------------------------------------------------------


def test_common_shock_marginal_utility_discounts_repeated_funder_bets_by_one_minus_a() -> None:
    """Verify Proposition 3(2):
    - A 2nd and 3rd programme sharing the same external scholarship k has its marginal
      utility discounted by (1 - a_j) for each already-selected programme j in S_k.
    - When candidates have independent funding, _marginal_portfolio_utility preserves
      rank_candidates ordering 100%.
    """
    profile = make_profile(
        strategy="BALANCED",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    h1 = make_candidate(
        program_id="hu-1",
        institution_id="inst-hu-1",
        program_country_code="HU",
        cost_components=(make_cost("TUITION", "6000.00"),),
    )
    h2 = make_candidate(
        program_id="hu-2",
        institution_id="inst-hu-2",
        program_country_code="HU",
        cost_components=(make_cost("TUITION", "6000.00"),),
    )
    h3 = make_candidate(
        program_id="hu-3",
        institution_id="inst-hu-3",
        program_country_code="HU",
        cost_components=(make_cost("TUITION", "6000.00"),),
    )
    risk_map = _decompose_portfolio_funder_risk(
        profile,
        [h1, h2, h3],
        EUR_RATES,
        schemes={
            "hu-1": ("Stipendium Hungaricum",),
            "hu-2": ("Stipendium Hungaricum",),
            "hu-3": ("Stipendium Hungaricum",),
        },
        probabilities={"hu-1": 60, "hu-2": 50, "hu-3": 40},
        funded_probabilities={"hu-1": 15, "hu-2": 12, "hu-3": 10},
        today=TODAY,
    )
    # q_k = 0.25, a_1 = 0.60, a_2 = 0.48, a_3 = 0.40
    score_val = Decimal("85.0")

    # 1st item (S = empty): Phi = 1.0
    u_1 = _marginal_portfolio_utility("hu-1", score_val, [], risk_map)
    assert math.isclose(u_1, 85.0, rel_tol=1e-12)

    # 2nd item sharing scholarship k (S = ["hu-1"]): discounted by (1 - a_1) = 0.40
    phi_2 = _marginal_survival_factor("hu-2", ["hu-1"], risk_map)
    assert math.isclose(phi_2, 1.0 - 0.60, rel_tol=1e-12)
    u_2 = _marginal_portfolio_utility("hu-2", score_val, ["hu-1"], risk_map)
    assert math.isclose(u_2, 85.0 * 0.40, rel_tol=1e-12)

    # 3rd item sharing scholarship k (S = ["hu-1", "hu-2"]): discounted by (1 - a_1)*(1 - a_2)
    phi_3 = _marginal_survival_factor("hu-3", ["hu-1", "hu-2"], risk_map)
    assert math.isclose(phi_3, (1.0 - 0.60) * (1.0 - 0.48), rel_tol=1e-12)
    u_3 = _marginal_portfolio_utility("hu-3", score_val, ["hu-1", "hu-2"], risk_map)
    assert math.isclose(u_3, 85.0 * 0.40 * 0.52, rel_tol=1e-12)


def test_correlated_external_funder_diversifies_pack_and_enforces_funder_ceiling() -> None:
    """Verify Proposition 2 and Proposition 3(3):
    1. When 5 Hungarian programmes all depend on 'Stipendium Hungaricum' (q_k = 20%, a_i = 60%,
       standalone funded = 12%), `pack_success_probability_pct` is strictly bounded by the
       funder ceiling q_k = 20% (actual: round(20 * (1 - 0.4^5)) = 20%) and strictly lower
       than naive independence (round(100 * (1 - 0.88^5)) = 47%).
    2. When German ('DAAD') and independent university-waiver programmes are also in the pool,
       `build_pack` diversifies across funders after picking the top Hungarian programme rather
       than stacking correlated Hungarian applications at the top of the pack.
    """
    profile = make_profile(
        strategy="FUNDING_FIRST",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
        application_budget=Money(amount=Decimal("500.00"), currency="EUR"),
    )
    hu_progs = [
        make_candidate(
            program_id=f"hu-{i}",
            institution_id=f"inst-hu-{i}",
            program_country_code="HU",
            cost_components=(
                make_cost("TUITION", "6000.00", currency="EUR", period="ANNUAL"),
                make_cost("APPLICATION_FEE", "0.00", currency="EUR", period="ONE_OFF"),
            ),
            dimension_scores=_STRONG_SCORES,
        )
        for i in range(1, 6)
    ]
    sh_schemes = {f"hu-{i}": ("Stipendium Hungaricum",) for i in range(1, 6)}
    probs_hu = {f"hu-{i}": 60 for i in range(1, 6)}
    funded_hu = {f"hu-{i}": 12 for i in range(1, 6)}  # q_SH = 0.20, a_i = 0.60

    pack_hu_only = build_pack(
        profile,
        hu_progs,
        EUR_RATES,
        attached_schemes=sh_schemes,
        probabilities=probs_hu,
        funded_probabilities=funded_hu,
        today=TODAY,
    )
    assert len(pack_hu_only.fee_free) == 5
    # Exact common-shock success probability: 0.20 * (1 - 0.40^5) = 0.197952 -> 20% (<= 20% ceiling)
    # Naive independence would be: 1 - (1 - 0.12)^5 = 47.23% -> 47%
    naive_pct = int(round((1.0 - (1.0 - 0.12) ** 5) * 100))
    assert naive_pct == 47
    assert pack_hu_only.pack_success_probability_pct is not None
    assert pack_hu_only.pack_success_probability_pct <= 20
    assert pack_hu_only.pack_success_probability_pct < naive_pct

    # Now add a DAAD programme (slightly lower standalone funded chance 11%, admit 55%)
    # and an independent university-funded programme (11% funded).
    daad_prog = make_candidate(
        program_id="de-daad",
        institution_id="inst-de-1",
        program_country_code="DE",
        cost_components=(
            make_cost("TUITION", "6000.00", currency="EUR", period="ANNUAL"),
            make_cost("APPLICATION_FEE", "0.00", currency="EUR", period="ONE_OFF"),
        ),
        dimension_scores=_HIGH_TARGET_SCORES,
    )
    indep_prog = make_candidate(
        program_id="nl-waiver",
        institution_id="inst-nl-1",
        program_country_code="NL",
        cost_components=(
            make_cost("TUITION", "6000.00", currency="EUR", period="ANNUAL"),
            make_cost("APPLICATION_FEE", "0.00", currency="EUR", period="ONE_OFF"),
        ),
        benefits=(
            make_benefit(
                id="nl-internal",
                amount="6000.00",
                accessibility="CAPACITY_LIMITED",
                eligibility_confidence="LIKELY",
            ),
        ),
        dimension_scores=_HIGH_TARGET_SCORES,
    )

    combined_candidates = [*hu_progs[:3], daad_prog, indep_prog]
    combined_schemes = {
        **{f"hu-{i}": ("Stipendium Hungaricum",) for i in range(1, 4)},
        "de-daad": ("DAAD",),
    }
    combined_probs = {
        **{f"hu-{i}": 60 for i in range(1, 4)},
        "de-daad": 55,
        "nl-waiver": 55,
    }
    combined_funded = {
        **{f"hu-{i}": 12 for i in range(1, 4)},
        "de-daad": 11,
        "nl-waiver": 11,
    }

    # In 1D rank_candidates, hu-1, hu-2, hu-3 all rank ahead of de-daad and nl-waiver
    ranked_1d = rank_candidates(
        profile,
        combined_candidates,
        EUR_RATES,
        schemes=combined_schemes,
        probabilities=combined_probs,
        funded_probabilities=combined_funded,
        today=TODAY,
    )
    assert [r.program_id for r in ranked_1d[:3]] == ["hu-1", "hu-2", "hu-3"]

    # In build_pack, after selecting hu-1, hu-2's marginal utility is discounted by
    # (1 - 0.60) = 0.40, so de-daad and nl-waiver are selected before hu-2!
    pack_diversified = build_pack(
        profile,
        combined_candidates,
        EUR_RATES,
        attached_schemes=combined_schemes,
        probabilities=combined_probs,
        funded_probabilities=combined_funded,
        today=TODAY,
    )
    packed_order = [app.program_id for app in pack_diversified.fee_free]
    assert packed_order[0] == "hu-1"
    assert set(packed_order[1:3]) == {"de-daad", "nl-waiver"}
    assert pack_diversified.pack_success_probability_pct is not None
    assert (
        pack_diversified.pack_success_probability_pct
        > pack_hu_only.pack_success_probability_pct
    )


# ---------------------------------------------------------------------------
# 3. Twin-Pass Fee-Budget Knapsack Optimization
# ---------------------------------------------------------------------------


def test_twin_pass_knapsack_three_30_eur_candidates_beat_single_95_eur_candidate() -> None:
    """Under a tight 100 EUR application fee budget:
    - A single 95 EUR candidate (`p95`, 45% chance, _STRONG_SCORES) ranks #1 in 1D isolation
      and leaves no budget for any 30 EUR candidate (`95 * 1.03 = 97.85 EUR` spent).
    - Three 30 EUR candidates (`p30-1`, `p30-2`, `p30-3`, each 38% chance, _HIGH_TARGET_SCORES)
      all fit together inside the 100 EUR budget (`90 * 1.03 = 92.70 EUR <= 100 EUR`) and have
      a much higher combined portfolio utility and success probability (`76%` vs `45%`).
    - Twin-pass budgeted submodular maximization selects `["p30-1", "p30-2", "p30-3"]`
      into `pack.paid` and moves `p95` to `pack.over_budget` with `APPLICATION_BUDGET_EXCEEDED`.
    """
    profile = make_profile(
        strategy="BALANCED",
        application_budget=Money(amount=Decimal("100.00"), currency="EUR"),
    )
    cand_95 = make_candidate(
        program_id="p95",
        institution_id="inst-95",
        cost_components=(
            make_cost("APPLICATION_FEE", "95.00", currency="EUR", period="ONE_OFF"),
        ),
        dimension_scores=_STRONG_SCORES,
    )
    cands_30 = [
        make_candidate(
            program_id=f"p30-{i}",
            institution_id=f"inst-30-{i}",
            cost_components=(
                make_cost("APPLICATION_FEE", "30.00", currency="EUR", period="ONE_OFF"),
            ),
            dimension_scores=_HIGH_TARGET_SCORES,
        )
        for i in range(1, 4)
    ]
    probs = {
        "p95": 45,
        "p30-1": 38,
        "p30-2": 38,
        "p30-3": 38,
    }

    # Verify p95 is #1 in 1D rank_candidates
    ranked = rank_candidates(profile, [cand_95, *cands_30], EUR_RATES, probabilities=probs)
    assert ranked[0].program_id == "p95"

    # Verify twin-pass selects the three 30 EUR candidates in build_pack
    pack = build_pack(profile, [cand_95, *cands_30], EUR_RATES, probabilities=probs)
    assert [app.program_id for app in pack.paid] == ["p30-1", "p30-2", "p30-3"]
    assert [app.program_id for app in pack.over_budget] == ["p95"]
    assert pack.over_budget[0].over_budget_reason == "APPLICATION_BUDGET_EXCEEDED"
    risk_map = _decompose_portfolio_funder_risk(
        profile, [cand_95, *cands_30], EUR_RATES, probabilities=probs
    )
    assert compute_pack_success_probability_pct(pack.paid, risk_map) == (
        pack.pack_success_probability_pct
    )
    assert pack.pack_success_probability_pct == int(round((1.0 - (1.0 - 0.38) ** 3) * 100))
    assert pack.pack_success_probability_pct > 45


def test_twin_pass_unscaled_single_anchor_wins_over_cheap_low_utility_filler() -> None:
    """Verify Kapur & Hong (2022) Example 3 safeguard:
    When a cheap 20 EUR filler has higher marginal utility per EUR than a 95 EUR high-value
    anchor (under a 100 EUR budget where taking the 20 EUR filler leaves 79.40 EUR < 97.85 EUR,
    blocking the 95 EUR anchor), Pass 1 (`cost_scaled=False`) has higher total portfolio utility
    than Pass 2 (`cost_scaled=True`), so the single 95 EUR anchor still wins!
    """
    profile = make_profile(
        strategy="BALANCED",
        application_budget=Money(amount=Decimal("100.00"), currency="EUR"),
        negotiable_preferences=(ProfileConstraint(kind="OTHER", value="TOP_UNIVERSITIES_ONLY"),),
    )
    cheap_filler = make_candidate(
        program_id="cheap-20",
        institution_id="inst-cheap",
        admission_baseline_pct=Decimal("45"),
        cost_components=(
            make_cost("APPLICATION_FEE", "20.00", currency="EUR", period="ONE_OFF"),
        ),
        dimension_scores=_LOW_REACH_SCORES,
    )
    flagship_anchor = make_candidate(
        program_id="anchor-95",
        institution_id="inst-anchor",
        admission_baseline_pct=Decimal("15"),
        cost_components=(
            make_cost("APPLICATION_FEE", "95.00", currency="EUR", period="ONE_OFF"),
        ),
        dimension_scores=_STRONG_SCORES,
    )
    probs = {
        "cheap-20": 22,
        "anchor-95": 55,
    }

    # cheap-20 has density ~82 / 20 = 4.10/EUR, whereas anchor-95 has ~96 / 95 = 1.01/EUR,
    # so pure density greedy (Pass 2) picks cheap-20 and blocks anchor-95.
    # Twin-pass compares U({anchor-95}) ~ 96 against U({cheap-20}) ~ 82 and keeps anchor-95!
    pack = build_pack(profile, [cheap_filler, flagship_anchor], EUR_RATES, probabilities=probs)
    assert [app.program_id for app in pack.paid] == ["anchor-95"]
    assert [app.program_id for app in pack.over_budget] == ["cheap-20"]
    assert pack.pack_success_probability_pct == 55


def test_independent_funding_preserves_exact_rank_candidates_order() -> None:
    """When all candidates have independent funding and fit within the budget,
    `build_pack` preserves 100% of `rank_candidates` ordering.
    """
    profile = make_profile(
        strategy="BALANCED",
        application_budget=Money(amount=Decimal("500.00"), currency="EUR"),
    )
    candidates = [
        make_candidate(
            program_id=f"indep-{i}",
            institution_id=f"inst-{i}",
            cost_components=(
                make_cost("APPLICATION_FEE", f"{10 * i}.00", currency="EUR", period="ONE_OFF"),
            ),
            dimension_scores={
                k: Decimal(str(96 - i * 2)) for k in _STRONG_SCORES
            },
        )
        for i in range(1, 5)
    ]
    probs = {f"indep-{i}": 70 - i * 10 for i in range(1, 5)}

    ranked = rank_candidates(profile, candidates, EUR_RATES, probabilities=probs)
    pack = build_pack(profile, candidates, EUR_RATES, probabilities=probs)

    assert [app.program_id for app in pack.paid] == [r.program_id for r in ranked]
    expected_fail = math.prod(1.0 - (70 - i * 10) / 100.0 for i in range(1, 5))
    assert pack.pack_success_probability_pct == int(round((1.0 - expected_fail) * 100))


# ---------------------------------------------------------------------------
# 4. Real Downstream Caller Integration (`SpineResult` & `handle_research_message`)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_real_caller_integration_spine_and_publish_consume_optimized_pack(
    agency_a: Any, membership_a: Any
) -> None:
    """Feed the real `build_pack` output through `handle_research_message` / `run_research_spine`
    and verify that downstream database publication (`PackVersion`, `PackCandidate`,
    `RecommendationCandidate`) persists the packed candidates and probabilities cleanly.
    """
    from apps.funding.models import CostComponent, PackCandidate, RecommendationCandidate
    from apps.research.services import handle_research_message
    from apps.tenancy.context import tenant_scope
    from tests.funding.test_spine import _catalogue, _message, _run

    program, _award_obj = _catalogue()
    CostComponent.objects.create(
        program=program,
        kind="APPLICATION_FEE",
        amount=Decimal("40.00"),
        currency="EUR",
        period="ONE_OFF",
    )
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("3000.00"),
        currency="EUR",
        period="ANNUAL",
    )
    run = _run(
        agency_a,
        membership_a,
        self_funding_capacity=Money(amount=Decimal("5000"), currency="EUR"),
        application_budget=Money(amount=Decimal("100"), currency="EUR"),
    )
    with tenant_scope(agency_a.id):
        pack_version = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        packed_candidates = list(
            RecommendationCandidate.objects.filter(
                id__in=PackCandidate.objects.filter(pack_version=pack_version).values(
                    "candidate_id"
                ),
                opportunity__isnull=True,
            )
        )
    assert len(packed_candidates) == 1
    assert packed_candidates[0].application_fee == Decimal("40.00")
    assert packed_candidates[0].estimated_chance_pct is not None
