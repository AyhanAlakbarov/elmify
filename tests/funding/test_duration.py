from decimal import Decimal

from apps.funding.affordability import calculate_affordability
from apps.funding.evaluation import evaluate, score_dimensions
from tests.funding.conftest import EUR_RATES, make_candidate, make_profile


def test_one_year_non_negotiable_excludes_a_two_year_program() -> None:
    profile = make_profile(duration_preference="ONE_YEAR", duration_flexibility="NON_NEGOTIABLE")
    candidate = make_candidate(duration_months=24, cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("duration" in reason for reason in result.reasons)


def test_one_year_non_negotiable_accepts_a_one_year_program() -> None:
    profile = make_profile(duration_preference="ONE_YEAR", duration_flexibility="NON_NEGOTIABLE")
    candidate = make_candidate(duration_months=12, cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_two_year_non_negotiable_excludes_a_one_year_program() -> None:
    profile = make_profile(duration_preference="TWO_YEAR", duration_flexibility="NON_NEGOTIABLE")
    candidate = make_candidate(duration_months=12, cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"


def test_two_year_non_negotiable_accepts_a_two_year_program() -> None:
    profile = make_profile(duration_preference="TWO_YEAR", duration_flexibility="NON_NEGOTIABLE")
    candidate = make_candidate(duration_months=24, cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_one_year_weighted_with_justification_does_not_exclude_a_two_year_program() -> None:
    profile = make_profile(
        duration_preference="ONE_YEAR",
        duration_flexibility="WEIGHTED",
        longer_program_justifications=("FUNDING",),
    )
    candidate = make_candidate(duration_months=24, cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_two_year_weighted_does_not_exclude_a_one_year_program() -> None:
    profile = make_profile(duration_preference="TWO_YEAR", duration_flexibility="WEIGHTED")
    candidate = make_candidate(duration_months=12, cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_duration_dimension_is_excluded_when_preference_is_none() -> None:
    profile = make_profile(duration_preference="NONE", duration_flexibility="NOT_APPLICABLE")
    candidate = make_candidate(cost_components=())
    affordability = calculate_affordability(profile, candidate, EUR_RATES)

    scores = score_dimensions(profile, candidate, affordability)

    assert "DURATION" not in {score.dimension for score in scores.dimensions}
    assert sum((score.weight for score in scores.dimensions), Decimal("0")) == Decimal("1")


def test_duration_dimension_is_included_when_a_preference_is_set() -> None:
    profile = make_profile(duration_preference="ONE_YEAR", duration_flexibility="NON_NEGOTIABLE")
    candidate = make_candidate(duration_months=12, cost_components=())
    affordability = calculate_affordability(profile, candidate, EUR_RATES)

    scores = score_dimensions(profile, candidate, affordability)

    assert "DURATION" in {score.dimension for score in scores.dimensions}
    assert sum((score.weight for score in scores.dimensions), Decimal("0")) == Decimal("1")
