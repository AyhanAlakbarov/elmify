"""Tiered agreement: existence gates the award, a detail does not.

Owner decision 2026-09-19, existence set confirmed 2026-09-22 (spec section 8.6
and decision-log row 23). Measured on the 2026-09-19 gate: ten awards decided on
five known funders, none shown, all split on `route` and `money_form`, none on
`holder`. Hiding the award is the wrong failure direction for a recall-first
goal -- the student loses a real scholarship because two models disagreed about
grant vs subsidy.
"""

import pytest

from apps.research.funding_judge import (
    _EXISTENCE,
    FundingVerdicts,
    Line,
    awards,
    line_outcomes,
)
from tests.research.conftest import verdict

WAIVER = "All admitted international students receive a 50% tuition waiver."
CHUNK = (Line("Scholarships", ""), Line(WAIVER, "Scholarships"))


def _reading(*verdicts) -> FundingVerdicts:
    return FundingVerdicts(verdicts=verdicts)


def _split_on(field: str, other: str):
    """Three readings of one line: two agreeing, one differing on `field`."""
    return [
        _reading(verdict(1)),
        _reading(verdict(1)),
        _reading(verdict(1, **{field: other})),
    ]


def test_an_award_split_on_money_form_is_shown_with_that_field_unconfirmed():
    decision = awards(line_outcomes(CHUNK, _split_on("money_form", "GRANT"))).decisions[0]

    assert decision.agreement == "AGREED"
    assert "money_form" in decision.unconfirmed
    assert decision.money_form == "UNSTATED"
    # Nothing is lost from the review path: `disputed` still names it.
    assert "money_form" in decision.disputed


@pytest.mark.parametrize(
    ("field", "other"),
    [("offered", "NO"), ("holder", "NATIONAL_GOVERNMENT"), ("scope", "INSTITUTION")],
)
def test_an_award_split_on_an_existence_field_is_still_not_agreed(field, other):
    """Existence is untouched. "Never show money the page does not offer" is the
    one guarantee this task may not weaken."""
    decisions = awards(line_outcomes(CHUNK, _split_on(field, other))).decisions
    assert decisions, f"a split on {field} must still produce a decision to refuse"
    assert all(d.agreement == "UNAGREED" for d in decisions)
    assert all(field not in d.unconfirmed for d in decisions)


def test_the_existence_set_is_exactly_the_three_the_owner_named():
    """Pinned as a set, so widening it -- which would hide awards again -- or
    narrowing it -- which would serve money a page does not offer -- fails here
    rather than in a measurement six weeks later."""
    assert _EXISTENCE == ("offered", "holder", "scope")


def test_an_unconfirmed_field_is_never_a_filterable_value():
    """The pool must not filter on a value no reading confirmed -- that is how a
    disagreement becomes a silent exclusion instead of a visible caveat. The
    mechanism is that the field is blanked to UNSTATED, so a filter on any real
    value cannot match it."""
    decision = awards(
        line_outcomes(CHUNK, _split_on("route", "STUDENT_APPLIES_SEPARATELY"))
    ).decisions[0]

    assert decision.agreement == "AGREED"
    assert decision.unconfirmed == ("route",)
    assert decision.route == "UNSTATED"


def test_an_award_the_readings_agree_on_carries_nothing_unconfirmed():
    decision = awards(line_outcomes(CHUNK, [_reading(verdict(1))] * 3)).decisions[0]
    assert decision.agreement == "AGREED"
    assert decision.unconfirmed == ()
    assert decision.money_form == "FEE_WAIVER"


def test_a_split_on_a_detail_and_on_existence_together_is_still_unagreed():
    """The tiers do not cancel: a detail being forgivable does not forgive the
    existence field split alongside it."""
    readings = [
        _reading(verdict(1)),
        _reading(verdict(1)),
        _reading(verdict(1, money_form="GRANT", holder="NATIONAL_GOVERNMENT")),
    ]
    decisions = awards(line_outcomes(CHUNK, readings)).decisions
    assert all(d.agreement == "UNAGREED" for d in decisions)
