"""The card's fields on a reading, and how three readings agree about them.

Spec 8.3 (the fields), 8.6 (a split detail is UNCONFIRMED, never a hidden award).
"""

import json

import pytest
from django.conf import settings
from pydantic import ValidationError

from apps.research.funding_judge import (
    _MAX_OUTPUT_TOKENS,
    _QUESTION,
    AmountStated,
    FundingVerdicts,
    Line,
    judge,
)
from tests.research.conftest import FakeResponse, FakeResponses, verdict

STIPEND = AmountStated(covers="LIVING", amount="€1,200", currency="EUR", period="MONTHLY")


def test_a_verdict_carries_the_cards_fields_and_defaults_to_unstated():
    plain = verdict(0)
    assert (plain.amounts, plain.duration, plain.duration_unit, plain.timing, plain.cycle) == (
        (), "UNSTATED", "UNSTATED", "UNSTATED", "UNSTATED",
    )
    full = verdict(
        0, amounts=(STIPEND,), duration="24 months", duration_unit="MONTHS",
        timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
    )
    assert full.amounts[0].bound == "EXACT"


@pytest.mark.parametrize(
    "bad",
    [
        {"covers": "SALARY"}, {"period": "WEEKLY"}, {"currency": "euro"},
        {"amount": ""}, {"amount": "x" * 41}, {"bound": "ABOUT"},
    ],
)
def test_an_amount_is_a_closed_shape(bad):
    fields = {"covers": "LIVING", "amount": "€1,200", "currency": "EUR", "period": "MONTHLY"}
    with pytest.raises(ValidationError):
        AmountStated(**{**fields, **bad})


@pytest.mark.parametrize(
    ("field", "value"), [("timing", "SOON"), ("cycle", "BIENNIAL"), ("duration_unit", "WEEKS")]
)
def test_timing_cycle_and_the_duration_unit_are_closed_lists(field, value):
    with pytest.raises(ValidationError):
        verdict(0, **{field: value})


def test_a_line_states_at_most_four_amounts():
    with pytest.raises(ValidationError):
        verdict(0, amounts=(STIPEND,) * 5)


def test_the_question_asks_for_copies_and_forbids_arithmetic():
    for phrase in (
        "amounts:", "copied exactly as the line writes it", "never compute or convert",
        "duration_unit", "timing:", "cycle:", "ROLLING", "PRE_ARRIVAL", "UP_TO",
    ):
        assert phrase in _QUESTION


def test_claudes_doubled_cap_stays_under_the_sdks_non_streaming_wall():
    """funding_judge's own comment on _MAX_OUTPUT_TOKENS: above 21,333 the
    installed SDK refuses a non-streaming call and every Claude reading is lost
    in silence. Claude's reading gets twice the cap."""
    assert 2 * _MAX_OUTPUT_TOKENS <= 21_333


def test_the_real_anthropic_sdk_accepts_a_verdict_with_the_cards_fields():
    """Offline, through the installed SDK, as the existing schema test does:
    the nested AmountStated must survive the SDK's schema transform."""
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    answer = FundingVerdicts(verdicts=(verdict(
        1, amounts=(STIPEND,), duration="24 months", duration_unit="MONTHS",
        timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
    ),))

    def _handler(request):
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "model": settings.ANTHROPIC_JUDGE_MODEL, "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            "content": [{"type": "text", "text": answer.model_dump_json()}],
        })

    claude = anthropic.Anthropic(
        api_key="test-key-not-a-secret",
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(_handler)),
    ).messages
    openai = FakeResponses(FakeResponse(output_parsed=FundingVerdicts()))
    chunk = (Line("Scholarships", ""), Line("Scholars receive €1,200 per month.", "Scholarships"))
    readings = judge(openai, claude, source_id="s", chunk=chunk)
    assert readings[-1] == answer
    assert json.loads(answer.model_dump_json())["verdicts"][0]["amounts"][0]["covers"] == "LIVING"


from decimal import Decimal  # noqa: E402

from apps.research.funding_judge import DecidedAmount, awards, line_outcomes  # noqa: E402

LINE = "Scholars receive €1,200 per month for 24 months, paid before arrival."
OTHER = "The scholarship is renewed every year."
CHUNK = (Line("Scholarships", ""), Line(LINE, "Scholarships"), Line(OTHER, "Scholarships"))
CARD = dict(
    living="FULL", amounts=(STIPEND,), duration="24 months", duration_unit="MONTHS",
    timing="PRE_ARRIVAL", cycle="ANNUAL_FIXED",
)


def _r(*verdicts):
    return FundingVerdicts(verdicts=verdicts)


def _decide(*readings, chunk=CHUNK):
    (decision,) = awards(line_outcomes(chunk, list(readings))).decisions
    return decision


def test_three_readings_agreeing_on_a_line_write_its_card():
    reading = _r(verdict(1, **CARD))
    decision = _decide(reading, reading, reading)
    assert decision.agreement == "AGREED"
    assert decision.amounts == (DecidedAmount(
        covers="LIVING", amount_text="€1,200", amount=Decimal("1200"), currency="EUR",
        period="MONTHLY", bound="EXACT", quote=LINE,
    ),)
    assert (decision.duration, decision.duration_months) == ("24 months", 24)
    assert (decision.timing, decision.cycle) == ("PRE_ARRIVAL", "ANNUAL_FIXED")
    assert dict(decision.card_quotes) == {
        "amount:LIVING": LINE, "duration": LINE, "timing": LINE, "cycle": LINE,
    }
    assert decision.unconfirmed == () and decision.card_off_line == 0


def test_a_figure_one_reading_invented_unconfirms_the_amount_not_the_award():
    good = _r(verdict(1, **CARD))
    invented = _r(verdict(
        1, **{**CARD, "amounts": (STIPEND.model_copy(update={"amount": "€1,400"}),)}
    ))
    decision = _decide(good, good, invented)
    assert decision.agreement == "AGREED"
    assert decision.amounts == ()
    assert "amount" in decision.unconfirmed
    assert decision.card_off_line == 1


def test_a_figure_all_three_readings_invented_is_written_nowhere_and_counted():
    invented = _r(verdict(
        1, **{**CARD, "amounts": (STIPEND.model_copy(update={"amount": "€1,300"}),)}
    ))
    decision = _decide(invented, invented, invented)
    assert decision.amounts == () and "amount" not in decision.unconfirmed
    assert decision.card_off_line == 3


def test_an_ambiguous_currency_keeps_the_text_and_writes_no_number():
    line = "Each scholar receives a one-time award of $5,000."
    stated = AmountStated(covers="TOTAL", amount="$5,000", currency="USD", period="ONE_OFF")
    reading = _r(verdict(0, amounts=(stated,)))
    (amount,) = _decide(reading, reading, reading, chunk=(Line(line, "Awards"),)).amounts
    assert (amount.amount_text, amount.amount, amount.currency) == ("$5,000", None, None)


def test_a_per_semester_figure_keeps_its_text_and_no_number():
    line = "Tuition is reduced by €500 per semester."
    stated = AmountStated(covers="TUITION", amount="€500", currency="EUR", period="OTHER")
    reading = _r(verdict(0, amounts=(stated,)))
    (amount,) = _decide(reading, reading, reading, chunk=(Line(line, "Fees"),)).amounts
    assert (amount.amount, amount.currency, amount.period) == (None, None, "OTHER")


def test_a_split_on_timing_blanks_timing_and_keeps_the_award_shown():
    a = _r(verdict(1, **CARD))
    b = _r(verdict(1, **{**CARD, "timing": "UNSTATED"}))
    decision = _decide(a, a, b)
    assert decision.agreement == "AGREED" and decision.timing == "UNSTATED"
    assert "timing" in decision.unconfirmed and "timing" in decision.disputed
    assert "timing" not in dict(decision.card_quotes)
    assert decision.cycle == "ANNUAL_FIXED"   # one split field blanks one field


def test_a_line_that_states_nothing_does_not_contradict_one_that_does():
    reading = _r(verdict(1, **CARD), verdict(2, living="FULL"))
    decision = _decide(reading, reading, reading)
    assert (decision.timing, decision.duration_months) == ("PRE_ARRIVAL", 24)
    assert decision.unconfirmed == ()


def test_two_lines_stating_different_durations_unconfirm_the_duration():
    top = "Top scholars are funded for 12 months."
    chunk = (Line(LINE, "Scholarships"), Line(top, "Scholarships"))
    reading = _r(
        verdict(0, **CARD),
        verdict(1, living="FULL", duration="12 months", duration_unit="MONTHS"),
    )
    decision = _decide(reading, reading, reading, chunk=chunk)
    assert (decision.duration, decision.duration_months) == ("UNSTATED", None)
    assert "duration" in decision.unconfirmed


def test_an_unagreed_award_keeps_its_card_but_names_nothing_unconfirmed():
    """`unconfirmed` is only ever reported on a shown award (spec 8.6); on an
    UNAGREED one the whole row is the caveat. `disputed` keeps the names for
    the operator either way."""
    a = _r(verdict(1, **CARD))
    b = _r(verdict(1, **{**CARD, "holder": "PRIVATE_FOUNDATION", "timing": "UNSTATED"}))
    decision = _decide(a, a, b)
    assert decision.agreement == "UNAGREED"
    assert decision.unconfirmed == () and "timing" in decision.disputed


import os  # noqa: E402


@pytest.mark.live
def test_three_live_readings_copy_a_monthly_stipend_and_its_duration():
    """One real call per family: the figure, the currency and the months all
    come out of code, from copies three readings agreed on."""
    if not (os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("an award is agreed only when two model families agree")
    import anthropic
    from openai import OpenAI

    from apps.research.funding_judge import read_funding

    chunk = (
        Line("Stipendium", ""),
        Line("Das Stipendium beträgt 992 Euro monatlich für 24 Monate.", "Stipendium"),
    )
    read = read_funding(
        OpenAI().responses, anthropic.Anthropic().messages, source_id="live-card", chunks=[chunk]
    )
    (decision,) = read.decisions
    assert decision.agreement == "AGREED"
    (amount,) = decision.amounts
    assert (amount.amount, amount.currency, amount.period) == (Decimal("992"), "EUR", "MONTHLY")
    assert decision.duration_months == 24
