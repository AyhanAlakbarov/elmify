# Gap interview intake: the trust boundary and the audit trail

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `apps/documents/gaps.py` a caller that turns a submitted form into ledger writes without trusting the form, and audits every fact it writes.

**Architecture:** One new module, `apps/documents/gap_intake.py`, with two functions. `field_name` is the naming contract between whatever renders the form and this module — both sides call it, neither invents the string. `submit_answers` re-derives the question list from `gap_questions` and reads the submission **only** through `field_name`, so a submitted `(fact_id, payload_key)` pair that no current question produced is never looked at. Each written fact gets one `AuditEvent`.

**Tech Stack:** Django 5, Postgres, pytest + pytest-django, uv.

**Spec:** `docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md` (step 1 of 3; types 3, 4 and 5 — the deterministic checks). The checks themselves shipped in `docs/superpowers/plans/2026-08-30-gap-interview-deterministic-checks.md`; this plan is the caller that plan said it was owed.

## Global Constraints

- **Backend only.** No template, no view, no URL, no HTML, no CSS. The presentation layer is a separate later change. This plan produces a module a view calls in ten lines.
- **No model call anywhere in this change**, so no rate limiter is owed. Do not cite this module — or `gaps.py` — as evidence that a limiter exists. A change that later hosts question types 1, 2 or 6 owes `apps/ratelimit.py::rate_limited` in the same change (`CLAUDE.md` § LLM/AI security).
- **Do not add or alter question types.** `gaps.py` is not modified by this plan at all.
- **Authorisation is not in scope and must not be faked here.** `student` is taken on trust exactly as `answer_questions` takes it. Only the HTTP layer can resolve it (`apps.tenancy.services.current_membership`), and there is no HTTP layer yet.
- **Every question is skippable.** A blank answer is a skip. Nothing in this module may require a field to be present or non-empty.
- Commit convention: conventional commits, subject in the imperative, body explains *why*.
- Validation gate, all of which must pass before the branch is done:
  - `POSTGRES_DB=tehsil_gap_intake uv run pytest`
  - `uv run ruff check .`  (**there is no `ruff format` in this repo — do not run it**)
  - `uv run mypy apps config`
  - `uv run bandit -c pyproject.toml -r apps config`
  - `uv run python manage.py makemigrations --check --dry-run` (expect no changes; this plan adds no model fields)
- Worktree: `.worktrees/gap-intake`, branch `claude/gap-interview-intake`, based on `origin/master` (`9139da6`). Commit with `git -C .worktrees/gap-intake` — a bare `git` command from the parent directory lands on the wrong branch.
- The test database name is per-worktree. Always prefix pytest with `POSTGRES_DB=tehsil_gap_intake`; the shared `test_tehsil` wedges across parallel sessions.

## File Structure

| File | Responsibility |
|---|---|
| `apps/documents/gap_intake.py` *(create)* | The two functions. Depends on `gaps.py` (questions and writes), `audit.py` (events), `models.py` (return type), `tenancy.models` (Membership). Nothing depends on it yet. |
| `tests/documents/test_gap_intake.py` *(create)* | Both tasks' tests. Mirrors `tests/documents/test_gaps.py`'s fixture shape so a reader moving between them sees one idiom. |

`apps/documents/gaps.py` is **not** modified. Its module docstring enumerates what its caller owes; this plan satisfies two of those three obligations from outside, which is what that docstring asks for. Putting them inside `gaps.py` would also pull `apps.funding.models` (via `audit.py`) into what is currently a pure ledger module.

---

### Task 1: The naming contract and the trust boundary

**Files:**
- Create: `apps/documents/gap_intake.py`
- Test: `tests/documents/test_gap_intake.py`

**Interfaces:**
- Consumes: `apps.documents.gaps.GapQuestion` (frozen dataclass with `.kind`, `.fact_id: UUID`, `.payload_key: str`, `.prompt`, `.evidence`); `apps.documents.gaps.gap_questions(student: Membership) -> tuple[GapQuestion, ...]`; `apps.documents.gaps.answer_questions(answers: Sequence[tuple[GapQuestion, str]], *, student: Membership) -> tuple[VerifiedFact, ...]`.
- Produces: `field_name(question: GapQuestion) -> str` and `submit_answers(submitted: Mapping[str, str], *, student: Membership) -> tuple[VerifiedFact, ...]`. Task 2 adds the audit call inside `submit_answers` and a keyword-only `actor: Membership | None = None` alongside it. The parameter arrives in Task 2 rather than here because nothing in this task reads it, and a shipped-but-unused parameter is dead code; adding a keyword argument with a default is backward compatible, so no Task 1 caller breaks.

- [x] **Step 1: Write the failing tests**

Create `tests/documents/test_gap_intake.py`:

```python
import pytest

from apps.documents.gap_intake import field_name, submit_answers
from apps.documents.gaps import gap_questions
from apps.documents.models import VerifiedFact
from apps.documents.verification import unsuperseded_facts
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="intake-student")
        yield Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )


def _fact(student, category, payload, *, tier=VerifiedFact.SourceTier.STUDENT_STATEMENT):
    return VerifiedFact.objects.create(
        student=student,
        category=category,
        payload=payload,
        source_tier=tier,
        source_ref="upload:cv",
        confirmed_by=None,
        created_by=student,
    )


def _degree_without_a_grade(student):
    return _fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc Chemistry", "institution_original": "EPFL"},
    )


def test_an_answer_keyed_by_its_field_name_is_written(student):
    degree = _degree_without_a_grade(student)

    written = submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    assert [fact.payload["grade_native"] for fact in written] == ["16.45/20.0"]
    assert written[0].supersedes_id == degree.id


def test_a_payload_key_no_question_asked_about_is_ignored(student):
    """The whole point of re-deriving the questions.

    EDUCATION carries grade_conversion, so answer_questions would accept it --
    payload_keys() is category-wide. No detector asks for it, and gaps.py says
    in as many words that a conversion is a claim nobody made. A submission
    naming it must therefore reach nothing.
    """
    degree = _degree_without_a_grade(student)

    written = submit_answers({f"{degree.id}:grade_conversion": "3.9/4.0"}, student=student)

    assert written == ()
    assert unsuperseded_facts(student).get(id=degree.id).payload.get("grade_conversion") is None


def test_a_field_name_for_a_superseded_fact_is_ignored(student):
    """The ledger can move between the render and the submit -- a second tab, a
    counsellor edit, a double submit. A name for a fact that is no longer the
    tip of its chain matches no re-derived question and is dropped, rather than
    landing on whatever took its place.
    """
    degree = _degree_without_a_grade(student)
    submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    written = submit_answers({f"{degree.id}:grade_native": "18.0/20.0"}, student=student)

    assert written == ()


def test_another_student_s_fact_id_is_ignored(student, agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        other_user = django_user_model.objects.create(username="intake-other")
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT, active=True
        )
    their_degree = _degree_without_a_grade(other)
    _degree_without_a_grade(student)

    written = submit_answers({f"{their_degree.id}:grade_native": "20.0/20.0"}, student=student)

    assert written == ()
    assert unsuperseded_facts(other).get(id=their_degree.id).payload.get("grade_native") is None


def test_a_blank_answer_writes_nothing(student):
    """Every question is skippable, and a form of blanks is an ordinary
    outcome rather than an error.
    """
    degree = _degree_without_a_grade(student)

    assert submit_answers({f"{degree.id}:grade_native": "   "}, student=student) == ()


def test_a_submission_with_no_recognised_key_at_all_writes_nothing(student):
    """A CSRF token and a submit button are in every real submission."""
    _degree_without_a_grade(student)

    written = submit_answers(
        {"csrfmiddlewaretoken": "abc123", "submit": "Save"}, student=student
    )

    assert written == ()


def test_every_question_can_be_named_and_answered(student):
    """field_name is the contract, so building a submission out of it must
    reach every question gap_questions emits -- not most of them.
    """
    _fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    _degree_without_a_grade(student)
    _fact(student, VerifiedFact.Category.RESEARCH, {"thesis_title": "A thesis"})

    questions = gap_questions(student)
    written = submit_answers(
        {field_name(question): "an answer" for question in questions}, student=student
    )

    answered = {(fact.supersedes_id, key) for fact in written for key in fact.payload}
    assert {(q.fact_id, q.payload_key) for q in questions} <= answered
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
cd .worktrees/gap-intake
POSTGRES_DB=tehsil_gap_intake uv run pytest tests/documents/test_gap_intake.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'apps.documents.gap_intake'`.

- [x] **Step 3: Write the implementation**

Create `apps/documents/gap_intake.py`:

```python
"""Turning a submitted form into ledger writes, without trusting the form.

``gaps.py``'s docstring lists three things its first caller owes. Two are
here. The third is not, and cannot be:

- **A narrower key allowlist than gaps.py can express.** ``answer_questions``
  accepts any key the target fact's *category* carries, which is wider than
  the set the detectors ask about -- EDUCATION carries ``grade_conversion``,
  which gaps.py says in as many words it will never ask for, and SKILL carries
  ``category``, ``kind`` and ``evidence``, which are our reading of the
  student's material rather than their claim. ``submit_answers`` closes that
  by never reading a key *out of* the submission. It re-derives the questions
  and looks up each one's own field name, so a pair no current question
  produced is never looked at.

- **Attribution.** Every fact written here gets one ``AuditEvent`` naming
  whoever operated the form. ``created_by`` on the fact stays the student
  regardless -- that is provenance on the ledger row, matching every other
  fact writer (``ingest_uploaded_cv``, ``bridge_profile_to_facts``,
  ``evidence.facts``) -- and the audit trail is where an operator belongs.

- **Authorisation is NOT here.** ``student`` is taken on trust, exactly as
  ``answer_questions`` takes it. Resolving it from an authenticated session is
  ``apps.tenancy.services.current_membership``'s job, and nothing in this
  module has a request to inspect.

No model call, so no rate limiter is owed and this module is not evidence that
one exists. A change that gives this form the model-backed question types owes
``apps/ratelimit.py::rate_limited`` in the same change, per CLAUDE.md.

Design: docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md
"""

from __future__ import annotations

from collections.abc import Mapping

from apps.tenancy.models import Membership

from .gaps import GapQuestion, answer_questions, gap_questions
from .models import VerifiedFact


def field_name(question: GapQuestion) -> str:
    """The form field name a question's answer comes back under.

    The contract between whatever renders the form and this module: both sides
    call this, neither invents the string.

    Keyed by the fact and the payload key rather than by position, because the
    ledger can move between the render and the submit -- a second tab, a
    counsellor edit, a double submit. Positional names silently land an answer
    on whatever shifted into that slot; a stale name here matches no
    re-derived question and is dropped.
    """
    return f"{question.fact_id}:{question.payload_key}"


def submit_answers(
    submitted: Mapping[str, str], *, student: Membership
) -> tuple[VerifiedFact, ...]:
    """Write the answers a submission carries.

    ``submitted`` is a raw form mapping -- a Django ``QueryDict`` is one -- and
    is read only through ``field_name``. Keys it carries that no current
    question produced are never looked at, which makes the CSRF token, the
    submit button and a hand-edited field name all the same nothing.
    """
    questions = gap_questions(student)
    answers = [(question, submitted.get(field_name(question), "")) for question in questions]
    return answer_questions(answers, student=student)
```

- [x] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_gap_intake uv run pytest tests/documents/test_gap_intake.py -q
```

Expected: 7 passed.

- [x] **Step 5: Lint and type-check**

```bash
uv run ruff check .
uv run mypy apps config
```

Expected: both clean. If mypy objects to `submitted.get(...)`, the default `""` is what makes the return `str` rather than `str | None` — do not add a `cast`.

- [x] **Step 6: Commit**

```bash
git -C .worktrees/gap-intake add apps/documents/gap_intake.py tests/documents/test_gap_intake.py
git -C .worktrees/gap-intake commit -m "feat(documents): answer a gap question only where a question asked

gaps.py's answer_questions accepts any key the target's category carries,
which is wider than the set the detectors ask about. submit_answers never
reads a key out of the submission: it re-derives the questions and looks up
each one's own field name, so a pair no current question produced reaches
nothing. Positional field names would have landed an answer on whatever
moved into that slot when the ledger changed between render and submit."
```

---

### Task 2: The audit trail

**Files:**
- Modify: `apps/documents/gap_intake.py` (add the `record_event` loop and the `@transaction.atomic` decorator to `submit_answers`)
- Test: `tests/documents/test_gap_intake.py` (append)

**Interfaces:**
- Consumes: Task 1's `submit_answers(submitted, *, student)`; `apps.documents.audit.record_event(*, actor: Membership | None, event: str, object_id: UUID) -> AuditEvent | None`; `apps.funding.models.AuditEvent`.
- Produces: `submit_answers(submitted: Mapping[str, str], *, student: Membership, actor: Membership | None = None) -> tuple[VerifiedFact, ...]` — the return type is unchanged, the keyword-only `actor` is new, and it gains the side effect of one `AuditEvent` per written fact, with `event="document.gap_answered"` and `object_id` set to the written fact's id.

- [x] **Step 1: Write the failing tests**

Append to `tests/documents/test_gap_intake.py`, and add `from apps.funding.models import AuditEvent` and `from apps.documents.gaps import UnanswerableQuestion` to the imports at the top:

```python
def test_each_written_fact_is_audited_to_the_student(student):
    degree = _degree_without_a_grade(student)

    written = submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    events = AuditEvent.objects.filter(event="document.gap_answered")
    assert [event.object_id for event in events] == [written[0].id]
    assert events.get().actor_id == student.id
    assert events.get().actor_kind == AuditEvent.ActorKind.HUMAN


def test_a_counsellor_operated_submit_names_the_counsellor(
    student, agency_a, django_user_model
):
    """created_by on the fact is provenance and stays the student; the audit
    trail is where the operator is recorded. Same split as drafts.py.
    """
    with tenant_scope(agency_a.id):
        counsellor_user = django_user_model.objects.create(username="intake-counsellor")
        counsellor = Membership.objects.create(
            tenant=agency_a, user=counsellor_user, role=Membership.Role.COUNSELOR, active=True
        )
    degree = _degree_without_a_grade(student)

    written = submit_answers(
        {f"{degree.id}:grade_native": "16.45/20.0"}, student=student, actor=counsellor
    )

    assert written[0].created_by_id == student.id
    assert AuditEvent.objects.get(event="document.gap_answered").actor_id == counsellor.id


def test_a_skipped_form_audits_nothing(student):
    _degree_without_a_grade(student)

    submit_answers({}, student=student)

    assert not AuditEvent.objects.filter(event="document.gap_answered").exists()


def test_a_refused_batch_writes_neither_fact_nor_event(student):
    """An authoritative fact cannot be answered over. Nothing writes an
    authoritative EDUCATION fact today, so this is unreachable through the
    current detectors -- it becomes reachable the day transcript ingestion
    lands, and a half-written batch is not how anyone should find out.
    """
    degree = _fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc Chemistry"},
        tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
    )

    with pytest.raises(UnanswerableQuestion):
        submit_answers({f"{degree.id}:grade_native": "16.45/20.0"}, student=student)

    assert unsuperseded_facts(student).count() == 1
    assert not AuditEvent.objects.filter(event="document.gap_answered").exists()
```

- [x] **Step 2: Run the tests to verify they fail**

```bash
POSTGRES_DB=tehsil_gap_intake uv run pytest tests/documents/test_gap_intake.py -q
```

Expected: the three audit tests fail on an empty `AuditEvent` queryset (`test_a_skipped_form_audits_nothing` and `test_a_refused_batch_...` already pass, because nothing writes events yet — that is fine, they are the regression half).

- [x] **Step 3: Add the audit trail**

In `apps/documents/gap_intake.py`, add to the imports:

```python
from django.db import transaction

from .audit import record_event
```

Decorate `submit_answers` with `@transaction.atomic`, add the keyword-only `actor` parameter, and replace its final `return` with the audit loop:

```python
@transaction.atomic
def submit_answers(
    submitted: Mapping[str, str],
    *,
    student: Membership,
    actor: Membership | None = None,
) -> tuple[VerifiedFact, ...]:
```

```python
    written = answer_questions(answers, student=student)
    for fact in written:
        record_event(actor=actor or student, event="document.gap_answered", object_id=fact.id)
    return written
```

Add to the `submit_answers` docstring:

```
    ``actor`` is whoever operated the form, defaulting to the student
    answering their own questions; a counsellor operating it passes themselves
    while ``student`` stays the student. Same shape as ``drafts.py``'s
    ``actor or student``.

    Atomic over both halves. ``answer_questions`` is already atomic on its
    own, so a refused batch was never the risk; a failure between the ledger
    write and its audit is, and would leave facts nobody can trace.
```

- [x] **Step 4: Run the tests to verify they pass**

```bash
POSTGRES_DB=tehsil_gap_intake uv run pytest tests/documents/test_gap_intake.py -q
```

Expected: 11 passed.

- [x] **Step 5: Run the full gate**

```bash
POSTGRES_DB=tehsil_gap_intake uv run pytest
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
POSTGRES_DB=tehsil_gap_intake uv run python manage.py makemigrations --check --dry-run
```

Expected: the suite green with no regressions, ruff and mypy clean, bandit with no new findings, and `makemigrations --check` reporting no changes (this plan adds no model fields).

- [x] **Step 6: Commit**

```bash
git -C .worktrees/gap-intake add apps/documents/gap_intake.py tests/documents/test_gap_intake.py
git -C .worktrees/gap-intake commit -m "feat(documents): audit every fact a gap answer writes

One AuditEvent per written fact, naming whoever operated the form. The fact's
created_by stays the student either way -- that is provenance on the ledger
row, and the audit trail is where an operator belongs. Atomic over both
halves: answer_questions was already atomic, but a failure between the write
and its audit would leave facts nobody can trace."
```

---

## What the next change inherits

- **No view, no URL, no template.** Deliberately out of scope. Stack-independent obligations, true whatever presentation layer is chosen: `current_membership(request, Membership.Role.STUDENT)` is both the authorisation check and the `student` argument — that is the only thing standing between a submission and another student's ledger, since `submit_answers` takes `student` on trust; **no field may be marked required**, because every question is skippable and a blank is an ordinary skip; a field's name must come from `field_name(question)` and never be invented by the renderer; `UnanswerableQuestion` must render as a client error the student can act on, not a 500; and success must Post/Redirect/Get, after which the answered questions no longer appear because the ledger now carries their values.

  **Do not follow this plan's earlier draft guidance about `templates/components/_field.html`.** That partial no longer exists — see the next bullet. Whether the field id needs to avoid the colon in `field_name` is a property of the stack that gets chosen: it mattered for Django's `id_{name}` default, and may not for anything else.
- **A concurrent submit can fork a supersession chain, and nothing stops it.** `answer_questions` reads its target with `unsuperseded_facts(student).filter(id=fact_id).first()` (`gaps.py:285`) and takes no row lock; the only database constraint touching `supersedes` is `verifiedfact_supersedes_tenant_fk`, a tenant FK, not a unique index. Two submits naming the same fact therefore both read the same tip and both write a superseding row, after which `unsuperseded_facts` returns **two** tips for one logical fact — and every reader downstream of it, `generatable_facts` and the detectors in `gaps.py` included, sees the fork.

  Not introduced by this plan and not reachable today: `answer_questions` shipped this way in #32, and there is still no view, so nothing can submit twice. A double-submitted form is the textbook trigger, so **this becomes real the day the form lands** — the same change that adds the view should close it, or explicitly decide not to.

  The fix belongs in `gaps.py`, not in `gap_intake.py`, because `answer_questions` is where the read-then-write sits: either `select_for_update()` on that read, or a partial unique index on `supersedes` (`WHERE supersedes_id IS NOT NULL`) that turns the race into an `IntegrityError` the caller can retry. The index is the stronger of the two — it holds against writers that never go through `answer_questions` — but it needs checking against `evidence/facts.py`'s `_previous(...)` supersession writes first, which this plan did not do. Deliberately untested here: a test that documents a race nothing can currently reach is noise.

- **`end_date` accepts a sentence.** `incomplete_entry` asks *"Are you still working as X? If not, when did it end?"*, so a student who answers "yes, still there" writes that string into the `end_date` payload key — and the question then stops being asked, so nobody notices. It is a flaw in the question, not in this module, and it is contained by `confirmed_by=None` (a counsellor gates it before generation). Whoever next owns the detectors should split it into a yes/no and a date, or stop asking it as free text.
- **`CLAUDE.md`'s "Design authority" section now describes a frontend that no longer exists, and reconciling it is the form change's first task — before any design work.** PR #33 deleted `templates/` and `static/` outright; `tests/templates/` holds deliberately empty stubs, wired in `config/settings/test.py` only, so that view tests can keep asserting authorisation, tenant isolation and rate limiting through views that end in a `render()`. Its `README.md` says a stub that needs real markup to pass means the test is asserting presentation and should be deleted, not enriched.

  `CLAUDE.md` was not updated to match, so every referent in its Design authority section is now dangling: `templates/base.html` and `templates/components/_field.html` (deleted), `DESIGN.md` §3/§8/§11 (deleted by `451791e`; `DESIGN.md` is now a 131-line *marketing-site* contract), and `refero-design`/`taste-skill` (not installed). `tests/templates/README.md` quotes a CLAUDE.md sentence — "the presentation layer is chosen fresh from the idea by `spec-to-site-orchestrator` at build time" — that **is not in `CLAUDE.md`**, which suggests the intended edit was written but never landed.

  The tests that asserted markup were quarantined rather than deleted: a `frontend` marker ("asserts rendered markup; skipped while `templates/` is absent") now guards about 40 of them across 15 files, including `tests/acceptance/test_htmx_config.py` and `test_swap_render.py`. They are skipped, not failing — the full suite is green at 1678 passed, 43 skipped, where it was 3 skipped before this merge. That quarantine is the honest record of what the chosen stack will owe: whichever presentation layer wins has to satisfy those assertions again or retire them deliberately.

  So the reconciliation is not doc-tidying: until it is done there is no answer to "what does a form look like here". Settle *which stack and which authority* first, then design the surface.
- **No rate limiter, and that is correct here.** No model call, and this is not a free-text spam vector: every answer closes the question that produced it, so the form empties itself and a resubmit can only re-answer what was skipped. Growth is bounded by open questions, not by submits. Question types 1, 2 and 6 change that, and the change that adds them owes `rate_limited`.
