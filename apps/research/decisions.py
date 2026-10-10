"""The typed-decision layer: closed questions, probabilities, one provider.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md,
amended by 2026-09-26-requirement-reader-addendum-design.md.

**This module is the only place in the codebase that builds a question.** That
is TypeSafe's own guidance -- "put the constants in a single place so they're
easy to review" -- and it is what makes a threshold reviewable and a provider
swappable. A caller passes a state and a question map; it never passes a prompt.

Nothing here generates text. A question is a Noul (is this true?) or a Choice
(which of these?), and an answer is one of the options plus a probability
distribution over all of them. A steered page can therefore mislabel a real
sentence; it can never invent one (spec 9 item 1).

**Jev is reached through OpenRouter by default** (addendum 2): TypeSafe paused
sign-ups, and an OpenRouter key authenticates the TypeSafe SDK pointed at
`DECISIONS_BASE_URL`. TypeSafe's own key is sent only to TypeSafe's own host.

**This module never switches provider.** When no decision is reached it raises
`DecisionsUnavailable` with a `kind` the caller acts on (addendum 5.1):
`not_configured` means the caller runs the frontier judge, `failed` means the read
is `decision_failed` and retried, and `refused` means it is recorded and never
retried. A failover here would run decisions at a threshold tuned for another
model (spec 3.1 item 7).

The catalogue boundary applies: `DecisionRecord` (Task 2) is readable and
writable only by `runtime_engine`, so this module runs in the worker, never
on a web request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import system_one_adapter
import typesafe_sdk
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

#: TypeSafe's documented Choice ceiling, read 2026-09-22.
MAX_OPTIONS = 255
#: The endpoint's context: OpenRouter lists context_length 32000 for
#: typesafe/jev-1.13. Checked here so an oversize state is a ValueError at
#: the seam rather than a vendor 400 mid-sweep.
MAX_STATE_TOKENS = 32_000
#: Four characters per token is the usual English approximation and is
#: deliberately pessimistic for the scripts this system reads (spec 8.1):
#: Chinese, Japanese and Korean run closer to one token per character, so a
#: state that passes this check in Latin script may still be dense in CJK.
#: The caller chunks; this only refuses what is certainly too large.
_CHARS_PER_TOKEN = 4

#: TypeSafe's own API host. Only a base URL on this host receives TYPESAFE_API_KEY.
_TYPESAFE_HOST = "api.typesafe.ai"

UnavailableKind = Literal["not_configured", "failed", "refused"]


class DecisionsUnavailable(RuntimeError):
    """No decision was reached. Never raised because an answer was uncertain --
    an uncertain answer is a low confidence, which is a value the caller reads.

    `kind` is what the caller does next (addendum 5.1):

    - ``not_configured`` -- no key for the routed provider. The caller runs the
      frontier judge, so a missing key costs money, not correctness.
    - ``failed`` -- transport, timeout, 5xx, 429 after the SDK's own retries,
      billing, or a skipped answer. The read is ``decision_failed``, the page's
      previous rows stand, and the page joins the FetchAttempt retry queue at
      ``retry_after_seconds`` (or FETCH_RETRY_HOURS when that is None).
    - ``refused`` -- the provider declined this state. Recorded (Task 3), never
      retried.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: UnavailableKind = "failed",
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind: UnavailableKind = kind
        self.retry_after_seconds = retry_after_seconds


class DecisionBudgetExhausted(RuntimeError):
    """Raised before a request is made, never after one is paid for."""


class StateTooLarge(ValueError):
    """`ask()` refused a state over `MAX_STATE_TOKENS` (fix round 1, finding 2).

    A `ValueError` subclass, not a new hierarchy: every existing
    `except ValueError` still catches it. Typed so a caller that wants to
    treat this differently from an arbitrary programming-error ValueError --
    the derive seam does, for a single oversized candidate -- does not have
    to match on the message text to tell the two apart.
    """


@dataclass(frozen=True)
class Noul:
    """Is this true? Returns P(yes).

    `inspect` is a backtick path into the state (`` `sentences.s3` ``): the
    vendor's mechanism for pointing a question at a named part, and the fix for
    the indirection failure their jaggedness page documents -- "for the
    sentence with id 3" in prose is exactly what it warns against. Key the part
    rather than index a list: Jev addressed by list position answered about a
    neighbour (measured, transcript_questions.py). `focus` and
    `note` are their other two instruction fields; all three are optional and
    travel to the SDK as a structured `instructions` object when any is set.

    `criteria`, when given, is `{"true": ..., "false": ...}` and nothing else:
    that is the Noul criteria shape, and a key the SDK does not know is a
    silent no-op rather than an error.
    """

    question: str
    criteria: Mapping[str, object] = field(default_factory=dict)
    inspect: str = ""
    focus: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("a question needs text")
        if set(self.criteria) - {"true", "false"}:
            raise ValueError("a Noul's criteria are keyed 'true' and 'false' only")


@dataclass(frozen=True)
class Choice:
    """Which of these? Returns one option and a distribution over all of them.

    The vendor's Choice has no separate option list: the options ARE the keys
    of `criteria`. This dataclass keeps `options` beside `criteria` because a
    call site reads better with the list visible, and `_to_sdk` builds the map
    the SDK wants -- so the two must agree, and a description for an option
    that does not exist is refused here rather than becoming a phantom option.
    """

    question: str
    options: tuple[str, ...]
    criteria: Mapping[str, object] = field(default_factory=dict)
    inspect: str = ""
    focus: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("a question needs text")
        if len(self.options) < 2:
            raise ValueError("a Choice needs at least two options")
        if len(self.options) > MAX_OPTIONS:
            raise ValueError(f"a Choice takes at most {MAX_OPTIONS} options")
        if len(set(self.options)) != len(self.options):
            raise ValueError("a Choice's options must be distinct")
        stray = set(self.criteria) - set(self.options)
        if stray:
            raise ValueError(f"criteria for options that do not exist: {sorted(stray)}")


def instructions_of(question: Question) -> object:
    """What the SDK receives as `instructions`: the bare question when nothing
    else is set, else the vendor's structured object. `inspect`, `focus` and
    `note` are their field names, not ours."""
    extras = {k: v for k, v in (("inspect", question.inspect), ("focus", question.focus),
                                ("note", question.note)) if v}
    if not extras:
        return question.question
    return {"question": question.question, **extras}


Question = Noul | Choice


@dataclass(frozen=True)
class Answer:
    """One typed answer with its distribution, the model, and what it cost.

    `confidence` is the Choice's own confidence, or, for a Noul, P(yes) when
    the answer is True and 1 - P(yes) when it is False -- so a caller can
    always read "how sure" without knowing which type it asked.

    `model` is the id we pinned and asked for (the cache key); `served_model` is
    the snapshot the provider says answered (OpenRouter returns e.g.
    `typesafe/jev-1.13-20260917`). A calibration break that coincides with a
    change in `served_model` is the provider moving the pin under us.
    """

    id: str
    value: str | bool
    confidence: float
    probabilities: Mapping[str, float]
    model: str
    provider: str
    input_tokens: int = 0
    served_model: str = ""


#: A client answers a question map against a state. Two exist below; a test
#: injects a third. It is the ONLY thing a provider swap changes.
Client = Callable[..., dict[str, Answer]]


@dataclass
class DecisionBudget:
    """Layer 2 of the cost controls (spec 9a), the same shape SweepBudget has.

    Layer 1 is the provider's own account limit (set a per-key credit limit in
    the OpenRouter dashboard -- configuration survives a bug here; code does
    not); layer 3 is the monthly reconciliation over DecisionRecord a run does
    at start-up. This one is process-local and exact for one run.
    """

    limit_tokens: int | None = None
    spent: int = 0

    def check(self, estimate: int = 0) -> None:
        if self.limit_tokens is not None and self.spent + estimate >= self.limit_tokens:
            raise DecisionBudgetExhausted(
                f"decision budget {self.limit_tokens} reached (spent {self.spent})"
            )

    def spend(self, tokens: int) -> None:
        self.spent += tokens


def provider_for(decision: str, language: str = "") -> str:
    """Which provider answers this decision, in this language.

    Jev is the default for every classification. The adapter takes a decision
    only where 11 gate 9's measurement put it there -- never as a fallback,
    because thresholds are tuned per provider (spec 3.1 item 7) and a silent
    failover would run every decision at an uncalibrated bar.
    """
    mapping: Mapping[str, str] = settings.DECISIONS_PROVIDER
    if language and f"{decision}:{language}" in mapping:
        return mapping[f"{decision}:{language}"]
    return mapping.get(decision) or mapping.get("default", "typesafe")


def _estimate_tokens(state: object, questions: Mapping[str, Question]) -> int:
    """A pessimistic token count for a state that may mix scripts --
    conservative for question-dominated requests (state is a few % of a
    request); revisit once Jev's tokenizer is measured.

    `ensure_ascii=False`: the default `ensure_ascii=True` turns every
    Cyrillic, Arabic or CJK character into a 6-character `\\uXXXX` escape,
    over-estimating those scripts 3-5x before this function even applies its
    own per-character rule -- which would make `grammar_questions.pack` split
    a non-Latin page far more aggressively than an equally-long Latin one.
    ASCII characters are still charged at `_CHARS_PER_TOKEN` (4, the usual
    English approximation); every other character is charged a full token,
    which is conservative for scripts whose real tokenizers run close to one
    token per character (CJK) and still safely above the true rate for
    Cyrillic and Arabic.
    """
    payload = json.dumps(
        {
            "state": state,
            "questions": [
                {"q": instructions_of(q), "options": getattr(q, "options", ()),
                 "criteria": q.criteria}
                for q in questions.values()
            ],
        },
        default=str,
        ensure_ascii=False,
    )
    non_ascii = sum(1 for ch in payload if ord(ch) > 127)
    ascii_chars = len(payload) - non_ascii
    return ascii_chars // _CHARS_PER_TOKEN + non_ascii


def _to_sdk(
    questions: Mapping[str, Question],
) -> dict[str, typesafe_sdk.Noul | typesafe_sdk.Choice]:
    """Our questions as the SDK's. One of the functions a provider swap touches.

    0.7.1 `_core/question_types.py`: `Choice(instructions, criteria)` where
    criteria maps EVERY option to a description or None -- there is no options
    list -- and `Noul(instructions, criteria)` with criteria keyed true/false.
    `model_validate` rather than keyword construction because criteria values
    are JSON content, which our Mapping[str, object] cannot prove statically.
    """
    built: dict[str, typesafe_sdk.Noul | typesafe_sdk.Choice] = {}
    for qid, question in questions.items():
        if isinstance(question, Choice):
            built[qid] = typesafe_sdk.Choice.model_validate(
                {
                    "instructions": instructions_of(question),
                    "criteria": {
                        option: (dict(desc) if isinstance(desc, Mapping) else desc)
                        for option in question.options
                        for desc in (question.criteria.get(option),)
                    },
                }
            )
        else:
            built[qid] = typesafe_sdk.Noul.model_validate(
                {
                    "instructions": instructions_of(question),
                    "criteria": dict(question.criteria) or None,
                }
            )
    return built


def _from_sdk(
    response: typesafe_sdk.SystemOneResponse,
    questions: Mapping[str, Question],
    *,
    model: str,
    provider: str,
) -> dict[str, Answer]:
    """The SDK's response as ours. The other function a provider swap touches.

    A question the provider skipped is left out, and `ask()` turns the gap into
    `failed` -- treating it as "no rule" is the silence this design removes.
    """
    answers: dict[str, Answer] = {}
    tokens = response.usage.input_tokens or 0
    for qid, question in questions.items():
        if isinstance(question, Choice):
            choice = response.choices.get(qid)
            if choice is None:
                continue
            answers[qid] = Answer(
                id=qid, value=choice.choice, confidence=choice.confidence,
                probabilities=dict(choice.probabilities), model=model, provider=provider,
                input_tokens=tokens, served_model=response.model,
            )
        else:
            noul = response.nouls.get(qid)
            if noul is None:
                continue
            p_yes = noul.noul
            answers[qid] = Answer(
                id=qid, value=p_yes >= 0.5, confidence=p_yes if p_yes >= 0.5 else 1 - p_yes,
                probabilities={"true": p_yes, "false": 1 - p_yes}, model=model,
                provider=provider, input_tokens=tokens, served_model=response.model,
            )
        tokens = 0  # the request's tokens are charged once, to the first answer
    return answers


def _decisions_key() -> tuple[str, str]:
    """(setting name, value) of the key the Jev route needs. TypeSafe's own
    host takes TYPESAFE_API_KEY; any other base URL -- OpenRouter by default --
    takes OPENROUTER_API_KEY. A key is never sent to a host it was not issued by."""
    if urlsplit(settings.DECISIONS_BASE_URL).hostname == _TYPESAFE_HOST:
        return "TYPESAFE_API_KEY", settings.TYPESAFE_API_KEY
    return "OPENROUTER_API_KEY", settings.OPENROUTER_API_KEY


def _require_configured(provider: str) -> None:
    """Raise `not_configured` when `provider` cannot be asked from this
    deployment. `ask()` runs it before the budget (final review, minor 6: a
    missing key is the caller's cue for the frontier judge, and a spent budget
    must not turn that into a failed page), and each client runs it before
    sending anything.

    A DECISIONS_BASE_URL that is not https is `not_configured` too (minor 7),
    not a ValueError: it is a fact about this deployment exactly like a missing
    key, nothing is sent, and the caller's fallback is the designed answer to
    "no usable provider". The message names the setting so the log says why."""
    if provider == "typesafe":
        if urlsplit(settings.DECISIONS_BASE_URL).scheme != "https":
            raise DecisionsUnavailable(
                "DECISIONS_BASE_URL must be https; no key is sent over plain http",
                kind="not_configured",
            )
        name, key = _decisions_key()
        if not key:
            raise DecisionsUnavailable(f"{name} is not set", kind="not_configured")
    elif provider in _ADAPTERS:
        env = _ADAPTERS[provider][1]
        if not os.environ.get(env):
            raise DecisionsUnavailable(
                f"{env} is not set for DECISIONS_PROVIDER={provider}", kind="not_configured"
            )
    else:
        raise DecisionsUnavailable(f"unknown provider {provider!r}", kind="not_configured")


def _is_refusal(error: BaseException) -> bool:
    """The provider declining this state, as opposed to failing to answer.

    Neither SDK types a refusal, so this reads the two shapes that exist:
    OpenRouter's moderation answers 403 with `error.metadata.reasons`, and the
    0.2.1 adapter raises a bare TypeSafeError whose text names the refusal
    (providers/anthropic.py, providers/openai.py).
    """
    if isinstance(error, typesafe_sdk.TypeSafePermissionDeniedError):
        detail = error.body.get("error") if isinstance(error.body, dict) else None
        metadata = detail.get("metadata") if isinstance(detail, dict) else None
        return isinstance(metadata, dict) and "reasons" in metadata
    return type(error) is typesafe_sdk.TypeSafeError and "refusal" in str(error).lower()


def _unavailable(error: Exception, label: str) -> DecisionsUnavailable:
    """Type an SDK failure for the caller. The message carries the type name and
    status only, never str(error): a vendor body may quote the page, and an
    exception message is the kind of thing that ends up in a log line."""
    name = type(error).__name__
    status = getattr(error, "status", None)
    detail = f"{label}: {name}" + (f" {status}" if status is not None else "")
    if _is_refusal(error):
        return DecisionsUnavailable(f"{detail} (refused)", kind="refused")
    wait_ms = None
    if isinstance(error, typesafe_sdk.TypeSafeRateLimitError):
        wait_ms = error.retry_after_ms
    return DecisionsUnavailable(
        detail, kind="failed", retry_after_seconds=None if wait_ms is None else wait_ms / 1000
    )


def _typesafe_client(
    state: typesafe_sdk.JSONContent,
    questions: Mapping[str, Question],
    *,
    model: str,
    provider: str,
) -> dict[str, Answer]:
    """Jev through DECISIONS_BASE_URL. Both the key and the base URL are passed
    explicitly, so the SDK's own TYPESAFE_API_KEY / TYPESAFE_BASE_URL
    environment fallbacks never choose the route. The SDK retries 408/429/5xx
    itself (2 retries, Retry-After honoured, 30 s per call); what still fails is
    `failed`."""
    _require_configured("typesafe")
    _, key = _decisions_key()
    try:
        with typesafe_sdk.TypeSafeClient(
            api_key=key, base_url=settings.DECISIONS_BASE_URL
        ) as client:
            response = client.system_one(state=state, questions=_to_sdk(questions), model=model)
    except Exception as error:  # noqa: BLE001 - every SDK failure becomes a typed kind
        raise _unavailable(error, "typesafe") from error
    return _from_sdk(response, questions, model=model, provider=provider)


#: DECISIONS_PROVIDER value -> (adapter provider name, the env var its SDK reads).
_ADAPTERS: dict[str, tuple[Literal["anthropic", "openai"], str]] = {
    "adapter:anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
    "adapter:openai": ("openai", "OPENAI_API_KEY"),
}


def _adapter_client(
    state: typesafe_sdk.JSONContent,
    questions: Mapping[str, Question],
    *,
    model: str,
    provider: str,
) -> dict[str, Answer]:
    """The same questions through Claude or OpenAI, via TypeSafe's own adapter.

    Reached only where DECISIONS_PROVIDER names it (spec 3.2), never as a
    fallback. Its probabilities are numbers the model writes into its answer,
    not logprobs (addendum 2), so they are not calibrated -- which is why it is
    a measured exception and never the default. Its response subclasses the
    SDK's, so `_from_sdk` reads it unchanged. The provider SDKs read their keys
    from the environment; there is no Django setting for either.
    """
    _require_configured(provider)
    family = _ADAPTERS[provider][0]
    try:
        with system_one_adapter.SystemOneAdapterClient(
            structured_outputs=True,
            llm_answer_mode="probabilities",
            n_retry_malformed_structure=1,
        ) as client:
            # system_one_adapter declares `state` as dict/list, typesafe_sdk as
            # Mapping/Sequence -- the same JSON shape, two vendors' own type
            # aliases. cast rather than narrow our own signature to either one.
            response = client.system_one(
                cast(Any, state), _to_sdk(questions), provider=family, model=model
            )
    except Exception as error:  # noqa: BLE001
        raise _unavailable(error, provider) from error
    return _from_sdk(response, questions, model=model, provider=provider)


def _model_for(provider: str) -> str:
    if provider == "typesafe":
        return settings.TYPESAFE_MODEL
    if provider == "adapter:anthropic":
        return settings.ANTHROPIC_JUDGE_MODEL
    if provider == "adapter:openai":
        return settings.OPENAI_EXTRACTION_MODEL
    raise DecisionsUnavailable(f"unknown provider {provider!r}", kind="not_configured")


def _digest(payload: object) -> str:
    """sha256 over canonical JSON. `sort_keys` so two equal states that were
    built in a different order are one cache entry, not two."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()


def _question_payload(questions: Mapping[str, Question]) -> object:
    """Everything that could change an answer: the id, the wording, the options
    and the criteria. A reworded question must miss the cache, or a measurement
    nobody made is reported as one that was."""
    return {
        qid: {
            "type": type(q).__name__,
            # instructions_of, not q.question: `inspect` and `focus` change the
            # answer as surely as the wording does, so they are part of the key.
            "instructions": instructions_of(q),
            "options": list(getattr(q, "options", ())),
            "criteria": dict(q.criteria),
        }
        for qid, q in sorted(questions.items())
    }


def month_tokens_spent() -> int:
    """Layer 3 (spec §9a): what the decision layer has spent in the last 30 days.

    Meters catalogue reads only -- rows written with `record=True`. A
    `record=False` caller (§11's measurement gates, transcript reading) is never
    written to `DecisionRecord` at all, so it is invisible here on purpose and
    carries its own limiter."""
    from django.db.models import Sum

    from .models import DecisionRecord

    since = timezone.now() - timedelta(days=30)
    total = DecisionRecord.objects.filter(created_at__gte=since).aggregate(
        total=Sum("input_tokens")
    )["total"]
    return int(total or 0)


def run_budget() -> DecisionBudget:
    """A run's ceiling: its own limit, or what is left this month, whichever is
    smaller. Read once at start-up -- a per-request aggregate would be a query
    per decision on a table that only grows."""
    remaining = max(settings.DECISIONS_MONTHLY_TOKENS - month_tokens_spent(), 0)
    return DecisionBudget(limit_tokens=min(settings.DECISIONS_RUN_TOKENS, remaining))


def _cached(
    state_digest: str, question_digest: str, model: str, questions: Mapping[str, Question]
) -> dict[str, Answer] | None:
    """The cached answers, or None on a miss. A cached REFUSAL raises: that
    state was declined under this pin and question set, and asking again spends
    a request for the same refusal (addendum 5.1)."""
    from .models import DecisionRecord

    rows = {
        row.question_id: row
        for row in DecisionRecord.objects.filter(
            state_digest=state_digest, question_digest=question_digest, model=model
        )
    }
    if set(rows) != set(questions):
        # A partial hit is a miss: answering half from cache and half from the
        # provider would mix two model runs inside one decision.
        return None
    if any(row.refused for row in rows.values()):
        raise DecisionsUnavailable(
            f"refused under {model}; recorded, not asked again", kind="refused"
        )
    return {
        qid: Answer(
            id=qid,
            value=(row.value == "true") if isinstance(questions[qid], Noul) else row.value,
            confidence=row.confidence, probabilities=row.probabilities, model=row.model,
            provider=row.provider, input_tokens=0, served_model=row.served_model,
        )
        for qid, row in rows.items()
    }


def _record(
    answers: Mapping[str, Answer], *, state_digest: str, question_digest: str,
    decision: str, language: str,
) -> None:
    """Sorted by question_id: two workers racing the same page with differently
    ordered question maps must take Postgres's row locks in the same order, or
    each can hold the lock the other wants and deadlock."""
    from .models import DecisionRecord

    DecisionRecord.objects.bulk_create(
        [
            DecisionRecord(
                state_digest=state_digest, question_digest=question_digest,
                decision=decision, question_id=answer.id,
                value="true" if answer.value is True
                else "false" if answer.value is False else str(answer.value),
                confidence=answer.confidence, probabilities=dict(answer.probabilities),
                model=answer.model, served_model=answer.served_model,
                provider=answer.provider, language=language,
                input_tokens=answer.input_tokens,
            )
            for answer in sorted(answers.values(), key=lambda a: a.id)
        ],
        ignore_conflicts=True,
    )


def _record_refusal(
    questions: Mapping[str, Question], *, state_digest: str, question_digest: str,
    decision: str, language: str, model: str, provider: str,
) -> None:
    """One `refused` row per question, so `_cached` sees a full set and raises
    rather than asking again. No value, no probabilities, no tokens: a refusal
    is not an answer and must never reach the calibration audit as one."""
    from .models import DecisionRecord

    logger.warning("decision %s refused by %s under %s", decision, provider, model)
    DecisionRecord.objects.bulk_create(
        [
            DecisionRecord(
                state_digest=state_digest, question_digest=question_digest,
                decision=decision, question_id=qid, value="", confidence=0.0,
                probabilities={}, model=model, provider=provider, language=language,
                refused=True,
            )
            for qid in sorted(questions)
        ],
        ignore_conflicts=True,
    )


def ask(
    state: object,
    questions: Mapping[str, Question],
    *,
    decision: str,
    language: str = "",
    budget: DecisionBudget | None = None,
    record: bool = True,
    client: Client | None = None,
) -> dict[str, Answer]:
    """Answer every question against the state, independently and in parallel.

    `decision` is the decision ID (D1-D8, or a grammar slot) -- it selects the
    provider and is what the record and the calibration audit key on. It never
    reaches the model. `record=False` is for §11's measurement runs, which ask
    the same question many times on purpose and must not be served a cache --
    and it is also the only setting allowed for a state that carries student
    text (transcript reading): `DecisionRecord` is shared-catalog, so nothing
    student-derived may ever land in it (global constraints).

    No decision reached raises `DecisionsUnavailable`; read its `kind`. The
    cache is read before the key is needed, so a state already decided keeps
    serving when no key is configured. `month_tokens_spent`'s ceiling only ever
    sees `record=True` calls; a `record=False` caller carries its own limit.
    """
    if not questions:
        return {}
    estimate = _estimate_tokens(state, questions)
    if estimate > MAX_STATE_TOKENS:
        raise StateTooLarge(
            f"{estimate} tokens exceeds the {MAX_STATE_TOKENS} token budget; chunk the state"
        )
    provider = provider_for(decision, language)
    model = _model_for(provider)
    state_digest = _digest(state)
    question_digest = _digest(_question_payload(questions))
    if record:
        hit = _cached(state_digest, question_digest, model, questions)
        if hit is not None:
            return hit
    if client is None:
        # Before the budget: see _require_configured. An injected client
        # carries its own configuration, so it is not asked about ours.
        _require_configured(provider)
    if budget is not None:
        budget.check(estimate)
    call: Client = client or (_typesafe_client if provider == "typesafe" else _adapter_client)
    try:
        answers = call(state, questions, model=model, provider=provider)
    except DecisionsUnavailable as error:
        # Only a refusal is remembered. A failure must be asked again on the next
        # read, and not_configured is a fact about this deployment, not this state.
        if record and error.kind == "refused":
            _record_refusal(questions, state_digest=state_digest,
                            question_digest=question_digest, decision=decision,
                            language=language, model=model, provider=provider)
        raise
    if budget is not None:
        # Spent before the missing check: a reply that skips a question still
        # burned tokens on whatever it DID answer, and a repeatedly-thin
        # provider must not escape both the run budget and the month ceiling
        # by always failing this check first.
        budget.spend(sum(a.input_tokens for a in answers.values()))
    missing = set(questions) - set(answers)
    if missing:
        # A provider that skipped a question is a provider failure, not an
        # uncertain answer. Treating it as "no rule" is the silence this whole
        # design exists to remove.
        raise DecisionsUnavailable(f"{provider} did not answer {sorted(missing)}")
    if record:
        _record(answers, state_digest=state_digest, question_digest=question_digest,
                decision=decision, language=language)
    return answers
