import math

import pytest

from apps.research.engine_eval.chat import (
    Reader,
    Spend,
    SpendCapReached,
    chat_json,
    check_first_tokens,
)

DS = Reader(model="deepseek/deepseek-v4-pro", host="fireworks", thinking="off")


def _reply(content: str, tokens: list[tuple[str, list[tuple[str, float]]]], *, reasoning=0,
           finish="stop", cost=0.0001, cached=2000):
    return {
        "choices": [{
            "finish_reason": finish,
            "message": {"content": content},
            "logprobs": {"content": [
                {"token": t, "logprob": math.log(dict(alts).get(t, 0.5) or 1e-9),
                 "top_logprobs": [{"token": a, "logprob": math.log(p)} for a, p in alts]}
                for t, alts in tokens]},
        }],
        "usage": {"cost": cost, "prompt_tokens_details": {"cached_tokens": cached},
                  "completion_tokens_details": {"reasoning_tokens": reasoning}},
    }


def test_probability_is_read_at_the_value_token_not_at_a_key_token():
    # "no_funding" as a key starts with the token "no": the old spike read it as an answer.
    content = '{"no_funding": "yes", "level": "no"}'
    tokens = [('{"', [('{"', 1.0)]), ("no", [("no", 1.0)]), ("_funding", [("_funding", 1.0)]),
              ('": "', [('": "', 1.0)]), ("yes", [("yes", 0.9), ("no", 0.1)]),
              ('", "', [('", "', 1.0)]), ("level", [("level", 1.0)]), ('": "', [('": "', 1.0)]),
              ("no", [("no", 0.8), ("yes", 0.2)]), ('"}', [('"}', 1.0)])]
    post = lambda url, **kw: _reply(content, tokens)  # noqa: E731
    got = chat_json(DS, system="s", page="p", question="q",
                    schema_props={"no_funding": ["yes", "no"], "level": ["yes", "no"]},
                    session_id="x", spend=Spend(cap_usd=1.0), post=post)
    assert got.ok and got.values == {"no_funding": "yes", "level": "no"}
    assert got.probs["no_funding"] == pytest.approx({"yes": 0.9, "no": 0.1})
    assert got.probs["level"] == pytest.approx({"no": 0.8, "yes": 0.2})


def test_reasoning_tokens_make_the_answer_unsure():
    post = lambda url, **kw: _reply('{"a": "yes"}', [("yes", [("yes", 1.0)])], reasoning=40)  # noqa: E731
    got = chat_json(DS, system="s", page="p", question="q", schema_props={"a": ["yes", "no"]},
                    session_id="x", spend=Spend(cap_usd=1.0), post=post)
    assert not got.ok and got.reason == "reasoning_tokens"


def test_request_pins_the_host_and_turns_thinking_off():
    seen = {}

    def post(url, *, payload, headers, read_timeout=None):
        seen.update(payload)
        return _reply('{"a": "no"}', [("no", [("no", 1.0)])])
    chat_json(DS, system="sys", page="PAGE", question="Q", schema_props={"a": ["yes", "no"]},
              session_id="sid", spend=Spend(cap_usd=1.0), post=post)
    assert seen["provider"] == {"only": ["fireworks"], "allow_fallbacks": False,
                                "require_parameters": True}
    assert seen["reasoning"] == {"enabled": False}
    assert seen["top_logprobs"] == 5 and seen["session_id"] == "sid"
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "user"]
    assert "PAGE" in seen["messages"][1]["content"] and seen["messages"][2]["content"] == "Q"


def test_spend_cap_stops_before_the_call():
    spend = Spend(cap_usd=0.01, spent_usd=0.01)
    called = []
    with pytest.raises(SpendCapReached):
        chat_json(DS, system="s", page="p", question="q", schema_props={"a": ["yes", "no"]},
                  session_id="x", spend=spend, post=lambda *a, **k: called.append(1))
    assert called == []


def test_options_sharing_a_first_token_are_refused():
    with pytest.raises(ValueError):
        check_first_tokens(["not_stated", "none"])
    check_first_tokens(["paid_to_student", "fee_charged_to_student", "unstated"])


def test_a_thinking_reader_gets_no_logprobs_room_for_reasoning_and_may_reason():
    seen = {}

    def post(url, *, payload, headers, read_timeout=None):
        seen.update(payload)
        return _reply('{"a": "yes"}', [("yes", [("yes", 1.0)])], reasoning=40)
    thinker = Reader(model="m", host=None, thinking="medium")
    got = chat_json(thinker, system="s", page="p", question="q", schema_props={"a": ["yes", "no"]},
                    session_id="x", spend=Spend(cap_usd=1.0), post=post)
    assert "logprobs" not in seen and "top_logprobs" not in seen
    assert seen["max_tokens"] == 16000
    assert got.ok and got.values == {"a": "yes"} and got.reasoning_tokens == 40


def _failing(*a, **k):
    raise TimeoutError("secret-in-message")


def _call(spend, post):
    from apps.research.engine_eval.chat import ChatFailed
    try:
        chat_json(DS, system="s", page="p", question="q", schema_props={"a": ["yes", "no"]},
                  session_id="x", spend=spend, post=post)
    except ChatFailed:
        pass


def test_three_unmetered_calls_in_a_row_stop_the_run():
    spend = Spend(cap_usd=100.0)
    _call(spend, _failing)
    _call(spend, _failing)
    with pytest.raises(SpendCapReached, match="3 consecutive unmetered"):
        _call(spend, _failing)


def test_a_response_with_no_cost_counts_as_unmetered():
    spend = Spend(cap_usd=100.0)
    no_cost = lambda *a, **k: {"choices": [{}], "usage": {}}  # noqa: E731
    _call(spend, no_cost)
    _call(spend, no_cost)
    with pytest.raises(SpendCapReached):
        _call(spend, no_cost)


def test_a_metered_success_resets_the_unmetered_count():
    spend = Spend(cap_usd=100.0)
    ok = lambda *a, **k: _reply('{"a": "no"}', [("no", [("no", 1.0)])])  # noqa: E731
    _call(spend, _failing)
    _call(spend, _failing)
    _call(spend, ok)
    _call(spend, _failing)
    _call(spend, _failing)  # two since the reset: no stop
    assert spend.unmetered == 2
