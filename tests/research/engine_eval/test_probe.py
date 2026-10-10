from apps.research.engine_eval.chat import ChatAnswer, ChatFailed, Reader, Spend
from apps.research.engine_eval.probe import probe

R = Reader("deepseek/deepseek-v4-pro", "somehost", "off")


def _chat(values, *, cached=(0, 2000), probs=True, reasoning=0):
    calls = iter(range(2))

    def chat(reader, *, schema_props, **kw):
        n = next(calls)
        key = next(iter(schema_props))
        return ChatAnswer({key: values[n]}, {key: ({values[n]: 0.99} if probs else None)},
                          0.0001, cached[n], reasoning, ok=reasoning == 0,
                          reason="" if reasoning == 0 else "reasoning_tokens")
    return chat


def test_a_host_that_answers_right_caches_and_returns_probabilities_is_accepted():
    r = probe(R, Spend(1.0), chat=_chat(["paid_to_student", "monthly"]))
    assert r.accepted and r.answered_right and r.cached_on_second and r.logprobs_every_call


def test_the_wrong_answer_on_the_control_item_rejects_the_host():
    r = probe(R, Spend(1.0), chat=_chat(["unstated", "monthly"]))
    assert not r.accepted and not r.answered_right


def test_no_cache_hit_rejects_the_host():
    r = probe(R, Spend(1.0), chat=_chat(["paid_to_student", "monthly"], cached=(0, 0)))
    assert not r.accepted


def test_reasoning_tokens_reject_the_host():
    r = probe(R, Spend(1.0), chat=_chat(["paid_to_student", "monthly"], reasoning=30))
    assert not r.accepted


def test_chat_failed_on_first_call_returns_accepted_false():
    def chat_raises_first(reader, *, schema_props, **kw):
        raise ChatFailed("HTTP 400: Reasoning is mandatory for this endpoint")

    r = probe(R, Spend(1.0), chat=chat_raises_first)
    assert not r.accepted
    assert "ChatFailed" in r.notes or "HTTP 400" in r.notes
