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
    profile = make_profile(strategy="FUNDING_FIRST", funding_dependency="MANDATORY")
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
    fee_free = make_candidate(
        program_id="fee-free-1",
        cost_components=(make_cost("TUITION", "5000.00"),),
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
