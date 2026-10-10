# Gap Interview: The Deterministic Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build question types 3 (MISSING_CONTACT), 4 (MISSING_GRADE) and 5 (INCOMPLETE_ENTRY) of the gap interview — the checks that read the fact ledger and need no model call — plus the answer-to-candidate-fact plumbing all three share.

**Architecture:** One new module, `apps/documents/gaps.py`, holding a `GapQuestion` record, three pure detector functions over `unsuperseded_facts`, one entry point that runs them in order, and one writer that turns an answer into a superseding candidate fact. Nothing here calls a model, opens a socket, or renders a page. It is unwired by design, in the same way `tailor_skills` and `ingest_evidence` are — the view is a separate surface the design doc does not specify.

**Tech Stack:** Django 5.2, Python 3.12, pytest + pytest-django, uv. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md` (question types 3, 4 and 5, and "What must be true of every question"; this plan implements order-of-implementation step 1 only)

## Global Constraints

- **Every question names its evidence.** A question the student cannot trace to something in their own material reads as a machine guessing. Same principle as `Technique.excerpt` in `evidence/extraction.py`.
- **Every question is answerable in one line or one number.** The student is not writing a second CV.
- **Every answer becomes a candidate fact, never a confirmed one** — `source_tier=STUDENT_STATEMENT`, `confirmed_by=None`, exactly as `ingest_uploaded_cv` writes. The counsellor confirms.
- **Every question is skippable.** A required answer to an inferred gap is a wall in front of a paying student.
- **Ask only for what is genuinely absent.** Asking for something already on file is the fastest way to make a student distrust the tool. An avoidable question is worse than none.
- **No model call anywhere in this plan.** These three types are field-null tests against the ledger. Because nothing here calls an LLM, `CLAUDE.md`'s rule that a wiring change must carry a rate limiter does not bind — and must not be cited as satisfied either. Type 1, 2 and 6 will call a model, and they will owe the limiter.
- **The ledger is append-only.** A correction is a new row with `supersedes` set (`apps/documents/models.py:9`). Nothing in this plan may mutate an existing `VerifiedFact`.
- Test database is per-worktree: run pytest with `POSTGRES_DB=tehsil_gaps`.
- Lint/type/security gate, all blocking: `uv run ruff check .`, `uv run mypy apps config`, `uv run bandit -c pyproject.toml -r apps config`. There is **no** `ruff format` in this repo — do not run it.

---

## Why this plan exists rather than just the design doc

The design doc calls types 3, 4 and 5 "field-null tests against the ledger [that] need no model call at all... most of the value and none of the cost". Read against the code, three of those field-null tests cannot be written as described:

1. **`ExperienceEntry.supervisor` never reaches the ledger.** The field exists on the schema (`apps/documents/schemas.py:230`), the extractor is told to fill it (`apps/documents/ingestion.py:269`), and `render.py:326` reads it to decide research-vs-taught section order — but `_PAYLOAD_KEYS[EXPERIENCE]` is `('employer', 'title', 'city', 'country', 'start_date', 'end_date', 'bullets')`. `fact_payload` drops it. Type 5's primary detector ("an experience entry with `supervisor` null") would therefore fire on *every* experience entry, including the ones whose CV named the PI — the avoidable question the doc forbids. This is also a live round-trip bug independent of the gap interview: `generation._facts_payload` serialises the whole payload into the prompt, so a CV regenerated from the ledger loses the supervisor and `_section_order` then reads a research applicant as taught-track. **Task 1, and everything else depends on it.**

2. **Type 5's date check describes a state that cannot exist.** The doc asks for "any entry with no `end_date` and no 'present'". In this schema `end_date=None` *is* "present" — every CV template renders it with `{{ entry.end_date|month_year:"present" }}`. There is no separate flag to be missing. Resolved in Task 4.

3. **Type 4's second question has nowhere to put its answer.** "The classification if the mark is there but unlabelled" needs a field for the honours classification. `EducationEntry` has `grade_native`, `grade_scale`, `grade_conversion` and no classification field, so today the classification is folded into `grade_native` — which is what produced `Grade: GPA: 16.45/20.0 (Highest Honors) (20.0)` in PR #30. Adding one is `CVContent` schema work and a `schema_version` bump, which puts it in the same bucket as the type-7 sections. Resolved in Task 3 by shipping the mark-and-scale question only.

And the three tasks converge on one shared piece — a writer that supersedes an existing fact with one added field — which nothing in the codebase provides generically. `profile_bridge.bridge_profile_to_facts` does exactly this shape but is keyed on a profile slot index via `source_ref`, which a gap answer cannot use because it already holds a `fact_id`. **Task 5**, and getting it wrong forks the ledger.

## Decisions this plan makes that the design doc left open

- **D1 — `supervisor` is carried for provenance and never compared.** Decided against the alternative, which was to put it in `spec.detail` and compare it the way `ResearchEntry` already does. Comparing it would make a CV and a ledger naming the same PI differently read CONFLICTING, and PR #30 measured extraction as non-deterministic on exactly this kind of field: "Prof. Schwaller" one run and "Philippe Schwaller" the next would block a student's own draft over a formatting difference nobody disagreed about. The cost is accepted and named: a CV naming a genuinely *different* supervisor than the ledger reads SUPPORTED, because nothing looks. That is the same bargain `degree_english`, `grade_native`, `methods`, `outcomes`, `phone` and the contact URLs are already on — see the module docstring on what SUPPORTED does and does not mean. It still lands in `_PAYLOAD_KEYS`, which is what Task 4 detects on and what lets Task 5's writer accept an answer for it.
- **D2 — "academic-looking employer" is replaced by a ledger signal.** The doc's phrasing implies a keyword list over employer strings, which fails on `CNRS`, `Max-Planck-Institut`, `Institut Curie` and every non-English institution. Instead: ask about a missing supervisor only when the student has at least one RESEARCH or PUBLICATION fact — i.e. this is a research applicant, so their posts plausibly had principal investigators. Language-independent, needs no list to maintain, and reads the same ledger everything else here reads.
- **D3 — no source-tier precedence rule is needed.** An answer superseding a CV-derived fact is same-tier: `ingest_uploaded_cv` writes `STUDENT_STATEMENT` (`apps/documents/ingestion.py:346`), not `AUTHORITATIVE_DOCUMENT`. Only DOI-fetched publications and "Languages and tools" skills are authoritative, and no type-3/4/5 question targets those. The writer refuses an authoritative target anyway (Task 5) — it is a trust boundary, and "it cannot happen today" is not a guarantee.
- **D4 — type 4 degrades until transcripts are ingested, and that is accepted.** The doc says "a transcript usually answers both, so read it before asking". Nothing in this repository ingests a transcript — the word appears only inside a prompt string and in test `source_ref` values. The check is written against the ledger, so it needs no change when transcript ingestion lands; until then it asks for grades a transcript already carries. Shipping type 4 now is still right: a missing grade is a real defect on a graduate application.

## Out of scope, deliberately

- **The view and form.** The doc specifies "the student sees a form, not a chat" and nothing else about the surface. `gaps.py` gains a caller in the same change that designs that surface.
- **Types 1, 2 and 6.** They need a model call and the programme profile.
- **Type 7.** Schema work precedes the question.
- **The honours-classification question** (see reason 3 above) and **transcript ingestion** (D4).

## File Structure

| File | Responsibility |
| --- | --- |
| `apps/documents/verification.py` (modify, `_PAYLOAD_KEYS` experience branch, line 206) | Add `supervisor` to the keys an experience payload carries, so `fact_payload` stops dropping it (Task 1), and expose `payload_keys(category)` so a writer outside this module can reject a key a category does not carry (Task 5). |
| `apps/documents/gaps.py` (create) | `GapQuestion` record, the three detectors, `gap_questions` entry point, `answer_question` writer. One module: these change together and nothing else reads them yet. |
| `tests/documents/test_gaps.py` (create) | Every test in this plan. |
| `tests/documents/test_verification.py` (modify) | The supervisor payload test from Task 1. |

---

### Task 1: `supervisor` reaches the EXPERIENCE payload

Everything else in this plan depends on this. It is also a standalone round-trip bug: the supervisor is extracted, used by `render._section_order`, and then lost, so a CV regenerated from the ledger demotes a research applicant to the taught-track section order.

**Files:**
- Modify: `apps/documents/verification.py:206` (the experience branch of `_PAYLOAD_KEYS`)
- Test: `tests/documents/test_verification.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_PAYLOAD_KEYS[VerifiedFact.Category.EXPERIENCE]` now contains `"supervisor"`, so `fact_payload(ExperienceEntry(...), category=EXPERIENCE)` returns a dict with a `supervisor` key. Tasks 4 and 6 read it.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_verification.py`:

```python
def test_an_experience_entry_keeps_its_supervisor_in_the_ledger():
    """The supervisor is the strongest single signal on an academic CV, and it
    was the one ExperienceEntry field fact_payload dropped. Generation
    serialises the whole payload into its prompt, so a key absent here can
    never be put back: a CV regenerated from the ledger loses the PI, and
    render._section_order then reads a research applicant as taught-track.
    """
    entry = ExperienceEntry(
        employer="EPFL",
        title="Research Assistant",
        supervisor="Prof. Schwaller",
        city="Lausanne",
        country="CH",
        start_date="2023-01-01",
        end_date="2024-06-30",
        # Required, min_length=1: S-010 makes an experience entry bullets
        # rather than a prose block, and the schema enforces it. Omit this and
        # the test fails on a pydantic ValidationError before it can reach the
        # KeyError it exists to prove.
        bullets=("Benchmarked three generative frameworks on one dataset.",),
    )

    payload = fact_payload(entry, category=VerifiedFact.Category.EXPERIENCE)

    assert payload["supervisor"] == "Prof. Schwaller"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_verification.py::test_an_experience_entry_keeps_its_supervisor_in_the_ledger -v`
Expected: FAIL with `KeyError: 'supervisor'`.

- [ ] **Step 3: Write minimal implementation**

In `apps/documents/verification.py`, the experience branch of `_PAYLOAD_KEYS` (line 206) becomes:

```python
    # supervisor joins bullets as carried-but-never-compared. It used to be on
    # the schema and nowhere in the payload: extracted, read by
    # render._section_order, and lost on the way to the ledger, so a CV
    # regenerated from facts demoted a research applicant to the taught order.
    #
    # NOT a spec.detail key, though ResearchEntry compares its own. Extraction
    # is measurably non-deterministic on a name read off a folded line
    # ("EPFL | Prof. Schwaller's group"), and comparing it would turn
    # "Prof. Schwaller" against "Philippe Schwaller" into a CONFLICTING verdict
    # that blocks the applicant's own draft over a formatting difference. The
    # cost is that a genuinely wrong supervisor now reads SUPPORTED; that is
    # the same bargain every other key in this group is on.
    + (("bullets", "supervisor") if spec.field == "experience" else ())
```

The experience `_CategorySpec` is **not** touched — `identity`, `detail` and `label` stay exactly as they are.

- [ ] **Step 4: Run the test and the whole documents suite**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents -q`
Expected: PASS, including the pre-existing verification and generation tests. If a generation snapshot test fails on the added key, that failure is the bug being fixed showing itself — read it before changing anything.

- [ ] **Step 5: Verify the check is not vacuous**

Revert the `_PAYLOAD_KEYS` experience branch to `(("bullets",) if spec.field == "experience" else ())`, re-run the new test, confirm it fails with `KeyError: 'supervisor'`, then restore. A payload-key test that passes with the key removed is testing nothing.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/verification.py tests/documents/test_verification.py
git commit -m "fix(documents): carry an experience entry's supervisor into the ledger"
```

---

### Task 2: `GapQuestion`, and the MISSING_CONTACT check

**Files:**
- Create: `apps/documents/gaps.py`
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `apps.documents.verification.unsuperseded_facts`, `apps.documents.models.VerifiedFact`.
- Produces:
  - `class Kind(StrEnum)` with members `MISSING_CONTACT`, `MISSING_GRADE`, `INCOMPLETE_ENTRY`.
  - `@dataclass(frozen=True) class GapQuestion` with fields `kind: Kind`, `fact_id: UUID`, `payload_key: str`, `prompt: str`, `evidence: str`.
  - `def missing_contact(student: Membership) -> tuple[GapQuestion, ...]`.
  Tasks 3, 4, 5 and 6 all use `GapQuestion` and `Kind`.

- [ ] **Step 1: Write the failing tests**

Create `tests/documents/test_gaps.py`:

```python
import pytest
from django.utils import timezone

from apps.documents.gaps import Kind, missing_contact
from apps.documents.models import VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture
def student(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="gap-student")
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


def test_a_missing_orcid_is_a_question(student):
    _fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    questions = missing_contact(student)

    assert [q.payload_key for q in questions if q.payload_key == "orcid"] == ["orcid"]
    assert all(q.kind is Kind.MISSING_CONTACT for q in questions)


def test_a_handle_recovered_from_the_pdf_is_not_asked_for_again(student):
    """extract_link_urls recovers addresses from PDF link annotations, and a CV
    that hyperlinks a handle is not missing anything. Asking for something
    already on file is the fastest way to make a student distrust the tool.
    """
    _fact(
        student,
        VerifiedFact.Category.IDENTITY,
        {"full_name": "A Student", "github_username": "0rkhann"},
    )

    assert "github_url" not in {q.payload_key for q in missing_contact(student)}


def test_every_question_names_the_evidence_it_came_from(student):
    _fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    assert all(q.evidence for q in missing_contact(student))


def test_a_student_with_no_identity_fact_is_asked_nothing(student):
    """No IDENTITY row means the CV was never ingested. Questions about a
    contact header that does not exist yet are noise, not a gap.
    """
    assert missing_contact(student) == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'apps.documents.gaps'`.

- [ ] **Step 3: Write minimal implementation**

Create `apps/documents/gaps.py`:

```python
"""The gap interview's deterministic checks: what the ledger is missing.

Three field-null tests against the fact ledger, run before generation rather
than after it. Asking after generating burns a generation, shows a document
built on a gap, and then asks; asking first costs nothing and produces a
better first draft.

No model call anywhere in this module -- these are the checks that need none.
Types 1, 2 and 6 of the design will call a model, and the change that wires
one up owes the per-student rate limiter CLAUDE.md requires. Nothing here
does, and this module must not be used as evidence that a limiter exists.

Design: docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from apps.tenancy.models import Membership

from .models import VerifiedFact
from .verification import unsuperseded_facts


class Kind(StrEnum):
    MISSING_CONTACT = "MISSING_CONTACT"
    MISSING_GRADE = "MISSING_GRADE"
    INCOMPLETE_ENTRY = "INCOMPLETE_ENTRY"


@dataclass(frozen=True)
class GapQuestion:
    kind: Kind
    #: The fact this question is about. An answer supersedes it (see
    #: answer_question) rather than writing a second row for the same thing.
    fact_id: UUID
    #: The payload key the answer lands in. Must be a key the fact's category
    #: already carries -- answer_question refuses anything else.
    payload_key: str
    #: What the student is asked. One line or one number to answer.
    prompt: str
    #: What in the student's own material triggered this. A question they
    #: cannot trace reads as a machine guessing, and they stop answering.
    evidence: str


#: (payload key, alternative key that also counts as present, prompt).
#: The alternative exists because extract_link_urls recovers addresses from a
#: PDF's link annotations while the prompt refuses to build a URL from a bare
#: handle -- so a CV printing "Github: 0rkhann" yields a username and no URL,
#: and is not missing anything a student needs to retype.
_CONTACT_FIELDS: tuple[tuple[str, str | None, str], ...] = (
    ("orcid", None, "What is your ORCID iD?"),
    ("linkedin_url", "linkedin_handle", "What is your LinkedIn profile address?"),
    ("github_url", "github_username", "What is your GitHub profile address?"),
    ("website_url", None, "Do you have a personal or academic website?"),
    ("phone", None, "What phone number should the CV print?"),
)


def _current(student: Membership, category: str) -> list[VerifiedFact]:
    return list(unsuperseded_facts(student).filter(category=category))


def missing_contact(student: Membership) -> tuple[GapQuestion, ...]:
    """Contact details the header has no value for.

    Cheapest to detect and cheapest to answer, so this should never be the
    reason a CV is weak. Asks only for what is genuinely absent.
    """
    identity = _current(student, VerifiedFact.Category.IDENTITY)
    if not identity:
        return ()
    fact = identity[-1]
    payload = fact.payload if isinstance(fact.payload, dict) else {}
    name = str(payload.get("full_name") or "your CV")
    return tuple(
        GapQuestion(
            kind=Kind.MISSING_CONTACT,
            fact_id=fact.id,
            payload_key=key,
            prompt=prompt,
            evidence=f"The contact header for {name} has no {key.replace('_', ' ')}.",
        )
        for key, alternative, prompt in _CONTACT_FIELDS
        if not payload.get(key) and not (alternative and payload.get(alternative))
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "feat(documents): ask for the contact details the header has no value for"
```

---

### Task 3: The MISSING_GRADE check

Ships the mark-and-scale question only. The classification question the design doc also lists needs a field on `EducationEntry` to hold the answer, which is `CVContent` schema work and a `schema_version` bump — the same bucket as the type-7 sections, and not this plan.

**Files:**
- Modify: `apps/documents/gaps.py`
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `GapQuestion`, `Kind`, `_current` from Task 2.
- Produces: `def missing_grade(student: Membership) -> tuple[GapQuestion, ...]`. Task 6 calls it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_gaps.py` (and add `missing_grade` to the `apps.documents.gaps` import):

```python
_DEGREE = {
    "degree_as_awarded": "BSc Petroleum Engineering",
    "institution_original": "Example University",
    "start_date": "2020-09-01",
    "end_date": "2024-06-30",
}


def test_a_degree_with_no_grade_is_a_question(student):
    """For a graduate application the grade is expected, not optional."""
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))

    questions = missing_grade(student)

    assert [q.payload_key for q in questions] == ["grade_native"]
    assert "BSc Petroleum Engineering" in questions[0].evidence


def test_a_degree_that_already_states_its_grade_is_not_a_question(student):
    _fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {**_DEGREE, "grade_native": "16.45", "grade_scale": "20.0"},
    )

    assert missing_grade(student) == ()


def test_the_question_asks_for_the_mark_and_the_scale_together(student):
    """S-027: the grade goes on the institution's own scale, mark and
    denominator together. Asking for a bare number invites a conversion, and a
    conversion is a new claim nobody made.
    """
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))

    prompt = missing_grade(student)[0].prompt
    assert "scale" in prompt.lower()


def test_a_superseded_degree_is_not_asked_about(student):
    old = _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    new = _fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {**_DEGREE, "grade_native": "16.45", "grade_scale": "20.0"},
    )
    new.supersedes = old
    new.save(update_fields=["supersedes"])

    assert missing_grade(student) == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: FAIL with `ImportError: cannot import name 'missing_grade'`.

- [ ] **Step 3: Write minimal implementation**

Append to `apps/documents/gaps.py`:

```python
def missing_grade(student: Membership) -> tuple[GapQuestion, ...]:
    """A degree the ledger has no mark for.

    One question per degree, asking for the mark and its scale together --
    S-027 puts the grade on the institution's own scale, mark and denominator
    together (16.45/20.0, 3.82/4.0). Never asks for a conversion: 16.45/20.0
    is the claim, and a 4.0-scale equivalent is a new claim nobody made, with
    tables that differ between the institution, the destination country and
    the credential evaluator.

    Deliberately does not ask how many semesters the grade covers. Searched
    for S-027; no source states it, and the degree's own date range already
    carries the period. Recorded as a negative result so nobody re-derives it.

    Until a transcript is ingested this asks for grades a transcript already
    carries -- the check reads the ledger, so it needs no change when that
    lands, and a missing grade is a real defect on a graduate application in
    the meantime.
    """
    questions: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.EDUCATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        if payload.get("grade_native"):
            continue
        degree = str(payload.get("degree_as_awarded") or "your degree")
        institution = str(payload.get("institution_original") or "")
        questions.append(
            GapQuestion(
                kind=Kind.MISSING_GRADE,
                fact_id=fact.id,
                payload_key="grade_native",
                prompt=(
                    f"What grade did you finish {degree} with, on your "
                    "institution's own scale? Give the mark and the scale "
                    "together, for example 16.45/20.0."
                ),
                evidence=(
                    f"{degree}"
                    + (f" at {institution}" if institution else "")
                    + " is on file with no grade."
                ),
            )
        )
    return tuple(questions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "feat(documents): ask for a degree's grade on its own scale"
```

---

### Task 4: The INCOMPLETE_ENTRY check

Two of the design doc's three detectors survive contact with the schema; the third is replaced. See "Why this plan exists" reasons 2 and 3, and decision D2.

**Files:**
- Modify: `apps/documents/gaps.py`
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `GapQuestion`, `Kind`, `_current` from Task 2; the `supervisor` payload key from Task 1.
- Produces: `def incomplete_entry(student: Membership) -> tuple[GapQuestion, ...]`. Task 6 calls it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_gaps.py` (and add `incomplete_entry` to the import):

```python
_POST = {
    "employer": "EPFL",
    "title": "Research Assistant",
    "start_date": "2023-01-01",
    "end_date": "2024-06-30",
}
_PAPER = {"title": "A paper", "year": 2024}


def test_a_research_applicant_is_asked_who_supervised_a_post(student):
    """S-028, and the field most often lost: a CV prints
    "EPFL | Prof. Schwaller's group" on one line and the extractor folds it
    into the employer.
    """
    _fact(student, VerifiedFact.Category.EXPERIENCE, dict(_POST))
    _fact(student, VerifiedFact.Category.PUBLICATION, dict(_PAPER))

    assert "supervisor" in {q.payload_key for q in incomplete_entry(student)}


def test_an_applicant_with_no_research_record_is_not_asked_for_a_supervisor(student):
    """D2: the signal is the applicant's own ledger, not a keyword list over
    employer strings. A list would have to recognise CNRS, Max-Planck-Institut
    and Institut Curie, and would still miss the next one.
    """
    _fact(student, VerifiedFact.Category.EXPERIENCE, dict(_POST))

    assert "supervisor" not in {q.payload_key for q in incomplete_entry(student)}


def test_a_post_that_already_names_its_supervisor_is_not_asked_about(student):
    _fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {**_POST, "supervisor": "Prof. Schwaller"},
    )
    _fact(student, VerifiedFact.Category.PUBLICATION, dict(_PAPER))

    assert "supervisor" not in {q.payload_key for q in incomplete_entry(student)}


def test_an_open_ended_post_is_asked_whether_it_is_still_running(student):
    """The doc asks for "no end_date and no present". In this schema
    end_date=None IS present -- every template renders it with
    |month_year:"present" -- so that state cannot exist. The real ambiguity is
    whether the CV meant "ongoing" or simply omitted the date.
    """
    _fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})

    questions = [q for q in incomplete_entry(student) if q.payload_key == "end_date"]
    assert len(questions) == 1
    assert "EPFL" in questions[0].evidence


def test_a_research_entry_with_no_institution_is_a_question(student):
    _fact(
        student,
        VerifiedFact.Category.RESEARCH,
        {"thesis_title": "A thesis", "start_date": "2023-01-01"},
    )

    assert "institution" in {q.payload_key for q in incomplete_entry(student)}


def test_a_complete_record_produces_no_questions(student):
    _fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {**_POST, "supervisor": "Prof. Schwaller"},
    )

    assert incomplete_entry(student) == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: FAIL with `ImportError: cannot import name 'incomplete_entry'`.

- [ ] **Step 3: Write minimal implementation**

Append to `apps/documents/gaps.py`:

```python
def _is_research_applicant(student: Membership) -> bool:
    """Whether this student's posts plausibly had principal investigators.

    D2: the design doc says "an academic-looking employer", which implies a
    keyword list over employer strings. Such a list has to recognise CNRS,
    Max-Planck-Institut and Institut Curie and will still miss the next one,
    and it is English-shaped in a product whose applicants are not. The
    student's own ledger answers the same question without a list.
    """
    return unsuperseded_facts(student).filter(
        category__in=(VerifiedFact.Category.RESEARCH, VerifiedFact.Category.PUBLICATION)
    ).exists()


def incomplete_entry(student: Membership) -> tuple[GapQuestion, ...]:
    """A section missing a field the reader needs.

    S-028: an academic post names the group or laboratory and its principal
    investigator; an industry post names the company; both carry a month-year
    range.

    The doc's third detector -- "any entry with no end_date and no 'present'"
    -- describes a state this schema cannot hold: end_date=None *is* present,
    rendered by every template as |month_year:"present". There is no separate
    flag to be missing. What is genuinely ambiguous is whether the CV meant
    "still running" or simply omitted the date, so that is what gets asked.
    """
    questions: list[GapQuestion] = []
    ask_supervisor = _is_research_applicant(student)
    for fact in _current(student, VerifiedFact.Category.EXPERIENCE):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        employer = str(payload.get("employer") or "a post on your CV")
        title = str(payload.get("title") or "")
        where = f"{title} at {employer}" if title else employer
        if ask_supervisor and not payload.get("supervisor"):
            questions.append(
                GapQuestion(
                    kind=Kind.INCOMPLETE_ENTRY,
                    fact_id=fact.id,
                    payload_key="supervisor",
                    prompt=f"Who supervised your work as {where}?",
                    evidence=f"{where} names no supervisor, and your CV lists research work.",
                )
            )
        if not payload.get("end_date"):
            questions.append(
                GapQuestion(
                    kind=Kind.INCOMPLETE_ENTRY,
                    fact_id=fact.id,
                    payload_key="end_date",
                    prompt=(
                        f"Are you still working as {where}? If not, when did it end?"
                    ),
                    evidence=f"{where} has a start date and no end date.",
                )
            )
    for fact in _current(student, VerifiedFact.Category.RESEARCH):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        if payload.get("institution"):
            continue
        thesis = str(payload.get("thesis_title") or "your research")
        questions.append(
            GapQuestion(
                kind=Kind.INCOMPLETE_ENTRY,
                fact_id=fact.id,
                payload_key="institution",
                prompt=f"Where did you carry out {thesis}?",
                evidence=f"{thesis} names no institution.",
            )
        )
    return tuple(questions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: 14 passed.

- [ ] **Step 5: Verify Task 1 is load-bearing here**

Revert Task 1's `_PAYLOAD_KEYS` change, run `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`, and confirm `test_a_post_that_already_names_its_supervisor_is_not_asked_about` fails — the payload key is what makes "already answered" distinguishable from "never asked". Restore Task 1.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "feat(documents): ask for the fields an entry is missing"
```

---

### Task 5: Turning answers into candidate facts

The piece all three checks converge on. `profile_bridge.bridge_profile_to_facts` does this shape already but is keyed on a profile slot index carried in `source_ref`; a gap answer holds a `fact_id`, which is a stronger key, so this is a separate writer rather than a generalisation of that one.

**It takes a batch, not one answer.** Two questions can name the same fact — a post missing both its supervisor and its end date produces one of each. Writing them one at a time would make the first answer supersede the fact the second one names, and the second would then be refused as stale. One row per fact, carrying every answer for it, avoids that entirely and leaves a cleaner chain. It also matches the surface: the student sees a form and submits all of it at once.

**Files:**
- Modify: `apps/documents/verification.py` (add the public `payload_keys` helper)
- Modify: `apps/documents/gaps.py`
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `GapQuestion` from Task 2.
- Produces:
  - `apps.documents.verification.payload_keys(category: str) -> tuple[str, ...]`
  - `apps.documents.gaps.UnanswerableQuestion(ValueError)`
  - `apps.documents.gaps.answer_questions(answers: Sequence[tuple[GapQuestion, str]], *, student: Membership) -> tuple[VerifiedFact, ...]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_gaps.py`. Add `GapQuestion, UnanswerableQuestion, answer_questions` to the `apps.documents.gaps` import and `from apps.documents.verification import unsuperseded_facts` to the module's imports.

```python
def test_an_answer_supersedes_the_fact_it_was_asked_about(student):
    fact = _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    (written,) = answer_questions([(question, "16.45/20.0")], student=student)

    assert written.supersedes_id == fact.id
    assert written.payload["grade_native"] == "16.45/20.0"
    assert written.payload["degree_as_awarded"] == "BSc Petroleum Engineering"
    assert list(unsuperseded_facts(student).filter(category="EDUCATION")) == [written]


def test_two_answers_about_one_fact_write_one_row(student):
    """A post missing both its supervisor and its end date produces one
    question of each, on the same fact. Written one at a time, the first
    answer would supersede the fact the second names and the second would be
    refused as stale -- so they are written together, as one row.
    """
    _fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})
    _fact(student, VerifiedFact.Category.PUBLICATION, dict(_PAPER))
    questions = [q for q in incomplete_entry(student) if q.payload_key in {"supervisor", "end_date"}]
    assert len(questions) == 2

    written = answer_questions(
        [(questions[0], "Prof. Schwaller"), (questions[1], "2025-01-31")], student=student
    )

    assert len(written) == 1
    assert written[0].payload["supervisor"] == "Prof. Schwaller"
    assert written[0].payload["end_date"] == "2025-01-31"


def test_an_answer_is_a_candidate_and_never_a_confirmed_fact(student):
    """An answer is a student statement. The counsellor confirms; generation
    reads generatable_facts, which is unsuperseded AND confirmed, so nothing
    written here can reach a document on its own.
    """
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    (written,) = answer_questions([(question, "16.45/20.0")], student=student)

    assert written.confirmed_by is None
    assert written.confirmed_at is None
    assert written.source_tier == VerifiedFact.SourceTier.STUDENT_STATEMENT


def test_a_skipped_question_writes_nothing(student):
    """Every question is skippable -- a required answer to an inferred gap is a
    wall in front of a paying student. A blank is a skip, not an empty fact,
    and a form of blanks must not write a row.
    """
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]

    assert answer_questions([(question, "   ")], student=student) == ()
    assert unsuperseded_facts(student).count() == 1


def test_an_answer_cannot_overwrite_an_authoritative_fact(student):
    """A DOI-fetched publication is AUTHORITATIVE_DOCUMENT. No type-3/4/5
    question targets one today, and this is why that stays true: a typed
    sentence must never quietly replace a registry's record.
    """
    fact = _fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        dict(_PAPER),
        tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
    )
    question = GapQuestion(
        kind=Kind.INCOMPLETE_ENTRY,
        fact_id=fact.id,
        payload_key="venue",
        prompt="Where was it published?",
        evidence="no venue",
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(question, "Journal of Things")], student=student)


def test_an_answer_cannot_invent_a_payload_key(student):
    """payload_key arrives from a form. A key the category does not carry would
    put a value somewhere no reader looks and no verdict compares.
    """
    fact = _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = GapQuestion(
        kind=Kind.MISSING_GRADE,
        fact_id=fact.id,
        payload_key="salary",
        prompt="?",
        evidence="?",
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(question, "lots")], student=student)


def test_answering_another_student_s_question_is_refused(student, agency_a, django_user_model):
    """fact_id arrives from a form. It is a trust boundary, not a hint."""
    fact = _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    question = missing_grade(student)[0]
    other_user = django_user_model.objects.create(username="other-student")
    other = Membership.objects.create(
        tenant=agency_a, user=other_user, role=Membership.Role.STUDENT, active=True
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(question, "16.45/20.0")], student=other)

    assert VerifiedFact.objects.filter(supersedes=fact).count() == 0


def test_a_rejected_answer_writes_none_of_the_batch(student):
    """One form, one transaction. A student who answered three questions and
    tripped a guard on the fourth must not find two of them landed.
    """
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    good = missing_grade(student)[0]
    bad = GapQuestion(
        kind=Kind.MISSING_GRADE,
        fact_id=good.fact_id,
        payload_key="salary",
        prompt="?",
        evidence="?",
    )

    with pytest.raises(UnanswerableQuestion):
        answer_questions([(good, "16.45/20.0"), (bad, "lots")], student=student)

    assert unsuperseded_facts(student).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: FAIL with `ImportError: cannot import name 'answer_questions'`.

- [ ] **Step 3: Add the public payload-key helper**

In `apps/documents/verification.py`, directly below the `_PAYLOAD_KEYS` definition:

```python
def payload_keys(category: str) -> tuple[str, ...]:
    """The payload keys one category carries.

    Public because a writer outside this module has to reject a key the
    category does not have: a value stored under an unknown key sits where no
    reader looks and no verdict compares it. Returns () for a category with no
    spec rather than raising -- an unknown category is "carries nothing", and
    every caller here treats that as a refusal.
    """
    return _PAYLOAD_KEYS.get(category, ())
```

- [ ] **Step 4: Write the writer**

In `apps/documents/gaps.py`, add `from collections.abc import Sequence` and `from django.db import transaction` to the imports, and `payload_keys` to the `.verification` import. Then append:

```python
class UnanswerableQuestion(ValueError):
    """An answer cannot be written: wrong student, wrong key, or a fact whose
    tier a typed sentence may not overwrite.

    Not raised for a blank answer -- every question is skippable, and a skip is
    an ordinary outcome rather than an error.
    """


@transaction.atomic
def answer_questions(
    answers: Sequence[tuple[GapQuestion, str]], *, student: Membership
) -> tuple[VerifiedFact, ...]:
    """Write a form's worth of answers as superseding candidate facts.

    One row per fact, carrying every answer for that fact. Written one at a
    time instead, the first answer would supersede the fact the second names
    and the second would be refused as stale -- a post missing both its
    supervisor and its end date produces exactly that pair.

    A correction is a new row with supersedes set: the ledger is append-only
    (see VerifiedFact's docstring), so this never mutates the row it answers.
    Everything written is a candidate -- confirmed_by=None, exactly as
    ingest_uploaded_cv writes -- and generation reads generatable_facts, so an
    answer cannot reach a document until a counsellor accepts it.

    Blank answers are dropped: a skipped question is not an empty fact, and a
    form of blanks writes nothing at all. Everything else that fails raises,
    and the whole batch is one transaction -- a student who answered three
    questions and tripped a guard on the fourth must not find two of them
    landed. All three guards read values that arrived from a form, which makes
    them a trust boundary rather than a hint.
    """
    updates: dict[UUID, dict[str, str]] = {}
    for question, answer in answers:
        value = answer.strip()
        if not value:
            continue
        updates.setdefault(question.fact_id, {})[question.payload_key] = value
    if not updates:
        return ()

    written: list[VerifiedFact] = []
    for fact_id, fields in updates.items():
        target = unsuperseded_facts(student).filter(id=fact_id).first()
        if target is None:
            raise UnanswerableQuestion(f"no current fact {fact_id} for this student")
        if target.source_tier == VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT:
            raise UnanswerableQuestion("an authoritative fact cannot be answered over")
        allowed = payload_keys(target.category)
        unknown = sorted(set(fields) - set(allowed))
        if unknown:
            raise UnanswerableQuestion(
                f"{target.category} facts do not carry {', '.join(unknown)}"
            )
        payload = dict(target.payload) if isinstance(target.payload, dict) else {}
        written.append(
            VerifiedFact.objects.create(
                student=student,
                category=target.category,
                payload={**payload, **fields},
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="gap-interview",
                confirmed_by=None,
                supersedes=target,
                created_by=student,
            )
        )
    return tuple(written)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: 22 passed.

- [ ] **Step 6: Mutation-check each guard**

Delete each of the three `raise UnanswerableQuestion` branches in turn, then the `@transaction.atomic` decorator, running the suite after each and restoring before the next. Confirm each removal fails at least one test — a guard with no test that fails without it is decoration.

- [ ] **Step 7: Commit**

```bash
git add apps/documents/gaps.py apps/documents/verification.py tests/documents/test_gaps.py
git commit -m "feat(documents): write gap-interview answers as superseding candidate facts"
```

---

### Task 6: One entry point, in the order the student should see

**Files:**
- Modify: `apps/documents/gaps.py`
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `missing_contact`, `missing_grade`, `incomplete_entry` from Tasks 2-4; `answer_questions` from Task 5.
- Produces: `def gap_questions(student: Membership) -> tuple[GapQuestion, ...]`. This is the module's public surface — the view that eventually renders the form calls this and `answer_questions`, and nothing else.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_gaps.py` (add `gap_questions` to the import):

```python
def test_the_cheapest_questions_come_first(student):
    """MISSING_CONTACT is cheapest to detect and cheapest to answer, so it
    should never be the reason a CV is weak. First in the form also means the
    student's first question is one they can answer without thinking.
    """
    _fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    _fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})

    order = [Kind.MISSING_CONTACT, Kind.MISSING_GRADE, Kind.INCOMPLETE_ENTRY]
    ranks = [order.index(q.kind) for q in gap_questions(student)]

    assert ranks == sorted(ranks)
    assert set(ranks) == {0, 1, 2}


def test_an_empty_ledger_produces_no_questions(student):
    """Nothing has been uploaded. A form full of questions about a CV that does
    not exist is noise, not a gap.
    """
    assert gap_questions(student) == ()


def test_every_question_gap_questions_emits_can_be_answered(student):
    """The contract between the two halves of this module: anything
    gap_questions emits, answer_questions accepts. A question whose key its own
    category does not carry would be a dead end the student cannot clear, and
    this is the test that would have caught the same-fact batching bug.
    """
    _fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    _fact(student, VerifiedFact.Category.EDUCATION, dict(_DEGREE))
    _fact(student, VerifiedFact.Category.EXPERIENCE, {**_POST, "end_date": None})
    _fact(student, VerifiedFact.Category.RESEARCH, {"thesis_title": "A thesis"})
    questions = gap_questions(student)
    assert questions

    written = answer_questions([(q, "an answer") for q in questions], student=student)

    assert len(written) == len({q.fact_id for q in questions})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: FAIL with `ImportError: cannot import name 'gap_questions'`.

- [ ] **Step 3: Write minimal implementation**

Append to `apps/documents/gaps.py`:

```python
def gap_questions(student: Membership) -> tuple[GapQuestion, ...]:
    """Everything the ledger can be asked about without a model call.

    Ordered cheapest-first: a contact detail is one line and needs no thought,
    a grade needs a document consulted, an incomplete entry needs the student
    to remember. Their attention is the scarce resource in this whole flow,
    and the order is what spends it well.

    Deliberately whole-ledger and one-shot rather than a conversation: these
    questions are independent of each other, the student sees one form, and a
    chat loop would cost a call per turn to produce the same questions in a
    worse order.
    """
    return missing_contact(student) + missing_grade(student) + incomplete_entry(student)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `POSTGRES_DB=tehsil_gaps uv run pytest tests/documents/test_gaps.py -v`
Expected: 25 passed.

- [ ] **Step 5: Run the whole gate**

```bash
POSTGRES_DB=tehsil_gaps uv run pytest -q
uv run ruff check .
uv run mypy apps config
uv run bandit -c pyproject.toml -r apps config
POSTGRES_DB=tehsil_gaps uv run python manage.py makemigrations --check --dry-run
```

Expected: all pass, and no new migrations — nothing in this plan changes a model field.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "feat(documents): one entry point for the gap interview's deterministic checks"
```

---

## What the next plan inherits

- `gaps.py` has no caller. The change that gives it one designs the form, and — because types 1, 2 and 6 arrive with a model call — carries the per-student rate limiter from `apps/ratelimit.py::rate_limited` in the same change, per `CLAUDE.md`.
- The honours-classification question needs a field on `EducationEntry`, a `schema_version` bump to 4, and belongs with the type-7 sections (conference presentations, referees) rather than on its own.
- Transcript ingestion does not exist anywhere in this repository. When it lands, `missing_grade` needs no change — it reads the ledger, and a transcript's grades will be EDUCATION facts in it. What it will change is the *volume* of type-4 questions, downward.
- Task 1's `supervisor` payload key fixes a round-trip loss that predates the gap interview. If a regenerated CV still reads as taught-track for a research applicant after this plan, `render._section_order` is no longer the suspect.
