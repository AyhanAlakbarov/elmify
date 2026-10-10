# The Decision Layer and the Rule Grammar, as amended — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read CV and motivation-letter requirements off programme pages as typed, closed decisions, cheaply and reliably:
- Jev answers each question with a probability, reached through OpenRouter.
- Code finds every figure and its unit.
- One rule grammar projects each answer onto the sinks the CV and letter engines already read.
- The current three-reading judge stays as the fallback whenever no decision provider is configured.

**Architecture:**
- `apps/research/decisions.py` owns every question, threshold and provider, and the client: Jev via OpenRouter by default, TypeSafe's own endpoint when `DECISIONS_BASE_URL` names it.
- `research.DecisionRecord` stores every answer with its probabilities and model version, and doubles as the cache.
- `apps/documents/grammar.py` takes a requirement sentence apart into document, operation, value and scope. Every figure is its own decision, with its bound (maximum, minimum, approximate, a section's limit, another statement's limit, or not a limit).
- The result lands on the existing sinks: `Program.cv_constraints`, `Program.cv_directives`, and `LetterShape` / `ApplicationPrompt.letter_*`. That includes the new `min_chars` and `document_language`.

**Tech Stack:** Django 5.2, PostgreSQL row-level security (the 2026-09-25 role model: `runtime_engine` / `runtime_web`), `typesafe-sdk==0.7.1` pointed at OpenRouter, `system-one-adapter[anthropic,openai]==0.2.1`, pydantic 2, pytest.

**Spec:**
- `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` (the design);
- `docs/superpowers/specs/2026-09-26-requirement-reader-addendum-design.md` (its amendment, which wins where they differ).

Read the addendum in full, then the design's §3, §4, §6, §9, §9a and §11, before Task 1. This plan **supersedes** `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` ("the 2026-09-23 plan"). Its text is kept where it was still right, and every changed block is marked `<!-- amended 2026-09-26 -->` or `<!-- reconciled 2026-09-26 -->`. The 2026-09-23 plan stays in the repo as the record.

**Branch and database:**
- Branch `claude/requirement-reader`, in worktree `.worktrees/requirement-reader`.
- Test database `POSTGRES_DB=tehsil_requirement_reader`. Never share a test database between sessions (CLAUDE.md).
- Commit with `uv run git commit` (the pre-commit hooks need the venv), and end every message with the line `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Global Constraints

- **Engine, not rules.** No code on the read path may name a particular university, host or programme. The guard test `tests/documents/test_letter_page_corpus.py::test_no_engine_code_names_a_corpus_university` joins this branch with the corpus (addendum §8), and until then the same rule binds reviewers (owner, 2026-09-25).
- **One run per page, both documents.** CV and letter requirements come from the same read. No task adds a second pass per document.
- **The classifier:**
  - Default `DECISIONS_BASE_URL=https://openrouter.ai/api`, key `OPENROUTER_API_KEY`, model pinned by `TYPESAFE_MODEL=typesafe/jev-1.13`, never an alias.
  - `TYPESAFE_API_KEY` is sent only to TypeSafe's own host.
- **Fallback, not stop.** With no decision provider configured, `derive_page_rules` runs the existing frontier judge unchanged. The frontier judge is deleted only after addendum §8's corpus gates pass on Jev, and never in this plan.
- **Failures:**
  - A failed decision request never crashes a page read. It leaves the page's previous rules standing and marks the read `decision_failed`.
  - A refused request is recorded once and never retried.
- **Catalogue tables follow CLAUDE.md's recipe:** `shared_catalog_select`, `runtime_engine_write`, and `REVOKE ALL … FROM runtime_web` in the same migration. `tests/tenancy/test_catalog_grants.py` must pass.
- **Migrations:** research `0010`, `0011`; funding `0050`. Re-read each app's migration tip at the start of the task that adds one, and renumber if master moved.
- **Numbers come from the page.** Only `letter_terms.figures_on_line` finds figures. A model never supplies a number, and the grammar copies the picked figure verbatim.
- **Enforcement never drops.** A derived rule never lowers a `BINDING` one (`constraints.resolve_rules`, unchanged).
- **Interfaces other plans consume do not change:** `decisions.ask`, `decisions.Noul`, `decisions.Choice`, `DecisionRecord`, `DecisionBudget`, `DecisionsUnavailable`. The award-card plan (build item 13, Part B) and the reader plan consume them.
- **Nothing student-derived is cached in a catalogue table.** `DecisionRecord` holds page sentences only. A question whose state carries student text (research fit) is never cached there.
- **Quality gate before every commit:** `uv run ruff check .`, `uv run mypy apps config`, and the task's tests. The full suite runs before Task 13's commit and at the end.

## Review Focus

The five inputs most likely to hurt someone that the spec implies but no drafted test covered. Each has its test in the owning task, marked `<!-- review focus N -->`:

1. **A year beside a limit** ("For the 2027 intake, the letter is max. 500 words"). `figures_on_line` offers 2027 only if a unit follows it, and a figure the decision marks `not_a_limit` never becomes a cap. *(Task 6)*
2. **Negated or inverted phrasing:** "no more than 500 words" is a maximum, "not less than 300 words" is a minimum, "there is no word limit" yields no limit. Jev's own documentation names literal reading of negation as a weakness. *(Task 6)*
3. **A provider failure halfway through a page:** the first request answered, the second failed. No partial rule set is written, and the page's previous rules stand. *(Task 3, Task 10)*
4. **A model change behind a warm cache:** a `DecisionRecord` answered by `jev-1.13` must not answer the same question after `TYPESAFE_MODEL` changes. The cache key carries the model. *(Task 3)*
5. **A limit sentence in a language whose unit words are missing** from `letter_terms` (such as Kazakh). No figure is found, so no limit is written, and the sentence is kept as a topic, never dropped in silence. *(Task 6)*

---

## File Structure

| file | responsibility | task |
|---|---|---|
| `config/settings/base.py` | `DECISIONS_BASE_URL`, `OPENROUTER_API_KEY`, `TYPESAFE_MODEL`, thresholds, ceilings | 1 |
| `apps/research/decisions.py` | question types, the client, `ask()`, cache, budget, outage policy | 1–3 |
| `apps/research/models.py` + migrations `0010`, `0011` | `DecisionRecord` and its row-level security and grants | 2 |
| `apps/documents/letter_terms.py` | `figures_on_line`, the single number and unit finder | 4–6 |
| `apps/documents/grammar.py` | `Rule`, operations, `BOUNDS`, `NOTE_BOUNDS`, `sink_for`, `limit_sink` | 4 |
| `apps/documents/grammar_questions.py` | the two requests per sentence set: slots, then typed values | 5–6 |
| `apps/documents/grammar_conflicts.py` | the safer value, with notes | 7 |
| `apps/funding/models.py` + migration `0050` | `ApplicationPrompt.letter_min_chars` | 4 (Part A) |
| `apps/documents/letter_shape.py` | `LetterShape.min_chars`; `apply_derived_shape` writes it and `document_language` | 4, 9 |
| `apps/documents/derive.py` | `derive_page_rules`: the decision layer when configured, the frontier judge otherwise | 8–10 |
| `apps/documents/research_fit/jev.py` | its transport folded into `decisions.ask()` | 13 |

The exact file list per task is in each task's **Files** block, and wins over this table.

---

### Task 0: Land the three fixes the addendum depends on

The frontier judge stays as the fallback, so its fixes matter. The number finder that Task 6 extends is one of them. They exist on `claude/judge-schema-fix` and nowhere on master.

**Files:**
- Modify (by cherry-pick): `apps/documents/derive.py`, `apps/documents/letter_terms.py`, `apps/research/reader.py`
- Test (by cherry-pick): `tests/documents/test_letter_derive.py`, `tests/documents/test_letter_terms.py`, `tests/documents/test_letter_shape.py`, `tests/research/test_reader.py`

**Interfaces:**
- Produces: `letter_terms.numbers_on_line(text: str) -> set[int]` (Task 6 builds `figures_on_line` on it), `LetterVerdict`'s all-required sent schema, and `reader.readable_text` reading a vendor-rendered PDF body as HTML.

- [ ] **Step 1: Bring the three commits onto this branch**

```bash
git -C .worktrees/requirement-reader fetch origin
git -C .worktrees/requirement-reader log --oneline -1 origin/master
git -C .worktrees/requirement-reader cherry-pick fee45437 a9ad5242 2c751714
```

Expected: three new commits. If a pick conflicts, master has changed the same lines. Resolve by keeping master's code and re-applying only the fix the commit message describes, then `git -C .worktrees/requirement-reader cherry-pick --continue`.

- [ ] **Step 2: Run the three fixes' own tests**

Run: `cd .worktrees/requirement-reader && POSTGRES_DB=tehsil_requirement_reader uv run pytest -q tests/documents/test_letter_derive.py tests/documents/test_letter_terms.py tests/documents/test_letter_shape.py tests/research/test_reader.py`
Expected: all pass. They include `test_every_letter_verdict_field_is_sent_as_required`, `test_a_pdf_the_vendor_already_rendered_is_read_as_the_html_it_is`, `test_a_count_written_as_a_word_or_space_grouped_is_on_the_line` and `test_number_verification_stays_strict`.

- [ ] **Step 3: Run the full gate**

Run: `cd .worktrees/requirement-reader && POSTGRES_DB=tehsil_requirement_reader uv run pytest -q && uv run ruff check . && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run`
Expected: all pass, and "No changes detected".

- [ ] **Step 4: Open the fixes' own PR — owner's go-ahead required**

Pushing and opening a PR is outward-facing. Ask the owner first. With a yes:

```bash
git -C .worktrees/judge-schema-fix fetch origin && git -C .worktrees/judge-schema-fix rebase origin/master
git -C .worktrees/judge-schema-fix push -u origin claude/judge-schema-fix
gh pr create --repo 0rkhann/tehsil_agent --head claude/judge-schema-fix --base master \
  --title "fix: three defects the first live letter-rule run found" \
  --body "Anthropic refused the page-rule schema (every read crashed with a key set); every PDF programme page read as empty; limits written as words or '1 000' were dropped. Measured 2026-09-25/26 on real programme pages; each fix pinned by a test that fails without it.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

This branch keeps its cherry-picked copies either way. When the PR merges, the next `git merge origin/master` finds nothing to apply.

### Task 1: The decision layer's vocabulary and its client

Everything in both documents' rule paths consumes these names. Nothing here touches the database
(the test file is marked `django_db` only because Task 3 makes `ask()` read its cache).

**Files:**
- Create: `apps/research/decisions.py`
- Modify: `config/settings/base.py` (replace the `TYPESAFE_API_KEY` block at lines 147-149; add
  `import json` at line 1), `pyproject.toml`
- Test: `tests/research/test_decisions.py`

**Interfaces:**
- Consumes: `django.conf.settings` — `DECISIONS_BASE_URL`, `OPENROUTER_API_KEY`,
  `TYPESAFE_API_KEY`, `TYPESAFE_MODEL`, `DECISIONS_PROVIDER`, `ANTHROPIC_JUDGE_MODEL`,
  `OPENAI_EXTRACTION_MODEL`. The environment variables `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
  are read only on an adapter route.
- Produces: `Noul`, `Choice`, `Question`, `Answer` (adds `served_model: str = ""`),
  `DecisionsUnavailable(message: str, *, kind: Literal["not_configured", "failed", "refused"] =
  "failed", retry_after_seconds: float | None = None)` with `.kind` and `.retry_after_seconds`,
  `DecisionBudgetExhausted`, `DecisionBudget`, `instructions_of(question) -> object`,
  `ask(state, questions, *, decision, language="", budget=None, client=None) -> dict[str, Answer]`,
  `provider_for(decision, language="") -> str`, and the alias
  `Client = Callable[..., dict[str, Answer]]` (Tasks 5, 6, 9, 10 and 12 type their `client`
  seams with it) <!-- reconciled 2026-09-26: Client was defined here but not listed -->

**What a caller does with each `DecisionsUnavailable.kind`** (addendum §5.1). This is the contract
plan 2's reader and plan 4's merge are written against:

| `kind` | when | the caller |
|---|---|---|
| `not_configured` | no key for the routed provider | runs the current frontier judge, so a missing key costs money and correctness is kept |
| `failed` | transport error, timeout, 5xx, 429 after the SDK's own retries, a billing 400/402, a skipped answer | marks the page read `decision_failed`, keeps the page's previous rows, and schedules a `FetchAttempt` retry at `retry_after_seconds` (or `FETCH_RETRY_HOURS` when that is `None`) |
| `refused` | the provider declined this state (OpenRouter moderation 403, an adapter model's refusal) | records it (Task 3 writes the row) and never retries it |

`ask()` itself never falls back. The provider is chosen by `DECISIONS_PROVIDER` and nothing else,
so thresholds stay calibrated (design §9a). The frontier fallback is the caller's, and only on
`not_configured`, never on an outage.

- [ ] **Step 0: Confirm the installed SDKs match the shapes this task was written against**

<!-- amended 2026-09-26: shapes were read from the 0.7.1 / 0.2.1 source; this step now confirms them instead of discovering them -->

Both packages are on public PyPI under the author "TypeSafe AI", published from the vendor's
`typesafe-ai` GitHub org, so they are **confirmed sources** under `engineering.md`'s gate: pin them,
check them for vulnerabilities, no approval round (spec §3.2, verified 2026-09-23). Two namesakes
exist and neither is the vendor's: `typesafe` (2010) and `typesafe-ai`.

```bash
uv add 'typesafe-sdk==0.7.1' 'system-one-adapter[anthropic,openai]==0.2.1'
uv run python -c "
import inspect, json, typesafe_sdk, system_one_adapter
assert typesafe_sdk.__version__ == '0.7.1' and system_one_adapter.__version__ == '0.2.1'
print(inspect.signature(typesafe_sdk.TypeSafeClient.__init__))
print(inspect.signature(typesafe_sdk.TypeSafeClient.system_one))
print(inspect.signature(system_one_adapter.SystemOneAdapterClient.__init__))
print(inspect.signature(system_one_adapter.SystemOneAdapterClient.system_one))
assert issubclass(system_one_adapter.SystemOneResponse, typesafe_sdk.SystemOneResponse)
r = typesafe_sdk.SystemOneResponse.model_validate_json(json.dumps({
    'model': 'typesafe/jev-1.13-20260917', 'usage': {'input_tokens': 42, 'output_tokens': 0},
    'answers': {'d': {'type': 'choice', 'choice': 'cv', 'confidence': 0.9,
                      'probabilities': {'cv': 0.9, 'x': 0.1}},
                'n': {'type': 'noul', 'noul': 0.2}}}))
print(r.model, r.usage.input_tokens, r.choices['d'].choice, r.nouls['n'].noul)
"
```

Expected (checked against the 0.7.1 / 0.2.1 wheels on 2026-09-26):
- `TypeSafeClient.__init__` has keyword-only `api_key`, `model`, `retry`, `timeout`, `headers`,
  `transport`, `http_client`, `base_url`;
- `system_one(self, state, questions, *, model=None, retry=None, ...)`;
- `SystemOneAdapterClient.__init__(self, *, structured_outputs, llm_answer_mode,
  normalize_probabilities=False, n_retry_malformed_structure=0, retry=None, provider=None,
  model=None)`;
- the last line prints `typesafe/jev-1.13-20260917 42 cv 0.2`.

`_to_sdk`, `_from_sdk`, `_typesafe_client` and `_adapter_client` are the **only** functions that
touch these shapes. If the check disagrees, change those four functions and nothing else.

Two SDK facts this module relies on:
- **The SDK retries on its own.** `RetryPolicy()` defaults to 2 retries on 408, 429 and 5xx,
  honours `Retry-After`, and caps each call at 30 s (`_core/retry.py`). That is the design §9a
  back-off. Anything still failing after it is `failed`.
- **The SDK falls back to the environment variables `TYPESAFE_API_KEY` and `TYPESAFE_BASE_URL`
  when an argument is `None`** (`constants.py`). `_typesafe_client` always passes both
  explicitly, so a stray environment variable never picks the route or the key.

- [ ] **Step 1: Write the failing test**

<!-- amended 2026-09-26: django_db mark (Task 3's cache reads the DB), OpenRouter key/base-URL routing, typed failure kinds, served model -->

```python
# tests/research/test_decisions.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/research/test_decisions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.research.decisions'`

- [ ] **Step 3: Write the module**

<!-- amended 2026-09-26: OpenRouter route and key selection, typed failure kinds, 32k ceiling, typed SDK mapping, real adapter API, served model -->

```python
# apps/research/decisions.py
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

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

import system_one_adapter
import typesafe_sdk
from django.conf import settings

logger = logging.getLogger(__name__)

#: TypeSafe's documented Choice ceiling, read 2026-09-22.
MAX_OPTIONS = 255
#: The endpoint's context, not TypeSafe's 64k: OpenRouter lists
#: context_length 32000 for typesafe/jev-1.13 (read 2026-09-26). Checked here so
#: an oversize state is a ValueError at the seam rather than a vendor 400 mid-sweep.
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
    name, key = _decisions_key()
    if not key:
        raise DecisionsUnavailable(f"{name} is not set", kind="not_configured")
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
    if provider not in _ADAPTERS:
        raise DecisionsUnavailable(f"unknown provider {provider!r}", kind="not_configured")
    family, env = _ADAPTERS[provider]
    if not os.environ.get(env):
        raise DecisionsUnavailable(
            f"{env} is not set for DECISIONS_PROVIDER={provider}", kind="not_configured"
        )
    try:
        with system_one_adapter.SystemOneAdapterClient(
            structured_outputs=True,
            llm_answer_mode="probabilities",
            n_retry_malformed_structure=1,
        ) as client:
            response = client.system_one(state, _to_sdk(questions), provider=family, model=model)
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
    reaches the model. No decision reached raises `DecisionsUnavailable`; read
    its `kind`.
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
# config/settings/base.py -- line 1, beside `import os`
import json
```

```python
# config/settings/base.py -- REPLACES lines 147-149 (the TypeSafe comment and TYPESAFE_API_KEY)

# --- The typed-decision layer (typed-decisions design §3.2, §9a; addendum 2026-09-26 §2) ---
#: Where Jev is reached. OpenRouter by default: TypeSafe paused new sign-ups,
#: and an OpenRouter key authenticates its System One route (the SDK appends
#: /v1/systemone). `https://api.typesafe.ai` reaches TypeSafe directly; moving
#: there also changes TYPESAFE_MODEL, whose ids carry no `typesafe/` prefix.
DECISIONS_BASE_URL = os.getenv("DECISIONS_BASE_URL", "https://openrouter.ai/api")
#: The key for any DECISIONS_BASE_URL that is not TypeSafe's own host. Env only,
#: never a default, never logged. Public page sentences only are ever sent with
#: it -- no student data -- which is why this route needs no DPA (design §3.3).
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
#: TypeSafe's own key: sent ONLY when DECISIONS_BASE_URL is api.typesafe.ai. Also
#: the research-fit candidate's key (research_fit.jev) until plan 1 Task 13 folds
#: that client into decisions.ask(); no real student text reaches it before the
#: DPA is filed.
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY", "")
#: The pinned OpenRouter id, never the `~typesafe/jev-latest` alias: thresholds
#: are tuned against a version and moved on our schedule. OpenRouter uses an
#: author-prefixed id as-is and answers with the dated snapshot it served
#: (`typesafe/jev-1.13-20260917`, read 2026-09-26), which DecisionRecord keeps.
TYPESAFE_MODEL = os.getenv("TYPESAFE_MODEL", "typesafe/jev-1.13")
#: Which provider answers which decision. "typesafe" means Jev through
#: DECISIONS_BASE_URL. An adapter entry appears ONLY when §11 gate 9's
#: measurement showed it better on that decision (optionally in one language:
#: "D4:kk-Cyrl"). Never a failover.
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

```toml
# pyproject.toml -- appended to [project] dependencies by `uv add` in Step 0
  "system-one-adapter[anthropic,openai]==0.2.1",
  "typesafe-sdk==0.7.1",
```

The adapter's extras require `anthropic>=0.121.0` and `openai>=2.53.0`. The repo pins
`anthropic<2` and `openai>=3.16.2,<4`, so `uv add` should resolve without moving either. If it
does not, stop and report it; do not loosen a pin.

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/research/test_decisions.py -v`
Expected: 21 passed (the 12 original tests plus 9 new ones: 5 functions, one of them parametrized
four ways).

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run pip-audit`
Expected: all clean. `pip-audit` matters here because two dependencies (and `httpx2`, `tenacity`
transitively) were just added from a source this repo has not used before. Do not run
`ruff format`.

- [ ] **Step 6: Commit**

```bash
uv run git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader add apps/research/decisions.py config/settings/base.py pyproject.toml uv.lock tests/research/test_decisions.py
uv run git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader commit -m "feat: the typed-decision layer -- closed questions, probabilities, one provider

One module owns every question and threshold, which is what makes a threshold
reviewable and a provider swappable. Nothing here generates text: a question is
a Noul or a Choice and an answer is an option plus a distribution, so a steered
page can mislabel a real sentence and never invent one.

Jev is reached through OpenRouter (DECISIONS_BASE_URL, OPENROUTER_API_KEY)
while TypeSafe's sign-ups are paused; TypeSafe's own key goes only to its own
host. The model is pinned as typesafe/jev-1.13 and the served snapshot is kept
on every answer.

The provider is never switched on a failure. No decision reached raises
DecisionsUnavailable with a kind the caller acts on: not_configured (run the
frontier judge), failed (decision_failed, retry via the fetch queue, carrying
the provider's Retry-After), refused (recorded, never retried).

SDK shapes confirmed at Step 0 against typesafe-sdk 0.7.1 and
system-one-adapter 0.2.1.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `DecisionRecord` — every decision is a row

<!-- amended 2026-09-26: migrations 0010/0011 after research tip 0009; catalogue-table recipe (runtime_engine_write, revoke from runtime_web, depends on funding 0049); served_model and refused columns; old Step 0 deleted (fixture already in tests/conftest.py) -->

**Files:**
- Modify: `apps/research/models.py` (append after `SiteJobRecord`)
- Create: `apps/research/migrations/0010_decision_record.py` (generated),
  `apps/research/migrations/0011_decision_record_rls.py` (hand-written)
- Modify: `tests/tenancy/test_database_isolation.py` (`_SHARED_TABLES`)
- Test: `tests/research/test_decision_record_rls.py`; `tests/tenancy/test_catalog_grants.py` (existing, unchanged — it reads the
  catalogue from `pg_policies`, so it covers the new table the moment the policy exists)

**Interfaces:**
- Consumes: nothing from Task 1 (the model stands alone; Task 3 joins them)
- Produces: `research.DecisionRecord` with `state_digest`, `question_digest`, `decision`,
  `question_id`, `value`, `confidence`, `probabilities`, `model`, `served_model`, `provider`,
  `language`, `input_tokens`, `refused`, `created_at`

**Is it catalogue data? Yes, by the plan's own reasoning.** No student data is ever in a state
(spec §9a). Which sentence a programme's page states, and how Jev labelled it, is the same fact for
every agency. The table is the cache that lets a faculty page linked by thirty programmes be
decided once. It therefore follows CLAUDE.md's recipe for a new catalogue table (2026-09-25):
- `shared_catalog_select` for reads;
- `runtime_engine_write` as its only writer;
- `REVOKE ALL ... FROM runtime_web` in the same migration;
- `tests/tenancy/test_catalog_grants.py` fails until the revoke lands.

A UUID primary key owns no sequence, so there is no sequence to revoke.

- [ ] **Step 0: Re-read the migration tip**

Run: `ls /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader/apps/research/migrations/`
Expected: the newest is `0009_site_job_record_rls.py`, so this task writes `0010` and `0011`. If
the tip has moved, take the next free pair. Repoint `0011`'s `research` dependency at the real
`0010`, and keep its `("funding", "0049_catalog_grants")` edge. A dependency naming a node that no
longer exists is the collision CLAUDE.md records from 2026-09-15.

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_decision_record_rls.py
"""RLS and grants on DecisionRecord, verified through roles that cannot bypass them.

CLAUDE.md: the test role is a superuser and bypasses grants and RLS alike, so a
test that uses it proves nothing. The read goes through `runtime_connection` (a
NOBYPASSRLS login with SELECT everywhere). The write goes through
`role_connection`, as a member of `runtime_engine` (allowed by
`runtime_engine_write`) and of `runtime_web` (refused by the missing table
grant) -- `runtime_connection` is a member of neither, so a refusal there
would prove nothing about who may write.
"""
from uuid import uuid4

import psycopg
import pytest

from apps.research.models import DecisionRecord

pytestmark = pytest.mark.django_db

_FIELDS = dict(
    state_digest="a" * 64, question_digest="b" * 64, decision="D6",
    question_id="document", value="cv", confidence=0.97,
    probabilities={"cv": 0.97, "motivation_letter": 0.03},
    model="typesafe/jev-1.13", served_model="typesafe/jev-1.13-20260917",
    provider="typesafe", language="en", input_tokens=120,
)

_INSERT = (
    "INSERT INTO research_decisionrecord "
    "(id, state_digest, question_digest, decision, question_id, value, confidence, "
    " probabilities, model, served_model, provider, language, input_tokens, refused, "
    " created_at) "
    "VALUES (gen_random_uuid(), repeat('a', 64), repeat('b', 64), 'D6', 'q', 'cv', 0.9, "
    "'{}', 'typesafe/jev-1.13', '', 'typesafe', 'en', 1, false, now())"
)


@pytest.mark.django_db(transaction=True)
def test_a_record_is_readable_by_every_tenant(runtime_connection):
    """`transaction=True`: `runtime_connection` is a second, real connection, so
    the row must be committed on Django's connection before it can see it."""
    DecisionRecord.objects.create(**_FIELDS)
    with runtime_connection.cursor() as cursor:
        for _ in range(2):
            cursor.execute("SELECT set_config('app.tenant_id', %s, false)", [str(uuid4())])
            cursor.execute("SELECT count(*) FROM research_decisionrecord")
            assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
def test_only_the_engine_can_write_one_and_the_web_cannot_even_read(role_connection):
    """The engine's INSERT succeeding shows the web refusal is about the ROLE,
    not a malformed row. The web refusal is the table grant (`permission denied
    for table`), never a policy returning zero rows -- CLAUDE.md: the catalogue
    boundary is a GRANT. `transaction=True` because these connections
    autocommit; the flush after the test removes the row."""
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_INSERT)
        assert cursor.rowcount == 1

    with role_connection("runtime_web") as conn:
        for statement in (_INSERT, "SELECT 1 FROM research_decisionrecord LIMIT 1"):
            with conn.cursor() as cursor:
                with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
                    cursor.execute(statement)
                assert "permission denied for table research_decisionrecord" in str(
                    refused.value
                )


def test_the_digest_pair_is_unique_per_model():
    """The row is the cache (spec §9a): the same state and question set under the
    same model answer once. Two rows would make the cache a coin flip."""
    DecisionRecord.objects.create(**_FIELDS)
    with pytest.raises(Exception, match="unique|duplicate"):
        DecisionRecord.objects.create(**_FIELDS)


def test_it_is_in_the_shared_tables_list():
    """A shared-catalog table absent from this list is one the isolation test
    never checks -- which is how a table ends up with no policy at all."""
    from tests.tenancy.test_database_isolation import _SHARED_TABLES

    assert "research_decisionrecord" in _SHARED_TABLES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/research/test_decision_record_rls.py -v`
Expected: FAIL with `ImportError: cannot import name 'DecisionRecord'`

- [ ] **Step 3: Write the model and the table migration**

```python
# apps/research/models.py -- append

class DecisionRecord(models.Model):
    """One answer from the decision layer, with everything needed to re-judge it.

    Three jobs, and the third is why it is a table rather than a log line:

    1. **The calibration audit** (spec §11.4) reads confidence against outcome
       monthly. Drift or a steered page shows up as a calibration break, which
       is measurable, rather than as a wrong CV, which is not. It reads
       `refused=False` rows only.
    2. **`rederive_rules`** (spec §6.5) re-asks the slot questions over stored
       sentences when the grammar grows, without refetching a page.
    3. **The cache.** The same `(state_digest, question_digest, model)` is
       answered from here. A faculty-wide requirements page linked by thirty
       programmes is decided once, not thirty times -- and a state the provider
       refused is refused from here, never asked again (addendum §5.1).

    Shared catalog: no student data is ever in a state (spec §9a), and which
    sentence a page states is the same fact for every agency. Written and read
    by `runtime_engine` only; `runtime_web` holds no grant (0011).
    """

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    #: sha256 of the canonical JSON of the state the question was asked against.
    state_digest = models.CharField(max_length=64)
    #: sha256 of the canonical JSON of the WHOLE question map, so a reworded
    #: question never reads a stale answer out of the cache.
    question_digest = models.CharField(max_length=64)
    decision = models.CharField(max_length=40)
    question_id = models.CharField(max_length=120)
    #: The chosen option, or "true"/"false" for a Noul; "" on a refusal. Always a
    #: string so one column holds both and a query never has to know which.
    value = models.CharField(max_length=200)
    confidence = models.FloatField()
    probabilities = models.JSONField(default=dict)
    #: The id we pinned and asked for -- the cache key (`typesafe/jev-1.13`).
    model = models.CharField(max_length=60)
    #: The snapshot the provider says answered (`typesafe/jev-1.13-20260917`).
    #: The pin can move under an alias-like id; this is where it shows.
    served_model = models.CharField(max_length=80, blank=True, default="")
    provider = models.CharField(max_length=30)
    language = models.CharField(max_length=12, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    #: The provider declined this state. Kept so it is never asked again under
    #: this model and question set; excluded from calibration.
    refused = models.BooleanField(default=False)
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

Generate the table migration:

```bash
POSTGRES_DB=tehsil_requirement_reader uv run python manage.py makemigrations research --name decision_record
```

Expected: `apps/research/migrations/0010_decision_record.py`, depending on
`("research", "0009_site_job_record_rls")`.

- [ ] **Step 4: Write the policy migration without the revoke, and watch the guard fail**

```python
# apps/research/migrations/0011_decision_record_rls.py  (first draft -- Step 5 adds one line)
from django.db import migrations

TABLE = "research_decisionrecord"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{TABLE}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0010_decision_record"),
        ("funding", "0049_catalog_grants"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
```

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/tenancy/test_catalog_grants.py::test_every_catalogue_table_is_revoked_from_web_and_granted_to_engine -v`
Expected: FAIL with `AssertionError: ('research_decisionrecord', 'SELECT')`. The default privileges
from `funding/0049` granted the new table to `runtime_web`, which is exactly what the guard exists
to catch.

- [ ] **Step 5: Add the revoke, and the table to the isolation list**

```python
# apps/research/migrations/0011_decision_record_rls.py -- final
# research_decisionrecord joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: no student
# data is ever in a decision state, and which sentence a page states is the
# same fact for every tenant.
#
# CLAUDE.md's recipe for a new catalogue table (2026-09-25): the shared read
# policy, a write policy for runtime_engine -- never catalog_ingestion, which
# funding/0049 dropped -- and REVOKE from runtime_web in the same migration,
# because 0049's default privileges grant every new table to both runtime roles.
# The boundary is the GRANT: an absent grant fails closed with `permission
# denied`, where a policy returning zero rows looks like an empty table.
#
# Depends on funding/0049 because that is what creates runtime_engine and
# runtime_web on a superuser-migrated database; without the edge this policy
# could be created before its role exists.
#
# ENABLE without FORCE, matching every shared catalog table
# (test_task7_rls_policy_shapes_and_runtime_acl asserts (True, False)). FORCE
# is for TENANT tables, where CLAUDE.md's failure mode 3 applies; a table
# whose read policy is USING (true) has nothing to force.
#
# UUID primary key: no sequence to revoke.
from django.db import migrations

TABLE = "research_decisionrecord"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{TABLE}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
REVOKE ALL ON public.{TABLE} FROM runtime_web;
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0010_decision_record"),
        ("funding", "0049_catalog_grants"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
```

The reverse does not re-grant `runtime_web`. Reversing `0011` alone leaves the table with no web
grant, which is the safe side, and reversing `0010` drops the table anyway.

```python
# tests/tenancy/test_database_isolation.py -- append inside _SHARED_TABLES, after "research_sitejobrecord"
    # The decision layer's answers and cache (research/0010, 0011). A label on a
    # public page's sentence is the same fact for every tenant; no state ever
    # carries student data.
    "research_decisionrecord",
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/research/test_decision_record_rls.py tests/tenancy/test_database_isolation.py tests/tenancy/test_catalog_grants.py -v`
Expected: all pass. That includes:
- `test_task7_rls_policy_shapes_and_runtime_acl`, which now sees exactly
  `runtime_engine_write`/`ALL` and `shared_catalog_select`/`SELECT` on the new table;
- `test_the_catalogue_writer_is_the_engine_and_nothing_names_catalog_ingestion`;
- `test_an_agency_connection_cannot_read_the_catalogue`.

- [ ] **Step 7: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run python manage.py makemigrations --check --dry-run`
Expected: all clean, "No changes detected"

- [ ] **Step 8: Commit**

```bash
uv run git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader add apps/research/models.py apps/research/migrations/0010_decision_record.py apps/research/migrations/0011_decision_record_rls.py tests/research/test_decision_record_rls.py tests/tenancy/test_database_isolation.py
uv run git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader commit -m "feat: DecisionRecord -- the calibration input, the re-derivation input, and the cache

Shared catalog, because no student data is ever in a state and which sentence a
page states is the same fact for every agency. Built by the 2026-09-25 recipe:
shared_catalog_select, runtime_engine_write as the only writer, and REVOKE from
runtime_web in the same migration -- test_catalog_grants failed on this table
until the revoke landed. 0011 depends on funding/0049, which creates the roles.

The unique key is the cache key: one state, one question map, one pinned model,
one answer. served_model keeps the snapshot that actually answered; refused keeps
a declined state from being asked again. Verified through runtime_connection and
role_connection, since the test role bypasses RLS and grants.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The cache, the monthly ceiling, and the outage policy

**Files:**
- Modify: `apps/research/decisions.py`
- Test: `tests/research/test_decisions_cache.py`

**Interfaces:**
- Consumes: `models.DecisionRecord`, `Answer`, `ask`, `DecisionsUnavailable`
- Produces: `ask(..., record=True)` writing rows and reading them back, including refusals (a
  cached refusal raises `DecisionsUnavailable(kind="refused")` with no request);
  `month_tokens_spent() -> int`; `run_budget() -> DecisionBudget`

What the outage policy is, end to end, after this task:
- a 429/5xx is retried by the SDK, then raised as `failed` with the provider's wait. It writes no
  row, so the next read asks again.
- a refusal writes `refused=True` rows and is answered from them from then on, until the model
  pin or the question wording changes.
- with no key, a state already in the cache is still answered from the cache. Only an uncached
  state raises `not_configured`, and there the caller falls back to the frontier judge.

<!-- amended 2026-09-26: served_model in the record, refusals recorded and served from cache, a cached answer needs no key, model id typesafe/jev-1.13 -->

- [ ] **Step 1: Write the failing test**

```python
# tests/research/test_decisions_cache.py
import pytest

from apps.research.decisions import (
    Answer,
    Choice,
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


def test_the_month_ceiling_is_read_from_the_rows(settings):
    for _ in range(3):
        DecisionRecord.objects.create(
            state_digest=f"{_}" * 64, question_digest="b" * 64, decision="D6",
            question_id="q", value="cv", confidence=0.9, probabilities={},
            model="typesafe/jev-1.13", provider="typesafe", input_tokens=1_000,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/research/test_decisions_cache.py -v`
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
                    model=answer.model, served_model=answer.served_model,
                    provider=answer.provider, language=language,
                    input_tokens=answer.input_tokens,
                )
                for answer in answers.values()
            ],
            ignore_conflicts=True,
        )
    except IntegrityError:  # pragma: no cover - ignore_conflicts covers the race
        logger.warning("a decision record collided and was not written")


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
            for qid in questions
        ],
        ignore_conflicts=True,
    )
```

Then replace `ask()` in full. The cache read goes before the budget and the provider call, the
write after:

```python
# apps/research/decisions.py -- ask(), replacing Task 1's

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

    No decision reached raises `DecisionsUnavailable`; read its `kind`. The
    cache is read before the key is needed, so a state already decided keeps
    serving when no key is configured.
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

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/research/test_decisions.py tests/research/test_decisions_cache.py tests/research/test_decision_record_rls.py -v`
Expected: all pass: 21 + 12 + 4. Task 1's file now reads and writes the cache, which its
`pytestmark` allows.

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean; the full suite passes.

- [ ] **Step 6: Commit**

```bash
uv run git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader add apps/research/decisions.py tests/research/test_decisions_cache.py
uv run git -C /home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader commit -m "feat: the decision cache, the monthly ceiling and the outage policy

The cache key is the state, the whole question map and the pinned model, so a
reworded question or a new pin misses -- reading a stale answer would report a
measurement nobody made. A partial hit is a miss, because half a decision from
each of two model runs is neither. The served snapshot is recorded beside it.

A failure raises and is never cached, so the caller marks the read
decision_failed and the retry asks again. A refusal is recorded and served from
the record, so it is never asked again under the same pin. The cache is read
before the key is needed: with no key, what is already decided keeps serving and
only an uncached state raises not_configured for the caller's frontier fallback.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---


### Task 4: The grammar's vocabulary, and the sink every operation projects onto

Two parts, two commits. Part A gives a character floor a sink that is enforced; Part B is the
vocabulary, whose tests pin every sink against the real field and key lists, `min_chars`
included.

**Files:**
- Part A — Modify: `apps/funding/models.py` (`ApplicationPrompt`), `apps/documents/constraints.py`,
  `apps/documents/letter_shape.py`, `apps/documents/letter_render.py`, `apps/documents/letters.py`
- Part A — Create: `apps/funding/migrations/0050_applicationprompt_letter_min_chars.py`
- Part A — Test: `tests/documents/test_letter_min_chars.py`
- Part B — Create: `apps/documents/grammar.py`
- Part B — Modify: `apps/documents/derive.py` (the two plausibility constants move out)
- Part B — Test: `tests/documents/test_grammar_types.py`

**Interfaces:**
- Consumes: `apps.documents.constraints._INCLUDE_TARGETS`, `_SECTIONS`, `_ORDER_TARGETS`,
  `_CONSTRAINT_KEYS`; `letter_shape.LetterShape`
- Produces (Part A): `ApplicationPrompt.letter_min_chars: PositiveIntegerField(null=True)`,
  `LetterShape.min_chars: int | None = None`, constraint key `"min_chars_excl_spaces"`
- Produces (Part B): `DOCUMENTS`, `OPERATIONS` (with `form`, `naming`), `Operation`,
  `STYLE_VALUES`, `CONDITION_KINDS`, `UNITS`, `FORMAT_VERDICTS`, `BOUNDS`, `NOTE_BOUNDS`,
  `FORM_VALUES`, `NAMING_VALUES`, `_IMPLAUSIBLE_CAP`, `_IMPLAUSIBLE_MAX`, `Slotted`,
  `Rule` (with `bound: str = ""`, `figure: int | None = None`, `excl_spaces: bool = False`),
  `SINKS`, `sink_for(document, operation, value) -> str`,
  `limit_sink(document, bound, unit, *, excl_spaces=False) -> str`
  <!-- reconciled 2026-09-26: NOTE_BOUNDS, FORM_VALUES, NAMING_VALUES, excl_spaces; LIMIT_KINDS removed -->

Spec §6.1, addendum §6.1–§6.3. **The grammar is a projection onto sinks that already exist.** An
operation whose value cannot name a real sink does not enter the grammar; that is what keeps
"applied" meaning "a checker or renderer that exists ran it".

<!-- amended 2026-09-26: addendum §6.2 -- a floor keeps a sink; min_chars is added, and
enforced, because a source for a bound nothing enforces is the defect derive.py:1211 names -->

#### Part A — the `min_chars` sink

**Measured without spaces, whatever the page says.** A floor read that way is always the stricter
one — a letter with N non-space characters has at least N with them — so the letter never needs
to know the page's convention, and no second column is added. Kassel rejects a letter under 2,800
characters (addendum §6.2); a floor below which the application is rejected is a binding fact.

- [ ] **Step 0: Re-read the migration tip**

Run: `ls apps/funding/migrations/ | tail -3`
Expected: `0049_catalog_grants.py` is the last numbered file. If a later one exists, take the next
free number and point `dependencies` at the real leaf (Global Constraints, "Migration numbers").
Plan 2's funding migration then takes the number after this one (addendum §9 said "0050 or
later"; this is what takes 0050).

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_letter_min_chars.py
import pytest

from apps.documents.constraints import Enforcement
from apps.documents.letter_defaults import defaults_for
from apps.documents.letter_render import _check_letter_constraint
from apps.documents.letter_shape import (
    LetterShape,
    NotGeneratable,
    apply_derived_shape,
    constraints_from_shape,
    shape_from_prompt,
    target_word_count,
    validate_shape_bounds,
)
from apps.documents.letters import _shape_instructions

from .conftest import make_program

_URL = "https://x.example/p"


def _row():
    return defaults_for(
        country_code="GB", track="taught", portfolio_led=False,
        funder_kind="UNIVERSITY_ADMISSION",
    )


@pytest.mark.django_db
def test_a_character_floor_lands_on_the_prompt_and_round_trips():
    program = make_program(country_code="DE")
    shape = LetterShape(
        min_chars=2800,
        sources={"min_chars": {"text": "mindestens 2.800 Zeichen", "source_url": _URL}},
    )
    prompt = apply_derived_shape(program, "2027", shape, source_url=_URL)
    assert prompt.letter_min_chars == 2800
    assert shape_from_prompt(prompt) == shape


def test_a_character_floor_is_a_binding_rule_measured_without_spaces():
    (rule,) = constraints_from_shape(LetterShape(min_chars=2800))
    assert (rule.key, rule.value, rule.enforcement) == (
        "min_chars_excl_spaces", 2800, Enforcement.BINDING,
    )


def test_the_floor_blocks_a_letter_short_of_it_and_never_counts_spaces():
    """2,800 characters WITH spaces is 2,100 without: under the floor. Counting
    spaces here would pass a letter the page rejects."""
    (rule,) = constraints_from_shape(LetterShape(min_chars=2800))
    assert _check_letter_constraint(rule, text="abc " * 700) is not None
    assert _check_letter_constraint(rule, text="abcd " * 700) is None


def test_a_floor_above_the_cap_is_refused_before_any_model_call():
    with pytest.raises(NotGeneratable, match="characters"):
        validate_shape_bounds(LetterShape(min_chars=3000, max_chars=2000))


def test_the_word_target_carries_enough_characters_for_the_floor():
    """A target the floor then blocks is a model call paid for and thrown away --
    the defect letter_shape.py's clamps exist to prevent. 4.76 is this engine's
    measured non-space characters per word."""
    assert target_word_count(LetterShape(min_chars=2800), _row()) * 4.76 >= 2800


def test_the_writer_is_told_the_floor():
    text = _shape_instructions(LetterShape(min_chars=2800), _row())
    assert "at least 2800 characters, not counting spaces" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_letter_min_chars.py -v`
Expected: FAIL — `TypeError: LetterShape.__init__() got an unexpected keyword argument 'min_chars'`

- [ ] **Step 3: The column and its migration**

```python
# apps/funding/models.py -- ApplicationPrompt, directly after letter_min_words
    #: A character floor, always measured WITHOUT spaces: the stricter reading
    #: whatever the page's own convention, so a letter clearing it clears the
    #: page's (addendum 2026-09-26 §6.2 -- Kassel rejects a letter under 2,800).
    letter_min_chars = models.PositiveIntegerField(null=True, blank=True)
```

Run: `uv run python manage.py makemigrations funding --name applicationprompt_letter_min_chars`
Expected: `apps/funding/migrations/0050_applicationprompt_letter_min_chars.py`, equivalent to (quote style and the generated header may differ):

```python
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("funding", "0049_catalog_grants"),
    ]

    operations = [
        migrations.AddField(
            model_name="applicationprompt",
            name="letter_min_chars",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
```

A column on an existing catalogue table needs no grant or policy: `0049_catalog_grants` grants
per table, and RLS policies are per row.

- [ ] **Step 4: The key, the shape field, the check, the refusal, the aim, the sentence**

```python
# apps/documents/constraints.py -- in _CONSTRAINT_KEYS, directly after "min_words"
    #: The letter's character floor, measured without spaces (letter_shape
    #: _SHAPE_TO_KEY): the stricter reading of any page's floor.
    "min_chars_excl_spaces",
```

```python
# apps/documents/letter_shape.py -- imports
import logging
import math
from dataclasses import dataclass, field, replace
from decimal import Decimal
```

```python
# apps/documents/letter_shape.py -- LetterShape, directly after max_chars
    #: Measured without spaces (see _SHAPE_TO_KEY). Addendum 2026-09-26 §6.2.
    min_chars: int | None = None
```

```python
# apps/documents/letter_shape.py -- apply_derived_shape's `fields`, after letter_max_chars
        "letter_min_chars": shape.min_chars,
```

```python
# apps/documents/letter_shape.py -- shape_from_prompt, after max_chars=
        min_chars=prompt.letter_min_chars,
```

```python
# apps/documents/letter_shape.py -- validate_shape_bounds, after the min_words > max_words check
    if shape.min_chars and shape.max_chars and shape.min_chars > shape.max_chars:
        # min_chars is counted without spaces and max_chars with them, so a
        # floor above the cap is unsatisfiable outright -- never merely tight.
        raise NotGeneratable(
            f"letter shape unsatisfiable: floor of {shape.min_chars} characters exceeds "
            f"cap of {shape.max_chars} characters"
        )
```

```python
# apps/documents/letter_shape.py -- beside _TYPICAL_CHARS_PER_WORD
#: Non-space characters in one word of this engine's own prose: 5.759 measured
#: with the space (2026-09-22, above), so 4.76 without it. Used only to AIM at a
#: character floor; the word count is rounded UP, and the floor's own 15% of
#: headroom in target_word_count sits on top.
_NONSPACE_CHARS_PER_WORD = 4.76
```

```python
# apps/documents/letter_shape.py -- first lines of target_word_count's body
    if shape.min_chars and not counts_characters(document_language):
        # A character floor is aimed at as the word floor it implies, so every
        # branch and clamp below respects it exactly as it respects min_words.
        # Without this a page stating only "at least 2,800 characters" got the
        # row's own 450 words (about 2,140 non-space characters) and was blocked
        # after the model call.
        implied = math.ceil(shape.min_chars / _NONSPACE_CHARS_PER_WORD)
        shape = replace(shape, min_words=max(shape.min_words or 0, implied))
```

```python
# apps/documents/letter_shape.py -- _SHAPE_TO_KEY, after "max_chars"
    #: The floor is measured WITHOUT spaces: the stricter reading of any page,
    #: so the page's own convention never needs to be known.
    "min_chars": "min_chars_excl_spaces",
```

```python
# apps/documents/letter_render.py -- _TEXT_CONSTRAINT_KEYS
_TEXT_CONSTRAINT_KEYS = frozenset(
    {"max_words", "min_words", "max_chars_incl_spaces", "max_chars_excl_spaces",
     "min_chars_excl_spaces"}
)
```

```python
# apps/documents/letter_render.py -- _check_letter_constraint, after the max_chars_excl_spaces branch
    if rule.key == "min_chars_excl_spaces":
        stripped_len = len(text.replace(" ", ""))
        if stripped_len < int(cast(int, rule.value)):
            return LetterConstraintViolation(
                rule, f"{stripped_len} characters below floor {rule.value}"
            )
```

```python
# apps/documents/letters.py -- _shape_instructions, directly after the max_chars sentence
    if shape.min_chars:
        # Said the way it is measured (letter_shape._SHAPE_TO_KEY).
        parts.append(f" It must be at least {shape.min_chars} characters, not counting spaces.")
```

Known ceilings, named rather than built: a character-counting script (zh/ja/ko) with a floor and
no cap still gets a word target (`_shape_instructions`' existing branch), and a floor within 15% of
a cap in those scripts is aimed at 85% of the cap. Neither has appeared on a measured page.

- [ ] **Step 5: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_letter_min_chars.py tests/documents/test_letter_shape.py tests/documents/test_letters.py tests/documents/test_letter_formal_render.py -v`
Expected: `test_letter_min_chars.py` 6 passed; the three existing files pass unchanged.

- [ ] **Step 6: Run the checks and commit**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean, no missing migration, full suite green.

```bash
git -C "$WT" add apps/funding/models.py apps/funding/migrations/0050_applicationprompt_letter_min_chars.py \
  apps/documents/constraints.py apps/documents/letter_shape.py apps/documents/letter_render.py \
  apps/documents/letters.py tests/documents/test_letter_min_chars.py
uv run git -C "$WT" commit -m "feat: a character floor has a column, a check and a target

Kassel rejects a letter under 2,800 characters, and until now a page's
character floor was dropped because no column carried it -- deliberately,
since a source written for a bound nothing enforces shows the student an
unenforced rule as enforced. So the column comes with the rest: a BINDING
constraint key, the letter check, the floor-above-cap refusal, a word target
that carries enough characters, and the writer's sentence.

The floor is measured without spaces whatever the page says: that reading is
always the stricter one, so the page's convention never needs to be known.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

#### Part B — the vocabulary

- [ ] **Step 7: Write the failing test**

<!-- amended 2026-09-26: ("style", "signed") was never a style value, so the original
letter-sink test failed as written; limit_sink, BOUNDS, LIMIT_KINDS and Rule.bound/figure
are addendum §6.1 -->
<!-- reconciled 2026-09-26: LIMIT_KINDS is gone (NOTE_BOUNDS replaces it); Rule.excl_spaces,
FORM_VALUES and NAMING_VALUES are added -->

```python
# tests/documents/test_grammar_types.py
import pytest

from apps.documents.constraints import _CONSTRAINT_KEYS, _INCLUDE_TARGETS, _SECTIONS
# <!-- reconciled 2026-09-26 -->
from apps.documents.grammar import (
    BOUNDS,
    CONDITION_KINDS,
    DOCUMENTS,
    FORM_VALUES,
    FORMAT_VERDICTS,
    NAMING_VALUES,
    NOTE_BOUNDS,
    OPERATIONS,
    STYLE_VALUES,
    UNITS,
    Rule,
    limit_sink,
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
    for bound in BOUNDS:
        for unit in (*UNITS, "other"):
            for excluded in (False, True):
                sink = limit_sink("cv", bound, unit, excl_spaces=excluded)
                assert sink in keys | {""}, (bound, unit, excluded, sink)


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
    # <!-- reconciled 2026-09-26: form and naming are LetterShape fields already -->
    for operation, value in (("limit", 800), ("style", "signed_declaration"),
                             ("topic", "why this programme"),
                             ("student_action", "sign it by hand"),
                             ("form", "formal_letter"), ("naming", "forbidden")):
        sink = sink_for("motivation_letter", operation, value)
        assert sink in names, (operation, value, sink)
    for bound in BOUNDS:
        for unit in (*UNITS, "other"):
            sink = limit_sink("motivation_letter", bound, unit)
            assert sink in names | {""}, (bound, unit, sink)


def test_a_reference_letter_rule_never_binds_the_applicants_documents():
    """A reference letter is the referee's. For the applicant it is an action --
    obtain it -- and nothing else (spec §6.1)."""
    assert sink_for("reference_letter", "limit", 2) == "student_actions"
    assert sink_for("reference_letter", "format", "europass_required") == "student_actions"
    assert limit_sink("reference_letter", "maximum", "pages") == "student_actions"


@pytest.mark.parametrize(
    ("document", "bound", "unit", "sink"),
    [
        ("motivation_letter", "maximum", "words", "max_words"),
        # "approximately one A4 page" is read as a cap, as decide_letter_shape reads it.
        ("motivation_letter", "approximate", "pages", "max_pages"),
        ("motivation_letter", "maximum", "characters", "max_chars"),
        ("motivation_letter", "minimum", "words", "min_words"),
        ("motivation_letter", "minimum", "characters", "min_chars"),
        # No column holds a page floor and nothing measures one.
        ("motivation_letter", "minimum", "pages", ""),
        ("cv", "maximum", "pages", "max_pages"),
        ("cv", "maximum", "characters", "max_chars_incl_spaces"),
        # No CV checker measures a floor: a CV floor is `unapplied`, shown and counted.
        ("cv", "minimum", "pages", ""),
        ("cv", "not_a_limit", "pages", ""),
        # <!-- reconciled 2026-09-26 --> A note bound is a topic, never a length.
        ("motivation_letter", "section_limit", "words", ""),
        ("motivation_letter", "another_statement", "words", ""),
        ("cv", "maximum", "other", ""),
        ("reference_letter", "minimum", "words", "student_actions"),
    ],
)
def test_a_figure_lands_on_the_sink_its_bound_and_unit_name(document, bound, unit, sink):
    assert limit_sink(document, bound, unit) == sink


def test_a_cv_character_cap_without_spaces_has_its_own_key():
    assert limit_sink("cv", "maximum", "characters", excl_spaces=True) == "max_chars_excl_spaces"
    # The letter has one character cap, measured WITH spaces: a cap read that way
    # is the stricter one, so the letter never needs the page's convention.
    assert limit_sink("motivation_letter", "maximum", "characters", excl_spaces=True) == "max_chars"


# <!-- reconciled 2026-09-26: addendum §6.3 -- form and naming are operations -->
def test_the_operations_are_the_closed_list_the_spec_names():
    assert set(OPERATIONS) == {
        "limit", "language", "format", "include", "order", "emphasise", "style",
        "topic", "student_action", "form", "naming", "other",
    }


def test_form_and_naming_land_on_the_letters_own_fields_and_never_the_cv():
    """The frontier path types both (derive.LetterVerdict); the grammar may not
    lose them (addendum §6.3). A value outside the closed list has no sink."""
    assert set(FORM_VALUES) == {"essay", "formal_letter", "portal_form"}
    assert set(NAMING_VALUES) == {"required", "invited", "forbidden"}
    for value in FORM_VALUES:
        assert sink_for("motivation_letter", "form", value) == "form"
        assert sink_for("cv", "form", value) == ""
    for value in NAMING_VALUES:
        assert sink_for("motivation_letter", "naming", value) == "naming"
        assert sink_for("cv", "naming", value) == ""
    assert sink_for("motivation_letter", "form", "none") == ""
    assert sink_for("motivation_letter", "naming", "none") == ""


def test_the_documents_are_the_closed_list_the_spec_names():
    assert set(DOCUMENTS) == {"cv", "motivation_letter", "reference_letter", "other"}


# <!-- reconciled 2026-09-26: tolerance is not a bound; it is a topic sentence -->
def test_the_bounds_are_the_closed_list_the_addendum_names():
    assert BOUNDS == (
        "maximum", "minimum", "approximate", "section_limit", "another_statement", "not_a_limit",
    )
    assert NOTE_BOUNDS == frozenset({"section_limit", "another_statement"})
    assert "tolerance" not in BOUNDS


def test_a_rule_records_the_sentence_and_the_confidence_that_produced_it():
    rule = Rule(index=3, document="cv", operation="limit", value=2, unit="pages",
                confidence=0.93, sentence="Your CV may not exceed two pages.",
                heading="Application documents")
    assert rule.applied is True
    assert rule.note == ""


def test_a_rule_carries_its_bound_and_which_figure_it_was():
    """One sentence may state several figures -- '300-500 words' is a floor and
    a cap -- so a rule says which figure it is and which way it binds."""
    rule = Rule(index=2, document="motivation_letter", operation="limit", value=300,
                unit="words", bound="minimum", figure=0, confidence=0.93,
                sentence="The letter should be 300–500 words.")
    assert (rule.bound, rule.figure, rule.applied) == ("minimum", 0, True)
    # <!-- reconciled 2026-09-26 --> A rule no figure produced says so, and spaces
    # are a boolean the per-figure Noul answered -- never a string in `detail`.
    plain = Rule(index=0, document="cv", operation="style", value="photo_forbidden",
                 sentence="No photo.")
    assert (plain.figure, plain.excl_spaces, plain.detail) == (None, False, "")
    counted = Rule(index=1, document="cv", operation="limit", value=4000, unit="characters",
                   bound="maximum", figure=0, excl_spaces=True,
                   sentence="At most 4,000 characters without spaces.")
    assert limit_sink("cv", counted.bound, counted.unit,
                      excl_spaces=counted.excl_spaces) == "max_chars_excl_spaces"


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


def test_the_plausibility_bands_moved_rather_than_forked():
    """The letter judge and the grammar read one definition, so a band tuned
    for one can never silently diverge from the other."""
    from apps.documents import derive, grammar

    assert derive._IMPLAUSIBLE_CAP is grammar._IMPLAUSIBLE_CAP
    assert derive._IMPLAUSIBLE_MAX is grammar._IMPLAUSIBLE_MAX
```

- [ ] **Step 8: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.grammar'`

- [ ] **Step 9: Write the vocabulary**

```python
# apps/documents/grammar.py
"""The rule grammar: four slots, closed lists, one free topic.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md §6,
amended by 2026-09-26-requirement-reader-addendum-design.md §6.

A requirement sentence is never read as a sentence. It is taken apart into
`document`, `operation`, `value` and `scope`, each a closed question with a
probability, and a rule exists only when every slot fills at its bar.

**Every operation projects onto a sink that already exists** -- a constraint key
the renderer checks, a directive the generator reads, a LetterShape field the
letter engine uses. An operation whose value names no sink is `unapplied`: kept
verbatim, shown on the document, counted (§6.5), and never improvised into the
writing prompt. That is the one door this design keeps shut.

Nothing here calls a model. `grammar_questions` and `grammar_values` ask; this
module defines what may be asked and where each answer goes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from .constraints import _CONSTRAINT_KEYS, _INCLUDE_TARGETS, _ORDER_TARGETS, _SECTIONS

Document = Literal["cv", "motivation_letter", "reference_letter", "other"]
# <!-- reconciled 2026-09-26: addendum §6.3 -- form and naming, so nothing the
# frontier path types is lost -->
Operation = Literal[
    "limit", "language", "format", "include", "order", "emphasise", "style",
    "topic", "student_action", "form", "naming", "other",
]

DOCUMENTS: tuple[str, ...] = get_args(Document)
OPERATIONS: tuple[str, ...] = get_args(Operation)

#: The units a length may be stated in. `pages` is a CV and letter unit;
#: `words` and `characters` are the letter's (ApplicationPrompt.letter_max_words,
#: letter_max_chars) and the CV's max_words / max_chars_incl_spaces.
UNITS: tuple[str, ...] = ("pages", "words", "characters")

# <!-- amended 2026-09-26: addendum §6.1 -- every figure is its own decision -->
# <!-- reconciled 2026-09-26: the note bounds replace the sentence-level LIMIT_KINDS -->
#: What one figure in a length sentence IS (addendum §6.1). `approximate` is
#: read as a cap, as decide_letter_shape has always read it: "about one page"
#: is never a floor, and a letter written to the approximation is inside it.
#: `section_limit` (one part of the document, "three parts of 400 words each")
#: and `another_statement` (a different statement in the same application) are
#: lengths, but of something the engine does not write as one document.
BOUNDS: tuple[str, ...] = (
    "maximum", "minimum", "approximate", "section_limit", "another_statement", "not_a_limit",
)

#: The bounds that set no cap or floor. Addendum §6.5: recorded, not yet
#: enforced -- the figure yields a `topic` rule carrying its sentence, which the
#: letter lands in `letter_written_requirements`, because the renderer has no
#: per-section check and a second statement is a document the engine does not
#: write (addendum §10). A TOLERANCE is not here and is not a bound at all:
#: "an exceedance of more than 10 percent" states no length of the document,
#: so the sentence's operation is `topic` and no figure of it is asked a bound.
NOTE_BOUNDS: frozenset[str] = frozenset({"section_limit", "another_statement"})

#: The letter's form (derive.LetterVerdict's `form` minus its "none"), onto
#: LetterShape.form. A value outside it has no sink and is `unapplied`.
FORM_VALUES: tuple[str, ...] = ("essay", "formal_letter", "portal_form")

#: Whether the letter must, may or must not name a prospective supervisor
#: (LetterVerdict's `naming` minus "none"), onto LetterShape.naming.
NAMING_VALUES: tuple[str, ...] = ("required", "invited", "forbidden")

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

# <!-- amended 2026-09-26: moved verbatim from derive.py so the grammar keeps the
# guards and Task 10's cut of derive.py cannot take them -->
#: The smallest cap any real programme states. Grounded in the 119-rule research
#: catalogue (docs/research/letter-shape-rules.csv), whose shortest published
#: limits are in the hundreds of words and thousands of characters -- nothing
#: near these floors. A cap below one of them is a misread digit, not a rule,
#: and acting on it blocks every letter for that programme with nobody to see
#: why. Rejecting it costs only the cap: the default target then applies.
#:
#: Applies to CAPS only, never floors: a floor is already bounded above by
#: the page's own text, and a too-small floor is harmless (it only asks for
#: a longer letter, exactly like a false floor from a fabricated number).
_IMPLAUSIBLE_CAP = {"words": 50, "chars": 200, "pages": 0.25}

#: The largest figure any real programme states. Above this it is a misread, not a
#: rule: no motivation letter runs to twenty pages, and a floor above these blocks
#: every letter for the programme. Unlike the lower band this applies to FLOORS as
#: well as caps -- a too-small floor is harmless, an absurd one blocks everything --
#: and it also keeps max_pages inside its DecimalField(4,1) column, where an
#: overflow would raise inside read_and_derive's transaction and roll back the whole
#: read, statements and snapshot included.
_IMPLAUSIBLE_MAX = {"words": 20_000, "chars": 100_000, "pages": 20}

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
# <!-- amended 2026-09-26: addendum §6.2 -- floors keep a sink -->
#: A letter floor per unit. No column holds a page floor and no checker
#: measures one, so a page floor is `unapplied`. The CV has no floor sink at all.
_LETTER_FLOOR_SINK: dict[str, str] = {"words": "min_words", "characters": "min_chars"}
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
    # <!-- reconciled 2026-09-26: `detail` is a style's sub-value only; the
    # spaces reading is `excl_spaces`, and a note bound is `bound` -->
    detail: str = ""
    confidence: float = 0.0
    #: "" when applied; otherwise one of §6.3's kinds or §6.5's `unapplied`:
    #: unsure | conflict | conditional | phrasing | third_party | unapplied | quarantined
    note: str = ""
    condition: str = ""
    probabilities: tuple[tuple[str, float], ...] = ()
    # <!-- amended 2026-09-26: addendum §6.1 -- one sentence, several figures -->
    # <!-- reconciled 2026-09-26: figure is None off a figure; excl_spaces is a field -->
    #: On a limit: maximum | minimum | approximate. On a topic cut from a
    #: length sentence: the NOTE_BOUNDS member its figure was. "" on everything
    #: else, and read as a cap by limit_sink's callers, which is the old
    #: single-length reading every pre-amendment test assumes.
    bound: str = ""
    #: Which figure of its sentence this rule is (letter_terms.figures_on_line's
    #: order). A range yields figures 0 and 1 from one sentence, so the index
    #: alone no longer names a rule. None when no figure produced the rule.
    figure: int | None = None
    #: On a character figure: True when the page counts WITHOUT spaces (the
    #: per-figure Noul, at the bar). Only the CV's key depends on it
    #: (limit_sink); the letter's cap and floor are each measured the stricter
    #: way whatever the page says.
    excl_spaces: bool = False

    @property
    def applied(self) -> bool:
        return not self.note


def sink_for(document: str, operation: str, value: object) -> str:
    """Where this rule lands, or "" when nothing downstream can carry it.

    "" is not an error: it is §6.5's `unapplied`, the honest answer when a page
    states a real requirement the engine has no handler for. It is counted, and
    the grammar grows from the count -- never from a model improvising.

    For a limit, `value` is the UNIT and the answer is the cap's sink; a caller
    that knows the figure's bound calls `limit_sink`.
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


# <!-- amended 2026-09-26: addendum §6.1-6.2 -- a figure's sink is its bound and its unit -->
# <!-- reconciled 2026-09-26: NOTE_BOUNDS have no sink; excl_spaces is rule.excl_spaces -->
def limit_sink(document: str, bound: str, unit: str, *, excl_spaces: bool = False) -> str:
    """Where one figure lands, or "" when nothing can carry it.

    A cap and an approximation land on the unit's max field; a floor lands on the
    letter's min_words / min_chars and nowhere else -- no CV checker measures a
    floor and nothing measures a page floor, so those are `unapplied`, shown and
    counted, never silently read as caps. `not_a_limit` and an unknown unit have
    no sink, and neither has a NOTE_BOUNDS figure -- it becomes a topic.
    `excl_spaces` (always `rule.excl_spaces`) only moves a CV character cap to
    its own key: the letter's one character cap is measured with spaces, the
    stricter reading.
    """
    if document == "reference_letter":
        return "student_actions"
    if bound == "minimum":
        return _LETTER_FLOOR_SINK.get(unit, "") if document == "motivation_letter" else ""
    if bound not in ("maximum", "approximate"):
        return ""
    if document == "cv":
        if unit == "characters" and excl_spaces:
            return "max_chars_excl_spaces"
        return _CV_LIMIT_SINK.get(unit, "")
    if document == "motivation_letter":
        return _LETTER_LIMIT_SINK.get(unit, "")
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
    # <!-- reconciled 2026-09-26: addendum §6.3 -- LetterShape.form / .naming -->
    if operation == "form":
        return "form" if value in FORM_VALUES else ""
    if operation == "naming":
        return "naming" if value in NAMING_VALUES else ""
    return ""


#: Every sink this grammar may name. A test pins it against the real field and
#: key lists so a rename downstream fails here rather than silently dropping rules.
# <!-- reconciled 2026-09-26: "form" and "naming" -->
SINKS: frozenset[str] = frozenset(
    {"cv_directives", "cv_format_requirement", "student_actions", "written_requirements",
     "document_language", "form", "naming", ""}
    | set(get_args(_CONSTRAINT_KEYS))
    | set(_CV_LIMIT_SINK.values())
    | set(_LETTER_LIMIT_SINK.values())
    | set(_LETTER_FLOOR_SINK.values())
    | set(_LETTER_STYLE_SINK.values())
)
```

(The `# <!-- amended ... -->` and `# <!-- reconciled ... -->` lines inside the code block are plan
markers; do not paste them.)

Move the two constants out of `apps/documents/derive.py`: delete the block that begins
`#: The smallest cap any real programme states.` through `_IMPLAUSIBLE_MAX = {"words": 20_000,
"chars": 100_000, "pages": 20}` (lines 1009–1028 at `134b176`; re-resolve), keep `_MEASURE_KEY`
above it, and add to derive's imports, after the `.constraints` block:

```python
from .grammar import _IMPLAUSIBLE_CAP, _IMPLAUSIBLE_MAX
```

`grammar.py` imports only `constraints`, so this adds no cycle.

- [ ] **Step 10: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_types.py tests/documents/test_letter_shape.py -v`
Expected: `test_grammar_types.py` 30 passed (17 tests, one parametrised over 14 cases) <!-- reconciled 2026-09-26 -->; `test_letter_shape.py` unchanged and green — its implausible-cap tests now exercise the moved constants.

- [ ] **Step 11: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean. If ruff reports `I001` on an import block, `uv run ruff check --fix` on that file only (a lint fix, not `ruff format`).

- [ ] **Step 12: Commit**

<!-- reconciled 2026-09-26: the message names the note bounds and form/naming -->

```bash
git -C "$WT" add apps/documents/grammar.py apps/documents/derive.py tests/documents/test_grammar_types.py
uv run git -C "$WT" commit -m "feat: the rule grammar's vocabulary, and the sink every operation projects onto

Four slots over closed lists, and every operation resolves to a sink that
already exists -- a constraint key the renderer checks, a directive the
generator reads, a LetterShape field the letter engine uses. An operation whose
value names no sink returns '', which is \`unapplied\`: kept verbatim, shown,
counted, never improvised into a writing prompt. A reference letter binds the
referee, so for the applicant it is one action and nothing else.

A length is a figure with a bound: a cap or an approximation lands on the
unit's max field, a floor on the letter's min_words or min_chars, and a CV or
page floor -- which nothing measures -- is unapplied rather than read as a cap.
A section limit or another statement's length is a note bound: a topic for
the writer, never a length. The letter's form and naming are operations, so
nothing the frontier judge types is lost.
The plausibility bands move here from derive.py so the judge and the grammar
share one definition.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The first request — document, operation, scope

Unchanged in behaviour by the addendum. Reproduced with two amendments: `Candidate` is imported
for annotations only (the cycle, stale item 1), and the seam is typed for `mypy --strict`
(stale item 2).

**Files:**
- Create: `apps/documents/grammar_questions.py`
- Test: `tests/documents/test_grammar_slots.py`

**Interfaces:**
- Consumes: `apps.research.decisions.{Choice, Noul, ask, Answer, DecisionBudget, Question}`; Produces `grammar_questions.AskFn` (the grammar's seam, distinct from `decisions.Client`), `grammar.{DOCUMENTS, OPERATIONS, Slotted}`, `derive.Candidate` (annotation only)
- Produces: `slot_state(candidates) -> dict[str, object]`, `slot_questions(candidates) -> dict[str, Question]`, `read_slots(candidates, *, language="", budget=None, client=None, record=True) -> tuple[Slotted, ...]`, `SLOT_BAR`, `CHUNK`, `_ask(state, questions, *, client=None, **kwargs) -> dict[str, Answer]`

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


# <!-- reconciled 2026-09-26: addendum §6.3 -->
def test_the_operation_choice_offers_form_and_naming_and_describes_every_option():
    """Task 9 projects `form` and `naming`; an operation the first request never
    offers is one no page can ever state. A tolerance is described as a topic,
    so its figures are never asked a bound."""
    question = slot_questions(_candidates())["0:operation"]
    assert {"form", "naming"} <= set(question.options)
    assert set(question.criteria) == set(question.options)
    assert "tolerance" in question.criteria["topic"]["what"]


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

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_slots.py -v`
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

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from typing import Protocol

from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudget,
    Noul,
    Question,
    ask,
)

from .grammar import DOCUMENTS, OPERATIONS, Slotted


# <!-- reconciled 2026-09-26: the grammar's seam has its own type. decisions.Client is the
# provider transport ask() calls with `model=` and `provider=`; this stands in for ask()
# itself and receives ask()'s own keywords. One alias for both let a double built for one
# pass the type check where the other is expected and fail at run time. A transport's
# required keyword-only parameters make it incompatible with this protocol, so mypy
# catches that mix-up. -->
class AskFn(Protocol):
    """Stands in for decisions.ask() in tests and measurement runs."""

    def __call__(
        self, state: object, questions: Mapping[str, Question], /, **kwargs: Any
    ) -> dict[str, Answer]: ...

# <!-- amended 2026-09-26: annotation-only import, stale item 1 -->
if TYPE_CHECKING:
    # Never at run time: derive.py imports this module (Task 10), so a
    # module-level `from .derive import Candidate` here is a circular import
    # that fails on whichever of the two loads first.
    from .derive import Candidate

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

# <!-- reconciled 2026-09-26: `form` and `naming` (addendum §6.3); a tolerance is a
# topic, not a limit, so the limit/topic boundary says so in both directions -->
_OPERATION_CRITERIA = {
    "limit": {"what": "A maximum or minimum length: pages, words or characters.",
              "examples": ["no longer than two pages", "800 words maximum",
                           "Each part may have up to 400 words."],
              "not_for": "How far a stated length may be exceeded or undershot -- a "
                         "tolerance such as 'more than 10 percent over the limit'. "
                         "That is a topic."},
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
                      "programme asks, a theme it names -- or a condition on a length "
                      "that is not itself a length, such as a tolerance.",
              "examples": ["Explain your career plans after graduation.",
                           "An exceedance of the word limit by more than 10 percent "
                           "leads to exclusion."],
              "not_for": "A rule that sets the document's form, length or language."},
    "form": {"what": "What kind of text the letter is: an essay, a formal letter "
                     "addressed to someone, or answers typed into the portal's own fields.",
             "examples": ["Address your letter to the admissions committee.",
                          "Answer the questions in the online form."]},
    "naming": {"what": "Whether the letter must, may or must not name a prospective "
                       "supervisor or professor.",
               "examples": ["Please name a potential supervisor.",
                            "Do not contact or name individual professors."]},
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
    client: AskFn | None = None,
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


# <!-- amended 2026-09-26: typed for mypy --strict, stale item 2 -->
def _ask(
    state: object,
    questions: Mapping[str, Question],
    *,
    client: AskFn | None = None,
    **kwargs: Any,
) -> dict[str, Answer]:
    """One seam so both request modules inject the same test double."""
    if client is not None:
        return client(state, questions, **kwargs)
    return ask(state, questions, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_slots.py -v`
Expected: 9 passed <!-- reconciled 2026-09-26 -->

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean

- [ ] **Step 6: Commit**

<!-- reconciled 2026-09-26: the message names form/naming and the tolerance boundary -->

```bash
git -C "$WT" add apps/documents/grammar_questions.py tests/documents/test_grammar_slots.py
uv run git -C "$WT" commit -m "feat: the grammar's first request -- document, operation, scope

Every question names its sentence by id and the state carries that sentence
under its heading path: indirection costs accuracy in Jev's own documentation,
and a bare sentence is where the supervisor's-CV attribution error came from.
A page over 200 sentences is chunked, never truncated -- a page we only partly
read must not look like a page that said nothing.

Candidate is imported for annotations only: derive.py will import this module,
and a run-time import back would be a cycle.

The operation question offers form and naming, so nothing the frontier judge
types is lost, and describes a tolerance as a topic rather than a length.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The second request — the typed values, one decision per figure

<!-- amended 2026-09-26: addendum §6.1, §6.5, §9 -- numbers_in is replaced by
letter_terms.figures_on_line; every figure is its own Choice; nothing combines figures -->

Two parts, two commits. Part A extends `letter_terms` so code finds every figure **with the unit
word printed beside it**, reusing `numbers_on_line`'s digit rule, space-grouped thousands, number
words and unit window. Part B asks one bound Choice per figure. A range is a floor and a cap; two
units are two caps; a per-section cap or a second statement's length is a note bound and becomes
a topic. <!-- reconciled 2026-09-26 --> A tolerance is not a figure's bound at all: its sentence is
a `topic` by operation (Task 5), so no figure of it is asked. The letter's `form` and `naming`
are asked here too, each a Choice over its closed tuple plus a `none` escape.

**Files:**
- Part A — Modify: `apps/documents/letter_terms.py`; Test: `tests/documents/test_letter_terms.py`
- Part B — Create: `apps/documents/grammar_values.py`; Test: `tests/documents/test_grammar_values.py`

**Interfaces:**
- Consumes: `letter_terms.{normalise_numerals, TERMS, _NUMBER_WORDS, _SPACE_GROUPED, _WORD_WINDOW, _TOKEN, _units, _HAN, _HANGUL, _KANA}` (from `claude/judge-schema-fix`; the last three were used but unlisted <!-- reconciled 2026-09-26 -->), `grammar.{Slotted, Rule, Operation, FORMAT_VERDICTS, STYLE_VALUES, UNITS, BOUNDS, NOTE_BOUNDS, FORM_VALUES, NAMING_VALUES, CONDITION_KINDS, _IMPLAUSIBLE_CAP, _IMPLAUSIBLE_MAX, sink_for, limit_sink}` <!-- reconciled 2026-09-26: LIMIT_KINDS removed -->, `grammar_questions.{_ask, CHUNK, SLOT_BAR}`, `decisions.{Choice, Noul, Answer, DecisionBudget, Question}`, `grammar_questions.AskFn`, `constraints.{_INCLUDE_TARGETS, _ORDER_TARGETS, _SECTIONS}`
- Produces (Part A): `Figure(number: int | float, unit: str, span: tuple[int, int])`, `figures_on_line(text) -> tuple[Figure, ...]`; `numbers_on_line` unchanged
- Produces (Part B): `value_state(candidates, slots) -> dict[str, object]`, `value_questions(candidates, slots) -> dict[str, Question]`, `read_values(candidates, slots, *, language="", budget=None, client=None, record=True) -> tuple[Rule, ...]`, `FORMAT_EXAMPLES`, `font_candidates(text) -> tuple[str, ...]`, `language_candidates(text) -> tuple[tuple[str, str], ...]`. **`numbers_in` is gone.**

Spec §6.1 and §6.2; addendum §6.1, §6.5. **A number is found by code and never chosen by a
model:** the number a rule carries is always a figure `figures_on_line` returned. The model only
says what each figure *is*.

#### Part A — figures, with their units

- [ ] **Step 0: Confirm the number-word fix landed**

Run: `grep -n "def numbers_on_line\|^_SPACE_GROUPED\|^_WORD_WINDOW" apps/documents/letter_terms.py`
Expected: three matches. If `numbers_on_line` is absent, `claude/judge-schema-fix` has not landed —
stop; addendum §11 puts it first.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_letter_terms.py -- append; extend the existing import line to
# `from apps.documents.letter_terms import (
#     TERMS, detect_language, figures_on_line, normalise_numerals, numbers_on_line,
# )`


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # Measured live 2026-09-25 (TUM, ETH, Sciences Po): written as a word, or
        # space-grouped, and each lost its cap.
        ("eine schriftliche Begründung von maximal zwei DIN-A4-Seiten", [(2, "seiten")]),
        ("Approximately one A4 page in the language of instruction", [(1, "page")]),
        # The joined thousand AND its first part: a plain space also separates two
        # real numbers, so both are offered and the per-figure bound decides.
        ("Votre lettre de motivation doit aborder en maximum 1 000 mots",
         [(1000, "mots"), (1, "mots")]),
        # A number word far from any unit is no figure at all.
        ("One of the documents is a motivation letter of 500 words.", [(500, "words")]),
        # A range: both figures, each with the unit.
        ("The letter should be 300–500 words.", [(300, "words"), (500, "words")]),
        ("at most 3,500 characters (approximately 500 words)",
         [(3500, "characters"), (500, "words")]),
        # A year is offered with no unit: whether it is a limit is the page's to say.
        ("Letters for the 2027 intake may not exceed 800 words.", [(2027, ""), (800, "words")]),
        # A dot before exactly three digits is a thousands group (Kassel's floor)...
        ("mindestens 2.800 Zeichen", [(2800, "zeichen")]),
        # ...and one or two digits after a comma or dot are a decimal.
        ("maximal 1,5 Seiten", [(1.5, "seiten")]),
        # A CJK unit runs into the next word; a figure after CJK text is still found.
        ("不超过800字以内", [(800, "字")]),
    ],
)
def test_figures_carry_the_unit_printed_beside_them(line, expected) -> None:
    assert [(f.number, f.unit) for f in figures_on_line(line)] == expected


def test_a_figure_glued_to_a_letter_is_a_model_name_not_a_count() -> None:
    # <!-- reconciled 2026-09-26: no name of the deleted finder in shipped code -->
    """The 4 in "A4" was a candidate limit under the old digit finder; it is none here."""
    assert all(f.number != 4 for f in figures_on_line("one A4 page, DIN-A4 format"))


def test_a_figures_span_indexes_the_normalised_line() -> None:
    line = "mindestens 2.800 Zeichen"
    (figure,) = figures_on_line(line)
    assert normalise_numerals(line)[figure.span[0] : figure.span[1]] == "2.800"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_letter_terms.py -v`
Expected: FAIL with `ImportError: cannot import name 'figures_on_line'`

- [ ] **Step 3: Write `figures_on_line`**

```python
# apps/documents/letter_terms.py -- append after numbers_on_line


@dataclass(frozen=True)
class Figure:
    """One count a sentence states, with the unit word printed after it.

    `number` is an int unless the page wrote a decimal ("1,5 Seiten"). `unit` is
    the vocabulary's own unit word, casefolded, found within `_WORD_WINDOW`
    tokens after the figure -- or "" when none is, which is what a year, a date
    or a count of documents looks like. `span` indexes `normalise_numerals(text)`,
    never the raw sentence: the separators it strips move every offset after them.
    """

    number: int | float
    unit: str
    span: tuple[int, int]


#: A figure written in digits. A dot before exactly three digits is a thousands
#: group ("2.800 Zeichen" is 2800 -- normalise_numerals has already joined
#: "2,800"); one or two digits after a dot or comma are a decimal ("1,5 Seiten").
#: Never preceded by a Latin letter or a digit, so the 4 in "A4" is not a figure;
#: `\b` would also refuse "不超过800字", whose neighbour is a word character.
_FIGURE = re.compile(r"(?<![A-Za-z\d])(\d+(?:\.\d{3})*)(?:[.,](\d{1,2}))?(?!\d)")


def _prefix_units() -> tuple[str, ...]:
    """Units in a script written without spaces: they run into the next word
    ("字以内"), so they match as a prefix. Longest first, so "文字" wins over "字"."""
    spaceless = (
        unit
        for unit in _units()
        if _HAN.search(unit) or _HANGUL.search(unit) or _KANA.search(unit)
    )
    return tuple(sorted(spaceless, key=len, reverse=True))


_PREFIX_UNITS = _prefix_units()


def _unit_after(rest: str) -> str:
    """The first unit word within `_WORD_WINDOW` tokens of `rest`, or "".

    A Latin or Cyrillic unit must be the whole token -- "wordt" is Dutch for
    "is", not a word count -- and a spaceless-script unit may begin one.
    """
    units = _units()
    for token in _TOKEN.findall(rest)[:_WORD_WINDOW]:
        folded = str(token).casefold()  # findall is list[Any] to mypy
        if folded in units:
            return folded
        for unit in _PREFIX_UNITS:
            if folded.startswith(unit):
                return unit
    return ""


def _figure_value(whole: str, fraction: str | None) -> int | float:
    number = int(whole.replace(".", ""))
    return float(f"{number}.{fraction}") if fraction else number


def figures_on_line(text: str) -> tuple[Figure, ...]:
    """Every count the sentence states, each with the unit printed after it.

    The grammar's candidates for a length (addendum 2026-09-26 §6.1): code finds
    them, one Choice per figure says whether it is a cap, a floor, an
    approximation or no limit at all, and the number a rule carries is copied
    from here -- never from a model. So this is where "a value the page did not
    print cannot be chosen" is enforced.

    The three readings `numbers_on_line` verifies with, now returned as figures:
    - digits, as a whole figure (a thousands group joined, a decimal kept),
      offered with or without a unit -- "2027" must still be asked about and
      answered `not_a_limit`; dropping it here would be code deciding what
      only the sentence can say;
    - a space-grouped thousand joined ("1 000 mots"), offered BESIDE its parts:
      a plain space also separates two real numbers ("Part 2 500 words"), and
      the per-figure bound, the plausibility bands and the safer-side merge
      settle which it was;
    - a number word only within `_WORD_WINDOW` tokens before a unit, so "one of
      the documents" is no figure at all.
    A zero is never a length and is not offered. Ordered by position, a joined
    thousand before the part it starts with.
    """
    normalised = normalise_numerals(text)
    found: list[Figure] = []
    for match in _FIGURE.finditer(normalised):
        number = _figure_value(match.group(1), match.group(2))
        if number:
            found.append(Figure(number, _unit_after(normalised[match.end() :]), match.span()))
    for match in _SPACE_GROUPED.finditer(normalised):
        found.append(
            Figure(
                int(match.group(0).replace(" ", "")),
                _unit_after(normalised[match.end() :]),
                match.span(),
            )
        )
    for match in _TOKEN.finditer(normalised):
        value = _NUMBER_WORDS.get(match.group().casefold())
        if value is not None:
            unit = _unit_after(normalised[match.end() :])
            if unit:
                found.append(Figure(value, unit, match.span()))
    return tuple(sorted(found, key=lambda figure: (figure.span[0], -figure.span[1])))
```

`dataclass`, `re`, `_HAN`, `_HANGUL` and `_KANA` are already imported by the module.

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_letter_terms.py tests/documents/test_letter_shape.py -v`
Expected: every `test_letter_terms.py` test passes, 12 more than before (10 parametrised cases +
2); `numbers_on_line`'s own tests and `test_letter_shape.py` are unchanged.

- [ ] **Step 5: Run the checks and commit**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean

```bash
git -C "$WT" add apps/documents/letter_terms.py tests/documents/test_letter_terms.py
uv run git -C "$WT" commit -m "feat: figures_on_line -- every count a sentence states, with its unit

numbers_on_line answers 'is this number printed here?'; the grammar needs the
other question -- which figures does this sentence state, and in what unit --
so one decision can be asked per figure. Same three readings: digits (now a
decimal and a dotted thousands group are one figure, and the 4 in A4 is none),
a space-grouped thousand beside its parts, and a number word only just before
a unit. A year is still offered: whether it is a limit is the sentence's to say.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

#### Part B — the value questions

- [ ] **Step 6: Write the failing test**

<!-- amended 2026-09-26: the limit tests are rewritten for one decision per figure; every
other test is the original, verbatim -->

```python
# tests/documents/test_grammar_values.py
import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar import Slotted, limit_sink, sink_for
from apps.documents.grammar_values import read_values, value_questions, value_state
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
    for neutral in ("not_a_limit", "none", "other", "any", "not_a_format_rule"):
        if neutral in options:
            return neutral
    return options[0]


def _one(text, document, operation, **slot):
    """One sentence and its settled slots, for the tests written after the amendment."""
    candidates = (Candidate(text=text, heading="", europass=False),)
    slots = (Slotted(index=0, document=document, document_confidence=0.97,
                     operation=operation, operation_confidence=0.95,
                     third_party=slot.get("third_party", False),
                     conditional=slot.get("conditional", False)),)
    return candidates, slots


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


def test_a_margin_keeps_its_decimal():
    # <!-- reconciled 2026-09-26 -->
    """The old digit finder read "2,5 cm" as 25: a 25 cm margin on a page 21 cm wide."""
    candidates, slots = _one("Margins of 2,5 cm on every side.", "motivation_letter", "style")
    assert value_questions(candidates, slots)["0:style_number"].options == ("2.5", "none")
    rules = read_values(candidates, slots, client=_script({
        "0:style": ("margins", 0.93), "0:style_number": ("2.5", 0.95),
    }))
    assert (rules[0].value, rules[0].detail) == ("margins", "2.5")


# <!-- reconciled 2026-09-26: no sentence-level kind question; the bound carries it -->
def test_only_the_operations_present_get_value_questions():
    """The 48 format examples ride on format sentences only -- that is why the
    slots and the values are two requests (spec §6.1). A limit sentence gets,
    per figure, a bound, a unit and -- on the CV, where it picks a key --
    whether spaces count."""
    candidates, slots = _one("Your CV may not exceed two pages.", "cv", "limit")
    assert set(value_questions(candidates, slots)) == {
        "0:figure:0:bound", "0:figure:0:unit", "0:figure:0:spaces",
    }


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


def test_a_page_limit_is_a_figure_code_found():
    candidates, slots = _one("Your CV may not exceed two pages.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.96), "0:figure:0:unit": ("pages", 0.98),
    }))
    assert (rules[0].value, rules[0].unit, rules[0].bound) == (2, "pages", "maximum")
    assert rules[0].applied is True


def test_a_limit_sentence_with_no_figure_is_unapplied_and_nothing_can_be_invented():
    """The same principle as verified_statements, now structural: no figure on
    the page means no figure question at all, so there is nothing a provider
    could answer with a number nobody wrote."""
    candidates, slots = _one("Keep the CV short.", "cv", "limit")
    # <!-- reconciled 2026-09-26 -->
    assert set(value_questions(candidates, slots)) == set()
    rules = read_values(candidates, slots, client=_script({}))
    assert [(r.value, r.note) for r in rules] == [(None, "unapplied")]


def test_a_range_is_a_floor_and_a_cap_never_the_floor_as_the_cap():
    """Addendum §6.1. Measured 2026-09-25: every floor and range lost its floor,
    because a verdict held one length."""
    candidates, slots = _one("The motivation letter should be 300–500 words.",
                             "motivation_letter", "limit")
    assert value_state(candidates, slots)["sentences"][0]["figures"] == [
        {"figure": "300", "unit_as_printed": "words"},
        {"figure": "500", "unit_as_printed": "words"},
    ]
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("minimum", 0.93), "0:figure:0:unit": ("words", 0.97),
        "0:figure:1:bound": ("maximum", 0.95), "0:figure:1:unit": ("words", 0.98),
    }))
    assert [(r.value, r.unit, r.bound, r.figure, r.applied) for r in rules] == [
        (300, "words", "minimum", 0, True), (500, "words", "maximum", 1, True),
    ]
    assert [limit_sink(r.document, r.bound, r.unit) for r in rules] == ["min_words", "max_words"]


def test_a_figure_in_each_unit_is_two_caps():
    text = "The letter may have at most 3,500 characters (approximately 500 words)."
    candidates, slots = _one(text, "motivation_letter", "limit")
    # The letter's one character cap is measured with spaces, so it is not asked.
    assert "0:figure:0:spaces" not in value_questions(candidates, slots)
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.94), "0:figure:0:unit": ("characters", 0.97),
        "0:figure:1:bound": ("approximate", 0.91), "0:figure:1:unit": ("words", 0.96),
    }))
    assert [(r.value, r.unit, r.bound) for r in rules] == [
        (3500, "characters", "maximum"), (500, "words", "approximate"),
    ]
    assert {limit_sink(r.document, r.bound, r.unit) for r in rules} == {"max_chars", "max_words"}


@pytest.mark.parametrize(
    ("text", "number", "bound"),
    [
        ("Die Begründung umfasst maximal zwei DIN-A4-Seiten.", 2, "maximum"),  # TUM
        ("Approximately one A4 page.", 1, "approximate"),  # ETH
    ],
)
def test_a_limit_written_as_a_word_is_a_figure(text, number, bound):
    candidates, slots = _one(text, "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": (bound, 0.93), "0:figure:0:unit": ("pages", 0.97),
    }))
    assert [(r.value, r.unit, r.bound) for r in rules] == [(number, "pages", bound)]


def test_a_space_grouped_thousand_is_the_figure_and_its_stray_part_is_implausible():
    """Sciences Po, measured 2026-09-25. The joined 1000 and the part 1 are both
    offered; answered as caps, 1 word is below the plausibility band and drops."""
    candidates, slots = _one("Votre lettre de motivation doit aborder en maximum 1 000 mots.",
                             "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("words", 0.97),
        "0:figure:1:bound": ("maximum", 0.90), "0:figure:1:unit": ("words", 0.90),
    }))
    assert [(r.value, r.unit, r.applied) for r in rules] == [(1000, "words", True)]


def test_a_number_word_far_from_a_unit_is_never_asked_about():
    candidates, slots = _one("One of the documents is a motivation letter of 500 words.",
                             "motivation_letter", "limit")
    questions = value_questions(candidates, slots)
    assert "0:figure:0:bound" in questions and "0:figure:1:bound" not in questions
    assert value_state(candidates, slots)["sentences"][0]["figures"] == [
        {"figure": "500", "unit_as_printed": "words"},
    ]


# <!-- review focus 1 -->
def test_a_year_is_offered_and_not_a_limit_writes_nothing():
    """Code must not decide a year is not a length -- the sentence does. So the
    figure is asked about, and the grammar never writes it when the answer is
    not_a_limit."""
    candidates, slots = _one("Letters for the 2027 intake may not exceed 800 words.",
                             "motivation_letter", "limit")
    assert "0:figure:0:bound" in value_questions(candidates, slots)
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("not_a_limit", 0.96),
        "0:figure:1:bound": ("maximum", 0.95), "0:figure:1:unit": ("words", 0.97),
    }))
    assert [(r.value, r.unit, r.bound, r.figure) for r in rules] == [(800, "words", "maximum", 1)]


def test_a_figure_below_the_bar_is_one_note_beside_the_rules_that_cleared_it():
    candidates, slots = _one("At most 800 words, ideally around 600.",
                             "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("words", 0.97),
        "0:figure:1:bound": ("approximate", 0.55), "0:figure:1:unit": ("words", 0.90),
    }))
    assert [(r.value, r.note) for r in rules] == [(800, ""), (None, "unsure")]


def test_a_character_floor_is_kept_as_a_floor():
    """Kassel: a letter under 2,800 characters is rejected (addendum §6.2)."""
    candidates, slots = _one("Das Motivationsschreiben muss mindestens 2.800 Zeichen umfassen.",
                             "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("minimum", 0.94), "0:figure:0:unit": ("characters", 0.97),
    }))
    assert [(r.value, r.unit, r.bound, r.applied) for r in rules] == [
        (2800, "characters", "minimum", True),
    ]
    assert limit_sink("motivation_letter", "minimum", "characters") == "min_chars"


def test_a_cv_floor_has_no_sink_and_is_unapplied_with_its_sentence():
    candidates, slots = _one("The CV must be at least two pages long.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("minimum", 0.94), "0:figure:0:unit": ("pages", 0.97),
        "0:figure:0:spaces": (True, 0.9),
    }))
    assert [(r.value, r.bound, r.note) for r in rules] == [(2, "minimum", "unapplied")]
    assert rules[0].sentence == "The CV must be at least two pages long."


def test_a_cv_character_cap_that_leaves_out_spaces_says_so():
    candidates, slots = _one("The CV may not exceed 4,000 characters without spaces.",
                             "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("characters", 0.97),
        "0:figure:0:spaces": (False, 0.92),
    }))
    # <!-- reconciled 2026-09-26: a boolean on the rule, not a string in `detail` -->
    assert (rules[0].value, rules[0].excl_spaces, rules[0].detail) == (4000, True, "")
    assert limit_sink("cv", rules[0].bound, rules[0].unit,
                      excl_spaces=rules[0].excl_spaces) == "max_chars_excl_spaces"


def test_a_character_count_not_clearly_without_spaces_is_read_with_them():
    """Counting spaces is the stricter reading of a cap, so doubt lands there."""
    candidates, slots = _one("The CV may not exceed 4,000 characters.", "cv", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("characters", 0.97),
        "0:figure:0:spaces": (False, 0.60),
    }))
    # <!-- reconciled 2026-09-26 -->
    assert (rules[0].value, rules[0].excl_spaces) == (4000, False)


# <!-- reconciled 2026-09-26: the note is the figure's bound (NOTE_BOUNDS), not a
# sentence-level kind; a tolerance is a topic sentence and never a bound -->
@pytest.mark.parametrize(
    ("text", "bound"),
    [
        ("Each part of the statement may have up to 400 words.", "section_limit"),
        ("In addition, submit a statement of 250 words on your research interests.",
         "another_statement"),
    ],
)
def test_what_no_sink_can_enforce_reaches_the_writer_as_a_topic(text, bound):
    """Addendum §6.5: recorded, not yet enforced. The sentence reaches the letter
    writer and the document carries it; its figure never becomes a length."""
    candidates, slots = _one(text, "motivation_letter", "limit")
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": (bound, 0.93), "0:figure:0:unit": ("words", 0.97),
    }))
    assert [(r.operation, r.value, r.bound, r.figure, r.applied) for r in rules] == [
        ("topic", text, bound, 0, True),
    ]
    assert sink_for("motivation_letter", "topic", text) == "written_requirements"


# <!-- review focus 5 -->
def test_a_limit_in_a_language_with_no_unit_words_still_reaches_a_rule_or_a_note():
    """Kazakh is not seeded in letter_terms, so the finder offers the figure with no
    unit printed beside it, and the unit Choice supplies one. A confident unit lands
    a cap; an unsure one keeps the sentence as an `unsure` note -- never silence."""
    text = "Мотивациялық хат 500 сөзден аспауы тиіс."
    candidates, slots = _one(text, "motivation_letter", "limit")
    sure = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.93), "0:figure:0:unit": ("words", 0.95),
    }))
    assert [(r.value, r.unit, r.bound, r.note) for r in sure] == [(500, "words", "maximum", "")]
    unsure = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.93), "0:figure:0:unit": ("words", 0.40),
    }))
    assert len(unsure) == 1 and unsure[0].note == "unsure"


def test_a_tolerance_lands_as_a_topic_and_never_as_a_limit():
    """'More than 10 percent' is no length of the document: the sentence is a
    topic by operation, no figure of it is asked a bound, and nothing reaches a
    cap or a floor."""
    text = "An exceedance of the word limit by more than 10 percent leads to exclusion."
    candidates, slots = _one(text, "motivation_letter", "topic")
    assert set(value_questions(candidates, slots)) == set()
    rules = read_values(candidates, slots, client=_script({}))
    assert [(r.operation, r.value, r.bound, r.applied) for r in rules] == [
        ("topic", text, "", True),
    ]


@pytest.mark.parametrize(
    ("operation", "value", "options"),
    [
        ("form", "formal_letter", ("essay", "formal_letter", "portal_form", "none")),
        ("naming", "forbidden", ("required", "invited", "forbidden", "none")),
    ],
)
def test_form_and_naming_are_a_choice_over_their_closed_values(operation, value, options):
    """Addendum §6.3: the frontier path types both, so the grammar asks both.
    `none` is the vendor's escape and has no sink, so it is `unapplied`."""
    candidates, slots = _one("Address the letter to the committee; do not name a professor.",
                             "motivation_letter", operation)
    assert value_questions(candidates, slots)[f"0:{operation}"].options == options
    rules = read_values(candidates, slots, client=_script({f"0:{operation}": (value, 0.94)}))
    assert [(r.operation, r.value, r.applied) for r in rules] == [(operation, value, True)]
    unset = read_values(candidates, slots, client=_script({f"0:{operation}": ("none", 0.94)}))
    assert unset[0].note == "unapplied"


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
    candidates, slots = _one("Short CV (max. 2 pages) from this academic supervisor.",
                             "cv", "limit", third_party=True)
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.97), "0:figure:0:unit": ("pages", 0.98),
        "0:figure:0:spaces": (True, 0.9),
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
    candidates, slots = _one(
        "Applicants in exceptional circumstances may submit three pages.",
        "cv", "limit", conditional=True,
    )
    rules = read_values(candidates, slots, client=_script({
        "0:figure:0:bound": ("maximum", 0.95), "0:figure:0:unit": ("pages", 0.95),
        "0:figure:0:spaces": (True, 0.9), "0:condition": ("other", 0.88),
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

- [ ] **Step 7: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_values.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.grammar_values'`

- [ ] **Step 8: Write the value questions**

```python
# apps/documents/grammar_values.py
"""The grammar's second request: which value, for the operation the first found.

Only the operations a page actually states get value questions, which is why
this is a second request rather than one huge one -- the 48 format examples ride
on the few sentences that are format rules, and `state` plus questions stays
inside Jev's 64k ceiling (spec §6.1).

**A number is found by code, never chosen by a model** (addendum 2026-09-26
§6.1). `letter_terms.figures_on_line` finds every figure a sentence prints with
the unit word beside it, and one Choice per figure says what the figure IS -- a
cap, a floor, an approximation, or not a limit at all. The number a rule carries
is always that figure. A range is a floor and a cap, two units are two caps, and
nothing here combines figures: which of two caps wins is `resolve_conflicts`'
question, on the safer side. A figure whose bound is a NOTE_BOUNDS member
(a section's length, another statement's) is a topic carrying the sentence.
"""

from __future__ import annotations

import csv
import logging
import pathlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.research.decisions import Answer, Choice, DecisionBudget, Noul, Question

from .constraints import _INCLUDE_TARGETS, _ORDER_TARGETS, _SECTIONS
# <!-- reconciled 2026-09-26: NOTE_BOUNDS, FORM_VALUES, NAMING_VALUES; no LIMIT_KINDS -->
from .grammar import (
    _IMPLAUSIBLE_CAP,
    _IMPLAUSIBLE_MAX,
    BOUNDS,
    CONDITION_KINDS,
    FORM_VALUES,
    FORMAT_VERDICTS,
    NAMING_VALUES,
    NOTE_BOUNDS,
    STYLE_VALUES,
    UNITS,
    Operation,
    Rule,
    Slotted,
    limit_sink,
    sink_for,
)
from .grammar_questions import CHUNK, SLOT_BAR, _ask
from .letter_terms import figures_on_line

if TYPE_CHECKING:
    # Annotation only -- derive.py imports this module (Task 10).
    from .derive import Candidate

logger = logging.getLogger(__name__)

_EVAL = pathlib.Path(__file__).resolve().parents[2] / "docs" / "research" / "cv-format-eval.csv"

# <!-- amended 2026-09-26: addendum §6.1 -- one decision per figure -->
#: Spec §6.1: `none` at >= 0.6 means no limit. A figure answered `not_a_limit`
#: that surely is dropped with no note -- a year or a count of referees is not
#: something a counsellor needs to read about. Less sure, the doubt is a note.
_NOT_A_LIMIT_BAR = 0.6

# <!-- reconciled 2026-09-26: the first draft's sentence-level _KIND_CRITERIA is gone;
# section_limit and another_statement are per-figure bounds below, and a tolerance is
# a topic sentence (Task 5), never a bound -->
_BOUND_CRITERIA: dict[str, object] = {
    "maximum": {
        "what": "The most the document may be: a cap.",
        "examples": ["no more than 800 words", "maximal zwei DIN-A4-Seiten",
                     "the 500 in 300–500 words"],
    },
    "minimum": {
        "what": "The least the document must be: a floor.",
        "examples": ["at least 500 words", "mindestens 2.800 Zeichen",
                     "the 300 in 300–500 words"],
    },
    "approximate": {
        "what": "A length the page gives as approximate: around, about, roughly.",
        "examples": ["approximately one A4 page", "around 1,000 words"],
    },
    "section_limit": {
        "what": "A length of one part, section or answer of the document, not of the whole.",
        "examples": ["the 400 in 'three parts of 400 words each'",
                     "Each answer may be up to 250 words."],
    },
    "another_statement": {
        "what": "A length of a different, additional statement in the same application.",
        "examples": ["the 250 in 'in addition, a statement of 250 words on your research'"],
    },
    "not_a_limit": {
        "what": "Not a length of this document: a year, a date, a count of documents "
                "or referees, a percentage, a fee, a font size.",
        "examples": ["the 2027 intake", "two letters of recommendation", "10 percent"],
    },
}

_UNIT_CRITERIA: dict[str, object] = {
    "pages": {"what": "Pages or sheets.", "examples": ["two pages", "zwei DIN-A4-Seiten", "2枚"]},
    "words": {"what": "Words.", "examples": ["800 words", "1 000 mots", "500 Wörter"]},
    "characters": {"what": "Characters or signs, with or without spaces.",
                   "examples": ["3,500 characters", "2.800 Zeichen", "800字"]},
    "other": {"what": "Anything else: megabytes, lines, minutes, percent, or no unit at all."},
}

#: Criteria because the common real sentence says nothing about spaces, and
#: counting them is the stricter reading of a cap -- so silence answers yes.
_SPACES_CRITERIA: dict[str, object] = {
    "true": {"what": "Spaces are counted, or the sentence does not mention spaces at all.",
             "examples": ["3,500 characters including spaces", "1,500 characters",
                          "2.000 Zeichen inkl. Leerzeichen"]},
    "false": {"what": "The sentence says spaces are not counted.",
              "examples": ["4,000 characters without spaces", "2.000 Zeichen ohne Leerzeichen",
                           "3 000 caractères hors espaces"]},
}


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


# <!-- amended 2026-09-26: the original skipped the whole capitalised run when its FIRST
# word was not a font, so "Use Times New Roman" yielded nothing and its own test failed -->
def font_candidates(text: str) -> tuple[str, ...]:
    """Every plausible font name the sentence prints, in order, deduplicated.

    A capitalised run is trimmed of the leading words that are certainly not a
    font ("Use Times New Roman" -> "Times New Roman"), never discarded whole:
    the regex consumes the run, so a skipped run is a font nobody can pick.
    """
    found: list[str] = []
    for match in _FONT_NAME.finditer(text):
        words = match.group().split()
        while words and words[0] in _NOT_A_FONT:
            words.pop(0)
        name = " ".join(words)
        if len(name) >= 4 and name not in found:
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


def _asks_values(slot: Slotted) -> bool:
    return slot.document != "other" and not _below_bar(slot)


def value_state(
    candidates: Sequence[Candidate], slots: Sequence[Slotted]
) -> dict[str, object]:
    """The sentences, and under each length sentence the figures code found.

    A figure is shown as code found it -- the number and the unit word printed
    after it -- so each bound question points at one figure by path
    (`sentences[3].figures[1]`), never "the second number" in prose (§3.1a).
    """
    limits = {s.index for s in slots if s.operation == "limit" and _asks_values(s)}
    sentences: list[dict[str, object]] = []
    for i, candidate in enumerate(candidates):
        entry: dict[str, object] = {"id": str(i), "heading": candidate.heading,
                                    "text": candidate.text}
        if i in limits:
            entry["figures"] = [
                {"figure": str(f.number), "unit_as_printed": f.unit}
                for f in figures_on_line(candidate.text)
            ]
        sentences.append(entry)
    return {"sentences": sentences}


def value_questions(
    candidates: Sequence[Candidate], slots: Sequence[Slotted]
) -> dict[str, Question]:
    """One question set per sentence, for the operation its slot found.

    A sentence whose slots are below the bar, or whose document is `other`, gets
    no value question at all: there is nothing to ask a value for.
    """
    questions: dict[str, Question] = {}
    for slot in slots:
        if not _asks_values(slot):
            continue
        i = slot.index
        where = f"`sentences[{i}]`"
        text = candidates[i].text
        # <!-- amended 2026-09-26: addendum §6.1 and §6.5 -->
        # <!-- reconciled 2026-09-26: no sentence-level kind; each figure's bound says it -->
        if slot.operation == "limit":
            # Every question below is asked for every figure: a figure's unit
            # and bound are in the same response, so none can wait for another.
            # Tokens, never a call.
            for k in range(len(figures_on_line(text))):
                at = f"`sentences[{i}].figures[{k}]`"
                questions[f"{i}:figure:{k}:bound"] = Choice(
                    inspect=at, options=BOUNDS, criteria=_BOUND_CRITERIA,
                    question="Is this figure a limit on the document's length, and which kind?",
                    focus="Read the figure inside its sentence: a range states two "
                          "figures, a floor and a cap.",
                )
                questions[f"{i}:figure:{k}:unit"] = Choice(
                    inspect=at, question="What is this figure counted in?",
                    options=(*UNITS, "other"), criteria=_UNIT_CRITERIA,
                )
                if slot.document == "cv":
                    # Only the CV picks a key by it (max_chars_incl/excl_spaces);
                    # the letter's cap is measured with spaces and its floor
                    # without -- each the stricter reading -- so it never asks.
                    questions[f"{i}:figure:{k}:spaces"] = Noul(
                        inspect=at, question="Does this count of characters include spaces?",
                        criteria=_SPACES_CRITERIA,
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
            # <!-- amended 2026-09-26: figures, so "2,5 cm" is 2.5 and never 25 -->
            numbers = tuple(dict.fromkeys(str(f.number) for f in figures_on_line(text)))
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
        # <!-- reconciled 2026-09-26: addendum §6.3 -->
        elif slot.operation in ("form", "naming"):
            questions[f"{i}:{slot.operation}"] = Choice(
                inspect=where, question=_TARGET_QUESTION[slot.operation],
                options=_TARGET_OPTIONS[slot.operation],
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
    client: AskFn | None = None,
    record: bool = True,
) -> tuple[Rule, ...]:
    """The typed rules and notes for one page. Chunked like the slots.

    One sentence may yield several rules -- a range, two units, a note beside
    the rules that cleared the bar -- each carrying its sentence and `figure`.
    """
    rules: list[Rule] = []
    for start in range(0, len(slots), CHUNK):
        chunk = slots[start : start + CHUNK]
        questions = value_questions(candidates, chunk)
        answers: dict[str, Answer] = (
            _ask(value_state(candidates, chunk), questions, decision="D6.values",
                 language=language, budget=budget, record=record, client=client)
            if questions else {}
        )
        for slot in chunk:
            rules.extend(_rules_for(candidates, slot, answers))
    return tuple(rules)


def _below_bar(slot: Slotted) -> bool:
    return min(slot.document_confidence, slot.operation_confidence) < SLOT_BAR


# <!-- amended 2026-09-26: a typed draft in place of **dict (mypy --strict), and a
# sentence now yields a tuple of rules -->
@dataclass(frozen=True)
class _Draft:
    """One rule before its scope is settled: a figure, or the one value a
    non-limit operation states."""

    operation: Operation
    value: object
    confidence: float
    note: str = ""
    unit: str = ""
    bound: str = ""
    detail: str = ""
    # <!-- reconciled 2026-09-26: Rule's own types -->
    figure: int | None = None
    excl_spaces: bool = False


def _rules_for(
    candidates: Sequence[Candidate], slot: Slotted, answers: Mapping[str, Answer]
) -> tuple[Rule, ...]:
    i = slot.index
    candidate = candidates[i]

    if slot.document == "other" and slot.document_confidence >= SLOT_BAR:
        # Fees, deadlines, transcripts. Not this reader's business, and not a
        # note either -- a note on every unrelated sentence is noise that hides
        # the notes that matter.
        return ()
    if _below_bar(slot):
        return (Rule(
            index=i, document=slot.document, operation=slot.operation, value=None,
            sentence=candidate.text, heading=candidate.heading, note="unsure",
            confidence=min(slot.document_confidence, slot.operation_confidence),
            probabilities=(("document", slot.document_confidence),
                           ("operation", slot.operation_confidence)),
        ),)

    if slot.operation == "limit":
        drafts = _limit_drafts(candidate, slot, answers)
    else:
        value, unit, detail, confidence, note = _value(candidate, slot, answers)
        drafts = [_Draft(slot.operation, value, confidence, note, unit=unit, detail=detail)]

    condition, scope_note = "", ""
    if slot.conditional:
        chosen = answers.get(f"{i}:condition")
        condition = str(chosen.value) if chosen else "other"
        if condition == "other" or (chosen is not None and chosen.confidence < SLOT_BAR):
            scope_note = "conditional"
    rules: list[Rule] = []
    for draft in drafts:
        note = draft.note or scope_note
        if not note and slot.third_party:
            note = "third_party"
        if not note and not _has_sink(slot.document, draft):
            note = "unapplied"
        rules.append(Rule(
            index=i, document=slot.document, operation=draft.operation, value=draft.value,
            sentence=candidate.text, heading=candidate.heading, unit=draft.unit,
            bound=draft.bound, detail=draft.detail, figure=draft.figure,
            # <!-- reconciled 2026-09-26 -->
            excl_spaces=draft.excl_spaces,
            confidence=draft.confidence, note=note, condition=condition,
        ))
    return tuple(rules)


def _has_sink(document: str, draft: _Draft) -> bool:
    if draft.operation == "limit":
        return bool(limit_sink(document, draft.bound, draft.unit,
                               # <!-- reconciled 2026-09-26 -->
                               excl_spaces=draft.excl_spaces))
    return bool(sink_for(document, draft.operation, draft.unit or draft.value))


# <!-- amended 2026-09-26: addendum §6.1, §6.5 -->
# <!-- reconciled 2026-09-26: the note is a per-figure bound (NOTE_BOUNDS), so a
# sentence's cap survives beside its second statement; excl_spaces is a boolean -->
def _limit_drafts(
    candidate: Candidate, slot: Slotted, answers: Mapping[str, Answer]
) -> list[_Draft]:
    """One draft per figure the sentence states as a length, at most one topic
    for the figures that are a section's or another statement's length, and at
    most one note for the figures it could not settle and one for what no sink
    holds.

    Nothing here combines figures. There is no min() of a range: "300–500 words"
    is a floor and a cap, and "3,500 characters (approximately 500 words)" is
    two caps (addendum §6.1). The number is always the figure code found.
    """
    i = slot.index
    drafts: list[_Draft] = []
    doubt: float | None = None
    no_sink_unit = False
    noted = False
    for k, figure in enumerate(figures_on_line(candidate.text)):
        bound = answers.get(f"{i}:figure:{k}:bound")
        unit = answers.get(f"{i}:figure:{k}:unit")
        if bound is None or unit is None:
            continue
        if bound.value == "not_a_limit":
            if bound.confidence < _NOT_A_LIMIT_BAR:
                doubt = bound.confidence if doubt is None else min(doubt, bound.confidence)
            continue
        if bound.value in NOTE_BOUNDS:
            if bound.confidence < SLOT_BAR:
                doubt = bound.confidence if doubt is None else min(doubt, bound.confidence)
                continue
            if not noted:
                # Addendum §6.5: a section's length or another statement's.
                # Kept as ONE topic carrying its sentence, whatever the unit, so
                # the letter writer reads it and the document carries it;
                # nothing enforces it (§10). Never a cap or a floor.
                noted = True
                drafts.append(_Draft("topic", candidate.text, bound.confidence,
                                     bound=str(bound.value), figure=k))
            continue
        confidence = min(bound.confidence, unit.confidence)
        if confidence < SLOT_BAR:
            doubt = confidence if doubt is None else min(doubt, confidence)
            continue
        if unit.value not in UNITS:
            # A length in a unit nothing holds: megabytes, lines, minutes.
            no_sink_unit = True
            continue
        if not _plausible(figure.number, str(bound.value), str(unit.value)):
            continue
        spaces = answers.get(f"{i}:figure:{k}:spaces")
        excluded = (
            unit.value == "characters" and spaces is not None
            and spaces.value is False and spaces.confidence >= SLOT_BAR
        )
        drafts.append(_Draft(
            "limit", figure.number, confidence, unit=str(unit.value), bound=str(bound.value),
            figure=k, excl_spaces=excluded,
        ))
    if doubt is not None:
        drafts.append(_Draft("limit", None, doubt, "unsure"))
    if no_sink_unit or not drafts:
        # A length sentence that yields no length -- "keep it short", or every
        # figure a year -- still stated a requirement. Shown, never dropped.
        drafts.append(_Draft("limit", None, slot.operation_confidence, "unapplied"))
    return drafts


def _plausible(number: int | float, bound: str, unit: str) -> bool:
    """derive.py's two plausibility bands, unchanged: a cap below the smallest
    any programme states, or any figure above the largest, is a misread digit.
    Only that figure drops; the default applies in its place."""
    key = "chars" if unit == "characters" else unit
    if number > _IMPLAUSIBLE_MAX[key]:
        logger.warning("ignoring an implausible %s %s of %s on a programme page",
                       key, bound, number)
        return False
    if bound != "minimum" and number < _IMPLAUSIBLE_CAP[key]:
        logger.warning("ignoring an implausible %s cap of %s on a programme page", key, number)
        return False
    return True


def _value(
    candidate: Candidate, slot: Slotted, answers: Mapping[str, Answer]
) -> tuple[object, str, str, float, str]:
    """The typed value, its unit, its detail, its confidence, and a note if it
    cannot stand. Every operation but `limit`, which `_limit_drafts` reads."""
    i = slot.index
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
    # <!-- reconciled 2026-09-26: form and naming read like include -->
    if slot.operation in ("include", "emphasise", "form", "naming"):
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


def _style_value(answers: Mapping[str, Answer], i: int) -> tuple[object, str, str, float, str]:
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


# <!-- amended 2026-09-26: the original counted a phrasing below the bar as a vote and
# read required + preferred as agreement, so its own two tests failed: two phrasings at
# the bar plus one below were "unsure", and three different verdicts applied one -->
def _format_value(answers: Mapping[str, Answer], i: int) -> tuple[object, str, str, float, str]:
    """Three phrasings in one request; act when two of three agree AT THE BAR
    (spec §6.2). Anything less is the `phrasing` note, and the CV renders `any`.

    A Noul and a Choice on the same question are not guaranteed to agree
    (TypeSafe's own docs), which is exactly why their agreement is information.
    `europass_required` and `europass_preferred` are different verdicts, not an
    agreement: reading them as one is how a recommendation became a mandate.
    """
    choice = answers.get(f"{i}:format")
    noul = answers.get(f"{i}:format_noul")
    applicant = answers.get(f"{i}:format_applicant")
    if choice is None or noul is None or applicant is None:
        return None, "", "", 0.0, "unapplied"
    votes = [
        (str(choice.value), choice.confidence),
        ("europass_required" if noul.value else "not_europass", noul.confidence),
        (str(applicant.value), applicant.confidence),
    ]
    at_bar = Counter(verdict for verdict, confidence in votes if confidence >= SLOT_BAR)
    agreed, count = at_bar.most_common(1)[0] if at_bar else ("", 0)
    if count < 2 or agreed not in FORMAT_VERDICTS:
        return str(choice.value), "", "", choice.confidence, "phrasing"
    confidence = min(c for verdict, c in votes if verdict == agreed and c >= SLOT_BAR)
    return agreed, "", "", confidence, ""


_TARGET_QUESTION = {
    "include": "Which piece of information must the document contain?",
    "order": "Which section must be ordered?",
    "emphasise": "Which section must be foregrounded?",
    # <!-- reconciled 2026-09-26: addendum §6.3 -->
    "form": "What kind of text must the letter be?",
    "naming": "Must, may or must not the letter name a prospective supervisor?",
}

#: Each with `none`: the vendor's rule is an escape option whenever the list
#: may not cover the input, and a directive forced onto the wrong field is
#: worse than one marked unapplied. `none` has no sink, so it falls through
#: to `unapplied` with the sentence kept.
_TARGET_OPTIONS: dict[str, tuple[str, ...]] = {
    "include": (*_INCLUDE_TARGETS, "none"),
    "order": (*_ORDER_TARGETS, "none"),
    "emphasise": (*_SECTIONS, "none"),
    # <!-- reconciled 2026-09-26 -->
    "form": (*FORM_VALUES, "none"),
    "naming": (*NAMING_VALUES, "none"),
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

(Strip the `# <!-- amended ... -->` marker lines when pasting.)

- [ ] **Step 9: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_values.py -v`
Expected: 36 passed (33 tests; three parametrised, over 2 cases each) <!-- reconciled 2026-09-26 -->

- [ ] **Step 10: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean. `I001` on the `.grammar` import block → `uv run ruff check --fix apps/documents/grammar_values.py`.

- [ ] **Step 11: Commit**

<!-- reconciled 2026-09-26: the message names note bounds, tolerance and form/naming -->

```bash
git -C "$WT" add apps/documents/grammar_values.py tests/documents/test_grammar_values.py
uv run git -C "$WT" commit -m "feat: the grammar's second request -- one decision per figure

Only the operations a page states get value questions, which keeps the 48
format examples on format sentences and the state inside the 64k ceiling.

A length is no longer one number picked from a list. Code finds every figure
with the unit printed beside it, and one Choice per figure says what it is --
a cap, a floor, an approximation, or not a limit. So '300-500 words' is a
floor and a cap rather than the floor read as the cap, '3,500 characters
(approximately 500 words)' is two caps, and a year is asked about and answered
rather than guessed away. The number is always the figure code found. A
per-section cap or a second statement's length is a note bound and goes to
the writer as a topic with its sentence, beside any cap the same sentence
states; a tolerance sentence is a topic by operation and no figure of it is
asked. Nothing yet enforces those. The letter's form and naming are each a
Choice over their closed values.

The format verdict asks three phrasings in one request and acts on two of
three. A third-party sentence, an unevaluable condition and an operation with
no sink each produce a note that keeps the sentence and applies nothing.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Conflicts, and the safer value

<!-- amended 2026-09-26: addendum §6.1 -- a cap and a floor are different sides; the safer
side is the smaller cap and the LARGER floor; three crashes fixed (stale item 5) -->

**Files:**
- Create: `apps/documents/rule_sinks.py`
- Test: `tests/documents/test_rule_conflicts.py`

**Interfaces:**
- Consumes: `grammar.Rule` (with `bound`, `figure`, `excl_spaces`) <!-- reconciled 2026-09-26 -->
- Produces: `resolve_conflicts(rules) -> tuple[Rule, ...]` — signature unchanged

Spec §6.3: two rules on the same `(document, operation)` for one programme — two sentences, one
sentence's two figures, or the page and its PDF — both at the bar with different values is a
**conflict**. Every side becomes a note and **the safer value applies**: the smaller cap, the
larger floor, `any` for format. A cap and a floor are never a conflict with each other — a range
is both — and two caps in different units, or a CV character cap with and without spaces, are
different keys downstream. Nothing waits for anyone.

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


def test_two_floors_keep_the_larger_one():
    """A floor's safe side is the other way round: shipping under a stated
    minimum is a rejection (HBKU, M-091)."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 300, unit="words", bound="minimum", document="motivation_letter"),
        _rule(1, "limit", 500, unit="words", bound="minimum", document="motivation_letter"),
    ))
    assert [r.value for r in resolved if r.applied] == [500]
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_a_range_is_a_floor_and_a_cap_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "limit", 300, unit="words", bound="minimum", figure=0,
              document="motivation_letter"),
        _rule(0, "limit", 500, unit="words", bound="maximum", figure=1,
              document="motivation_letter"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0
    assert sorted(r.value for r in resolved if r.applied) == [300, 500]


def test_a_word_limit_and_a_page_limit_are_not_a_conflict():
    """Different units are different keys downstream (max_words vs max_pages),
    so both stand."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages"),
        _rule(1, "limit", 800, unit="words"),
    ))
    assert sorted(r.value for r in resolved if r.applied) == [2, 800]


def test_a_cap_in_each_unit_from_one_sentence_is_not_a_conflict():
    resolved = resolve_conflicts((
        _rule(0, "limit", 3500, unit="characters", bound="maximum", figure=0,
              document="motivation_letter"),
        _rule(0, "limit", 500, unit="words", bound="approximate", figure=1,
              document="motivation_letter"),
    ))
    assert sorted(r.value for r in resolved if r.applied) == [500, 3500]


def test_one_sentences_two_caps_in_one_unit_resolve_and_keep_their_figures():
    """'At most two pages, ideally one' -- an approximation is read as a cap, so
    the smaller applies; each note names its own figure, so the two notes stay
    two rules downstream."""
    resolved = resolve_conflicts((
        _rule(0, "limit", 2, unit="pages", bound="maximum", figure=0),
        _rule(0, "limit", 1, unit="pages", bound="approximate", figure=1),
    ))
    assert [r.value for r in resolved if r.applied] == [1]
    assert {(r.index, r.figure) for r in resolved if r.note == "conflict"} == {(0, 0), (0, 1)}


def test_a_decimal_page_cap_is_a_number_like_any_other():
    resolved = resolve_conflicts((
        _rule(0, "limit", 1.5, unit="pages"),
        _rule(1, "limit", 2, unit="pages"),
    ))
    assert [r.value for r in resolved if r.applied] == [1.5]


def test_a_cv_cap_with_and_without_spaces_are_two_keys():
    resolved = resolve_conflicts((
        # <!-- reconciled 2026-09-26: the spaces reading is Rule.excl_spaces -->
        _rule(0, "limit", 4000, unit="characters", excl_spaces=True),
        _rule(1, "limit", 4500, unit="characters"),
    ))
    assert sum(r.note == "conflict" for r in resolved) == 0


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


def test_two_europass_verdicts_that_differ_apply_nothing_and_never_crash():
    """No sentence stated `any`, so no rule carries it: the conflict notes are
    all that is left, and format_decision reads them as any + UNDECIDED."""
    resolved = resolve_conflicts((
        _rule(0, "format", "europass_required"),
        _rule(1, "format", "europass_preferred"),
    ))
    assert [r for r in resolved if r.applied] == []
    assert sum(r.note == "conflict" for r in resolved) == 2


def test_two_language_rules_that_differ_do_not_crash_on_a_list():
    resolved = resolve_conflicts((
        _rule(0, "language", ["en", "fr"]),
        _rule(1, "language", "de"),
    ))
    assert [r for r in resolved if r.applied] == []
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

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rule_conflicts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.documents.rule_sinks'`

- [ ] **Step 3: Write the resolver**

```python
# apps/documents/rule_sinks.py
"""Typed rules in, the sinks the engine already has out.

Design: docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md §6,
amended by 2026-09-26-requirement-reader-addendum-design.md §6.1.

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

#: A format the page contradicts itself about falls back to `any`, the
#: no-egress default: a page that cannot make up its mind about Europass must
#: never resolve to the one action that moves student data (spec §6.2, §14).
_FORMAT_SAFE = "any"

# <!-- reconciled 2026-09-26: the last member is Rule.excl_spaces -->
Bucket = tuple[str, str, str, str, bool]


# <!-- amended 2026-09-26: the side (cap or floor) and the spaces reading are part
# of what two rules must share to contradict each other -->
def _bucket(rule: Rule) -> Bucket:
    """What a rule would have to match to contradict another.

    For a limit: the unit, because max_words and max_pages are different keys;
    the side, because a range's floor and cap are both true at once; and the
    CV's spaces reading, because max_chars_incl_spaces and max_chars_excl_spaces
    are different keys too. An approximation is a cap (grammar.BOUNDS). A
    NOTE_BOUNDS figure never reaches here: it is a `topic`, which is set-valued.
    """
    if rule.operation == "limit":
        side = "floor" if rule.bound == "minimum" else "cap"
        # <!-- reconciled 2026-09-26 -->
        return (rule.document, rule.operation, rule.unit, side, rule.excl_spaces)
    return (rule.document, rule.operation, "", "", False)


def _comparable(value: object) -> object:
    """A language rule allowing two languages is a list; compare it as a tuple."""
    return tuple(value) if isinstance(value, list) else value


def _safer(bucket: Bucket, values: set[object]) -> object:
    """The value that cannot break what the page requires, or None when no
    ordering makes one safer."""
    _, operation, _, side, _ = bucket
    if operation == "limit":
        # A cap: the smaller -- a letter inside two pages is inside three, and
        # the reverse gets an application rejected. A floor: the larger, for
        # the mirror reason (addendum §6.1).
        numbers = [v for v in values if isinstance(v, int | float)]
        return max(numbers) if side == "floor" else min(numbers)
    if operation == "format":
        return _FORMAT_SAFE
    # `language` and `order`: no ordering makes one safer, so the page states
    # nothing this engine can act on. The notes carry every side.
    return None


def resolve_conflicts(rules: Sequence[Rule]) -> tuple[Rule, ...]:
    """Apply the safer value where a page contradicts itself; note every side.

    Only rules that are AT the bar can contradict each other. One already
    carrying a note is not asserting anything, so counting it would turn one
    uncertain sentence into two notes and hide the certain rule beside it.
    """
    applied: dict[Bucket, list[Rule]] = defaultdict(list)
    for rule in rules:
        if rule.applied and rule.operation in _SINGLE_VALUED:
            applied[_bucket(rule)].append(rule)

    disputed: dict[Bucket, object] = {}
    for bucket, group in applied.items():
        values = {_comparable(r.value) for r in group}
        if len(values) <= 1:
            continue
        disputed[bucket] = _safer(bucket, values)
        logger.info("conflicting %s rules %s; applying %r", bucket[1],
                    sorted(map(str, values)), disputed[bucket])

    resolved: list[Rule] = []
    settled: set[Bucket] = set()
    for rule in rules:
        bucket = _bucket(rule)
        if not (rule.applied and bucket in disputed):
            resolved.append(rule)
            continue
        # Every side of the dispute becomes a note carrying its own sentence.
        resolved.append(replace(rule, note="conflict"))
        if bucket in settled:
            continue
        settled.add(bucket)
        # The safer value may be one no sentence stated -- `any` between two
        # Europass verdicts -- and then nothing is applied: the notes are the
        # whole answer, and format_decision reads them as any + UNDECIDED.
        winner = next(
            (r for r in applied[bucket] if _comparable(r.value) == disputed[bucket]), None
        )
        if winner is not None:
            resolved.append(replace(winner, note=""))
    return tuple(resolved)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rule_conflicts.py -v`
Expected: 16 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest`
Expected: all clean

- [ ] **Step 6: Commit**

```bash
git -C "$WT" add apps/documents/rule_sinks.py tests/documents/test_rule_conflicts.py
uv run git -C "$WT" commit -m "feat: conflicts resolve to the safer side and note every side

A page that contradicts itself is common and is not a reason to stop: the
smaller cap applies, the larger floor applies, and a contradicted format falls
back to \`any\` -- the no-egress default, because a page that cannot make up its
mind about Europass must never resolve to the one action that moves student
data. Every sentence is on the document. A cap and a floor are never a
conflict with each other, since a range is both, and two units or the CV's two
spaces readings are different keys. Only a rule at the bar can contradict
another; a note asserts nothing.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


### Task 8: The CV's projection — constraint rules, directives, and the format switch

**Files:**
- Modify: `apps/documents/rule_sinks.py`
- Test: `tests/documents/test_rule_sinks_cv.py`

**Interfaces:**
- Consumes: `grammar.{Rule, sink_for, limit_sink}` (with Task 4's `Rule.bound`, `Rule.excl_spaces`), `constraints.{ConstraintRule, Enforcement, check_directive_shape}`, `funding.models.Program` <!-- reconciled 2026-09-26: limit_sink -->
- Produces: `to_constraint_rules(rules, *, source_url) -> tuple[ConstraintRule, ...]`, `to_directives(rules, *, source_url) -> tuple[dict[str, object], ...]`, `to_notes(rules, *, source_url) -> tuple[ConstraintRule, ...]`, `format_decision(rules) -> tuple[str, str]`, `cv_limit_key(rule) -> str`

Every derived rule is `ADVISORY_HIGH_RISK`. A note lands as an `undecided` or `unapplied` constraint rule, the two `_MULTI_KEYS` that carry a quote rather than a value. `resolve_rules` keeps one per sentence and `render_cv_with_warnings` shows them to the counsellor. <!-- amended 2026-09-26: addendum §6.1 --> **Every figure is its own rule.** The CV has caps and no floor key, so a CV floor is stated and `unapplied`. <!-- reconciled 2026-09-26 --> A section-limit or another-statement figure reaches here as a `topic` that Task 6 already marked `unapplied` on the CV, and a tolerance sentence is a `topic` by operation. None of them becomes the cap and none is dropped.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rule_sinks_cv.py
import pytest

from apps.documents.constraints import Enforcement, resolve_rules
from apps.documents.grammar import Rule
from apps.documents.rule_sinks import (
    cv_limit_key,
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


# <!-- amended 2026-09-26: addendum §6.1, per-figure bounds -->
def test_a_character_cap_counted_without_spaces_reaches_its_own_key():
    rules = to_constraint_rules(
        (_rule(0, "limit", 3000, unit="characters", bound="maximum", excl_spaces=True),),
        source_url=_URL,
    )
    assert rules[0].key == "max_chars_excl_spaces"


def test_an_approximate_figure_is_a_cap():
    rules = to_constraint_rules(
        (_rule(0, "limit", 2, unit="pages", bound="approximate"),), source_url=_URL
    )
    assert (rules[0].key, rules[0].value) == ("max_pages", 2)


def test_a_range_on_a_cv_is_its_cap_plus_an_unapplied_note_for_its_floor():
    """Addendum §6.1: every figure is its own decision. The CV has no floor key,
    so the floor is stated and unapplied -- never read as the cap, never dropped."""
    rules = (
        _rule(0, "limit", 1, unit="pages", bound="minimum", sentence="One to two pages."),
        _rule(0, "limit", 2, unit="pages", bound="maximum", sentence="One to two pages."),
    )
    assert [(r.key, r.value) for r in to_constraint_rules(rules, source_url=_URL)] == [
        ("max_pages", 2)
    ]
    assert [(n.key, n.rule_text) for n in to_notes(rules, source_url=_URL)] == [
        ("unapplied", "One to two pages.")
    ]
    assert cv_limit_key(rules[0]) == ""


def test_two_uncertain_figures_in_one_sentence_are_one_note():
    """The quote is the note; two figures of one sentence share it."""
    notes = to_notes((
        _rule(0, "limit", 1, unit="pages", bound="minimum", note="unsure",
              sentence="One or two pages."),
        _rule(0, "limit", 2, unit="pages", bound="maximum", note="unsure",
              sentence="One or two pages."),
    ), source_url=_URL)
    assert len(notes) == 1


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

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rule_sinks_cv.py -v`
Expected: FAIL with `ImportError: cannot import name 'cv_limit_key'`

- [ ] **Step 3: Write the projection**

```python
# apps/documents/rule_sinks.py -- add these imports at the top
from apps.funding.models import Program

from .constraints import ConstraintRule, Enforcement, check_directive_shape
from .grammar import limit_sink, sink_for
```

<!-- reconciled 2026-09-26 --> Merge that last line into Task 7's `from .grammar import Rule`, giving
`from .grammar import Rule, limit_sink, sink_for` (one import per module, or ruff reports `I001`).

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

# <!-- amended 2026-09-26: addendum §6.1 -- every figure is its own rule -->
# <!-- reconciled 2026-09-26: one mapping, grammar.limit_sink, instead of a second one here -->
def cv_limit_key(rule: Rule) -> str:
    """The constraint key a CV length figure writes, or "" when it is not a cap.

    `""` as the bound is a limit rule written before bounds existed, read as a
    cap; `approximate` is a cap, as the letter path always has read it. The CV
    has no floor key, so a floor is a real statement nothing downstream
    carries: `unapplied`.
    """
    return limit_sink("cv", rule.bound or "maximum", rule.unit, excl_spaces=rule.excl_spaces)


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
                              "topic", "student_action", "form", "naming", "other"):
            continue
        key = (
            cv_limit_key(rule) if rule.operation == "limit"
            else sink_for("cv", rule.operation, rule.value)
        )
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


# <!-- reconciled 2026-09-26: a note-bound figure is a topic by now; only a floor is here -->
def to_notes(rules: Sequence[Rule], *, source_url: str) -> tuple[ConstraintRule, ...]:
    """Every note, as the `undecided` or `unapplied` rule the counsellor reads.

    These are constraints._MULTI_KEYS: they carry a QUOTE rather than a value,
    have no checker, and `render_cv_with_warnings` puts them in front of a
    person with the page's own words. The rule_id names the sentence AND the
    kind, because one sentence can be undecided about several things at once and
    resolve_rules slots these by id -- a shared id silently drops all but one.

    An APPLIED CV figure that is not a cap (a floor) is a note too: the page
    stated it and no CV key carries it. A section limit or another statement
    arrives as a `topic` Task 6 already marked `unapplied`. And one sentence gets one note per kind -- its
    figures share the quote, so a second would say the same thing twice.
    """
    built: list[ConstraintRule] = []
    seen: set[tuple[int, str]] = set()
    for rule in rules:
        if rule.document == "other":
            continue
        if rule.applied:
            if not (rule.document == "cv" and rule.operation == "limit"
                    and not cv_limit_key(rule)):
                continue
            kind = "unapplied"
        else:
            kind = rule.note
        if (rule.index, kind) in seen:
            continue
        seen.add((rule.index, kind))
        built.append(ConstraintRule(
            rule_id=f"PAGE-{rule.index}-{kind[:9]}",
            key="unapplied" if kind == "unapplied" else "undecided",  # type: ignore[arg-type]
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
    if unsettled or any(str(r.value) == "other_template" for r in verdicts):
        return Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.UNDECIDED
    return Program.CVFormatRequirement.ANY, Program.CVFormatConfidence.EXTRACTED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rule_sinks_cv.py -v`
Expected: 20 passed

- [ ] **Step 5: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config`
Expected: both clean

- [ ] **Step 6: Commit**

<!-- reconciled 2026-09-26: the message says a section limit, not a per-section figure -->

```bash
git -C "$WT" add apps/documents/rule_sinks.py tests/documents/test_rule_sinks_cv.py
uv run git -C "$WT" commit -m "feat: the CV's projection -- constraint keys, directives, the format switch

Every derived rule is ADVISORY_HIGH_RISK without exception: a classifier answer
can make a rule say 'required' and can never make one bind. A style value
carries its polarity, so photo_forbidden is photo_allowed=False rather than a
silently inverted funder rule. Notes land as the two keys that carry a quote
instead of a value, one per sentence and kind, because resolve_rules slots
them by id and a shared one drops all but the first.

Every figure is its own rule. A CV floor, a section limit or a tolerance has
no key, so it is an unapplied note -- never the cap, never dropped.

A page stating no format rule writes any + EXTRACTED; anything unsettled
writes any + UNDECIDED, the no-egress default.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The letter's projection — one `LetterShape`, every typed field kept

<!-- amended 2026-09-26: addendum §6.1-§6.5. The 2026-09-23 Task 9 wrote nine of the fifteen
LetterShape fields. The five the frontier path types and the grammar lost (form, naming,
document_required, track, portfolio_led) are back. The letter's language reaches
ApplicationPrompt.document_language, floors get their sinks, and tolerances, per-section caps and
second statements become written requirements. -->

**Files:**
- Modify: `apps/documents/rule_sinks.py`, `apps/documents/grammar_questions.py`, `apps/documents/letter_shape.py`, `apps/documents/derive.py` (a move, no behaviour change), `apps/funding/requirements.py`
- Test: `tests/documents/test_rule_sinks_letter.py` (new), `tests/documents/test_grammar_page.py` (new), `tests/documents/test_letter_shape.py`, `tests/funding/test_requirements.py`

**Interfaces:**
- Consumes: `grammar.{Rule, Slotted, limit_sink, _IMPLAUSIBLE_CAP, _IMPLAUSIBLE_MAX}`, `grammar_questions.{SLOT_BAR, slot_state, _ask}`, `decisions.{Choice, Noul, Question, DecisionBudget}`, `grammar_questions.AskFn`, `LetterShape.min_chars` and `ApplicationPrompt.letter_min_chars` (Tasks 4–7) <!-- reconciled 2026-09-26 -->
- Produces:
  - `grammar_questions.PageFacts(letter_required: str = "UNSTATED", track: str = "", portfolio_led: bool = False)`
  - `grammar_questions.page_questions() -> dict[str, Question]`
  - `grammar_questions.read_page_facts(candidates, slots, *, language="", budget=None, client: AskFn | None = None, record=True) -> PageFacts`
  - `rule_sinks.letter_field(rule) -> tuple[str, object] | None`
  - `rule_sinks.to_letter_shape(rules, *, source_url, page=None) -> LetterShape`
  - `LetterShape.document_language: str = ""`
  - `letter_shape.{_SAFE_FONT_FAMILY, _naming_decision, _form_decision}` (moved from `derive`, re-imported there). The plausibility bands are NOT moved here: Task 4 already moved them to `grammar.py`. <!-- reconciled 2026-09-26 -->

`apply_derived_shape` keeps its signature. It gains one write: `document_language`, when the page stated it.

**The five fields the frontier path types, and where each now comes from:**

| field | grammar source | safer side (shared with the frontier path) |
|---|---|---|
| `form` | operation `form`, per sentence | `_form_decision`: FORMAL_LETTER over ESSAY, PORTAL_FORM only unopposed |
| `naming` | operation `naming`, per sentence | `_naming_decision`: FORBIDDEN wins, REQUIRED only unanimous |
| `document_required` | page-level Choice (addendum §6.3: D4's page-level question, extended to the letter) | written only with a letter sentence as its witness |
| `track` | page-level Choice | blank when unsure; blank resolves as `taught` at use |
| `portfolio_led` | page-level Noul | set only at the bar |

The page-level questions are one request per page, asked only when some sentence is the
applicant's own letter at the bar, which is when the frontier path would have typed them. Plan 2's
D4 asks the CV's version of the same question. Folding this one into D4 is plan 2's call and
changes nothing here: `PageFacts` is the seam.

- [ ] **Step 0: Check the prerequisites from Tasks 4–7**

```bash
grep -n "form\|naming\|NOTE_BOUNDS\|bound: str\|excl_spaces" apps/documents/grammar.py
grep -n "min_chars" apps/documents/letter_shape.py apps/funding/models.py
```

Expected: `grammar.py` shows `"form"`, `"naming"` in `Operation`, `NOTE_BOUNDS`, `bound: str = ""`
and `excl_spaces: bool = False` <!-- reconciled 2026-09-26 --> (and `FORM_VALUES`, `NAMING_VALUES`). `letter_shape.py` shows `min_chars` on `LetterShape`, in
`apply_derived_shape` and in `shape_from_prompt`, and `models.py` shows `letter_min_chars`. If any
is missing, stop. It belongs to Tasks 4–7, and adding it here would fork the vocabulary.

- [ ] **Step 1: Write the failing tests**

```python
# tests/documents/test_rule_sinks_letter.py
import pytest

from apps.documents.grammar import Rule
from apps.documents.grammar_questions import PageFacts
from apps.documents.letter_shape import LetterShape
from apps.documents.rule_sinks import letter_field, to_letter_shape

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


# <!-- amended 2026-09-26: addendum §6.1, §6.2 -->
def test_a_range_is_a_floor_and_a_cap_never_the_floor_as_the_cap():
    """"300-500 words" -- the measured defect: a verdict held one length, so
    every range lost its floor."""
    sentence = "Submit a personal statement (300-500 words)."
    shape = to_letter_shape((
        _rule(0, "limit", 300, unit="words", bound="minimum", sentence=sentence),
        _rule(0, "limit", 500, unit="words", bound="maximum", sentence=sentence),
    ), source_url=_URL)
    assert (shape.min_words, shape.max_words) == (300, 500)
    assert shape.sources["min_words"]["text"] == sentence


def test_a_character_floor_lands_on_min_chars():
    """Kassel rejects a letter under 2,800 characters (addendum §6.2)."""
    shape = to_letter_shape(
        (_rule(0, "limit", 2800, unit="characters", bound="minimum"),), source_url=_URL
    )
    assert shape.min_chars == 2800


def test_two_caps_in_two_units_are_both_kept():
    """"3,500 characters (approximately 500 words)" is two caps."""
    sentence = "3,500 characters (approximately 500 words)."
    shape = to_letter_shape((
        _rule(0, "limit", 3500, unit="characters", bound="maximum", sentence=sentence),
        _rule(0, "limit", 500, unit="words", bound="approximate", sentence=sentence),
    ), source_url=_URL)
    assert (shape.max_chars, shape.max_words) == (3500, 500)


def test_a_character_cap_counted_without_spaces_is_held_as_the_stricter_inclusive_cap():
    shape = to_letter_shape(
        (_rule(0, "limit", 3000, unit="characters", bound="maximum", excl_spaces=True),),
        source_url=_URL,
    )
    assert shape.max_chars == 3000


# <!-- reconciled 2026-09-26: min_chars IS measured without spaces (Task 4 Part A,
# key min_chars_excl_spaces), so a floor stated without spaces lands on it exactly -->
def test_a_page_floor_is_a_written_requirement_and_a_floor_without_spaces_is_min_chars():
    """A floor in pages has no column and nothing measures one, so it reaches the
    writer unenforced. A character floor is always checked without spaces (the
    stricter reading), so "2,000 characters without spaces" is min_chars as stated."""
    shape = to_letter_shape((
        _rule(0, "limit", 1, unit="pages", bound="minimum", sentence="At least one page."),
        _rule(1, "limit", 2000, unit="characters", bound="minimum", excl_spaces=True,
              sentence="At least 2,000 characters without spaces."),
    ), source_url=_URL)
    assert [w["text"] for w in shape.written_requirements] == ["At least one page."]
    assert shape.min_chars == 2000


# <!-- reconciled 2026-09-26: Task 6 turns a note-bound figure into a topic, and a
# tolerance is a topic sentence with no bound at all -- never a limit rule -->
@pytest.mark.parametrize("bound,sentence", [
    ("", "An exceedance of more than 10 percent is not accepted."),
    ("section_limit", "Three parts of 400 words each."),
    ("another_statement", "A 250-word statement on your research interests."),
])
def test_what_no_sink_can_enforce_is_carried_as_a_written_requirement(bound, sentence):
    """Addendum §6.5: recorded as notes, not yet enforced -- the writer reads
    them and the document carries them. A tolerance lands here as a topic,
    never as a limit."""
    shape = to_letter_shape(
        (_rule(0, "topic", sentence, bound=bound, sentence=sentence),), source_url=_URL
    )
    assert shape.written_requirements == ({"text": sentence, "source_url": _URL},)
    assert (shape.max_words, shape.min_words, shape.max_chars, shape.max_pages) == (
        None, None, None, None
    )


def test_one_sentence_with_two_note_figures_is_one_written_requirement():
    sentence = "Three parts of 400 words each, within a 10 percent tolerance."
    # <!-- reconciled 2026-09-26: both arrive as topics carrying the same sentence -->
    shape = to_letter_shape((
        _rule(0, "topic", sentence, bound="section_limit", figure=0, sentence=sentence),
        _rule(0, "topic", sentence, bound="section_limit", figure=1, sentence=sentence),
    ), source_url=_URL)
    assert len(shape.written_requirements) == 1


def test_an_implausible_cap_is_dropped_and_the_default_applies():
    """_IMPLAUSIBLE_CAP, moved verbatim from derive: a six-word cap is a misread
    digit, and acting on it blocks every letter with nobody to see why."""
    shape = to_letter_shape((_rule(0, "limit", 6, unit="words"),), source_url=_URL)
    assert shape.max_words is None


def test_an_implausible_floor_is_dropped():
    shape = to_letter_shape(
        (_rule(0, "limit", 50_000, unit="words", bound="minimum"),), source_url=_URL
    )
    assert shape.min_words is None


def test_the_letters_language_is_a_shape_field_with_its_sentence():
    """Addendum §6.4: the `language` operation writes document_language."""
    shape = to_letter_shape(
        (_rule(0, "language", "de", sentence="Das Motivationsschreiben ist auf Deutsch."),),
        source_url=_URL,
    )
    assert shape.document_language == "de"
    assert shape.sources["document_language"]["text"] == "Das Motivationsschreiben ist auf Deutsch."


def test_a_letter_allowed_in_several_languages_takes_english_when_allowed():
    shape = to_letter_shape((_rule(0, "language", ["de", "en"]),), source_url=_URL)
    assert shape.document_language == "en"


def test_form_resolves_to_the_safer_side_with_the_frontier_paths_own_rule():
    """FORMAL_LETTER over ESSAY: it keeps the prose (derive._form_decision's
    rule, now shared from letter_shape so the two paths cannot disagree)."""
    shape = to_letter_shape((
        _rule(0, "form", "essay", sentence="Write an essay."),
        _rule(1, "form", "formal_letter", sentence="Address it to the committee."),
    ), source_url=_URL)
    assert shape.form == "FORMAL_LETTER"
    assert shape.sources["form"]["text"] == "Address it to the committee."


def test_a_portal_form_alone_is_a_portal_form():
    shape = to_letter_shape((_rule(0, "form", "portal_form"),), source_url=_URL)
    assert shape.form == "PORTAL_FORM"


def test_naming_forbidden_wins_and_required_needs_every_sentence():
    assert to_letter_shape((
        _rule(0, "naming", "invited"), _rule(1, "naming", "forbidden"),
    ), source_url=_URL).naming == "FORBIDDEN"
    assert to_letter_shape((
        _rule(0, "naming", "required"), _rule(1, "naming", "invited"),
    ), source_url=_URL).naming == "INVITED"
    assert to_letter_shape((_rule(0, "naming", "required"),), source_url=_URL).naming == "REQUIRED"


def test_document_required_track_and_portfolio_come_from_the_page():
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", sentence="Motivation letter, 800 words."),),
        source_url=_URL,
        page=PageFacts(letter_required="REQUIRED", track="research", portfolio_led=True),
    )
    assert shape.document_required == "REQUIRED"
    assert shape.sources["document_required"]["text"] == "Motivation letter, 800 words."
    assert (shape.track, shape.portfolio_led) == ("research", True)


def test_document_required_with_no_letter_sentence_to_witness_it_stays_unstated():
    """A flag with no sentence is a decision nobody can check (spec §6.4)."""
    shape = to_letter_shape(
        (_rule(0, "limit", 800, unit="words", document="reference_letter"),),
        source_url=_URL, page=PageFacts(letter_required="NOT_REQUIRED"),
    )
    assert shape.document_required == "UNSTATED"


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


def test_a_template_the_letter_must_use_is_a_student_action():
    shape = to_letter_shape(
        (_rule(0, "format", "other_template", sentence="Use the form provided."),),
        source_url=_URL,
    )
    assert shape.student_actions[0]["text"] == "Use the form provided."


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


def test_a_style_rule_reaches_the_shape_field_it_names():
    shape = to_letter_shape((
        _rule(0, "style", "signed_declaration"),
        _rule(1, "style", "handwritten"),
        _rule(2, "style", "font_size_minimum", detail="12"),
        _rule(3, "style", "line_spacing", detail="1.5"),
        _rule(4, "style", "margins", detail="2.5"),
    ), source_url=_URL)
    assert shape.signed_declaration is True and shape.handwritten is True
    assert (shape.font_min_pt, shape.line_spacing, shape.margins_cm) == (12, 1.5, 2.5)


def test_a_font_size_or_margin_outside_the_frontier_paths_range_is_dropped():
    """LetterVerdict bounded font_min_pt to 4..40 and margins_cm to 0.1..10; the
    grammar keeps both bounds rather than trusting a picked number more."""
    shape = to_letter_shape((
        _rule(0, "style", "font_size_minimum", detail="400"),
        _rule(1, "style", "margins", detail="25"),
    ), source_url=_URL)
    assert (shape.font_min_pt, shape.margins_cm) == (None, None)


def test_every_stated_field_records_where_it_came_from():
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


@pytest.mark.parametrize("family", ["Arial; } body { display:none", "Arial\n"])
def test_a_font_family_that_is_not_plain_latin_text_is_dropped(family):
    """The one field that is not a closed list. Never interpolate it into CSS
    unvalidated -- Django's autoescaping does not neutralise ';' or '{' inside
    a CSS value. fullmatch, not match: `$` matches before a trailing newline."""
    shape = to_letter_shape(
        (_rule(0, "style", "font_family", detail=family),), source_url=_URL,
    )
    assert shape.font_family is None


def test_letter_field_is_what_the_gate_scores():
    """Task 11 scores the 77-sentence eval through this function, so the gate
    measures the projection that ships."""
    assert letter_field(_rule(0, "limit", 500, unit="words", bound="minimum")) == (
        "min_words", 500
    )
    assert letter_field(_rule(0, "naming", "forbidden")) == ("naming", "forbidden")
    assert letter_field(_rule(0, "limit", 500, unit="words", note="unsure")) is None
```

```python
# tests/documents/test_grammar_page.py
import pytest

from apps.documents.derive import Candidate
from apps.documents.grammar import Slotted
from apps.documents.grammar_questions import PageFacts, page_questions, read_page_facts
from apps.research.decisions import Answer

pytestmark = pytest.mark.django_db

_FOUND = (
    Candidate(text="Your CV may not exceed two pages.", heading="Documents", europass=False),
    Candidate(text="A motivation letter of one page.", heading="Documents", europass=False,
              letter=True),
)


def _slot(index, document, confidence=0.97, third_party=False):
    return Slotted(index=index, document=document, document_confidence=confidence,
                   operation="limit", operation_confidence=0.97,
                   third_party=third_party, conditional=False)


def _client(script, asked):
    def call(state, questions, *, decision, language="", budget=None, record=True, client=None):
        asked.append(decision)
        return {
            qid: Answer(id=qid, value=script[qid][0], confidence=script[qid][1],
                        probabilities={str(script[qid][0]).lower(): script[qid][1]},
                        model="jev-1.13.0", provider="typesafe")
            for qid in questions
        }

    return call


def test_the_page_questions_have_an_escape_on_every_choice():
    questions = page_questions()
    assert set(questions) == {"letter_required", "track", "portfolio"}
    assert "unstated" in questions["letter_required"].options
    assert "unstated" in questions["track"].options


def test_a_page_with_no_applicant_letter_sentence_asks_nothing():
    """The frontier path typed these only from the applicant's own letter lines,
    so the grammar asks only then -- and a CV-only page costs no request."""
    asked: list[str] = []
    facts = read_page_facts(
        _FOUND, (_slot(0, "cv"), _slot(1, "motivation_letter", third_party=True)),
        client=_client({}, asked),
    )
    assert facts == PageFacts() and asked == []


def test_answers_at_the_bar_are_the_pages_facts():
    asked: list[str] = []
    facts = read_page_facts(
        _FOUND, (_slot(0, "cv"), _slot(1, "motivation_letter")),
        client=_client({
            "letter_required": ("required", 0.93), "track": ("research", 0.9),
            "portfolio": (True, 0.88),
        }, asked),
    )
    assert facts == PageFacts(letter_required="REQUIRED", track="research", portfolio_led=True)
    assert asked == ["D6.page"]


def test_answers_below_the_bar_are_unstated():
    asked: list[str] = []
    facts = read_page_facts(
        _FOUND, (_slot(1, "motivation_letter"),),
        client=_client({
            "letter_required": ("not_required", 0.6), "track": ("taught", 0.5),
            "portfolio": (True, 0.7),
        }, asked),
    )
    assert facts == PageFacts()
```

Append to `tests/documents/test_letter_shape.py`:

```python
@pytest.mark.django_db
def test_a_stated_letter_language_reaches_the_prompt_and_round_trips(program) -> None:
    """Addendum §6.4: the `language` operation writes document_language."""
    shape = LetterShape(
        max_words=500, document_language="de",
        sources={"document_language": {"text": "auf Deutsch", "source_url": "u"}},
    )
    prompt = apply_derived_shape(program, "2027", shape, source_url="https://x.example/p")
    assert prompt.document_language == "de"
    assert shape_from_prompt(prompt) == shape


@pytest.mark.django_db
def test_a_page_stating_no_language_leaves_the_prompts_language_alone(program) -> None:
    ApplicationPrompt.objects.create(
        programme=program, cycle="2027", confidence=0.0,
        source=ApplicationPrompt.Source.EXTRACTED,
        funder_kind=ApplicationPrompt.FunderKind.UNIVERSITY_ADMISSION,
        structure=ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        document_language="fr",
    )
    prompt = apply_derived_shape(
        program, "2027", LetterShape(max_words=500), source_url="https://x.example/p"
    )
    assert prompt.document_language == "fr"
    assert shape_from_prompt(prompt).document_language == ""


@pytest.mark.django_db
def test_a_new_prompt_starts_in_the_stated_language(program) -> None:
    prompt = apply_derived_shape(
        program, "2027", LetterShape(document_language="pt"), source_url="https://x.example/p"
    )
    assert prompt.document_language == "pt"


@pytest.mark.django_db
def test_a_character_floor_reaches_the_prompt(program) -> None:
    prompt = apply_derived_shape(
        program, "2027", LetterShape(min_chars=2800), source_url="https://x.example/p"
    )
    assert prompt.letter_min_chars == 2800
```

(`ApplicationPrompt` is already imported at the top of `test_letter_shape.py`; if it is not, add
`from apps.funding.models import ApplicationPrompt`.)

Append to `tests/funding/test_requirements.py`:

```python
@pytest.mark.django_db
def test_a_stated_letter_language_is_enforced_when_the_letter_is_written() -> None:
    """letter_gates.check_language_mismatch refuses a letter in another language
    before anything is rendered, so the pane must not say "enforced at render"."""
    from apps.funding.requirements import ENFORCED_WHEN_WRITTEN

    programme = _programme()
    prompt = _prompt(programme)
    prompt.document_language = "de"
    prompt.letter_shape_sources = dict(prompt.letter_shape_sources) | {
        "document_language": {"text": "Bitte auf Deutsch.", "source_url": "u"}
    }
    prompt.save(update_fields=["document_language", "letter_shape_sources"])
    panes = program_requirements(programme, cycle="2027")
    by_text = {item.text: item for item in panes.letter}
    assert by_text["Bitte auf Deutsch."].status == ENFORCED_WHEN_WRITTEN
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rule_sinks_letter.py tests/documents/test_grammar_page.py tests/documents/test_letter_shape.py tests/funding/test_requirements.py -v`
Expected: FAIL. Collection stops with `ImportError: cannot import name 'PageFacts'`, and
`TypeError: LetterShape.__init__() got an unexpected keyword argument 'document_language'` follows
once that is fixed.

- [ ] **Step 3: Move the letter's safer-side rules into `letter_shape.py`**

The frontier path keeps them. The grammar path needs them too, so they move to `letter_shape.py`,
the module whose own docstring states these rules, and `derive.py` imports them back. `rule_sinks`
then never imports `derive`, and the deferred cleanup is a pure deletion.

<!-- reconciled 2026-09-26: the plausibility bands are not moved again. Task 4 Part B already
moved them to grammar.py and derive.py imports them from there; rule_sinks imports them from
grammar too. -->

Re-resolve the lines first: `grep -n "^_SAFE_FONT_FAMILY\|^def _naming_decision\|^def _form_decision" apps/documents/derive.py`
(at `f5cfac6`: 951, 1031, 1064, less the 20 lines Task 4 removed above the latter two). Delete from
`derive.py`: `_SAFE_FONT_FAMILY` with its comment block (944–951), `_naming_decision` and
`_form_decision`. `_IMPLAUSIBLE_CAP` / `_IMPLAUSIBLE_MAX` are already gone from `derive.py` (Task 4)
and stay in `grammar.py`. `_document_required_decision` stays in `derive.py`: only the frontier
path uses it. Add to `letter_shape.py`, after `FILE_BUNDLES`:

```python
# apps/documents/letter_shape.py -- add `import re` to the imports, then after FILE_BUNDLES

#: Letters, digits, spaces, apostrophes and hyphens only -- every real font
#: name ("Times New Roman", "Liberation Sans", "O'Malley Serif") fits inside
#: it, and none of ";{}()/:" that would need to reach render.py's CSS to do
#: anything hostile does. font_family is the one LetterVerdict field that is
#: not a closed Literal (a page may legitimately name any font), so this is
#: the only place fabricated CSS injection can be stopped -- Django's
#: autoescaping does not neutralise ';' or '{' inside a CSS value.
_SAFE_FONT_FAMILY = re.compile(r"^[A-Za-z0-9 '\-]{1,60}$")


def _naming_decision(votes: list[str], n: int) -> str:
    """The naming verdict a vote LIST currently implies.

    FORBIDDEN always wins; REQUIRED needs unanimity across at least `n`
    votes; one vote either way is enough for INVITED. Shared between
    `decide_letter_shape`'s incremental source tracking (called after every
    vote, to see whether the ACCEPTED value just changed) and the final
    return value, so the two can never disagree with each other -- and, since
    2026-09-26, with the grammar's projection (rule_sinks.to_letter_shape).
    """
    if "forbidden" in votes:
        return "FORBIDDEN"
    if votes and len(votes) >= n and all(v == "required" for v in votes):
        return "REQUIRED"
    if "invited" in votes or "required" in votes:
        return "INVITED"
    return "UNSTATED"


def _form_decision(forms: set[str], portal_unanimous: bool) -> str:
    """Same sharing rationale as `_naming_decision`, for `form`.

    FORMAL_LETTER if any reading anywhere says letter -- it keeps the prose,
    which is the safer side. PORTAL_FORM only where every reading on one
    line said so, because a wrongly assumed form drops the letter's prose
    entirely.
    """
    if "formal_letter" in forms:
        return "FORMAL_LETTER"
    if portal_unanimous:
        return "PORTAL_FORM"
    if "portal_form" in forms:
        return "FORMAL_LETTER"
    return "ESSAY"
```

In `derive.py`, change `from .letter_shape import LetterShape, apply_derived_shape` to the block
below, and leave Task 4's `from .grammar import _IMPLAUSIBLE_CAP, _IMPLAUSIBLE_MAX` as it is:
<!-- reconciled 2026-09-26 -->

```python
from .letter_shape import (
    _SAFE_FONT_FAMILY,
    LetterShape,
    _form_decision,
    _naming_decision,
    apply_derived_shape,
)
```

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_letter_shape.py tests/documents/test_letter_derive.py -q`
Expected: the tests that existed before this task all pass. The move changes no behaviour, and the
four tests appended in Step 1 still fail.

- [ ] **Step 4: `LetterShape.document_language`, and `apply_derived_shape` writes it**

```python
# apps/documents/letter_shape.py -- LetterShape, after `portfolio_led`
    #: Addendum §6.4, the `language` operation. "" means the page did not say,
    #: and then nothing is written: the column belongs to whoever set it (the
    #: resolver, or the "en" a new row starts with). Set only with a sentence in
    #: `sources`, like every other field here.
    document_language: str = ""
```

In `apply_derived_shape`, after the `fields = {...}` literal:

```python
    if shape.document_language:
        # The page stated the letter's language. Unstated leaves the column
        # alone: a page that says nothing about language has not said "English".
        fields["document_language"] = shape.document_language
```

and change the create call's `document_language="en", **fields,` to
`**{"document_language": "en", **fields},` (a stated language would otherwise be passed twice).

In `shape_from_prompt`, add the last argument:

```python
        document_language=(
            prompt.document_language
            if "document_language" in prompt.letter_shape_sources else ""
        ),
```

`letter_shape_sources` decides because it is the one record of what the page said. A resolver's
`"en"` is a default, and a default that round-tripped into the shape would read as stated.

In `apps/funding/requirements.py`:

```python
#: Shape fields a gate enforces before any render. `document_language` is
#: letter_gates.check_language_mismatch, which refuses a letter in another
#: language before anything is rendered.
_GATE_FIELDS = {"naming", "document_language"}
```

- [ ] **Step 5: The page-level questions**

```python
# apps/documents/grammar_questions.py -- add `from dataclasses import dataclass` to the imports; append


@dataclass(frozen=True)
class PageFacts:
    """What one page states about the letter as a whole, not in one sentence.

    The frontier path typed these three per line (LetterVerdict.document_required,
    .track, .portfolio_required); addendum §6.3 forbids losing them. They are
    properties of the page -- a letter is required by a documents list, not by a
    sentence about the letter's length -- so they are asked once, over the page.
    """

    letter_required: str = "UNSTATED"  # REQUIRED | NOT_REQUIRED | UNSTATED
    track: str = ""  # research | taught | ""
    portfolio_led: bool = False


_PAGE_WHERE = "`sentences`"


def page_questions() -> dict[str, Question]:
    """Three questions over the whole page, each with an escape.

    Wording is a first draft for spec §11 gate 12's ablation, like every other
    question in this module.
    """
    return {
        "letter_required": Choice(
            question="Does this page require the applicant to submit a motivation "
                     "letter, statement of purpose, personal statement or cover letter?",
            options=("required", "not_required", "unstated"),
            inspect=_PAGE_WHERE,
            criteria={
                "required": {
                    "what": "The page lists the letter among the documents the applicant "
                            "must submit, or says it must be submitted.",
                    "examples": ["Motivation letter (max. 2 pages)",
                                 "Please upload your statement of purpose."],
                },
                "not_required": {
                    "what": "The page says the letter is not required, optional or not "
                            "accepted.",
                    "examples": ["A motivation letter is not required.",
                                 "No cover letter is needed."],
                },
                "unstated": {"what": "The page does not say whether a letter is required."},
            },
        ),
        "track": Choice(
            question="Is this programme research-based -- a thesis or project under a "
                     "supervisor the applicant identifies -- or taught?",
            options=("research", "taught", "unstated"),
            inspect=_PAGE_WHERE,
            criteria={
                "research": {"what": "Admission depends on a research proposal or on "
                                     "naming a supervisor.",
                             "examples": ["Identify a potential supervisor in your "
                                          "statement of intent."]},
                "taught": {"what": "A coursework programme; nothing asks for a "
                                   "supervisor or a research proposal."},
                "unstated": {"what": "The page does not say."},
            },
        ),
        "portfolio": Noul(
            question="Does the page require the applicant to submit a portfolio of their "
                     "own creative or professional work?",
            inspect=_PAGE_WHERE,
        ),
    }


def read_page_facts(
    candidates: Sequence[Candidate],
    slots: Sequence[Slotted],
    *,
    language: str = "",
    budget: DecisionBudget | None = None,
    # <!-- reconciled 2026-09-26: _ask takes AskFn | None; object fails mypy --strict -->
    client: AskFn | None = None,
    record: bool = True,
) -> PageFacts:
    """The page's letter-level facts, or none when the page has no letter of the applicant's.

    Asked only when some sentence is the applicant's own letter at the bar --
    the only lines the frontier path typed these from -- so a CV-only page costs
    no request. One request over the whole candidate listing: candidates() caps
    a page at _MAX_CANDIDATES (100), under CHUNK, so it never needs chunking.
    """
    if not any(
        s.document == "motivation_letter" and not s.third_party
        and s.document_confidence >= SLOT_BAR
        for s in slots
    ):
        return PageFacts()
    answers = _ask(
        slot_state(candidates), page_questions(), decision="D6.page",
        language=language, budget=budget, record=record, client=client,
    )
    required, track, portfolio = (
        answers["letter_required"], answers["track"], answers["portfolio"]
    )
    return PageFacts(
        letter_required=(
            str(required.value).upper()
            if required.confidence >= SLOT_BAR and required.value in ("required", "not_required")
            else "UNSTATED"
        ),
        track=(
            str(track.value)
            if track.confidence >= SLOT_BAR and track.value in ("research", "taught")
            else ""
        ),
        portfolio_led=bool(portfolio.value) and portfolio.confidence >= SLOT_BAR,
    )
```

- [ ] **Step 6: The letter projection**

```python
# apps/documents/rule_sinks.py -- add to the imports
# <!-- reconciled 2026-09-26: the bands come from grammar (Task 4). The `.grammar` line below
# REPLACES Task 8's `from .grammar import Rule, limit_sink, sink_for`. NOTE_BOUNDS is not needed
# here because a note-bound figure reaches this module as a topic -->
from typing import TYPE_CHECKING

from .grammar import _IMPLAUSIBLE_CAP, _IMPLAUSIBLE_MAX, Rule, limit_sink, sink_for
from .letter_shape import (
    _SAFE_FONT_FAMILY,
    LetterShape,
    _form_decision,
    _naming_decision,
)

if TYPE_CHECKING:
    from .grammar_questions import PageFacts
```

```python
# apps/documents/rule_sinks.py -- append

#: A letter style value and the LetterShape field it sets, for the booleans.
_LETTER_FLAG: dict[str, str] = {
    "signed_declaration": "signed_declaration",
    "signature_required": "signed_declaration",
    "handwritten": "handwritten",
}
# <!-- reconciled 2026-09-26: no _LETTER_CAP / _LETTER_FLOOR here -- grammar.limit_sink is the
# one unit-to-field mapping, and min_chars is measured WITHOUT spaces (Task 4 Part A), so a floor
# stated without spaces lands on it exactly -->
_BAND: dict[str, str] = {"pages": "pages", "words": "words", "characters": "chars"}
#: When two sentences set one field, which value is safer. A cap: the smaller.
#: A floor, a minimum font size, a margin, a line spacing: the larger. Anything
#: else keeps the first sentence that set it.
_SMALLER_IS_SAFER = frozenset({"max_words", "max_chars", "max_pages"})
_LARGER_IS_SAFER = frozenset({"min_words", "min_chars", "font_min_pt", "margins_cm",
                              "line_spacing"})


def letter_field(rule: Rule) -> tuple[str, object] | None:
    """Where one applied letter rule lands: a LetterShape field and its value,
    `written_requirements` or `student_actions` with the sentence, or None.

    Task 11's letter gate scores through this function, so the gate measures
    the projection that ships rather than a copy of it.
    """
    if not rule.applied:
        return None
    if rule.document == "reference_letter":
        # The referee's document. For the applicant it is one action: obtain it.
        return ("student_actions", rule.sentence)
    if rule.document != "motivation_letter":
        return None
    operation = rule.operation
    if operation == "student_action":
        return ("student_actions", rule.sentence)
    if operation == "topic":
        return ("written_requirements", rule.sentence)
    if operation == "format":
        # A letter has no Europass; a template it names is the student's to use.
        return ("student_actions", rule.sentence) if rule.value == "other_template" else None
    if operation in ("form", "naming"):
        return (operation, str(rule.value))
    if operation == "language":
        # ApplicationPrompt.document_language holds ONE code, so a page allowing
        # several needs a pick: English when it is allowed, otherwise the first.
        # Every allowed one satisfies the page; the sentence in `sources` shows
        # what else was on offer.
        allowed = rule.value if isinstance(rule.value, list) else [rule.value]
        return ("document_language", "en" if "en" in allowed else str(allowed[0]))
    if operation == "limit":
        return _letter_limit(rule)
    if operation == "style":
        return _letter_style(rule)
    return None


# <!-- reconciled 2026-09-26: grammar.limit_sink decides the field -->
def _letter_limit(rule: Rule) -> tuple[str, object] | None:
    """One figure onto its bound's field (addendum §6.1, §6.2).

    `limit_sink` is the one mapping: a cap or an approximation onto max_*, a
    floor onto min_words / min_chars. A cap counted without spaces is held as
    the same number WITH spaces and a floor is always counted without them --
    each the stricter reading, so a letter that passes ours passes theirs. A
    page floor has no field and reaches the writer. Tolerances, section limits
    and a second statement never get here: they arrive as topics.
    """
    floor = rule.bound == "minimum"
    unit = rule.unit or "pages"
    name = limit_sink("motivation_letter", rule.bound or "maximum", unit,
                      excl_spaces=rule.excl_spaces)
    if not name:
        return ("written_requirements", rule.sentence)
    number = int(rule.value)  # type: ignore[call-overload]
    band = _BAND[unit]
    if number > _IMPLAUSIBLE_MAX[band] or (not floor and number < _IMPLAUSIBLE_CAP[band]):
        logger.warning("ignoring an implausible %s %s of %s on a programme page",
                       band, "floor" if floor else "cap", number)
        return None
    return (name, float(number) if name == "max_pages" else number)


def _letter_style(rule: Rule) -> tuple[str, object] | None:
    """One style value onto its LetterShape field, inside the ranges LetterVerdict enforced."""
    value = str(rule.value)
    if value in _LETTER_FLAG:
        return (_LETTER_FLAG[value], True)
    if value == "font_family":
        if _SAFE_FONT_FAMILY.fullmatch(rule.detail):
            return ("font_family", rule.detail)
        logger.warning("dropping an unsafe font family from %r", rule.sentence[:80])
        return None
    if value == "single_file_bundle":
        return ("file_bundle", "SINGLE_PDF_ALL")
    if value == "line_spacing":
        return ("line_spacing", float(rule.detail)) if rule.detail in ("1.0", "1.5", "2.0") \
            else None
    if value not in ("font_size_minimum", "margins"):
        # A CV-only style (photo, date of birth) has no letter field; Task 6
        # already marked it unapplied, so nothing reaches here applied.
        return None
    try:
        number = float(rule.detail)
    except ValueError:
        logger.warning("dropping an unreadable %s from %r", value, rule.sentence[:80])
        return None
    if value == "font_size_minimum" and 4 <= number <= 40:
        return ("font_min_pt", int(number))
    if value == "margins" and 0.1 <= number <= 10:
        return ("margins_cm", number)
    return None


def to_letter_shape(
    rules: Sequence[Rule], *, source_url: str, page: PageFacts | None = None
) -> LetterShape:
    """The letter's rules, and the page's letter facts, as the shape the letter engine consumes.

    Every field the frontier path types is written here too (addendum §6.3):
    the fifteen LetterShape fields, `document_language` and `min_chars`. `form`
    and `naming` resolve with the frontier path's own functions, so the two
    paths cannot disagree about the safer side. `document_required` is written
    only with a letter sentence as its witness -- a flag with no sentence is a
    decision nobody can check (spec §6.4).
    """
    fields: dict[str, object] = {}
    sources: dict[str, dict[str, str]] = {}
    written: list[dict[str, str]] = []
    actions: list[dict[str, str]] = []
    forms: list[Rule] = []
    namings: list[Rule] = []

    def cite(rule: Rule) -> dict[str, str]:
        return {"text": rule.sentence, "source_url": source_url}

    for rule in rules:
        target = letter_field(rule)
        if target is None:
            continue
        name, value = target
        if name in ("written_requirements", "student_actions"):
            bucket = written if name == "written_requirements" else actions
            if cite(rule) not in bucket:
                bucket.append(cite(rule))
        elif name == "form":
            forms.append(rule)
        elif name == "naming":
            namings.append(rule)
        elif name not in fields or (
            (name in _SMALLER_IS_SAFER and value < fields[name])  # type: ignore[operator]
            or (name in _LARGER_IS_SAFER and value > fields[name])  # type: ignore[operator]
        ):
            fields[name] = value
            sources[name] = cite(rule)

    if forms:
        values = {str(r.value) for r in forms}
        decided = _form_decision(values, portal_unanimous="portal_form" in values)
        fields["form"] = decided
        sources["form"] = cite(
            next((r for r in forms if str(r.value).upper() == decided), forms[0])
        )
    if namings:
        votes = [str(r.value) for r in namings]
        decided = _naming_decision(votes, len(votes))
        fields["naming"] = decided
        sources["naming"] = cite(
            next((r for r in namings if str(r.value).upper() == decided), namings[0])
        )
    if page is not None:
        witness = next(
            (r for r in rules if r.document == "motivation_letter" and r.note != "third_party"),
            None,
        )
        if page.letter_required != "UNSTATED" and witness is not None:
            fields["document_required"] = page.letter_required
            sources["document_required"] = cite(witness)
        if page.track:
            fields["track"] = page.track
        if page.portfolio_led:
            fields["portfolio_led"] = True

    return LetterShape(
        **fields,  # type: ignore[arg-type]
        sources=sources,
        written_requirements=tuple(written),
        student_actions=tuple(actions),
    )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rule_sinks_letter.py tests/documents/test_grammar_page.py tests/documents/test_letter_shape.py tests/documents/test_letter_derive.py tests/funding/test_requirements.py -v`
Expected: all pass: 32 in `test_rule_sinks_letter.py` (29 functions, two of them
parametrized), 4 in `test_grammar_page.py`, and every existing test in the other three files plus
the 5 appended.

- [ ] **Step 8: Run the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents -q`
Expected: all clean

- [ ] **Step 9: Commit**

```bash
git -C "$WT" add apps/documents/rule_sinks.py apps/documents/grammar_questions.py \
  apps/documents/letter_shape.py apps/documents/derive.py apps/funding/requirements.py \
  tests/documents/test_rule_sinks_letter.py tests/documents/test_grammar_page.py \
  tests/documents/test_letter_shape.py tests/funding/test_requirements.py
uv run git -C "$WT" commit -m "feat: the letter's projection -- every field the frontier judge types, kept

form and naming are operations and resolve with the frontier path's own
functions, now in letter_shape so the two paths cannot disagree about the
safer side. document_required, track and portfolio_led are properties of the
page, asked once and only when the page has a letter of the applicant's; a
letter requirement is written only with a sentence to witness it.

Every figure is its own field: a range is a floor and a cap, min_chars holds
Kassel's floor, and a cap without spaces is held as the stricter inclusive one.
Tolerances, per-section caps and a second statement reach the writer as written
requirements -- recorded, not yet enforced. The plausibility bands, the font
and margin ranges and the fullmatch font guard come across unchanged.

The language operation writes ApplicationPrompt.document_language through a new
LetterShape field; a page that states no language leaves the column alone.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `derive_page_rules` reads through the grammar, with the frontier judge as the fallback

<!-- amended 2026-09-26: addendum §2, §5.1. The 2026-09-23 Task 10 deleted the frontier judge in
the same commit. It now stays as the fallback for a page read with no decision provider configured,
and its deletion moves to the deferred cleanup after Task 13. The five letter fields the deletion
would have lost are proven end to end here. -->

This is the task that puts the earlier tasks on the live path. **Nothing is deleted.** The
frontier judge becomes the branch that runs only when no provider key exists.

<!-- reconciled 2026-09-26: no DecisionsNotConfigured subclass. Tasks 1-3 give
DecisionsUnavailable a `.kind` ("not_configured" | "failed" | "refused") and say "the fix is
.kind, not new class names"; this task reads the kind. decisions.py is not modified here. -->

**Files:**
- Modify: `apps/documents/derive.py`, `apps/documents/program_rules.py`, `tests/conftest.py`
- Test: `tests/documents/test_derive_grammar.py` (new)

**Interfaces:**
- Consumes: `grammar_questions.{read_slots, read_page_facts}`, `grammar_values.read_values`, `rule_sinks.*`, `decisions.{DecisionBudget, DecisionsUnavailable}` (with `.kind`), `grammar_questions.AskFn`
- Produces:
  - `derive_page_rules(program, *, page_text, snapshot, admissions_cycle="", page_language="", parser=None, claude=None, budget=None, client: AskFn | None = None) -> Decision` — `parser` and `claude` become optional keyword arguments. Every existing caller passes them by keyword and keeps working.
  - `read_and_derive(*, program, source, store, parser, claude, admissions_cycle, retrieve=..., budget=None) -> ReadResult` — unchanged apart from `budget`
  - `derive._grammar_rules(found, *, language, budget, client: AskFn | None, record=True) -> tuple[tuple[Rule, ...], tuple[Slotted, ...]]` — both grammar requests before conflicts are settled. Task 11's gates and Task 12's sweep call it, so they measure what ships.

**Which path reads a page:**
- a decision provider is configured, or `client=` is passed → the grammar;
- `ask()` raises `DecisionsUnavailable` with `kind == "not_configured"` → the frontier judge, when
  `parser` and `claude` were passed; otherwise the raise propagates;
- any other `DecisionsUnavailable` (an outage, a refusal) → propagates.
  `read_and_derive`'s transaction rolls the statement write back, and the page's previous rows
  stand. Addendum §5.1's `decision_failed` marker and retry hand-off are plan 2's, which owns the
  read.

- [ ] **Step 1: Write the failing tests**

<!-- reconciled 2026-09-26 --> The missing-key half is already pinned by Task 1's
`test_an_absent_key_raises_rather_than_degrading` (`raised.value.kind == "not_configured"`), so
nothing is appended to `tests/research/test_decisions.py`.

```python
# tests/documents/test_derive_grammar.py
"""derive_page_rules end to end, over a stubbed grammar.

The stubs sit at the grammar's module seams (read_slots, read_values,
read_page_facts), not at question ids: what is under test is what lands on the
Program and the ApplicationPrompt, and the question ids are Tasks 5-6's to
change. Every test asserts an OUTCOME.
"""
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents import derive
from apps.documents.derive import Decision, derive_page_rules
from apps.documents.grammar import Rule, Slotted
from apps.documents.grammar_questions import PageFacts
from apps.documents.letter_shape import LetterShape
from apps.funding.models import (
    ApplicationPrompt,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.decisions import DecisionsUnavailable

pytestmark = pytest.mark.django_db


# <!-- reconciled 2026-09-26: the kind Tasks 1-3 raise for a missing key -->
def _no_key() -> DecisionsUnavailable:
    return DecisionsUnavailable("OPENROUTER_API_KEY is not set", kind="not_configured")

_CV = "Your CV may not exceed two pages."
_LETTER = "The motivation letter must be at most 800 words."
_PAGE = f"# Application documents\n{_CV}\n{_LETTER}\nA photograph is not required.\n"


def _snapshot() -> OfficialSourceSnapshot:
    # tests/documents/test_derive.py:59-77 -- the factory master actually uses.
    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    return OfficialSourceSnapshot.objects.create(
        source=source, s3_key=f"official-sources/{uuid4()}", s3_version_id="1",
        sha256="0" * 64, final_url=source.canonical_url, redirect_chain=[],
        retrieved_at=timezone.now(), admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )


@pytest.fixture
def grammar(monkeypatch):
    """Install the grammar's answers: `script` maps a sentence to the rules the
    two requests would have produced for it, `page` is the page-level reading.
    Returns what the stubs saw."""

    def install(script=None, *, page=PageFacts(), raises=None):
        script = script or {}
        seen: dict[str, object] = {}

        def read_slots(found, **kwargs):
            seen["client"] = kwargs.get("client")
            if raises is not None:
                raise raises
            return tuple(
                Slotted(index=i, document="other", document_confidence=0.99,
                        operation="other", operation_confidence=0.99,
                        third_party=False, conditional=False)
                for i in range(len(found))
            )

        def read_values(found, slots, **kwargs):
            return tuple(
                Rule(index=i, sentence=c.text, heading=c.heading, **{"confidence": 0.95, **kw})
                for i, c in enumerate(found)
                for kw in script.get(c.text, ())
            )

        def read_page_facts(found, slots, **kwargs):
            return page

        monkeypatch.setattr("apps.documents.grammar_questions.read_slots", read_slots)
        monkeypatch.setattr("apps.documents.grammar_values.read_values", read_values)
        monkeypatch.setattr("apps.documents.grammar_questions.read_page_facts", read_page_facts)
        return seen

    return install


def _letter(**kw):
    return {"document": "motivation_letter", **kw}


def _prompt(program) -> ApplicationPrompt:
    return ApplicationPrompt.objects.get(programme=program, cycle="2027")


def test_a_page_limit_lands_on_the_program_as_an_advisory_rule(program_factory, grammar):
    grammar({_CV: [{"document": "cv", "operation": "limit", "value": 2, "unit": "pages",
                    "bound": "maximum"}]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]
    assert program.cv_constraints[0]["enforcement"] == "ADVISORY_HIGH_RISK"


def test_the_client_reaches_the_grammar(program_factory, grammar):
    seen = grammar()
    client = object()
    derive_page_rules(program_factory(), page_text=_PAGE, snapshot=_snapshot(), client=client)
    assert seen["client"] is client


def test_a_page_stating_no_format_rule_writes_any_and_extracted(program_factory, grammar):
    grammar()
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.ANY
    assert program.cv_format_confidence == Program.CVFormatConfidence.EXTRACTED


def test_a_europass_page_switches_the_format(program_factory, grammar):
    page = "# Documents\nCV in the Europass CV template.\n"
    grammar({"CV in the Europass CV template.": [
        {"document": "cv", "operation": "format", "value": "europass_required"}
    ]})
    program = program_factory()
    derive_page_rules(program, page_text=page, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.EUROPASS_REQUIRED


def test_a_hand_verified_format_is_never_overwritten_but_rules_still_land(program_factory,
                                                                          grammar):
    grammar({_CV: [{"document": "cv", "operation": "limit", "value": 2, "unit": "pages"}]})
    program = program_factory(
        cv_format_requirement=Program.CVFormatRequirement.FUNDER_TEMPLATE,
        cv_format_verified_for_cycle="2026/27",
    )
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_format_requirement == Program.CVFormatRequirement.FUNDER_TEMPLATE
    assert program.cv_constraints[0]["key"] == "max_pages"


def test_a_page_with_no_candidate_replaces_the_previous_rules_and_asks_nothing(
    program_factory, grammar
):
    """Kept from master: no CV or letter line found by code is NO_CV_FOUND, and
    the previous rows go -- spec §5.3's replace-on-empty, without a request."""
    seen = grammar(raises=AssertionError("the grammar was asked about an empty page"))
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    derive_page_rules(program, page_text="# About us\nWe are a university.\n",
                      snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert program.cv_format_confidence == Program.CVFormatConfidence.NO_CV_FOUND
    assert "client" not in seen


def test_an_unsure_sentence_becomes_a_note_the_counsellor_reads(program_factory, grammar):
    grammar({_CV: [{"document": "cv", "operation": "limit", "value": None, "note": "unsure",
                    "confidence": 0.44}]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), client=object())
    program.refresh_from_db()
    notes = [r for r in program.cv_constraints if r["key"] in ("undecided", "unapplied")]
    assert notes and notes[0]["rule_text"] == _CV


def test_nothing_writes_a_consultant_task(program_factory, grammar):
    """Owner decision 2026-09-23: no person in the pipeline."""
    from apps.research.models import ConsultantResearchTask

    grammar({_CV: [{"document": "cv", "operation": "other", "value": None,
                    "note": "unapplied"}]})
    derive_page_rules(program_factory(), page_text=_PAGE, snapshot=_snapshot(), client=object())
    assert ConsultantResearchTask.objects.count() == 0


# --- Nothing typed is lost (addendum §6.3): each field the frontier path writes,
# --- written by the grammar path, end to end onto the stored rows.

def test_the_letter_cap_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words", bound="maximum")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).letter_max_words == 800


def test_form_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="form", value="formal_letter")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    prompt = _prompt(program)
    assert prompt.letter_form == "FORMAL_LETTER"
    assert prompt.letter_shape_sources["form"]["text"] == _LETTER


def test_naming_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="naming", value="forbidden")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).letter_naming == "FORBIDDEN"


def test_document_required_is_written_with_its_witness(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words")]},
            page=PageFacts(letter_required="REQUIRED"))
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    prompt = _prompt(program)
    assert prompt.letter_document_required == "REQUIRED"
    assert prompt.letter_shape_sources["document_required"]["text"] == _LETTER


def test_track_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words")]},
            page=PageFacts(track="research"))
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    program.refresh_from_db()
    assert program.academic_track == "research"


def test_portfolio_led_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="limit", value=800, unit="words")]},
            page=PageFacts(portfolio_led=True))
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    program.refresh_from_db()
    assert program.portfolio_led is True


def test_the_letters_language_is_written(program_factory, grammar):
    grammar({_LETTER: [_letter(operation="language", value="de")]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).document_language == "de"


def test_a_range_writes_its_floor_and_its_cap(program_factory, grammar):
    grammar({_LETTER: [
        _letter(operation="limit", value=300, unit="words", bound="minimum"),
        _letter(operation="limit", value=500, unit="words", bound="maximum"),
    ]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    prompt = _prompt(program)
    assert (prompt.letter_min_words, prompt.letter_max_words) == (300, 500)


def test_a_character_floor_is_written(program_factory, grammar):
    grammar({_LETTER: [
        _letter(operation="limit", value=2800, unit="characters", bound="minimum")
    ]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert _prompt(program).letter_min_chars == 2800


def test_a_tolerance_is_a_written_requirement(program_factory, grammar):
    # <!-- reconciled 2026-09-26: a tolerance is a topic sentence, never a limit bound -->
    grammar({_LETTER: [_letter(operation="topic", value=_LETTER)]})
    program = program_factory()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      client=object())
    assert [w["text"] for w in _prompt(program).letter_written_requirements] == [_LETTER]


# --- Which path reads the page (addendum §2, §5.1).

def test_with_no_provider_configured_the_frontier_judge_reads_the_page(
    program_factory, grammar, monkeypatch
):
    """A missing key degrades cost, not correctness. The existing frontier
    tests in test_derive.py run this branch end to end: tests/conftest.py blanks
    every provider key, so read_and_derive reaches the judge exactly as before."""
    grammar(raises=_no_key())
    seen: dict[str, object] = {}

    def judge(found, *, parser, claude, program_id, source_url):
        seen["parser"], seen["claude"] = parser, claude
        return (
            Decision(abstained=False, format_value=Program.CVFormatRequirement.ANY,
                     confidence=Program.CVFormatConfidence.EXTRACTED, rules=(), directives=()),
            LetterShape(max_words=700,
                        sources={"max_words": {"text": _LETTER, "source_url": source_url}}),
        )

    monkeypatch.setattr(derive, "_read_by_judge", judge)
    program = program_factory()
    parser, claude = object(), object()
    derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(), admissions_cycle="2027",
                      parser=parser, claude=claude)
    assert (seen["parser"], seen["claude"]) == (parser, claude)
    assert _prompt(program).letter_max_words == 700


def test_with_no_provider_and_no_frontier_client_the_page_is_not_read(program_factory, grammar):
    grammar(raises=_no_key())
    with pytest.raises(DecisionsUnavailable) as raised:
        derive_page_rules(program_factory(), page_text=_PAGE, snapshot=_snapshot())
    assert raised.value.kind == "not_configured"


# <!-- review focus 3 -->
def test_an_outage_leaves_the_catalog_untouched_and_never_falls_back(
    program_factory, grammar, monkeypatch
):
    """'We learned nothing' must never reach a catalog write, and an outage is
    not a missing key: the frontier judge is not a second opinion (addendum
    §5.1). The raise propagates so read_and_derive rolls the statements back."""
    grammar(raises=DecisionsUnavailable("typesafe: ConnectTimeout", kind="failed"))

    def judge(*args, **kwargs):  # pragma: no cover
        raise AssertionError("an outage fell back to the frontier judge")

    monkeypatch.setattr(derive, "_read_by_judge", judge)
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    with pytest.raises(DecisionsUnavailable):
        derive_page_rules(program, page_text=_PAGE, snapshot=_snapshot(),
                          parser=object(), claude=object())
    program.refresh_from_db()
    assert program.cv_constraints[0]["rule_text"] == "old"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_derive_grammar.py -v`
Expected: FAIL — `TypeError: derive_page_rules() got an unexpected keyword argument 'client'`.
<!-- reconciled 2026-09-26 -->

- [ ] **Step 3: Confirm the missing-key raises carry `kind="not_configured"`**

<!-- reconciled 2026-09-26: a check, not a code change -- Tasks 1-3 already raise the kind -->

```bash
grep -n 'kind="not_configured"' apps/research/decisions.py
```

Expected: the missing-key raise in `_typesafe_client` (`f"{name} is not set"`), the adapter's
missing-environment-variable raise, and the two unknown-provider raises. Nothing else. A transport
failure, a skipped answer or a refusal is `failed` / `refused` and must never reach the frontier
judge. If a missing-key raise lacks the kind, Task 1 was executed from the 2026-09-23 text: stop and
fix Task 1, not this task.

- [ ] **Step 4: No test reaches a provider because a shell exported a key**

```python
# tests/conftest.py -- append
@pytest.fixture(autouse=True)
def _no_decision_provider_by_accident(request, settings):
    """derive_page_rules asks the decision layer first and falls back to the
    frontier judge only when no key is configured (addendum §2), so a key in a
    developer's environment would turn every read_and_derive test into a paid
    network call. Live tests carry their own marker and keep the real keys."""
    if request.node.get_closest_marker("live"):
        return
    settings.TYPESAFE_API_KEY = ""
    settings.OPENROUTER_API_KEY = ""
```

- [ ] **Step 5: Rewrite `derive_page_rules`**

Add to `derive.py`'s imports: `replace` from `dataclasses` (the line becomes
`from dataclasses import dataclass, replace`), then

```python
# <!-- reconciled 2026-09-26: AskFn for the grammar's seam; the kind, not a subclass -->
from apps.research.decisions import DecisionBudget, DecisionsUnavailable

from .grammar_questions import AskFn

from .grammar import Rule, Slotted
```

(`grammar.py` imports only `constraints`, so this is not a cycle; `grammar_questions`,
`grammar_values` and `rule_sinks` are imported inside the functions below.)

Replace `derive_page_rules` (re-resolve: `grep -n "^def derive_page_rules" apps/documents/derive.py`,
line 1363 at `f5cfac6`) through the end of the module with:

```python
def _grammar_rules(
    found: tuple[Candidate, ...],
    *,
    language: str,
    budget: DecisionBudget | None,
    # <!-- reconciled 2026-09-26: read_slots / read_values take AskFn | None -->
    client: AskFn | None,
    record: bool = True,
) -> tuple[tuple[Rule, ...], tuple[Slotted, ...]]:
    """Both grammar requests over one page's candidates, conflicts NOT yet settled.

    Separate from the page read so Task 11's gates and the rederive sweep score
    exactly what ships. The third-party regex stays as an ADDITIVE signal
    beside the scope Noul: a sentence either flags as somebody else's binds
    nothing, and a word list may add a guard and never remove one (§8.1).
    """
    # Imported here, not at module top: grammar_questions and grammar_values
    # import Candidate from this module, so a top-level import is a cycle that
    # fails with "partially initialized module".
    from .grammar_questions import read_slots
    from .grammar_values import read_values

    slots = read_slots(found, language=language, budget=budget, client=client, record=record)
    slots = tuple(
        replace(slot, third_party=slot.third_party or found[slot.index].third_party)
        for slot in slots
    )
    rules = read_values(found, slots, language=language, budget=budget, client=client,
                        record=record)
    return rules, slots


def _read_by_grammar(
    found: tuple[Candidate, ...],
    *,
    language: str,
    source_url: str,
    budget: DecisionBudget | None,
    # <!-- reconciled 2026-09-26 -->
    client: AskFn | None,
) -> tuple[Decision, LetterShape]:
    """The page read through the typed grammar: the CV decision and the letter shape."""
    from .grammar_questions import read_page_facts
    from .rule_sinks import (
        format_decision,
        resolve_conflicts,
        to_constraint_rules,
        to_directives,
        to_letter_shape,
        to_notes,
    )

    raw, slots = _grammar_rules(found, language=language, budget=budget, client=client)
    rules = resolve_conflicts(raw)
    page = read_page_facts(found, slots, language=language, budget=budget, client=client)
    format_value, confidence = format_decision(rules)
    unapplied = sum(r.note == "unapplied" for r in rules)
    if unapplied:
        # §6.5's counter and §9a's drift signal: a rise means the grammar is
        # falling behind what pages actually ask for.
        logger.info("derive: %d unapplied requirement sentences on %s", unapplied, source_url)
    decision = Decision(
        abstained=confidence == Program.CVFormatConfidence.UNDECIDED,
        format_value=format_value,
        confidence=confidence,
        rules=(
            *to_constraint_rules(rules, source_url=source_url),
            *to_notes(rules, source_url=source_url),
        ),
        directives=to_directives(rules, source_url=source_url),
    )
    return decision, to_letter_shape(rules, source_url=source_url, page=page)


def _read_by_judge(
    found: tuple[Candidate, ...],
    *,
    parser: ResponsesAPI,
    claude: MessagesAPI,
    program_id: str,
    source_url: str,
) -> tuple[Decision, LetterShape]:
    """The frontier judge: three readings, two model families, vote counting.

    The fallback while no decision provider is configured (addendum §2, §5.1).
    Deleted only by the cleanup after Task 13, on its stated trigger. Raises
    DerivationFailure when no sample answered, exactly as before.
    """
    listing = "\n".join(
        f"{i} | {c.heading + ' > ' if c.heading else ''}{c.text}" for i, c in enumerate(found)
    )
    samples = _judge(parser, claude, program_id=program_id, listing=listing)
    return (
        decide(found, samples, source_url=source_url),
        decide_letter_shape(found, samples, source_url=source_url),
    )


def derive_page_rules(
    program: Program,
    *,
    page_text: str,
    snapshot: OfficialSourceSnapshot,
    admissions_cycle: str = "",
    page_language: str = "",
    parser: ResponsesAPI | None = None,
    claude: MessagesAPI | None = None,
    budget: DecisionBudget | None = None,
    # <!-- reconciled 2026-09-26 -->
    client: AskFn | None = None,
) -> Decision:
    """Everything the catalog concludes from one read of a programme's page.

    Candidates by code over the whole page (plus the statement read's
    DOCUMENT/FORMAT sentences), read through the typed grammar -- or, when no
    decision provider is configured at all, through the frontier judge, so a
    missing key degrades cost and never correctness (addendum §2, §5.1). An
    outage is not a missing key: it raises, the caller's transaction rolls the
    statement write back, and the page's previous rows stand.

    ONE catalog write either way, so the format switch, the rules and the
    directives can never sit at different versions of the page. A hand-verified
    format (cv_format_verified_for_cycle) is never overwritten; its rules and
    directives still land. A page with no candidate writes NO_CV_FOUND and asks
    nothing.

    `page_language` is the page's own `<html lang>`, resolved here via
    `detect_language` (never trusted raw).
    """
    statements = ProgramStatement.objects.filter(
        program=program,
        kind__in=(ProgramStatement.Kind.FORMAT, ProgramStatement.Kind.DOCUMENT),
    ).values_list("text", flat=True)
    language = detect_language(page_text, html_lang=page_language)
    found = candidates(page_text, statements, language=language)
    source_url = snapshot.final_url
    if not found:
        decision = Decision(
            abstained=False, format_value=Program.CVFormatRequirement.ANY,
            confidence=Program.CVFormatConfidence.NO_CV_FOUND, rules=(), directives=(),
        )
        shape = LetterShape()
    else:
        try:
            decision, shape = _read_by_grammar(
                found, language=language, source_url=source_url, budget=budget, client=client,
            )
        # <!-- reconciled 2026-09-26: Tasks 1-3's kind, not a subclass -->
        except DecisionsUnavailable as error:
            if error.kind != "not_configured" or parser is None or claude is None:
                raise
            logger.warning("derive: no decision provider configured; reading %s with the "
                           "frontier judge", source_url)
            decision, shape = _read_by_judge(
                found, parser=parser, claude=claude, program_id=str(program.id),
                source_url=source_url,
            )
    fields: dict[str, object] = {
        "cv_constraints": [r.model_dump(mode="json") for r in decision.rules],
        "cv_directives": list(decision.directives),
    }
    if not program.cv_format_verified_for_cycle:
        fields["cv_format_requirement"] = decision.format_value
        fields["cv_format_confidence"] = decision.confidence
    _write_program(program.id, **fields)
    if admissions_cycle:
        # One read, both documents (spec §3): the letter shape comes from the
        # same read, inside the same transaction read_and_derive holds. No
        # cycle means a caller that only wants the CV rules.
        apply_derived_shape(program, admissions_cycle, shape, source_url=source_url)
    return decision
```

- [ ] **Step 6: `read_and_derive` passes the budget through**

In `apps/documents/program_rules.py`, add `from apps.research.decisions import DecisionBudget`. Add
`budget: DecisionBudget | None = None,` after `retrieve=...` in `read_and_derive`'s signature, and
change the inner call to:

```python
            derive_page_rules(
                program, parser=parser, claude=claude, budget=budget,
                page_text=result.page_text, snapshot=result.snapshot,
                admissions_cycle=admissions_cycle, page_language=result.page_language,
            )
```

Append to its docstring: *"Derivation reads through the decision layer when a provider is
configured and through the frontier judge otherwise (derive_page_rules). `parser` still serves
read_program_page's statement read, which plan 2 replaces."* The transaction boundary does not
change.

- [ ] **Step 7: Run the tests**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_derive_grammar.py tests/research/test_decisions.py -v`
Expected: all pass (21 in `test_derive_grammar.py`).

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_derive.py tests/documents/test_letter_derive.py tests/documents/test_letter_shape.py tests/research/test_reader.py -q`
Expected: all pass, unchanged. These are the frontier path's tests. They now reach it through
<!-- reconciled 2026-09-26 -->
a `not_configured` raise, which is the proof that the fallback is the old path, byte for byte.

- [ ] **Step 8: Run the whole suite and the checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run bandit -c pyproject.toml -r apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest && POSTGRES_DB=tehsil_requirement_reader uv run python manage.py makemigrations --check --dry-run`
Expected: all clean.

- [ ] **Step 9: Commit**

<!-- reconciled 2026-09-26: the message names the kind, not a subclass -->

```bash
git -C "$WT" add apps/documents/derive.py \
  apps/documents/program_rules.py tests/conftest.py tests/documents/test_derive_grammar.py
uv run git -C "$WT" commit -m "feat: derive_page_rules reads through the grammar; the frontier judge is the fallback

With a decision provider configured a page is read by two typed requests and a
page-level one, projected onto the sinks that exist. With no key at all it is
read by the frontier judge exactly as before, so a missing key degrades cost,
not correctness (addendum §2, §5.1). An outage is not a missing key: it raises,
the read's transaction rolls back, and the page's previous rows stand.
DecisionsUnavailable.kind ("not_configured" vs "failed") tells the two apart.

Nothing is deleted. Every field the frontier judge types -- form, naming,
document_required, track, portfolio_led -- is written by the grammar path too,
each proven end to end, and the frontier's own tests now run through the
fallback unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: The ship gates — every catalogued rule, the 48 CV sentences, the 77 letter sentences

<!-- amended 2026-09-26: gate 7 checks the new form/naming values; the 48-row gate is rescored to
the sheet's own outcomes and runs the production path; the 77-sentence letter eval is added and
scored per figure (addendum §1, §6.1); the page-corpus gates of addendum §8 are a pointer only. -->

None of these is a unit test. Gate 7 is a mapping a person makes once, and a test pins it forever
after. The two live gates spend real money, a few cents at Jev's price, and are run on purpose.

**Files:**
- Create: `docs/research/rule-grammar-map.csv`
- Create: `tests/documents/test_grammar_gate.py`

**Interfaces:**
- Consumes: `derive.{candidates, _grammar_rules}`, `rule_sinks.{to_constraint_rules, to_directives, letter_field}`, `grammar.{DOCUMENTS, OPERATIONS, STYLE_VALUES, UNITS, FORM_VALUES, NAMING_VALUES, sink_for}`, `docs/research/{cv-format-eval,letter-shape-eval}.csv`, the three rule catalogs
- Produces: no code, three gates

Spec §11 gates 1 and 7. **Gate 7 runs first.** If the grammar cannot express a rule the catalogs
already hold, it is missing an operation, and finding that after the decision layer ships is too
late.

**Not in this plan's gate: addendum §8's page corpus.** The 30-page answer key
(`docs/research/letter-page-corpus.csv`) lives on branch `claude/letter-gap-fixes` and joins the
labelled corpus later. Its gates bind the requirement reader once it lands:
- every length exact on ≥ 90% of dev pages and ≥ 85% of held-out pages;
- no wrong value on any page;
- the required-or-not answer right on every page;
- each reported per language and per stratum;
- the held-out split scored only when a part is declared finished.

Those gates are also the trigger for the deferred cleanup after Task 13. Nothing in this task
requires the corpus.

- [ ] **Step 1: Write the expressibility map**

A person reads all 216 rows (`cv-rules.csv` 93, `cv-style-rules.csv` 50, `letter-rules.csv` 73)
and writes one line per rule into `docs/research/rule-grammar-map.csv`:

```csv
rule_id,catalog,document,operation,value,note
R-001,cv-rules,cv,limit,pages,
S-010,cv-style-rules,cv,style,photo_forbidden,
S-026,cv-style-rules,cv,other,,"action verbs and outcome-first phrasing -- a writing-quality rule, not a page rule; the generator's prompt carries it"
L-041,letter-rules,motivation_letter,other,,"Cambridge's AI prohibition -- ai_use_policy, a catalog-only key no page sentence states"
M-003,letter-rules,motivation_letter,style,signed_declaration,
```

(Those five lines show the format. Every id in the map must be a real catalog id.) `operation = other`
with a note is a legitimate row: it records a catalogued rule that is not a page-stated requirement,
such as a writing-quality convention or a catalog-only key. The gate refuses a row whose rule a page
*would* state and the grammar cannot carry. That is a missing operation, and the grammar grows
before this task's commit. <!-- amended 2026-09-26 --> Letter rules about the letter's form (essay,
formal letter, portal field) map to `form` with a `FORM_VALUES` value. Rules about naming a
supervisor map to `naming` with a `NAMING_VALUES` value.

- [ ] **Step 2: Write the gates**

```python
# tests/documents/test_grammar_gate.py
"""The ship gates of spec §11, amended by the 2026-09-26 addendum.

Gate 7 (expressibility) is a plain test and runs everywhere. Gate 1 (the
48-row CV sheet) and the 77-sentence letter sheet call a real provider and
carry the `live` marker, so `addopts = "-m 'not live'"` keeps them out of a
default run; select them with `-m live`. Both run the production path
(derive.candidates + derive._grammar_rules + the rule_sinks projection), so
they measure what ships.
"""
import csv
import pathlib
from collections import defaultdict

import pytest

from apps.documents.grammar import (
    DOCUMENTS,
    FORM_VALUES,
    NAMING_VALUES,
    OPERATIONS,
    STYLE_VALUES,
    UNITS,
    sink_for,
)

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
    checked the grammar against."""
    mapped = {row["rule_id"] for row in _mapped()}
    for catalog, path in _CATALOGS.items():
        with path.open(encoding="utf-8") as handle:
            ids = {row["ID"] for row in csv.DictReader(handle)}
        missing = ids - mapped
        assert not missing, f"{catalog}: {len(missing)} unmapped rules, e.g. {sorted(missing)[:5]}"


def test_every_mapped_slot_is_in_a_closed_list():
    closed = {"style": STYLE_VALUES, "limit": UNITS, "form": FORM_VALUES,
              "naming": NAMING_VALUES}
    for row in _mapped():
        assert row["document"] in DOCUMENTS, row
        assert row["operation"] in OPERATIONS, row
        if row["operation"] in closed and row["value"]:
            assert row["value"] in closed[row["operation"]], row


def test_every_mapped_rule_reaches_a_sink_or_says_why_not():
    """An `other` row is legitimate when it says why; a silent one is a missing
    operation wearing a disguise."""
    for row in _mapped():
        if row["operation"] == "other":
            assert row["note"].strip(), f"{row['rule_id']} is `other` with no reason"
            continue
        sink = sink_for(row["document"], row["operation"], row["value"])
        assert sink, f"{row['rule_id']} maps to {row['operation']} with no sink"


def test_the_unapplied_share_of_the_catalogs_is_small():
    """Gate 8's static half."""
    rows = _mapped()
    other = [r for r in rows if r["operation"] == "other"]
    assert len(other) / len(rows) <= 0.2, (
        f"{len(other)} of {len(rows)} catalogued rules have no operation"
    )


# --- Gate 1: the 48 CV sentences, scored on the sheet's own outcomes -------------

def _cv_score(expect: str, detail: str, rules) -> str:
    """"correct" / "undecided" / "wrong" for one row, from the rules on its sentence.

    The sheet's outcomes are actions (europass / standard), constraints,
    directives, `unapplied` and `none` -- the same scoring the frontier gate
    uses (tests/documents/test_derive.py::_classify), read off typed rules.
    """
    from apps.documents.rule_sinks import to_constraint_rules, to_directives

    cv = [r for r in rules if r.document == "cv"]
    applied = [r for r in cv if r.applied]
    europass = any(
        r.operation == "format" and str(r.value).startswith("europass") for r in applied
    )
    noted = any(not r.applied for r in cv)
    constraints = {c.key: c.value for c in to_constraint_rules(cv, source_url="")}
    directives = {(d["action"], d["target"], d["value"])
                  for d in to_directives(cv, source_url="")}
    if expect == "europass":
        return "correct" if europass else "undecided" if noted else "wrong"
    if expect in ("standard", "none"):
        wrong = europass or (expect == "none" and (constraints or directives))
        return "wrong" if wrong else "correct"
    if europass:
        return "wrong"
    if expect == "unapplied":
        return "correct" if any(r.note == "unapplied" for r in cv) else "undecided"
    if expect == "constraint":
        key, _, value = detail.partition("=")
        if key in constraints:
            return "correct" if str(constraints[key]).lower() == value.lower() else "wrong"
    elif expect == "order":
        target, _, direction = detail.partition("=")
        if ("order", target, direction) in directives:
            return "correct"
    elif (expect, detail, None) in directives:
        return "correct"
    return "undecided" if noted else "wrong"


@pytest.mark.live
def test_the_forty_eight_row_cv_gate(capsys):
    """Gate 1 (spec §11.1): 48/48 on the Europass ACTION -- whether the CV would
    render Europass -- and >= 46/48 correct overall. The action matters more
    than the label because it is what moves student data."""
    from apps.documents.derive import _grammar_rules, candidates

    rows = list(csv.DictReader((_DOCS / "cv-format-eval.csv").open(encoding="utf-8")))
    assert len(rows) == 48
    found = candidates("\n".join(r["sentence"] for r in rows), ())
    assert len(found) == len(rows), "every eval sentence must be a candidate by code"
    rules, _ = _grammar_rules(found, language="", budget=None, client=None, record=False)
    by_index = defaultdict(list)
    for rule in rules:
        by_index[rule.index].append(rule)

    scored = {row["id"]: _cv_score(row["outcome"], row["detail"], by_index[i])
              for i, row in enumerate(rows)}
    action_wrong = [
        row["id"] for i, row in enumerate(rows)
        if (row["outcome"] == "europass") != any(
            r.document == "cv" and r.applied and r.operation == "format"
            and str(r.value).startswith("europass") for r in by_index[i]
        )
    ]
    correct = sum(v == "correct" for v in scored.values())
    with capsys.disabled():
        print(f"\ncv gate: {correct}/48 correct; action wrong {action_wrong}; "
              f"not correct {[(k, v) for k, v in scored.items() if v != 'correct']}")
    assert action_wrong == [], f"{len(action_wrong)} of 48 wrong on the Europass action"
    assert correct >= 46


# --- The 77 letter sentences, scored per figure (addendum §1, §6.1) ---------------

# <!-- reconciled 2026-09-26: min_chars is a length field since Task 4 Part A -->
_LENGTH_FIELDS = ("max_words", "min_words", "max_chars", "min_chars", "max_pages")


def _same(field: str, got: object, expected: str) -> bool:
    if field in ("signed_declaration", "handwritten"):
        return got is True and expected == "true"
    if field in ("max_pages", "line_spacing", "margins_cm"):
        return float(got) == float(expected)  # type: ignore[arg-type]
    # <!-- reconciled 2026-09-26 -->
    if field in ("max_words", "min_words", "max_chars", "min_chars", "font_min_pt"):
        return int(got) == int(expected)  # type: ignore[call-overload]
    return str(got).lower() == expected.lower()


@pytest.mark.live
def test_the_seventy_seven_sentence_letter_gate(capsys):
    """Every figure is its own decision, so a row is scored on its figure:
    asserted when a rule on its sentence projects to the expected field and
    value, contradicted when one projects to that field with another value --
    or, for a floor, when the floor's figure comes back as the cap, the defect
    the per-figure questions exist to close.

    The bar is the frontier judge's measured one (addendum §1): no wrong cap
    and no missed naming=forbidden in any language, and English asserting at
    least the 51 rules the frontier asserted. A `none` row is printed, never
    asserted, as tests/documents/test_letter_derive.py does.
    """
    from apps.documents.derive import _grammar_rules, candidates
    from apps.documents.rule_sinks import letter_field
    from apps.research.decisions import DecisionBudget

    # <!-- amended 2026-09-26: addendum §7 -- the cost is measured, not assumed. An
    # unlimited budget counts every input token the grammar spends on these sentences. -->
    spend = DecisionBudget()
    rows = list(csv.DictReader((_DOCS / "letter-shape-eval.csv").open(encoding="utf-8")))
    assert len(rows) == 77
    by_language: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_language[row["language"]].append(row)

    wrong_caps: list[tuple[str, str, str]] = []
    missed_forbidden: list[str] = []
    asserted_by_language: dict[str, int] = {}
    for language, group in sorted(by_language.items()):
        found = candidates("\n".join(r["sentence"] for r in group), (), language=language)
        index_of = {c.text: i for i, c in enumerate(found)}
        rules, _ = _grammar_rules(found, language=language, budget=spend, client=None,
                                  record=False)
        landed: dict[int, list[tuple[str, object]]] = defaultdict(list)
        for rule in rules:
            target = letter_field(rule)
            if target is not None:
                landed[rule.index].append(target)
        asserted = missed = contradicted = unfound = printed = 0
        for row in group:
            index = index_of.get(row["sentence"])
            if index is None:
                unfound += 1  # a result about the vocabulary, not the grammar
                continue
            field, expected = row["expected_field"], row["expected_value"]
            got = landed[index]
            if field == "none":
                printed += 1
                with capsys.disabled():
                    print(f"  ? {row['id']} [{language}] untypeable -> {got}")
                continue
            same = [value for name, value in got if name == field]
            floor_as_cap = field.startswith("min_") and any(
                name == "max_" + field[4:] and _same(field, value, expected)
                for name, value in got
            )
            if floor_as_cap or any(not _same(field, value, expected) for value in same):
                contradicted += 1
                if field in _LENGTH_FIELDS:
                    wrong_caps.append((row["id"], language, field))
            elif same:
                asserted += 1
            else:
                missed += 1
                if field == "naming" and expected == "forbidden":
                    missed_forbidden.append(row["id"])
        asserted_by_language[language] = asserted
        with capsys.disabled():
            print(f"  {language}: {len(group)} rows, {asserted} asserted, {missed} missed, "
                  f"{contradicted} contradicted, {unfound} not a candidate, "
                  f"{printed} untypeable")
    assert wrong_caps == []
    assert missed_forbidden == []
    assert asserted_by_language.get("en", 0) >= 51, asserted_by_language
    # Addendum §7: a page costing more than 3x the estimate fails the gate. The design's
    # §10 prices the rule judgement at ~$0.0002 per page, ~4,800 input tokens at Jev's
    # $0.042/M, over ~10 requirement sentences: ~500 tokens a sentence, so the bar is
    # 1,500. Printed every run so a drift upward is visible before it fails.
    per_sentence = spend.spent / len(rows)
    with capsys.disabled():
        print(f"  cost: {spend.spent} input tokens, {per_sentence:.0f} per sentence")
    assert per_sentence <= 1_500, per_sentence


# <!-- review focus 2 --> Jev's own documentation names literal reading of negation as a
# weakness (jev-1.13 failure-mode page). No stub can show how Jev reads these, so they are
# live: a negated maximum, a negated minimum, and a sentence stating there is no limit.
_NEGATIONS = (
    ("Your motivation letter must be no more than 500 words.", "max_words", 500),
    ("The statement should not be less than 300 words.", "min_words", 300),
    ("Das Motivationsschreiben darf nicht länger als zwei Seiten sein.", "max_pages", 2),
    ("There is no word limit for the motivation letter.", None, None),
)


@pytest.mark.live
def test_negated_limits_read_the_right_way_round(capsys):
    from apps.documents.derive import _grammar_rules, candidates
    from apps.documents.rule_sinks import letter_field

    for sentence, field, expected in _NEGATIONS:
        language = "de" if "Seiten" in sentence else "en"
        found = candidates(sentence, (), language=language)
        rules, _ = _grammar_rules(found, language=language, budget=None, client=None,
                                  record=False)
        landed = [target for rule in rules if (target := letter_field(rule)) is not None]
        with capsys.disabled():
            print(f"  {sentence!r} -> {landed}")
        lengths = [(name, value) for name, value in landed if name in _LENGTH_FIELDS]
        if field is None:
            assert lengths == [], sentence  # "no word limit" sets no limit
        else:
            assert lengths == [(field, expected)], sentence
```

- [ ] **Step 3: Run the gates**

```bash
POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_gate.py -v
```
Expected: 4 passed, 2 deselected. **If gate 7 fails, the grammar is short an operation: add it to
`grammar.py`, give it a sink and re-run. That is the gate working, not the test being wrong.**

```bash
set -a; . ~/.config/tehsil_agent/openrouter.env; set +a
POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_grammar_gate.py -m live -v -s
```
Expected: both pass, with the printed lists empty or nearly so. **Record the four figures in the
commit message:** CV correct/48, CV action wrong, letter EN asserted, and wrong caps. If the action
bar is missed, the shipped threshold moves up before anything else proceeds. §6.2's bar is a
starting value, and this is the measurement that sets it. The frontier's own gates
(`tests/documents/test_derive.py::test_the_eval_corpus_has_no_wrong_action_and_few_abstentions`,
`tests/documents/test_letter_derive.py::test_the_judge_reads_every_language_in_the_eval_sheet`)
stay: they gate the fallback.

- [ ] **Step 4: Commit**

```bash
git -C "$WT" add docs/research/rule-grammar-map.csv tests/documents/test_grammar_gate.py
uv run git -C "$WT" commit -m "test: the ship gates -- every catalogued rule, 48 CV and 77 letter sentences

Gate 7 runs first and is the cheap one: a grammar that cannot express a rule the
catalogs already hold is a missing operation, found before shipping. form and
naming values are checked against their closed lists.

Gate 1 scores the 48 CV sentences on the sheet's own outcomes through the
production path, the Europass action first because it moves student data. The
77 letter sentences are scored per figure: a floor that comes back as the cap
is a contradiction, not a near miss. The bar is the frontier judge's measured
one. The page-corpus gates of the 2026-09-26 addendum §8 bind once that corpus
lands from claude/letter-gap-fixes.

Live result: CV <correct>/48, action wrong <n>; letter EN <asserted> asserted,
wrong caps <n>.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(The four `<...>` fields are the measured numbers from Step 3's printed output, filled in at
commit time. They are data, not plan text.)

---

### Task 12: The re-derivation sweep, the counters, and the record

**Files:**
- Create: `apps/documents/management/commands/rederive_rules.py`
- Modify: `CLAUDE.md`, `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`
- Test: `tests/documents/test_rederive_rules.py`

**Interfaces:**
- Consumes: `ProgramStatement`, `derive.{Candidate, _THIRD_PARTY, _grammar_rules, _write_program}`, `rule_sinks.*`, `decisions.{run_budget, DecisionBudgetExhausted, DecisionsUnavailable}`, `grammar_questions.AskFn` <!-- reconciled 2026-09-26: AskFn -->
- Produces: `manage.py rederive_rules [--program <id>] [--dry-run]`

Spec §6.5: when the grammar grows, the questions are asked again over **stored sentences**, so
every programme that ever stated the rule gets it without a page being refetched. This is the sweep
CLAUDE.md warns about. It calls the decision layer directly, so it carries its own budget, or it
makes an unbounded call per programme. <!-- amended 2026-09-26 --> **It never falls back to the
frontier judge.** It exists to ask the grammar again, so with no provider it stops and says so. It
re-derives the CV's rows only. The letter shape is written per admissions cycle, which the sweep
does not have. Trigger for adding it: the first letter operation added to the grammar after this
plan.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_rederive_rules.py
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.documents.grammar import Rule
from apps.funding.models import OfficialSource, OfficialSourceSnapshot, ProgramStatement
from apps.research.decisions import DecisionsUnavailable

pytestmark = pytest.mark.django_db


def _statement(program, text):
    source = OfficialSource.objects.create(
        canonical_url=f"https://official.example/{uuid4()}",
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source, s3_key=f"official-sources/{uuid4()}", s3_version_id="1",
        sha256="0" * 64, final_url=source.canonical_url, redirect_chain=[],
        retrieved_at=timezone.now(), admissions_cycle="2027", content_type="text/html",
        byte_size=1,
    )
    return ProgramStatement.objects.create(
        program=program, snapshot=snapshot, kind="DOCUMENT", requirement="REQUIRED",
        text=text, label=text[:40],
    )


@pytest.fixture
def grammar(monkeypatch):
    """Stub both grammar requests at their module seams: every stored sentence
    reads as `rule` (a dict of Rule fields), or as nothing."""

    def install(rule=None, *, raises=None):
        def read_slots(found, **kwargs):
            if raises is not None:
                raise raises
            return ()

        def read_values(found, slots, **kwargs):
            if rule is None:
                return ()
            return tuple(Rule(index=i, sentence=c.text, confidence=0.95, **rule)
                         for i, c in enumerate(found))

        monkeypatch.setattr("apps.documents.grammar_questions.read_slots", read_slots)
        monkeypatch.setattr("apps.documents.grammar_values.read_values", read_values)

    return install


_PAGES_2 = {"document": "cv", "operation": "limit", "value": 2, "unit": "pages",
            "bound": "maximum"}


def test_a_stored_sentence_yields_its_rule_without_a_page(program_factory, grammar):
    """§6.5: when the grammar grows, every programme that ever stated the rule
    gets it -- without refetching a single page."""
    grammar(_PAGES_2)
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    assert [(r["key"], r["value"]) for r in program.cv_constraints] == [("max_pages", 2)]


def test_nothing_is_fetched(program_factory, grammar, monkeypatch):
    grammar()
    _statement(program_factory(), "Your CV may not exceed two pages.")

    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("the sweep refetched a page")

    monkeypatch.setattr("apps.research.discovery.retrieve_official_source", explode)
    call_command("rederive_rules", stdout=StringIO())


def test_a_dry_run_writes_nothing_and_reports_what_would_change(program_factory, grammar):
    grammar(_PAGES_2)
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    out = StringIO()
    call_command("rederive_rules", "--dry-run", stdout=out)
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert "max_pages" in out.getvalue()


def test_the_sweep_stops_on_its_budget_rather_than_running_unbounded(program_factory,
                                                                     settings):
    """CLAUDE.md names this exact sweep as the one that makes an unbounded model
    call per programme unless it adds its own limiter. The real ask() is used:
    the budget refuses before any request, so no key is needed."""
    settings.DECISIONS_RUN_TOKENS = 1
    for _ in range(3):
        _statement(program_factory(), "Your CV may not exceed two pages.")
    out = StringIO()
    call_command("rederive_rules", stdout=out)
    assert "budget" in out.getvalue().lower()


def test_with_no_provider_the_sweep_stops_and_writes_nothing(program_factory, grammar):
    """No frontier fallback here: the sweep exists to ask the grammar again."""
    # <!-- reconciled 2026-09-26: the kind Tasks 1-3 raise for a missing key -->
    grammar(raises=DecisionsUnavailable("OPENROUTER_API_KEY is not set", kind="not_configured"))
    program = program_factory()
    _statement(program, "Your CV may not exceed two pages.")
    out = StringIO()
    call_command("rederive_rules", stdout=out)
    program.refresh_from_db()
    assert program.cv_constraints == []
    assert "unavailable" in out.getvalue()


def test_a_programme_with_no_statements_is_skipped(program_factory, grammar):
    grammar(_PAGES_2)
    program = program_factory(cv_constraints=[{
        "rule_id": "PAGE-0-max_pages", "key": "max_pages", "value": 2,
        "enforcement": "ADVISORY_HIGH_RISK", "rule_text": "old", "source_url": "",
    }])
    call_command("rederive_rules", stdout=StringIO())
    program.refresh_from_db()
    # Untouched: an empty re-derivation here would erase rules a read DID produce.
    assert program.cv_constraints[0]["rule_text"] == "old"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rederive_rules.py -v`
Expected: FAIL with `CommandError: Unknown command: 'rederive_rules'`

- [ ] **Step 3: Write the command**

```python
# apps/documents/management/commands/rederive_rules.py
"""Re-ask the grammar over stored sentences, without refetching a page.

Spec §6.5. When an operation enters the grammar -- because the unapplied count
said the kind was real -- every programme that ever stated that rule should get
it. The sentences are already stored, so the questions are simply asked again.

**This is the sweep CLAUDE.md warns about.** It calls the decision layer
directly rather than through `read_program_page`, which is where the
per-programme limiter lives, so it carries its own budget or it is an unbounded
call per programme. It never falls back to the frontier judge: with no decision
provider it stops (2026-09-26 addendum §2 -- the fallback is the page read's,
not this sweep's). CV rows only; the letter shape is per cycle.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from apps.documents.derive import _THIRD_PARTY, Candidate, _grammar_rules, _write_program
from apps.documents.rule_sinks import (
    format_decision,
    resolve_conflicts,
    to_constraint_rules,
    to_directives,
    to_notes,
)
from apps.funding.models import Program, ProgramStatement
from apps.documents.grammar_questions import AskFn
from apps.research.decisions import (
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    run_budget,
)


# <!-- reconciled 2026-09-26: _grammar_rules takes AskFn | None -->
def _client() -> AskFn | None:
    """The decision client. A seam so a test injects without a network call."""
    return None


class Command(BaseCommand):
    help = "Re-derive every programme's CV rules from its stored sentences. Fetches nothing."

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
                # `heading` is empty until plan 2 stores heading_path on the
                # statement; the sentence stands alone, which is why this sweep
                # is run deliberately and its output read, not scheduled.
                Candidate(text=text, heading="", europass="europass" in text.lower(),
                          third_party=bool(_THIRD_PARTY.search(text)))
                for text, _ in statements
            )
            try:
                raw, _slots = _grammar_rules(candidates, language="", budget=budget,
                                             client=client)
            except DecisionBudgetExhausted as error:
                self.stdout.write(f"stopping: decision budget reached ({error})")
                break
            except DecisionsUnavailable as error:
                self.stdout.write(f"stopping: decision layer unavailable ({error})")
                break
            rules = resolve_conflicts(raw)
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
                # _write_program, not a bare update(): under RLS a role without
                # the grant updates zero rows and reports success.
                _write_program(program.id, **fields)

        self.stdout.write(
            f"{changed} programmes changed; {budget.spent} decision tokens spent"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/test_rederive_rules.py -v`
Expected: 6 passed

- [ ] **Step 5: Rewrite the record**

<!-- amended 2026-09-26: the frontier bullets stay, because they describe the fallback. -->

In `CLAUDE.md`, "LLM/AI security" section (re-resolve:
`grep -n "The CV-format decision is three readings" CLAUDE.md`, line 1207 at `f5cfac6`), insert
this bullet **directly above** that one, and change nothing in the bullets below it:

```markdown
- **Since 2026-09-26 a page is read by the typed grammar, and the three-reading judge below is the
  fallback.** With a decision provider configured (`OPENROUTER_API_KEY`, Jev through OpenRouter),
  `derive_page_rules` asks two typed requests per page plus one page-level request, over four
  slots and closed lists, and projects the answers onto sinks that already exist
  (`rule_sinks.py`). The bar is 0.85, with three phrasings on the Europass format. An uncertain
  reading becomes a note on the document; no person is waiting on it. With no key at all, the
  judge described below runs unchanged, so a missing key degrades cost, not correctness. An
  outage is not a missing key: it raises and the page's previous rows stand
  (`DecisionsUnavailable.kind`, `not_configured` vs `failed`, tells the two apart). The judge is deleted only when the page-corpus
  gates of the 2026-09-26 addendum §8 pass on Jev. Its measurements stay the record: the keyword
  rule's 61%, the Swiss supervisor's-CV attribution error, and the rule that a programme rule may
  not lower a key's enforcement. Design:
  `docs/superpowers/specs/2026-09-22-typed-decisions-and-multilingual-sources-design.md` §6, as
  amended by `2026-09-26-requirement-reader-addendum-design.md`.
- **The grammar is closed on purpose, and `unapplied` is a feature.** A page can state a
  requirement no operation carries, such as the first "publications in APA style". The sentence is
  kept, shown on the document and counted. It is never passed to the writing model as a free
  instruction: that is the door a hostile page would use to reach the generator, and the way the
  old attribution errors got in. When the count shows a kind is real, add the operation and its
  handler in code, then run `manage.py rederive_rules`. Every programme that ever stated the rule
  gets it without a page being refetched.
```

In `docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md`, append one line to the
blockquote at the top (after "…the measurements that set the bar."):

```markdown
> **Landed 2026-09-26** as `apps/documents/rule_sinks.py` and `derive._read_by_grammar` (plan
> `2026-09-23-decision-layer-and-rule-grammar.md` Tasks 8–10). The mechanism this document
> describes remains the fallback when no decision provider is configured, until the page-corpus
> gates of `2026-09-26-requirement-reader-addendum-design.md` §8 pass on Jev.
```

- [ ] **Step 6: Run everything**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && POSTGRES_DB=tehsil_requirement_reader uv run pytest && uv run bandit -c pyproject.toml -r apps config && uv run pip-audit && POSTGRES_DB=tehsil_requirement_reader uv run python manage.py makemigrations --check --dry-run`
Expected: all clean

- [ ] **Step 7: Commit**

```bash
git -C "$WT" add apps/documents/management/commands/rederive_rules.py \
  tests/documents/test_rederive_rules.py CLAUDE.md \
  docs/superpowers/specs/2026-09-13-format-decision-guarantee-design.md
uv run git -C "$WT" commit -m "feat: rederive_rules, and the record of the grammar beside its fallback

When an operation enters the grammar because the unapplied count said the kind
was real, every programme that ever stated that rule gets it -- from stored
sentences, with no page refetched. It carries its own budget, stops rather than
falling back when no provider is configured, skips a programme with no stored
sentences, and writes through _write_program so an RLS-blocked update fails
loudly.

CLAUDE.md records that the grammar reads pages and the three-reading judge is
the fallback until the page-corpus gates pass on Jev, and why unapplied is a
feature.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: The other Jev client folds into `decisions.ask()`

<!-- amended 2026-09-26: the ProviderUnavailable translation is KEPT -- research_fit/service.py's
_classify_safely catches only that, and dropping it would let an outage block a letter (D11). Its
asks pass record=False: DecisionRecord is shared-catalog data every tenant reads, and this question
carries a topic built from one student's record (the 2026-09-23 text would have cached it). The
test file is written out in full. The pinned model is OpenRouter's slug (addendum §2). -->

**Files:**
- Modify: `apps/documents/research_fit/jev.py`, `tests/documents/research_fit/test_jev.py`, `tests/documents/research_fit/test_live.py`

**Interfaces:**
- Consumes: `decisions.{ask, Noul, Choice, Answer, DecisionBudget, DecisionBudgetExhausted, DecisionsUnavailable}`, `settings.TYPESAFE_MODEL`
- Produces: `JevClassifier(*, client=None, budget=None, relevance_floor=0.5)`. The `api_key`, `post`
  and `input_tokens` members are removed, and `JEV_URL` and `JEV_MODEL` are removed. Its failure
  contract, `ProviderUnavailable`, is **unchanged**.

Master carries a second TypeSafe client (see the reconciliation section of the plan). This task
deletes its transport and keeps everything that makes it *this* classifier: `_ENTITY_PATTERNS`,
`entity_by_pattern`, the `entity_in_sentence` check and the `ClassifiedSentence` shape that
`service.py` consumes. The two questions become one `ask()` call per sentence under decision `D6`.

- [ ] **Step 0: Re-check the paths**

```bash
git -C "$WT" fetch origin && git -C "$WT" log --oneline -1 origin/master
grep -rn "JevClassifier\|ProviderUnavailable" apps/documents/research_fit/ tests/documents/research_fit/
```

Expected: `service.py` still builds `FrontierClassifier` unconditionally, and `_classify_safely`
(`service.py:239`) still catches `ProviderUnavailable` only. If `service.py` now builds
`JevClassifier`, this task changes the letter path and needs its own review round.

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/research_fit/test_jev.py
import pytest

from apps.documents.research_fit.classify import ClassifiedSentence
from apps.documents.research_fit.jev import JevClassifier, entity_by_pattern
from apps.research.decisions import (
    Answer,
    Choice,
    DecisionBudget,
    DecisionsUnavailable,
    Noul,
)
from apps.research.providers.base import ProviderUnavailable

# ask() reads and writes the DecisionRecord cache.
pytestmark = pytest.mark.django_db


def _client(answers_per_call, sent):
    """A provider client as decisions.ask() calls it: (state, questions, *, model, provider)."""

    def call(state, questions, *, model, provider):
        sent.append({"state": state, "questions": questions, "model": model})
        relevant, kind, confidence = answers_per_call.pop(0)
        return {
            "relevant": Answer(
                id="relevant", value=relevant >= 0.5,
                confidence=relevant if relevant >= 0.5 else 1 - relevant,
                probabilities={"true": relevant, "false": 1 - relevant},
                model=model, provider=provider, input_tokens=120,
            ),
            "kind": Answer(
                id="kind", value=kind, confidence=confidence,
                probabilities={kind: confidence}, model=model, provider=provider,
            ),
        }

    return call


_SENTENCES = (
    "Prof. Dr. A. Schmidt leads the Chair of Robotics.",
    "The canteen is open from 11 to 14.",
)


def test_one_ask_per_sentence_with_a_noul_and_a_choice():
    sent: list[dict[str, object]] = []
    budget = DecisionBudget()
    jev = JevClassifier(
        client=_client([(0.93, "research_group", 0.9), (0.02, "none", 0.95)], sent),
        budget=budget,
    )
    out = jev.classify(_SENTENCES, topic="legged locomotion")
    assert out == (
        ClassifiedSentence(
            index=0, relevance=0.93, kind="research_group", entity="Chair of Robotics"
        ),
        ClassifiedSentence(index=1, relevance=0.02, kind="none", entity=None),
    )
    assert sent[0]["state"] == _SENTENCES[0]
    questions = sent[0]["questions"]
    assert isinstance(questions["relevant"], Noul)
    assert "legged locomotion" in questions["relevant"].question
    assert isinstance(questions["kind"], Choice)
    assert set(questions["kind"].options) == {
        "research_group", "named_person", "module_or_track", "industry_partner", "none",
    }
    # What input_tokens counted before, the run budget counts now.
    assert budget.spent == 240


def test_a_kind_without_a_pattern_entity_falls_to_none():
    jev = JevClassifier(client=_client([(0.9, "research_group", 0.9)], []))
    out = jev.classify(("We work on legged locomotion.",), topic="t")
    assert out[0].kind == "none" and out[0].entity is None


def test_an_outage_is_provider_unavailable():
    """service._classify_safely catches ProviderUnavailable and nothing else: a
    classifier that is down must not block a letter (D11)."""

    def broken(state, questions, *, model, provider):
        raise DecisionsUnavailable("typesafe: ConnectTimeout")

    with pytest.raises(ProviderUnavailable):
        JevClassifier(client=broken).classify(_SENTENCES, topic="t")


def test_no_key_is_provider_unavailable(settings):
    settings.TYPESAFE_API_KEY = ""
    settings.OPENROUTER_API_KEY = ""
    with pytest.raises(ProviderUnavailable):
        JevClassifier().classify(_SENTENCES, topic="t")


def test_a_reply_missing_an_answer_is_provider_unavailable():
    """ask() refuses a reply that skipped a question; this caller still degrades."""

    def partial(state, questions, *, model, provider):
        return {"relevant": Answer(id="relevant", value=True, confidence=0.9,
                                   probabilities={"true": 0.9}, model=model,
                                   provider=provider)}

    with pytest.raises(ProviderUnavailable):
        JevClassifier(client=partial).classify(_SENTENCES, topic="t")


def test_a_spent_budget_is_provider_unavailable():
    with pytest.raises(ProviderUnavailable):
        JevClassifier(client=_client([], []), budget=DecisionBudget(limit_tokens=1)).classify(
            _SENTENCES, topic="t"
        )


def test_nothing_is_written_to_the_shared_decision_cache():
    """DecisionRecord is read by every tenant; a research-fit question carries
    a topic derived from one student's record."""
    from apps.research.models import DecisionRecord

    JevClassifier(client=_client([(0.9, "none", 0.9)], [])).classify(
        ("A sentence about robotics.",), topic="legged locomotion"
    )
    assert DecisionRecord.objects.count() == 0


def test_the_pinned_version_is_asked_for_not_the_alias(settings):
    """jev-latest moves under a tuned threshold. decisions.ask() pins the
    version for every caller; this one used to ask for the alias."""
    settings.TYPESAFE_MODEL = "typesafe/jev-1.13"
    sent: list[dict[str, object]] = []
    JevClassifier(client=_client([(0.9, "none", 0.9)], sent)).classify(
        ("A sentence about robotics.",), topic="t"
    )
    assert [s["model"] for s in sent] == ["typesafe/jev-1.13"]


@pytest.mark.parametrize("sentence,expected", [
    ("Prof. Dr. A. Schmidt leads the Chair of Robotics.", "Chair of Robotics"),
    ("The Institute for Energy Systems runs the grid lab.", "Institute for Energy Systems"),
    ("Robotik Laboratuvarı 2019'da kuruldu.", "Robotik Laboratuvarı"),
    ("Der Lehrstuhl für Robotik forscht an Laufrobotern.", "Lehrstuhl für Robotik"),
    ("Prof. Dr. B. Müller leitet die Gruppe.", "Prof. Dr. B. Müller"),
    ("The module Advanced Control Systems covers MPC.", "Advanced Control Systems"),
    ("We work on legged locomotion.", None),
])
def test_entity_by_pattern(sentence, expected):
    assert entity_by_pattern(sentence) == expected
```

Run: `POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/research_fit/test_jev.py -v`
Expected: FAIL with `TypeError: JevClassifier.__init__() got an unexpected keyword argument 'client'`

- [ ] **Step 2: Implement**

In `apps/documents/research_fit/jev.py`, replace the imports, delete `JEV_URL` and `JEV_MODEL`,
keep `_CAP`, `_ENTITY_PATTERNS`, `_KIND_CRITERIA` and `entity_by_pattern` unchanged, and replace
`class JevClassifier` entirely:

```python
from __future__ import annotations

import re
from collections.abc import Sequence

from apps.research.decisions import (
    Choice,
    DecisionBudget,
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    Noul,
    ask,
)
from apps.research.providers.base import ProviderUnavailable

from .classify import KIND_VALUES, ClassifiedSentence, entity_in_sentence
```

```python
class JevClassifier:
    """Research fit's classifier over decisions.ask(): the pinned version, the
    DecisionRecord cache, the run budget, and one place D6 is tuned."""

    def __init__(
        self,
        *,
        client: object | None = None,
        budget: DecisionBudget | None = None,
        relevance_floor: float = 0.5,
    ) -> None:
        self._client = client
        self._budget = budget
        self._floor = relevance_floor

    def _ask(self, sentence: str, topic: str) -> tuple[float, str]:
        answers = ask(
            sentence,
            {
                "relevant": Noul(
                    question=f"Does this sentence describe research or teaching work "
                             f"related to: {topic}?",
                ),
                # `none` has no description: it is the residual, and a
                # criterion for it would invite the classifier to argue for it.
                "kind": Choice(
                    question="What does this sentence name?",
                    options=tuple(_KIND_CRITERIA),
                    criteria={k: {"what": v} for k, v in _KIND_CRITERIA.items() if v},
                ),
            },
            decision="D6",
            budget=self._budget,
            client=self._client,  # type: ignore[arg-type]
            # Never cached. DecisionRecord is shared-catalog data every tenant
            # reads, and this question carries a topic built from ONE student's
            # record (guard_phrase keeps the student out of it, not the topic).
            # A per-student question has no reuse to buy with that exposure.
            record=False,
        )
        kind = answers["kind"].value
        # P(yes), not `.confidence`: a Noul's confidence is 1 - P(yes) when the
        # answer is False, and this caller's floor is a relevance, not a
        # certainty. Reading `.confidence` would score a confidently irrelevant
        # sentence as highly relevant.
        return float(answers["relevant"].probabilities.get("true", 0.0)), (
            str(kind) if kind in KIND_VALUES else "none"
        )

    def classify(self, sentences: Sequence[str], *, topic: str) -> tuple[ClassifiedSentence, ...]:
        out: list[ClassifiedSentence] = []
        try:
            for index, sentence in enumerate(sentences):
                relevance, kind = self._ask(sentence, topic)
                entity = (
                    entity_in_sentence(entity_by_pattern(sentence), sentence)
                    if kind != "none"
                    else None
                )
                out.append(
                    ClassifiedSentence(
                        index=index,
                        relevance=relevance,
                        kind=kind if entity else "none",
                        entity=entity,
                    )
                )
        except (DecisionsUnavailable, DecisionBudgetExhausted) as error:
            # service._classify_safely catches ProviderUnavailable and nothing
            # else: a classifier that is down must not block a letter (D11).
            # Translated here, never widened there. The type name only -- an
            # exception message may carry provider text.
            raise ProviderUnavailable(f"jev: {type(error).__name__}") from error
        return tuple(out)
```

Update the module docstring's first paragraph. Replace "typed decisions with probabilities, one
sentence per call, output free" with "typed decisions with probabilities through
`decisions.ask()` (Jev through OpenRouter, addendum §2), one sentence per ask". Keep the DPA
sentence and the entity paragraph.

In `tests/documents/research_fit/test_live.py`, change the skip condition to

```python
@pytest.mark.skipif(
    not (os.getenv("OPENROUTER_API_KEY") or os.getenv("TYPESAFE_API_KEY")),
    reason="no decision provider key set",
)
```

- [ ] **Step 3: Verify**

```bash
POSTGRES_DB=tehsil_requirement_reader uv run pytest tests/documents/research_fit/ -v
uv run ruff check apps config tests scripts && uv run mypy apps config
```

Expected: all pass (15 in `test_jev.py`). `test_live.py` still skips without a key. It is the
24-row EN/DE/TR gate, and it is now a measurement of the decision layer rather than of research fit.

- [ ] **Step 4: Commit**

```bash
git -C "$WT" add apps/documents/research_fit/jev.py tests/documents/research_fit/test_jev.py \
  tests/documents/research_fit/test_live.py
uv run git -C "$WT" commit -m "refactor(research-fit): one Jev client, not two

research_fit/jev.py built its own questions against its own transport, with
the jev-latest alias, no cache, no budget and no DecisionRecord row. It had no
caller -- service.py builds FrontierClassifier unconditionally -- so folding it
into decisions.ask() costs a test rewrite and no behaviour change. It gains the
pinned version, the run budget and one place D6 is tuned. It does not write the
shared DecisionRecord cache: every tenant reads that table, and this question
carries a topic built from one student's record. Its failure contract does not
change: every decision-layer failure is still ProviderUnavailable, the one
exception service._classify_safely catches.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---


---

## Left for later tasks, named so they are not lost

- **Which programme a sentence binds on a page that covers several** (addendum §6.6), and
  **binding a conditional rule to the student** (citizens only, EU only). The first needs D3's
  page-scope question, which is plan 3's unbuilt triage; the second needs the student's facts at
  pack time. Until both exist, a conditional rule is written as a note (Task 5's `CONDITION_KINDS`
  already records its kind), and a multi-programme page's rules are recorded at that page's tier
  by plan 4's merge. Neither is silently applied to every student.
- **The page-corpus gates** (addendum §8) run once plan 4's merge exists. The corpus
  (`docs/research/letter-page-corpus.csv`, its runner and its guard test) moves here from
  `claude/letter-gap-fixes` at the start of plan 4.

- **The key in infrastructure** (design §9a "Keys"). `OPENROUTER_API_KEY` reaches the worker as a
  Secrets Manager secret with an empty container, pinned in `tests/infra/test_template.py` the way
  `FIRECRAWL_API_KEY` is (`tests/infra/test_template.py:1524`, `infra/template.yaml:1583`). It is
  not in Tasks 1–3 because nothing deployed calls `ask()` yet. It is owed before a worker does.
- **The retry hand-off** (addendum §5.1). `DecisionsUnavailable(kind="failed")` carries what a
  `FetchAttempt.retry_after` needs, but `retry_due_fetches` still re-runs no reader
  (`apps/research/management/commands/retry_due_fetches.py`, docstring "What a successful retry
  does NOT do"). The reader side belongs to plan 2 / plan 4.
- **Task 13** (the research-fit Jev client) inherits this route: `research_fit/jev.py:24-25` still
  POSTs `https://api.typesafe.ai/v1/systemone` with `jev-latest`.


## Deferred: deleting the frontier judge (not a task of this plan)

<!-- amended 2026-09-26: moved out of Task 10 (addendum §2, §5.1). -->

**Trigger:** the page-corpus gates of addendum §8 pass on Jev. Every length must be exact on ≥ 90%
of dev pages and ≥ 85% of held-out pages, with no wrong value on any page and the required-or-not
answer right on every page, per language and per stratum. The run must go through the grammar path
with `OPENROUTER_API_KEY` set. Tasks 11's two live gates must also still pass. Until then the judge
is the fallback, and deleting it turns a missing key into a page nobody reads.

**Preconditions, checked before the first deletion:**
- `tests/documents/test_derive_grammar.py`'s "nothing typed is lost" tests pass **unchanged**.
  Those tests, not the frontier's, are what prove `form`, `naming`, `document_required`, `track`
  and `portfolio_led` survive.
- No caller relies on the fallback. `grep -rn "claude=" apps/ | grep -i derive` lists only
  `read_and_derive`.

**Deleted then, in one commit, so it reviews as a deletion:**
- From `apps/documents/derive.py`: `_read_by_judge`, the `not_configured` fallback in
  `derive_page_rules`' `except DecisionsUnavailable` branch (the raise then propagates),
  <!-- reconciled 2026-09-26 --> `derive_page_rules`' `parser` and `claude` parameters,
  `DerivationFailure`, `_DERIVABLE_KEY`, `_DERIVE_MAX_OUTPUT_TOKENS`, `_CLAUDE_MAX_TOKENS`,
  `_FORMAT_VALUE`, `_ACTION`, `_ORDER_VALUE`, `_ABOUT_WHOM`, `Derived`, `FormatVerdict`,
  `Directive`, `_SUBJECT`, `_MEASURE`, `_BOUND`, `_FORM`, `_NAMING`, `_REQUIRED`, `_TRACK`,
  `_BUNDLE`, `_SPACING`, `_PATH`, `_every_field_required` (from `claude/judge-schema-fix`),
  `LetterVerdict`, `Derivations`, `_SAMPLES`, `_QUESTION`, `_LETTER_QUESTION`, `_PHRASINGS`,
  `_claude_reading`, `_openai_reading`, `_with_one_retry`, `_judge`, `_FORMAT_ACTION_VALUE`,
  `_FORMAT_ACTION`, `_format_action`, `_OUTCOME_KIND`, `Outcome`, `_DISSENT`, `_agreed_by_all`,
  `_touches_cv`, `_touches_letter`, `outcomes`, `_surfaced`, `decide`, `_number_is_on_the_page`,
  `_verdicts_for`, `_MEASURE_KEY`, `_document_required_decision`, `decide_letter_shape`, and the
  re-imports of the letter_shape helpers the judge alone used.
- Kept: `candidates`, `Candidate`, `_CV_TERMS`, `_THIRD_PARTY`, `_document_pattern`,
  `_MAX_CANDIDATES`, `_write_program`, `Decision`, `_quote`, `detect_language`,
  `_grammar_rules`, `_read_by_grammar`. In `letter_shape.py`, `_naming_decision`, `_form_decision`
  and `_SAFE_FONT_FAMILY` stay, and in `grammar.py` the plausibility bands stay, because
  `rule_sinks` and `grammar_values` use them. <!-- reconciled 2026-09-26 -->
- `read_and_derive`'s `claude` parameter goes. `parser` stays until plan 2 removes the statement
  read.
- The judge's tests go: the frontier-mechanism tests in `tests/documents/test_derive.py` (the list
  in the 2026-09-23 Task 10 Step 4), the frontier eval gates
  `test_the_eval_corpus_has_no_wrong_action_and_few_abstentions` and
  `test_the_judge_reads_every_language_in_the_eval_sheet`, and every `decide_letter_shape` test in
  `tests/documents/test_letter_shape.py`. First, re-point every outcome-asserting test in those
  files at the grammar stub from `test_derive_grammar.py`.
- `tests/conftest.py`'s `_no_decision_provider_by_accident` stays. With no fallback it makes a
  missing key fail fast instead of making a paid call.
- CLAUDE.md: the frontier bullets under "LLM/AI security" become history. Keep the three
  measurements, and state the date the fallback ended.
- `ANTHROPIC_JUDGE_MODEL` stays only if another caller still reads it:
  `grep -rn ANTHROPIC_JUDGE_MODEL apps config`.

**What deleting it costs to reverse:** one revert. Nothing downstream reads which path produced a
row: `LetterShape`, `Program.cv_constraints`, `cv_directives` and the format switch are the same
sinks either way.


## Self-review against the addendum

Each addendum section this plan owns, and the task that implements it:

- **§2, the classifier.** OpenRouter base URL, key routing, pinned model and served model are Task 1. The record is Task 2. The cache, budget and outage policy are Task 3. The research-fit client is folded in by Task 13.
- **§5.1, failures.** The three failure kinds are Task 3, and Task 10 falls back to the frontier judge when no provider is configured.
  - Not here: the retry hand-off (plan 2 / plan 4), control-character stripping (§5.2), the shell rescue (§5.3) and language from text (§5.4). Those are the reader's, not the grammar's.
- **§6.1, every figure its own decision.** `figures_on_line` is Tasks 4–6. The Choice over `BOUNDS` and the space question are Task 6. A range is resolved to a floor plus a cap in Task 7, never by `min()`.
- **§6.2, floors keep a sink.** `min_chars` is Task 4, Part A: the field, migration `0050`, the constraint key, the check and the writer's sentence.
- **§6.3, nothing typed is lost.** The `form` and `naming` operations are Tasks 4–6, and the five fields' survival tests are Tasks 9–10. Deleting the old deciders is deferred with its trigger.
- **§6.4, the letter's language** writes `document_language` in Task 9.
- **§6.5, notes.** Tolerance is a topic; section and second-statement limits are `NOTE_BOUNDS`. All in Task 6.
- **§6.6, scope.** Condition kinds are Task 5. The rest is left for later, with the reason.
- **§7, cost.** Measured in Task 11 against a 3× bar.
- **§8, measurement.** The 48-, 77- and catalogue gates are Task 11; the page corpus is left for later.
- **§9, corrections.** Every stale reference is in Appendix A, and each is fixed in its task.

Review Focus: all five cases have a test, marked in Tasks 3, 6, 10 and 11.

Type consistency was checked by the reconciliation pass (Tasks 4–9 run against stubs, 142 tests). One more fix came after it: the grammar's seam is `grammar_questions.AskFn`, distinct from the provider transport `decisions.Client`.

## After this plan

In the addendum's §11 order, each gets its own plan written against master as it is then:
- **Plan 2 as amended** (the reader: sentence enumeration with context, D4/D5, the multilingual layer, and addendum §5.2–§5.4).
- **Plan 3's remainder** (`triage.py`: D1, D2, D3, D8).
- **Plan 4** (the per-page `PageRequirement` store, the tier merge, and wiring the reader to the funnel).
- **The full corpus run**, dev split first, then held-out.

## Appendix A — drafting notes: what the 2026-09-23 text got wrong, and what each task absorbs

Written by the three drafters and the reconciliation pass on 2026-09-26, against `origin/master` at `134b176`/`f5cfac6`. Each item is fixed in the task text above; they are kept so a reviewer can see why a task differs from the 2026-09-23 plan. Where a note below and a task disagree, the task wins.

### Drafting notes for Tasks 1–3


Drop-in replacement for `### Task 1` through the end of `### Task 3` in
`docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` (lines 90–1316 at `f5cfac64`).
Every exported name other plans consume is unchanged: `decisions.ask`, `DecisionRecord`,
`DecisionBudget`, `DecisionsUnavailable` (plus `Noul`, `Choice`, `Answer`, `provider_for`,
`month_tokens_spent`, `run_budget`). What is added is additive: `DecisionsUnavailable.kind` and
`.retry_after_seconds`, `Answer.served_model`, and two `DecisionRecord` columns (`served_model`,
`refused`).

#### Stale assumptions found in the original Tasks 1–3 (verified against `origin/master` at `f5cfac64`, 2026-09-26)

1. **Base branch** (plan:13) is `claude/fetch-spec-refresh`. Execute from `origin/master` in
   `/home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader`, test DB
   `POSTGRES_DB=tehsil_requirement_reader` (addendum §9).
2. **Settings insert point** (plan:22, 83, 96, 650) says "after `ANTHROPIC_JUDGE_MODEL`, line 120".
   `ANTHROPIC_JUDGE_MODEL` is at `config/settings/base.py:121`, and `TYPESAFE_API_KEY` already
   exists at `config/settings/base.py:147-149`. The new block replaces those three lines.
3. **`json` is not imported in `config/settings/base.py`** (plan:679 assumes it probably is).
   `base.py:1-4` imports `os`, `pathlib.Path` and `.database` only. `DECISIONS_PROVIDER`'s
   `json.loads` needs `import json`.
4. **Migration numbers** (plan:60-69, 77-78, 724, 951). `research` is at
   `0009_site_job_record_rls` (there is no `0006`; `0007` depends on `0005`). The decision
   layer's pair is **`0010_decision_record` + `0011_decision_record_rls`**.
5. **`catalog_ingestion` no longer exists** (plan:917-957). `funding/0049_catalog_grants.py`
   renamed every write policy to `runtime_engine_write` and dropped the role. A new catalogue table
   follows CLAUDE.md's recipe: `shared_catalog_select`, `runtime_engine_write`,
   `REVOKE ALL ... FROM runtime_web`, and the policy migration **depends on
   `("funding", "0049_catalog_grants")`**, which is what creates `runtime_engine` on a fresh
   superuser-migrated database. Without that edge, `CREATE POLICY ... TO runtime_engine` can run
   before the role exists.
6. **Task 2 Step 0 is already done** (plan:734-770). `runtime_connection` lives in
   `tests/conftest.py:275` and grants `SELECT ON ALL TABLES` (moved 2026-09-23). The step is
   deleted.
7. **The original write test proves nothing about the writer** (plan:806-826).
   `runtime_connection` is a member of neither runtime role (`tests/conftest.py:275-300`), so a
   refusal there is expected whatever the policy says. The writer is asserted through
   `role_connection("runtime_engine")` (allowed) and `role_connection("runtime_web")` (refused by
   the grant), exactly as `tests/research/test_site_job_record_rls.py:62-83` does.
8. **The adapter call shape is wrong** (plan:580-597). `system-one-adapter` 0.2.1 has no
   module-level `system_one(..., api_key=...)`. Its API is
   `SystemOneAdapterClient(structured_outputs=..., llm_answer_mode=...).system_one(state, questions,
   provider=..., model=...)`, and keys come from the provider SDKs' own environment variables
   (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). `settings.ANTHROPIC_API_KEY` and
   `settings.OPENAI_API_KEY` do not exist: `config/settings/base.py:118-120` says the key is read
   from the environment "at use time, never a setting". Read from the 0.2.1 source,
   `_client.py:334-343, 466-473`.
9. **`_from_sdk` guessed attribute access** (plan:528-547, `# type: ignore`). The SDK is typed:
   `SystemOneResponse.choices` / `.nouls` are typed dicts and `.usage.input_tokens` is `int | None`
   (0.7.1 `_core/response_types.py`). The response's `model` is the served snapshot
   (`typesafe/jev-1.13-20260917` through OpenRouter), and the original recorded only the
   requested id.
10. **`MAX_STATE_TOKENS = 64_000`** (plan:324). OpenRouter's endpoint for `typesafe/jev-1.13`
    lists `context_length: 32000` (public `GET /api/v1/models/typesafe/jev-1.13/endpoints`,
    2026-09-26), so the ceiling is 32,000.
11. **`TYPESAFE_MODEL` default `jev-1.13.0`** (plan:660) is TypeSafe's direct id. Through
    OpenRouter the exact id is **`typesafe/jev-1.13`**. OpenRouter's SDK guide: "IDs that already
    carry an author prefix, such as `typesafe/jev-1.13`, are used as-is", and the response `model`
    is the dated snapshot.
12. **Task 1 "Expected: 11 passed"** (plan:690). The file holds 12 tests.
13. **Task 3 Step 4 is false as written** (plan:1291-1292: "Task 1's file unchanged"). From Task 3
    on, `ask()` defaults to `record=True` and reads `DecisionRecord`, but Task 1's tests carry no
    `django_db` mark. Every one that calls `ask()` would fail with "Database access not allowed".
    The amended Task 1 file sets `pytestmark = pytest.mark.django_db` from the start.
14. **`DecisionsUnavailable` has one meaning** (plan:44-46, 333-338). Addendum §5.1 needs three:
    not configured (the caller runs the frontier judge), failed (`decision_failed` plus a retry),
    and refused (recorded, never retried). The fix is `.kind`, not new class names.
15. **Addendum §10's "`DECISIONS_BASE_URL` changes, and nothing else does"** is off by one env
    var. Moving to TypeSafe directly also changes `TYPESAFE_MODEL`, because TypeSafe's ids carry
    no `typesafe/` prefix.
16. **Co-author line** (plan:715, 986, 1313) says "Claude Opus 5". It is now
    `Claude Opus 5.5 (1M context)`.

Replace these header rows as well, so the plan does not contradict itself:
- **File Structure** (plan:77-78): `0010_decision_record.py` (the table) and
  `0011_decision_record_rls.py` (`shared_catalog_select` + `runtime_engine_write` + revoke from
  `runtime_web`).
- **File Structure** (plan:83): `config/settings/base.py` gets the decision-layer settings in
  place of the `TYPESAFE_API_KEY` lines at 147-149.
- **Global Constraints** (plan:56): "`OPENROUTER_API_KEY` and `TYPESAFE_API_KEY` never have a
  settings default…"
- **Global Constraints** (plan:60-69): research tip is `0009`, so this plan takes `0010`/`0011`.

---


### Drafting notes for Tasks 4–7


Replaces `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` Tasks 4–7
(lines 1318–3131 at `f5cfac6`). Everything outside these four tasks stands, except the deltas
listed under "What Tasks 8–11 must absorb" below.

**Base:** `origin/master` at execution time, with `claude/judge-schema-fix` already merged
(addendum §11 step 1 — Task 6 Step 0 checks for it). **Test database:**
`POSTGRES_DB=tehsil_requirement_reader`. **Checks after every task** (Global Constraints):
`uv run ruff check apps config tests scripts`, `uv run mypy apps config`,
`POSTGRES_DB=tehsil_requirement_reader uv run pytest`, and
`uv run python manage.py makemigrations --check --dry-run`. Never `ruff format`.
<!-- reconciled 2026-09-26 --> **Git:** `WT=/home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader`;
every git command is `git -C "$WT" ...` and every commit `uv run git -C "$WT" commit`, as in
Tasks 1–3 and 8–13 — the shell's cwd resets to the main checkout between calls.

#### Stale assumptions found in the original Tasks 4–7 (fixed below)

Plan line numbers are `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` at
`f5cfac6`; code line numbers are `origin/master` at `134b176`.

1. **Import cycle.** `grammar_questions.py` (plan:1867) and `grammar_values.py` (plan:2388) do
   `from .derive import Candidate` at module level, and Task 10's import block (plan:4137–4138)
   makes `derive.py` import both. Whichever loads first fails with "cannot import name
   Candidate from partially initialized module". Fixed: `Candidate` is imported under
   `TYPE_CHECKING` only (it is used only in annotations).
2. **mypy is `strict = true`** (`pyproject.toml:74–76`) and the original code does not pass it:
   `_ask(state, questions, **kwargs)` is unannotated (plan:2041); `Rule(**base, ...)` with
   `base = dict(...)` is `**dict[str, object]` against typed fields (plan:2642–2667);
   `client: object | None` is then called. Fixed with the plan's own `decisions.Client` alias
   and a typed `_Draft` in place of the dict.
3. **`numbers_in` misreads decimals and model names** (plan:2404–2436): `\d[\d.,]*` with every
   `.`/`,` stripped turns "2,5 cm" into 25, "1.5" into 15, and finds the 4 in "A4". Replaced by
   `letter_terms.figures_on_line` (addendum §6.1, §9).
4. **Task 4's letter-sink test fails as written** (plan:1377): `("style", "signed")` is not a
   `STYLE_VALUES` member, so `sink_for` returns `""`, which is not a `LetterShape` field. The
   value is `signed_declaration`. Its `import pytest` is also unused (F401 under
   `ruff check tests`).
5. **`resolve_conflicts` crashes three ways** (plan:3072–3099): `{r.value for r in group}` raises
   `TypeError: unhashable type: 'list'` on a two-language rule (Task 6 emits `["en", "fr"]`);
   `min(v for v in values if isinstance(v, int))` skips a `1.5`-page cap; and
   `next(r for r in applied[bucket] if r.value == disputed[bucket])` raises `StopIteration`
   when the safer value is `any` and no sentence stated `any` (europass_required vs
   europass_preferred). Its "the tighter limit" also applies to floors, where the smaller is the
   unsafe side.
6. **A floor had no sink** — `derive.py:1211–1216` drops every non-word floor because "no
   column carries it", and says why: writing a source for a bound nothing enforces made the
   requirements pane show it as enforced (PR review 2026-09-22). Adding `min_chars` as a field
   alone would reopen that. Task 4 Part A therefore adds the column **and** the checker, the
   refusal, the aim and the writer's sentence.
7. **Plausibility bands live in `derive.py:1009–1028`**, the module Task 10 cuts to a third.
   Moved to `grammar.py` (Task 4) and re-imported by `derive.py`, so neither the judge nor the
   grammar can lose them.
8. **Two of Task 6's own tests failed against its own code**, found by running the plan's code
   against stubs: `font_candidates` (plan:2452–2462) skips a capitalised run whose first word is
   "Use", so "Use Times New Roman" yields nothing; `_format_value` (plan:2771–2798) counts a
   phrasing below the bar as a vote (two-of-three "unsure") and treats required + preferred as
   agreement (three different verdicts applied `europass_preferred`). Both fixed below.
9. Base branch `claude/fetch-spec-refresh` and DB `tehsil_decisions` → `origin/master` and
   `tehsil_requirement_reader` (addendum §9). Commit trailers → `Claude Opus 5.5`.
10. **Not fixed here, flagged:** Task 4's `_letter_sink("language")` returns `"document_language"`
   (plan:1639), which is not a `LetterShape` field, and Task 9 passes it into `LetterShape(...)`
   (plan:3708) — addendum §6.4; Task 9 adds the field. Task 10 deletes the frontier judge that
   addendum §5.1 keeps as the no-key fallback; Task 10 keeps it. <!-- reconciled 2026-09-26 -->
   The `form` and `naming` operations (addendum §6.3) are now in Task 4 (`FORM_VALUES`,
   `NAMING_VALUES`, their sinks) and asked in Tasks 5–6, because Task 9 projects them.
11. <!-- reconciled 2026-09-26 --> **Tolerance is not a bound.** "An exceedance of more than 10
   percent" states no length of the document, so the sentence is a `topic` (Task 5's operation
   question says so) and none of its figures is asked a bound. A section limit and another
   statement's length ARE figures of a length sentence, so they are bounds — `NOTE_BOUNDS` — and
   each yields a `topic` rule carrying the sentence instead of a cap or floor. The sentence-level
   `limit_kind` question and `LIMIT_KINDS` of the first draft are gone: one per-figure Choice
   carries it, so "800 words, plus a 250-word statement" keeps its cap.

#### What Tasks 8–11 must absorb

Every name Tasks 8–13 import still exists with its signature: `DOCUMENTS`, `OPERATIONS`,
`STYLE_VALUES`, `CONDITION_KINDS`, `UNITS`, `FORMAT_VERDICTS`, `Slotted`, `Rule`, `SINKS`,
`sink_for`, `SLOT_BAR`, `CHUNK`, `slot_questions`, `slot_state`, `read_slots`, `value_questions`,
`read_values`, `FORMAT_EXAMPLES`, `font_candidates`, `language_candidates`, `resolve_conflicts`.
**Removed:** `grammar_values.numbers_in` (nothing after Task 6 imports it). **Added:**
<!-- reconciled 2026-09-26 -->
`grammar.BOUNDS`, `grammar.NOTE_BOUNDS`, `grammar.FORM_VALUES`, `grammar.NAMING_VALUES`,
`grammar.limit_sink`, the `form` and `naming` operations, `grammar_values.value_state`,
`letter_terms.Figure`, `letter_terms.figures_on_line`, `LetterShape.min_chars`,
`ApplicationPrompt.letter_min_chars` (funding `0050`), constraint key `min_chars_excl_spaces`.
There is no `LIMIT_KINDS`.

<!-- reconciled 2026-09-26 -->
`Rule` gains three defaulted fields: **`bound: str = ""`** (`maximum` | `minimum` |
`approximate` on a limit; the `NOTE_BOUNDS` member on a topic cut from a length sentence),
**`figure: int | None = None`** (which figure of its sentence, in `figures_on_line` order; `None`
when the rule came from no figure) and **`excl_spaces: bool = False`** (a character figure whose
count leaves spaces out). `Rule.detail` is only ever a style's sub-value. **One limit sentence
now yields several rules** — a range, two units, a cap beside a note-bound topic, a note beside
applied rules, a conflict pair.

- **Task 8** `to_constraint_rules`: for `operation == "limit"`, the key is `cv_limit_key(rule)`,
  which is `limit_sink("cv", rule.bound or "maximum", rule.unit, excl_spaces=rule.excl_spaces)`,
  skipped when `""`, instead of `sink_for("cv", rule.operation, rule.unit or rule.value)`
  (plan:3372). Ids stay `PAGE-{index}-{key[:9]}`; `to_notes` writes one note per
  `(index, kind)`, because a sentence's figures share its quote. Its tests' `_rule(...)` helper
  needs no change (`bound` defaults to `""`, read as a cap).
- **Task 9** `to_letter_shape`: the limit branch (plan:3697) becomes
  `field = limit_sink("motivation_letter", rule.bound or "maximum", rule.unit or "pages",
  excl_spaces=rule.excl_spaces)`; floors land on `min_words` / `min_chars` (a character floor
  without spaces lands on `min_chars`, which is measured without spaces); `float(...)` for
  `max_pages`, `int(...)` otherwise; `_LETTER_LIMIT_FIELD` is deleted. The plausibility bands are
  imported from `grammar`, never moved a second time. Separately (addendum §6.4, pre-existing):
  `document_language` must not reach `LetterShape(**fields)` until Task 9 adds the field. A
  tolerance, per-section cap or second statement arrives as `operation="topic"` and already
  lands in `written_requirements`.
- **Task 10**: keep `from .grammar import _IMPLAUSIBLE_CAP, _IMPLAUSIBLE_MAX` in `derive.py`
  while `decide_letter_shape` exists and drop it with it (else F401). Never add a module-level
  `from .derive import ...` to `grammar_questions.py` or `grammar_values.py`.
- **Task 11**: the format gate's `{r.index: r for r in read_values(...)}` (plan:4372) is still
  right for format rows (one rule per format sentence); any gate over limits must group by
  `index`.

---


### Drafting notes for Tasks 8–13


Replaces `docs/superpowers/plans/2026-09-23-decision-layer-and-rule-grammar.md` lines 3132–4848
(Tasks 8–13) and adds one deferred section after Task 13. Written against `origin/master` at
`f5cfac6` (addendum on top of `134b176`), read-only. Amendments come from
`docs/superpowers/specs/2026-09-26-requirement-reader-addendum-design.md` §2, §5.1, §6.1–§6.5, §8, §9.

<!-- amended 2026-09-26: the whole block below is new; it is the contract these six tasks consume. -->

#### Read before Task 8: what these tasks need from Tasks 1–7

#### The vocabulary Task 4 must contain (for the drafter of Tasks 4–7)

Tasks 8–12 import these names and fail at import or at their first test without them:

1. **`OPERATIONS` gains `form` and `naming`** (addendum §6.3). The `Operation` Literal becomes
   `limit, language, format, include, order, emphasise, style, topic, student_action, form, naming, other`
   — twelve values; Task 4's `test_the_operations_are_the_closed_list_the_spec_names` lists them.
2. **`FORM_VALUES = ("essay", "formal_letter", "portal_form")`** and
   **`NAMING_VALUES = ("required", "invited", "forbidden")`** — the old `LetterVerdict` literals
   minus `"none"` (`derive.py:300-301`). Task 6 asks each over its list plus a `none` escape; `none`
   is `unapplied`.
3. **`sink_for("motivation_letter", "form", v)` → `"form"`** when `v in FORM_VALUES`, else `""`;
   **`sink_for("motivation_letter", "naming", v)` → `"naming"`** likewise. Both are `""` for the CV.
   `SINKS` gains `"form"` and `"naming"`.
<!-- reconciled 2026-09-26: items 4-8 and 11 now state what Tasks 1-7 actually produce -->
4. **`BOUNDS = ("maximum", "minimum", "approximate", "section_limit", "another_statement",
   "not_a_limit")`** and **`NOTE_BOUNDS = frozenset({"section_limit", "another_statement"})`**
   (addendum §6.1, §6.5). Task 6's per-figure Choice asks over `BOUNDS`. **Tolerance is not a
   bound:** a tolerance sentence ("an exceedance of more than 10 percent") is a `topic` by
   operation (Task 5's operation question says so), so no figure of it is ever asked a bound.
5. **`Rule` gains `bound: str = ""`, `figure: int | None = None` and `excl_spaces: bool =
   False`.** `bound` is `maximum` | `minimum` | `approximate` on a `limit` rule, the
   `NOTE_BOUNDS` member on a topic cut from a length sentence, and `""` everywhere else.
   `figure` is which figure of the sentence (`letter_terms.figures_on_line` order), `None` off a
   figure. `excl_spaces` is the answer to the per-figure Noul "does the count include spaces?",
   `True` only for a CV character figure whose count excludes spaces at the bar. `detail` is only
   ever a style's sub-value.
6. **Task 6's output contract** (not its question ids — no test in Tasks 8–12 scripts a Task 6
   question id): one `Rule` per figure, all sharing the sentence's `index`; a `not_a_limit` figure
   yields no rule; a figure whose bound is in `NOTE_BOUNDS` yields, once per sentence, a **`topic`**
   rule whose `value` is the sentence, `bound` that member, `unit` `""` — applied on the letter
   (sink `written_requirements`), `unapplied` on the CV (no topic sink); a `limit` rule's `value` is
   the picked figure (`int`, or `float` for a decimal page count).
7. **Task 7's `resolve_conflicts`**: a floor and a cap never contradict each other, so `_bucket`
   is `(document, operation, unit, "floor" if bound == "minimum" else "cap", excl_spaces)`; a
   note-bound topic never enters a bucket (`topic` is set-valued); between two floors the
   **larger** wins; `form` and `naming` are **not** in `_SINGLE_VALUED` — their safer side is
   settled by the projection (Task 9) with the same two functions the frontier path uses, so the
   two paths cannot disagree about it.
8. **`min_chars`**, all created by Task 4 Part A: `LetterShape.min_chars: int | None = None`,
   `ApplicationPrompt.letter_min_chars` (`PositiveIntegerField(null=True, blank=True)`, funding
   migration **`0050_applicationprompt_letter_min_chars`**; these tasks create no migration),
   `apply_derived_shape` writes `"letter_min_chars": shape.min_chars`, `shape_from_prompt` reads it
   back, and the letter check enforces it as constraint key **`min_chars_excl_spaces`** — a floor
   measured WITHOUT spaces, the stricter reading of any page's floor. Task 9 Step 0 checks all
   four exist. The plausibility bands `_IMPLAUSIBLE_CAP` / `_IMPLAUSIBLE_MAX` live in `grammar.py`
   (Task 4 moved them; `derive.py` re-imports them).
9. **Two names Task 9 owns**: `LetterShape.document_language` (addendum §6.4) and
   `grammar_questions.PageFacts` / `read_page_facts` / `page_questions`. Tasks 4–7 do not define
   them. Task 4's `test_every_letter_sink_is_a_real_letter_shape_field` does not assert that
   `language`'s sink is a `LetterShape` field — the field arrives in Task 9. The canonical length
   mapping is `grammar.limit_sink(document, bound, unit, *, excl_spaces=False)`; Tasks 8 and 9 call
   it rather than keeping their own unit maps.
10. **The import cycle.** Tasks 5 and 6 import `Candidate` from `derive`, so `derive` imports the
    grammar modules inside a function (Task 10), never at module top. Keep `rule_sinks.py` free of
    any import of `derive`.
11. **From Tasks 1–3, as amended:** `ask(..., record: bool = True, client: AskFn | None = None)`
    (Task 5 already passes both), `decisions.Client`, a Noul `Answer.probabilities` keyed
    `"true"`, `run_budget()`, `DecisionBudget(limit_tokens=, spent=)`, `DecisionBudgetExhausted`,
    and `DecisionsUnavailable(message, *, kind=...)` whose missing-key raises carry
    **`kind="not_configured"`** (Task 1's `test_an_absent_key_raises_rather_than_degrading` pins
    it). There is no `DecisionsNotConfigured` subclass: Tasks 1–3 chose `.kind` over new class
    names, and Task 10 reads the kind.

#### Global Constraints, amended

- **The frontier judge is the fallback, not deleted** (addendum §2, §5.1). Replace the first
  Global Constraint's "never as a fallback" with: *"No frontier model classifies where a decision
  provider is configured. With no provider key at all, `derive_page_rules` falls back to the
  existing frontier judge, so a missing key degrades cost, not correctness. The judge is deleted
  only by the deferred cleanup after Task 13, on the trigger stated there."* `decisions.ask()`
  itself still never degrades (Task 1's `test_an_absent_key_raises_rather_than_degrading` stands);
  the one caller that catches the raise is `derive_page_rules`.
- Test database: **`POSTGRES_DB=tehsil_requirement_reader`**, replacing `tehsil_decisions` in
  every command.
- Git: the executing worktree is `$WT` (for this session,
  `/home/orkhan/Desktop/tehsil_agent/.worktrees/requirement-reader`). Every git command uses
  `git -C "$WT"` — the shell's cwd resets to the main checkout between calls.

#### Stale assumptions in the 2026-09-23 text of Tasks 8–13, re-resolved against `f5cfac6`

- Task 10 "Replace `derive_page_rules` (`apps/documents/derive.py:1305`)" — it is at
  `apps/documents/derive.py:1363`.
- Task 10 imports `read_slots` / `read_values` at the top of `derive.py`; `grammar_questions.py`
  imports `Candidate` from `derive` (Task 5, plan line 1866) — a cycle that fails at import with
  "partially initialized module". Now imported inside the function.
- Task 10's `program_rules.py` snippet reads `result.snapshot.unreadable`; master reads
  `result.snapshot.readability == _READABLE` (`apps/documents/program_rules.py:24`, `:69`).
- Task 10 asserts the transaction no longer spans the fetch. It does: `read_and_derive` opens one
  `transaction.atomic()` around both calls (`program_rules.py:61`), and `read_program_page` nests
  its own (`apps/research/reader.py:754`). Kept as is; moving it is plan 2's.
- Task 10 drops the no-candidates branch that writes `NO_CV_FOUND` (`derive.py:1398-1402`), which
  `tests/documents/test_derive.py:370-395` pins. Kept.
- Task 10's `test_the_old_judge_is_gone` and `test_derive_makes_no_frontier_model_call` contradict
  addendum §2/§5.1. Dropped; the deletion moves to the deferred cleanup.
- Task 10's and Task 12's test helpers build `OfficialSource(first_seen=...)` and
  `OfficialSourceSnapshot(fetched_at=, content_sha256=, retrieval_status=)`. None of those are
  fields. Master's working factory is `tests/documents/test_derive.py:59-77`, copied below.
- Task 9 passes `document_language` into `LetterShape`, which has no such field
  (`apps/documents/letter_shape.py:43-73`), and `apply_derived_shape` hard-codes `"en"` on create
  and never updates it (`letter_shape.py:122`). Fixed in Task 9.
- Task 9 dropped three guards the frontier path has: the plausibility bands
  (`derive.py:1009-1028`), the font-size and margin ranges (`LetterVerdict` `ge=4, le=40` and
  `ge=0.1, le=10`, `derive.py:341,343`), and `fullmatch` on the font family (`derive.py:951` is
  used with `fullmatch`; the plan used `.match`, which lets `"Arial\n"` through). All restored.
- Task 11's format gate maps the sheet to `europass_preferred`, a label the sheet does not have.
  `docs/research/cv-format-eval.csv` carries `europass` (26), `standard` (8), `none` (6),
  `unapplied` (3), `constraint` (2), `include`, `order`, `emphasise` (1 each), and the frontier gate
  scores it by action (`tests/documents/test_derive.py:1237-1300`). It also built `Candidate`s
  without the third-party regex that `swiss-3rd` needs. Rescored below.
- Task 12 writes with `Program.objects.filter(...).update(...)`, which matches zero rows under RLS
  and reports success (CLAUDE.md, "Row-level security"). It now uses `derive._write_program`. It
  also crashed on a missing key. It now stops with a message.
- Task 13 drops the `ProviderUnavailable` translation, but `research_fit/service.py:239-248`
  (`_classify_safely`) catches `ProviderUnavailable` and nothing else, so an outage would block a
  letter (D11). The translation is kept. Its test used an undefined `_recording` and positional
  `Choice(...)` arguments. Both are rewritten in full. Its asks would also have written
  `DecisionRecord`, a table every tenant reads, keyed on a question carrying a topic built from one
  student's record. They now pass `record=False`.
- Catalogue sizes: `cv-rules.csv` 93, `cv-style-rules.csv` 50, `letter-rules.csv` 73 (CLAUDE.md
  still says 33 and 71).

---

