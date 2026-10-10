"""The one Jev client: OpenRouter's System One route, a pinned model, page text only."""

import os

import pytest
from django.conf import settings as django_settings

from apps.research.jev import JevUnavailable, ask, jev_url

QUESTIONS = {
    "s0": {
        "type": "noul",
        "instructions": {
            "question": "Does this sentence state a fee?",
            "inspect": "`sentences[0]`",
        },
    }
}


def _post(reply, sent):
    def post(url, *, payload, headers):
        sent.append({"url": url, "payload": payload, "headers": headers})
        return reply
    return post


def test_the_call_goes_to_openrouter_with_the_pinned_model(settings) -> None:
    settings.JEV_API_KEY = "k"
    sent: list[dict] = []
    reply = ask(
        {"sentences": ["An application fee of 50 EUR applies."]}, QUESTIONS,
        post=_post({"model": "typesafe/jev-1.13.0", "answers": {"s0": {"noul": 0.97}},
                    "usage": {"input_tokens": 40}}, sent),
    )
    assert sent[0]["url"] == "https://openrouter.ai/api/v1/systemone" == jev_url()
    assert sent[0]["headers"] == {"Authorization": "Bearer k"}
    assert sent[0]["payload"]["model"] == "jev-1.13"
    assert sent[0]["payload"]["state"] == {"sentences": ["An application fee of 50 EUR applies."]}
    assert (reply.answers, reply.model, reply.input_tokens) == (
        {"s0": {"noul": 0.97}}, "typesafe/jev-1.13.0", 40,
    )


def test_no_key_is_unavailable_and_nothing_is_sent(settings) -> None:
    settings.JEV_API_KEY = ""
    sent: list[dict] = []
    with pytest.raises(JevUnavailable, match="OPENROUTER_API_KEY"):
        ask({"sentences": []}, QUESTIONS, post=_post({}, sent))
    assert sent == []


def test_a_transport_failure_never_carries_the_key(settings) -> None:
    settings.JEV_API_KEY = "secret-key"

    def broken(url, *, payload, headers):
        raise RuntimeError(f"529 for {headers['Authorization']}")

    with pytest.raises(JevUnavailable) as raised:
        ask({"sentences": []}, QUESTIONS, post=broken)
    assert "secret-key" not in str(raised.value)


def test_a_reply_without_answers_is_unavailable(settings) -> None:
    settings.JEV_API_KEY = "k"
    with pytest.raises(JevUnavailable, match="no answers"):
        ask({"sentences": []}, QUESTIONS, post=_post({"model": "jev-1.13"}, []))


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
def test_live_openrouter_serves_the_pinned_jev_model() -> None:
    """Run by hand with -m live. Synthetic page text only; no student data."""
    reply = ask({"sentences": ["An application fee of 50 EUR applies."]}, QUESTIONS)
    assert django_settings.JEV_MODEL in reply.model
    assert 0.0 <= float(reply.answers["s0"]["noul"]) <= 1.0
