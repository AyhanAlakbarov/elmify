import pytest

from apps.research.engine_eval.chat import ChatAnswer, ChatFailed, Spend, SpendCapReached
from apps.research.engine_eval.chat_reader import read_chat
from apps.research.engine_eval.items import Item
from apps.research.engine_eval.questions import LINE_QUESTIONS

IDS = [q.id for q in LINE_QUESTIONS]


def _keys(n=2):
    return [f"L{k}_{q}" for k in range(1, n + 1) for q in IDS]


ITEMS = [Item(id=f"p0l{n}", page="u", language="tr", scheme="s", half="score",
              text=f"satır {n}", heading="Başlık") for n in range(2)]


def test_probabilities_are_returned_and_the_page_is_the_shared_prefix():
    pages = []

    def chat(reader, *, system, page, question, schema_props, session_id, spend):
        pages.append((page, session_id))
        probs = {k: {"yes": 0.1 if k.startswith("L1_") else 0.7} for k in schema_props}
        return ChatAnswer({k: "no" for k in schema_props}, probs, 0.0001, 100, 0, ok=True)
    got = read_chat("ds_flash", ITEMS, Spend(1.0), chat=chat, page_text={"u": "P"})
    assert set(got) == {"p0l0", "p0l1"}
    assert got["p0l0"]["level_rule"] == 0.1 and got["p0l1"]["level_rule"] == 0.7
    assert pages == [("P", pages[0][1])]  # both lines in one call, the page as the prefix


def test_an_unsure_answer_leaves_the_item_out():
    def chat(reader, **kw):
        return ChatAnswer({}, {}, 0.0, 0, 30, ok=False, reason="reasoning_tokens")
    assert read_chat("ds_flash", ITEMS, Spend(1.0), chat=chat, page_text={"u": "P"}) == {}


def test_no_logprobs_becomes_a_marked_vote():
    def chat(reader, **kw):
        return ChatAnswer({k: "yes" for k in _keys()}, {k: None for k in _keys()}, 0.0, 0, 0,
                          ok=True)
    got = read_chat("gemini_flash", ITEMS, Spend(1.0), chat=chat, page_text={"u": "P"})
    assert got["p0l1"]["level_rule"] == 1.0 and got["p0l1"]["_vote"] is True


def test_chat_failed_on_one_page_leaves_its_lines_out():
    other = Item(id="p1l0", page="v", language="tr", scheme="s", half="score", text="x",
                 heading="")

    def chat(reader, *, page, schema_props, **kw):
        if page == "P":
            raise ChatFailed("Timeout")
        return ChatAnswer({k: "yes" for k in schema_props}, {k: {"yes": 0.9} for k in schema_props},
                          0.0, 0, 0, ok=True)
    got = read_chat("ds_flash", [*ITEMS, other], Spend(1.0), chat=chat,
                    page_text={"u": "P", "v": "V"})
    assert set(got) == {"p1l0"}


def test_spend_cap_reached_propagates():
    def chat(reader, **kw):
        raise SpendCapReached(0.0, 1.0)
    with pytest.raises(SpendCapReached):
        read_chat("ds_flash", ITEMS, Spend(1.0), chat=chat, page_text={"u": "P"})
