from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudget,
    DecisionsUnavailable,
    Noul,
    ask,
    month_tokens_spent,
    run_budget,
)
from apps.research.models import DecisionRecord

pytestmark = pytest.mark.django_db

_SERVED = "typesafe/jev-1.13-20260917"


def _client(calls, value="cv", confidence=0.97):
    def call(state, questions, *, model, provider):
        calls.append(dict(questions))
        return {
            qid: Answer(id=qid, value=value, confidence=confidence,
                        probabilities={value: confidence}, model=model,
                        provider=provider, input_tokens=100, served_model=_SERVED)
            for qid in questions
        }

    return call


_Q = {"document": Choice(question="Which document?", options=("cv", "motivation_letter"))}


def test_the_same_state_and_questions_are_asked_once():
    """The saving that makes page-level triage affordable: a faculty-wide
    requirements page linked by thirty programmes is decided once."""
    calls = []
    first = ask({"text": "A CV is required."}, _Q, decision="D6", client=_client(calls))
    second = ask({"text": "A CV is required."}, _Q, decision="D6", client=_client(calls))
    assert len(calls) == 1
    assert second["document"].value == first["document"].value
    assert second["document"].confidence == pytest.approx(first["document"].confidence)
    assert second["document"].served_model == _SERVED


def test_a_different_state_is_a_different_question():
    calls = []
    ask({"text": "A CV is required."}, _Q, decision="D6", client=_client(calls))
    ask({"text": "A letter is required."}, _Q, decision="D6", client=_client(calls))
    assert len(calls) == 2


def test_rewording_a_question_invalidates_the_cached_answer():
    """The digest covers the whole question map. A question whose wording
    changed is a different question, and reading the old answer would silently
    report a measurement that was never made."""
    calls = []
    ask({"text": "x"}, _Q, decision="D6", client=_client(calls))
    reworded = {"document": Choice(question="Which document is meant?",
                                   options=("cv", "motivation_letter"))}
    ask({"text": "x"}, reworded, decision="D6", client=_client(calls))
    assert len(calls) == 2


# <!-- review focus 4 -->
def test_a_new_model_version_invalidates_the_cached_answer(settings):
    calls = []
    ask({"text": "x"}, _Q, decision="D6", client=_client(calls))
    settings.TYPESAFE_MODEL = "typesafe/jev-1.14"
    ask({"text": "x"}, _Q, decision="D6", client=_client(calls))
    assert len(calls) == 2


def test_every_answer_is_recorded_with_its_probabilities():
    ask({"text": "A CV is required."}, _Q, decision="D6", language="en",
        client=_client([]))
    row = DecisionRecord.objects.get()
    assert (row.decision, row.question_id, row.value) == ("D6", "document", "cv")
    assert row.probabilities == {"cv": pytest.approx(0.97)}
    assert (row.model, row.provider, row.language) == ("typesafe/jev-1.13", "typesafe", "en")
    assert row.served_model == _SERVED
    assert row.refused is False


def test_recording_can_be_turned_off_for_a_measurement_run():
    """§11's gates re-ask the same questions many times deliberately; a cache
    would turn 15 repeats into one answer and 15 identical rows."""
    calls = []
    ask({"text": "x"}, _Q, decision="D6", record=False, client=_client(calls))
    ask({"text": "x"}, _Q, decision="D6", record=False, client=_client(calls))
    assert len(calls) == 2
    assert DecisionRecord.objects.count() == 0


def test_the_month_ceiling_is_read_from_the_rows():
    for _ in range(3):
        DecisionRecord.objects.create(
            state_digest=f"{_}" * 64, question_digest="b" * 64, decision="D6",
            question_id="q", value="cv", confidence=0.9, probabilities={},
            model="typesafe/jev-1.13", provider="typesafe", input_tokens=1_000,
        )
    old = DecisionRecord.objects.create(
        state_digest="old" * 21 + "d", question_digest="b" * 64, decision="D6",
        question_id="q", value="cv", confidence=0.9, probabilities={},
        model="typesafe/jev-1.13", provider="typesafe", input_tokens=9_999,
    )
    DecisionRecord.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    assert month_tokens_spent() == 3_000


def test_a_run_budget_is_the_smaller_of_the_run_and_what_is_left_this_month(settings):
    settings.DECISIONS_RUN_TOKENS = 5_000
    settings.DECISIONS_MONTHLY_TOKENS = 6_000
    DecisionRecord.objects.create(
        state_digest="a" * 64, question_digest="b" * 64, decision="D6", question_id="q",
        value="cv", confidence=0.9, probabilities={}, model="typesafe/jev-1.13",
        provider="typesafe", input_tokens=4_000,
    )
    assert run_budget().limit_tokens == 2_000


def test_an_unavailable_provider_is_not_swallowed_and_is_asked_again():
    """§9a / addendum 5.1: a failure reschedules the read through the fetch
    engine's retry queue. It never becomes 'this page states no rule', and it
    is never cached -- the next read asks again."""
    calls = []

    def down(*args, **kwargs):
        calls.append(1)
        raise DecisionsUnavailable("typesafe: TypeSafeAPIConnectionError")

    for _ in range(2):
        with pytest.raises(DecisionsUnavailable) as raised:
            ask({"text": "x"}, _Q, decision="D6", client=down)
        assert raised.value.kind == "failed"
    assert len(calls) == 2
    assert DecisionRecord.objects.count() == 0


# <!-- review focus 3 -->
def test_a_partial_answer_leaves_no_row_and_is_asked_again():
    """A page reads several questions in one call; if the provider answers
    some and drops the rest, that is a provider failure, not a partial rule
    set (Task 10's caller rolls the whole page read back on this). Nothing
    from the partial answer may reach the cache, or the next read would see a
    full hit built from an answer that was never actually given for every
    question."""
    two_questions = {
        "document": Choice(question="Which document?", options=("cv", "motivation_letter")),
        "pages": Choice(question="How many pages?", options=("one", "two")),
    }
    calls = []

    def half(state, questions, *, model, provider):
        calls.append(1)
        # Only ever answers "document", dropping "pages" -- exactly the shape
        # of a provider that answered the first request and failed the second.
        return {"document": Answer(id="document", value="cv", confidence=0.9,
                                    probabilities={"cv": 0.9}, model=model,
                                    provider=provider, input_tokens=50,
                                    served_model=_SERVED)}

    for _ in range(2):
        with pytest.raises(DecisionsUnavailable) as raised:
            ask({"text": "x"}, two_questions, decision="D6", client=half)
        assert raised.value.kind == "failed"
    assert len(calls) == 2
    assert DecisionRecord.objects.count() == 0


def test_a_skipped_question_still_spends_its_answered_tokens_from_the_budget():
    """A reply that skips a question still burned tokens on the question(s) it
    DID answer. Charging the budget only on a full set lets a provider that
    always drops the last question spend real tokens forever while `ask()`
    reports `failed` every time and the run budget never notices."""
    two_questions = {
        "document": Choice(question="Which document?", options=("cv", "motivation_letter")),
        "pages": Choice(question="How many pages?", options=("one", "two")),
    }

    def half(state, questions, *, model, provider):
        return {"document": Answer(id="document", value="cv", confidence=0.9,
                                    probabilities={"cv": 0.9}, model=model,
                                    provider=provider, input_tokens=75,
                                    served_model=_SERVED)}

    budget = DecisionBudget()
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, two_questions, decision="D6", client=half, budget=budget)
    assert raised.value.kind == "failed"
    assert budget.spent == 75


def test_a_refusal_is_recorded_and_never_asked_again():
    """Addendum 5.1: a model that is refusing, as opposed to failing, is
    recorded as a refusal and not retried. The record is what makes 'not
    retried' survive the next run; a new pin or a reworded question asks afresh."""
    calls = []

    def refuse(state, questions, *, model, provider):
        calls.append(1)
        raise DecisionsUnavailable("typesafe: TypeSafePermissionDeniedError 403 (refused)",
                                   kind="refused")

    for _ in range(2):
        with pytest.raises(DecisionsUnavailable) as raised:
            ask({"text": "x"}, _Q, decision="D6", client=refuse)
        assert raised.value.kind == "refused"
    assert len(calls) == 1
    row = DecisionRecord.objects.get()
    assert (row.refused, row.value, row.input_tokens) == (True, "", 0)


def test_a_cached_answer_serves_without_a_key(settings):
    """No key degrades cost, not correctness (addendum 5.1): what is already
    decided keeps serving, and only an uncached state raises not_configured."""
    ask({"text": "x"}, _Q, decision="D6", client=_client([]))
    settings.DECISIONS_BASE_URL = "https://openrouter.ai/api"
    settings.OPENROUTER_API_KEY = ""
    assert ask({"text": "x"}, _Q, decision="D6")["document"].value == "cv"
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "never asked"}, _Q, decision="D6")
    assert raised.value.kind == "not_configured"


def test_a_noul_round_trips_through_the_cache():
    calls = []
    question = {"q": Noul(question="Is it required?")}
    ask({"text": "x"}, question, decision="D6", client=_client(calls, value=True))
    again = ask({"text": "x"}, question, decision="D6", client=_client(calls, value=True))
    assert len(calls) == 1
    assert again["q"].value is True
