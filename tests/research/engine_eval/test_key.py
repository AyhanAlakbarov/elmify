from collections import Counter

import pytest

from apps.research.engine_eval.chat import ChatAnswer, ChatFailed, Spend, SpendCapReached
from apps.research.engine_eval.items import Item
from apps.research.engine_eval.key import LABELLERS, LINES_PER_CALL, REFEREE, build_key, label_lines
from apps.research.engine_eval.questions import LINE_QUESTIONS

IDS = [q.id for q in LINE_QUESTIONS]


def _item(n):
    return Item(id=f"p0l{n}", page="u", language="en", scheme="s", half="tune",
                text=f"t{n}", heading="")


def _per_line(fn):
    """A batch labeller built from a per-line rule; None leaves that line unanswered."""
    def label(reader, items, spend, chat=None):
        rows = {i.id: fn(reader, i) for i in items}
        return {k: v for k, v in rows.items() if v is not None}
    return label


def test_agreement_enters_the_key_and_disputes_go_to_the_referee():
    calls = []

    def rule(reader, item):
        calls.append((reader.model, item.id))
        yes = reader is LABELLERS[0] or reader is REFEREE
        return {q: (yes if (q == "level_rule" and item.id == "p0l0") else False) for q in IDS}
    key = build_key([_item(0), _item(1)], Spend(5.0), label=_per_line(rule), audit_share=0.0)
    assert key["p0l0"]["level_rule"] is True          # referee sided with labeller 0
    assert key["p0l1"]["level_rule"] is False         # agreed
    assert (REFEREE.model, "p0l0") in calls and (REFEREE.model, "p0l1") not in calls


def test_an_unanswered_item_is_left_out_of_the_key_not_guessed():
    rows = _per_line(lambda r, i: None if i.id == "p0l1" else {q: False for q in IDS})
    key = build_key([_item(0), _item(1)], Spend(5.0), label=rows, audit_share=0.0)
    assert set(key) == {"p0l0"}


def test_audit_sends_a_share_of_agreements_to_the_referee_and_counts_overturns():
    stats: Counter[str] = Counter()
    key = build_key([_item(n) for n in range(20)], Spend(5.0), audit_share=0.5, stats=stats,
                    label=_per_line(lambda r, i: {q: (r is REFEREE) for q in IDS}))
    assert stats["audited"] >= 5 and stats["audit_overturned"] == stats["audited"]
    # audit reports, never edits
    assert all(v is False for row in key.values() for v in row.values())


def test_each_line_of_a_call_is_read_from_its_own_answer_keys():
    seen = {}

    def chat(reader, **kwargs):
        seen.update(kwargs)
        values = {k: ("yes" if k == f"L2_{IDS[0]}" else "no") for k in kwargs["schema_props"]}
        return ChatAnswer(values=values, probs={}, cost_usd=0.0, cached_tokens=0,
                          reasoning_tokens=0, ok=True)
    rows = label_lines(LABELLERS[0], [_item(0), _item(1)], Spend(5.0), chat=chat)
    assert rows["p0l1"][IDS[0]] is True and rows["p0l0"][IDS[0]] is False
    assert len(seen["schema_props"]) == 2 * len(IDS) and "L2 (heading: -): t1" in seen["page"]


def test_one_call_carries_at_most_its_line_count_and_never_two_pages():
    sizes = []

    def label(reader, items, spend, chat=None):
        if reader is LABELLERS[0]:
            sizes.append((len(items), {i.page for i in items}))
        return {i.id: {q: False for q in IDS} for i in items}
    other = Item(id="p1l0", page="v", language="en", scheme="s", half="tune", text="x", heading="")
    build_key([_item(n) for n in range(LINES_PER_CALL + 3)] + [other], Spend(5.0), label=label,
              audit_share=0.0)
    assert sizes == [(LINES_PER_CALL, {"u"}), (3, {"u"}), (1, {"v"})]


def test_a_transport_failure_leaves_that_call_out_and_keeps_the_rest():
    def chat(reader, **kwargs):
        if kwargs["session_id"] == "key-p1l0":
            raise ChatFailed("Timeout")
        values = {k: "no" for k in kwargs["schema_props"]}
        return ChatAnswer(values=values, probs={}, cost_usd=0.0, cached_tokens=0,
                          reasoning_tokens=0, ok=True)
    other = Item(id="p1l0", page="v", language="en", scheme="s", half="tune", text="x", heading="")
    key = build_key([_item(0), other], Spend(5.0), audit_share=0.0,
                    label=lambda reader, items, spend: label_lines(reader, items, spend, chat=chat))
    assert set(key) == {"p0l0"}


def test_the_spend_cap_still_propagates():
    def chat(reader, **kwargs):
        raise SpendCapReached("cap")
    with pytest.raises(SpendCapReached):
        label_lines(LABELLERS[0], [_item(0)], Spend(5.0), chat=chat)


def test_the_second_labeller_is_not_called_for_lines_the_first_left_unanswered():
    calls = []

    def label(reader, items, spend, chat=None):
        calls.append((reader.model, [i.id for i in items]))
        return {}
    assert build_key([_item(0)], Spend(5.0), label=label, audit_share=0.0) == {}
    assert calls == [(LABELLERS[0].model, ["p0l0"]), (LABELLERS[1].model, [])]


def test_the_referee_pools_lines_from_several_calls():
    ref_calls = []

    def label(reader, items, spend, chat=None):
        if reader is REFEREE:
            ref_calls.append(len(items))
        # labeller 0 says yes on every line, labeller 1 no: every line is disputed
        return {i.id: {q: reader is not LABELLERS[1] for q in IDS} for i in items}
    items = [Item(id=f"p{n}l0", page=f"u{n}", language="en", scheme="s", half="tune", text="x",
                  heading="") for n in range(LINES_PER_CALL + 2)]
    key = build_key(items, Spend(5.0), label=label, audit_share=0.0)
    assert ref_calls == [LINES_PER_CALL, 2]  # ten one-line pages, two referee calls
    assert len(key) == LINES_PER_CALL + 2
