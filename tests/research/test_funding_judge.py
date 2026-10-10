import logging

from apps.research.funding_judge import MAX_CHUNKS, Line, funding_chunks, funding_lines


def test_lines_keep_their_heading_as_context_and_lose_their_markers():
    text = "# MSc Chemistry\n## Scholarships\n- A 50% tuition waiver.\nHousing is offered."
    assert funding_lines(text) == (
        Line(text="MSc Chemistry", heading=""),
        Line(text="Scholarships", heading="MSc Chemistry"),
        Line(text="A 50% tuition waiver.", heading="Scholarships"),
        Line(text="Housing is offered.", heading="Scholarships"),
    )


def test_a_line_over_300_characters_is_split_into_sentences():
    first = "The consortium awards scholarships to the best applicants. " * 4
    second = "They cover tuition, travel and a monthly allowance of 1,400 euros for 24 months."
    lines = funding_lines(first + second)
    assert [line.text for line in lines] == [
        "The consortium awards scholarships to the best applicants.",
        "The consortium awards scholarships to the best applicants.",
        "The consortium awards scholarships to the best applicants.",
        "The consortium awards scholarships to the best applicants.",
        second,
    ]


def test_a_short_line_is_never_split_and_a_long_one_without_punctuation_is_kept_whole():
    assert funding_lines("Fees: 0 EUR. Waivers: yes.") == (Line("Fees: 0 EUR. Waivers: yes.", ""),)
    unbroken = "x" * 400
    assert funding_lines(unbroken) == (Line(unbroken, ""),)


def test_blank_lines_are_skipped():
    assert funding_lines("\n\n  \nA grant.\n") == (Line("A grant.", ""),)


def test_chunks_hold_80_lines_and_at_most_three_are_judged(caplog):
    text = "\n".join(f"Line {i}." for i in range(250))
    with caplog.at_level(logging.WARNING, logger="apps.research.funding_judge"):
        chunks = funding_chunks(text)
    assert [len(chunk) for chunk in chunks] == [80, 80, 80]
    assert len(chunks) == MAX_CHUNKS
    assert "250 lines" in caplog.text


def test_a_page_with_no_lines_has_no_chunks():
    assert funding_chunks("") == []


import json  # noqa: E402

import pytest  # noqa: E402
from django.conf import settings  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from apps.research.extraction import privacy_safe_identifier  # noqa: E402
from apps.research.funding_judge import FundingVerdicts, LineVerdict, judge  # noqa: E402
from tests.research.conftest import FakeResponse, FakeResponses, verdict  # noqa: E402

CHUNK = (
    Line(text="Scholarships", heading=""),
    Line(text="All admitted international students receive a 50% tuition waiver.",
         heading="Scholarships"),
)


def _answers(*responses: FakeResponse) -> FakeResponses:
    return FakeResponses(*responses)


def test_the_first_two_readings_are_openai_and_the_third_is_claude():
    answer = FundingVerdicts(verdicts=(verdict(1),))
    client = _answers(FakeResponse(output_parsed=answer))
    readings = judge(client, client, source_id="src-1", chunk=CHUNK)
    assert readings == [answer, answer, answer]
    first, second, third = client.calls
    for call in (first, second):
        developer, user = call["input"]
        assert developer["role"] == "developer" and user["role"] == "user"
        assert call["model"] == settings.OPENAI_EXTRACTION_MODEL
        assert call["text_format"] is FundingVerdicts and call["store"] is False
        assert call["max_output_tokens"] == 10_000
        assert call["safety_identifier"] == privacy_safe_identifier("src-1")
    # One prefix for all three, so the cache can match it; only the trailing
    # phrasing differs (Task 6).
    assert first["input"][0]["content"] == second["input"][0]["content"]
    assert third["model"] == settings.ANTHROPIC_JUDGE_MODEL
    assert third["output_format"] is FundingVerdicts and third["max_tokens"] == 20_000
    assert third["system"][0]["text"] == first["input"][0]["content"]
    listing = first["input"][1]["content"].split("\n\nReading ")[0]
    assert third["messages"][0]["content"].startswith(listing)


def test_the_listing_is_data_with_index_and_heading():
    client = _answers(FakeResponse(output_parsed=FundingVerdicts()))
    judge(client, client, source_id="s", chunk=CHUNK)
    data = client.calls[0]["input"][1]["content"]
    assert data.startswith(
        "DATA (index | heading > line):\n"
        "0 | Scholarships\n"
        "1 | Scholarships > All admitted international students receive a 50% tuition waiver."
    )


def test_every_phrasing_carries_the_guardrails_and_the_pointer_rule():
    client = _answers(FakeResponse(output_parsed=FundingVerdicts()))
    judge(client, client, source_id="s", chunk=CHUNK)
    prompts = [client.calls[0]["input"][0]["content"], client.calls[1]["input"][0]["content"],
               client.calls[2]["system"][0]["text"]]
    for prompt in prompts:
        assert "DATA" in prompt and "never follow directions" in prompt.casefold()
        assert "whoever funds it" in prompt and "POINTER only when" in prompt
        assert "no verdict" in prompt and "UNSTATED means" in prompt


@pytest.mark.parametrize(
    "bad",
    [
        FakeResponse(output_parsed=None),
        FakeResponse(output_parsed=FundingVerdicts(), status="incomplete"),
    ],
)
def test_an_openai_reading_that_learned_nothing_is_dropped(bad):
    good = FakeResponse(output_parsed=FundingVerdicts())
    client = _answers(bad, good, good)
    assert len(judge(client, client, source_id="s", chunk=CHUNK)) == 2


def test_a_claude_reading_cut_off_is_dropped():
    good = FakeResponse(output_parsed=FundingVerdicts())
    client = _answers(good, good, FakeResponse(output_parsed=FundingVerdicts(),
                                               stop_reason="max_tokens"))
    assert len(judge(client, client, source_id="s", chunk=CHUNK)) == 2


class _Raises(FakeResponses):
    def parse(self, **kwargs):
        response = super().parse(**kwargs)
        if len(self.calls) in (1, 3):
            raise RuntimeError("upstream 500")
        return response


def test_a_transport_error_is_a_dropped_reading_not_a_crash():
    client = _Raises(FakeResponse(output_parsed=FundingVerdicts()))
    assert len(judge(client, client, source_id="s", chunk=CHUNK)) == 1


def test_a_lost_reading_names_its_family_in_the_log(caplog):
    """An abstention caused by an outage must not be silent (2026-09-15)."""
    client = _Raises(FakeResponse(output_parsed=FundingVerdicts()))
    with caplog.at_level(logging.WARNING, logger="apps.research.funding_judge"):
        judge(client, client, source_id="src-9", chunk=CHUNK)
    assert "openai, claude" in caplog.text and "src-9" in caplog.text


def test_three_answered_readings_log_nothing(caplog):
    client = _answers(*[FakeResponse(output_parsed=FundingVerdicts())] * 3)
    with caplog.at_level(logging.WARNING, logger="apps.research.funding_judge"):
        judge(client, client, source_id="s", chunk=CHUNK)
    assert caplog.text == ""


def test_the_verdict_schema_is_closed():
    with pytest.raises(ValidationError):
        verdict(0, offered="MAYBE")
    with pytest.raises(ValidationError):
        verdict(0, name="")
    with pytest.raises(ValidationError):
        verdict(0, name="x" * 81)
    with pytest.raises(ValidationError):
        LineVerdict.model_validate({**verdict(0).model_dump(), "unknown": 1})
    assert verdict(0, extras=("HOUSING",)).extras == ("HOUSING",)


def test_the_real_anthropic_sdk_accepts_the_verdict_schema():
    """Offline, through the installed SDK: FundingVerdicts must survive the
    SDK's schema transform and a JSON answer must parse back. Only the
    transport is fake."""
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    answer = FundingVerdicts(verdicts=(verdict(1),))
    sent: list[dict[str, object]] = []

    def _handler(request):
        sent.append(json.loads(request.content))
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
    openai = _answers(FakeResponse(output_parsed=FundingVerdicts()))
    readings = judge(openai, claude, source_id="s", chunk=CHUNK)
    assert readings[-1] == answer
    assert sent[0]["output_config"]["format"]["type"] == "json_schema"


from apps.research.funding_judge import (  # noqa: E402
    FundingDecision,
    FundingReadResult,
    awards,
    line_outcomes,
    read_funding,
)

WAIVER = "All admitted international students receive a 50% tuition waiver."
HOUSING = "Students may apply for a housing bursary."
NEGATION = "No scholarships are offered for this programme."
PAGE_CHUNK = (
    Line("Scholarships", ""),
    Line(WAIVER, "Scholarships"),
    Line(HOUSING, "Scholarships"),
    Line(NEGATION, "Scholarships"),
)


def _reading(*verdicts: LineVerdict) -> FundingVerdicts:
    return FundingVerdicts(verdicts=verdicts)


def _status(readings, line=1):
    (outcome,) = [o for o in line_outcomes(PAGE_CHUNK, readings) if o.line == PAGE_CHUNK[line]]
    return outcome


def test_three_identical_yes_verdicts_are_agreed():
    outcome = _status([_reading(verdict(1))] * 3)
    assert outcome.status == "agreed" and outcome.disputed == ()


def test_a_field_one_reading_labels_differently_is_disputed_and_named():
    readings = [_reading(verdict(1)), _reading(verdict(1)),
                _reading(verdict(1, route="STUDENT_APPLIES_SEPARATELY"))]
    outcome = _status(readings)
    assert outcome.status == "disputed" and outcome.disputed == ("route",)


def test_a_non_decided_field_does_not_dispute():
    readings = [_reading(verdict(1, tuition="FULL")), _reading(verdict(1)),
                _reading(verdict(1, name="Waiver", extras=("HOUSING",)))]
    assert _status(readings).status == "agreed"


def test_two_yes_and_one_silence_is_disputed_on_offered():
    outcome = _status([_reading(verdict(1)), _reading(verdict(1)), _reading()])
    assert outcome.status == "disputed" and "offered" in outcome.disputed


def test_one_yes_alone_is_noise():
    assert _status([_reading(verdict(1)), _reading(), _reading()]).status == "noise"


def test_a_line_nobody_judged_has_no_outcome():
    assert line_outcomes(PAGE_CHUNK, [_reading(), _reading(), _reading()]) == []


def test_no_yes_and_at_least_two_no_is_a_negation():
    no = verdict(3, offered="NO", money_form="UNSTATED", tuition="UNSTATED")
    assert _status([_reading(no), _reading(no), _reading()], line=3).status == "negation"
    assert _status([_reading(no)] * 3, line=3).status == "negation"


def test_two_no_and_one_yes_is_disputed():
    no = verdict(3, offered="NO")
    outcome = _status([_reading(no), _reading(no), _reading(verdict(3))], line=3)
    assert outcome.status == "disputed" and "offered" in outcome.disputed


def test_a_reading_repeating_one_verdict_is_one_vote():
    """2249fe4: a reading that repeats itself cannot stand in for silent readings."""
    repeated = _reading(verdict(1), verdict(1), verdict(1))
    assert _status([repeated, _reading(), _reading()]).status == "noise"


def test_a_reading_contradicting_itself_can_dispute_but_never_agree():
    contradictory = _reading(verdict(1), verdict(1, money_form="GRANT"))
    outcome = _status([contradictory, _reading(verdict(1)), _reading(verdict(1))])
    assert outcome.status == "disputed" and "money_form" in outcome.disputed


def test_fewer_than_three_readings_abstain_every_funding_line():
    outcome = _status([_reading(verdict(1)), _reading(verdict(1))])
    assert outcome.status == "abstained"


def test_a_verdict_for_a_line_outside_the_chunk_is_ignored():
    readings = [_reading(verdict(1), verdict(40))] * 3
    assert [o.line.text for o in line_outcomes(PAGE_CHUNK, readings)] == [WAIVER]


def test_agreed_lines_become_an_agreed_award_with_quotes_and_name():
    result = awards(line_outcomes(PAGE_CHUNK, [_reading(verdict(1))] * 3))
    (decision,) = result.decisions
    assert decision.agreement == "AGREED" and decision.quotes == (WAIVER,)
    assert (decision.kind, decision.scope, decision.money_form) == (
        "I2_PROGRAMME_ATTACHED", "PROGRAM", "FEE_WAIVER")
    assert decision.name == "Tuition waiver" and decision.disputed == ()


def test_two_lines_of_one_kind_that_disagree_on_eligibility_are_shown_unconfirmed():
    """The C2 case as a rule: UNSTATED is a value, distinct from YES -- so
    `disputed` still names both fields, unchanged.

    **What changed on 2026-09-22 is the consequence, not the detection.** This
    asserted UNAGREED, which was right under the strict rule and is wrong under
    tiered agreement (spec 8.6): none of the three existence fields is in
    dispute here, so the award is SHOWN with the two fields marked unconfirmed
    beside the quotes. That is the whole owner decision -- a student losing a
    real scholarship because two readings disagreed about a detail is the wrong
    failure direction. The fields are blanked to UNSTATED so the pool cannot
    filter on a value no reading confirmed.
    """
    housing = verdict(2, internationals_included="UNSTATED", nationality_shape="UNSTATED",
                      money_form="SUBSIDY", tuition="NONE", extras=("HOUSING",))
    result = awards(line_outcomes(PAGE_CHUNK, [_reading(verdict(1), housing)] * 3))
    (decision,) = result.decisions
    assert decision.agreement == "AGREED"
    assert set(decision.disputed) >= {"internationals_included", "nationality_shape"}
    assert set(decision.unconfirmed) >= {"internationals_included", "nationality_shape"}
    assert decision.internationals_included == "UNSTATED"
    assert decision.nationality_shape == "UNSTATED"
    assert decision.quotes == (WAIVER, HOUSING)


def test_name_comes_from_the_first_agreed_line_not_page_order():
    """Spec 2.4: name is the first AGREED line's -- a disputed line earlier on the
    page must not supply the merged award's name."""
    majority_reading = _reading(verdict(1), verdict(2, name="Housing bursary"))
    dissenting_reading = _reading(
        verdict(1, route="STUDENT_APPLIES_SEPARATELY"), verdict(2, name="Housing bursary"))
    result = awards(line_outcomes(
        PAGE_CHUNK, [majority_reading, majority_reading, dissenting_reading]))
    (decision,) = result.decisions
    assert decision.name == "Housing bursary"


def test_two_lines_with_identical_decided_fields_stay_agreed_and_union_extras():
    housing = verdict(2, extras=("HOUSING",), tuition="FULL")
    result = awards(line_outcomes(PAGE_CHUNK, [_reading(verdict(1), housing)] * 3))
    (decision,) = result.decisions
    assert decision.agreement == "AGREED" and decision.extras == ("HOUSING",)


def test_awards_are_separate_per_kind_and_scope_and_pointers_are_counted():
    ra = verdict(2, kind="I3_STIPEND_OR_ASSISTANTSHIP", money_form="GRANT", tuition="NONE",
                 living="PARTIAL")
    pointer = verdict(3, scope="POINTER", kind="I1_UNIVERSITY_WIDE", money_form="GRANT")
    result = awards(line_outcomes(PAGE_CHUNK, [_reading(verdict(1), ra, pointer)] * 3))
    assert sorted(d.kind for d in result.decisions) == [
        "I2_PROGRAMME_ATTACHED", "I3_STIPEND_OR_ASSISTANTSHIP"]
    assert result.pointers == 1


def test_a_negation_is_a_decision_of_its_own_and_noise_is_only_counted():
    """Changed 2026-09-18 (spec 3.5.3): a negation used to be counted and
    dropped, which is how a page that says "this intake will be without
    scholarship" kept serving one. It now decides its award, unserved, with
    the sentence kept -- and it is still counted, so the tallies compare."""
    no = verdict(3, offered="NO")
    readings = [_reading(verdict(1), no), _reading(no), _reading(no)]
    result = awards(line_outcomes(PAGE_CHUNK, readings))
    assert (result.pointers, result.negations, result.noise) == (0, 1, 1)
    # Two awards: the waiver line 1 states, and the one line 3 denies.
    denied = [d for d in result.decisions if d.offered == "NO"]
    assert len(denied) == 1
    assert denied[0].suspension_quote == NEGATION and denied[0].applies_to == "UNSTATED"


def test_an_abstained_line_makes_its_award_abstained():
    result = awards(line_outcomes(PAGE_CHUNK, [_reading(verdict(1))] * 2))
    (decision,) = result.decisions
    assert decision.agreement == "ABSTAINED"


def test_coverage_is_the_majority_over_every_yes_verdict():
    readings = [_reading(verdict(1, tuition="FULL")), _reading(verdict(1, tuition="FULL")),
                _reading(verdict(1))]
    (decision,) = awards(line_outcomes(PAGE_CHUNK, readings)).decisions
    assert decision.tuition == "FULL"


def test_one_reading_alone_in_stating_coverage_does_not_carry_it():
    """A minority of one must not become the award's coverage just because the other
    two said nothing. UNSTATED is a verdict, not an abstention to be discounted: the
    denominator is every YES verdict. Before this, the only stated value won by
    default, and `_benefit_kinds` turned it into a TUITION benefit, which is enough on
    its own to make `funding_reader` serve a row all three readings agree states no
    money at all."""
    readings = [_reading(verdict(1, tuition="UNSTATED")), _reading(verdict(1, tuition="UNSTATED")),
                _reading(verdict(1, tuition="FULL"))]
    (decision,) = awards(line_outcomes(PAGE_CHUNK, readings)).decisions
    assert decision.tuition == "UNSTATED"


def test_read_funding_judges_every_chunk_and_groups_across_them():
    client = FakeResponses(FakeResponse(output_parsed=_reading(verdict(1))))
    result = read_funding(client, client, source_id="s", chunks=[PAGE_CHUNK, PAGE_CHUNK])
    assert len(client.calls) == 6
    (decision,) = result.decisions
    assert decision.quotes == (WAIVER,)  # the same sentence in two chunks is one quote


def test_the_result_types_are_frozen():
    assert FundingDecision.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert FundingReadResult.__dataclass_params__.frozen  # type: ignore[attr-defined]


EMJM_PAGE = """# Erasmus Mundus Joint Master in Coastal Engineering
## Scholarships
The consortium awards Erasmus Mundus scholarships to the best-ranked applicants.
Scholarships are open to applicants of any nationality.
They cover participation costs, travel and installation costs, and a monthly subsistence allowance of 1,400 euros for the 24 months of the programme.
Applicants are considered for a scholarship when they apply to the programme; no separate application is needed.
## Tuition fees
Self-funded students pay a participation cost of 9,000 euros per year.
"""


@pytest.mark.live
def test_three_live_readings_serve_a_plain_erasmus_mundus_scholarship():
    """Both keys must be sourced. A plain, unambiguous scholarship is the floor:
    if two families cannot agree here, nothing harder will be served."""
    import anthropic
    import openai

    chunks = funding_chunks(EMJM_PAGE)
    result = read_funding(
        openai.OpenAI().responses, anthropic.Anthropic().messages, source_id="live-emjm",
        chunks=chunks,
    )
    for decision in result.decisions:
        print(decision.agreement, decision.kind, decision.scope, decision.disputed,
              decision.money_form, decision.route)
    served = [d for d in result.decisions if d.agreement == "AGREED"]
    assert any(d.kind == "I5_FUNDED_DUAL_DEGREE" and d.scope == "PROGRAM" for d in served)
    assert result.pointers == 0


def test_a_verdict_carries_who_holds_the_money():
    v = LineVerdict(
        line=1, offered="YES", kind="I0_HOLDER_AWARD", scope="HOLDER_OWN",
        internationals_included="YES", nationality_shape="OPEN",
        route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", tuition="UNSTATED",
        living="FULL", holder="PRIVATE_FOUNDATION", name="Cusanuswerk scholarship",
    )
    assert v.holder == "PRIVATE_FOUNDATION" and v.scope == "HOLDER_OWN"


def test_holder_is_a_closed_list():
    with pytest.raises(ValidationError):
        LineVerdict(
            line=1, offered="YES", kind="I0_HOLDER_AWARD", scope="HOLDER_OWN",
            internationals_included="YES", nationality_shape="OPEN", route="UNSTATED",
            money_form="GRANT", tuition="UNSTATED", living="UNSTATED", holder="CHARITY",
            name="x",
        )


def test_readings_that_disagree_on_the_holder_are_disputed_on_it():
    base = dict(line=1, offered="YES", kind="I0_HOLDER_AWARD", scope="HOLDER_OWN",
                internationals_included="YES", nationality_shape="OPEN", route="UNSTATED",
                money_form="GRANT", tuition="UNSTATED", living="FULL", name="Award")
    readings = [
        _reading(LineVerdict(holder="PRIVATE_FOUNDATION", **base)),
        _reading(LineVerdict(holder="PRIVATE_FOUNDATION", **base)),
        _reading(LineVerdict(holder="EMPLOYER", **base)),
    ]
    outcome = _status(readings)
    assert outcome.status == "disputed" and outcome.disputed == ("holder",)


def test_the_question_defines_holder_own_and_every_holder_value():
    from apps.research.funding_judge import _HOLDERS, _QUESTION

    assert "HOLDER_OWN" in _QUESTION
    for value in _HOLDERS:
        assert value in _QUESTION, value


def test_a_pointer_line_is_returned_as_a_lead_with_its_quote():
    from apps.research.funding_judge import PointerLead

    daad = Line("Students may also apply for a DAAD scholarship.", "Funding")
    chunk = (daad,)
    v = LineVerdict(line=0, offered="YES", kind="I1_UNIVERSITY_WIDE", scope="POINTER",
                    internationals_included="YES", nationality_shape="OPEN",
                    route="STUDENT_APPLIES_SEPARATELY", money_form="GRANT", tuition="UNSTATED",
                    living="UNSTATED", holder="NATIONAL_GOVERNMENT", name="DAAD scholarship")
    result = awards(line_outcomes(chunk, [_reading(v)] * 3))
    assert result.pointers == 1
    assert result.pointer_leads == (PointerLead(quote=daad.text, name="DAAD scholarship",
                                                holder="NATIONAL_GOVERNMENT"),)
    assert result.decisions == ()


def test_a_two_one_split_on_offered_is_settled_by_a_fourth_yes():
    readings = [_reading(verdict(1)), _reading(verdict(1)), _reading()]
    fourth = _reading(verdict(1))
    outcome = _status(readings + [fourth])
    assert outcome.status == "agreed"


def test_a_two_two_split_on_offered_stays_disputed():
    readings = [_reading(verdict(1)), _reading(verdict(1)), _reading(), _reading()]
    outcome = _status(readings)
    assert outcome.status == "disputed" and "offered" in outcome.disputed


def test_the_tie_break_is_asked_only_when_offered_split(monkeypatch):
    from apps.research import funding_judge

    calls = []

    def fake_openai(parser, *, instructions, source_id, data, **_):
        calls.append(instructions[:40])
        return _reading(verdict(1))

    monkeypatch.setattr(funding_judge, "_openai_reading", fake_openai)
    unanimous = [_reading(verdict(1))] * 3
    assert funding_judge.tie_break_offered(
        object(), source_id="s", chunk=PAGE_CHUNK, readings=unanimous
    ) == unanimous
    assert calls == []
    split = [_reading(verdict(1)), _reading(verdict(1)), _reading()]
    out = funding_judge.tie_break_offered(
        object(), source_id="s", chunk=PAGE_CHUNK, readings=split
    )
    assert len(out) == 4 and len(calls) == 1


def test_an_unpayable_tie_break_is_not_asked_and_the_tie_stands(monkeypatch):
    from apps.research import funding_judge

    calls = []
    monkeypatch.setattr(
        funding_judge, "_openai_reading",
        lambda *a, **k: calls.append(1) or _reading(verdict(1)),
    )
    split = [_reading(verdict(1)), _reading(verdict(1)), _reading()]
    out = funding_judge.tie_break_offered(
        object(), source_id="s", chunk=PAGE_CHUNK, readings=split, pay=lambda: False
    )
    assert out == split and calls == []


def test_the_two_openai_readings_share_an_identical_prefix():
    client = _answers(FakeResponse(output_parsed=FundingVerdicts()))
    judge(client, client, source_id="s", chunk=CHUNK)
    first, second, third = client.calls
    assert first["input"][0]["content"] == second["input"][0]["content"]
    users = [call["input"][1]["content"] for call in (first, second)]
    assert users[0].split("\n\nReading ")[0] == users[1].split("\n\nReading ")[0]
    assert users[0] != users[1]
    # Hashed and bounded: the API caps this at 64 characters, and a caller
    # whose source_id is a URL had every OpenAI reading refused with a 400
    # that the reading swallowed as "lost" (measured 2026-09-19).
    key = privacy_safe_identifier("s")
    assert first["prompt_cache_key"] == second["prompt_cache_key"] == key
    assert len(key) <= 64
    # Claude's system block carries the same text and asks for it to be cached.
    (block,) = third["system"]
    assert block["text"] == first["input"][0]["content"]
    assert block["cache_control"] == {"type": "ephemeral"}


def test_the_tie_break_reading_reuses_the_same_cached_prefix(monkeypatch):
    from apps.research import funding_judge

    client = _answers(FakeResponse(output_parsed=_reading(verdict(1))))
    split = [_reading(verdict(1)), _reading(verdict(1)), _reading()]
    funding_judge.tie_break_offered(
        client, source_id="s", chunk=PAGE_CHUNK, readings=split
    )
    (call,) = client.calls
    assert call["input"][0]["content"] == funding_judge._DATA_RULE + funding_judge._QUESTION
    assert "disagreed" in call["input"][1]["content"]


CHEMO = (
    Line("Grants", ""),
    Line(
        "Disclaimer (15/10/2025): the recruitment of the student intake for the academic year "
        "2026-2028 will be without scholarship.",
        "Grants",
    ),
    Line(
        "About 20 Erasmus Mundus scholarships are awarded to the best-ranked applicants each year.",
        "Grants",
    ),
    Line("Applications for the 2028-2030 intake close on 15 January 2028.", "Grants"),
)


def _no(line, **kw):
    return verdict(
        line, offered="NO", kind="I5_FUNDED_DUAL_DEGREE", scope="PROGRAM", money_form="GRANT", **kw
    )


def _yes(line, **kw):
    return verdict(
        line, kind="I5_FUNDED_DUAL_DEGREE", scope="PROGRAM", money_form="GRANT", **kw
    )


def test_a_dated_intake_negation_wins_over_an_undated_yes_for_that_intake():
    readings = [_reading(_no(1, applies_to="2026-2028", stated_on="2025-10-15"), _yes(2))] * 3
    (decision,) = awards(line_outcomes(CHEMO, readings)).decisions
    assert decision.offered == "NO" and decision.applies_to == "2026-2028"
    assert decision.stated_on == "2025-10-15"
    assert "without scholarship" in decision.suspension_quote


def test_equal_specificity_disputes_offered_instead_of_serving():
    readings = [_reading(_no(1), _yes(2))] * 3
    (decision,) = awards(line_outcomes(CHEMO, readings)).decisions
    assert decision.agreement == "UNAGREED" and "offered" in decision.disputed


def test_a_yes_for_another_intake_is_its_own_decision_and_keeps_its_deadline():
    readings = [
        _reading(
            _no(1, applies_to="2026-2028", stated_on="2025-10-15"),
            _yes(3, applies_to="2028-2030", deadline="2028-01-15"),
        )
    ] * 3
    decisions = awards(line_outcomes(CHEMO, readings)).decisions
    assert {(d.offered, d.applies_to, d.deadline) for d in decisions} == {
        ("NO", "2026-2028", "UNSTATED"),
        ("YES", "2028-2030", "2028-01-15"),
    }


def test_the_question_asks_for_intake_date_deadline_and_whose_deadline():
    from apps.research.funding_judge import _QUESTION

    assert "applies_to" in _QUESTION and "stated_on" in _QUESTION and "deadline" in _QUESTION
    assert "deadline_for" in _QUESTION


def test_two_deadlines_for_two_groups_are_both_kept_on_the_award():
    page = (
        Line("Deadlines", ""),
        Line("Applicants from India: 15 October 2026.", "Deadlines"),
        Line("Applicants from Turkiye: 30 November 2026.", "Deadlines"),
    )
    readings = [
        _reading(
            _yes(1, deadline="2026-10-15", deadline_for="applicants from India"),
            _yes(2, deadline="2026-11-30", deadline_for="applicants from Turkiye"),
        )
    ] * 3
    (decision,) = awards(line_outcomes(page, readings)).decisions
    assert set(decision.deadlines) == {
        ("2026-10-15", "applicants from India"),
        ("2026-11-30", "applicants from Turkiye"),
    }


def test_a_date_that_is_not_a_date_is_refused_by_the_schema():
    with pytest.raises(ValidationError):
        verdict(1, stated_on="15/10/2025")
    with pytest.raises(ValidationError):
        verdict(1, deadline="soon")


def test_a_verdict_carries_the_conditions_the_page_states():
    from apps.funding.eligibility import ConditionTriple

    v = verdict(
        1,
        conditions=(
            ConditionTriple(
                key="CITIZENSHIP", operator="IN", value="AZ,TR",
                quote="Open to citizens of Azerbaijan and Türkiye.",
            ),
        ),
    )
    assert v.conditions[0].key == "CITIZENSHIP"


def test_conditions_all_three_readings_agree_on_reach_the_award():
    from apps.funding.eligibility import ConditionTriple

    condition = ConditionTriple(
        key="AGE", operator="LTE", value="35", unit="YEARS", quote="Applicants must be under 35."
    )
    readings = [_reading(verdict(1, conditions=(condition,)))] * 3
    (decision,) = awards(line_outcomes(PAGE_CHUNK, readings)).decisions
    assert decision.conditions == (condition,)
    assert decision.disputed_conditions == ()


def test_a_condition_the_readings_split_on_is_disputed_not_dropped():
    """Tiered agreement: the award still serves; the condition is unconfirmed and
    never filtered on."""
    from apps.funding.eligibility import ConditionTriple

    quote = "Applicants must be under 35."
    strict = ConditionTriple(key="AGE", operator="LTE", value="35", unit="YEARS", quote=quote)
    loose = ConditionTriple(key="AGE", operator="LTE", value="30", unit="YEARS", quote=quote)
    readings = [
        _reading(verdict(1, conditions=(strict,))),
        _reading(verdict(1, conditions=(strict,))),
        _reading(verdict(1, conditions=(loose,))),
    ]
    (decision,) = awards(line_outcomes(PAGE_CHUNK, readings)).decisions
    assert decision.conditions == ()
    assert decision.disputed_conditions == (quote,)
    # The award itself is unaffected -- existence agreed.
    assert decision.agreement == "AGREED"


def test_the_question_names_every_eligibility_key():
    from apps.funding.eligibility import KEYS
    from apps.research.funding_judge import _QUESTION

    for key in KEYS:
        if key in ("OTHER", "OPEN"):
            continue
        assert key in _QUESTION, key


from apps.research.funding_judge import (  # noqa: E402
    claude_system,
    decide,
    needs_tie_break,
    reading_prompts,
    tie_break_data,
)


def test_judge_sends_exactly_the_reading_prompts():
    """The batch path builds its requests from reading_prompts; this pins that
    the synchronous path sends the same bytes."""
    client = FakeResponses(FakeResponse(output_parsed=FundingVerdicts(verdicts=(verdict(1),))))
    judge(client, client, source_id="src-1", chunk=CHUNK)
    instructions, openai_data, claude_data = reading_prompts(CHUNK)
    first, second, third = client.calls
    assert [first["input"], second["input"]] == [
        [{"role": "developer", "content": instructions}, {"role": "user", "content": data}]
        for data in openai_data
    ]
    assert third["system"] == claude_system(instructions)
    assert third["messages"] == [{"role": "user", "content": claude_data}]


def test_the_tie_break_data_trails_the_same_listing():
    _, (first, _), _ = reading_prompts(CHUNK)
    listing = first.rsplit("\n\n", 1)[0]
    assert tie_break_data(CHUNK).startswith(listing + "\n\n")


def test_a_tie_break_is_needed_only_when_three_readings_split_on_offered():
    yes = FundingVerdicts(verdicts=(verdict(1),))
    no = FundingVerdicts(verdicts=(verdict(1, offered="NO"),))
    assert needs_tie_break(CHUNK, [yes, yes, no]) is True
    assert needs_tie_break(CHUNK, [yes, yes, yes]) is False
    assert needs_tie_break(CHUNK, [yes, no]) is False  # two readings abstain; never a tie


def test_decide_is_awards_over_every_chunks_line_outcomes():
    yes = FundingVerdicts(verdicts=(verdict(1),))
    assert decide([CHUNK], [[yes, yes, yes]]) == awards(line_outcomes(CHUNK, [yes, yes, yes]))


import httpx2  # noqa: E402
import openai  # noqa: E402

from apps.research.funding_judge import tie_break_offered  # noqa: E402
from apps.research.model_cost import CostMeter, ReadingTier, ReadingTierRefused  # noqa: E402
from tests.research.conftest import ScriptedReaders  # noqa: E402

_WAIVER = "tuition waiver."


def _status_error(cls, status):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    return cls("refused", response=httpx2.Response(status, request=request), body=None)


class RaisingFirst(FakeResponses):
    """Raises `error` on the first call, then answers like FakeResponses."""

    def __init__(self, error, *responses):
        super().__init__(*responses)
        self.error = error

    def parse(self, **kwargs):
        if not self.calls:
            self.calls.append(kwargs)
            raise self.error
        return super().parse(**kwargs)


def _answer():
    return FakeResponse(output_parsed=FundingVerdicts(verdicts=(verdict(1),)))


def test_every_reading_of_a_chunk_is_metered_by_family():
    client = FakeResponses(_answer())
    meter = CostMeter()
    judge(client, client, source_id="src-1", chunk=CHUNK, meter=meter)
    assert [usage.family for usage in meter.usages] == ["openai", "openai", "claude"]
    assert meter.tokens("openai")["output"] == 34  # FakeResponse reports 17 each
    assert meter.lost == 0


def test_a_call_that_raised_is_lost_and_a_truncated_one_is_still_metered():
    raising = ScriptedReaders({_WAIVER: {}}, fail_calls=(1,))
    meter = CostMeter()
    readings = judge(raising, raising, source_id="src-1", chunk=CHUNK, meter=meter)
    assert len(readings) == 2 and meter.lost == 1 and len(meter.usages) == 2

    truncated = FakeResponses(
        FakeResponse(output_parsed=FundingVerdicts(verdicts=(verdict(1),)), status="incomplete")
    )
    meter = CostMeter()
    readings = judge(truncated, truncated, source_id="src-1", chunk=CHUNK, meter=meter)
    # Both OpenAI readings are dropped as truncated, and both were billed.
    assert len(readings) == 1 and len(meter.usages) == 3


def test_the_tie_break_reading_is_metered_too():
    client = ScriptedReaders({_WAIVER: {}}, {_WAIVER: {}}, {_WAIVER: {"offered": "NO"}})
    meter = CostMeter()
    read_funding(client, client, source_id="src-1", chunks=[CHUNK], meter=meter)
    assert len(meter.usages) == 4


def test_flex_is_asked_for_on_the_openai_readings_only():
    client = FakeResponses(_answer())
    judge(client, client, source_id="src-1", chunk=CHUNK, tier=ReadingTier.FLEX)
    first, second, third = client.calls
    assert first["service_tier"] == second["service_tier"] == "flex"
    assert "service_tier" not in third  # Anthropic has no flex tier


def test_a_standard_reading_names_no_tier():
    client = FakeResponses(_answer())
    judge(client, client, source_id="src-1", chunk=CHUNK)
    assert all("service_tier" not in call for call in client.calls)


def test_flex_without_capacity_is_asked_again_at_default_and_counted():
    parser = RaisingFirst(_status_error(openai.RateLimitError, 429), _answer())
    claude = FakeResponses(_answer())
    meter = CostMeter()
    readings = judge(
        parser, claude, source_id="src-1", chunk=CHUNK, meter=meter, tier=ReadingTier.FLEX
    )
    assert len(readings) == 3 and meter.flex_fallbacks == 1
    assert "service_tier" not in parser.calls[1]


def test_a_flex_request_the_vendor_rejects_stops_the_read_rather_than_losing_it():
    parser = RaisingFirst(_status_error(openai.BadRequestError, 400), _answer())
    claude = FakeResponses(_answer())
    with pytest.raises(ReadingTierRefused):
        read_funding(parser, claude, source_id="src-1", chunks=[CHUNK], tier=ReadingTier.FLEX)


def test_a_standard_bad_request_is_still_one_lost_reading():
    parser = RaisingFirst(_status_error(openai.BadRequestError, 400), _answer())
    claude = FakeResponses(_answer())
    meter = CostMeter()
    readings = judge(parser, claude, source_id="src-1", chunk=CHUNK, meter=meter)
    assert len(readings) == 2 and meter.lost == 1


def test_the_synchronous_path_refuses_the_batch_tier():
    client = FakeResponses(_answer())
    with pytest.raises(ValueError, match="batch_reading"):
        read_funding(client, client, source_id="s", chunks=[CHUNK], tier=ReadingTier.BATCH)


def test_tie_break_offered_passes_meter_and_tier():
    client = ScriptedReaders({_WAIVER: {"offered": "NO"}})
    yes = FundingVerdicts(verdicts=(verdict(1),))
    no = FundingVerdicts(verdicts=(verdict(1, offered="NO"),))
    meter = CostMeter()
    tie_break_offered(
        client, source_id="s", chunk=CHUNK, readings=[yes, yes, no], meter=meter,
        tier=ReadingTier.FLEX,
    )
    assert client.calls[0]["service_tier"] == "flex" and len(meter.usages) == 1


def _off_schema():
    from pydantic import TypeAdapter
    from pydantic import ValidationError as PydanticValidationError

    try:
        TypeAdapter(int).validate_python("not a number")
    except PydanticValidationError as error:
        return error
    raise AssertionError("unreachable")


class RaisingOn(FakeResponses):
    """Raises `error` on the calls numbered in `on` (1-based), answers otherwise."""

    def __init__(self, error, on, *responses):
        super().__init__(*responses)
        self.error, self.on = error, set(on)

    def parse(self, **kwargs):
        if len(self.calls) + 1 in self.on:
            self.calls.append(kwargs)
            raise self.error
        return super().parse(**kwargs)


def test_an_off_schema_openai_reply_is_paid_for_not_lost():
    """The SDK raises ValidationError inside parse() on an off-schema answer
    (JSON cut off at the output cap included); it came back and was billed."""
    parser = RaisingOn(_off_schema(), {1}, _answer())
    meter = CostMeter()
    readings = judge(parser, FakeResponses(_answer()), source_id="s", chunk=CHUNK, meter=meter)
    assert len(readings) == 2
    assert (meter.lost, meter.unmetered, len(meter.usages)) == (0, 1, 2)


def test_an_off_schema_claude_reply_is_paid_for_not_lost():
    claude = RaisingOn(_off_schema(), {1}, _answer())
    meter = CostMeter()
    readings = judge(FakeResponses(_answer()), claude, source_id="s", chunk=CHUNK, meter=meter)
    assert len(readings) == 2
    assert (meter.lost, meter.unmetered, len(meter.usages)) == (0, 1, 2)
