import json

import httpx2
import pytest
import system_one_adapter
import typesafe_sdk

from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudget,
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    Noul,
    _estimate_tokens,
    ask,
    provider_for,
)

#: Task 3 makes ask() read and write the DecisionRecord cache by default, so
#: every test that calls it touches the database from Task 3 on. Harmless now.
pytestmark = pytest.mark.django_db

_SERVED = "typesafe/jev-1.13-20260917"


def _client(answers):
    """A scripted client: question id -> (value, confidence, probabilities)."""

    def call(state, questions, *, model, provider):
        return {
            qid: Answer(
                id=qid,
                value=answers[qid][0],
                confidence=answers[qid][1],
                probabilities=answers[qid][2],
                model=model,
                provider=provider,
                input_tokens=10,
            )
            for qid in questions
        }

    return call


def _response(answers, tokens=42):
    """A real SDK response object, as the transport would decode one."""
    return typesafe_sdk.SystemOneResponse.model_validate_json(
        json.dumps(
            {
                "model": _SERVED,
                "usage": {"input_tokens": tokens, "output_tokens": 0},
                "answers": answers,
            }
        )
    )


@pytest.fixture
def sdk(monkeypatch):
    """Stand in for typesafe_sdk.TypeSafeClient: record how it was built and
    called, and answer (or raise) whatever the test hands it."""

    def install(outcome):
        seen = {}

        class FakeClient:
            def __init__(self, **kwargs):
                seen["client"] = kwargs

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def system_one(self, **kwargs):
                seen["call"] = kwargs
                if isinstance(outcome, BaseException):
                    raise outcome
                return outcome

        monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", FakeClient)
        return seen

    return install


@pytest.fixture
def openrouter(settings):
    settings.DECISIONS_BASE_URL = "https://openrouter.ai/api"
    settings.OPENROUTER_API_KEY = "or-test-key"
    settings.TYPESAFE_API_KEY = "ts-must-not-be-sent"
    settings.TYPESAFE_MODEL = "typesafe/jev-1.13"
    settings.DECISIONS_PROVIDER = {"default": "typesafe"}
    return settings


def test_a_choice_comes_back_with_its_probabilities():
    questions = {
        "document": Choice(
            question="Which document is this about?",
            options=("cv", "motivation_letter"),
        )
    }
    answers = ask(
        {"text": "Your CV may not exceed two pages."},
        questions,
        decision="D6",
        client=_client({"document": ("cv", 0.97, {"cv": 0.97, "motivation_letter": 0.03})}),
    )
    assert answers["document"].value == "cv"
    assert answers["document"].confidence == pytest.approx(0.97)
    assert answers["document"].probabilities["motivation_letter"] == pytest.approx(0.03)


def test_a_noul_answers_true_or_false_with_its_probability():
    questions = {"third_party": Noul(question="Is this somebody else's document?")}
    answers = ask(
        {"text": "Short CV from this academic supervisor."},
        questions,
        decision="D6",
        client=_client({"third_party": (True, 0.91, {"true": 0.91, "false": 0.09})}),
    )
    assert answers["third_party"].value is True
    assert answers["third_party"].confidence == pytest.approx(0.91)


def test_a_choice_refuses_more_than_the_documented_option_ceiling():
    """TypeSafe's Choice takes at most 255 options (spec 3.1). A question built
    over a longer list is a programming error, caught here rather than as a
    vendor 400 in production."""
    with pytest.raises(ValueError, match="255"):
        Choice(question="which?", options=tuple(str(i) for i in range(256)))


def test_a_question_with_no_options_is_refused():
    with pytest.raises(ValueError, match="at least two"):
        Choice(question="which?", options=("only",))


def test_a_choice_refuses_a_description_for_an_option_it_does_not_have():
    """The SDK has no option list -- the options ARE the criteria keys -- so a
    stray description would become a phantom option the model could pick."""
    with pytest.raises(ValueError, match="do not exist"):
        Choice(question="which?", options=("a", "b"), criteria={"c": "not an option"})


def test_a_noul_criteria_is_keyed_true_and_false_only():
    """Any other key is a silent no-op on the vendor's side, which is worse
    than an error: a `what` description nobody reads looks like guidance."""
    with pytest.raises(ValueError, match="true"):
        Noul(question="is it?", criteria={"what": "..."})
    Noul(question="is it?", criteria={"true": "yes when", "false": "no when"})


def test_a_question_points_at_a_named_part_of_the_state():
    """The vendor's `inspect` field, and the fix for prose indirection."""
    from apps.research.decisions import instructions_of

    plain = Noul(question="Is it about the CV?")
    pointed = Noul(question="Is it about the CV?", inspect="`sentences[3]`",
                   focus="Judge the sentence under its heading.")
    assert instructions_of(plain) == "Is it about the CV?"
    assert instructions_of(pointed) == {
        "question": "Is it about the CV?", "inspect": "`sentences[3]`",
        "focus": "Judge the sentence under its heading.",
    }


def test_the_provider_is_the_default_unless_a_decision_names_one(settings):
    settings.DECISIONS_PROVIDER = {
        "default": "typesafe",
        "D5": "adapter:anthropic",
        "D4:kk-Cyrl": "adapter:openai",
    }
    assert provider_for("D6") == "typesafe"
    assert provider_for("D5") == "adapter:anthropic"
    assert provider_for("D4", "kk-Cyrl") == "adapter:openai"
    # A language with no entry of its own falls back to the decision's, then the default.
    assert provider_for("D4", "tr") == "typesafe"


def test_an_absent_key_raises_rather_than_degrading(openrouter):
    """ask() never swaps providers: a missing key must never silently become a
    frontier model's answer at a threshold tuned for a different one (spec 3.1
    item 7, 9a). It raises `not_configured`, and the CALLER decides to run the
    frontier judge instead (addendum 5.1) -- a choice made in one visible place,
    not a failover hidden in the client."""
    openrouter.OPENROUTER_API_KEY = ""
    with pytest.raises(DecisionsUnavailable, match="OPENROUTER_API_KEY") as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert raised.value.kind == "not_configured"


def test_the_budget_refuses_before_a_request_is_made():
    budget = DecisionBudget(limit_tokens=100)
    budget.spend(95)

    def explode(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("spent past the budget")

    with pytest.raises(DecisionBudgetExhausted):
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6",
            budget=budget, client=explode)


def test_the_budget_counts_what_the_answer_reports():
    budget = DecisionBudget(limit_tokens=1_000)
    ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6", budget=budget,
        client=_client({"q": (True, 0.9, {"true": 0.9})}))
    assert budget.spent == 10


def test_a_question_set_is_refused_over_the_state_token_ceiling():
    """32k tokens is the endpoint's context (OpenRouter lists context_length
    32000 for typesafe/jev-1.13). A page that would exceed it must be chunked by
    the caller, not truncated by the client."""
    huge = {"sentences": [{"id": str(i), "text": "x" * 400} for i in range(1_000)]}
    with pytest.raises(ValueError, match="token budget"):
        ask(huge, {"q": Noul(question="is it?")}, decision="D6",
            client=_client({"q": (True, 0.9, {"true": 0.9})}))


def test_the_estimate_is_not_blown_up_by_ascii_escaping_non_latin_scripts():
    """Task 1 review carry-over: json.dumps's default `ensure_ascii=True` turns
    every Cyrillic or Arabic character into a 6-character `\\uXXXX` escape
    before the char-per-token division, over-estimating those scripts 3-5x --
    which would make the packer (grammar_questions.pack) split a Cyrillic or
    Arabic page far more aggressively than an equally-long page in Latin
    script. The real estimate must land well under what that escaped length
    would have given."""
    cyrillic = {"text": "х" * 400}
    escaped_len = len(json.dumps(cyrillic, default=str, ensure_ascii=True))
    over_escaped_estimate = escaped_len // 4

    real_estimate = _estimate_tokens(cyrillic, {})

    # The escaped route charges ~1.5 tokens per Cyrillic character (each
    # becomes a 6-character `\uXXXX` escape, still divided by 4); the real
    # estimate must land close to one token per character, not that inflated
    # rate -- comfortably under the escaped figure.
    assert real_estimate < over_escaped_estimate
    assert real_estimate <= len(cyrillic["text"]) * 1.1


def test_the_estimate_never_undercounts_a_dense_script():
    """CJK tokenizers run close to one token per character, so 400 CJK
    characters must never estimate under 400 tokens -- the estimator must stay
    conservative (never UNDER budget) even though it is no longer inflated by
    ascii-escaping."""
    cjk = {"text": "日" * 400}
    assert _estimate_tokens(cjk, {}) >= 400


def test_jev_is_reached_through_the_base_url_with_the_openrouter_key(openrouter, sdk):
    """Addendum 2: the SDK client is built against DECISIONS_BASE_URL with the
    OpenRouter key, the pinned id goes out as the model, and the snapshot that
    actually answered comes back on every answer."""
    seen = sdk(_response({
        "document": {"type": "choice", "choice": "cv", "confidence": 0.97,
                     "probabilities": {"cv": 0.97, "motivation_letter": 0.03}},
        "third_party": {"type": "noul", "noul": 0.12},
    }))
    answers = ask(
        {"text": "Your CV may not exceed two pages."},
        {
            "document": Choice(question="Which document?", options=("cv", "motivation_letter")),
            "third_party": Noul(question="Is this somebody else's document?"),
        },
        decision="D6",
    )
    assert seen["client"] == {"api_key": "or-test-key", "base_url": "https://openrouter.ai/api"}
    assert seen["call"]["model"] == "typesafe/jev-1.13"
    assert answers["document"].value == "cv"
    assert answers["third_party"].value is False
    assert answers["third_party"].confidence == pytest.approx(0.88)
    assert {a.served_model for a in answers.values()} == {_SERVED}
    assert {a.model for a in answers.values()} == {"typesafe/jev-1.13"}
    # The request's tokens are charged once, not once per question.
    assert sum(a.input_tokens for a in answers.values()) == 42


def test_the_typesafe_key_is_sent_only_to_typesafes_own_endpoint(openrouter, sdk):
    openrouter.DECISIONS_BASE_URL = "https://api.typesafe.ai"
    openrouter.TYPESAFE_API_KEY = "ts-test-key"
    openrouter.OPENROUTER_API_KEY = "or-must-not-be-sent"
    seen = sdk(_response({"q": {"type": "noul", "noul": 0.9}}))
    ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert seen["client"]["api_key"] == "ts-test-key"
    assert seen["client"]["base_url"] == "https://api.typesafe.ai"


def test_a_rate_limit_after_the_sdks_own_retries_is_failed_with_its_wait(openrouter, sdk):
    """Addendum 5.1: one failed request is a failed READ, never a failed page and
    never a crash. The provider's own Retry-After travels to the caller, which
    schedules the FetchAttempt retry with it."""
    sdk(typesafe_sdk.TypeSafeRateLimitError(
        429, {"error": "rate limited"}, httpx2.Headers({"retry-after": "7"})
    ))
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert raised.value.kind == "failed"
    assert raised.value.retry_after_seconds == pytest.approx(7.0)
    assert "or-test-key" not in str(raised.value)


@pytest.mark.parametrize(
    "error",
    [
        typesafe_sdk.TypeSafeAPIError(
            402, {"error": {"code": 402, "message": "Insufficient credits"}}, httpx2.Headers()
        ),
        typesafe_sdk.TypeSafeBadRequestError(
            400, {"error": "Your credit balance is too low"}, httpx2.Headers()
        ),
        typesafe_sdk.TypeSafeInternalServerError(503, None, httpx2.Headers()),
        typesafe_sdk.TypeSafeAPIConnectionError("connection reset"),
    ],
    ids=["billing-402", "billing-400", "5xx", "transport"],
)
def test_every_other_failure_is_failed_and_carries_no_wait(openrouter, sdk, error):
    sdk(error)
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert raised.value.kind == "failed"
    assert raised.value.retry_after_seconds is None


def test_a_moderation_refusal_is_refused_not_failed(openrouter, sdk):
    """OpenRouter answers a flagged input with 403 and `error.metadata.reasons`.
    That is the provider declining THIS state: retrying it spends a request for
    the same answer, so it is typed apart from a failure (addendum 5.1)."""
    sdk(typesafe_sdk.TypeSafePermissionDeniedError(
        403,
        {"error": {"code": 403, "message": "Input flagged",
                   "metadata": {"reasons": ["violence"], "flagged_input": "..."}}},
        httpx2.Headers(),
    ))
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert raised.value.kind == "refused"


def test_an_adapter_refusal_is_refused(settings, monkeypatch):
    """system-one-adapter 0.2.1 raises a bare TypeSafeError naming the refusal
    (providers/anthropic.py: 'did not complete: refusal', providers/openai.py:
    'was a refusal')."""
    settings.DECISIONS_PROVIDER = {"default": "typesafe", "D5": "adapter:anthropic"}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    class Refusing:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def system_one(self, *args, **kwargs):
            raise typesafe_sdk.TypeSafeError("Anthropic response did not complete: refusal.")

    monkeypatch.setattr(system_one_adapter, "SystemOneAdapterClient", Refusing)
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D5")
    assert raised.value.kind == "refused"


# Final review, minor 6: no key is `not_configured` (the caller's frontier
# fallback) even when the budget would refuse -- a spent budget must not turn
# "use the other judge" into a failed page.
def test_no_key_and_a_zero_budget_is_not_configured(openrouter):
    openrouter.OPENROUTER_API_KEY = ""
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6",
            budget=DecisionBudget(limit_tokens=0))
    assert raised.value.kind == "not_configured"


def test_no_adapter_key_and_a_zero_budget_is_not_configured(openrouter, monkeypatch):
    openrouter.DECISIONS_PROVIDER = {"default": "adapter:openai"}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(DecisionsUnavailable) as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6",
            budget=DecisionBudget(limit_tokens=0))
    assert raised.value.kind == "not_configured"


# Final review, minor 7: a key never travels over plain http.
def test_a_plain_http_base_url_is_refused_before_any_key_is_sent(openrouter, sdk):
    openrouter.DECISIONS_BASE_URL = "http://openrouter.ai/api"
    seen = sdk(_response({"q": {"type": "noul", "noul": 0.9}}))
    with pytest.raises(DecisionsUnavailable, match="https") as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert raised.value.kind == "not_configured"
    assert seen == {}


def test_an_absent_typesafe_key_raises_on_typesafe_host(openrouter):
    """The same rule on TypeSafe's own host, where TYPESAFE_API_KEY is the key."""
    openrouter.DECISIONS_BASE_URL = "https://api.typesafe.ai"
    openrouter.TYPESAFE_API_KEY = ""
    with pytest.raises(DecisionsUnavailable, match="TYPESAFE_API_KEY") as raised:
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")
    assert raised.value.kind == "not_configured"
