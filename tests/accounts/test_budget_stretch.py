from decimal import Decimal

import pytest

from apps.accounts.consultation import QUESTIONS
from apps.accounts.forms import MoneyField, _canonical_value, question_field
from apps.accounts.schemas import StudentProfileSnapshot
from tests.accounts.test_profile_schema_v3 import _answers


def test_the_stretch_is_asked_right_after_the_budget() -> None:
    keys = [question.key for question in QUESTIONS]
    assert keys[keys.index("application_budget") + 1] == "budget_stretch"


def test_the_stretch_question_may_be_left_blank() -> None:
    field = question_field("budget_stretch")
    assert isinstance(field, MoneyField)
    assert field.required is False


@pytest.mark.parametrize("value", [None, "", {"amount": "0", "currency": "AZN"}])
def test_blank_or_zero_means_no_stretch(value) -> None:
    assert _canonical_value("budget_stretch", value) is None


def test_a_stretch_is_kept_as_money() -> None:
    stored = _canonical_value("budget_stretch", {"amount": "150", "currency": "AZN"})
    assert stored["currency"] == "AZN"
    assert Decimal(stored["amount"]) == Decimal("150")


def test_an_old_snapshot_without_the_key_is_still_valid() -> None:
    assert StudentProfileSnapshot.model_validate(_answers()).budget_stretch is None


def test_a_snapshot_carries_the_stretch() -> None:
    profile = StudentProfileSnapshot.model_validate(
        _answers(budget_stretch={"amount": "150", "currency": "AZN"})
    )
    assert profile.budget_stretch.amount == Decimal("150")
