from datetime import date
from decimal import Decimal

from apps.funding.pack import build_pack, rank_candidates
from tests.funding.conftest import (
    EUR_RATES,
    make_applicant_condition,
    make_benefit,
    make_candidate,
    make_cost,
    make_profile,
    make_return_service,
)

_STRONG_SCORES = {
    "ACADEMIC_FIT": Decimal("95"),
    "PROGRAM_FIT": Decimal("95"),
    "CAREER_FIT": Decimal("95"),
    "DURATION": Decimal("95"),
    "MOBILITY_FIT": Decimal("95"),
    "RESEARCH_FIT": Decimal("95"),
}
_WEAK_SCORES = {
    "ACADEMIC_FIT": Decimal("65"),
    "PROGRAM_FIT": Decimal("65"),
    "CAREER_FIT": Decimal("65"),
    "DURATION": Decimal("65"),
    "MOBILITY_FIT": Decimal("65"),
    "RESEARCH_FIT": Decimal("65"),
}
# Still clears the balanced 80/100 overall and 60/100 critical-dimension bar, unlike
# _WEAK_SCORES, so both candidates in the descending-order test stay ELIGIBLE.
_MODEST_SCORES = {
    "ACADEMIC_FIT": Decimal("85"),
    "PROGRAM_FIT": Decimal("85"),
    "CAREER_FIT": Decimal("85"),
    "DURATION": Decimal("85"),
    "MOBILITY_FIT": Decimal("85"),
    "RESEARCH_FIT": Decimal("85"),
}


def test_balanced_ranking_orders_candidates_by_overall_score_descending() -> None:
    profile = make_profile(strategy="BALANCED")
    strong = make_candidate(
        program_id="strong", cost_components=(), dimension_scores=_STRONG_SCORES
    )
    weak = make_candidate(program_id="weak", cost_components=(), dimension_scores=_MODEST_SCORES)

    ranked = rank_candidates(profile, [weak, strong], EUR_RATES)

    assert [candidate.program_id for candidate in ranked] == ["strong", "weak"]


def test_funding_first_can_beat_better_fit_but_unaffordable() -> None:
    # MANDATORY never carries a capacity: the questionnaire drops the answer
    # (apps/accounts/consultation.py). The default 10,000 a year would pay the
    # 9,000 gap and make the "unaffordable" one affordable.
    profile = make_profile(
        strategy="FUNDING_FIRST", funding_dependency="MANDATORY", self_funding_capacity=None
    )
    better_fit = make_candidate(
        program_id="better_fit",
        cost_components=(make_cost("TUITION", "9000.00"),),
        benefits=(make_benefit(amount="0.00", currency="EUR"),),
        dimension_scores=_STRONG_SCORES,
    )
    fully_funded = make_candidate(
        program_id="fully_funded",
        cost_components=(make_cost("TUITION", "9000.00"),),
        benefits=(make_benefit(amount="9000.00"),),
        dimension_scores=_WEAK_SCORES,
    )

    ranked = rank_candidates(profile, [better_fit, fully_funded], EUR_RATES)

    assert ranked[0].program_id == "fully_funded"
    assert "weaker fit" in " ".join(ranked[0].tradeoffs)


def test_funding_first_ranks_on_what_the_student_cannot_pay_themselves() -> None:
    """Both gaps fit inside 10,000 a year, so neither leaves anything to find
    and the better fit comes first -- a funding gap the family covers is not a
    reason to rank a programme down."""
    profile = make_profile(strategy="FUNDING_FIRST", funding_dependency="IMPORTANT")
    better_fit = make_candidate(
        program_id="better_fit",
        cost_components=(make_cost("TUITION", "9000.00"),),
        benefits=(make_benefit(amount="0.00", currency="EUR"),),
        dimension_scores=_STRONG_SCORES,
    )
    fully_funded = make_candidate(
        program_id="fully_funded",
        cost_components=(make_cost("TUITION", "9000.00"),),
        benefits=(make_benefit(amount="9000.00"),),
        dimension_scores=_WEAK_SCORES,
    )

    ranked = rank_candidates(profile, [fully_funded, better_fit], EUR_RATES)

    assert [r.program_id for r in ranked] == ["better_fit", "fully_funded"]


def test_research_fit_dimension_is_excluded_and_redistributed_without_research_interests() -> None:
    profile = make_profile(strategy="BALANCED", research_interests=())
    candidate = make_candidate(cost_components=())

    ranked = rank_candidates(profile, [candidate], EUR_RATES)

    assert ranked[0].scores is not None
    assert "RESEARCH_FIT" not in {score.dimension for score in ranked[0].scores.dimensions}


def test_mobility_fit_dimension_is_included_only_with_mobility_priorities() -> None:
    profile_without = make_profile(strategy="BALANCED", mobility_priorities=())
    profile_with = make_profile(strategy="BALANCED", mobility_priorities=("Public transport",))
    candidate = make_candidate(cost_components=())

    ranked_without = rank_candidates(profile_without, [candidate], EUR_RATES)
    ranked_with = rank_candidates(profile_with, [candidate], EUR_RATES)

    assert ranked_without[0].scores is not None
    assert "MOBILITY_FIT" not in {score.dimension for score in ranked_without[0].scores.dimensions}
    assert sum(d.weight for d in ranked_without[0].scores.dimensions) == Decimal("1")

    assert ranked_with[0].scores is not None
    assert "MOBILITY_FIT" in {score.dimension for score in ranked_with[0].scores.dimensions}
    assert sum(d.weight for d in ranked_with[0].scores.dimensions) == Decimal("1")


def test_pack_includes_every_fee_free_fully_funded_funding_first_candidate() -> None:
    profile = make_profile(
        strategy="FUNDING_FIRST",
        funding_dependency="MANDATORY",
        application_budget={"amount": Decimal("0.00"), "currency": "USD"},
    )
    # A stated 0.00 fee: since 2026-10-24 a programme stating NO fee is "fee not
    # known", its own capped group, never fee-free.
    fee_free = make_candidate(
        program_id="fee-free-1",
        cost_components=(
            make_cost("TUITION", "5000.00"),
            make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),
        ),
        benefits=(make_benefit(amount="5000.00"),),
    )

    pack = build_pack(profile, [fee_free], EUR_RATES)

    assert [item.program_id for item in pack.fee_free] == ["fee-free-1"]
    assert pack.paid == ()


def test_pack_adds_paid_candidates_in_priority_order_within_budget() -> None:
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("150.00"), "currency": "USD"},
    )
    first = make_candidate(
        program_id="first",
        cost_components=(make_cost("APPLICATION_FEE", "100.00", currency="USD", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    second = make_candidate(
        program_id="second",
        cost_components=(make_cost("APPLICATION_FEE", "80.00", currency="USD", period="ONE_OFF"),),
        dimension_scores=_WEAK_SCORES,
    )

    pack = build_pack(profile, [second, first], EUR_RATES)

    assert [item.program_id for item in pack.paid] == ["first"]
    assert any(excluded.program_id == "second" for excluded in pack.excluded)


def test_pack_orders_scholarship_decision_before_university_fee_when_safe() -> None:
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("200.00"), "currency": "USD"},
    )
    candidate = make_candidate(
        program_id="scholarship-first",
        application_deadline=date(2027, 6, 1),
        scholarship_decision_deadline=date(2027, 3, 1),
        cost_components=(make_cost("APPLICATION_FEE", "100.00", currency="USD", period="ONE_OFF"),),
    )

    pack = build_pack(profile, [candidate], EUR_RATES)

    assert pack.paid[0].ordering == "SCHOLARSHIP_FIRST"


def test_pack_uses_parallel_or_university_first_when_scholarship_timing_is_not_safely_earlier() -> (
    None
):
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("200.00"), "currency": "USD"},
    )
    candidate = make_candidate(
        program_id="no-safe-order",
        application_deadline=date(2027, 3, 1),
        scholarship_decision_deadline=None,
        cost_components=(make_cost("APPLICATION_FEE", "100.00", currency="USD", period="ONE_OFF"),),
    )

    pack = build_pack(profile, [candidate], EUR_RATES)

    assert pack.paid[0].ordering == "PARALLEL_OR_UNIVERSITY_FIRST"


def test_the_application_fee_stays_in_the_destination_currency() -> None:
    # strategy=FUNDING_FIRST: BALANCED's overall>=80/critical>=60 eligibility bar would
    # reject this candidate on an unaffordable AFFORDABILITY score of 0 before the
    # currency assertion below is ever reached; FUNDING_FIRST has no such bar (see
    # evaluate()), isolating this test to the fee-currency behavior under test.
    profile = make_profile(country_of_residence="AZ", strategy="FUNDING_FIRST")
    candidate = make_candidate(
        cost_components=(
            make_cost("TUITION", "10000.00", currency="EUR"),
            # USD, not the EUR base of EUR_RATES: a fee converted into the comparison
            # currency would read 69.12 EUR here, understating what is actually payable.
            make_cost("APPLICATION_FEE", "75.00", currency="USD", period="ONE_OFF"),
        ),
    )

    ranked = rank_candidates(profile, [candidate], EUR_RATES)

    assert ranked[0].affordability.application_fee == Decimal("75.00")
    assert ranked[0].affordability.application_fee_currency == "USD"
    assert ranked[0].affordability.currency == "EUR"


def test_the_application_budget_is_converted_before_it_is_compared_to_a_fee() -> None:
    # 100.00 USD is 92.17 EUR against EUR_RATES, so a 95.00 EUR fee does not fit the
    # budget. Comparing the raw 100.00 USD figure against 95.00 EUR would wrongly admit it.
    profile = make_profile(application_budget={"amount": Decimal("100.00"), "currency": "USD"})
    candidate = make_candidate(
        program_id="just-over-budget",
        cost_components=(make_cost("APPLICATION_FEE", "95.00", currency="EUR", period="ONE_OFF"),),
    )

    pack = build_pack(profile, [candidate], EUR_RATES)

    assert pack.paid == ()
    assert [item.reason_code for item in pack.excluded] == ["APPLICATION_BUDGET_EXCEEDED"]


def test_pack_retains_ineligible_candidates_for_internal_review_with_reason_codes() -> None:
    profile = make_profile(strategy="BALANCED", acceptable_teaching_languages=("English",))
    ineligible = make_candidate(program_id="ineligible", teaching_languages=("German",))

    pack = build_pack(profile, [ineligible], EUR_RATES)

    assert pack.fee_free == ()
    assert pack.paid == ()
    assert len(pack.excluded) == 1
    assert pack.excluded[0].program_id == "ineligible"
    assert pack.excluded[0].reasons


def test_a_bonded_award_is_disclosed_to_the_student() -> None:
    """ADB-JSP, Bolashak and YLSY all bind the graduate to return home. A bonded award
    is a materially different product from an unbonded one and the student must be
    told which they are accepting."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="bolashak"),),
        return_service=(
            make_return_service(
                benefit_id="bolashak",
                months=60,
                rule_text="graduates must work in Kazakhstan for five years",
            ),
        ),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    assert len(ranked) == 1
    disclosure = " ".join(ranked[0].tradeoffs)
    assert "bolashak" in disclosure
    assert "60 months" in disclosure
    assert "work in Kazakhstan for five years" in disclosure


def test_return_service_never_excludes_a_candidate() -> None:
    profile = make_profile(funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(make_benefit(id="bolashak"),),
        return_service=(make_return_service(benefit_id="bolashak"),),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    assert len(ranked) == 1


def test_a_route_closed_by_a_condition_is_named_even_when_the_candidate_survives() -> None:
    """The candidate stays in the pack on another route, but the student should still
    learn that the scheme they had heard of is shut, and on what bar."""
    profile = make_profile(experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"), make_benefit(id="open-scheme")),
        applicant_conditions=(
            make_applicant_condition(
                benefit_id="adb-jsp",
                rule_text="at least two years of full-time professional work experience",
            ),
        ),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    disclosure = " ".join(ranked[0].tradeoffs)
    assert "adb-jsp" in disclosure
    assert "two years of full-time professional work experience" in disclosure


def test_return_service_on_an_inapplicable_route_is_not_disclosed() -> None:
    """Disclosing a bond attached to a scheme the student cannot use is a false
    warning, and it would push them off a candidate that carries no bond at all."""
    profile = make_profile()
    candidate = make_candidate(
        program_country_code="DE",
        benefits=(make_benefit(id="fr-only", scope_type="COUNTRY", country_code="FR"),),
        return_service=(make_return_service(benefit_id="fr-only"),),
    )

    ranked = rank_candidates(profile, (candidate,), EUR_RATES)

    assert not any("fr-only" in tradeoff for tradeoff in ranked[0].tradeoffs)


def test_a_fee_fits_only_with_three_percent_left_for_bank_charges() -> None:
    """Spec §7.6: a fee that fits only at the exact rate "may not fit". 100 USD
    is 92.17 EUR; 97 USD is 89.40 EUR and 92.08 with the margin, which fits;
    98 USD is 90.32 EUR and 93.03 with it, which does not."""
    profile = make_profile(application_budget={"amount": Decimal("100.00"), "currency": "USD"})
    fits = make_candidate(
        program_id="fits",
        cost_components=(make_cost("APPLICATION_FEE", "97.00", currency="USD", period="ONE_OFF"),),
    )
    tight = make_candidate(
        program_id="tight",
        cost_components=(make_cost("APPLICATION_FEE", "98.00", currency="USD", period="ONE_OFF"),),
    )

    assert [item.program_id for item in build_pack(profile, [fits], EUR_RATES).paid] == ["fits"]
    pack = build_pack(profile, [tight], EUR_RATES)
    assert pack.paid == ()
    assert [item.program_id for item in pack.over_budget] == ["tight"]
    assert [item.reason_code for item in pack.excluded] == ["APPLICATION_BUDGET_EXCEEDED"]


def test_the_budget_is_spent_at_the_plain_fee_not_the_margin() -> None:
    """The margin is a check, not a charge. 300 USD is 276.50 EUR; the first fee
    (97 USD, 89.40 EUR) leaves 187.10, and 180 EUR needs 185.40 with its
    margin. Spending the margin too would have left 184.42 and refused it."""
    profile = make_profile(
        strategy="FUNDING_FIRST",
        application_budget={"amount": Decimal("300.00"), "currency": "USD"},
    )
    first = make_candidate(
        program_id="first",
        cost_components=(make_cost("APPLICATION_FEE", "97.00", currency="USD", period="ONE_OFF"),),
    )
    second = make_candidate(
        program_id="second",
        cost_components=(make_cost("APPLICATION_FEE", "180.00", currency="EUR", period="ONE_OFF"),),
    )

    pack = build_pack(profile, [first, second], EUR_RATES)

    assert [item.program_id for item in pack.paid] == ["first", "second"]


def test_every_ranked_programme_carries_its_place_and_whether_its_fee_is_known() -> None:
    profile = make_profile(strategy="FUNDING_FIRST")
    stated = make_candidate(
        program_id="stated",
        cost_components=(make_cost("APPLICATION_FEE", "50.00", period="ONE_OFF"),),
    )
    silent = make_candidate(program_id="silent", cost_components=())

    pack = build_pack(profile, [stated, silent], EUR_RATES)

    assert [(i.program_id, i.rank, i.fee_known) for i in pack.paid] == [("stated", 1, True)]
    # A programme stating no fee is in its own group, never among the fee-free.
    assert pack.fee_free == ()
    assert [(i.program_id, i.rank, i.fee_known) for i in pack.fee_not_known] == [
        ("silent", 2, False)
    ]


def test_funding_first_orders_guaranteed_zero_gap_before_selective_and_unclosed_gap() -> None:
    profile = make_profile(
        strategy="FUNDING_FIRST",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    guaranteed = make_candidate(
        program_id="guaranteed",
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(make_benefit(id="auto-full", amount="10000.00", accessibility="ORDINARY"),),
    )
    selective = make_candidate(
        program_id="selective",
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(
            make_benefit(id="sel-full", amount="10000.00", accessibility="CAPACITY_LIMITED"),
        ),
    )
    unclosed = make_candidate(
        program_id="unclosed",
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(make_benefit(id="auto-part", amount="4000.00", accessibility="ORDINARY"),),
    )

    ranked = rank_candidates(profile, [unclosed, selective, guaranteed], EUR_RATES)

    assert [r.program_id for r in ranked] == ["guaranteed", "selective", "unclosed"]


def test_return_bond_penalizes_ranking_and_discloses_conflict_with_work_abroad() -> None:
    profile = make_profile(strategy="BALANCED", career_intent="WORK_ABROAD")
    bonded = make_candidate(
        program_id="bonded",
        cost_components=(),
        benefits=(make_benefit(id="bolashak"),),
        return_service=(
            make_return_service(
                benefit_id="bolashak",
                months=36,
                rule_text="must return home for 3 years",
            ),
        ),
    )
    unbonded = make_candidate(
        program_id="unbonded",
        cost_components=(),
        benefits=(make_benefit(id="free-grant"),),
    )

    ranked = rank_candidates(profile, [bonded, unbonded], EUR_RATES)

    assert [r.program_id for r in ranked] == ["unbonded", "bonded"]
    assert any("work abroad" in t for t in ranked[1].tradeoffs)


def test_portfolio_anti_lottery_guard_reserves_budget_for_target_anchor_over_reach_bet() -> None:
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("100.00"), "currency": "EUR"},
    )
    reach_prog = make_candidate(
        program_id="reach",
        institution_id="inst-1",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    target_prog = make_candidate(
        program_id="target",
        institution_id="inst-2",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_MODEST_SCORES,
    )
    probs = {
        "reach": 10,
        "target": 40,
    }

    pack = build_pack(profile, [reach_prog, target_prog], EUR_RATES, probabilities=probs)

    assert [p.program_id for p in pack.paid] == ["target"]
    assert pack.paid[0].risk_tier == "TARGET"
    assert [p.program_id for p in pack.over_budget] == ["reach"]
    assert pack.over_budget[0].risk_tier == "REACH"


def test_institution_diversity_cap_limits_single_university_across_multiple_institutions() -> None:
    profile = make_profile(strategy="FUNDING_FIRST")
    inst_a_1 = make_candidate(
        program_id="a1",
        institution_id="inst-a",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
    )
    inst_a_2 = make_candidate(
        program_id="a2",
        institution_id="inst-a",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
    )
    inst_a_3 = make_candidate(
        program_id="a3",
        institution_id="inst-a",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
    )
    inst_b_1 = make_candidate(
        program_id="b1",
        institution_id="inst-b",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
    )

    pack = build_pack(profile, [inst_a_1, inst_a_2, inst_a_3, inst_b_1], EUR_RATES)

    assert [p.program_id for p in pack.fee_free] == ["a1", "a2", "b1"]
    assert [p.program_id for p in pack.over_budget] == ["a3"]
    assert any("same institution" in t for t in pack.over_budget[0].tradeoffs)


def test_below_fit_bar_candidates_surface_in_over_budget_when_pack_has_active_programme() -> None:
    profile = make_profile(strategy="BALANCED")
    strong = make_candidate(
        program_id="strong",
        institution_id="inst-1",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    below_bar = make_candidate(
        program_id="below_bar",
        institution_id="inst-2",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
        dimension_scores=_WEAK_SCORES,
    )

    pack = build_pack(profile, [strong, below_bar], EUR_RATES)

    assert [p.program_id for p in pack.fee_free] == ["strong"]
    assert [p.program_id for p in pack.over_budget] == ["below_bar"]
    assert pack.over_budget[0].over_budget_reason == "ELIGIBLE_BELOW_FIT_BAR"
    assert any("80" in t for t in pack.over_budget[0].tradeoffs)


def test_stripped_undecidable_route_excluded_from_gap_closing_and_rescued_by_scheme() -> None:
    profile = make_profile(
        strategy="FUNDING_FIRST",
        career_intent="WORK_ABROAD",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    undecidable_bonded = make_benefit(
        id="undecidable-bonded",
        amount="20000.00",
        accessibility="CAPACITY_LIMITED",
    )
    prog = make_candidate(
        program_id="prog-rescued",
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(undecidable_bonded,),
        applicant_conditions=(
            make_applicant_condition(
                "MEANS_TEST",
                benefit_id="undecidable-bonded",
                comparable_value=None,
                rule_text="Household income below threshold",
            ),
        ),
        return_service=(make_return_service(benefit_id="undecidable-bonded", months=24),),
    )

    ranked = rank_candidates(
        profile,
        [prog],
        EUR_RATES,
        schemes={"prog-rescued": ("DAAD Full Scholarship",)},
    )

    assert len(ranked) == 1
    assert ranked[0].program_id == "prog-rescued"
    assert not any("work abroad" in t for t in ranked[0].tradeoffs)

    pack = build_pack(
        profile,
        [prog],
        EUR_RATES,
        attached_schemes={"prog-rescued": ("DAAD Full Scholarship",)},
    )
    assert len(pack.fee_not_known) == 1
    assert pack.fee_not_known[0].winnable_with == ("DAAD Full Scholarship",)
    assert not any("work abroad" in t for t in pack.fee_not_known[0].tradeoffs)


def test_anti_lottery_lookahead_skips_institution_capped_anchor_and_discloses_tradeoff() -> None:
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("100.00"), "currency": "EUR"},
    )
    inst_a_free_1 = make_candidate(
        program_id="a-free-1",
        institution_id="inst-a",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    inst_a_free_2 = make_candidate(
        program_id="a-free-2",
        institution_id="inst-a",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    reach_prog = make_candidate(
        program_id="reach-b",
        institution_id="inst-b",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    capped_target = make_candidate(
        program_id="target-a3",
        institution_id="inst-a",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_MODEST_SCORES,
    )
    probs = {
        "a-free-1": 10,
        "a-free-2": 10,
        "reach-b": 10,
        "target-a3": 45,
    }

    # Because target-a3 is at inst-a (which already has 2 programmes in the pack),
    # reach-b is NOT skipped for target-a3.
    pack = build_pack(
        profile,
        [inst_a_free_1, inst_a_free_2, reach_prog, capped_target],
        EUR_RATES,
        probabilities=probs,
    )
    assert [p.program_id for p in pack.paid] == ["reach-b"]

    # When the target anchor is at an uncapped institution (inst-c), reach-b IS reserved
    # and carries the ANCHOR_BUDGET_RESERVED reason + tradeoff disclosure.
    uncapped_target = capped_target.model_copy(
        update={"program_id": "target-c1", "institution_id": "inst-c"}
    )
    probs["target-c1"] = 45
    pack2 = build_pack(
        profile,
        [inst_a_free_1, inst_a_free_2, reach_prog, uncapped_target],
        EUR_RATES,
        probabilities=probs,
    )
    assert [p.program_id for p in pack2.paid] == ["target-c1"]
    reach_over = next(p for p in pack2.over_budget if p.program_id == "reach-b")
    assert reach_over.over_budget_reason == "ANCHOR_BUDGET_RESERVED"
    assert any("higher-probability target or safety" in t for t in reach_over.tradeoffs)


def test_coursework_warning_penalizes_effective_score_on_tie() -> None:
    profile = make_profile(strategy="BALANCED")
    clean = make_candidate(
        program_id="clean",
        cost_components=(),
        benefits=(make_benefit(id="b1"),),
    )
    warned = make_candidate(
        program_id="warned",
        cost_components=(),
        benefits=(make_benefit(id="b2"),),
    )

    ranked = rank_candidates(
        profile,
        [warned, clean],
        EUR_RATES,
        coursework_warnings={"warned": ("Coursework prerequisite check needed",)},
    )

    assert [r.program_id for r in ranked] == ["clean", "warned"]


def test_anti_lottery_lookahead_skips_overflowing_fnk_and_recognizes_20pct_target() -> None:
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("100.00"), "currency": "EUR"},
    )
    fnk_1 = make_candidate(
        program_id="fnk-1",
        institution_id="inst-1",
        cost_components=(),
        dimension_scores=_STRONG_SCORES,
    )
    fnk_2 = make_candidate(
        program_id="fnk-2",
        institution_id="inst-2",
        cost_components=(),
        dimension_scores=_STRONG_SCORES,
    )
    fnk_3 = make_candidate(
        program_id="fnk-3",
        institution_id="inst-3",
        cost_components=(),
        dimension_scores=_STRONG_SCORES,
    )
    reach_paid = make_candidate(
        program_id="reach-paid",
        institution_id="inst-4",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    fnk_4_overflow = make_candidate(
        program_id="fnk-4",
        institution_id="inst-5",
        cost_components=(),
        dimension_scores=_MODEST_SCORES,
    )
    target_22pct = make_candidate(
        program_id="target-22",
        institution_id="inst-6",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_MODEST_SCORES,
    )
    probs = {
        "fnk-1": 10,
        "fnk-2": 10,
        "fnk-3": 10,
        "reach-paid": 10,
        "fnk-4": 45,
        "target-22": 22,
    }

    pack = build_pack(
        profile,
        [fnk_1, fnk_2, fnk_3, reach_paid, fnk_4_overflow, target_22pct],
        EUR_RATES,
        probabilities=probs,
    )

    # fnk-4 overflows MAX_FEE_NOT_KNOWN=3, so lookahead continues past fnk-4 and reserves
    # budget for target-22 (22% TARGET tier).
    assert [p.program_id for p in pack.paid] == ["target-22"]
    assert pack.paid[0].risk_tier == "TARGET"


def test_rank_candidates_differentiates_mild_bridge_warning_from_hard_warning() -> None:
    profile = make_profile(strategy="BALANCED")
    hard_warned = make_candidate(program_id="hard-warned", dimension_scores=_STRONG_SCORES)
    mild_bridge = make_candidate(program_id="mild-bridge", dimension_scores=_STRONG_SCORES)
    clean = make_candidate(program_id="clean", dimension_scores=_STRONG_SCORES)

    ranked = rank_candidates(
        profile,
        [hard_warned, mild_bridge, clean],
        EUR_RATES,
        coursework_warnings={
            "hard-warned": ("Coursework prerequisite check needed: verify credits",),
            "mild-bridge": (
                "Coursework prerequisites may require conditional bridge modules or "
                "transcript verification",
            ),
        },
    )

    assert [r.program_id for r in ranked] == ["clean", "mild-bridge", "hard-warned"]


def test_rank_candidates_deduplicates_identical_tradeoffs_across_benefits() -> None:
    profile = make_profile(strategy="BALANCED", career_intent="WORK_ABROAD")
    cand = make_candidate(
        program_id="dup-bonds",
        dimension_scores=_STRONG_SCORES,
        benefits=(make_benefit(id="b1"), make_benefit(id="b2")),
        return_service=(
            make_return_service(
                benefit_id="b1",
                months=36,
                rule_text="must return home for 3 years",
            ),
            make_return_service(
                benefit_id="b2",
                months=36,
                rule_text="must return home for 3 years",
            ),
        ),
    )

    ranked = rank_candidates(
        profile,
        [cand],
        EUR_RATES,
        coursework_warnings={
            "dup-bonds": (
                "Portfolio required: submit portfolio",
                "Portfolio required: submit portfolio",
            )
        },
    )

    assert len(ranked[0].tradeoffs) == len(set(ranked[0].tradeoffs))


def test_anti_lottery_lookahead_does_not_reserve_when_active_slots_exhausted() -> None:
    profile = make_profile(
        strategy="BALANCED",
        application_budget={"amount": Decimal("100.00"), "currency": "EUR"},
    )
    reach_paid = make_candidate(
        program_id="reach-paid",
        institution_id="inst-reach",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=_STRONG_SCORES,
    )
    # 10 fee-free REACH programmes ranked between reach_paid and target_paid will fill all
    # MAX_ACTIVE_PROGRAMS=10 slots before target_paid is ever reached.
    free_reaches = [
        make_candidate(
            program_id=f"free-reach-{i}",
            institution_id=f"inst-free-{i}",
            cost_components=(
                make_cost("APPLICATION_FEE", "0.00", currency="EUR", period="ONE_OFF"),
            ),
        )
        for i in range(10)
    ]
    target_paid = make_candidate(
        program_id="target-paid",
        institution_id="inst-target",
        cost_components=(make_cost("APPLICATION_FEE", "60.00", currency="EUR", period="ONE_OFF"),),
        dimension_scores=dict.fromkeys(_STRONG_SCORES, Decimal("80")),
    )
    probs = {
        "reach-paid": 15,
        **{f"free-reach-{i}": 15 for i in range(10)},
        "target-paid": 40,
    }

    pack = build_pack(
        profile,
        [reach_paid, *free_reaches, target_paid],
        EUR_RATES,
        probabilities=probs,
    )

    assert [p.program_id for p in pack.paid] == ["reach-paid"]


def test_unconstrained_self_funded_and_top_universities_only_priorities() -> None:
    from apps.accounts.schemas import ProfileConstraint
    from apps.funding.evaluation import AwardCandidateFacts, applicable_dimensions, evaluate
    from apps.funding.validity import Evidence

    # 1. Unconstrained OPTIONAL self-funding omits AFFORDABILITY and never fails high-tuition bars
    profile = make_profile(
        funding_dependency="OPTIONAL",
        self_funding_capacity=None,
        strategy="BALANCED",
        application_budget={"amount": Decimal("100.00"), "currency": "EUR"},
        non_negotiables=(ProfileConstraint(kind="OTHER", value="TOP_UNIVERSITIES_ONLY"),),
        negotiable_preferences=(
            ProfileConstraint(kind="OTHER", value="NO_FUNDING_NEEDED"),
            ProfileConstraint(kind="OTHER", value="NO_RETURN_BOND"),
        ),
    )
    assert "AFFORDABILITY" not in applicable_dimensions(profile)

    expensive_flagship = make_candidate(
        program_id="flagship-reach",
        institution_id="inst-flagship",
        cost_components=(
            make_cost("TUITION", "45000.00", currency="EUR", period="ANNUAL"),
            make_cost("APPLICATION_FEE", "75.00", currency="EUR", period="ONE_OFF"),
        ),
        dimension_scores=_STRONG_SCORES,
    )
    open_entry_safety = make_candidate(
        program_id="open-safety",
        institution_id="inst-safety",
        cost_components=(
            make_cost("TUITION", "2000.00", currency="EUR", period="ANNUAL"),
            make_cost("APPLICATION_FEE", "75.00", currency="EUR", period="ONE_OFF"),
        ),
        dimension_scores=_STRONG_SCORES,
    )
    assert evaluate(profile, expensive_flagship, EUR_RATES).outcome == "ELIGIBLE"

    # 2. TOP_UNIVERSITIES_ONLY ranks selective flagship (15% REACH) above open-entry (70% SAFETY)
    # and does NOT demote the flagship via reserve_for_anchor; NO_FUNDING_NEEDED skips awards.
    holder_award = AwardCandidateFacts(
        award_id="aw-1",
        name="National Scholarship",
        holder_name="Foundation",
        organisation_id="org-1",
        money_form="GRANT",
        route="SEPARATE_APPLICATION",
        unconfirmed=(),
        benefits=(make_benefit(id="b-aw", amount="10000.00"),),
        applicant_conditions=(),
        return_service=(),
        evidence_confidence="HIGH",
        evidence=Evidence(applies_to="2027", deadline=date(2027, 3, 1)),
        coverage_is_unstated=False,
    )
    pack = build_pack(
        profile,
        [open_entry_safety, expensive_flagship],
        EUR_RATES,
        awards=(holder_award,),
        probabilities={"flagship-reach": 15, "open-safety": 70},
    )
    assert [p.program_id for p in pack.paid] == ["flagship-reach"]
    assert pack.awards == ()

    # 3. OB11 & RB1: TOP_UNIVERSITIES_ONLY under FUNDING_FIRST enforces fit bars (>=80)
    # and ranks selective candidate + winnable scholarship ahead of low-tier guaranteed waiver
    from apps.funding.probability import is_selective_candidate

    funding_first_top_profile = make_profile(
        funding_dependency="MANDATORY",
        strategy="FUNDING_FIRST",
        non_negotiables=(ProfileConstraint(kind="OTHER", value="TOP_UNIVERSITIES_ONLY"),),
    )
    weak_fit_waiver = make_candidate(
        program_id="weak-waiver",
        institution_id="inst-local",
        cost_components=(make_cost("TUITION", "5000.00", currency="EUR", period="ANNUAL"),),
        benefits=(make_benefit(id="b-waiver", amount="5000.00", accessibility="ORDINARY"),),
        dimension_scores={**_STRONG_SCORES, "ACADEMIC_FIT": Decimal("65")},
    )
    assert not is_selective_candidate(weak_fit_waiver)
    assert (
        evaluate(funding_first_top_profile, weak_fit_waiver, EUR_RATES).outcome
        == "ELIGIBLE_BELOW_FIT_BAR"
    )

    low_tier_waiver = make_candidate(
        program_id="low-tier-waiver",
        institution_id="inst-regional",
        cost_components=(make_cost("TUITION", "5000.00", currency="EUR", period="ANNUAL"),),
        benefits=(make_benefit(id="b-waiver-2", amount="5000.00", accessibility="ORDINARY"),),
        dimension_scores=_STRONG_SCORES,
    )
    flagship_selective = make_candidate(
        program_id="eth-selective",
        institution_id="ethz",
        cost_components=(make_cost("TUITION", "15000.00", currency="EUR", period="ANNUAL"),),
        benefits=(
            make_benefit(
                id="b-esop",
                amount="15000.00",
                accessibility="CAPACITY_LIMITED",
            ),
        ),
        dimension_scores=_STRONG_SCORES,
    )
    assert is_selective_candidate(flagship_selective)
    ranked_top = rank_candidates(
        funding_first_top_profile,
        [low_tier_waiver, flagship_selective],
        EUR_RATES,
        probabilities={"low-tier-waiver": 65, "eth-selective": 18},
    )
    assert [r.program_id for r in ranked_top] == ["eth-selective", "low-tier-waiver"]

    # 4. P3-B2: Dynamic selectivity detection (`is_selective_candidate`) recognizes
    # research/competency/GPA/selective-benefit programmes without hardcoded domain lists
    high_gpa_candidate = make_candidate(
        program_id="high-gpa-prog",
        applicant_conditions=(
            make_applicant_condition(
                "PRIOR_DEGREE_GRADE",
                value="3.5/4.0",
                rule_text="Minimum GPA 3.5/4.0 required.",
            ),
        ),
        dimension_scores=_STRONG_SCORES,
    )
    assert is_selective_candidate(high_gpa_candidate)
    assert is_selective_candidate(
        low_tier_waiver,
        statements=(("COMPETENCY", "GRE General Test required."),),
    )
    huf_tuition_cand = make_candidate(
        program_id="huf-prog",
        cost_components=(make_cost("TUITION", "10000.00", currency="HUF", period="ANNUAL"),),
        dimension_scores=_STRONG_SCORES,
    )
    assert not is_selective_candidate(huf_tuition_cand)

    # 5. P3-B3 & P3-B4: `longer_program_justifications` ("FUNDING") and `negotiable_preferences`
    # boost the corresponding dimension scores in `score_dimensions`
    from apps.funding.affordability import calculate_affordability
    from apps.funding.evaluation import score_dimensions

    just_profile = make_profile(
        duration_preference="ONE_YEAR",
        duration_flexibility="WEIGHTED",
        longer_program_justifications=("FUNDING",),
        mobility_priorities=("POST_STUDY_WORK",),
        negotiable_preferences=(
            ProfileConstraint(kind="LOCATION", value="Berlin"),
            ProfileConstraint(kind="FIELD", value="Computer Science"),
        ),
    )
    two_yr_funded = make_candidate(
        program_id="two-yr-funded",
        city="Berlin",
        field_of_study="Computer Science",
        duration_months=24,
        cost_components=(make_cost("TUITION", "5000.00", currency="EUR", period="ANNUAL"),),
        benefits=(make_benefit(id="b-1", amount="5000.00", accessibility="ORDINARY"),),
        dimension_scores={**_STRONG_SCORES, "DURATION": Decimal("65")},
    )
    aff_funded = calculate_affordability(just_profile, two_yr_funded, EUR_RATES)
    scored_just = score_dimensions(just_profile, two_yr_funded, aff_funded)
    dim_map = {d.dimension: d.score for d in scored_just.dimensions}
    assert dim_map["DURATION"] == Decimal("85")
    assert dim_map["MOBILITY_FIT"] == Decimal("95")
    assert dim_map["PROGRAM_FIT"] == Decimal("95")

    # 6. P3-B5: `_language_margin` discounts unverified (`ATTESTED`), future-dated, or
    # ungraduated ADA University `DEGREE` evidence by 0.5 compared to verified `TEST`
    from apps.accounts.schemas import LanguageEvidence
    from apps.funding.probability import _language_margin

    today_ref = date(2026, 10, 30)
    prof_verified_test = make_profile(
        language_evidence=(
            LanguageEvidence(
                language="English",
                level="IELTS 7.5",
                evidence_type="TEST",
                available_by=date(2026, 5, 1),
            ),
        )
    )
    prof_attested = make_profile(
        language_evidence=(
            LanguageEvidence(
                language="English",
                level="IELTS 7.5",
                evidence_type="ATTESTED",
                available_by=date(2026, 5, 1),
            ),
        )
    )
    prof_future_test = make_profile(
        language_evidence=(
            LanguageEvidence(
                language="English",
                level="IELTS 7.5",
                evidence_type="TEST",
                available_by=date(2027, 2, 1),
            ),
        )
    )
    assert _language_margin(prof_verified_test, required_cefr="B2", today=today_ref) == 0.35
    assert _language_margin(prof_attested, required_cefr="B2", today=today_ref) == 0.175
    assert _language_margin(prof_future_test, required_cefr="B2", today=today_ref) == 0.175


def test_post_admission_government_scholarship_risk_portfolio() -> None:
    """Students applying via a post-admission government scholarship (admission first,
    then government scholarship, for any nationality) get:
    1. Foreign selective/high-fit tuition-charging programmes covered by
       'Post-Admission Government Scholarship' (or the matched catalog scheme name),
       with domestic or low-fit unfunded programmes excluded.
    2. Application ordering set to PARALLEL_OR_UNIVERSITY_FIRST (apply to university
       first to secure admission offer, then apply for the scholarship).
    3. Correlated joint probability (rho=0.75) scaled dynamically by admission selectivity
       so TARGET (45% admit -> 43% funded) and SAFETY (65% admit -> 61% funded) do not
       collapse into <10% REACH lotteries, and the portfolio anti-lottery guard preserves
       a TARGET/SAFETY admission anchor.
    """
    from apps.accounts.schemas import ProfileConstraint

    dp_profile = make_profile(
        nationality="AZ",
        country_of_residence="AZ",
        funding_dependency="MANDATORY",
        self_funding_capacity={"amount": Decimal("0.00"), "currency": "EUR"},
        application_budget={"amount": Decimal("120.00"), "currency": "EUR"},
        strategy="BALANCED",
        negotiable_preferences=(
            ProfileConstraint(kind="OTHER", value="GOV_SCHOLARSHIP_AFTER_ADMISSION"),
        ),
    )

    imperial_reach = make_candidate(
        program_id="imperial-msc",
        institution_id="imperial",
        program_country_code="GB",
        cost_components=(
            make_cost("APPLICATION_FEE", "100.00", currency="EUR", period="ONE_OFF"),
            make_cost("TUITION", "32000.00", currency="EUR", period="ANNUAL"),
        ),
        benefits=(),
        dimension_scores={
            **_STRONG_SCORES,
            "ACADEMIC_FIT": Decimal("99"),
            "PROGRAM_FIT": Decimal("99"),
        },
    )
    delft_target = make_candidate(
        program_id="tudelft-msc",
        institution_id="tudelft",
        program_country_code="NL",
        cost_components=(
            make_cost("APPLICATION_FEE", "100.00", currency="EUR", period="ONE_OFF"),
            make_cost("TUITION", "21000.00", currency="EUR", period="ANNUAL"),
        ),
        benefits=(),
        dimension_scores=_STRONG_SCORES,
    )
    domestic_unfunded = make_candidate(
        program_id="baku-local",
        institution_id="baku-state",
        program_country_code="AZ",
        cost_components=(
            make_cost("APPLICATION_FEE", "20.00", currency="EUR", period="ONE_OFF"),
            make_cost("TUITION", "4000.00", currency="EUR", period="ANNUAL"),
        ),
        benefits=(),
        dimension_scores=_STRONG_SCORES,
    )

    pack = build_pack(
        dp_profile,
        [imperial_reach, delft_target, domestic_unfunded],
        EUR_RATES,
        probabilities={"imperial-msc": 14, "tudelft-msc": 45, "baku-local": 80},
    )

    # Domestic unfunded programme is rejected by Gate 10 (state scholarship is for study abroad)
    excluded_ids = {exc.program_id: exc.reason_code for exc in pack.excluded}
    assert excluded_ids.get("baku-local") == "NOT_ELIGIBLE"

    # Both foreign programmes stay in their realistic risk tier (45% admit -> 43% TARGET,
    # 14% admit -> 13% REACH) and have PARALLEL_OR_UNIVERSITY_FIRST ordering!
    assert [app.program_id for app in pack.paid] == ["tudelft-msc"]
    target_app = pack.paid[0]
    assert target_app.ordering == "PARALLEL_OR_UNIVERSITY_FIRST"
    assert (
        "apply to the university first to secure your admission offer"
        in target_app.ordering_reason
    )
    assert target_app.winnable_with == ("Post-Admission Government Scholarship",)
    assert target_app.estimated_chance_pct == 45
    assert target_app.estimated_funded_chance_pct == 42
    assert target_app.risk_tier == "TARGET"

    reach_overflow = next(
        app for app in pack.over_budget if app.program_id == "imperial-msc"
    )
    assert reach_overflow.ordering == "PARALLEL_OR_UNIVERSITY_FIRST"
    assert reach_overflow.estimated_funded_chance_pct == 13
    assert reach_overflow.risk_tier == "REACH"

    # Catalog award identified via ApplicantConditionFact.rule_text (without name keywords)
    from apps.funding.evaluation import AwardCandidateFacts
    from apps.funding.validity import Evidence

    condition_only_award = AwardCandidateFacts(
        award_id="state-fund",
        name="National Study Abroad Fund",
        holder_name="National Fund",
        organisation_id="org-fund",
        money_form="GRANT",
        route="SEPARATE_APPLICATION",
        unconfirmed=(),
        benefits=(
            make_benefit(
                id="sf-tuition",
                kind="TUITION",
                amount="25000.00",
                accessibility="CAPACITY_LIMITED",
            ),
        ),
        applicant_conditions=(
            make_applicant_condition(
                "OTHER",
                value="UNCONDITIONAL_OFFER",
                rule_text="Requires an unconditional offer of admission from the university.",
            ),
        ),
        return_service=(),
        evidence_confidence="HIGH",
        evidence=Evidence(applies_to="2027", deadline=date(2027, 6, 15)),
        coverage_is_unstated=False,
        pays_for_program_ids=frozenset({"tudelft-msc"}),
    )
    no_pref_profile = make_profile(
        nationality="KZ",
        country_of_residence="KZ",
        funding_dependency="MANDATORY",
        self_funding_capacity={"amount": Decimal("0.00"), "currency": "EUR"},
        application_budget={"amount": Decimal("120.00"), "currency": "EUR"},
        strategy="FUNDING_FIRST",
    )
    pack_cond_award = build_pack(
        no_pref_profile,
        [delft_target],
        EUR_RATES,
        awards=(condition_only_award,),
        attached_schemes={"tudelft-msc": ("National Study Abroad Fund",)},
        probabilities={"tudelft-msc": 50},
    )
    assert pack_cond_award.paid[0].ordering == "PARALLEL_OR_UNIVERSITY_FIRST"
    assert pack_cond_award.paid[0].estimated_funded_chance_pct == 47









