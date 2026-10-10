import pytest

from apps.research.decisions import Answer
from apps.research.engine_eval.items import Item
from apps.research.engine_eval.jev_reader import jev_cost_usd, read_jev

ITEMS = [Item(id=f"p0l{n}", page="u", language="en", scheme="s", half="tune",
              text=("Holders receive 43,000 HUF monthly." if n == 0 else f"Line {n}."),
              heading="Coverage") for n in range(3)]


def _client(order_flip=False):
    seen = []

    def client(state, questions, *, model, provider):
        seen.append(state)
        out = {}
        for qid, q in questions.items():
            if qid.startswith("amt|"):
                reverse = qid.endswith("|rev")
                value = "fee_charged_to_student" if (reverse and order_flip) else "paid_to_student"
                conf = 0.9 if reverse else 0.95
                out[qid] = Answer(id=qid, value=value, confidence=conf,
                                  probabilities={value: conf, "other": 1 - conf},
                                  model=model, provider=provider, input_tokens=10)
            else:
                out[qid] = Answer(id=qid, value=True, confidence=0.8,
                                  probabilities={"true": 0.8, "false": 0.2},
                                  model=model, provider=provider, input_tokens=10)
        return out
    return client, seen


def test_heading_travels_as_its_own_key_and_amounts_are_keyed():
    client, seen = _client()
    read_jev(ITEMS, wording="a", client=client)
    state = seen[0]
    assert state["lines"]["p0l0"] == {"heading": "Coverage", "text": ITEMS[0].text}
    assert any(v == "43,000 HUF" for v in state["amounts"].values())


def test_order_swapped_pair_averages_the_two_distributions():
    client, _ = _client()
    got = read_jev(ITEMS, wording="a", client=client)
    role = got["p0l0"]["_amounts"]["p0l0_m0"]
    assert role["value"] == "paid_to_student" and role["agree"] is True
    assert role["conf"] == pytest.approx((0.95 + 0.9) / 2)


def test_order_swapped_pair_that_disagrees_is_flagged():
    client, _ = _client(order_flip=True)
    got = read_jev(ITEMS, wording="a", client=client)
    assert got["p0l0"]["_amounts"]["p0l0_m0"]["agree"] is False


def test_every_line_question_gets_a_probability():
    client, _ = _client()
    got = read_jev(ITEMS, wording="a", client=client)
    assert got["p0l2"]["level_rule"] == 0.8


def test_a_small_token_budget_splits_a_page_into_several_requests():
    client, seen = _client()
    got = read_jev(ITEMS, wording="a", client=client, max_tokens=1)
    assert len(seen) == 3 and set(got) == {"p0l0", "p0l1", "p0l2"}


def test_cost_is_per_million_tokens():
    assert jev_cost_usd(1_000_000) == pytest.approx(0.042)


def test_a_spent_cap_stops_jev_before_any_call():
    from apps.research.engine_eval.chat import Spend, SpendCapReached
    client, seen = _client()
    with pytest.raises(SpendCapReached):
        read_jev(ITEMS, wording="a", client=client, spend=Spend(cap_usd=0.5, spent_usd=0.5))
    assert seen == []


def test_jev_spend_grows_by_the_cost_of_the_request_tokens():
    from apps.research.decisions import Answer as A
    from apps.research.engine_eval.chat import Spend

    def client(state, questions, *, model, provider):
        first = True
        out = {}
        for qid in questions:  # the request's tokens sit on its first answer only
            out[qid] = A(id=qid, value=True, confidence=0.8, probabilities={"true": 0.8},
                         model=model, provider=provider, input_tokens=1_000_000 if first else 0)
            first = False
        return out
    spend = Spend(cap_usd=100.0)
    read_jev(ITEMS, wording="a", client=client, spend=spend)
    assert spend.spent_usd == pytest.approx(jev_cost_usd(1_000_000))


def test_jev_charges_its_estimate_when_ask_raises():
    from apps.research.decisions import _estimate_tokens
    from apps.research.engine_eval.chat import Spend
    from apps.research.engine_eval.jev_reader import _request

    def client(state, questions, *, model, provider):
        raise TimeoutError("host down")
    spend = Spend(cap_usd=100.0)
    with pytest.raises(TimeoutError):
        read_jev(ITEMS, wording="a", client=client, spend=spend)
    assert spend.spent_usd == pytest.approx(
        jev_cost_usd(_estimate_tokens(*_request(ITEMS, "a"))))
    assert spend.spent_usd > 0
