"""The scholarship page's copies: facts about the option, and the student's fit."""

from decimal import Decimal

from apps.funding.evaluation import ApplicantConditionFact
from apps.research.candidate_details import budget_line, fit_for, program_details
from tests.funding.conftest import make_candidate, make_profile


def _grade(bar: str, quote: str = "A GPA of at least 3.0 out of 4.0.") -> ApplicantConditionFact:
    return ApplicantConditionFact(
        benefit_id="b1", condition_type="WORK_EXPERIENCE", key="GRADE", operator="GTE",
        value=f"{bar} 4.0 GPA", rule_text=quote,
    )


def test_a_grade_bar_the_student_clears_is_a_reason_they_fit() -> None:
    rows = fit_for([_grade("3.0")], make_profile())
    assert rows == [
        {
            "key": "GRADE",
            "outcome": "SATISFIED",
            "quote": "A GPA of at least 3.0 out of 4.0.",
            "reason": rows[0]["reason"],
        }
    ]
    assert "3.8" in rows[0]["reason"]


def test_a_bar_above_the_student_is_shown_as_not_met() -> None:
    (row,) = fit_for([_grade("3.9")], make_profile())
    assert row["outcome"] == "FAILED"


def test_without_a_full_profile_nothing_is_claimed() -> None:
    assert fit_for([_grade("3.0")], None) == []
    assert budget_line(None) == {}


def test_one_sentence_on_two_routes_is_one_requirement() -> None:
    twice = [_grade("3.0"), _grade("3.0").model_copy(update={"benefit_id": "b2"})]
    assert len(fit_for(twice, make_profile())) == 1


def test_the_budget_is_the_students_yearly_figure() -> None:
    assert budget_line(make_profile()) == {"amount": "10000", "currency": "EUR"}


def test_programme_details_leave_the_application_fee_to_its_own_line() -> None:
    facts = make_candidate()
    details = program_details(facts)
    assert details["city"] == facts.city
    assert all(cost["kind"] != "APPLICATION_FEE" for cost in details["costs"])
    assert all(Decimal(cost["amount"]) >= 0 for cost in details["costs"])
