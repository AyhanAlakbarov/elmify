# The Decision Layer and the Rule Grammar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the CV-and-letter judge — nine frontier model calls per page, vote-counted — with one typed-decision layer that asks closed questions with probabilities, and one rule grammar of four slots that projects every answer onto a sink the engine already has.

**Architecture:** `apps/research/decisions.py` owns every question, threshold, provider and the client (TypeSafe's Jev by default, its `system-one-adapter` on Claude or OpenAI where a measurement says so). `research.DecisionRecord` stores every answer with its probabilities and doubles as the cache. `apps/documents/grammar.py` takes a requirement sentence apart into four slots — document, operation, value, scope — over closed lists seeded from the 216 catalogued rules, and projects the result onto `Program.cv_constraints`, `Program.cv_directives` and `LetterShape`, which all exist. Nothing new is invented downstream: the grammar writes into sinks the renderer and the writer already read.

**Tech Stack:** Django 5.2, `typesafe-sdk` and `system-one-adapter` (public PyPI), pydantic 2, pytest with the repo's test DB.

**Spec:** `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` — this plan is its §15 plan 1. Read §3 (what Jev is and the contract), §4 (the decision table), §6 (the grammar, acting, ambiguity, notes, unapplied, templates), §9 (security), §9a (operations) and §11 (the gates) before starting. They are the argument for every task below.

**Base branch:** `claude/fetch-spec-refresh`, rebased onto `origin/master` at 40f8400 on 2026-09-23. Work in a fresh worktree: `git worktree add ../decision-layer claude/fetch-spec-refresh`. Test database: `POSTGRES_DB=tehsil_decisions` — never share a test DB between sessions (CLAUDE.md).

## Reconciliation with master 40f8400 — 2026-09-23, read before Task 1

This plan was written against `bb03a1c`. Master merged PR #114 (research fit) the same day, and it
**already contains a TypeSafe client and the key this plan declares**. Three deltas:

1. **`TYPESAFE_API_KEY` is already in `config/settings/base.py`**, beside `EXA_API_KEY` and
   `RESEARCH_FIT_DAILY_CEILING_USD`. Task 1's settings block **edits that line's comment and adds the
   four new settings after it** — it does not re-declare the key, and the stated insert point
   "after `ANTHROPIC_JUDGE_MODEL` (line 120)" is stale. Everything else in the block is new.
2. **`apps/documents/research_fit/jev.py` is a second, independent Jev client.** It POSTs
   `https://api.typesafe.ai/v1/systemone` through `egress.fetch_json_api` with its own Noul + Choice
   payload, the `jev-latest` **alias**, its own token counter and its own `ProviderUnavailable` (from
   `apps.research.providers.base`). Two clients is exactly what this plan's "`decisions.py` is the
   only module in the codebase that builds a question" forbids, and the duplicate is the cheaper one
   to lose: it has no cache, no budget, no pinned version and no `DecisionRecord` row. It is also
   **not wired** — `service.py` builds `FrontierClassifier` unconditionally, so `JevClassifier` is
   reached only by its own tests and the live gate. Folding it now costs one task; folding it after
   it has a caller costs a behaviour change in the letter path.
   **Task 13 (new, after Task 12): `JevClassifier._ask` calls `decisions.ask()`.** It keeps its
   entity-by-pattern code and its `ClassifiedSentence` shape — only the transport changes. What it
   gains: the `DecisionRecord` cache, `DecisionBudget`, `settings.TYPESAFE_MODEL`'s pinned version in
   place of `jev-latest`, and one place where a threshold is tuned. What it costs: `relevance_floor`
   becomes a threshold in `decisions.py`, and the research-fit tests that stub `post=` stub
   `client=` instead.
3. **`tests/documents/research_fit/test_live.py` is a 24-row EN/DE/TR labelled set that has never
   run**, because no `TYPESAFE_API_KEY` has ever existed on this machine. It is the first real
   measurement of Jev available to this plan and it predates §11's gates — run it before gate 9, and
   read its result as evidence about the *vendor*, not about the decision table.

`apps/research/providers/base.py::ProviderUnavailable` also already exists. `DecisionsUnavailable`
stays a separate class in `decisions.py`: one means "a search index did not answer", the other means
"no decision was reached", and §4's outage policy branches on the second only.


## Global Constraints

- **No frontier model classifies.** Owner decision 2026-09-22. The adapter running Claude or OpenAI is permitted *only* where §11 gate 9's measurement writes it into `DECISIONS_PROVIDER`, never as a fallback and never as a second opinion. Translation, image transcription, `/agent` navigation and template extraction are not classification and keep their frontier calls.
- **No person in the pipeline.** Owner decision 2026-09-23. Nothing waits on a human and nothing creates a task for one. Every uncertain reading is a *note* on the rules the documents are generated from (§6.4). `ConsultantResearchTask` is not written by anything in this plan.
- **A rule is verbatim page text with a label.** No model in this plan generates text. Code cuts the sentences; the classifier picks and labels; code copies the sentence. A value that is a number is *picked* from the numbers code found in the sentence, never computed (spec §3.1 item 2).
- **Enforcement never changes.** Every derived rule is `Enforcement.ADVISORY_HIGH_RISK`. `resolve_rules`' guard that a programme rule may not lower a key's enforcement stays untouched. A classifier answer can make a rule *say* "required"; it can never make one *bind*.
- **`extra="forbid"` on every schema, a cap on every model call, a rate limit on every caller.** The repo's LLM baseline (`~/.config/ai_rules/rules/engineering.md`, CLAUDE.md "LLM/AI security"). `apps/research/extraction.py` is the reference pattern.
- **Keys from the environment only.** `TYPESAFE_API_KEY` never has a settings default and never appears in a log line or an exception message.
- **Never run `ruff format`** in this repo — it is a lint-only gate and `ruff format` churns 26 files (CLAUDE.md).
- **After every task:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_decisions uv run pytest`, and `uv run python manage.py makemigrations --check --dry-run` must stay clean.
- **RLS is verified against a `NOBYPASSRLS` role or it is not verified.** The test role bypasses RLS, so a passing test proves nothing about a policy; use the `runtime_connection` fixture (`tests/tenancy/test_database_isolation.py`) or `rls_enforced_orm` (`tests/conftest.py`). CLAUDE.md, "Row-level security: what actually filters a query".
- **Migration numbers, and a collision to expect.** `research` is at `0003_organisation_register`
  on master (2026-09-23, 40f8400 — `0003` was taken by the Organisation register after this plan
  was written). Three plans now queue on that chain: fetch-engine-core Task 2 takes
  `0004`/`0005`, **this plan takes `0006_decision_record` and `0007_decision_record_rls`**, and
  `2026-09-23-site-jobs-and-the-funnel.md` takes `0008`/`0009`. That assignment presumes the
  landing order fetch-core → decision layer → funnel. **Run `ls apps/research/migrations/` in
  Task 2 Step 0 and take the next free pair**, repointing `dependencies` at the real leaf: a
  textually clean merge whose dependency names a node that does not exist is exactly the collision
  CLAUDE.md records from 2026-09-15, and `makemigrations --check` in CI is what catches it.
  `funding` is at `0046_candidate_catalog_link`; this plan writes no funding migration.

## File Structure

| file | responsibility |
|---|---|
| `apps/research/decisions.py` (new) | `Noul`, `Choice`, `Answer`, `DecisionBudget`, `ask()`, provider routing, the TypeSafe and adapter clients. **The only module in the codebase that builds a question.** |
| `apps/research/models.py` (modify) | `DecisionRecord` |
| `apps/research/migrations/0006_decision_record.py` (new) | the table |
| `apps/research/migrations/0007_decision_record_rls.py` (new) | `shared_catalog_select` + `catalog_ingestion_write` |
| `apps/documents/grammar.py` (new) | the four slots, their closed lists, the two requests, and `read_rules()` — sentences in, typed rules out |
| `apps/documents/rule_sinks.py` (new) | the projection: rules → `ConstraintRule`, `PageDirective`, `LetterShape`, notes |
| `apps/documents/derive.py` (modify) | `derive_page_rules` calls the grammar; `_judge`, `_PHRASINGS`, `_claude_reading`, `_openai_reading`, `_with_one_retry`, `outcomes`, `decide`, `decide_letter_shape`, `Derivations` and its sub-schemas are deleted |
| `apps/documents/management/commands/rederive_rules.py` (new) | §6.5's sweep — re-ask the slot questions over stored sentences, no refetch |
| `config/settings/base.py` (modify) | the decision-layer settings, beside `ANTHROPIC_JUDGE_MODEL` at line 120 |
| `pyproject.toml` (modify) | `typesafe-sdk`, `system-one-adapter[anthropic,openai]` |
| `docs/research/rule-grammar-map.csv` (new) | every catalogued rule mapped to a slot — §11 gate 7's instrument |
| tests (new) | `tests/research/test_decisions.py`, `test_decisions_cache.py`, `test_decision_record_rls.py`, `tests/documents/test_grammar.py`, `test_rule_sinks.py`, `test_grammar_gate.py`, `test_rederive_rules.py` |

---

### Task 1: The decision layer's vocabulary and its client

Everything in both documents' rule paths consumes these names. Nothing here touches the database.

**Files:**
- Create: `apps/research/decisions.py`
- Modify: `config/settings/base.py` (after `ANTHROPIC_JUDGE_MODEL`, line 120), `pyproject.toml`
- Test: `tests/research/test_decisions.py`

**Interfaces:**
- Consumes: `django.conf.settings`
- Produces: `Noul`, `Choice`, `Question`, `Answer`, `DecisionsUnavailable`, `DecisionBudgetExhausted`, `DecisionBudget`, `ask(state, questions, *, decision, language="", budget=None, client=None) -> dict[str, Answer]`, `provider_for(decision, language="") -> str`

- [ ] **Step 0: Read the installed SDK's own signature before writing the client**

Both packages are on public PyPI under the author "TypeSafe AI", published from the vendor's `typesafe-ai` GitHub org, so they are **confirmed sources** under `engineering.md`'s gate: pin, check for vulnerabilities, no approval round (spec §3.2, verified 2026-09-23). Two namesakes exist and neither is the vendor's: `typesafe` (2010) and `typesafe-ai`.

```bash
uv add 'typesafe-sdk==0.7.1' 'system-one-adapter[anthropic,openai]==0.2.1'
uv run python -c "
import inspect, typesafe_sdk, system_one_adapter
print('sdk exports:', sorted(n for n in dir(typesafe_sdk) if not n.startswith('_')))
print('adapter exports:', sorted(n for n in dir(system_one_adapter) if not n.startswith('_')))
for mod, name in ((typesafe_sdk, 'system_one'), (system_one_adapter, 'system_one')):
    fn = getattr(mod, name, None)
    print(mod.__name__, name, inspect.signature(fn) if fn else 'ABSENT')
for cls in ('Noul', 'Choice', 'Score'):
    print(cls, inspect.signature(getattr(typesafe_sdk, cls)))
print('default model:', getattr(typesafe_sdk, 'DEFAULT_MODEL', None))
"
```

Record the real signatures in the commit message. `_to_sdk` and `_from_sdk` below are the **only** two functions that touch them; if the shapes differ from what this plan assumes, change those two and nothing else. Everything above them is ours and is provider-agnostic by design (spec §3.2).

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_decisions.py
import pytest

from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudget,
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    Noul,
    ask,
    provider_for,
)


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


def test_an_absent_key_raises_rather_than_degrading(settings):
    """The owner's rule: the adapter answers only where DECISIONS_PROVIDER names
    it. A missing key must never silently become a frontier model's answer at a
    threshold tuned for a different one (spec 3.1 item 7, 9a outage policy)."""
    settings.TYPESAFE_API_KEY = ""
    settings.DECISIONS_PROVIDER = {"default": "typesafe"}
    with pytest.raises(DecisionsUnavailable, match="TYPESAFE_API_KEY"):
        ask({"text": "x"}, {"q": Noul(question="is it?")}, decision="D6")


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
    """64k tokens for state plus all questions (spec 3.1). A page that would
    exceed it must be chunked by the caller, not truncated by the client."""
    huge = {"sentences": [{"id": str(i), "text": "x" * 400} for i in range(1_000)]}
    with pytest.raises(ValueError, match="token budget"):
        ask(huge, {"q": Noul(question="is it?")}, decision="D6",
            client=_client({"q": (True, 0.9, {"true": 0.9})}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/research/test_decisions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.decisions'`

- [ ] **Step 3: Write the module**

```python
# apps/research/decisions.py
"""The typed-decision layer: closed questions, probabilities, one provider.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md.

**This module is the only place in the codebase that builds a question.** That
is TypeSafe's own guidance -- "put the constants in a single place so they're
easy to review" -- and it is what makes a threshold reviewable and a provider
swappable. A caller passes a state and a question map; it never passes a prompt.

Nothing here generates text. A question is a Noul (is this true?) or a Choice
(which of these?), and an answer is one of the options plus a probability
distribution over all of them. A steered page can therefore mislabel a real
sentence; it can never invent one (spec 9 item 1).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

#: TypeSafe's documented ceilings, read 2026-09-22: 255 options per Choice,
#: 64k tokens for `state` plus all questions. Both are checked here so a
#: violation is a ValueError at the seam rather than a vendor 400 mid-sweep.
MAX_OPTIONS = 255
MAX_STATE_TOKENS = 64_000
#: Four characters per token is the usual English approximation and is
#: deliberately pessimistic for the scripts this system reads (spec 8.1):
#: Chinese, Japanese and Korean run closer to one token per character, so a
#: state that passes this check in Latin script may still be dense in CJK.
#: The caller chunks; this only refuses what is certainly too large.
_CHARS_PER_TOKEN = 4


class DecisionsUnavailable(RuntimeError):
    """The provider could not be reached, or its key is not set.

    Never raised because an answer was uncertain -- an uncertain answer is a
    low confidence, which is a value the caller reads.
    """


class DecisionBudgetExhausted(RuntimeError):
    """Raised before a request is made, never after one is paid for."""


@dataclass(frozen=True)
class Noul:
    """Is this true? Returns P(yes).

    `inspect` is a backtick path into the state (`` `sentences[3]` ``): the
    vendor's mechanism for pointing a question at a named part, and the fix for
    the indirection failure their jaggedness page documents -- "for the
    sentence with id 3" in prose is exactly what it warns against. `focus` and
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


def instructions_of(question: "Question") -> object:
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
    """

    id: str
    value: str | bool
    confidence: float
    probabilities: Mapping[str, float]
    model: str
    provider: str
    input_tokens: int = 0


#: A client answers a question map against a state. Two exist below; a test
#: injects a third. It is the ONLY thing a provider swap changes.
Client = Callable[..., dict[str, Answer]]


@dataclass
class DecisionBudget:
    """Layer 2 of the cost controls (spec 9a), the same shape SweepBudget has.

    Layer 1 is TypeSafe's own account limit, enforced by them; layer 3 is the
    monthly reconciliation over DecisionRecord a run does at start-up. This one
    is process-local and exact for one run, which is what a sweep needs.
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
    )
    return len(payload) // _CHARS_PER_TOKEN


def _to_sdk(questions: Mapping[str, Question]) -> dict[str, object]:
    """Our questions as the SDK's. One of the two functions a provider swap touches.

    Read from `sdk/python/api/types/questions` on 2026-09-23: `Choice(instructions,
    criteria)` where criteria maps EVERY option to a description or None -- there
    is no options list -- and `Noul(instructions, criteria)` with criteria keyed
    `true` / `false`. Step 0 re-checks these against the installed package.
    """
    import typesafe_sdk

    built: dict[str, object] = {}
    for qid, question in questions.items():
        if isinstance(question, Choice):
            built[qid] = typesafe_sdk.Choice(
                instructions=instructions_of(question),
                criteria={
                    option: (dict(desc) if isinstance(desc, Mapping) else desc)
                    for option in question.options
                    for desc in (question.criteria.get(option),)
                },
            )
        else:
            built[qid] = typesafe_sdk.Noul(
                instructions=instructions_of(question),
                criteria=dict(question.criteria) or None,
            )
    return built


def _from_sdk(
    response: object, questions: Mapping[str, Question], *, model: str, provider: str
) -> dict[str, Answer]:
    """The SDK's response as ours. The other function a provider swap touches."""
    answers: dict[str, Answer] = {}
    raw = response.answers  # type: ignore[attr-defined]
    usage = getattr(response, "usage", None)
    tokens = int(getattr(usage, "input_tokens", 0) or 0)
    for qid, question in questions.items():
        item = raw[qid]
        if isinstance(question, Choice):
            probabilities = {str(k): float(v) for k, v in dict(item.probabilities).items()}
            answers[qid] = Answer(
                id=qid, value=str(item.choice), confidence=float(item.confidence),
                probabilities=probabilities, model=model, provider=provider,
                input_tokens=tokens,
            )
        else:
            p_yes = float(item.noul)
            answers[qid] = Answer(
                id=qid, value=p_yes >= 0.5, confidence=p_yes if p_yes >= 0.5 else 1 - p_yes,
                probabilities={"true": p_yes, "false": 1 - p_yes}, model=model,
                provider=provider, input_tokens=tokens,
            )
        tokens = 0  # the request's tokens are charged once, to the first answer
    return answers


def _typesafe_client(
    state: object, questions: Mapping[str, Question], *, model: str, provider: str
) -> dict[str, Answer]:
    import typesafe_sdk

    if not settings.TYPESAFE_API_KEY:
        raise DecisionsUnavailable("TYPESAFE_API_KEY is not set")
    client = typesafe_sdk.TypeSafeClient(
        api_key=settings.TYPESAFE_API_KEY, base_url=settings.TYPESAFE_BASE_URL
    )
    try:
        response = client.system_one(state=state, questions=_to_sdk(questions), model=model)
    except Exception as error:  # noqa: BLE001 - the SDK's exception tree is not ours to enumerate
        # type(error).__name__ alone, never str(error): an SDK message may quote
        # the request, and the request carries the API key.
        raise DecisionsUnavailable(f"typesafe: {type(error).__name__}") from error
    return _from_sdk(response, questions, model=model, provider=provider)


def _adapter_client(
    state: object, questions: Mapping[str, Question], *, model: str, provider: str
) -> dict[str, Answer]:
    """The same questions through Claude or OpenAI, via TypeSafe's own adapter.

    Reached only where DECISIONS_PROVIDER names it (spec 3.2). The adapter is a
    drop-in for `system_one` whose response subclasses the SDK's, so `_from_sdk`
    reads it unchanged; what differs is that every call names its provider and
    model, and asks for probabilities rather than a discrete label.
    """
    import system_one_adapter

    family = provider.split(":", 1)[1]
    key = settings.ANTHROPIC_API_KEY if family == "anthropic" else settings.OPENAI_API_KEY
    if not key:
        raise DecisionsUnavailable(f"{family} key is not set for DECISIONS_PROVIDER={provider}")
    try:
        response = system_one_adapter.system_one(
            state=state,
            questions=_to_sdk(questions),
            provider=family,
            model=model,
            api_key=key,
            llm_answer_mode="probabilities",
        )
    except Exception as error:  # noqa: BLE001
        raise DecisionsUnavailable(f"{provider}: {type(error).__name__}") from error
    return _from_sdk(response, questions, model=model, provider=provider)


def _model_for(provider: str) -> str:
    if provider == "typesafe":
        return settings.TYPESAFE_MODEL
    if provider == "adapter:anthropic":
        return settings.ANTHROPIC_JUDGE_MODEL
    if provider == "adapter:openai":
        return settings.OPENAI_EXTRACTION_MODEL
    raise DecisionsUnavailable(f"unknown provider {provider!r}")


def ask(
    state: object,
    questions: Mapping[str, Question],
    *,
    decision: str,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: Client | None = None,
) -> dict[str, Answer]:
    """Answer every question against the state, independently and in parallel.

    `decision` is the decision ID (D1-D8, or a grammar slot) -- it selects the
    provider and is what the record and the calibration audit key on. It never
    reaches the model.
    """
    if not questions:
        return {}
    estimate = _estimate_tokens(state, questions)
    if estimate > MAX_STATE_TOKENS:
        raise ValueError(
            f"{estimate} tokens exceeds the {MAX_STATE_TOKENS} token budget; chunk the state"
        )
    if budget is not None:
        budget.check(estimate)
    provider = provider_for(decision, language)
    model = _model_for(provider)
    call = client or (_typesafe_client if provider == "typesafe" else _adapter_client)
    answers = call(state, questions, model=model, provider=provider)
    missing = set(questions) - set(answers)
    if missing:
        # A provider that skipped a question is a provider failure, not an
        # uncertain answer. Treating it as "no rule" is the silence this whole
        # design exists to remove.
        raise DecisionsUnavailable(f"{provider} did not answer {sorted(missing)}")
    if budget is not None:
        budget.spend(sum(a.input_tokens for a in answers.values()))
    return answers
```

```python
# config/settings/base.py -- insert after ANTHROPIC_JUDGE_MODEL (line 120)

# --- The typed-decision layer (spec 2026-09-22-typed-decisions §3.2, §9a) ----
#: TypeSafe's Jev answers every classification. The key is env-only; an absent
#: key raises at call time and never degrades to a frontier model, because
#: thresholds are tuned per provider (spec §3.1 item 7).
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
#: The VERSIONED id, never the `jev-latest` alias: their docs say to pin the
#: version once confidence thresholds are tuned against it, and §11's gates tune
#: them. Verified 2026-09-23: `jev-latest` resolved to `jev-1.13.0`.
TYPESAFE_MODEL = os.getenv("TYPESAFE_MODEL", "jev-1.13.0")
#: `https://openrouter.ai/api` reaches the same model through OpenRouter's
#: native decisions route (the SDK appends /v1/systemone). Chat-completions
#: clients cannot call it.
TYPESAFE_BASE_URL = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai")
#: Which provider answers which decision. Jev by default; an entry appears here
#: ONLY when §11 gate 9's measurement showed the adapter better on that decision
#: (optionally in one language: "D4:kk-Cyrl"). Never a failover.
DECISIONS_PROVIDER: dict[str, str] = json.loads(
    os.getenv("DECISIONS_PROVIDER", '{"default": "typesafe"}')
)
#: Layer 3 of the cost controls (spec §9a). Jev is cheap and unbounded; a
#: runaway sweep is still a bill. At $0.042/MTok this is about $8 a month.
DECISIONS_MONTHLY_TOKENS = int(os.getenv("DECISIONS_MONTHLY_TOKENS", "200000000"))
#: Per run, checked before every request. A run that exhausts it reschedules
#: through the fetch engine's retry queue rather than skipping pages silently.
DECISIONS_RUN_TOKENS = int(os.getenv("DECISIONS_RUN_TOKENS", "20000000"))
```

`json` is already imported in `base.py`; if it is not, add `import json` at the top beside `os`.

```toml
# pyproject.toml -- in [project] dependencies, alphabetically
  "system-one-adapter[anthropic,openai]==0.2.1",
  "typesafe-sdk==0.7.1",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/research/test_decisions.py -v`
Expected: 11 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run pip-audit`
Expected: all clean. `pip-audit` matters here because two dependencies were just added from a source this repo has not used before.

- [ ] **Step 6: Commit**

```bash
git add apps/research/decisions.py config/settings/base.py pyproject.toml uv.lock tests/research/test_decisions.py
git commit -m "feat: the typed-decision layer -- closed questions, probabilities, one provider

One module owns every question and threshold, which is what makes a threshold
reviewable and a provider swappable. Nothing here generates text: a question is
a Noul or a Choice and an answer is an option plus a distribution, so a steered
page can mislabel a real sentence and never invent one.

The provider is never switched on a failure. Thresholds are tuned per provider,
so a silent failover would run every decision at an uncalibrated bar; an absent
key raises instead. Both packages are on public PyPI from the vendor's own org
-- confirmed sources, pinned exactly.

SDK signatures recorded at Step 0: <paste them here>.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `DecisionRecord` — every decision is a row

**Files:**
- Modify: `apps/research/models.py`
- Create: `apps/research/migrations/0006_decision_record.py`, `apps/research/migrations/0007_decision_record_rls.py`
- Modify: `tests/tenancy/test_database_isolation.py` (`_SHARED_TABLES`)
- Test: `tests/research/test_decision_record_rls.py`

**Interfaces:**
- Consumes: nothing from Task 1 (the model stands alone; Task 3 joins them)
- Produces: `research.DecisionRecord` with `state_digest`, `question_digest`, `decision`, `question_id`, `value`, `confidence`, `probabilities`, `model`, `provider`, `language`, `input_tokens`, `created_at`

Shared catalog, not tenant data: which sentence a programme's page states is the same fact for every agency, and **no student data is ever in a state** (spec §9a). Same policy shape as `funding/0030_program_awarding_institutions_rls`.

- [ ] **Step 0: Make the `NOBYPASSRLS` fixture reachable, and able to see the table**

Two things block the test below, and both are real:

1. **`runtime_connection` is defined inside `tests/tenancy/test_database_isolation.py`, not a
   conftest** (master, 2026-09-23). A pytest fixture declared in a test module is visible only in
   that module, so a test in `tests/research/` asking for it fails with "fixture not found" — not
   with a policy failure, which is the dangerous shape: it looks like a missing fixture and is
   actually an unverified policy.
2. **It grants `SELECT ON tenancy_membership` and nothing else.** A new table is invisible to that
   role whatever its policy says, so the test would pass on a permission error and prove nothing —
   the exact trap CLAUDE.md describes, one layer down.

Move the fixture verbatim into `tests/conftest.py` beside `rls_enforced_orm` (which already lives
there and is already shared), leave `from tests.conftest import runtime_connection` out — pytest
resolves conftest fixtures by name — and widen its grant to the tables a runtime role really reads:

```python
# tests/conftest.py -- inside runtime_connection, replacing the single GRANT
            # Production grants this role SELECT on every table in the schema
            # through ALTER DEFAULT PRIVILEGES (scripts/create_runtime_role.sql).
            # The fixture hand-granted one table because it was written for one
            # test module; a table it cannot SELECT is invisible whatever its
            # policy says, so an RLS test on a NEW table would pass on a
            # permission error and prove nothing.
            cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}")
                           .format(role))
```

`tests/tenancy/test_database_isolation.py` then imports nothing new and its own cases keep passing —
run them first to prove the move changed no behaviour:

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/tenancy/test_database_isolation.py -v`
Expected: unchanged, all pass.

**`docs/superpowers/plans/2026-09-22-fetch-engine-core.md` Task 2 needs the same move** for
`HostProfile` and `FetchAttempt`. Whichever plan runs first does it; the second finds it done.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_decision_record_rls.py
"""RLS on DecisionRecord, verified through a role that cannot bypass it.

CLAUDE.md: the test role bypasses RLS, so a policy test that uses it proves
nothing. Everything here goes through `runtime_connection`.
"""
from uuid import uuid4

import pytest

from apps.research.models import DecisionRecord

pytestmark = pytest.mark.django_db


def test_a_record_is_readable_by_every_tenant(runtime_connection):
    DecisionRecord.objects.create(
        state_digest="a" * 64, question_digest="b" * 64, decision="D6",
        question_id="0:document", value="cv", confidence=0.97,
        probabilities={"cv": 0.97, "motivation_letter": 0.03},
        model="jev-1.13.0", provider="typesafe", language="en", input_tokens=120,
    )
    with runtime_connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.tenant_id = %s", [str(uuid4())])
        cursor.execute("SELECT count(*) FROM research_decisionrecord")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SET LOCAL app.tenant_id = %s", [str(uuid4())])
        cursor.execute("SELECT count(*) FROM research_decisionrecord")
        assert cursor.fetchone()[0] == 1


def test_the_runtime_role_cannot_write_one(runtime_connection):
    """Only catalog_ingestion writes shared catalog rows -- the same rule
    ProgramStatement follows, for the same reason: a tenant that can write here
    writes what every other tenant reads.

    The write is refused by the GRANT (the fixture gives SELECT only) before the
    policy is ever consulted, and both refusals are correct -- production's
    runtime role holds neither. This test pins that the write does not happen,
    not which of the two stops it; `test_a_record_is_readable_by_every_tenant`
    above is what exercises the policy."""
    with runtime_connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.tenant_id = %s", [str(uuid4())])
        with pytest.raises(Exception, match="row-level security|permission denied"):
            cursor.execute(
                "INSERT INTO research_decisionrecord "
                "(id, state_digest, question_digest, decision, question_id, value, "
                " confidence, probabilities, model, provider, language, input_tokens, created_at) "
                "VALUES (gen_random_uuid(), %s, %s, 'D6', 'q', 'cv', 0.9, '{}', "
                "'jev-1.13.0', 'typesafe', 'en', 1, now())",
                ["a" * 64, "b" * 64],
            )


def test_the_digest_pair_is_unique_per_model():
    """The row is the cache (spec §9a): the same state and question set under the
    same model answer once. Two rows would make the cache a coin flip."""
    fields = dict(
        state_digest="a" * 64, question_digest="b" * 64, decision="D6",
        question_id="0:document", value="cv", confidence=0.97, probabilities={},
        model="jev-1.13.0", provider="typesafe", language="en", input_tokens=1,
    )
    DecisionRecord.objects.create(**fields)
    with pytest.raises(Exception, match="unique|duplicate"):
        DecisionRecord.objects.create(**fields)


def test_it_is_in_the_shared_tables_list():
    """A shared-catalog table absent from this list is one the isolation test
    never checks -- which is how a table ends up with no policy at all."""
    from tests.tenancy.test_database_isolation import _SHARED_TABLES

    assert "research_decisionrecord" in _SHARED_TABLES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/research/test_decision_record_rls.py -v`
Expected: FAIL with `ImportError: cannot import name 'DecisionRecord'`

- [ ] **Step 3: Write the model and its migrations**

```python
# apps/research/models.py -- append

class DecisionRecord(models.Model):
    """One answer from the decision layer, with everything needed to re-judge it.

    Three jobs, and the third is why it is a table rather than a log line:

    1. **The calibration audit** (spec §11.4) reads confidence against outcome
       monthly. Drift or a steered page shows up as a calibration break, which
       is measurable, rather than as a wrong CV, which is not.
    2. **`rederive_rules`** (spec §6.5) re-asks the slot questions over stored
       sentences when the grammar grows, without refetching a page.
    3. **The cache.** The same `(state_digest, question_digest, model)` is
       answered from here. A faculty-wide requirements page linked by thirty
       programmes is decided once, not thirty times.

    Shared catalog: no student data is ever in a state (spec §9a), and which
    sentence a page states is the same fact for every agency.
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: sha256 of the canonical JSON of the state the question was asked against.
    state_digest = models.CharField(max_length=64)
    #: sha256 of the canonical JSON of the WHOLE question map, so a reworded
    #: question never reads a stale answer out of the cache.
    question_digest = models.CharField(max_length=64)
    decision = models.CharField(max_length=40)
    question_id = models.CharField(max_length=120)
    #: The chosen option, or "true"/"false" for a Noul. Always a string so one
    #: column holds both and a query never has to know which it is reading.
    value = models.CharField(max_length=200)
    confidence = models.FloatField()
    probabilities = models.JSONField(default=dict)
    model = models.CharField(max_length=60)
    provider = models.CharField(max_length=30)
    language = models.CharField(max_length=12, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("state_digest", "question_digest", "model", "question_id"),
                name="decision_record_cache_key_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=("decision", "created_at")),
            models.Index(fields=("created_at",)),
        ]
```

Generate the table migration, then write the policy migration by hand:

```bash
POSTGRES_DB=tehsil_decisions uv run python manage.py makemigrations research --name decision_record
```

```python
# apps/research/migrations/0007_decision_record_rls.py
# research_decisionrecord joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: no student
# data is ever in a decision state, and which sentence a page states is the same
# fact for every tenant. Same shape as
# funding/0030_program_awarding_institutions_rls -- both the shared_catalog_select
# read policy and the catalog_ingestion_write policy, from the start.
#
# ENABLE without FORCE, matching that reference exactly. FORCE would apply the
# policies to the table OWNER as well, and the owner is the migration role --
# which is not a member of catalog_ingestion, so the write policy would lock the
# migration role out of its own table. FORCE is right for a TENANT table, where
# CLAUDE.md's failure mode 3 applies; a shared catalog table whose read policy is
# USING (true) has nothing to force.
from django.db import migrations

TABLE = "research_decisionrecord"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("research", "0006_decision_record")]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
```

`catalog_ingestion` already exists — `funding/0006_official_snapshots` creates it `NOLOGIN` if it is
absent, and every shared catalog table since has used it. Do not create it again.

```python
# tests/tenancy/test_database_isolation.py -- add to _SHARED_TABLES
    "research_decisionrecord",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/research/test_decision_record_rls.py tests/tenancy/test_database_isolation.py -v`
Expected: all pass

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_decisions uv run python manage.py makemigrations --check --dry-run`
Expected: all clean, "No changes detected"

- [ ] **Step 6: Commit**

```bash
git add apps/research/models.py apps/research/migrations/ tests/
git commit -m "feat: DecisionRecord -- the calibration input, the re-derivation input, and the cache

Shared catalog, because no student data is ever in a state and which sentence a
page states is the same fact for every agency. The unique key is the cache key:
one state, one question map, one model version, one answer -- so a faculty page
linked by thirty programmes is decided once. Policies verified through
runtime_connection, since the test role bypasses RLS and proves nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The cache, the monthly ceiling, and the outage policy

**Files:**
- Modify: `apps/research/decisions.py`
- Test: `tests/research/test_decisions_cache.py`

**Interfaces:**
- Consumes: `models.DecisionRecord`, `Answer`, `ask`
- Produces: `ask(..., record=True)` writing rows and reading them back; `month_tokens_spent() -> int`; `run_budget() -> DecisionBudget`

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_decisions_cache.py
import pytest

from apps.research.decisions import Answer, Choice, Noul, ask, month_tokens_spent, run_budget
from apps.research.models import DecisionRecord

pytestmark = pytest.mark.django_db


def _client(calls, value="cv", confidence=0.97):
    def call(state, questions, *, model, provider):
        calls.append(dict(questions))
        return {
            qid: Answer(id=qid, value=value, confidence=confidence,
                        probabilities={value: confidence}, model=model,
                        provider=provider, input_tokens=100)
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


def test_a_new_model_version_invalidates_the_cached_answer(settings):
    calls = []
    ask({"text": "x"}, _Q, decision="D6", client=_client(calls))
    settings.TYPESAFE_MODEL = "jev-1.14.0"
    ask({"text": "x"}, _Q, decision="D6", client=_client(calls))
    assert len(calls) == 2


def test_every_answer_is_recorded_with_its_probabilities():
    ask({"text": "A CV is required."}, _Q, decision="D6", language="en",
        client=_client([]))
    row = DecisionRecord.objects.get()
    assert (row.decision, row.question_id, row.value) == ("D6", "document", "cv")
    assert row.probabilities == {"cv": pytest.approx(0.97)}
    assert (row.model, row.provider, row.language) == ("jev-1.13.0", "typesafe", "en")


def test_recording_can_be_turned_off_for_a_measurement_run():
    """§11's gates re-ask the same questions many times deliberately; a cache
    would turn 15 repeats into one answer and 15 identical rows."""
    calls = []
    ask({"text": "x"}, _Q, decision="D6", record=False, client=_client(calls))
    ask({"text": "x"}, _Q, decision="D6", record=False, client=_client(calls))
    assert len(calls) == 2
    assert DecisionRecord.objects.count() == 0


def test_the_month_ceiling_is_read_from_the_rows(settings):
    for _ in range(3):
        DecisionRecord.objects.create(
            state_digest=f"{_}" * 64, question_digest="b" * 64, decision="D6",
            question_id="q", value="cv", confidence=0.9, probabilities={},
            model="jev-1.13.0", provider="typesafe", input_tokens=1_000,
        )
    assert month_tokens_spent() == 3_000


def test_a_run_budget_is_the_smaller_of_the_run_and_what_is_left_this_month(settings):
    settings.DECISIONS_RUN_TOKENS = 5_000
    settings.DECISIONS_MONTHLY_TOKENS = 6_000
    DecisionRecord.objects.create(
        state_digest="a" * 64, question_digest="b" * 64, decision="D6", question_id="q",
        value="cv", confidence=0.9, probabilities={}, model="jev-1.13.0",
        provider="typesafe", input_tokens=4_000,
    )
    assert run_budget().limit_tokens == 2_000


def test_an_unavailable_provider_is_not_swallowed():
    """§9a: an outage reschedules the read through the fetch engine's retry
    queue. It never becomes 'this page states no rule'."""
    from apps.research.decisions import DecisionsUnavailable

    def down(*args, **kwargs):
        raise DecisionsUnavailable("typesafe: ConnectTimeout")

    with pytest.raises(DecisionsUnavailable):
        ask({"text": "x"}, _Q, decision="D6", client=down)
    assert DecisionRecord.objects.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/research/test_decisions_cache.py -v`
Expected: FAIL with `ImportError: cannot import name 'month_tokens_spent'`

- [ ] **Step 3: Extend the module**

```python
# apps/research/decisions.py -- add these imports at the top
import hashlib
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone
```

```python
# apps/research/decisions.py -- append

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
    """Layer 3 (spec §9a): what the decision layer has spent in the last 30 days."""
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
    return {
        qid: Answer(
            id=qid,
            value=(row.value == "true") if isinstance(questions[qid], Noul) else row.value,
            confidence=row.confidence, probabilities=row.probabilities, model=row.model,
            provider=row.provider, input_tokens=0,
        )
        for qid, row in rows.items()
    }


def _record(
    answers: Mapping[str, Answer], *, state_digest: str, question_digest: str,
    decision: str, language: str,
) -> None:
    from .models import DecisionRecord

    try:
        DecisionRecord.objects.bulk_create(
            [
                DecisionRecord(
                    state_digest=state_digest, question_digest=question_digest,
                    decision=decision, question_id=answer.id,
                    value="true" if answer.value is True
                    else "false" if answer.value is False else str(answer.value),
                    confidence=answer.confidence, probabilities=dict(answer.probabilities),
                    model=answer.model, provider=answer.provider, language=language,
                    input_tokens=answer.input_tokens,
                )
                for answer in answers.values()
            ],
            ignore_conflicts=True,
        )
    except IntegrityError:  # pragma: no cover - ignore_conflicts covers the race
        logger.warning("a decision record collided and was not written")
```

Then change `ask()`'s body — the cache read goes before the provider call, the write after:

```python
# apps/research/decisions.py -- ask(), replacing the body from `provider = ...`

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
    the same question many times on purpose and must not be served a cache.
    """
    if not questions:
        return {}
    estimate = _estimate_tokens(state, questions)
    if estimate > MAX_STATE_TOKENS:
        raise ValueError(
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
    if budget is not None:
        budget.check(estimate)
    call = client or (_typesafe_client if provider == "typesafe" else _adapter_client)
    answers = call(state, questions, model=model, provider=provider)
    missing = set(questions) - set(answers)
    if missing:
        raise DecisionsUnavailable(f"{provider} did not answer {sorted(missing)}")
    if budget is not None:
        budget.spend(sum(a.input_tokens for a in answers.values()))
    if record:
        _record(answers, state_digest=state_digest, question_digest=question_digest,
                decision=decision, language=language)
    return answers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/research/ -v`
Expected: all pass, including Task 1's file unchanged

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/research/decisions.py tests/research/test_decisions_cache.py
git commit -m "feat: the decision cache, the monthly ceiling and the outage policy

The cache key is the state, the whole question map and the model version, so a
reworded question or a new model version misses -- reading a stale answer would
report a measurement nobody made. A partial hit is a miss, because half a
decision from each of two model runs is neither.

An outage raises and the caller reschedules; it never becomes 'this page states
no rule', which is the silence this design exists to remove.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The grammar's vocabulary, and the sink every operation projects onto

**Files:**
- Create: `apps/documents/grammar.py`
- Test: `tests/documents/test_grammar_types.py`

**Interfaces:**
- Consumes: `apps.documents.constraints._INCLUDE_TARGETS`, `_SECTIONS`, `_ORDER_TARGETS`, `_CONSTRAINT_KEYS`
- Produces: `DOCUMENTS`, `OPERATIONS`, `STYLE_VALUES`, `CONDITION_KINDS`, `UNITS`, `FORMAT_VERDICTS`, `Slotted`, `Rule`, `SINKS`, `sink_for(document, operation, value) -> str`

Spec §6.1. **The grammar is a projection onto sinks that already exist.** An operation whose value cannot name a real sink does not enter the grammar; that is what keeps "applied" meaning "a checker or renderer that exists ran it".

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_grammar_types.py
import pytest

from apps.documents.constraints import _CONSTRAINT_KEYS, _INCLUDE_TARGETS, _SECTIONS
from apps.documents.grammar import (
    CONDITION_KINDS,
    DOCUMENTS,
    FORMAT_VERDICTS,
    OPERATIONS,
    STYLE_VALUES,
    UNITS,
    Rule,
    sink_for,
)


def test_every_cv_sink_is_a_real_constraint_key_or_directive_action():
    """The grammar may only ever produce a rule something downstream reads.
    A sink that names nothing is a rule that is silently never applied -- the
    exact failure `unapplied` exists to make visible."""
    import typing

    keys = set(typing.get_args(_CONSTRAINT_KEYS))
    for operation in ("limit", "language", "format", "style"):
        for value in {"limit": (2,), "language": ("en",), "format": FORMAT_VERDICTS,
                      "style": STYLE_VALUES}[operation]:
            sink = sink_for("cv", operation, value)
            assert sink in keys | {"cv_format_requirement", ""}, (operation, value, sink)


def test_every_directive_operation_names_a_closed_target():
    assert sink_for("cv", "include", "education.thesis_title") == "cv_directives"
    assert sink_for("cv", "order", "publications") == "cv_directives"
    assert sink_for("cv", "emphasise", "research") == "cv_directives"
    # A target outside the closed list has no sink and becomes `unapplied`.
    assert sink_for("cv", "include", "education.astrology") == ""


def test_every_letter_sink_is_a_real_letter_shape_field():
    from dataclasses import fields

    from apps.documents.letter_shape import LetterShape

    names = {f.name for f in fields(LetterShape)}
    for operation, value in (("limit", 800), ("style", "signed"), ("topic", "why this programme"),
                             ("student_action", "sign it by hand")):
        sink = sink_for("motivation_letter", operation, value)
        assert sink in names, (operation, value, sink)


def test_a_reference_letter_rule_never_binds_the_applicants_documents():
    """A reference letter is the referee's. For the applicant it is an action --
    obtain it -- and nothing else (spec §6.1)."""
    assert sink_for("reference_letter", "limit", 2) == "student_actions"
    assert sink_for("reference_letter", "format", "europass_required") == "student_actions"


def test_the_operations_are_the_closed_list_the_spec_names():
    assert set(OPERATIONS) == {
        "limit", "language", "format", "include", "order", "emphasise", "style",
        "topic", "student_action", "other",
    }


def test_the_documents_are_the_closed_list_the_spec_names():
    assert set(DOCUMENTS) == {"cv", "motivation_letter", "reference_letter", "other"}


def test_a_rule_records_the_sentence_and_the_confidence_that_produced_it():
    rule = Rule(index=3, document="cv", operation="limit", value=2, unit="pages",
                confidence=0.93, sentence="Your CV may not exceed two pages.",
                heading="Application documents")
    assert rule.applied is True
    assert rule.note == ""


def test_a_style_rule_carries_its_own_sub_value():
    """`font_family` and `font_size_minimum` name a value the sentence prints;
    without somewhere to put it the style value alone says 'a font rule' and
    nothing about which font."""
    rule = Rule(index=0, document="motivation_letter", operation="style",
                value="font_family", detail="Times New Roman", confidence=0.9,
                sentence="Use Times New Roman.")
    assert rule.detail == "Times New Roman"


def test_a_rule_below_the_bar_is_a_note_and_is_not_applied():
    rule = Rule(index=3, document="cv", operation="limit", value=2, unit="pages",
                confidence=0.40, sentence="Keep it short.", heading="", note="unsure")
    assert rule.applied is False


def test_the_condition_kinds_are_what_the_student_ledger_can_answer():
    assert set(CONDITION_KINDS) == {
        "nationality", "degree_level", "work_experience", "track", "other"
    }


def test_units_and_sections_are_not_invented_here():
    assert set(UNITS) == {"pages", "words", "characters"}
    assert set(_SECTIONS) <= set(_SECTIONS)  # sanity: the grammar imports, never redefines
    assert "education.thesis_title" in _INCLUDE_TARGETS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.grammar'`

- [ ] **Step 3: Write the vocabulary**

```python
# apps/documents/grammar.py
"""The rule grammar: four slots, closed lists, one free topic.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md §6.

A requirement sentence is never read as a sentence. It is taken apart into
`document`, `operation`, `value` and `scope`, each a closed question with a
probability, and a rule exists only when every slot fills at its bar.

**Every operation projects onto a sink that already exists** -- a constraint key
the renderer checks, a directive the generator reads, a LetterShape field the
letter engine uses. An operation whose value names no sink is `unapplied`: kept
verbatim, shown on the document, counted (§6.5), and never improvised into the
writing prompt. That is the one door this design keeps shut.

Nothing here calls a model. `questions.py` asks; this module defines what may
be asked and where each answer goes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from .constraints import _CONSTRAINT_KEYS, _INCLUDE_TARGETS, _ORDER_TARGETS, _SECTIONS

Document = Literal["cv", "motivation_letter", "reference_letter", "other"]
Operation = Literal[
    "limit", "language", "format", "include", "order", "emphasise", "style",
    "topic", "student_action", "other",
]

DOCUMENTS: tuple[str, ...] = get_args(Document)
OPERATIONS: tuple[str, ...] = get_args(Operation)

#: The units a length may be stated in. `pages` is a CV and letter unit;
#: `words` and `characters` are the letter's (ApplicationPrompt.letter_max_words,
#: letter_max_chars) and the CV's max_words / max_chars_incl_spaces.
UNITS: tuple[str, ...] = ("pages", "words", "characters")

#: The CV-format verdict, unchanged in values from the 2026-09-13 spec so the
#: 48-row eval sheet still scores it. `third_party` left the list: it is the
#: scope slot's job now and a sentence can be both third-party and a format rule.
FORMAT_VERDICTS: tuple[str, ...] = (
    "europass_required", "europass_preferred", "any", "other_template", "not_a_format_rule",
)

#: Style values, seeded from docs/research/cv-style-rules.csv and letter-rules.csv
#: by §11 gate 7 and frozen here. Each names a sink below; a style rule with no
#: sink would be a rule nothing checks.
STYLE_VALUES: tuple[str, ...] = (
    "photo_required", "photo_forbidden", "signature_required", "date_of_issue_required",
    "date_of_birth_forbidden", "font_size_minimum", "font_family", "line_spacing",
    "margins", "signed_declaration", "handwritten", "single_file_bundle",
)

#: What a condition may be about, limited to what the student ledger can answer.
#: Anything else is `other` and becomes a note -- a condition we cannot evaluate
#: must never silently apply to everyone.
CONDITION_KINDS: tuple[str, ...] = (
    "nationality", "degree_level", "work_experience", "track", "other",
)

#: operation -> the CV constraint key it writes, for the operations whose value
#: does not pick the key itself.
_CV_STYLE_SINK: dict[str, str] = {
    "photo_required": "photo_allowed",
    "photo_forbidden": "photo_allowed",
    "signature_required": "signature_required",
    "date_of_issue_required": "date_of_issue_required",
    "date_of_birth_forbidden": "date_of_birth_allowed",
    "font_size_minimum": "font",
    "font_family": "font",
}
_CV_LIMIT_SINK: dict[str, str] = {
    "pages": "max_pages",
    "words": "max_words",
    "characters": "max_chars_incl_spaces",
}
#: The letter's sinks are LetterShape field names; apply_derived_shape writes
#: them onto ApplicationPrompt.letter_*.
_LETTER_LIMIT_SINK: dict[str, str] = {
    "pages": "max_pages", "words": "max_words", "characters": "max_chars",
}
_LETTER_STYLE_SINK: dict[str, str] = {
    "signed_declaration": "signed_declaration",
    "handwritten": "handwritten",
    "font_family": "font_family",
    "font_size_minimum": "font_min_pt",
    "line_spacing": "line_spacing",
    "margins": "margins_cm",
    "single_file_bundle": "file_bundle",
    "signature_required": "signed_declaration",
}


@dataclass(frozen=True)
class Slotted:
    """What the first request settled about one sentence: who and what."""

    index: int
    document: Document
    document_confidence: float
    operation: Operation
    operation_confidence: float
    third_party: bool
    conditional: bool


@dataclass(frozen=True)
class Rule:
    """One filled rule, or one note. `note` empty means it is applied.

    `sentence` is verbatim page text and becomes `rule_text`; `heading` is the
    context the question was asked with and is stored so §6.5's re-derivation
    can ask again without the page (spec §9a).
    """

    index: int
    document: Document
    operation: Operation
    value: object
    sentence: str
    heading: str = ""
    unit: str = ""
    #: The style value's own sub-value, where it has one: the font family the
    #: sentence names, a point size, a line spacing, a margin. It is PICKED from
    #: the sentence like any other value (grammar_values), never generated --
    #: which is why it is a field here and not a free string a caller fills in.
    detail: str = ""
    confidence: float = 0.0
    #: "" when applied; otherwise one of §6.3's kinds or §6.5's `unapplied`:
    #: unsure | conflict | conditional | phrasing | third_party | unapplied | quarantined
    note: str = ""
    condition: str = ""
    probabilities: tuple[tuple[str, float], ...] = ()

    @property
    def applied(self) -> bool:
        return not self.note


def sink_for(document: str, operation: str, value: object) -> str:
    """Where this rule lands, or "" when nothing downstream can carry it.

    "" is not an error: it is §6.5's `unapplied`, the honest answer when a page
    states a real requirement the engine has no handler for. It is counted, and
    the grammar grows from the count -- never from a model improvising.
    """
    if document == "reference_letter":
        # The referee's document. For the applicant it is one action: obtain it.
        return "student_actions"
    if document == "other":
        return ""
    if operation == "student_action":
        return "student_actions"
    if document == "cv":
        return _cv_sink(operation, value)
    if document == "motivation_letter":
        return _letter_sink(operation, value)
    return ""


def _cv_sink(operation: str, value: object) -> str:
    if operation == "limit":
        # The unit decides the key; the caller passes it as the value's unit and
        # `rule_sinks` re-reads it. Any unit is a valid sink, so a bare limit
        # answers `max_pages` -- the commonest case by far in the catalogs.
        return _CV_LIMIT_SINK.get(str(value), "max_pages")
    if operation == "language":
        return "language"
    if operation == "format":
        return "cv_format_requirement" if value in FORMAT_VERDICTS else ""
    if operation == "style":
        return _CV_STYLE_SINK.get(str(value), "")
    if operation == "include":
        return "cv_directives" if value in _INCLUDE_TARGETS else ""
    if operation == "order":
        return "cv_directives" if value in _ORDER_TARGETS else ""
    if operation == "emphasise":
        return "cv_directives" if value in _SECTIONS else ""
    # `topic` has no CV sink: the CV states facts from the ledger and has no
    # free-text section a topic could steer. On the letter it does.
    return ""


def _letter_sink(operation: str, value: object) -> str:
    if operation == "limit":
        return _LETTER_LIMIT_SINK.get(str(value), "max_pages")
    if operation == "language":
        # The letter's language lives on ApplicationPrompt.document_language,
        # which shape_from_prompt reads; LetterShape carries it as `track`'s
        # neighbour rather than a field of its own, so the sink is named here
        # and rule_sinks writes the prompt field directly.
        return "document_language"
    if operation == "style":
        return _LETTER_STYLE_SINK.get(str(value), "")
    if operation == "topic":
        return "written_requirements"
    if operation == "format":
        # A letter has no Europass; a template it names is a student action
        # (download it, use it) until a renderer knows it.
        return "student_actions" if value == "other_template" else ""
    return ""


#: Every sink this grammar may name. A test pins it against the real field and
#: key lists so a rename downstream fails here rather than silently dropping rules.
SINKS: frozenset[str] = frozenset(
    {"cv_directives", "cv_format_requirement", "student_actions", "written_requirements",
     "document_language", ""}
    | set(get_args(_CONSTRAINT_KEYS))
    | set(_CV_LIMIT_SINK.values())
    | set(_LETTER_LIMIT_SINK.values())
    | set(_LETTER_STYLE_SINK.values())
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_types.py -v`
Expected: 10 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/documents/grammar.py tests/documents/test_grammar_types.py
git commit -m "feat: the rule grammar's vocabulary, and the sink every operation projects onto

Four slots over closed lists, and every operation resolves to a sink that
already exists -- a constraint key the renderer checks, a directive the
generator reads, a LetterShape field the letter engine uses. An operation whose
value names no sink returns '', which is `unapplied`: kept verbatim, shown,
counted, never improvised into a writing prompt. A reference letter binds the
referee, so for the applicant it is one action and nothing else.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The first request — document, operation, scope

**Files:**
- Create: `apps/documents/grammar_questions.py`
- Test: `tests/documents/test_grammar_slots.py`

**Interfaces:**
- Consumes: `apps.research.decisions.{Choice, Noul, ask, Answer}`, `grammar.{DOCUMENTS, OPERATIONS, Slotted}`, `derive.Candidate`
- Produces: `slot_questions(candidates) -> dict[str, Question]`, `read_slots(candidates, *, budget=None, client=None, language="") -> tuple[Slotted, ...]`, `SLOT_BAR`

Spec §6.1: the slots are asked in **two requests per sentence set** — document, operation and scope for every sentence first, then the value questions each sentence's operation calls for. That keeps the 48 format examples on the few sentences that are format rules and keeps state plus questions under the 64k ceiling.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_grammar_slots.py
import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar_questions import SLOT_BAR, read_slots, slot_questions
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db


def _candidates():
    return (
        Candidate(text="Your CV may not exceed two pages.", heading="Application documents",
                  europass=False),
        Candidate(text="Short CV (max. 2 pages) from this academic supervisor.",
                  heading="References", europass=False),
        Candidate(text="The motivation letter must be at most 800 words.",
                  heading="Application documents > Motivation letter", europass=False),
    )


def _answers(script):
    """script: {question_id: (value, confidence)}; anything unscripted answers
    'no' or the neutral option, so a test names only the questions it is about."""

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        answers = {}
        for qid, question in questions.items():
            if qid in script:
                value, confidence = script[qid]
            else:
                options = getattr(question, "options", None)
                value, confidence = (False if options is None else options[-1]), 0.99
            answers[qid] = Answer(id=qid, value=value, confidence=confidence,
                                  probabilities={str(value): confidence},
                                  model="jev-1.13.0", provider="typesafe")
        return answers

    return call


def test_one_question_per_sentence_per_slot():
    questions = slot_questions(_candidates())
    assert set(questions) == {
        f"{i}:{slot}"
        for i in range(3)
        for slot in ("document", "operation", "third_party", "conditional", "subset")
    }


def test_every_question_points_at_its_sentence_with_inspect():
    """Jev's own guidance: a question points at a named part of a structured
    state with a backtick path; "the sentence with id 2" in prose is the
    indirection their jaggedness page warns against (§3.1a)."""
    questions = slot_questions(_candidates())
    assert questions["0:document"].inspect == "`sentences[0]`"
    assert questions["2:operation"].inspect == "`sentences[2]`"
    assert "id" not in questions["2:operation"].question


def test_a_condition_and_a_subset_are_two_questions_ored_in_code():
    """One condition per Noul (the vendor's first rule). 'Non-EU applicants
    must…' is a subset; 'if you have work experience…' is a condition; either
    alone makes the rule conditional."""
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.98), "0:operation": ("style", 0.95),
        "0:subset": (True, 0.9),
    }))
    assert slots[0].conditional is True


def test_the_state_carries_each_sentence_under_its_heading():
    """A bare sentence is where wrong attributions came from: 'no longer than
    two pages' means nothing once its heading is gone (spec §5.1)."""
    from apps.documents.grammar_questions import slot_state

    state = slot_state(_candidates())
    assert state["sentences"][2]["heading"] == "Application documents > Motivation letter"
    assert state["sentences"][2]["text"] == "The motivation letter must be at most 800 words."


def test_a_cv_page_limit_fills_both_slots():
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.98), "0:operation": ("limit", 0.95),
        "0:third_party": (False, 0.97), "0:conditional": (False, 0.99),
    }))
    assert (slots[0].document, slots[0].operation) == ("cv", "limit")
    assert slots[0].third_party is False


def test_a_supervisors_cv_is_marked_third_party():
    """Measured 2026-09-12 on the Swiss Government Excellence Scholarships' real
    page: the engine derived max_pages=2 for the STUDENT from a sentence about
    the host professor's CV. The fabrication check could not catch it -- '2'
    really is in the sentence. Only attribution was wrong."""
    slots = read_slots(_candidates()[1:2], client=_answers({
        "0:document": ("cv", 0.93), "0:operation": ("limit", 0.91),
        "0:third_party": (True, 0.88), "0:conditional": (False, 0.95),
    }))
    assert slots[0].third_party is True


def test_a_sentence_below_the_bar_keeps_its_confidence_for_the_note():
    slots = read_slots(_candidates()[:1], client=_answers({
        "0:document": ("cv", 0.51), "0:operation": ("limit", 0.42),
        "0:third_party": (False, 0.9), "0:conditional": (False, 0.9),
    }))
    assert slots[0].operation_confidence == pytest.approx(0.42)
    assert slots[0].operation_confidence < SLOT_BAR


def test_a_long_page_is_chunked_rather_than_truncated():
    """§3.1 item 4: irrelevant state costs accuracy, and the 64k ceiling is
    hard. A page over the chunk size must be asked in parts -- never cut, which
    is how a page that partly read looked like a page that said nothing."""
    many = tuple(
        Candidate(text=f"Rule number {i} about the CV.", heading="Documents", europass=False)
        for i in range(250)
    )
    seen = []

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        seen.append(len(state["sentences"]))
        return {
            qid: Answer(id=qid, value="cv" if qid.endswith("document") else "limit",
                        confidence=0.9, probabilities={}, model="m", provider="p")
            for qid in questions
        }

    slots = read_slots(many, client=call)
    assert len(slots) == 250
    assert len(seen) > 1 and max(seen) <= 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_slots.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.grammar_questions'`

- [ ] **Step 3: Write the questions**

```python
# apps/documents/grammar_questions.py
"""The grammar's questions, and nothing else.

Two requests per sentence set (spec §6.1): this module's `read_slots` asks who
and what, and `grammar_values.read_values` asks which value. Splitting them
keeps the 48 format examples on the few sentences that are format rules, and
keeps `state` plus questions inside Jev's 64k ceiling.

Every question names its sentence by id and the state carries that sentence
under its heading path -- their own guidance, and the fix for the attribution
errors a bare sentence produced.
"""

from __future__ import annotations

from collections.abc import Sequence

from apps.research.decisions import Answer, Choice, DecisionBudget, Noul, Question, ask

from .derive import Candidate
from .grammar import DOCUMENTS, OPERATIONS, Slotted

#: The bar every slot must clear for a rule to be applied (spec §6.2). Below it
#: the rule is a note and the document is produced without it. §11's calibration
#: sets the shipped figure per question; this is the starting value the spec names.
SLOT_BAR = 0.85

#: Sentences per request. 200 is the spec's chunk size (§5.2); a page over it is
#: asked in parts and the parts' answers concatenated. Never truncated: a page
#: we only partly read must not look like a page that said nothing.
CHUNK = 200

_DOCUMENT_CRITERIA = {
    "cv": {
        "what": "The applicant's own curriculum vitae, résumé or academic CV.",
        "examples": ["CV in the Europass CV template",
                     "Your CV may not exceed two pages.",
                     "A curriculum vitae in reverse chronological order."],
    },
    "motivation_letter": {
        "what": "The applicant's own motivation letter, statement of purpose, "
                "personal statement or cover letter.",
        "examples": ["The motivation letter must be at most 800 words.",
                     "Explain why you have chosen this programme."],
    },
    "reference_letter": {
        "what": "A letter written about the applicant by somebody else -- a "
                "referee, supervisor, employer or teacher.",
        "examples": ["Two letters of recommendation from academic referees.",
                     "Your referee must upload the reference directly."],
    },
    "other": {
        "what": "Any other document, or no document at all: transcripts, "
                "passports, language certificates, fees, deadlines.",
        "not_for": "Do not use this for a CV or a letter merely because the "
                   "sentence also mentions another document.",
    },
}

_OPERATION_CRITERIA = {
    "limit": {"what": "A maximum or minimum length: pages, words or characters.",
              "examples": ["no longer than two pages", "800 words maximum"]},
    "language": {"what": "Which language the document must be written in.",
                 "examples": ["The CV must be in English.", "in English or German"]},
    "format": {"what": "A required or recommended FORM or TEMPLATE for the whole "
                       "document -- Europass, the funder's own template, a tabular form.",
               "not_for": "A rule about one field, a length, or a style detail."},
    "include": {"what": "A specific piece of information the document must contain.",
                "examples": ["state your ECTS credits", "give your date of birth"]},
    "order": {"what": "The order entries must appear in.",
              "examples": ["in reverse chronological order"]},
    "emphasise": {"what": "A section the document should foreground.",
                  "examples": ["highlight your research experience"]},
    "style": {"what": "A presentation rule: photo, signature, date, font, spacing, "
                      "margins, colour, columns, file bundling.",
              "examples": ["A photograph is not required.", "minimum font size 11pt"]},
    "topic": {"what": "A subject the document must address -- a question the "
                      "programme asks, a theme it names.",
              "examples": ["Explain your career plans after graduation."],
              "not_for": "A rule about the document's form, length or language."},
    "student_action": {
        "what": "Something only the applicant can do: sign by hand, have it "
                "notarised or stamped, upload it under a particular filename, "
                "paste it into a portal field, have a referee send it directly.",
        "examples": ["The CV must be signed and dated by hand.",
                     "Upload as a single PDF named SURNAME_CV.pdf"],
    },
    "other": {"what": "A real requirement about this document that none of the "
                      "other answers describes."},
}


def slot_state(candidates: Sequence[Candidate]) -> dict[str, object]:
    """The sentences, each under its heading path.

    `heading` is context for the question and is never stored as a rule: only
    `text` can become a ProgramStatement or a rule_text (spec §5.1).
    """
    return {
        "sentences": [
            {"id": str(i), "heading": c.heading, "text": c.text}
            for i, c in enumerate(candidates)
        ]
    }


def slot_questions(candidates: Sequence[Candidate]) -> dict[str, Question]:
    """Four questions per sentence: which document, what operation, and two scopes."""
    questions: dict[str, Question] = {}
    for i in range(len(candidates)):
        # The vendor's `inspect` path, never "for the sentence with id 3" in
        # prose: indirection is a documented failure mode (research note of
        # 2026-09-23, rule 2), and the path names the part of the state exactly.
        where = f"`sentences[{i}]`"
        questions[f"{i}:document"] = Choice(
            question="Which document does this sentence state a requirement about?",
            options=DOCUMENTS, criteria=_DOCUMENT_CRITERIA, inspect=where,
            focus="Judge the sentence under its heading; the heading says which "
                  "document a list belongs to.",
        )
        questions[f"{i}:operation"] = Choice(
            question="What does this sentence require about that document?",
            options=OPERATIONS, criteria=_OPERATION_CRITERIA, inspect=where,
        )
        questions[f"{i}:third_party"] = Noul(
            question=(
                "Is the document this sentence describes somebody else's -- a "
                "referee's, supervisor's, host's or employer's -- rather than the "
                "applicant's own?"
            ),
            inspect=where,
            # Criteria because a real sentence showed the need (the vendor's
            # rule: add them only then). Measured 2026-09-12 on the Swiss
            # Government Excellence Scholarships' page.
            criteria={
                "true": {"what": "The CV or letter belongs to a referee, supervisor, "
                                 "host professor, employer or recommender.",
                         "examples": ["Short CV (max. 2 pages) from this academic "
                                      "supervisor.",
                                      "Your referee must upload the reference directly."]},
                "false": {"what": "The document is the applicant's own.",
                          "examples": ["Your CV may not exceed two pages."]},
            },
        )
        # Two Nouls, not one with an `or`: the vendor's first rule is one
        # condition per question, and code ORs them.
        questions[f"{i}:conditional"] = Noul(
            question="Does this sentence state a condition that must hold for the "
                     "requirement to apply?",
            inspect=where,
        )
        questions[f"{i}:subset"] = Noul(
            question="Does this requirement apply only to some applicants rather than "
                     "to every applicant?",
            inspect=where,
        )
    return questions


def read_slots(
    candidates: Sequence[Candidate],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: object | None = None,
    record: bool = True,
) -> tuple[Slotted, ...]:
    """Who and what, for every sentence. Chunked, never truncated."""
    slotted: list[Slotted] = []
    for start in range(0, len(candidates), CHUNK):
        chunk = candidates[start : start + CHUNK]
        answers: dict[str, Answer] = _ask(
            slot_state(chunk), slot_questions(chunk), decision="D6.slots",
            language=language, budget=budget, record=record, client=client,
        )
        for i in range(len(chunk)):
            document = answers[f"{i}:document"]
            operation = answers[f"{i}:operation"]
            slotted.append(Slotted(
                index=start + i,
                document=str(document.value),  # type: ignore[arg-type]
                document_confidence=document.confidence,
                operation=str(operation.value),  # type: ignore[arg-type]
                operation_confidence=operation.confidence,
                third_party=bool(answers[f"{i}:third_party"].value),
                conditional=(
                    bool(answers[f"{i}:conditional"].value)
                    or bool(answers[f"{i}:subset"].value)
                ),
            ))
    return tuple(slotted)


def _ask(state, questions, **kwargs) -> dict[str, Answer]:
    """One seam so both request modules inject the same test double."""
    client = kwargs.pop("client", None)
    if client is not None:
        return client(state, questions, **kwargs)
    return ask(state, questions, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_slots.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/documents/grammar_questions.py tests/documents/test_grammar_slots.py
git commit -m "feat: the grammar's first request -- document, operation, scope

Every question names its sentence by id and the state carries that sentence
under its heading path: indirection costs accuracy in Jev's own documentation,
and a bare sentence is where the supervisor's-CV attribution error came from.
A page over 200 sentences is chunked, never truncated -- a page we only partly
read must not look like a page that said nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The second request — the typed values

**Files:**
- Create: `apps/documents/grammar_values.py`
- Test: `tests/documents/test_grammar_values.py`

**Interfaces:**
- Consumes: `grammar.{Slotted, Rule, FORMAT_VERDICTS, STYLE_VALUES, UNITS, CONDITION_KINDS, sink_for}`, `grammar_questions._ask`, `decisions.{Choice, Noul}`
- Produces: `numbers_in(text) -> tuple[int, ...]`, `value_questions(candidates, slots) -> dict[str, Question]`, `read_values(candidates, slots, *, ...) -> tuple[Rule, ...]`, `FORMAT_EXAMPLES`

Spec §6.1 and §6.2. **A number is picked, never computed** (§3.1 item 2): code lists every number in the sentence and the Choice picks which one is the limit.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_grammar_values.py
import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar import Slotted
from apps.documents.grammar_values import numbers_in, read_values, value_questions
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db


def _script(script):
    """Answers from the script; anything unscripted answers 'nothing here', so a
    test states only the questions it is about."""

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        answers = {}
        for qid, question in questions.items():
            if qid in script:
                value, confidence = script[qid]
            else:
                value, confidence = _neutral(question), 0.99
            answers[qid] = Answer(id=qid, value=value, confidence=confidence,
                                  probabilities={str(value): confidence},
                                  model="jev-1.13.0", provider="typesafe")
        return answers

    return call


def _neutral(question):
    options = getattr(question, "options", None)
    if options is None:
        return False
    for neutral in ("none", "other", "any", "not_a_format_rule"):
        if neutral in options:
            return neutral
    return options[0]


def test_numbers_are_found_by_code_in_digits_and_words():
    assert numbers_in("Your CV may not exceed two pages.") == (2,)
    assert numbers_in("maximum 800 words, minimum 500") == (800, 500)
    assert numbers_in("no more than 1,500 characters") == (1500,)
    assert numbers_in("a CV") == ()


def test_a_style_sentence_is_asked_for_its_sub_values_in_the_same_request():
    """The style value and its detail cannot be two requests: the detail
    question would have to know which style was chosen, and that answer is in
    the same response. So every detail question is asked unconditionally and
    only the one the chosen style needs is read -- tokens, not calls."""
    candidates = (Candidate(text="Use Times New Roman at 11pt.", heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.95,
                     operation="style", operation_confidence=0.92, third_party=False,
                     conditional=False),)
    questions = value_questions(candidates, slots)
    assert {"0:style", "0:style_number", "0:style_spacing", "0:style_font"} <= set(questions)
    assert questions["0:style_number"].options == ("11", "none")


def test_a_font_family_is_picked_from_the_names_the_sentence_prints():
    from apps.documents.grammar_values import font_candidates

    assert font_candidates("Use Times New Roman at 11pt.") == ("Times New Roman",)
    assert font_candidates("Any legible font is fine.") == ()
    candidates = (Candidate(text="Use Times New Roman at 11pt.", heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.95,
                     operation="style", operation_confidence=0.92, third_party=False,
                     conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("font_family", 0.94), "0:style_font": ("Times New Roman", 0.96),
    }))
    assert (rules[0].value, rules[0].detail) == ("font_family", "Times New Roman")


def test_a_minimum_font_size_is_picked_from_the_numbers_on_the_page():
    candidates = (Candidate(text="Use Times New Roman at 11pt.", heading="", europass=False),)
    slots = (Slotted(index=0, document="motivation_letter", document_confidence=0.95,
                     operation="style", operation_confidence=0.92, third_party=False,
                     conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("font_size_minimum", 0.93), "0:style_number": ("11", 0.97),
    }))
    assert (rules[0].value, rules[0].detail) == ("font_size_minimum", "11")


def test_only_the_operations_present_get_value_questions():
    """The 48 format examples ride on format sentences only -- that is why the
    slots and the values are two requests (spec §6.1)."""
    candidates = (Candidate(text="Your CV may not exceed two pages.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.98, operation="limit",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    questions = value_questions(candidates, slots)
    assert set(questions) == {"0:limit", "0:unit"}


def test_a_sentence_allowing_two_languages_yields_both():
    """Eiffel's R-072: 'CV in French or English'. render._check_language has
    taken a list since, so a Choice picking one would silently forbid the
    other -- and a CV in the forbidden one is a rejected application."""
    from apps.documents.grammar_values import language_candidates

    assert {c for _, c in language_candidates("CV in French or English.")} == {"fr", "en"}
    candidates = (Candidate(text="CV in French or English.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:language:fr": (True, 0.96), "0:language:en": (True, 0.97),
    }))
    assert rules[0].value == ["en", "fr"]


def test_a_sentence_allowing_one_language_yields_a_bare_string():
    """A one-item list would change nothing except how the rule reads to a
    person, and _check_language keeps a bare string's exact meaning."""
    candidates = (Candidate(text="The CV must be in English.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({"0:language:en": (True, 0.98)}))
    assert rules[0].value == "en"


def test_a_language_the_sentence_names_but_forbids_is_not_a_value():
    candidates = (Candidate(text="German is not accepted; write in English.", heading="",
                            europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.97, operation="language",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:language:de": (False, 0.94), "0:language:en": (True, 0.97),
    }))
    assert rules[0].value == "en"


def test_a_page_limit_is_picked_from_the_numbers_on_the_page():
    candidates = (Candidate(text="Your CV may not exceed two pages.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.98, operation="limit",
                     operation_confidence=0.95, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:limit": ("2", 0.96), "0:unit": ("pages", 0.98),
    }))
    assert (rules[0].value, rules[0].unit) == (2, "pages")
    assert rules[0].applied is True


def test_a_number_the_sentence_does_not_print_cannot_be_the_value():
    """The same principle as verified_statements: the readings may agree
    perfectly on a number nobody wrote. The options ARE the page's numbers, so
    a fabricated one cannot be chosen -- and if the provider returns one anyway
    it is dropped, not applied."""
    candidates = (Candidate(text="Keep the CV short.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.9, operation="limit",
                     operation_confidence=0.9, third_party=False, conditional=False),)
    questions = value_questions(candidates, slots)
    assert questions["0:limit"].options == ("none",)
    rules = read_values(candidates, slots, client=_script({
        "0:limit": ("3", 0.99), "0:unit": ("pages", 0.99),
    }))
    assert rules[0].note == "unapplied"


def test_the_format_verdict_asks_three_phrasings_in_one_request():
    """Owner decision 2026-09-22, kept at the ordinary bar on 2026-09-23: three
    phrasings cost tokens in one request and no extra call, and their agreement
    is information because a Noul and a Choice on one question are not
    guaranteed to agree (spec §3.1 item 7)."""
    candidates = (Candidate(text="CV in the Europass CV template", heading="", europass=True),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.99, operation="format",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    questions = value_questions(candidates, slots)
    assert {"0:format", "0:format_noul", "0:format_applicant"} <= set(questions)


def test_two_of_three_phrasings_agreeing_acts():
    candidates = (Candidate(text="CV in the Europass CV template", heading="", europass=True),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.99, operation="format",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:format": ("europass_required", 0.94),
        "0:format_noul": (True, 0.93),
        "0:format_applicant": ("europass_required", 0.60),
    }))
    assert rules[0].value == "europass_required"
    assert rules[0].applied is True


def test_three_phrasings_disagreeing_is_a_phrasing_note():
    candidates = (Candidate(text="We recommend the Europass model.", heading="", europass=True),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.99, operation="format",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:format": ("europass_required", 0.91),
        "0:format_noul": (False, 0.88),
        "0:format_applicant": ("europass_preferred", 0.90),
    }))
    assert rules[0].note == "phrasing"
    assert rules[0].applied is False


def test_a_third_party_sentence_is_never_applied_to_the_applicant():
    candidates = (Candidate(text="Short CV (max. 2 pages) from this academic supervisor.",
                            heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.95, operation="limit",
                     operation_confidence=0.93, third_party=True, conditional=False),)
    rules = read_values(candidates, slots, client=_script({
        "0:limit": ("2", 0.97), "0:unit": ("pages", 0.98),
    }))
    assert rules[0].note == "third_party"
    assert rules[0].applied is False


def test_a_conditional_sentence_asks_what_the_condition_is_about():
    candidates = (Candidate(text="Non-EU applicants must also submit a signed CV.",
                            heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.95, operation="style",
                     operation_confidence=0.9, third_party=False, conditional=True),)
    questions = value_questions(candidates, slots)
    assert "0:condition" in questions
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("signature_required", 0.93),
        "0:condition": ("nationality", 0.95),
    }))
    assert rules[0].condition == "nationality"
    assert rules[0].applied is True


def test_a_condition_we_cannot_evaluate_is_a_note_not_a_rule_for_everyone():
    candidates = (Candidate(text="Applicants in exceptional circumstances may submit three pages.",
                            heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.9, operation="limit",
                     operation_confidence=0.9, third_party=False, conditional=True),)
    rules = read_values(candidates, slots, client=_script({
        "0:limit": ("3", 0.95), "0:unit": ("pages", 0.95), "0:condition": ("other", 0.88),
    }))
    assert rules[0].note == "conditional"
    assert rules[0].applied is False


def test_an_operation_with_no_sink_is_unapplied_and_keeps_its_sentence():
    candidates = (Candidate(text="List your publications in APA style.", heading="",
                            europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.96, operation="other",
                     operation_confidence=0.91, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({}))
    assert rules[0].note == "unapplied"
    assert rules[0].sentence == "List your publications in APA style."


def test_a_slot_below_the_bar_is_an_unsure_note():
    candidates = (Candidate(text="Keep it professional.", heading="", europass=False),)
    slots = (Slotted(index=0, document="cv", document_confidence=0.52, operation="style",
                     operation_confidence=0.41, third_party=False, conditional=False),)
    rules = read_values(candidates, slots, client=_script({}))
    assert rules[0].note == "unsure"
    assert rules[0].probabilities != ()


def test_a_sentence_about_no_document_yields_nothing_at_all():
    """`other` at the bar is not a note: the page said something about fees or
    deadlines and this reader has no business with it."""
    candidates = (Candidate(text="The application fee is 75 EUR.", heading="", europass=False),)
    slots = (Slotted(index=0, document="other", document_confidence=0.98, operation="other",
                     operation_confidence=0.97, third_party=False, conditional=False),)
    assert read_values(candidates, slots, client=_script({})) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_values.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.grammar_values'`

- [ ] **Step 3: Write the value questions**

```python
# apps/documents/grammar_values.py
"""The grammar's second request: which value, for the operation the first found.

Only the operations a page actually states get value questions, which is why
this is a second request rather than one huge one -- the 48 format examples ride
on the few sentences that are format rules, and `state` plus questions stays
inside Jev's 64k ceiling (spec §6.1).

**A number is picked, never computed.** `numbers_in` lists every number the
sentence prints and the Choice picks which one is the limit; a value that is not
on the page cannot be chosen, and one that arrives anyway is dropped. That is
the same principle as the reader's quote verification, applied to figures.
"""

from __future__ import annotations

import csv
import pathlib
import re
from collections.abc import Sequence

from apps.research.decisions import Answer, Choice, DecisionBudget, Noul, Question

from .derive import Candidate
from .grammar import (
    CONDITION_KINDS,
    FORMAT_VERDICTS,
    STYLE_VALUES,
    UNITS,
    Rule,
    Slotted,
    sink_for,
)
from .grammar_questions import CHUNK, SLOT_BAR, _ask, slot_state
from .letter_terms import normalise_numerals

#: Digits, with thousands separators, and the number words the §8.1 vocabulary
#: carries. Plan 2 replaces `_NUMBER_WORDS` with vocabulary.csv rows in fourteen
#: languages; until then English and German cover the catalogs' own sentences.
_DIGITS = re.compile(r"\d[\d.,]*")
_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
    "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5,
}
#: Above this a "number" in a sentence is a year, a postcode or a phone number,
#: not a length. It stays an option -- the Choice may still pick it and be
#: right -- but `none` is always offered beside it.
_MAX_PLAUSIBLE = 100_000

_EVAL = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research" / "cv-format-eval.csv"


def numbers_in(text: str) -> tuple[int, ...]:
    """Every number the sentence prints, in order, digits and words alike.

    Deduplicated by value while keeping first-seen order, so "2 pages (two
    pages)" offers one option rather than two identical ones.
    """
    found: list[int] = []
    normalised = normalise_numerals(text)
    for match in _DIGITS.finditer(normalised):
        raw = match.group().rstrip(".,").replace(",", "").replace(".", "")
        if raw.isdigit() and int(raw) <= _MAX_PLAUSIBLE:
            found.append(int(raw))
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", normalised, re.IGNORECASE):
            found.append(value)
    seen: set[int] = set()
    return tuple(n for n in found if not (n in seen or seen.add(n)))


#: A font name as a page prints it: capitalised words, optionally several
#: ("Times New Roman", "Liberation Sans"), optionally with a digit ("Arial 11").
#: Code finds the candidates and the Choice picks one, so a font nobody wrote
#: cannot be chosen -- the same rule as a number. A closed list is impossible
#: here: a page may legitimately name any font.
_FONT_NAME = re.compile(r"\b[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3}\b")
#: Words that are capitalised at the start of a sentence or in a heading and are
#: certainly not fonts. Additive and deliberately short: a wrong entry costs one
#: option in a Choice that also offers `none`, never a rule.
_NOT_A_FONT = frozenset({
    "The", "Use", "Your", "Please", "All", "Applicants", "CV", "Europass", "A", "An",
    "It", "We", "Documents", "Application", "Letter", "Motivation", "This", "Note",
})


def font_candidates(text: str) -> tuple[str, ...]:
    """Every plausible font name the sentence prints, in order, deduplicated."""
    found: list[str] = []
    for match in _FONT_NAME.finditer(text):
        name = match.group().strip()
        head = name.split(" ", 1)[0]
        if head in _NOT_A_FONT or len(name) < 4:
            continue
        if name not in found:
            found.append(name)
    return tuple(found)


def _format_examples() -> dict[str, dict[str, object]]:
    """The 48 confirmed rows of cv-format-eval.csv as criteria examples.

    Real sentences, with the verdict a person confirmed. Negation ("no need to
    use the Europass format"), softening ("we suggest", "Wir empfehlen") and a
    stated choice each land on the side they belong to -- the keyword rule was
    wrong on exactly those, at 61% (spec of 2026-09-13).
    """
    criteria: dict[str, dict[str, object]] = {
        verdict: {"examples": []} for verdict in FORMAT_VERDICTS
    }
    criteria["europass_required"]["what"] = (
        "The applicant's own CV must be in the Europass format or template."
    )
    criteria["europass_preferred"]["what"] = (
        "Europass is recommended, suggested or offered for the applicant's own CV, "
        "but another format is allowed."
    )
    criteria["any"]["what"] = "No format is imposed on the applicant's own CV."
    criteria["other_template"]["what"] = (
        "A template or form OTHER than Europass is required -- the funder's own, "
        "a named tabular form, a downloadable file."
    )
    criteria["not_a_format_rule"]["what"] = (
        "The sentence states no rule about the FORM of the applicant's own CV."
    )
    if _EVAL.exists():
        with _EVAL.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                verdict = _EVAL_OUTCOME.get(row["outcome"], "")
                if verdict in criteria and len(criteria[verdict]["examples"]) < 8:  # type: ignore[arg-type]
                    criteria[verdict]["examples"].append(row["sentence"][:400])  # type: ignore[attr-defined]
    return criteria


#: The eval sheet's own outcome vocabulary, mapped to the grammar's.
_EVAL_OUTCOME = {
    "europass": "europass_required",
    "europass_preferred": "europass_preferred",
    "any": "any",
    "other_template": "other_template",
    "none": "not_a_format_rule",
    "third_party": "not_a_format_rule",
}

FORMAT_EXAMPLES = _format_examples()


def value_questions(
    candidates: Sequence[Candidate], slots: Sequence[Slotted]
) -> dict[str, Question]:
    """One question set per sentence, for the operation its slot found.

    A sentence whose slots are below the bar, or whose document is `other`, gets
    no value question at all: there is nothing to ask a value for.
    """
    questions: dict[str, Question] = {}
    for slot in slots:
        if slot.document == "other" or _below_bar(slot):
            continue
        i = slot.index
        where = f"`sentences[{i}]`"
        text = candidates[i].text
        if slot.operation == "limit":
            options = tuple(str(n) for n in numbers_in(text)) or ("none",)
            questions[f"{i}:limit"] = Choice(
                inspect=where, question="which of these numbers is the length limit it states?",
                options=(*options, "none") if options != ("none",) else options,
            )
            questions[f"{i}:unit"] = Choice(
                inspect=where, question="what is that length measured in?", options=UNITS,
            )
        elif slot.operation == "format":
            questions[f"{i}:format"] = Choice(
                inspect=where, question="what does it require about the FORM of the document?",
                options=FORMAT_VERDICTS, criteria=FORMAT_EXAMPLES,
            )
            questions[f"{i}:format_noul"] = Noul(
                inspect=where, question="does it require the Europass CV format?",
            )
            questions[f"{i}:format_applicant"] = Choice(
                inspect=where, question=(
                    "reading it from the applicant's side -- what must the "
                    "applicant submit?"
                ),
                options=FORMAT_VERDICTS, criteria=FORMAT_EXAMPLES,
            )
        elif slot.operation == "language":
            # Set-valued, not one Choice. Eiffel's R-072 says "CV in French or
            # English" and render._check_language has taken a list since, so a
            # Choice here would pick one and silently forbid the other. Code
            # finds the names the sentence prints; one Noul per name asks
            # whether it is allowed, and every yes is a value.
            for name, code in language_candidates(text):
                questions[f"{i}:language:{code}"] = Noul(
                    inspect=where, question=(
                        "does it allow the document to be written in "
                        f"{name}?"
                    ),
                )
        elif slot.operation == "style":
            questions[f"{i}:style"] = Choice(
                inspect=where, question="Which presentation rule does it state?",
                # `other` is the escape the vendor asks for; it has no sink and
                # becomes `unapplied`, which is what a style we do not know is.
                options=(*STYLE_VALUES, "other"),
            )
            # The three sub-values, asked unconditionally. A detail question
            # cannot wait for the style answer -- they are in one response --
            # and asking all three costs tokens, never an extra call. Only the
            # one the chosen style needs is read.
            numbers = tuple(str(n) for n in numbers_in(text))
            questions[f"{i}:style_number"] = Choice(
                inspect=where, question="which number does it state, if any?",
                options=(*numbers, "none") if numbers else ("none", "not_stated"),
            )
            questions[f"{i}:style_spacing"] = Choice(
                inspect=where, question="what line spacing does it require, if any?",
                options=("1.0", "1.5", "2.0", "none"),
            )
            fonts = font_candidates(text)
            questions[f"{i}:style_font"] = Choice(
                inspect=where, question="which font does it name, if any?",
                options=(*fonts, "none") if fonts else ("none", "not_stated"),
            )
        elif slot.operation in ("include", "order", "emphasise"):
            questions[f"{i}:{slot.operation}"] = Choice(
                inspect=where, question=_TARGET_QUESTION[slot.operation],
                options=_TARGET_OPTIONS[slot.operation],
            )
            if slot.operation == "order":
                questions[f"{i}:order_direction"] = Choice(
                    inspect=where, question="in which direction?",
                    options=("chronological", "reverse_chronological"),
                )
        if slot.conditional:
            questions[f"{i}:condition"] = Choice(
                inspect=where, question="what is the condition about?", options=CONDITION_KINDS,
            )
    return questions


def read_values(
    candidates: Sequence[Candidate],
    slots: Sequence[Slotted],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    client: object | None = None,
    record: bool = True,
) -> tuple[Rule, ...]:
    """The typed rules and notes for one page. Chunked like the slots."""
    rules: list[Rule] = []
    for start in range(0, len(slots), CHUNK):
        chunk = slots[start : start + CHUNK]
        questions = value_questions(candidates, chunk)
        answers: dict[str, Answer] = (
            _ask(slot_state(candidates), questions, decision="D6.values", language=language,
                 budget=budget, record=record, client=client)
            if questions else {}
        )
        for slot in chunk:
            rule = _rule_for(candidates, slot, answers)
            if rule is not None:
                rules.append(rule)
    return tuple(rules)


def _below_bar(slot: Slotted) -> bool:
    return min(slot.document_confidence, slot.operation_confidence) < SLOT_BAR


def _rule_for(
    candidates: Sequence[Candidate], slot: Slotted, answers: dict[str, Answer]
) -> Rule | None:
    i = slot.index
    candidate = candidates[i]
    base = dict(index=i, document=slot.document, operation=slot.operation,
                sentence=candidate.text, heading=candidate.heading)

    if slot.document == "other" and slot.document_confidence >= SLOT_BAR:
        # Fees, deadlines, transcripts. Not this reader's business, and not a
        # note either -- a note on every unrelated sentence is noise that hides
        # the notes that matter.
        return None
    if _below_bar(slot):
        return Rule(**base, value=None, note="unsure", confidence=min(
            slot.document_confidence, slot.operation_confidence
        ), probabilities=(("document", slot.document_confidence),
                          ("operation", slot.operation_confidence)))

    value, unit, detail, confidence, note = _value(candidate, slot, answers)
    condition = ""
    if slot.conditional:
        chosen = answers.get(f"{i}:condition")
        condition = str(chosen.value) if chosen else "other"
        if condition == "other" or (chosen and chosen.confidence < SLOT_BAR):
            note = note or "conditional"
    if not note and slot.third_party:
        note = "third_party"
    if not note and not sink_for(slot.document, slot.operation, unit or value):
        note = "unapplied"
    return Rule(**base, value=value, unit=unit, detail=detail, confidence=confidence,
                note=note, condition=condition)


def _value(
    candidate: Candidate, slot: Slotted, answers: dict[str, Answer]
) -> tuple[object, str, str, float, str]:
    """The typed value, its unit, its detail, its confidence, and a note if it
    cannot stand."""
    i = slot.index
    if slot.operation == "limit":
        picked = answers.get(f"{i}:limit")
        unit_answer = answers.get(f"{i}:unit")
        if picked is None or str(picked.value) == "none":
            return None, "", "", picked.confidence if picked else 0.0, "unapplied"
        on_page = numbers_in(candidate.text)
        try:
            number = int(str(picked.value))
        except ValueError:
            return None, "", "", picked.confidence, "unapplied"
        if number not in on_page:
            # A figure nobody wrote. The options were the page's own numbers, so
            # this can only be a provider defect -- dropped, never applied.
            return None, "", "", picked.confidence, "unapplied"
        unit = str(unit_answer.value) if unit_answer else "pages"
        confidence = min(picked.confidence, unit_answer.confidence if unit_answer else 1.0)
        return number, unit, "", confidence, "" if confidence >= SLOT_BAR else "unsure"
    if slot.operation == "format":
        return _format_value(answers, i)
    if slot.operation == "order":
        target = answers.get(f"{i}:order")
        direction = answers.get(f"{i}:order_direction")
        if target is None or direction is None:
            return None, "", "", 0.0, "unapplied"
        confidence = min(target.confidence, direction.confidence)
        return ((str(target.value), str(direction.value)), "", "", confidence,
                "" if confidence >= SLOT_BAR else "unsure")
    if slot.operation == "style":
        return _style_value(answers, i)
    if slot.operation == "language":
        allowed = [
            code for key, answer in answers.items()
            if key.startswith(f"{i}:language:") and answer.value
            and answer.confidence >= SLOT_BAR
            for code in (key.rsplit(":", 1)[1],)
        ]
        if not allowed:
            return None, "", "", 0.0, "unapplied"
        confidences = [
            a.confidence for k, a in answers.items() if k.startswith(f"{i}:language:") and a.value
        ]
        # A list where the page named several, a bare string where it named one:
        # _check_language reads both, and a one-item list would change nothing
        # except how the rule reads to a person.
        value = sorted(allowed) if len(allowed) > 1 else allowed[0]
        return value, "", "", min(confidences), ""
    if slot.operation in ("include", "emphasise"):
        answer = answers.get(f"{i}:{slot.operation}")
        if answer is None:
            return None, "", "", 0.0, "unapplied"
        return (str(answer.value), "", "", answer.confidence,
                "" if answer.confidence >= SLOT_BAR else "unsure")
    if slot.operation in ("topic", "student_action"):
        # The value IS the sentence, verbatim. No question is asked, because
        # there is nothing closed to choose from -- and nothing open is invented.
        return candidate.text, "", "", slot.operation_confidence, ""
    # `other` at the bar: a real requirement with no handler (spec §6.5).
    return None, "", "", slot.operation_confidence, "unapplied"


#: Which sub-value question each style value reads. A style not here needs none:
#: `photo_forbidden` is the whole rule.
_STYLE_DETAIL: dict[str, str] = {
    "font_family": "style_font",
    "font_size_minimum": "style_number",
    "line_spacing": "style_spacing",
    "margins": "style_number",
}


def _style_value(answers: dict[str, Answer], i: int) -> tuple[object, str, str, float, str]:
    """The style rule and, where it has one, the value it names.

    A style whose detail question came back `none` or `not_stated` is a rule the
    sentence did not finish stating -- "use a legible font" names no font -- and
    it is `unapplied` rather than a rule with an empty value, which nothing
    downstream could act on.
    """
    chosen = answers.get(f"{i}:style")
    if chosen is None:
        return None, "", "", 0.0, "unapplied"
    value = str(chosen.value)
    needs = _STYLE_DETAIL.get(value)
    if needs is None:
        return (value, "", "", chosen.confidence,
                "" if chosen.confidence >= SLOT_BAR else "unsure")
    detail_answer = answers.get(f"{i}:{needs}")
    detail = str(detail_answer.value) if detail_answer else "none"
    if detail in ("none", "not_stated"):
        return value, "", "", chosen.confidence, "unapplied"
    confidence = min(chosen.confidence, detail_answer.confidence if detail_answer else 1.0)
    return value, "", detail, confidence, "" if confidence >= SLOT_BAR else "unsure"


def _format_value(answers: dict[str, Answer], i: int) -> tuple[object, str, str, float, str]:
    """Three phrasings in one request; act when two of three agree (spec §6.2).

    A Noul and a Choice on the same question are not guaranteed to agree
    (TypeSafe's own docs), which is exactly why their agreement is information.
    """
    choice = answers.get(f"{i}:format")
    noul = answers.get(f"{i}:format_noul")
    applicant = answers.get(f"{i}:format_applicant")
    if choice is None or noul is None or applicant is None:
        return None, "", "", 0.0, "unapplied"
    votes = [
        str(choice.value),
        "europass_required" if noul.value else "not_europass",
        str(applicant.value),
    ]
    europass = sum(v in ("europass_required", "europass_preferred") for v in votes)
    if votes[0] == votes[2] and votes[0] in FORMAT_VERDICTS:
        agreed = votes[0]
    elif europass >= 2:
        agreed = "europass_required" if votes.count("europass_required") >= 2 else \
            "europass_preferred"
    else:
        return str(choice.value), "", "", choice.confidence, "phrasing"
    confidence = min(choice.confidence, applicant.confidence)
    if agreed in ("europass_required", "europass_preferred") and europass < 2:
        return agreed, "", "", confidence, "phrasing"
    return agreed, "", "", confidence, "" if confidence >= SLOT_BAR else "unsure"


_TARGET_QUESTION = {
    "include": "Which piece of information must the document contain?",
    "order": "Which section must be ordered?",
    "emphasise": "Which section must be foregrounded?",
}
```

Add the imports the targets need at the top of the module:

```python
from .constraints import _INCLUDE_TARGETS, _ORDER_TARGETS, _SECTIONS
```

and, below `_TARGET_QUESTION`:

```python
#: Each with `none`: the vendor's rule is an escape option whenever the list
#: may not cover the input, and a directive forced onto the wrong field is
#: worse than one marked unapplied. `none` has no sink, so it falls through
#: to `unapplied` with the sentence kept.
_TARGET_OPTIONS: dict[str, tuple[str, ...]] = {
    "include": (*_INCLUDE_TARGETS, "none"),
    "order": (*_ORDER_TARGETS, "none"),
    "emphasise": (*_SECTIONS, "none"),
}

#: Language NAMES as a page prints them, to the ISO 639-1 code the `language`
#: constraint key and `ApplicationPrompt.document_language` use. A seed only:
#: plan 2 replaces it with vocabulary.csv's `language_names` rows in all
#: fourteen languages, and the lookup below is the seam that does not change.
#: A name missing here costs a language the sentence allowed -- never a wrong
#: one -- so it degrades to a tighter rule a person sees, not a looser one.
_LANGUAGE_NAMES: dict[str, str] = {
    "english": "en", "englisch": "en", "anglais": "en", "inglés": "en", "ingilizce": "en",
    "german": "de", "deutsch": "de", "allemand": "de", "almanca": "de",
    "french": "fr", "français": "fr", "französisch": "fr", "francais": "fr",
    "spanish": "es", "español": "es", "espagnol": "es",
    "portuguese": "pt", "português": "pt",
    "italian": "it", "italiano": "it",
    "dutch": "nl", "nederlands": "nl",
    "russian": "ru", "русский": "ru",
    "turkish": "tr", "türkçe": "tr",
    "chinese": "zh", "中文": "zh",
    "japanese": "ja", "日本語": "ja",
    "korean": "ko", "한국어": "ko",
}


def language_candidates(text: str) -> tuple[tuple[str, str], ...]:
    """Every language name the sentence prints, as (name, code), deduplicated.

    Code finds them so the Nouls that follow are about languages the page named,
    never a list of every language we know: asking thirteen Nouls on a sentence
    that names one is thirteen chances to say yes to a language nobody allowed.
    """
    lowered = text.casefold()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, code in _LANGUAGE_NAMES.items():
        if name in lowered and code not in seen:
            seen.add(code)
            found.append((name, code))
    return tuple(found)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_values.py -v`
Expected: 13 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/documents/grammar_values.py tests/documents/test_grammar_values.py
git commit -m "feat: the grammar's second request -- typed values, picked never computed

Only the operations a page states get value questions, which is what keeps the
48 format examples on format sentences and the state inside the 64k ceiling. A
limit's options are the numbers code found on the page, so a figure nobody
wrote cannot be chosen, and one that arrives anyway is dropped -- quote
verification applied to numbers.

The format verdict asks three phrasings in one request and acts on two of
three; a disagreement is a phrasing note, not a coin flip. A third-party
sentence, an unevaluable condition and an operation with no sink each produce a
note that keeps the sentence and applies nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Conflicts, and the safer value

**Files:**
- Create: `apps/documents/rule_sinks.py`
- Test: `tests/documents/test_rule_conflicts.py`

**Interfaces:**
- Consumes: `grammar.Rule`
- Produces: `resolve_conflicts(rules) -> tuple[Rule, ...]`

Spec §6.3: two rules on the same `(document, operation)` for one programme — two sentences, or the page and its PDF — both at the bar with different values is a **conflict**. Both sentences become notes and **the safer value applies**: the tighter limit, `any` for format. Nothing waits for anyone.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rule_conflicts.py
from apps.documents.grammar import Rule
from apps.documents.rule_sinks import resolve_conflicts


def _rule(index, operation, value, **kw):
    return Rule(index=index, document=kw.pop("document", "cv"), operation=operation,
                value=value, sentence=kw.pop("sentence", f"sentence {index}"),
                confidence=kw.pop("confidence", 0.95), **kw)


def test_two_page_limits_keep_the_tighter_one_and_note_both():
    """The page and its PDF disagree. A person is not asked; the safer value
    applies and both sentences are on the document (spec §6.3)."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages", sentence="no more than two pages"),
        _rule(1, "limit", 3, unit="pages", sentence="up to three pages"),
    ))
    applied = [r for r in resolved if r.applied]
    notes = [r for r in resolved if r.note == "conflict"]
    assert [r.value for r in applied] == [2]
    assert {r.sentence for r in notes} == {"no more than two pages", "up to three pages"}


def test_a_word_limit_and_a_page_limit_are_not_a_conflict():
    """Different units are different keys downstream (max_words vs max_pages),
    so both stand."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 800, unit="words"),
    ))
    assert sorted(r.value for r in resolved if r.applied) == [2, 800]


def test_two_format_verdicts_that_differ_fall_back_to_any():
    """`any` is the no-egress default. A page that contradicts itself about
    Europass must not resolve to the one action that moves student data."""
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "any"),
    ))
    applied = [r for r in resolved if r.applied]
    assert [r.value for r in applied] == ["any"]
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_two_identical_values_are_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "europass_required"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert sum(r.applied for r in resolved) == 2


def test_the_same_operation_on_different_documents_is_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages", document="cv"),
        _rule(1, "limit", 1, unit="pages", document="motivation_letter"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0


def test_a_rule_already_carrying_a_note_never_joins_a_conflict():
    """A note is not at the bar, so it cannot contradict anything -- and
    counting it would turn one uncertain sentence into two notes."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 3, unit="pages", note="third_party"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert [r.value for r in resolved if r.applied] == [2]


def test_two_include_directives_on_different_fields_are_both_applied():
    """`include` is set-valued: a page may require three fields. Only a
    single-valued operation can contradict itself."""
    resolved = resolve_conflicts((
        _rule(0, "include", "education.ects_credits"),
        _rule(1, "include", "education.thesis_title"),
    ))
    assert sum(r.applied for r in resolved) == 2


def test_two_topics_are_both_kept():
    resolved = resolve_conflicts((
        _rule(0, "topic", "why this programme", document="motivation_letter"),
        _rule(1, "topic", "your career plans", document="motivation_letter"),
    ))
    assert sum(r.applied for r in resolved) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rule_conflicts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.rule_sinks'`

- [ ] **Step 3: Write the resolver**

```python
# apps/documents/rule_sinks.py
"""Typed rules in, the sinks the engine already has out.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md §6.

Three projections and one resolver. Nothing here calls a model: by the time a
rule reaches this module it is already typed, and all that remains is to write
it where the renderer, the generator and the letter engine will find it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from .grammar import Rule

logger = logging.getLogger(__name__)

#: Operations that hold ONE value per document. Two of these at the bar with
#: different values contradict each other. `include`, `emphasise`, `topic` and
#: `student_action` are set-valued -- a page may require three fields, name two
#: themes and ask for two actions, and none of that is a contradiction.
_SINGLE_VALUED = frozenset({"limit", "language", "format", "order"})

#: When a page contradicts itself, which value is safer.
#: A limit: the smaller number -- a CV that fits two pages fits three, and the
#: reverse is what gets an application rejected.
#: A format: `any`, the no-egress default. A page that cannot make up its mind
#: about Europass must never resolve to the one action that moves student data
#: (spec §6.2, §14).
_FORMAT_SAFE = "any"


def _bucket(rule: Rule) -> tuple[str, str, str]:
    """What a rule would have to match to contradict another.

    The unit is part of it: `max_words` and `max_pages` are different keys
    downstream, so a word limit and a page limit are two rules, not a dispute.
    """
    return (rule.document, rule.operation, rule.unit)


def resolve_conflicts(rules: Sequence[Rule]) -> tuple[Rule, ...]:
    """Apply the safer value where a page contradicts itself; note every side.

    Only rules that are AT the bar can contradict each other. One already
    carrying a note is not asserting anything, so counting it would turn one
    uncertain sentence into two notes and hide the certain rule beside it.
    """
    applied: dict[tuple[str, str, str], list[Rule]] = defaultdict(list)
    for rule in rules:
        if rule.applied and rule.operation in _SINGLE_VALUED:
            applied[_bucket(rule)].append(rule)

    disputed: dict[tuple[str, str, str], object] = {}
    for bucket, group in applied.items():
        values = {r.value for r in group}
        if len(values) <= 1:
            continue
        _, operation, _ = bucket
        if operation == "limit":
            winner = min(v for v in values if isinstance(v, int))
        elif operation == "format":
            winner = _FORMAT_SAFE
        else:
            # `language` and `order`: no ordering makes one safer, so the page
            # states nothing this engine can act on. The notes carry both.
            winner = None
        disputed[bucket] = winner
        logger.info("conflicting %s rules %s; applying %r", operation, sorted(map(str, values)),
                    winner)

    resolved: list[Rule] = []
    settled: set[tuple[str, str, str]] = set()
    for rule in rules:
        bucket = _bucket(rule)
        if not (rule.applied and bucket in disputed):
            resolved.append(rule)
            continue
        # Every side of the dispute becomes a note carrying its own sentence.
        resolved.append(replace(rule, note="conflict"))
        if bucket not in settled and disputed[bucket] is not None:
            settled.add(bucket)
            winner = next(r for r in applied[bucket] if r.value == disputed[bucket])
            resolved.append(replace(winner, note=""))
    return tuple(resolved)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rule_conflicts.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/documents/rule_sinks.py tests/documents/test_rule_conflicts.py
git commit -m "feat: conflicts resolve to the safer value and note every side

A page that contradicts itself is common and is not a reason to stop: the
tighter limit applies, a contradicted format falls back to `any` -- the
no-egress default, because a page that cannot make up its mind about Europass
must never resolve to the one action that moves student data -- and both
sentences are on the document. Only a rule at the bar can contradict another;
a note asserts nothing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The CV's projection — constraint rules, directives, and the format switch

**Files:**
- Modify: `apps/documents/rule_sinks.py`
- Test: `tests/documents/test_rule_sinks_cv.py`

**Interfaces:**
- Consumes: `grammar.{Rule, sink_for}`, `constraints.{ConstraintRule, Enforcement}`, `funding.models.Program`
- Produces: `to_constraint_rules(rules, *, source_url) -> tuple[ConstraintRule, ...]`, `to_directives(rules, *, source_url) -> tuple[dict[str, object], ...]`, `to_notes(rules, *, source_url) -> tuple[ConstraintRule, ...]`, `format_decision(rules) -> tuple[str, str]`

Every derived rule is `ADVISORY_HIGH_RISK`. A note lands as an `undecided` or `unapplied` constraint rule — the two `_MULTI_KEYS` that carry a quote rather than a value, which `resolve_rules` keeps one-per-sentence and `render_cv_with_warnings` puts in front of the counsellor.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rule_sinks_cv.py
import pytest

from apps.documents.constraints import Enforcement, resolve_rules
from apps.documents.grammar import Rule
from apps.documents.rule_sinks import (
    format_decision,
    to_constraint_rules,
    to_directives,
    to_notes,
)
from apps.funding.models import Program

pytestmark = pytest.mark.django_db

_URL = "https://example.test/apply"


def _rule(index, operation, value, **kw):
    return Rule(index=index, document=kw.pop("document", "cv"), operation=operation,
                value=value, sentence=kw.pop("sentence", f"sentence {index}"),
                confidence=kw.pop("confidence", 0.95), **kw)


def test_a_page_limit_becomes_max_pages_as_an_advisory_rule():
    rules = to_constraint_rules(
        (_rule(0, "limit", 2, unit="pages", sentence="No more than two pages."),),
        source_url=_URL,
    )
    assert (rules[0].key, rules[0].value) == ("max_pages", 2)
    assert rules[0].enforcement is Enforcement.ADVISORY_HIGH_RISK
    assert rules[0].rule_text == "No more than two pages."
    assert rules[0].source_url == _URL


def test_a_word_limit_and_a_character_limit_reach_their_own_keys():
    rules = to_constraint_rules((
        _rule(0, "limit", 800, unit="words"),
        _rule(1, "limit", 4000, unit="characters"),
    ), source_url=_URL)
    assert {r.key for r in rules} == {"max_words", "max_chars_incl_spaces"}


def test_a_style_rule_becomes_the_key_it_names_with_the_right_polarity():
    """`photo_forbidden` is photo_allowed=False. Writing it as True would
    silently invert a funder's rule."""
    rules = to_constraint_rules((
        _rule(0, "style", "photo_forbidden"),
        _rule(1, "style", "signature_required"),
        _rule(2, "style", "date_of_birth_forbidden"),
    ), source_url=_URL)
    by_key = {r.key: r.value for r in rules}
    assert by_key["photo_allowed"] is False
    assert by_key["signature_required"] is True
    assert by_key["date_of_birth_allowed"] is False


def test_a_language_rule_becomes_the_language_key():
    rules = to_constraint_rules((_rule(0, "language", "en"),), source_url=_URL)
    assert (rules[0].key, rules[0].value) == ("language", "en")


def test_a_directive_carries_its_action_target_and_sentence():
    directives = to_directives((
        _rule(0, "include", "education.ects_credits", sentence="State your ECTS credits."),
        _rule(1, "order", ("cv", "reverse_chronological")),
        _rule(2, "emphasise", "research"),
    ), source_url=_URL)
    assert directives[0] == {
        "action": "include", "target": "education.ects_credits", "value": None,
        "rule_text": "State your ECTS credits.", "source_url": _URL,
    }
    assert directives[1]["value"] == "reverse_chronological"
    assert directives[2]["action"] == "emphasise"


def test_every_directive_validates_against_the_read_side_schema():
    """check_directive_shape is shared by the write side and the read side so
    the two can never drift. A directive that would fail on read must fail here."""
    from apps.documents.constraints import PageDirective

    directives = to_directives((_rule(0, "include", "education.thesis_title"),), source_url=_URL)
    assert PageDirective.model_validate(directives[0]).target == "education.thesis_title"


def test_a_note_becomes_an_undecided_rule_carrying_the_sentence():
    notes = to_notes(
        (_rule(0, "limit", None, note="unsure", sentence="Keep it short."),), source_url=_URL
    )
    assert notes[0].key == "undecided"
    assert notes[0].rule_text == "Keep it short."
    assert notes[0].enforcement is Enforcement.ADVISORY_HIGH_RISK


def test_an_unapplied_note_uses_the_unapplied_key():
    notes = to_notes(
        (_rule(0, "other", None, note="unapplied", sentence="List publications in APA style."),),
        source_url=_URL,
    )
    assert notes[0].key == "unapplied"


def test_two_notes_on_one_sentence_survive_resolve_rules(program_factory):
    """constraints._MULTI_KEYS slots undecided and unapplied by rule_id, so two
    quotes must both reach the counsellor. A shared id would silently drop one."""
    notes = to_notes((
        _rule(0, "limit", None, note="unsure", sentence="Keep it short."),
        _rule(1, "format", None, note="phrasing", sentence="We suggest Europass."),
    ), source_url=_URL)
    assert len({n.rule_id for n in notes}) == 2
    program = program_factory(cv_constraints=[n.model_dump(mode="json") for n in notes])
    resolved = resolve_rules(program, None, content=None)
    assert sum(r.key in ("undecided", "unapplied") for r in resolved) == 2


def test_the_format_switch_is_the_agreed_verdict():
    value, confidence = format_decision((_rule(0, "format", "europass_required"),))
    assert value == Program.CVFormatRequirement.EUROPASS_REQUIRED
    assert confidence == Program.CVFormatConfidence.EXTRACTED


def test_a_preferred_verdict_is_its_own_value():
    value, _ = format_decision((_rule(0, "format", "europass_preferred"),))
    assert value == Program.CVFormatRequirement.EUROPASS_PREFERRED


def test_a_page_with_no_format_rule_is_any_and_extracted():
    """A served page that states no format rule states no format rule. That is
    a result, not an abstention (spec §5.3)."""
    value, confidence = format_decision(())
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.EXTRACTED


def test_an_undecided_format_note_writes_any_and_undecided():
    value, confidence = format_decision(
        (_rule(0, "format", "europass_required", note="phrasing"),)
    )
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.UNDECIDED


def test_other_template_never_renders_a_template_the_engine_does_not_know():
    value, confidence = format_decision((_rule(0, "format", "other_template"),))
    assert value == Program.CVFormatRequirement.ANY
    assert confidence == Program.CVFormatConfidence.UNDECIDED


def test_a_third_party_format_rule_never_reaches_the_switch():
    """Measured 2026-09-14: two of three readings attributed 'Short CV (max. 2
    pages) from this academic supervisor' to the applicant."""
    value, _ = format_decision(
        (_rule(0, "format", "europass_required", note="third_party"),)
    )
    assert value == Program.CVFormatRequirement.ANY


def test_a_letter_rule_is_not_a_cv_constraint():
    assert to_constraint_rules(
        (_rule(0, "limit", 800, unit="words", document="motivation_letter"),), source_url=_URL
    ) == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rule_sinks_cv.py -v`
Expected: FAIL with `ImportError: cannot import name 'to_constraint_rules'`

- [ ] **Step 3: Write the projection**

```python
# apps/documents/rule_sinks.py -- add these imports at the top
from apps.funding.models import Program

from .constraints import ConstraintRule, Enforcement, check_directive_shape
from .grammar import sink_for
```

```python
# apps/documents/rule_sinks.py -- append

#: A style value and the value its constraint key takes. The polarity matters:
#: `photo_forbidden` is photo_allowed=False, and writing True would silently
#: invert a funder's rule.
_STYLE_VALUE: dict[str, object] = {
    "photo_required": True,
    "photo_forbidden": False,
    "signature_required": True,
    "date_of_issue_required": True,
    "date_of_birth_forbidden": False,
}

#: The format verdict as a Program.CVFormatRequirement, or None where the engine
#: must not act. `other_template` is None because render.py's _funder_dispatch
#: knows only SISGP and RHODES: deriving a template it cannot render would route
#: every other funder to UnsupportedRenderVariant (CLAUDE.md).
_FORMAT_SWITCH: dict[str, str | None] = {
    "europass_required": Program.CVFormatRequirement.EUROPASS_REQUIRED,
    "europass_preferred": Program.CVFormatRequirement.EUROPASS_PREFERRED,
    "any": Program.CVFormatRequirement.ANY,
    "not_a_format_rule": None,
    "other_template": None,
}


def _cv_rules(rules: Sequence[Rule]) -> list[Rule]:
    return [r for r in rules if r.document == "cv" and r.applied]


def to_constraint_rules(
    rules: Sequence[Rule], *, source_url: str
) -> tuple[ConstraintRule, ...]:
    """The CV's value rules as stored constraints.

    Format is not here: it is a switch on the Program, not a constraint key
    (`format_decision`). Directives are not here either (`to_directives`).
    Everything written is ADVISORY_HIGH_RISK, without exception -- a classifier
    answer can make a rule SAY "required" and can never make one BIND
    (2026-09-13 spec, CLAUDE.md).
    """
    built: list[ConstraintRule] = []
    for rule in _cv_rules(rules):
        if rule.operation in ("format", "include", "order", "emphasise",
                              "topic", "student_action", "other"):
            continue
        key = sink_for("cv", rule.operation, rule.unit or rule.value)
        if not key or key == "cv_directives":
            continue
        if rule.operation == "style":
            # A flag style is its polarity; a detail style (font family, point
            # size) is the value the sentence printed, which `detail` carries.
            value = _STYLE_VALUE.get(str(rule.value), rule.detail or rule.value)
        else:
            value = rule.value
        built.append(ConstraintRule(
            rule_id=f"PAGE-{rule.index}-{key[:9]}",
            key=key,  # type: ignore[arg-type]
            value=value,
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text=rule.sentence,
            source_url=source_url,
        ))
    return tuple(built)


def to_directives(rules: Sequence[Rule], *, source_url: str) -> tuple[dict[str, object], ...]:
    """The CV's structural rules as stored directives.

    `order` carries a (target, direction) pair; the others carry a target alone.
    Each is validated through `check_directive_shape`, the same function the
    read side runs, so a directive that would fail on read fails here instead.
    """
    built: list[dict[str, object]] = []
    for rule in _cv_rules(rules):
        if rule.operation not in ("include", "order", "emphasise"):
            continue
        if rule.operation == "order":
            target, value = rule.value  # type: ignore[misc]
        else:
            target, value = str(rule.value), None
        try:
            check_directive_shape(rule.operation, target, value)
        except ValueError:
            logger.warning("dropping a malformed %s directive for %r",
                           rule.operation, rule.sentence[:80])
            continue
        built.append({
            "action": rule.operation, "target": target, "value": value,
            "rule_text": rule.sentence, "source_url": source_url,
        })
    return tuple(built)


def to_notes(rules: Sequence[Rule], *, source_url: str) -> tuple[ConstraintRule, ...]:
    """Every note, as the `undecided` or `unapplied` rule the counsellor reads.

    These are constraints._MULTI_KEYS: they carry a QUOTE rather than a value,
    have no checker, and `render_cv_with_warnings` puts them in front of a
    person with the page's own words. The rule_id names the sentence AND the
    kind, because one sentence can be undecided about several things at once and
    resolve_rules slots these by id -- a shared id silently drops all but one.
    """
    built: list[ConstraintRule] = []
    for rule in rules:
        if rule.applied or rule.document == "other":
            continue
        key = "unapplied" if rule.note == "unapplied" else "undecided"
        built.append(ConstraintRule(
            rule_id=f"PAGE-{rule.index}-{rule.note[:9]}",
            key=key,  # type: ignore[arg-type]
            value=f"{rule.document}:{rule.operation}",
            enforcement=Enforcement.ADVISORY_HIGH_RISK,
            rule_text=rule.sentence,
            source_url=source_url,
        ))
    return tuple(built)


def format_decision(rules: Sequence[Rule]) -> tuple[str, str]:
    """The Program's format switch and its confidence.

    A page that states no format rule writes `any` + EXTRACTED: with selection
    over enumerated sentences, silence is the page's and is a result (spec §5.3).
    A format rule that could not be settled -- a phrasing disagreement, a
    conflict, a template the engine does not know -- writes `any` + UNDECIDED,
    the no-egress default, and its sentence is already a note.
    """
    verdicts = [
        r for r in rules
        if r.document == "cv" and r.operation == "format" and r.applied
    ]
    unsettled = [
        r for r in rules
        if r.document == "cv" and r.operation == "format" and not r.applied
    ]
    switches = {_FORMAT_SWITCH.get(str(r.value)) for r in verdicts}
    switches.discard(None)
    if len(switches) == 1:
        return switches.pop(), Program.CVFormatConfidence.EXTRACTED  # type: ignore[return-value]
    if unsettled or any(
        _FORMAT_SWITCH.get(str(r.value)) is None and str(r.value) == "other_template"
        for r in verdicts
    ):
        return Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.UNDECIDED
    return Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.EXTRACTED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rule_sinks_cv.py -v`
Expected: 15 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/documents/rule_sinks.py tests/documents/test_rule_sinks_cv.py
git commit -m "feat: the CV's projection -- constraint keys, directives, the format switch

Every derived rule is ADVISORY_HIGH_RISK without exception: a classifier answer
can make a rule say 'required' and can never make one bind. A style value
carries its polarity, so photo_forbidden is photo_allowed=False rather than a
silently inverted funder rule. Notes land as the two keys that carry a quote
instead of a value, with an id naming the sentence and the kind, because
resolve_rules slots them by id and a shared one drops all but the first.

A page stating no format rule writes `any` + EXTRACTED -- silence over
enumerated sentences is the page's. Anything unsettled writes `any` +
UNDECIDED, the no-egress default.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The letter's projection — one `LetterShape`, unchanged downstream

**Files:**
- Modify: `apps/documents/rule_sinks.py`
- Test: `tests/documents/test_rule_sinks_letter.py`

**Interfaces:**
- Consumes: `grammar.Rule`, `letter_shape.LetterShape`
- Produces: `to_letter_shape(rules, *, source_url) -> LetterShape`

`LetterShape` and `apply_derived_shape` are untouched: the grammar replaces how the fields are *read*, never where they go. Master's `decide_letter_shape` did this by counting votes across three frontier readings; this does it from typed values with probabilities.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rule_sinks_letter.py
import pytest

from apps.documents.grammar import Rule
from apps.documents.letter_shape import LetterShape
from apps.documents.rule_sinks import to_letter_shape

_URL = "https://example.test/apply"


def _rule(index, operation, value, **kw):
    return Rule(index=index, document=kw.pop("document", "motivation_letter"),
                operation=operation, value=value,
                sentence=kw.pop("sentence", f"sentence {index}"),
                confidence=kw.pop("confidence", 0.95), **kw)


def test_a_word_limit_lands_on_max_words():
    shape = to_letter_shape((_rule(0, "limit", 800, unit="words"),), source_url=_URL)
    assert shape.max_words == 800
    assert shape.is_stated("max_words") is True


def test_a_page_limit_and_a_character_limit_land_on_their_own_fields():
    shape = to_letter_shape((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 4000, unit="characters"),
    ), source_url=_URL)
    assert (shape.max_pages, shape.max_chars) == (2.0, 4000)


def test_a_style_rule_reaches_the_shape_field_it_names():
    shape = to_letter_shape((
        _rule(0, "style", "signed_declaration"),
        _rule(1, "style", "handwritten"),
    ), source_url=_URL)
    assert shape.signed_declaration is True
    assert shape.handwritten is True


def test_a_topic_becomes_a_written_requirement_carrying_its_sentence():
    """The letter's one free slot. It reaches the engine labelled as data with
    its source, exactly as a ProgramStatement does -- a subject, never an
    instruction (spec §6.1)."""
    shape = to_letter_shape(
        (_rule(0, "topic", "Explain your career plans.",
               sentence="Explain your career plans after graduation."),),
        source_url=_URL,
    )
    assert shape.written_requirements[0]["text"] == "Explain your career plans after graduation."
    assert shape.written_requirements[0]["source_url"] == _URL


def test_a_student_action_is_the_students_and_never_the_engines():
    shape = to_letter_shape(
        (_rule(0, "student_action", "sign it by hand",
               sentence="The letter must be signed by hand."),),
        source_url=_URL,
    )
    assert shape.student_actions[0]["text"] == "The letter must be signed by hand."


def test_a_reference_letter_rule_is_a_student_action_not_a_shape():
    """A reference letter binds the referee. For the applicant it is one action
    -- obtain it -- and it must never set the motivation letter's length."""
    shape = to_letter_shape(
        (_rule(0, "limit", 1, unit="pages", document="reference_letter",
               sentence="References must be one page."),),
        source_url=_URL,
    )
    assert shape.max_pages is None
    assert shape.student_actions[0]["text"] == "References must be one page."


def test_every_stated_field_records_where_it_came_from():
    """LetterShape.sources is what letter_render reads to tell a counsellor why
    a letter is the shape it is."""
    shape = to_letter_shape((_rule(0, "limit", 800, unit="words",
                                   sentence="At most 800 words."),), source_url=_URL)
    assert shape.sources["max_words"]["text"] == "At most 800 words."
    assert shape.sources["max_words"]["source_url"] == _URL


def test_a_note_sets_no_field():
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", note="unsure"),), source_url=_URL
    )
    assert shape.max_words is None
    assert shape.sources == {}


def test_a_page_with_no_letter_rule_is_an_empty_shape():
    assert to_letter_shape((), source_url=_URL) == LetterShape()


def test_a_font_family_that_is_not_plain_latin_text_is_dropped():
    """The one field that is not a closed list. Never interpolate it into CSS
    unvalidated -- Django's autoescaping does not neutralise ';' or '{' inside
    a CSS value (derive._SAFE_FONT_FAMILY, kept verbatim)."""
    shape = to_letter_shape(
        (_rule(0, "style", "font_family", detail="Arial; } body { display:none"),),
        source_url=_URL,
    )
    assert shape.font_family is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rule_sinks_letter.py -v`
Expected: FAIL with `ImportError: cannot import name 'to_letter_shape'`

- [ ] **Step 3: Write the letter projection**

```python
# apps/documents/rule_sinks.py -- add to the imports
import re

from .letter_shape import LetterShape
```

```python
# apps/documents/rule_sinks.py -- append

#: Letters, digits, spaces, apostrophes and hyphens only -- every real font name
#: ("Times New Roman", "Liberation Sans", "O'Malley Serif") fits, and none of
#: ";{}()/:" that would need to reach letter_render's CSS to do anything hostile
#: does. Moved verbatim from derive._SAFE_FONT_FAMILY when the judge was deleted:
#: font_family is the one letter value that is not a closed list, so this is the
#: only place fabricated CSS injection can be stopped.
_SAFE_FONT_FAMILY = re.compile(r"^[A-Za-z0-9 '\-]{1,60}$")

#: A letter style value and the LetterShape field it sets, for the booleans.
_LETTER_FLAG: dict[str, str] = {
    "signed_declaration": "signed_declaration",
    "signature_required": "signed_declaration",
    "handwritten": "handwritten",
}
_LETTER_LIMIT_FIELD: dict[str, str] = {
    "pages": "max_pages", "words": "max_words", "characters": "max_chars",
}


def to_letter_shape(rules: Sequence[Rule], *, source_url: str) -> LetterShape:
    """The letter's rules as the shape the letter engine already consumes.

    `LetterShape` and `apply_derived_shape` are untouched by this design: what
    changed is how a field's value is READ (typed answers with probabilities,
    not three frontier readings vote-counted), never where it goes.

    A reference-letter rule sets no field. It binds the referee's document, so
    for the applicant it is one action -- obtain it -- and letting it set the
    motivation letter's length is exactly the attribution error the third-party
    guard exists to prevent.
    """
    fields: dict[str, object] = {}
    sources: dict[str, dict[str, str]] = {}
    written: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []

    def state(name: str, value: object, rule: Rule) -> None:
        fields[name] = value
        sources[name] = {"text": rule.sentence, "source_url": source_url}

    for rule in rules:
        if not rule.applied:
            continue
        if rule.document == "reference_letter":
            actions.append({"text": rule.sentence, "source_url": source_url})
            continue
        if rule.document != "motivation_letter":
            continue
        if rule.operation == "student_action":
            actions.append({"text": rule.sentence, "source_url": source_url})
        elif rule.operation == "topic":
            written.append({"text": rule.sentence, "source_url": source_url})
        elif rule.operation == "limit":
            field = _LETTER_LIMIT_FIELD.get(rule.unit or "pages")
            if field:
                state(field, float(rule.value) if field == "max_pages" else int(rule.value),  # type: ignore[arg-type]
                      rule)
        elif rule.operation == "language":
            # ApplicationPrompt.document_language holds ONE code, so a page
            # allowing several needs a pick. English when it is allowed,
            # otherwise the first: the letter engine writes in one language and
            # every allowed one satisfies the page. The set is in `sources`, so
            # a person can see what else was on offer.
            allowed = rule.value if isinstance(rule.value, list) else [rule.value]
            state("document_language", "en" if "en" in allowed else allowed[0], rule)
        elif rule.operation == "style":
            _letter_style(str(rule.value), rule, state)

    return LetterShape(
        **fields,  # type: ignore[arg-type]
        sources=sources,
        written_requirements=tuple(written),
        student_actions=tuple(actions),
    )


def _letter_style(value: str, rule: Rule, state) -> None:
    """One style value onto its LetterShape field."""
    if value in _LETTER_FLAG:
        state(_LETTER_FLAG[value], True, rule)
        return
    if value == "font_family":
        family = rule.detail
        if _SAFE_FONT_FAMILY.match(family):
            state("font_family", family, rule)
        else:
            logger.warning("dropping an unsafe font family from %r", rule.sentence[:80])
        return
    if value == "font_size_minimum":
        try:
            state("font_min_pt", int(rule.detail), rule)
        except (TypeError, ValueError):
            logger.warning("dropping an unreadable font size from %r", rule.sentence[:80])
        return
    if value == "line_spacing":
        spacing = rule.detail
        if spacing in ("1.0", "1.5", "2.0"):
            state("line_spacing", float(spacing), rule)
        return
    if value == "margins":
        try:
            state("margins_cm", float(rule.detail), rule)
        except ValueError:
            logger.warning("dropping an unreadable margin from %r", rule.sentence[:80])
        return
    if value == "single_file_bundle":
        state("file_bundle", "SINGLE_PDF_ALL", rule)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rule_sinks_letter.py -v`
Expected: 10 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

```bash
git add apps/documents/rule_sinks.py tests/documents/test_rule_sinks_letter.py
git commit -m "feat: the letter's projection -- one LetterShape, nothing downstream changed

LetterShape and apply_derived_shape are untouched: what changed is how a
field's value is read, never where it goes. A reference-letter rule sets no
field -- it binds the referee, so for the applicant it is one action, and
letting it set the motivation letter's length is the attribution error the
third-party guard exists to prevent. derive._SAFE_FONT_FAMILY moves here
verbatim, because font_family is the one letter value that is not a closed list.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `derive_page_rules` switches over, and the old judge is deleted

The task that makes every earlier one real. It is one commit on purpose, so the deletion is reviewable as a deletion rather than hidden inside a feature.

**Files:**
- Modify: `apps/documents/derive.py` (delete ~900 of its 1,371 lines), `apps/documents/program_rules.py`
- Modify: `tests/documents/test_derive.py` (the tests that stub two model clients now stub the decision layer)
- Test: `tests/documents/test_derive_grammar.py` (new)

**Interfaces:**
- Consumes: `grammar_questions.read_slots`, `grammar_values.read_values`, `rule_sinks.*`, `decisions.{DecisionBudget, run_budget}`
- Produces: `derive_page_rules(program, *, page_text, snapshot, admissions_cycle="", page_language="", budget=None, client=None) -> Decision` — **the `parser` and `claude` parameters are gone**

**What must NOT be deleted — taken literally this task would take all of them, and it must not:**
- `candidates()`, `Candidate`, `_CV_TERMS`, `_THIRD_PARTY`, `_document_pattern`, `_MAX_CANDIDATES` — code still finds the sentences, additively. Plan 2 adds D4's selection *beside* this, never instead of it.
- `_write_program` — the one catalog write, so the format switch, the rules and the directives can never sit at different versions of the page.
- `detect_language` and its call — the page's language selects the letter vocabulary and, from Plan 2, the provider.
- `apply_derived_shape`, `LetterShape`, everything in `letter_shape.py`.
- Every test that asserts an *outcome* rather than a mechanism. They now stub the decision layer instead of two model clients.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_derive_grammar.py
"""derive_page_rules end to end, over a stubbed decision layer.

Every test here asserts an OUTCOME -- what lands on the Program -- rather than
how many model calls were made or in which order. That is the whole point of
replacing vote counting with typed answers: the mechanism is no longer the
thing under test.
"""
from datetime import date

import pytest
from django.utils import timezone

from apps.documents.derive import derive_page_rules
from apps.funding.models import (
    ApplicationPrompt,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db

_PAGE = """# Application documents
Your CV may not exceed two pages.
The motivation letter must be at most 800 words.
A photograph is not required.
"""


def _snapshot():
    source = OfficialSource.objects.create(
        canonical_url="https://example.test/apply", publisher="Example University",
        first_seen=date.today(),
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, fetched_at=timezone.now(), final_url="https://example.test/apply",
        content_sha256="a" * 64, retrieval_status="CURRENT",
    )


def _decisions(script):
    """Answers both grammar requests from one script of {question_id: (value, confidence)}."""

    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        answers = {}
        for qid in questions:
            value, confidence = script.get(qid, (_default(qid, questions[qid]), 0.99))
            answers[qid] = Answer(id=qid, value=value, confidence=confidence,
                                  probabilities={str(value): confidence},
                                  model="jev-1.13.0", provider="typesafe")
        return answers

    return call


def _default(qid, question):
    """Anything the script does not name answers 'nothing here', so a test only
    states the sentences it is about."""
    options = getattr(question, "options", None)
    if options is None:
        return False
    for neutral in ("other", "none", "any", "not_a_format_rule"):
        if neutral in options:
            return neutral
    return options[0]


def test_a_page_limit_lands_on_the_program_as_an_advisory_rule(program_factory):
    program = program_factory()
    derive_page_rules(
        program, page_text=_PAGE, snapshot=_snapshot(),
        client=_decisions({
            "0:document": ("cv", 0.98), "0:operation": ("limit", 0.96),
            "0:limit": ("2", 0.97), "0:unit": ("pages", 0.98),
        }),
    )
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]
    assert program.cv_constraints[0]["enforcement"] == "ADVISORY_HIGH_RISK"


def test_a_page_stating_no_format_rule_writes_any_and_extracted(program_factory):
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=_decisions({}))
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert program.cv_format_confidence == Program.CVFormatConfidence.EXTRACTED


def test_a_europass_page_switches_the_format(program_factory):
    program = program_factory()
    page = "# Documents\nCV in the Europass CV template.\n"
    derive_page_rules(
        program, page_text=page, snapshot=_snapshot(),
        client=_decisions({
            "0:document": ("cv", 0.99), "0:operation": ("format", 0.97),
            "0:format": ("europass_required", 0.96),
            "0:format_noul": (True, 0.95),
            "0:format_applicant": ("europass_required", 0.94),
        }),
    )
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED


def test_a_hand_verified_format_is_never_overwritten_but_rules_still_land(program_factory):
    program = program_factory(
        cv_format_requirement=Program.CVFormatRequirement.FUNDER_TEMPLATE,
        cv_format_verified_for_cycle="2026/27",
    )
    derive_page_rules(
        program, page_text=_PAGE, snapshot=_snapshot(),
        client=_decisions({
            "0:document": ("cv", 0.98), "0:operation": ("limit", 0.96),
            "0:limit": ("2", 0.97), "0:unit": ("pages", 0.98),
        }),
    )
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.FUNDER_TEMPLATE
    assert program.cv_constraints[0]["key"] == "max_pages"


def test_an_empty_read_on_a_served_page_replaces_the_previous_rules(program_factory):
    """Spec §5.3: with selection, a served page on which nothing is found yields
    an empty set and REPLACES the rows. A rule that vanished from a page
    vanishes from the catalog -- the generative reader kept stale rows here."""
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    derive_page_rules(program, page_text="# About us\nWe are a university.\n",
                      snapshot=_snapshot(), client=_decisions({}))
    program.refresh_from_db()
    assert program.cv_constraints == []


def test_an_unsure_sentence_becomes_a_note_the_counsellor_reads(program_factory):
    program = program_factory()
    derive_page_rules(
        program, page_text=_PAGE, snapshot=_snapshot(),
        client=_decisions({
            "0:document": ("cv", 0.55), "0:operation": ("limit", 0.44),
        }),
    )
    program.refresh_from_db()
    notes = [r for r in program.cv_constraints if r["key"] in ("undecided", "unapplied")]
    assert notes and notes[0]["rule_text"] == "Your CV may not exceed two pages."


def test_nothing_writes_a_consultant_task(program_factory):
    """Owner decision 2026-09-23: no person in the pipeline. The reader creates
    no task and waits on no one; the fetch engine's rung 7 is the only writer."""
    from apps.research.models import ConsultantResearchTask

    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=_decisions({}))
    assert ConsultantResearchTask.objects.count() == 0


def test_the_letter_shape_is_written_when_a_cycle_is_given(program_factory):
    program = program_factory()
    derive_page_rules(
        program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
        client=_decisions({
            "1:document": ("motivation_letter", 0.97), "1:operation": ("limit", 0.95),
            "1:limit": ("800", 0.96), "1:unit": ("words", 0.97),
        }),
    )
    prompt = ApplicationPrompt.objects.get(programme=program, cycle="2027")
    assert prompt.letter_max_words == 800


def test_a_provider_outage_leaves_the_catalog_untouched(program_factory):
    """'We learned nothing' must never reach a catalog write. The raise
    propagates so read_and_derive's transaction rolls the statements back too."""
    from apps.research.decisions import DecisionsUnavailable

    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])

    def down(*args, **kwargs):
        raise DecisionsUnavailable("typesafe: ConnectTimeout")

    with pytest.raises(DecisionsUnavailable):
        derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=down)
    program.refresh_from_db()
    assert program.cv_constraints[0]["rule_text"] == "old"


def test_the_old_judge_is_gone():
    """A deletion nobody can quietly undo. Each of these names was a frontier
    model call or a vote count; the grammar replaced all of them."""
    import apps.documents.derive as derive

    for name in ("_judge", "_PHRASINGS", "_SAMPLES", "_claude_reading", "_openai_reading",
                 "_with_one_retry", "_agreed_by_all", "outcomes", "decide",
                 "decide_letter_shape", "Derivations", "LetterVerdict", "FormatVerdict"):
        assert not hasattr(derive, name), f"{name} survived the switchover"


def test_derive_makes_no_frontier_model_call():
    """Owner decision 2026-09-22: no frontier model classifies. An import of an
    LLM client in this module is that decision being reversed by accident."""
    import inspect

    import apps.documents.derive as derive

    source = inspect.getsource(derive)
    for forbidden in ("ResponsesAPI", "MessagesAPI", "OPENAI_EXTRACTION_MODEL",
                      "ANTHROPIC_JUDGE_MODEL"):
        assert forbidden not in source, f"{forbidden} is still referenced"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_derive_grammar.py -v`
Expected: FAIL — `derive_page_rules() got an unexpected keyword argument 'client'`

- [ ] **Step 3: Rewrite `derive_page_rules` and delete the judge**

Replace `derive_page_rules` (`apps/documents/derive.py:1305`) with:

```python
def derive_page_rules(
    program: Program,
    *,
    page_text: str,
    snapshot: OfficialSourceSnapshot,
    admissions_cycle: str = "",
    page_language: str = "",
    budget: DecisionBudget | None = None,
    client: object | None = None,
) -> Decision:
    """Everything the catalog concludes from one read of a programme's page.

    Candidates by code over the whole page (plus the statement read's
    DOCUMENT/FORMAT sentences); two typed requests -- who and what, then which
    value; and ONE catalog write, so the format switch, the rules and the
    directives can never sit at different versions of the page. A hand-verified
    format (cv_format_verified_for_cycle) is never overwritten; its rules and
    directives still land.

    **A served page that states nothing writes nothing, and that REPLACES the
    previous rows** (spec §5.3). The generative reader kept stale rows when a
    read verified no quotes, because a generative read could fail to quote. A
    selection over enumerated sentences cannot, so its silence is the page's:
    a rule that vanished from a page vanishes from the catalog.

    Raises DecisionsUnavailable when the provider could not answer; the
    caller's transaction rolls the statement write back with it, and the fetch
    engine's retry queue reschedules the read (spec §9a).
    """
    statements = ProgramStatement.objects.filter(
        program=program,
        kind__in=(ProgramStatement.Kind.FORMAT, ProgramStatement.Kind.DOCUMENT),
    ).values_list("text", flat=True)
    language = detect_language(page_text, html_lang=page_language)
    found = candidates(page_text, statements, language=language)

    rules: tuple[Rule, ...] = ()
    if found:
        slots = read_slots(found, language=language, budget=budget, client=client)
        # The regex that marked a third-party sentence stays as an ADDITIVE
        # signal beside the scope Noul: a sentence either flags as somebody
        # else's binds nothing. A word list can add a guard here and can never
        # remove one, which is the same rule §8.1 states for every vocabulary.
        slots = tuple(
            replace(slot, third_party=slot.third_party or found[slot.index].third_party)
            for slot in slots
        )
        rules = resolve_conflicts(read_values(found, slots, language=language,
                                              budget=budget, client=client))

    format_value, confidence = format_decision(rules)
    stored = [
        *to_constraint_rules(rules, source_url=snapshot.final_url),
        *to_notes(rules, source_url=snapshot.final_url),
    ]
    fields: dict[str, object] = {
        "cv_constraints": [r.model_dump(mode="json") for r in stored],
        "cv_directives": list(to_directives(rules, source_url=snapshot.final_url)),
    }
    if not program.cv_format_verified_for_cycle:
        fields["cv_format_requirement"] = format_value
        fields["cv_format_confidence"] = confidence
    _write_program(program.id, **fields)

    if admissions_cycle:
        # One read, both documents (spec §3): the letter shape comes from the
        # same rules, inside the same transaction read_and_derive holds, so the
        # CV rules and the letter shape can never sit at different versions of
        # the page.
        apply_derived_shape(
            program, admissions_cycle,
            to_letter_shape(rules, source_url=snapshot.final_url),
            source_url=snapshot.final_url,
        )
    unapplied = sum(r.note == "unapplied" for r in rules)
    if unapplied:
        # §6.5's counter and §9a's drift signal. A rise here means the grammar
        # is falling behind what pages actually ask for.
        logger.info("derive: %d unapplied requirement sentences on %s",
                    unapplied, snapshot.final_url)
    return Decision(
        abstained=confidence == Program.CVFormatConfidence.UNDECIDED,
        format_value=format_value, confidence=confidence,
        rules=tuple(r for r in stored), directives=fields["cv_directives"],  # type: ignore[arg-type]
    )
```

Set the module's imports to exactly this — every deleted name goes with its import:

```python
# apps/documents/derive.py -- the import block
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cache
from uuid import UUID

from apps.funding.models import OfficialSourceSnapshot, Program, ProgramStatement
from apps.research.decisions import DecisionBudget
from apps.research.reader import _HEADING_LINE, normalize

from .constraints import ConstraintRule
from .grammar import Rule
from .grammar_questions import read_slots
from .grammar_values import read_values
from .letter_shape import apply_derived_shape
from .letter_terms import TERMS, detect_language
from .rule_sinks import (
    format_decision,
    resolve_conflicts,
    to_constraint_rules,
    to_directives,
    to_letter_shape,
    to_notes,
)
```

Delete, in one pass: `DerivationFailure`, `_DERIVABLE_KEY`, `_DERIVE_MAX_OUTPUT_TOKENS`, `_CLAUDE_MAX_TOKENS`, `_FORMAT_VALUE`, `_ACTION`, `_ORDER_VALUE`, `Derived`, `FormatVerdict`, `Directive`, `_SUBJECT`, `_MEASURE`, `_BOUND`, `_FORM`, `_NAMING`, `_REQUIRED`, `_TRACK`, `_BUNDLE`, `_SPACING`, `_PATH`, `LetterVerdict`, `Derivations`, `_SAMPLES`, `_QUESTION`, `_LETTER_QUESTION`, `_PHRASINGS`, `_claude_reading`, `_openai_reading`, `_with_one_retry`, `_judge`, `_FORMAT_ACTION_VALUE`, `_FORMAT_ACTION`, `_format_action`, `_OUTCOME_KIND`, `Outcome`, `_DISSENT`, `_agreed_by_all`, `_touches_cv`, `_touches_letter`, `outcomes`, `_surfaced`, `decide`, `_SAFE_FONT_FAMILY` (moved to `rule_sinks`), `_number_is_on_the_page`, `_verdicts_for`, `_naming_decision`, `_document_required_decision`, `_form_decision`, `decide_letter_shape`. Keep `Decision` — it is `derive_page_rules`' return type and three callers read it.

Then `program_rules.py` loses the two model clients:

```python
# apps/documents/program_rules.py -- the changed lines

from apps.research.decisions import DecisionBudget
from apps.research.extraction import ResponsesAPI   # still needed by read_program_page


def read_and_derive(
    *,
    program: Program,
    source: OfficialSource,
    store: ObjectStore,
    parser: ResponsesAPI,
    admissions_cycle: str,
    retrieve: Callable[[str], FetchResult] = retrieve_official_source,
    budget: DecisionBudget | None = None,
) -> ReadResult:
    """One read, one derivation, one transaction.

    `claude` is gone: no frontier model classifies (owner decision 2026-09-22),
    so derivation calls the decision layer and `parser` survives only for
    `read_program_page`'s own statement read -- which Plan 2 replaces in turn.

    **The transaction no longer spans the fetch or the model calls** (spec §9a).
    `read_program_page` fetches outside it and this function opens a short one
    around the writes, so a programme's statements and its derived rules still
    land together without holding a connection idle across a network call.
    """
    result = read_program_page(
        program=program, source=source, store=store, parser=parser,
        admissions_cycle=admissions_cycle, retrieve=retrieve,
    )
    if result.snapshot is not None and not result.snapshot.unreadable:
        with transaction.atomic():
            derive_page_rules(
                program, page_text=result.page_text, snapshot=result.snapshot,
                admissions_cycle=admissions_cycle, page_language=result.page_language,
                budget=budget,
            )
    return result
```

**`read_program_page` still writes its statements in its own transaction.** Check that before committing: if it does not, keep the outer `transaction.atomic()` around both calls for this task and let Plan 2 move it, and say so in the commit message. Do not guess.

- [ ] **Step 4: Update the existing tests**

`tests/documents/test_derive.py` keeps every case that asserts an outcome and loses every case that asserts the mechanism. Delete: `test_the_judge_asks_three_times_in_three_phrasings_and_two_model_families`, `test_the_claude_budget_stays_inside_the_sdk_non_streaming_ceiling`, `test_a_dropped_openai_reading_is_asked_once_more`, `test_a_retry_repeats_the_same_phrasing`, `test_a_thin_claude_reading_is_asked_once_more`, `test_a_claude_reading_that_fails_twice_is_a_missing_sample_and_is_logged`, `test_a_reading_that_is_thin_twice_keeps_its_retry`, `test_a_claude_answer_the_sdk_could_not_validate_twice_is_a_missing_sample`, `test_an_openai_answer_the_sdk_could_not_validate_is_retried_not_a_crash`, `test_the_real_anthropic_sdk_sends_the_schema_and_parses_the_answer`, `test_the_judge_raises_when_no_sample_answered`, and every test importing `Derivations`, `Derived`, `FormatVerdict`, `LetterVerdict` or `Outcome`.

Keep and re-point at the stubbed decision layer: `test_one_read_switches_the_format_writes_the_rule_and_the_directive`, `test_a_page_the_statement_read_could_not_quote_is_still_judged`, `test_an_unchanged_page_derives_nothing_again`, `test_an_unreadable_page_derives_nothing`, `test_derive_page_rules_resolves_a_non_english_page_via_the_language_detector`, `test_a_hand_verified_format_is_never_overwritten_but_rules_still_land`, `test_a_page_with_no_cv_line_makes_no_judge_call`, `test_the_page_rule_reaches_a_render_as_an_advisory_violation_with_the_sentence`, and every `candidates()` test (they test code, which did not change).

**`test_a_split_reading_abstains_and_the_counsellor_sees_the_sentence` becomes `test_a_disagreement_is_a_note_the_counsellor_sees`** — the mechanism changed from three readings splitting to three phrasings disagreeing, and the outcome it pins is the same one.

- [ ] **Step 5: Run the whole suite**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest`
Expected: all green. This is the first task where the catalog path runs on the decision layer, so a failure here is a real regression, not a fixture problem.

- [ ] **Step 6: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config`
Expected: all clean

- [ ] **Step 7: Commit**

```bash
git add apps/documents/ tests/documents/
git commit -m "feat: the catalog path runs on the grammar; the nine-call judge is deleted

derive_page_rules takes no model client. Two typed requests replace three
phrasings times three readings times two model families, at a thousandth of the
cost, and the mechanism is no longer the thing under test -- every surviving
test asserts what lands on the Program.

A served page that states nothing now REPLACES the previous rows. The
generative reader kept them because a generative read could fail to quote; a
selection over enumerated sentences cannot, so its silence is the page's and a
rule that vanished from a page vanishes from the catalog.

The third-party regex stays beside the scope question as an additive guard: a
word list may add a guard and never remove one.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: The two ship gates — 48 sentences, and every catalogued rule

Neither gate is a unit test. Gate 1 spends real money and runs deliberately; gate 7 is a human mapping made once and pinned forever after.

**Files:**
- Create: `docs/research/rule-grammar-map.csv`
- Create: `tests/documents/test_grammar_gate.py`
- Modify: `pyproject.toml` if `live` is not already a declared marker (it is — `addopts = "-m 'not live'"`)

**Interfaces:**
- Consumes: `grammar_values.{value_questions, read_values}`, `grammar_questions.read_slots`, `docs/research/cv-format-eval.csv`, the three rule catalogs
- Produces: no code — two gates

Spec §11 gates 1 and 7. **Gate 7 runs first**, because a grammar that cannot express a rule the catalogs already hold is a missing operation, and finding that after the decision layer ships is finding it too late.

- [ ] **Step 1: Write the expressibility map**

A person reads all 216 rows and writes one line per rule into `docs/research/rule-grammar-map.csv`:

```csv
rule_id,catalog,document,operation,value,note
R-001,cv-rules,cv,limit,pages,
S-010,cv-style-rules,cv,style,photo_forbidden,
S-026,cv-style-rules,cv,other,,"action verbs and outcome-first phrasing -- a writing-quality rule, not a page rule; the generator's prompt carries it"
L-041,letter-rules,motivation_letter,other,,"Cambridge's AI prohibition -- ai_use_policy, a catalog-only key no page sentence states"
M-003,letter-rules,motivation_letter,style,signed_declaration,
```

`operation = other` with a note is a legitimate row: it records a catalogued rule that is **not** a page-stated requirement (a writing-quality convention, a catalog-only key). What gate 7 refuses is a row whose rule a page *would* state and the grammar cannot carry — that is a missing operation, and the grammar grows before this task's commit.

Expected shape: the great majority map to `limit`, `format`, `include`, `order`, `style` and `topic`; a minority are `other` with a reason.

- [ ] **Step 2: Write the failing test**

```python
# tests/documents/test_grammar_gate.py
"""The two ship gates of spec §11.

Gate 7 (expressibility) is a plain test and runs everywhere. Gate 1 (the 48-row
CV-format eval) calls a real provider and carries the `live` marker, so
`addopts = "-m 'not live'"` keeps it out of a default run; select it with
`-m live`. Cost per run at Jev's $0.042/MTok: well under a cent.
"""
import csv
import pathlib

import pytest

from apps.documents.grammar import DOCUMENTS, OPERATIONS, STYLE_VALUES, UNITS, sink_for

_DOCS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research"
_MAP = _DOCS / "rule-grammar-map.csv"
_CATALOGS = {
    "cv-rules": _DOCS / "cv-rules.csv",
    "cv-style-rules": _DOCS / "cv-style-rules.csv",
    "letter-rules": _DOCS / "letter-rules.csv",
}


def _mapped():
    with _MAP.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_every_catalogued_rule_is_in_the_map():
    """Gate 7. A rule in the catalogs with no line here is a rule nobody
    checked the grammar against -- which is how a missing operation is found
    after shipping instead of before."""
    mapped = {row["rule_id"] for row in _mapped()}
    for catalog, path in _CATALOGS.items():
        with path.open(encoding="utf-8") as handle:
            ids = {row[next(iter(row))] for row in csv.DictReader(handle)}
        missing = ids - mapped
        assert not missing, f"{catalog}: {len(missing)} unmapped rules, e.g. {sorted(missing)[:5]}"


def test_every_mapped_slot_is_in_a_closed_list():
    for row in _mapped():
        assert row["document"] in DOCUMENTS, row
        assert row["operation"] in OPERATIONS, row
        if row["operation"] == "style" and row["value"]:
            assert row["value"] in STYLE_VALUES, row
        if row["operation"] == "limit" and row["value"]:
            assert row["value"] in UNITS, row


def test_every_mapped_rule_reaches_a_sink_or_says_why_not():
    """An `other` row is legitimate -- a writing-quality convention or a
    catalog-only key is not a page-stated requirement -- but it must say so.
    A silent `other` is a missing operation wearing a disguise."""
    for row in _mapped():
        if row["operation"] == "other":
            assert row["note"].strip(), f"{row['rule_id']} is `other` with no reason"
            continue
        sink = sink_for(row["document"], row["operation"], row["value"] or row["value"])
        assert sink, f"{row['rule_id']} maps to {row['operation']} with no sink"


def test_the_unapplied_share_of_the_catalogs_is_small():
    """Gate 8's static half: if a fifth of the rules we already researched
    cannot be carried, the grammar is not ready for pages nobody has read."""
    rows = _mapped()
    other = [r for r in rows if r["operation"] == "other"]
    assert len(other) / len(rows) <= 0.2, (
        f"{len(other)} of {len(rows)} catalogued rules have no operation"
    )


@pytest.mark.live
def test_the_forty_eight_row_format_gate():
    """Gate 1. Every row of cv-format-eval.csv through the real grammar.

    The bar is the one the frontier judge met (spec §11.1): 48/48 on the
    Europass ACTION -- whether the CV would render Europass -- and >= 46/48 on
    the exact verdict. The action matters more than the label because it is what
    moves student data.
    """
    from apps.documents.derive import Candidate
    from apps.documents.grammar_questions import read_slots
    from apps.documents.grammar_values import read_values

    path = _DOCS / "cv-format-eval.csv"
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 48

    candidates = tuple(
        Candidate(text=row["sentence"], heading="", europass="europass" in row["sentence"].lower())
        for row in rows
    )
    slots = read_slots(candidates, record=False)
    rules = {r.index: r for r in read_values(candidates, slots, record=False)}

    action_wrong, verdict_wrong = [], []
    for i, row in enumerate(rows):
        rule = rules.get(i)
        got = str(rule.value) if rule and rule.applied and rule.operation == "format" else "any"
        expected = {"europass": "europass_required",
                    "europass_preferred": "europass_preferred"}.get(row["outcome"], "any")
        renders_europass = got.startswith("europass")
        should_render = expected.startswith("europass")
        if renders_europass != should_render:
            action_wrong.append((row["id"], expected, got))
        if got != expected:
            verdict_wrong.append((row["id"], expected, got))

    print(f"\naction wrong: {action_wrong}\nverdict wrong: {verdict_wrong}")
    assert not action_wrong, f"{len(action_wrong)} of 48 wrong on the ACTION"
    assert len(verdict_wrong) <= 2, f"{len(verdict_wrong)} of 48 wrong on the verdict"
```

- [ ] **Step 3: Run the gates**

```bash
POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_gate.py -v
```
Expected: 4 passed, 1 deselected. **If gate 7 fails, the grammar is short an operation — add it to `grammar.py`, give it a sink, and re-run. That is the gate working, not the test being wrong.**

```bash
TYPESAFE_API_KEY=... POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_grammar_gate.py -m live -v
```
Expected: pass, with the two printed lists empty or nearly so. **Record the two counts in the commit message.** If the action bar is missed, the shipped threshold moves up before anything else proceeds — §6.2's bar is a starting value and this is the measurement that sets it.

- [ ] **Step 4: Commit**

```bash
git add docs/research/rule-grammar-map.csv tests/documents/test_grammar_gate.py
git commit -m "test: the two ship gates -- every catalogued rule, and the 48 real sentences

Gate 7 runs first and is the cheap one: a grammar that cannot express a rule the
catalogs already hold is a missing operation, and finding that after the
decision layer ships is finding it too late. An `other` row is legitimate when
it says why -- a writing-quality convention is not a page-stated requirement --
and a silent one is a missing operation in disguise.

Gate 1 is the 48 rows a person already confirmed, scored on the ACTION first:
whether the CV would render Europass matters more than the label, because it is
what moves student data.

Live gate result: <action wrong>/48 on the action, <verdict wrong>/48 on the verdict.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: The re-derivation sweep, the counters, and the record

**Files:**
- Create: `apps/documents/management/commands/rederive_rules.py`
- Modify: `CLAUDE.md`, `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`
- Test: `tests/documents/test_rederive_rules.py`

**Interfaces:**
- Consumes: `DecisionRecord`, `ProgramStatement`, `grammar_questions.read_slots`, `grammar_values.read_values`, `rule_sinks.*`, `decisions.run_budget`
- Produces: `manage.py rederive_rules [--program <id>] [--dry-run]`

Spec §6.5: when the grammar grows, the slot questions are re-asked over **stored sentences**, so every programme that ever stated the rule gets it without a page being refetched. This is also the sweep CLAUDE.md warns about — it calls the decision layer directly, so it carries its own budget or it is an unbounded call per programme.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rederive_rules.py
from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.funding.models import (
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramStatement,
)
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db


def _statement(program, text, **kw):
    source = OfficialSource.objects.create(
        canonical_url="https://example.test/apply", publisher="Example",
        first_seen=date.today(),
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, fetched_at=timezone.now(), final_url="https://example.test/apply",
        content_sha256="a" * 64, retrieval_status="CURRENT",
    )
    return ProgramStatement.objects.create(
        program=program, snapshot=snapshot, kind=kw.get("kind", "DOCUMENT"),
        requirement="REQUIRED", text=text, label=text[:40],
    )


def _client(script):
    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        return {
            qid: Answer(id=qid, value=script.get(qid, ("other", 0.99))[0],
                        confidence=script.get(qid, ("other", 0.99))[1],
                        probabilities={}, model="jev-1.13.0", provider="typesafe")
            for qid in questions
        }

    return call


def test_a_stored_sentence_yields_its_rule_without_a_page(program_factory, monkeypatch):
    """§6.5: when the grammar grows, every programme that ever stated the rule
    gets it -- without refetching a single page."""
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    monkeypatch.setattr(
        "apps.documents.management.commands.rederive_rules._client",
        lambda: _client({
            "0:document": ("cv", 0.98), "0:operation": ("limit", 0.96),
            "0:limit": ("2", 0.97), "0:unit": ("pages", 0.98),
        }),
    )
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]


def test_nothing_is_fetched(program_factory, monkeypatch):
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")

    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("the sweep refetched a page")

    monkeypatch.setattr("apps.research.discovery.retrieve_official_source", explode)
    monkeypatch.setattr(
        "apps.documents.management.commands.rederive_rules._client",
        lambda: _client({}),
    )
    call_command("rederive_rules", stdout=StringIO())


def test_a_dry_run_writes_nothing_and_reports_what_would_change(program_factory, monkeypatch):
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    monkeypatch.setattr(
        "apps.documents.management.commands.rederive_rules._client",
        lambda: _client({
            "0:document": ("cv", 0.98), "0:operation": ("limit", 0.96),
            "0:limit": ("2", 0.97), "0:unit": ("pages", 0.98),
        }),
    )
    out = StringIO()
    call_command("rederive_rules", "--dry-run", stdout=out)
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert "max_pages" in out.getvalue()


def test_the_sweep_stops_on_its_budget_rather_than_running_unbounded(program_factory,
                                                                     monkeypatch, settings):
    """CLAUDE.md names this exact sweep as the one that makes an unbounded model
    call per programme unless it adds its own limiter."""
    settings.DECISIONS_RUN_TOKENS = 1
    for _ in range(3):
        _statement(program_factory(), "Your CV may not exceed two pages.")
    monkeypatch.setattr(
        "apps.documents.management.commands.rederive_rules._client", lambda: None
    )
    out = StringIO()
    call_command("rederive_rules", stdout=out)
    assert "budget" in out.getvalue().lower()


def test_a_programme_with_no_statements_is_skipped(program_factory, monkeypatch):
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    monkeypatch.setattr(
        "apps.documents.management.commands.rederive_rules._client", lambda: _client({})
    )
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    # Untouched: a programme nothing has read has no stored sentences, and an
    # empty re-derivation there would erase rules a read DID produce.
    assert program.cv_constraints[0]["rule_text"] == "old"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rederive_rules.py -v`
Expected: FAIL with `CommandError: Unknown command: 'rederive_rules'`

- [ ] **Step 3: Write the command**

```python
# apps/documents/management/commands/rederive_rules.py
"""Re-ask the grammar over stored sentences, without refetching a page.

Spec §6.5. When an operation enters the grammar -- because the unapplied count
said the kind was real -- every programme that ever stated that rule should get
it. Refetching the catalog to learn that would cost a sweep's worth of credits
for pages that have not changed; the sentences are already stored, with their
heading path (spec §9a), so the questions can simply be asked again.

**This is the sweep CLAUDE.md warns about.** It calls the decision layer
directly rather than through `read_program_page`, which is the only place the
per-programme limiter lives, so it carries its own budget or it is an unbounded
call per programme.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from apps.documents.derive import Candidate
from apps.documents.grammar_questions import read_slots
from apps.documents.grammar_values import read_values
from apps.documents.rule_sinks import (
    format_decision,
    resolve_conflicts,
    to_constraint_rules,
    to_directives,
    to_notes,
)
from apps.funding.models import Program, ProgramStatement
from apps.research.decisions import DecisionBudgetExhausted, run_budget


def _client() -> object | None:
    """The decision client. A seam so a test injects without a network call."""
    return None


class Command(BaseCommand):
    help = "Re-derive every programme's rules from its stored sentences. Fetches nothing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--program", help="one programme id; default is every programme")
        parser.add_argument("--dry-run", action="store_true",
                            help="report what would change and write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        budget = run_budget()
        client = _client()
        programmes = Program.objects.all()
        if options["program"]:
            programmes = programmes.filter(id=options["program"])

        changed = 0
        for program in programmes.iterator():
            statements = list(
                ProgramStatement.objects.filter(program=program)
                .order_by("id")
                .values_list("text", "snapshot__final_url")
            )
            if not statements:
                # Nothing has read this programme. An empty re-derivation here
                # would erase rules a real read DID produce.
                continue
            source_url = statements[0][1] or ""
            candidates = tuple(
                # `heading` is empty: Plan 2 stores heading_path on the
                # statement and this reads it. Until then the sentence stands
                # alone, which is why this sweep is run deliberately and its
                # output read, not scheduled.
                Candidate(text=text, heading="", europass="europass" in text.lower())
                for text, _ in statements
            )
            try:
                slots = read_slots(candidates, budget=budget, client=client)
                rules = resolve_conflicts(
                    read_values(candidates, slots, budget=budget, client=client)
                )
            except DecisionBudgetExhausted as error:
                self.stdout.write(f"stopping: decision budget reached ({error})")
                break

            stored = [
                *to_constraint_rules(rules, source_url=source_url),
                *to_notes(rules, source_url=source_url),
            ]
            payload = [r.model_dump(mode="json") for r in stored]
            directives = list(to_directives(rules, source_url=source_url))
            if payload == program.cv_constraints and directives == program.cv_directives:
                continue
            changed += 1
            self.stdout.write(
                f"{program.canonical_key}: {[r['key'] for r in payload]} "
                f"{[d['action'] for d in directives]}"
            )
            if options["dry_run"]:
                continue
            format_value, confidence = format_decision(rules)
            fields: dict[str, object] = {
                "cv_constraints": payload, "cv_directives": directives,
            }
            if not program.cv_format_verified_for_cycle:
                fields["cv_format_requirement"] = format_value
                fields["cv_format_confidence"] = confidence
            with transaction.atomic():
                Program.objects.filter(id=program.id).update(**fields)

        self.stdout.write(
            f"{changed} programmes changed; {budget.spent} decision tokens spent"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/test_rederive_rules.py -v`
Expected: 5 passed

- [ ] **Step 5: Rewrite the record**

In `CLAUDE.md`, the "LLM/AI security" section's bullets about `derive.py`'s judge and the "CV-format decision is three readings" paragraph are now history. Replace them with the grammar, keeping as *record with its reason*: the 61% keyword measurement, the measured Swiss supervisor's-CV attribution error, and the rule that a programme rule may not lower a key's enforcement. State plainly what replaced them: one classifier, four slots over closed lists, the sinks that already exist, the bar at 0.85 with three phrasings on the format, and notes on the document instead of a person in the pipeline.

Add one paragraph that did not exist before, because it is the trap a future session will fall into:

> **The grammar is closed on purpose, and `unapplied` is a feature.** A page can state a requirement no operation carries — the first "publications in APA style". The sentence is kept, shown on the document and counted; it is never passed to the writing model as free instruction. That door is how a hostile page would reach the generator, and how the old attribution errors got in. When the count says a kind is real, add the operation and its handler in code, then run `manage.py rederive_rules` — every programme that ever stated it gets the rule without a page being refetched.

In `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`, extend the existing "superseded in mechanism" pointer with the date the mechanism actually landed and the section that holds it.

- [ ] **Step 6: Run everything**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_decisions uv run pytest && uv run bandit -c pyproject.toml -r apps config && uv run pip-audit && POSTGRES_DB=tehsil_decisions uv run python manage.py makemigrations --check --dry-run`
Expected: all clean

- [ ] **Step 7: Commit**

```bash
git add apps/documents/ tests/documents/ CLAUDE.md docs/superpowers/specs/
git commit -m "feat: rederive_rules, and the record of what replaced the judge

When an operation enters the grammar because the unapplied count said the kind
was real, every programme that ever stated that rule gets it -- from stored
sentences, with no page refetched. This is the sweep CLAUDE.md warns about, so
it carries its own budget; a programme with no stored sentences is skipped,
because an empty re-derivation there would erase rules a real read produced.

CLAUDE.md now records the grammar and keeps the three measurements that argue
for it: the keyword rule's 61%, the Swiss supervisor's-CV attribution error,
and the enforcement guard. The new paragraph is the one a future session needs:
`unapplied` is a feature, and the closed grammar is the door this design keeps
shut.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: The other Jev client folds into `decisions.ask()`

**Files:**
- Modify: `apps/documents/research_fit/jev.py`, `tests/documents/research_fit/test_jev.py`
- Test: `tests/documents/research_fit/test_jev.py` (rewritten stubs, same assertions)

**Interfaces:**
- Consumes: `decisions.ask`, `decisions.Noul`, `decisions.Choice`, `decisions.DecisionsUnavailable`, `settings.TYPESAFE_MODEL`
- Produces: `JevClassifier(*, client=None, relevance_floor=None)` — the `api_key=` and `post=` parameters go

Master carries a second TypeSafe client (see the reconciliation section above). This task deletes its
transport and leaves everything that makes it *this* classifier: `_ENTITY_PATTERNS`,
`entity_by_pattern`, the `entity_in_sentence` substring check, and the `ClassifiedSentence` shape
`service.py` consumes. The two questions become one `ask()` call per sentence under the decision key
`D6`, which is what the decision table already calls this classification.

- [ ] **Step 0: Re-check the paths**

```bash
git fetch origin && git log --oneline -1 origin/master
sed -n '1,20p' apps/documents/research_fit/jev.py
grep -rn "JevClassifier" apps tests
```

If `service.py` has gained a branch that builds `JevClassifier`, this task changes the letter path
and needs its own review round; at 40f8400 it had not.

- [ ] **Step 1: Write the failing test**

Rewrite `tests/documents/research_fit/test_jev.py`'s stubs: every test that passed `post=` passes a
fake `client=` returning `{"relevant": Answer(...), "kind": Answer(...)}`. The assertions do not
change — a malformed reply is still `DecisionsUnavailable`, an off-page entity is still kind
`"none"`, a missing key still raises before the first sentence. Add one:

```python
def test_the_pinned_version_is_asked_for_not_the_alias(settings):
    """jev-latest moves under a tuned threshold. decisions.ask() pins the
    version for every caller; this one used to ask for the alias."""
    settings.TYPESAFE_MODEL = "jev-1.13.0"
    seen: list[str] = []
    JevClassifier(client=_recording(seen)).classify(("A sentence about robotics.",), topic="t")
    assert seen == ["jev-1.13.0"]
```

Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'client'`.

- [ ] **Step 2: Implement**

`_ask` becomes:

```python
    def _ask(self, sentence: str, topic: str) -> tuple[float, str]:
        answers = ask(
            sentence,
            {
                "relevant": Noul(
                    f"Does this sentence describe research or teaching work related to: {topic}?"
                ),
                # Choice takes the options beside the criteria, and `none` has
                # no description -- it is the residual, and a criterion for it
                # would invite the classifier to argue for it.
                "kind": Choice(
                    "What does this sentence name?",
                    tuple(_KIND_CRITERIA),
                    {k: v for k, v in _KIND_CRITERIA.items() if v},
                ),
            },
            decision="D6",
            budget=self._budget,
            client=self._client,
        )
        kind = answers["kind"].value
        # P(yes), not `.confidence`: a Noul's confidence is 1 - P(yes) when the
        # answer is False, and this caller's floor is a relevance, not a
        # certainty. Reading `.confidence` here would score a confidently
        # irrelevant sentence as highly relevant.
        return answers["relevant"].probabilities.get("true", 0.0), (
            kind if kind in KIND_VALUES else "none"
        )
```

`JEV_URL`, `JEV_MODEL`, `self._key`, `self._post`, `self.input_tokens` and the `ProviderUnavailable`
translation all go: `ask()` raises `DecisionsUnavailable` on a missing key and on a malformed reply,
and counts tokens onto the budget. `relevance_floor` stays a constructor argument at `0.5` — it is
research fit's own relevance bar over D6's distribution, not one of `SLOT_BAR`'s slot thresholds, and
moving it would change what the letter cites. Keep the module docstring's DPA sentence.

- [ ] **Step 3: Verify**

```bash
POSTGRES_DB=tehsil_decisions uv run pytest tests/documents/research_fit/ -v
uv run ruff check apps config tests scripts && uv run mypy apps config
```

Expected: all pass. `tests/documents/research_fit/test_live.py` still imports `JevClassifier` and
still skips without a key — it is the 24-row EN/DE/TR gate, and it is now the decision layer's
measurement rather than research fit's.

- [ ] **Step 4: Commit**

```bash
git add apps/documents/research_fit/jev.py tests/documents/research_fit/test_jev.py
git commit -m "refactor(research-fit): one Jev client, not two

research_fit/jev.py built its own questions against its own transport, with
the jev-latest alias, no cache, no budget and no DecisionRecord row. It had no
caller -- service.py builds FrontierClassifier unconditionally -- so folding it
into decisions.ask() now costs a test rewrite and no behaviour change. What it
gains is what every other decision has: the pinned version, the cache, the run
budget, and one place where D6's threshold is tuned.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review against the spec

Checked section by section on 2026-09-23.

**Covered:** §3.1's eight failure modes (literal questions with criteria in Task 5/6; no arithmetic in Task 6's `numbers_in`; one judgment per question throughout; sentences not pages in Task 5; §9's security in Tasks 6–8; no negated questions; per-question thresholds in `SLOT_BAR`; per-language routing in Task 1). §3.2 entirely (Task 1). §4's D6 row (Tasks 5–6). §5.3's replace-on-empty (Task 10). §5.4's notes (Tasks 8, 10). §6.1–§6.5 (Tasks 4–9). §6.7's deletion list (Task 10). §9's five points (Tasks 6, 8, 10). §9a's trigger, transaction, records, budget, outage, keys and counters (Tasks 1–3, 10, 12). §11 gates 1, 7, 8-static (Task 11).

**Deliberately deferred to plan 2, and each is named in that plan's header:** §5.1's sentence splitter and stored `heading_path` — this plan uses `derive.candidates()`, which finds its own sentences by code, and Task 5 takes context from `Candidate.heading`, so the seam is already the right shape; §6.6's template reading; §8 entirely (vocabularies, `language`, `normalize`, translation); §11 gates 2–6, 9, 10, which need the corpus or the reader.

**Two gaps found and closed while writing this plan:**
- The spec's §6.1 gave `topic` no CV sink and did not say so. `grammar._cv_sink` now returns `""` for it with the reason: the CV states facts from the ledger and has no free-text section a topic could steer.
- The spec said conflicts apply "the safer value" without saying what is safer for `language` and `order`. Task 7 answers it: no ordering makes one safer, so nothing is applied and both sentences are notes.

**One thing this plan cannot verify and says so:** whether `read_program_page` opens its own transaction. Task 10 Step 3 stops and checks rather than guessing, because moving the boundary wrongly would let a programme's statements and its rules land at different versions of the page — the failure `read_and_derive` was built to prevent.

## After the plan

Plan 2 (`2026-09-23-reader-and-multilingual-layer.md`) replaces `candidates()` with D4's selection over split sentences, stores the heading path, and adds the multilingual layer. Plan 3 folds D1, D2, D3 and D8 into the fetch engine's funnel. Neither changes anything this plan builds: `ask()`, the four slots and the sinks are the seams they consume.
