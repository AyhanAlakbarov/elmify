from datetime import date
from decimal import Decimal

import pytest

from apps.funding.affordability import calculate_affordability
from apps.funding.fx import UnconvertibleCurrency
from tests.funding.conftest import EUR_RATES, make_benefit, make_candidate, make_cost, make_profile


def test_five_local_cost_components_are_summed_into_the_baseline() -> None:
    profile = make_profile()
    candidate = make_candidate(
        duration_months=12,
        cost_components=(
            make_cost("TUITION", "8000.00"),
            make_cost("HOUSING", "6000.00"),
            make_cost("FOOD", "2400.00"),
            make_cost("TRANSPORT", "600.00"),
            make_cost("UTILITIES", "1200.00"),
        ),
        benefits=(),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.baseline_cost == Decimal("18200.00")
    assert result.gap == Decimal("18200.00")


def test_global_scope_benefit_applies_to_any_candidate() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="GLOBAL", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.gap == Decimal("0.00")


def test_country_scope_benefit_is_excluded_for_a_different_country() -> None:
    profile = make_profile()
    candidate = make_candidate(
        program_country_code="DE",
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="COUNTRY", country_code="FR", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.gap == Decimal("1000.00")


def test_city_scope_benefit_applies_only_to_matching_location() -> None:
    profile = make_profile()
    candidate = make_candidate(
        location_key="DE-BERLIN",
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="CITY", location_key="DE-BERLIN", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.gap == Decimal("0.00")


def test_program_scope_benefit_is_excluded_for_a_different_program() -> None:
    profile = make_profile()
    candidate = make_candidate(
        program_id="program-1",
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="PROGRAM", program_id="program-2", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.gap == Decimal("1000.00")


def test_ordinary_reliable_access_benefit_reduces_the_baseline_gap() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "2000.00"),),
        benefits=(make_benefit(accessibility="ORDINARY", amount="500.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("500.00")
    assert result.gap == Decimal("1500.00")


def test_capacity_limited_benefit_is_a_separate_conditional_scenario() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "2000.00"),),
        benefits=(make_benefit(accessibility="CAPACITY_LIMITED", amount="500.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("0.00")
    assert result.gap == Decimal("2000.00")
    assert result.conditional_savings == Decimal("500.00")


def test_emergency_aid_never_reduces_baseline_or_gap_or_conditional_savings() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "2000.00"),),
        benefits=(make_benefit(accessibility="EMERGENCY", amount="500.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("0.00")
    assert result.gap == Decimal("2000.00")
    assert result.conditional_savings == Decimal("0.00")


def test_full_program_period_benefit_is_counted_once_not_multiplied() -> None:
    profile = make_profile()
    candidate = make_candidate(
        duration_months=24,
        cost_components=(make_cost("TUITION", "1000.00", period="FULL_PROGRAM"),),
        benefits=(make_benefit(amount="1000.00", period="FULL_PROGRAM"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.baseline_cost == Decimal("1000.00")
    assert result.gap == Decimal("0.00")


def test_monthly_cost_is_normalized_to_the_full_program_duration() -> None:
    profile = make_profile()
    candidate = make_candidate(
        duration_months=12,
        cost_components=(make_cost("FOOD", "200.00", period="MONTHLY"),),
        benefits=(),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.baseline_cost == Decimal("2400.00")


def test_application_fee_is_tracked_separately_from_the_affordability_gap() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(
            make_cost("TUITION", "1000.00"),
            make_cost("APPLICATION_FEE", "75.00", period="ONE_OFF"),
        ),
        benefits=(),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.application_fee == Decimal("75.00")
    assert result.baseline_cost == Decimal("1000.00")
    assert result.gap == Decimal("1000.00")


def test_uncertain_confidence_benefit_is_excluded_from_baseline_and_conditional_savings() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "2000.00"),),
        benefits=(make_benefit(eligibility_confidence="UNCERTAIN", amount="500.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("0.00")
    assert result.conditional_savings == Decimal("0.00")


def test_stale_non_current_benefit_is_excluded() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "2000.00"),),
        benefits=(make_benefit(is_current=False, amount="500.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("0.00")


def test_nationality_scope_benefit_applies_to_a_matching_student() -> None:
    profile = make_profile(nationality="AZ")
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="NATIONALITY", nationality_code="AZ", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.gap == Decimal("0.00")


def test_nationality_scope_benefit_is_excluded_for_a_different_nationality() -> None:
    profile = make_profile(nationality="KZ")
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00"),),
        benefits=(make_benefit(scope_type="NATIONALITY", nationality_code="AZ", amount="1000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.gap == Decimal("1000.00")


def test_a_benefit_in_another_currency_is_converted_before_subtraction() -> None:
    profile = make_profile()
    candidate = make_candidate(
        duration_months=12,
        cost_components=(make_cost("TUITION", "800000.00", currency="INR", period="FULL_PROGRAM"),),
        benefits=(
            make_benefit(
                scope_type="GLOBAL", amount="5000.00", currency="EUR", period="FULL_PROGRAM"
            ),
        ),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.currency == "EUR"
    assert result.baseline_cost == Decimal("8465.61")
    assert result.covered == Decimal("5000.00")
    assert result.gap == Decimal("3465.61")


def test_an_unconvertible_currency_raises_instead_of_summing_across_currencies() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "1000.00", currency="KZT"),),
    )

    with pytest.raises(UnconvertibleCurrency):
        calculate_affordability(profile, candidate, EUR_RATES)


def test_affordability_carries_the_rate_provenance_behind_its_conversions() -> None:
    result = calculate_affordability(
        make_profile(),
        make_candidate(cost_components=(make_cost("TUITION", "1000.00", currency="USD"),)),
        EUR_RATES,
    )

    assert result.rates_source == "TEST"
    assert result.rates_retrieved_on == date(2026, 8, 14)


def test_annual_proration_rounds_half_up_at_the_exact_boundary() -> None:
    from apps.funding.affordability import _normalize_to_program_total

    # 1000.05 * 6 / 12 = 500.025 exactly — ROUND_HALF_EVEN would give 500.02,
    # ROUND_HALF_UP (the pipeline-wide rule) must give 500.03.
    result = _normalize_to_program_total(Decimal("1000.05"), "ANNUAL", 6)

    assert result == Decimal("500.03")


def test_the_repayable_half_of_an_award_is_not_coverage() -> None:
    """AKF's International Scholarship Programme is half grant, half interest-free
    loan. Counting the loan as coverage understates the gap by the repayable half."""
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(make_benefit(amount="10000.00", repayable_share="0.50"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("5000.00")
    assert result.gap == Decimal("5000.00")


def test_a_grant_with_no_repayable_share_covers_in_full() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(make_benefit(amount="10000.00"),),
    )

    result = calculate_affordability(profile, candidate, EUR_RATES)

    assert result.covered == Decimal("10000.00")
    assert result.gap == Decimal("0.00")
