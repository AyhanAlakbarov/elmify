from apps.research.engine_eval.chat import check_first_tokens
from apps.research.engine_eval.questions import (
    AMOUNT_ROLE_OPTIONS,
    LINE_QUESTIONS,
    TIERS,
    criteria_text,
    jev_amount_choice,
    jev_noul,
)


def test_every_question_has_both_criteria_two_wordings_and_a_tier():
    assert [q.id for q in LINE_QUESTIONS] == [
        "money_to_student", "costs_covered", "fee_waived", "application_date",
        "nationality_rule", "level_rule", "requirement_rule", "not_available"]
    for q in LINE_QUESTIONS:
        assert q.true and q.false and q.wording_a != q.wording_b
        assert "{p}" in q.wording_a and "{p}" in q.wording_b
        assert TIERS[q.id] in {"deadline", "eligibility", "money"}


def test_jev_noul_points_at_the_line_text_by_key_and_carries_criteria():
    n = jev_noul(LINE_QUESTIONS[3], "p3l7", "a")
    assert n.inspect == "`lines.p3l7.text`"
    assert set(n.criteria) == {"true", "false"}
    assert "`lines.p3l7.text`" in n.question


def test_amount_choice_reverses_options_and_keeps_an_unstated_escape():
    fwd = jev_amount_choice("m2", "a", reverse=False)
    rev = jev_amount_choice("m2", "a", reverse=True)
    assert rev.options == tuple(reversed(fwd.options))
    assert "unstated" in fwd.options
    check_first_tokens(AMOUNT_ROLE_OPTIONS)


def test_criteria_text_names_both_sides():
    t = criteria_text(LINE_QUESTIONS[0])
    assert "TRUE:" in t and "FALSE:" in t
