# TimelineEntry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the ledger somewhere to put "what were you doing between Jun 2023 and
Nov 2023", so the timeline detector stops emitting a note nobody can act on and starts
asking a question whose answer renders on the CV.

**Architecture:** A `TIMELINE` fact category holding `(start_date, end_date, statement)`,
a `TimelineEntry` on `CVContent` merged into the experience chronology at `render.py`'s one
ordering funnel, and `timeline_gaps` converted from
`GapNote` to a create-path `GapQuestion` group covering the spans between entries **and** the
span from the last entry to today. The create-path machinery today keys its
required-key list and its detector-supplied defaults off two module-level dicts looked up
by slug; a timeline gap's slug is per-gap (`timeline-gap:2023-06-30:2023-11-01`) and its
defaults are per-gap dates, so both move onto `GapQuestion` as server-built fields. That
is a net deletion — `_CREATE_GROUPS` goes away — and it is the only structural change.

**Tech Stack:** Django 5.2, Postgres, pydantic v2, WeasyPrint templates, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-cv-counsellor-review-design.md` §1b.
Phase 1 and its follow-up list: `docs/superpowers/plans/2026-09-17-cv-counsellor-review-phase-1.md`.

**Refreshed 2026-10-05** from the unexecuted 2026-09-17 draft (left untracked in the
`cv-phase2-timeline` worktree), re-checked against master `1a4c6b5e`. What changed, so a
reader of the old draft knows what not to trust in it:

- Migration `0016` → **`0025`**, depending on `0024_merge_20260927_0906`.
- `answer_questions` on master accumulates `(category, fields, asked)` and checks
  `asked != set(_CREATE_GROUPS[slug])`; Task 5 now replaces that exact shape.
- Test helpers are named for what master has: `test_verification.py` is table-driven
  (`CATEGORY_CASES` / `CONFLICT_CASES`, `_fact(..., confirmed=True)`, `verify_against_facts(content,
  [fact])`), render tests read PDF text through `_text(render_cv(...))`, ingestion tests stub the
  model through `_openai_client()` and call `ingest_uploaded_cv`. There is no `content_with`,
  `render_cv_html` or `write_facts`.
- **New Task 7: a gap statement never reaches a letter model.** `letters.py::_facts_payload`
  serialises every confirmed fact into the letter prompt; without a filter, "Illness, now
  recovered." becomes material for a motivation letter. The draft did not know the letter
  engine existed.
- The CV's reader is the **student**, not a counsellor (CLAUDE.md, "Who reads a CV warning").
  Wording that said "counsellor" is corrected where this plan writes new text.
- `claude/student-dashboard` (unmerged, under active work) rewrites `gap_interview.html` to
  extend `base.html`. Task 6's template change is two lines; whichever branch merges second
  re-applies them by hand. Do not restructure the template here.

## Global Constraints

- **Worktree.** All work happens in
  `/home/orkhan/Desktop/tehsil_agent/.worktrees/cv-timeline` on branch
  `claude/cv-timeline-entry`. Never `cd` to the main checkout; its git index is shared
  and other sessions commit there. Use `git -C <worktree>` if a shell resets its cwd.
- **Test database.** Always `POSTGRES_DB=tehsil_cvtimeline uv run pytest`. Never the shared
  default. Baseline to beat, measured on this branch at `1a4c6b5e` on 2026-10-05:
  **6368 passed, 72 skipped, 68 deselected, 2 xfailed**. It goes up, never down.
- **Never run `ruff format`** in this repo — it rewrites hundreds of untouched files and no
  gate runs the formatter. `uv run ruff check .` only.
- **Gates (CI's, `.github/workflows/ci.yml`):** `uv run ruff check .`, `uv run mypy apps config`,
  the full suite, `uv run python manage.py check`, and
  `uv run python manage.py makemigrations --check --dry-run`.
- **This branch's first migration.** CLAUDE.md's "Migrations: squash once" section applies —
  read it before Task 1. The squash window is still open and every branch carrying a
  migration collides with a squash; that is accepted here because the category cannot be
  added without one.
- **Threshold is 92 days** (`_MIN_GAP_DAYS`), TUM's three months, already in the code. Do
  not change it.
- **No model call is added anywhere in this plan.** `gaps.py`'s docstring says the module
  makes none, and that must stay true — detector 3 is a separate plan that owes a rate
  limiter.
- **A timeline statement never reaches europa.eu, and never reaches a letter model.** Task 3
  pins the first with a test, Task 7 the second. A gap statement is the most sensitive line
  on the CV — Cambridge's own printed samples are caring, illness and unemployment — so it
  goes exactly one place: the student's own CV, verbatim.

## Review Focus

Inputs the spec implies and no draft task exercised, most likely to bite first. Each line's
test lives in the task named.

1. **An answer longer than `TimelineEntry.statement` allows (300 characters).** The ledger
   stores the raw string, so without a guard a long answer lands as a fact and every later
   CV generation for that student fails schema validation. Expected: `answer_questions`
   refuses it with `UnanswerableQuestion` and the form re-renders it as an error. Test in
   Task 6.
2. **A gap answered, then a neighbouring entry's dates corrected so the gap widens.** Expected:
   only the uncovered remainder is asked, under its own slug, and the earlier answer still
   prints. Test in Task 6.
3. **An entry dated in the future** (an accepted place starting next September). Expected: the
   months before it that are already past are asked; the future months are not. The draft's
   arithmetic asked "between Jun 2025 and Sep 2026" in October 2025. Test and fix in Task 6.
4. **A gap statement in a letter.** Expected: never in the letter prompt. Test in Task 7.
5. **A CV with only gap rows and no posts.** Expected: the Experience heading and the rows
   print. Covered by Task 3's second render test.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `apps/documents/models.py` | `VerifiedFact.Category.TIMELINE`, check constraint | modify |
| `apps/documents/migrations/0025_timeline_category.py` | the choices + constraint migration | create |
| `apps/documents/schemas.py` | `TimelineEntry`, `CVContent.timeline` | modify |
| `apps/documents/verification.py` | the `_CategorySpec` that makes a timeline claim verifiable | modify |
| `apps/documents/templates/documents/_cv_experience.html` | a gap row in date order among the posts | modify |
| `apps/documents/templates/documents/gap_interview.html` | the statements a student can pick instead of explaining | modify |
| `apps/documents/render.py` | `_experience_rows` — the merge, at the one ordering funnel | modify |
| `apps/documents/europass.py` | nothing — the deliberate absence, pinned by a test | unchanged |
| `apps/documents/ingestion.py` | reads a printed gap entry off an uploaded CV | modify |
| `apps/documents/generation.py` | carries a timeline fact through unchanged | modify |
| `apps/documents/gaps.py` | `group_keys`/`defaults` on `GapQuestion`; `timeline_gaps` asks | modify |
| `apps/documents/letters.py` | `_facts_payload` drops TIMELINE facts | modify |
| `tests/documents/test_gaps.py` | the detector's tests, note → question | modify |
| `tests/documents/test_schemas.py` | `TimelineEntry` validation | modify |
| `tests/documents/test_verification.py` | timeline rows in `CATEGORY_CASES` / `CONFLICT_CASES` | modify |
| `tests/documents/test_render.py` | a gap row renders in order, with no employer and no bullets | modify |
| `tests/documents/test_europass.py` | the statement is not in the payload | modify |
| `tests/documents/test_ingestion.py` | an extracted gap line lands as a TIMELINE fact | modify |
| `tests/documents/test_gap_intake.py` | a timeline answer round-trips through the form | modify |
| `tests/documents/test_gap_interview_view.py` | the statements are offered | modify |
| `tests/documents/test_letters.py` | no gap statement in the letter prompt | modify |

---

### Task 1: The TIMELINE fact category

**Files:**
- Modify: `apps/documents/models.py:17-34` (the `Category` enum), `apps/documents/models.py:74-92`
  (the `verifiedfact_category_valid` check constraint)
- Create: `apps/documents/migrations/0025_timeline_category.py`
- Test: `tests/documents/test_gaps.py` (one new test at the end of the file)

**Interfaces:**
- Produces: `VerifiedFact.Category.TIMELINE == "TIMELINE"`, accepted by the database.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_gaps.py`:

```python
def test_a_timeline_fact_can_be_stored(student):
    fact = make_fact(
        student,
        VerifiedFact.Category.TIMELINE,
        {
            "start_date": "2023-06-30",
            "end_date": "2023-11-01",
            "statement": "Full-time carer for a family member.",
        },
    )

    assert fact.category == "TIMELINE"
    assert unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.TIMELINE
    ).count() == 1
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_gaps.py::test_a_timeline_fact_can_be_stored -q
```

Expected: `AttributeError: TIMELINE` on `VerifiedFact.Category`.

- [ ] **Step 3: Add the enum member and widen the constraint**

In `apps/documents/models.py`, after the `IDENTITY` member of `class Category` (the last
member; declaration order on master is `... PERSONAL, REFERENCE, IDENTITY`):

```python
        #: A span of time no education or experience entry covers, and the one
        #: line that accounts for it. Its own category because neither
        #: neighbouring shape fits: ExperienceEntry requires an employer and a
        #: bullet, and S-045 measured that what Cambridge actually prints for a
        #: gap ("Full-time carer for family member", "3 months' full-time
        #: job-hunting") has neither. Required by ETH, TUM (no gap over three
        #: months), DAAD PRIME (R-011), uni-assist (R-020) and Harvard GSD.
        TIMELINE = "TIMELINE"
```

In the same file's `verifiedfact_category_valid` check constraint, add `"TIMELINE"` to the
end of the `category__in` tuple (after `"REFERENCE"`).

- [ ] **Step 4: Generate the migration, then cut its dependencies to `documents` alone**

`makemigrations` adds a spurious cross-app dependency whenever another app also has an
unapplied migration, and that edge knots `tests/migrations/test_task7_migrations.py` into an
`InvalidMigrationPlan` — `0008` and `0015` carry a comment saying so. The current leaf is
`0024_merge_20260927_0906`. Generate it, then strip the dependency to `documents` alone:

```bash
POSTGRES_DB=tehsil_cvtimeline uv run python manage.py makemigrations documents --name timeline_category
```

Then edit the generated `apps/documents/migrations/0025_timeline_category.py` so it reads
exactly:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    # Only the documents dependency, deliberately -- same reason 0008 and 0015
    # state: makemigrations names every app touched in the same run, and an
    # edge to tenancy this migration does not need makes the cross-app plan in
    # tests/migrations/test_task7_migrations.py run in both directions at once.
    dependencies = [
        ('documents', '0024_merge_20260927_0906'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='verifiedfact',
            name='verifiedfact_category_valid',
        ),
        migrations.AlterField(
            model_name='verifiedfact',
            name='category',
            field=models.CharField(choices=[('EDUCATION', 'Education'), ('EXPERIENCE', 'Experience'), ('RESEARCH', 'Research'), ('PUBLICATION', 'Publication'), ('AWARD', 'Award'), ('LANGUAGE', 'Language'), ('SKILL', 'Skill'), ('PERSONAL', 'Personal'), ('REFERENCE', 'Reference'), ('IDENTITY', 'Identity'), ('TIMELINE', 'Timeline')], max_length=20),
        ),
        migrations.AddConstraint(
            model_name='verifiedfact',
            constraint=models.CheckConstraint(condition=models.Q(('category__in', ('EDUCATION', 'EXPERIENCE', 'RESEARCH', 'PUBLICATION', 'AWARD', 'LANGUAGE', 'SKILL', 'PERSONAL', 'IDENTITY', 'REFERENCE', 'TIMELINE'))), name='verifiedfact_category_valid'),
        ),
    ]
```

If the generated `AlterField` lists the choices in a different order from the one above, keep
the **generated** order — it mirrors the enum's declaration order, and `makemigrations --check`
in CI compares against exactly that.

- [ ] **Step 5: Run the test and the migration check**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_gaps.py::test_a_timeline_fact_can_be_stored -q
POSTGRES_DB=tehsil_cvtimeline uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/migrations -q
```

Expected: the test passes, `makemigrations --check` reports no changes, the migration tests
pass.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/models.py apps/documents/migrations/0025_timeline_category.py tests/documents/test_gaps.py
git commit -m "documents: a timeline entry is its own fact category -- an employer and a bullet are what a gap has not got"
```

---

### Task 2: `TimelineEntry` on the schema, and a spec that verifies it

**Files:**
- Modify: `apps/documents/schemas.py` (a new entry class after `LanguageEntry`, and one field
  on `CVContent`), `apps/documents/verification.py:84-183` (`_SPECS`)
- Test: `tests/documents/test_schemas.py`, `tests/documents/test_verification.py`

**Interfaces:**
- Consumes: `VerifiedFact.Category.TIMELINE` (Task 1).
- Produces: `schemas.TimelineEntry(start_date: date | None, end_date: date | None,
  statement: str)`; `CVContent.timeline: tuple[TimelineEntry, ...]`, default `()`, max 20;
  `verification.payload_keys("TIMELINE") == ("start_date", "end_date", "statement")`.

- [ ] **Step 1: Write the failing schema test**

Append to `tests/documents/test_schemas.py`:

```python
def test_a_timeline_entry_carries_a_span_and_one_statement():
    entry = TimelineEntry(
        start_date="June 2023",
        end_date="November 2023",
        statement="Full-time carer for a family member.",
    )

    assert entry.start_date == date(2023, 6, 1)
    assert entry.end_date == date(2023, 11, 30)
    assert entry.statement == "Full-time carer for a family member."


def test_a_timeline_entry_refuses_an_empty_statement():
    with pytest.raises(ValidationError):
        TimelineEntry(start_date="2023-06-30", end_date="2023-11-01", statement="")


def test_a_timeline_entry_refuses_a_statement_over_the_cap():
    with pytest.raises(ValidationError):
        TimelineEntry(
            start_date="2023-06-30",
            end_date="2023-11-01",
            statement="x" * (TIMELINE_STATEMENT_MAX + 1),
        )


def test_cv_content_has_no_timeline_by_default():
    assert _minimal_content().timeline == ()
```

`_minimal_content` is that file's own builder (`tests/documents/test_schemas.py:19`). Add
`TimelineEntry` and `TIMELINE_STATEMENT_MAX` to its `from apps.documents.schemas import (...)`.

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_schemas.py -q -k timeline
```

Expected: `ImportError`/`NameError` on `TimelineEntry`.

- [ ] **Step 3: Add the schema**

In `apps/documents/schemas.py`, after `class LanguageEntry` and before `class CVContent`:

```python
#: Shared with gaps.answer_questions, which refuses a longer answer at the
#: form. The ledger stores whatever string it is handed, so without that guard
#: a long answer becomes a fact every later generation fails to validate.
TIMELINE_STATEMENT_MAX = 300


class TimelineEntry(_RangeEntry):
    """A span nothing else on the CV covers, and the line that accounts for it.

    Not an ExperienceEntry with the awkward fields left blank: that model
    requires an employer and at least one bullet, and S-045 measured what
    Cambridge's own samples print for a gap -- "Full-time carer for family
    member", "3 months' full-time job-hunting" -- which has neither. Required
    by ETH, TUM ("must not contain any gaps longer than 3 months"), DAAD PRIME
    (R-011), uni-assist (R-020) and Harvard GSD.

    One statement, not bullets. A gap is accounted for, not sold: the bullet
    shape invites a model or a student to build an achievement out of a period
    of unemployment or illness, which is the opposite of what every source
    asks for.
    """

    model_config = _CONTENT_CONFIG

    start_date: CVDate = None
    end_date: CVEndDate = None
    statement: Annotated[str, BeforeValidator(_tidy_prose)] = Field(
        min_length=1, max_length=TIMELINE_STATEMENT_MAX
    )
```

On `CVContent`, after the `languages` field:

```python
    #: Deliberately last among the record tuples and defaulted to (): every
    #: CV generated before this field existed validates unchanged, and a CV
    #: with no gaps carries none.
    timeline: tuple[TimelineEntry, ...] = Field(default=(), max_length=20)
```

Check the imports at the top of `schemas.py` already include `Annotated`, `BeforeValidator`
and `Field` — they do, every other entry uses them — and add nothing.

- [ ] **Step 4: Run the schema tests**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_schemas.py -q
```

Expected: PASS.

- [ ] **Step 5: Add timeline rows to the verification tables**

`tests/documents/test_verification.py` is table-driven: every test is parametrized over
`CATEGORY_CASES` (and, for detail conflicts, `CONFLICT_CASES`), and the table's own comment
says a new category cannot be added to `CVContent` without a row. Add a sample entry beside
the others:

```python
_TIMELINE = TimelineEntry(
    start_date="2023-06-30",
    end_date="2023-11-01",
    statement="Full-time carer for a family member.",
)
```

then append to `CATEGORY_CASES`:

```python
    ("timeline", VerifiedFact.Category.TIMELINE, _TIMELINE),
```

and to `CONFLICT_CASES` — the statement is the detail compared, and a rewrite is exactly what
it must catch:

```python
    (
        "timeline",
        VerifiedFact.Category.TIMELINE,
        _TIMELINE,
        {"statement": "Took a planned career break to develop leadership skills."},
    ),
```

Add `TimelineEntry` to the file's schema import. `_content(field, entry)` already wraps any
non-`personal_information` field in a one-tuple, so it needs no change.

- [ ] **Step 6: Run it and watch it fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_verification.py -q -k timeline
```

Expected: the new `timeline` parametrizations fail -- no `_CategorySpec` covers the field, so
no `timeline` verdict is produced.

- [ ] **Step 7: Add the spec**

In `apps/documents/verification.py`, append to `_SPECS` (after the `personal_information`
spec — `_SPECS` order is verdict order, and a timeline entry is the least prominent thing on
the page):

```python
    _CategorySpec(
        # Identified by its span: two entries cannot describe the same months,
        # and the span is what the gap detector matched on when it asked.
        #
        # The statement IS compared, unlike every other piece of prose in this
        # table. The others (thesis_title, supervisor, funding) are a model's
        # transcription off a document, so comparing them blocks a draft over a
        # transcription difference. This one is the student's own typed
        # sentence, carried in and out unchanged, so a difference is a model
        # having rewritten a person's account of a period of their life --
        # exactly the thing to refuse.
        field="timeline",
        category=VerifiedFact.Category.TIMELINE,
        identity=("start_date", "end_date"),
        detail=("statement",),
        label=("statement",),
    ),
```

- [ ] **Step 8: Run the verification tests**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_verification.py tests/documents/test_schemas.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/documents/schemas.py apps/documents/verification.py tests/documents/test_schemas.py tests/documents/test_verification.py
git commit -m "documents: a timeline entry is a span and one statement, and the statement is verified like any other claim"
```

---

### Task 3: It renders in the chronology it interrupts, and it never reaches europa.eu

**Why in place rather than a section at the foot.** ETH, verbatim (S-047, BINDING where the
admissions page states it): "LEAVE NO TIME GAPS: **also list** periods when you did not attend
school, study or work". TUM, same rule: "chronological and tabular", "must not contain any gaps
longer than 3 months". S-041 has University College Cork putting the gap-filler among the roles
— "include name of organization and dates only to account for a possible gap" — and S-045's
Cambridge samples are the same shape without the organization. Every source that mentions
placement puts the gap in the history, not in an appendix.

So a timeline entry renders **inside the Experience section**, date-ordered with the experience
entries. Experience and not Education: ETH's own wording groups a gap with "did not attend
school, study or work", which makes it a period of activity like a post, not a qualification
like a degree. A gap between two degrees still renders under Experience — it is listed, dated
and in order, which is all ETH's "also list" asks.

Not a merged whole-CV chronology. S-001 (education and research before employment for a
master's applicant) and R-027's track ordering both require the section structure, so merging
every dated section into one list would break two rules to satisfy one.

**Where the merge goes, and why not on the schema.** `render.py` already owns every ordering
decision: `reverse_chronological` (`render.py:228`) sorts `education`, `experience` and
`research` newest-first with `_newest_first`, and `apply_directives` (`render.py:482`) then
reverses a section to `chronological` when a programme page said so. A sort added anywhere else
— a property on `CVContent`, say — would run after both and silently discard the directive. So
the merge is a function in `render.py` that reuses `_newest_first` and follows whatever
direction `experience` ended up in, and the template reads it from the context.

**Files:**
- Modify: `apps/documents/render.py` (one helper beside `_newest_first`, one context key in
  `_render_pdf`'s `render_to_string` call at `render.py:462`),
  `apps/documents/templates/documents/_cv_experience.html`
- Test: `tests/documents/test_render.py`, `tests/documents/test_europass.py`

**Interfaces:**
- Consumes: `CVContent.timeline` (Task 2).
- Produces: `render._experience_rows(content: CVContent) -> tuple[ExperienceEntry | TimelineEntry, ...]`
  and the template context key `experience_rows`. No schema change, no new partial, no new
  section, no change to either track tuple.

- [ ] **Step 1: Write the failing tests**

Append to `tests/documents/test_render.py`. It renders through `render_cv` /
`render_cv_with_warnings` and reads the PDF's text with `_text`; `_content(experience=...)` and
`_directive(...)` are its own helpers. `_content` has no `timeline` parameter, so the gap rows
go on the way `_content_with_skills` adds skills:

```python
_GAP = TimelineEntry(
    start_date="2023-06-30",
    end_date="2023-11-01",
    statement="Full-time carer for a family member.",
)
_ICIQ = ExperienceEntry(
    employer="ICIQ",
    title="Research Intern",
    city="Tarragona",
    country="ES",
    start_date="2023-11-01",
    end_date="2024-02-29",
    bullets=("Ran a screen of forty catalysts.",),
)


def _with_timeline(content, *entries):
    return CVContent.model_validate(
        {**content.model_dump(mode="json"), "timeline": [e.model_dump(mode="json") for e in entries]}
    )


def test_a_timeline_entry_renders_among_the_experience_entries():
    content = _with_timeline(_content(experience=(_ICIQ,)), _GAP)

    text = _text(render_cv(content, variant="STANDARD"))

    assert "Full-time carer for a family member." in text
    # Reverse-chronological by default (S-001): the later post, then the gap.
    assert text.index("Research Intern") < text.index("Full-time carer")


def test_a_cv_whose_only_dated_row_is_a_gap_still_has_the_section():
    content = _with_timeline(_content(experience=()), _GAP)

    text = _text(render_cv(content, variant="STANDARD"))

    assert "Experience" in text
    assert "Full-time carer for a family member." in text


def test_a_gap_row_prints_no_employer_line_and_no_bullets():
    html = render_to_string(
        "documents/_cv_experience.html",
        {"experience_rows": (_GAP,), "tabular": False},
    )

    assert "Full-time carer for a family member." in html
    assert "<li>" not in html


def test_a_chronological_directive_moves_the_gap_with_the_posts():
    """The merge follows apply_directives, not only reverse_chronological.

    A sort that ran after the directive would put the gap in the newest-first
    position on a CV whose posts had just been flipped to oldest-first.
    """
    content = _with_timeline(_content(experience=(_ICIQ,)), _GAP)

    artifact, _ = render_cv_with_warnings(
        content, variant="STANDARD", directives=(_directive("order", "cv", "chronological"),)
    )

    text = _text(artifact)
    assert text.index("Full-time carer") < text.index("Research Intern")
```

Import `TimelineEntry` (and `ExperienceEntry` / `CVContent` if the file does not already) from
`apps.documents.schemas`. If `_content(experience=())` trips a validator because the fixture
needs at least one experience row, build that test's content with `_content()` and replace
`experience` through `model_validate` the same way.

Append to `tests/documents/test_europass.py`, using its own `_content(**overrides)`:

```python
def test_a_timeline_statement_never_reaches_europass():
    """The one path carrying student PII off-platform does not carry this.

    A gap statement is the most sensitive line on the CV -- Cambridge's own
    printed samples are illness, caring and unemployment -- and Europass has no
    field for it, so mapping one would mean choosing a field it does not belong
    in. The absence is the decision; this test is what keeps it one.

    This is about the EUROPASS_API path only. The EUROPASS render variant is a
    local template extending cv_base.html, so a gap row does print on that
    PDF -- which is ours, read by the student, and never sent anywhere.
    """
    content = _content(
        timeline=(
            TimelineEntry(
                start_date="2023-06-30",
                end_date="2023-11-01",
                statement="Full-time carer for a family member.",
            ),
        )
    )

    payload = json.dumps(europass_payload(content), default=str)

    assert "carer" not in payload
    assert "timeline" not in payload.lower()
```

Import `json` and `TimelineEntry` if the file does not already.

- [ ] **Step 2: Run them and watch the render ones fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_render.py tests/documents/test_europass.py -q -k "timeline or gap"
```

Expected: the Europass test already passes (nothing maps the field) — a test that passes before
the feature exists is the point here, it guards a future change rather than describing today.
The four render tests fail: the statement is nowhere in the output (the template test fails
on the missing `experience_rows` loop).

- [ ] **Step 3: Add the merge to `render.py`**

Immediately after `_newest_first` (`apps/documents/render.py:210`):

```python
def _experience_rows(content: CVContent) -> tuple[ExperienceEntry | TimelineEntry, ...]:
    """Posts and gap statements in one run, in whatever direction experience is in.

    ETH (S-047, binding where the admissions page states it) asks the CV to
    "leave no time gaps: ALSO LIST periods when you did not attend school,
    study or work", and TUM's tabular CV "must not contain any gaps longer than
    3 months". Both read as requirements on the chronology a reader scans, so a
    gap is listed where it happened rather than in a section at the foot.

    Experience and not education: ETH's own wording groups a gap with "did not
    attend school, study or work", which makes it a period like a post rather
    than a qualification like a degree.

    Computed HERE and not as a property on CVContent, because ordering in this
    codebase happens at one funnel and in two steps: reverse_chronological
    sorts newest-first, then apply_directives may reverse a section to
    chronological on a programme page's instruction. A sort anywhere downstream
    of that would quietly discard the directive. Reading the direction back off
    `experience` rather than off the directives is what keeps this a pure
    function of the content the template is about to render.
    """
    rows = _newest_first(content.experience + content.timeline)
    if content.experience != _newest_first(content.experience):
        return tuple(reversed(rows))
    return rows
```

`ExperienceEntry` and `TimelineEntry` need importing from `.schemas` at the top of `render.py`
if they are not already there; `CVContent` is.

Then in `_render_pdf`'s `render_to_string` context (`apps/documents/render.py:462`), add:

```python
            # Not content.experience: _cv_experience.html renders the posts and
            # the gap statements as one chronology (see _experience_rows).
            "experience_rows": _experience_rows(content),
```

- [ ] **Step 4: Render the merged sequence**

In `apps/documents/templates/documents/_cv_experience.html`, change both branches to iterate
`experience_rows` and branch each row on whether it is a gap.

The outer guard and the tabular branch:

```html
{% load cv_dates cv_countries %}{% if experience_rows %}<h2>Experience</h2>
{% if tabular %}
<table class="grid">
  {% for entry in experience_rows %}
  <tr>
    <td class="when">{{ entry.start_date|month_year }} – {{ entry.end_date|month_year:"present" }}</td>
    {% if entry.statement %}<td>{{ entry.statement }}</td>
    {% else %}<td><strong>{{ entry.title }}</strong><br>
    {% if entry.group %}{{ entry.group }}, {% endif %}{{ entry.employer }}{% if entry.city or entry.country %}, {% include "documents/_cv_place.html" with entry=entry only %}{% endif %}{% if entry.distinct_supervisor %} — Supervisor: {{ entry.distinct_supervisor }}{% endif %}<br>
    {% include "documents/_cv_bullets.html" with entry=entry only %}</td>{% endif %}
  </tr>
  {% endfor %}
</table>
{% else %}
```

And the prose branch's loop body gains a gap arm before the existing post markup:

```html
{% for entry in experience_rows %}
{% if entry.statement %}
<div class="entry">
  {% comment %}
     A GAP ROW. One line, no employer and no bullets, sitting in date order
     among the posts -- ETH: "leave no time gaps: also list periods when you
     did not attend school, study or work"; S-045 records Cambridge's own
     samples, which have no employer at all. Deliberately not dressed up: a
     gap is accounted for, not sold, and the bullet shape invites a model or a
     student to build an achievement out of an illness.

     Branching on `statement` because a Django template cannot ask a value its
     type, and TimelineEntry is the only entry here that has one. If
     ExperienceEntry ever gains a `statement` field, this branch is what
     breaks -- add an explicit flag then.
  {% endcomment %}
  <div class="entry-header"><strong>{{ entry.statement }}</strong><span>{{ entry.start_date|month_year }} – {{ entry.end_date|month_year:"present" }}</span></div>
</div>
{% else %}
```

…followed by the existing `<div class="entry">…</div>` post markup unchanged, then `{% endif %}`
before the existing `{% endfor %}`.

The outer guard moves from `content.experience` to `experience_rows` so a student whose only
dated rows are gaps still gets the section and its heading.

- [ ] **Step 5: Run the render and Europass suites in full**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_render.py tests/documents/test_europass.py tests/documents/test_funder_templates.py -q
```

Expected: PASS, with no change to any existing experience-order test — `_experience_rows`
re-sorts a tuple `reverse_chronological` already sorted, which is idempotent, and a CV with no
timeline entries gets back exactly what it had.

`cv_funder_rhodes.html` and `cv_funder_sisgp.html` do not extend `cv_base.html` and get their
context from `apps/documents/funder_templates/` (`sisgp.py` caps and splits `experience` itself),
not from `_render_pdf`, so they never see `experience_rows`. They are unchanged and print no gap
rows. Correct for now: both are fixed-form documents whose sections the funder dictates,
and adding one is that funder's decision, not ours.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/render.py apps/documents/templates/documents/_cv_experience.html tests/documents/test_render.py tests/documents/test_europass.py
git commit -m "documents: a gap is listed where it happened -- ETH asks for the periods to be in the chronology, not in an appendix"
```

---

### Task 4: Ingestion reads one, generation carries one through

**Files:**
- Modify: `apps/documents/ingestion.py:82-95` (`_SECTIONS`) and its instruction string (the
  experience/project sentences around `apps/documents/ingestion.py:340-360`)
- Modify: `apps/documents/generation.py` (the `instructions` string in `_call_model`, after the
  `unpaid` sentence around line 246)
- Test: `tests/documents/test_ingestion.py`

**Interfaces:**
- Consumes: `CVContent.timeline` (Task 2), `VerifiedFact.Category.TIMELINE` (Task 1).
- Produces: an uploaded CV printing a gap line lands as a `TIMELINE` fact; a `TIMELINE` fact
  reaches a generated CV unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_ingestion.py`. The file stubs the model with
`_openai_client()`, whose parsed output is `_content()`; this test hands it a content carrying
one gap line and drives the real `ingest_uploaded_cv`, exactly as
`test_ingestion_writes_unconfirmed_student_statement_facts` does:

```python
def test_a_gap_line_on_an_upload_becomes_a_timeline_fact(
    agency_a, django_user_model, fake_store
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "i-timeline")
        document = apply_scan_result(register(agency_a.id, student.id), "NO_THREATS_FOUND")
        fake_store.put(document.object_key, _pdf())
        client = _openai_client()
        client.responses.parse.return_value.output_parsed = CVContent.model_validate(
            {
                **_content().model_dump(mode="json"),
                "timeline": [
                    {
                        "start_date": "2023-06-30",
                        "end_date": "2023-11-01",
                        "statement": "Full-time carer for a family member.",
                    }
                ],
            }
        )

        facts = ingest_uploaded_cv(
            document=document, student=student, client=client, store=fake_store
        )

        timeline = [f for f in facts if f.category == VerifiedFact.Category.TIMELINE]
        assert len(timeline) == 1
        assert timeline[0].payload["statement"] == "Full-time carer for a family member."
        assert timeline[0].confirmed_by is None
```

Assert the statement and not the whole payload: dates go through the same `fact_payload`
serialisation every other category uses, and pinning its date format here would test that
function instead of this change.

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_ingestion.py -q -k timeline
```

Expected: `len(timeline) == 1` fails with 0 — `_SECTIONS` does not list the field.

Run `-k timeline_fact` if `-k timeline` also selects other tests in that file.

- [ ] **Step 3: Add the section and the instruction sentence**

In `apps/documents/ingestion.py`, add to `_SECTIONS` after `("languages", ...)`:

```python
    ("timeline", VerifiedFact.Category.TIMELINE),
```

And in the instruction string, after the sentence about an experience entry's project:

```python
                        "A span DATA accounts for without naming an employer or duties -- "
                        "a career break, caring, illness, military service, job-hunting -- "
                        "is a timeline entry, never an experience entry: copy its dates and "
                        "its sentence as DATA prints them and write nothing DATA does not "
                        "state. A role with an employer is never a timeline entry. "
```

- [ ] **Step 4: Add the generation instruction**

In `apps/documents/generation.py`, in `_call_model`'s `instructions`, after the `unpaid`
sentence:

```python
        # The student's own account of a period of their life, typed into the
        # gap interview. A model that rewrites it has authored a claim about a
        # person's circumstances; verification.py's TIMELINE spec compares the
        # statement for exactly this reason, so a rewrite lands as CONFLICTING
        # rather than silently.
        "Carry a timeline fact through unchanged -- its dates and its statement word "
        "for word. Never invent a timeline entry, never rewrite one into an "
        "achievement, and never move a timeline entry into experience. "
```

- [ ] **Step 5: Run the ingestion and generation tests**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_ingestion.py tests/documents/test_generation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/ingestion.py apps/documents/generation.py tests/documents/test_ingestion.py
git commit -m "documents: an uploaded CV's gap line lands as a timeline fact, and generation carries it word for word"
```

---

### Task 5: A create group declares its own keys and defaults

This task changes no behaviour. It moves two facts about a create-path group — which keys it
needs answered, and which values the detector supplies — from module-level dicts looked up by
slug onto the question itself, because Task 6's slug is built per gap and cannot be in a
static dict. `_CREATE_GROUPS` is deleted.

**Files:**
- Modify: `apps/documents/gaps.py:139-171` (`GapQuestion`), `apps/documents/gaps.py:291-330`
  (`_CREATE_GROUPS`, `_GROUP_DEFAULTS`, `_group_questions`), `apps/documents/gaps.py:1210-1270`
  (`answer_questions`'s creation half)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Produces: `GapQuestion.group_keys: tuple[str, ...]` and
  `GapQuestion.defaults: tuple[tuple[str, str | bool], ...]`, both defaulting to `()`, both
  server-built. `GapQuestion.__post_init__` raises `ValueError` when `fact_id is None` and
  `group_keys` is empty, alongside the existing slug check.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_gaps.py`:

```python
def test_a_create_question_declares_its_own_group_keys_and_defaults(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {"degree_as_awarded": "MSc", "institution_original": "Strasbourg"},
    )

    voluntary = [
        q for q in gap_questions(student) if q.slug == "voluntary-role"
    ]

    assert {q.group_keys for q in voluntary} == {("employer", "title", "bullets")}
    assert {q.defaults for q in voluntary} == {(("unpaid", True),)}


def test_a_question_with_no_fact_and_no_group_keys_is_refused():
    with pytest.raises(ValueError):
        GapQuestion(
            kind=Kind.ABSENT_SECTION,
            fact_id=None,
            slug="anything",
            payload_key="title",
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.AWARD,
        )
```

Two existing tests read `gaps._CREATE_GROUPS`, which this task deletes. Rewrite both now, in
the same file, so they test the same guarantee through the question instead:

`test_a_created_answer_is_refused_a_key_its_category_does_not_carry` (around line 855) — drop
the `monkeypatch.setitem(gaps._CREATE_GROUPS, ...)` line and the `monkeypatch` parameter, and
declare the misconfigured key set on the question itself:

```python
def test_a_created_answer_is_refused_a_key_its_category_does_not_carry(student):
    """Same trust boundary as the supersession path: the key is checked against
    the category, not trusted from the question object.

    The unknown-key guard only runs once a group is COMPLETE, so reaching it
    needs a question whose declared group keys themselves name an unsupported
    key -- a detector misconfiguration, not a value a form could produce.
    """
    bad = GapQuestion(
        kind=Kind.MISSING_AWARD,
        fact_id=None,
        category=VerifiedFact.Category.AWARD,
        payload_key="employer",
        prompt="x",
        evidence="y",
        slug="bad-group",
        group_keys=("employer",),
    )
    with pytest.raises(UnanswerableQuestion):
        answer_questions([(bad, "something")], student=student)
```

`test_every_create_slug_a_detector_emits_is_declared` (around line 1396) — keep its setup and
replace everything from `emitted = ...` down with:

```python
    creates = [q for q in gap_questions(student) if q.fact_id is None]

    assert creates
    for slug in {q.slug for q in creates}:
        group = [q for q in creates if q.slug == slug]
        # One declaration per group, and the group asks exactly what it declares:
        # a key declared and never asked would make the group unwritable, a key
        # asked and not declared would be silently dropped.
        assert len({q.group_keys for q in group}) == 1
        assert {q.payload_key for q in group} == set(group[0].group_keys)
```

Rename it `test_every_create_group_asks_exactly_its_declared_keys`.

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_gaps.py -q -k "group_keys or declared_keys or does_not_carry"
```

Expected: `AttributeError: 'GapQuestion' object has no attribute 'group_keys'`.

- [ ] **Step 3: Add the two fields**

In `apps/documents/gaps.py`, on `GapQuestion`, after `slug`:

```python
    #: Every payload key this question's GROUP needs answered before
    #: answer_questions writes the fact -- not just this question's own key.
    #: Server-built and identical on every question of a group, like `category`
    #: and for the same reason: it decides whether a half-answered group is
    #: written, which is a trust decision the form must not reach.
    #:
    #: It travels on the question rather than in a table keyed by slug because
    #: a timeline gap's slug names the span it is about
    #: ("timeline-gap:2023-06-30:2023-11-01") and cannot be a module constant.
    #:
    #: Required whenever fact_id is None. Without it every create-path group
    #: would be written from whatever subset the student happened to answer.
    group_keys: tuple[str, ...] = ()
    #: Payload values the DETECTOR supplies, which nobody is asked for: a
    #: voluntary role is unpaid by construction, and a timeline entry's dates
    #: are the gap the detector found. Merged after the completeness check, so
    #: a default never counts as an answer.
    defaults: tuple[tuple[str, str | bool], ...] = ()
```

And extend `__post_init__`:

```python
    def __post_init__(self) -> None:
        if self.fact_id is None and self.slug is None:
            raise ValueError("a question with no fact must carry a slug")
        if self.fact_id is None and not self.group_keys:
            raise ValueError("a question with no fact must declare its group keys")
```

- [ ] **Step 4: Have `_group_questions` stamp them, and delete `_CREATE_GROUPS`**

Delete the `_CREATE_GROUPS` definition (`apps/documents/gaps.py:291-296` on master, including
its comment). Keep `_GROUPS` and `_GROUP_DEFAULTS` exactly as they are — they are still the
readable declaration of every static group — and change `_group_questions` to copy them onto
each question:

```python
def _group_questions(slug: str, kind: Kind, evidence: str) -> tuple[GapQuestion, ...]:
    """Every question in a create-path group, sharing one evidence string.

    `_GROUPS` supplies the category, keys and prompts and `_GROUP_DEFAULTS` the
    values nobody is asked for; both are stamped onto every question of the
    group, because answer_questions reads them off the question rather than
    looking them up by slug -- see GapQuestion.group_keys for why.

    Evidence stays a parameter because a group's evidence counts the student's
    own rows (see missing_award) and cannot be a constant.
    """
    category, asks = _GROUPS[slug]
    keys = tuple(key for key, _ in asks)
    defaults = tuple(sorted(_GROUP_DEFAULTS.get(slug, {}).items()))
    return tuple(
        GapQuestion(
            kind=kind,
            fact_id=None,
            category=category,
            slug=slug,
            group_keys=keys,
            defaults=defaults,
            payload_key=key,
            prompt=prompt,
            evidence=evidence,
        )
        for key, prompt in asks
    )
```

Retype `_GROUP_DEFAULTS` so the sorted-items tuple matches the field:

```python
_GROUP_DEFAULTS: dict[str, dict[str, str | bool]] = {"voluntary-role": {"unpaid": True}}
```

- [ ] **Step 5: Read them off the question in `answer_questions`**

Replace the `creations` accumulator and its write loop. The dict now carries one representative
question per slug rather than a 3-tuple:

```python
    # slug -> (one question of that group, the answers given). A new entry
    # takes several answers -- an EducationEntry needs an institution AND a
    # degree, an ExperienceEntry an employer, a title and a bullet -- so the
    # group is the unit of creation, not the question. The question is kept
    # because it carries the group's category, its full key list and its
    # defaults; all three are server-built and identical across the group.
    creations: dict[str, tuple[GapQuestion, dict[str, str]]] = {}
```

In the loop over `answers`, replace the `fact_id is None` branch's body after the
`category is None` check with:

```python
            slug = question.slug
            assert slug is not None  # GapQuestion.__post_init__ guarantees it
            first, fields = creations.setdefault(slug, (question, {}))
            if first.category != question.category:
                raise UnanswerableQuestion(f"{slug} names two categories")
            if first.group_keys != question.group_keys:
                raise UnanswerableQuestion(f"{slug} declares two key sets")
            fields[question.payload_key] = value
            continue
```

And the write loop's head:

```python
    for slug, (question, fields) in creations.items():
        # All or nothing. A half-answered group writes a fact no reader can use
        # -- an EDUCATION row holding an institution and no degree gives
        # generation nothing to build an entry from, and the model's only legal
        # move is to invent the other half. A dropped partial answer costs one
        # re-ask, which the interview does on its own because the detector
        # still fires.
        if set(fields) != set(question.group_keys):
            continue
        category = question.category
        assert category is not None  # checked when the answer was read
        # Merged after the completeness check above: a default is not
        # something the student answered, and must not count toward it.
        full_fields: dict[str, object] = {**fields, **dict(question.defaults)}
```

The rest of that loop (the `unknown` key check, the `_LIST_KEYS` wrap, the
`VerifiedFact.objects.create` call) is unchanged.

- [ ] **Step 6: Run the whole gaps and intake suite**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_intake.py tests/documents/test_gap_interview_view.py -q
uv run mypy apps/documents
```

Expected: PASS, including every existing create-group test — this task changed no behaviour,
and a red test here means the move lost something.

- [ ] **Step 7: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: a create group carries its own key list and defaults, so a slug can name the gap it is about"
```

---

### Task 6: The timeline detector asks

Three things land together because they are one behaviour: the detector emits questions rather
than notes, it looks at the span from the last entry to today as well as the spans between
entries, and the form offers a set of statements so that a student who will not explain a gap
can still close it.

**The trailing gap.** ETH asks for "all details right up to the time of application"; the
detector today iterates `spans[1:]` and never compares its running coverage against today, so a
student who finished a degree fourteen months ago is asked nothing about those fourteen months —
the most likely gap on a real applicant's CV. Its answer is stored with **no end date**, which
is how `timeline_gaps` already reads "still running", so it closes permanently and prints as
"Nov 2024 – present". An end date of *today* would reopen the gap 93 days later and re-ask.

**The student who will not answer.** Every other create group stops via `_already_created`; this
one stops because the answer covers the span, so an unanswered gap re-fires on every page load
and `gaps.py`'s own docstring says nagging is how a form gets abandoned. The close is a
`<datalist>` of neutral statements on the timeline inputs: the student picks "Personal reasons."
or types their own, it is an ordinary answer writing an ordinary fact, and what they picked is
exactly what prints on the CV. No new mechanism, no dismissal store, and no question that
cannot be made to go away.

**Files:**
- Modify: `apps/documents/gaps.py:1-30` (module docstring), `:97-126` (`Kind`),
  `:337-384` (`timeline_gaps`), `:424-430` (`gap_notes`), `:1178-1270` (`answer_questions`, the
  statement-length guard), `:1312-1346` (`gap_questions`)
- Modify: `apps/documents/templates/documents/gap_interview.html`
- Test: `tests/documents/test_gaps.py:965-1115` (the existing timeline tests),
  `tests/documents/test_gap_intake.py`, `tests/documents/test_gap_interview_view.py`

**Interfaces:**
- Consumes: everything from Tasks 1, 2 and 5.
- Produces: `timeline_gaps(student) -> tuple[GapQuestion, ...]`; `gap_notes` returns only the
  certificates note; `gap_questions` includes timeline gaps.

- [ ] **Step 1: Rewrite the existing timeline tests to expect questions**

In `tests/documents/test_gaps.py`:

- `test_a_four_month_gap_between_two_entries_is_a_note` → rename to
  `test_a_four_month_gap_between_two_entries_is_a_question` and replace its assertions:

```python
    questions = timeline_gaps(student)

    assert len(questions) == 1
    assert questions[0].kind == Kind.TIMELINE_GAP
    assert questions[0].category == VerifiedFact.Category.TIMELINE
    assert questions[0].fact_id is None
    assert questions[0].slug == "timeline-gap:2023-06-30:2023-11-01"
    assert questions[0].payload_key == "statement"
    assert questions[0].group_keys == ("statement",)
    assert questions[0].defaults == (
        ("end_date", "2023-11-01"),
        ("start_date", "2023-06-30"),
    )
    assert "2023" in questions[0].prompt
```

- `test_a_two_month_gap_is_not_a_note` → rename to `..._is_not_a_question`, assertion
  unchanged (`timeline_gaps(student) == ()`).
- `test_overlapping_entries_leave_no_gap` and
  `test_an_entry_still_running_ends_the_timeline_today` — unchanged. Both students' latest
  entry runs to today, so neither grows a trailing gap.
- **Delete** `test_a_note_is_never_a_question` outright. It asserted the exact thing this task
  reverses, and its replacement is the next test.
- `test_gap_notes_includes_the_timeline_detector` → replace with:

```python
def test_gap_notes_is_the_certificates_note_alone(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )

    assert gap_notes(student) == (_CERTIFICATES_NOTE,)
    assert timeline_gaps(student)
```

Note that this student's last entry ends 29 Feb 2024, so from 2026 they also carry a trailing
gap; `timeline_gaps(student)` is truthy either way and `gap_notes` is what this test is about.

- [ ] **Step 2: Add the tests for the two new behaviours**

```python
def test_answering_a_timeline_gap_closes_it(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )
    question = next(
        q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"
    )

    written = answer_questions(
        [(question, "Full-time carer for a family member.")], student=student
    )

    assert len(written) == 1
    assert written[0].payload == {
        "start_date": "2023-06-30",
        "end_date": "2023-11-01",
        "statement": "Full-time carer for a family member.",
    }
    assert written[0].source_ref == "gap-interview:timeline-gap:2023-06-30:2023-11-01"
    assert not [
        q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"
    ]


def test_a_span_from_the_last_entry_to_today_is_asked(student):
    """ETH: "all details right up to the time of application"."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )

    questions = timeline_gaps(student)

    assert len(questions) == 1
    assert questions[0].slug == "timeline-gap:2023-06-30:present"
    # No end date: the span runs to today, and today moves.
    assert questions[0].defaults == (("start_date", "2023-06-30"),)


def test_answering_the_trailing_gap_closes_it_permanently(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    question = timeline_gaps(student)[0]

    written = answer_questions([(question, "Full-time job-hunting.")], student=student)

    assert written[0].payload == {
        "start_date": "2023-06-30",
        "statement": "Full-time job-hunting.",
    }
    # An entry with no end date covers the timeline to today, forever -- so
    # this does not reopen in 93 days the way an end_date of today would.
    assert timeline_gaps(student) == ()


def test_an_entry_running_to_today_leaves_no_trailing_gap(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    assert timeline_gaps(student) == ()


def test_two_gaps_get_two_distinct_form_fields(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2016-09-01",
            "end_date": "2019-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2020-06-01",
            "end_date": "2020-12-31",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "EPFL",
            "title": "Intern",
            "start_date": "2022-01-01",
            "end_date": "2022-08-31",
        },
    )

    questions = timeline_gaps(student)

    # Two between-entry gaps plus the trailing one to today.
    assert len(questions) == 3
    assert len({field_name(q) for q in questions}) == 3
```

```python
def test_a_widened_gap_asks_only_the_remainder(student):
    """Review Focus 2: an answer covers the span it was asked about. When a
    neighbouring entry's dates are later corrected, the new hole is asked
    under its own slug and the old answer still stands."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.TIMELINE,
        {
            "start_date": "2023-06-30",
            "end_date": "2023-11-01",
            "statement": "Full-time carer for a family member.",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2024-03-01",
            "end_date": "2024-08-31",
        },
    )

    slugs = {q.slug for q in timeline_gaps(student)}

    assert "timeline-gap:2023-11-01:2024-03-01" in slugs
    assert not any(slug.startswith("timeline-gap:2023-06-30") for slug in slugs)


def test_an_entry_that_has_not_started_yet_covers_nothing(student):
    """Review Focus 3: a place starting next year must not turn the months
    before it into a gap that ends in the future."""
    today = date.today()
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": f"{today.year - 4}-09-01",
            "end_date": f"{today.year - 1}-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "TUM",
            "start_date": f"{today.year + 1}-10-01",
        },
    )

    slugs = [q.slug for q in timeline_gaps(student)]

    # Asked as the span to today, not as a span ending in the future.
    assert slugs == [f"timeline-gap:{today.year - 1}-06-30:present"]


def test_an_answer_longer_than_the_entry_allows_is_refused(student):
    """Review Focus 1: the ledger keeps any string, so the cap is enforced
    where the answer arrives -- otherwise every later generation fails."""
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    question = timeline_gaps(student)[0]

    with pytest.raises(UnanswerableQuestion):
        answer_questions(
            [(question, "x" * (TIMELINE_STATEMENT_MAX + 1))], student=student
        )
    assert not unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.TIMELINE
    ).exists()
```

Import `field_name` from `apps.documents.gap_intake`, `TIMELINE_STATEMENT_MAX` from
`apps.documents.schemas` and `date` from `datetime` at the top of the test module if they are
not already imported there.

- [ ] **Step 3: Run them and watch them fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_gaps.py -q -k "timeline or gap_notes"
```

Expected: `AttributeError: TIMELINE_GAP` on `Kind`, and the note/question assertions failing.

- [ ] **Step 4: Add the Kind**

In `apps/documents/gaps.py`, after `EDUCATION_COMPLETENESS`:

```python
    #: A span longer than three months that no education, experience or
    #: timeline entry covers -- including the span from the last entry to
    #: today. A question since the TIMELINE category exists to hold the
    #: answer; it was a note for as long as it did not.
    TIMELINE_GAP = "TIMELINE_GAP"
```

- [ ] **Step 5: Rewrite `timeline_gaps`**

```python
def timeline_gaps(student: Membership) -> tuple[GapQuestion, ...]:
    """Uncovered spans between the education, experience and timeline entries.

    A question since the TIMELINE category exists; it was a NOTE for as long as
    the ledger had nowhere to put the answer. S-045 measured what Cambridge
    actually prints for a gap -- "Full-time carer for family member", "3 months'
    full-time job-hunting" -- and neither has an employer or a bullet, which
    ExperienceEntry requires both of.

    TIMELINE facts are scanned alongside the other two, which is what stops a
    gap being asked twice: an answer covers exactly the span it was asked
    about, so the next run finds the timeline continuous. There is no
    _already_created call here for that reason -- unlike every other create
    group, this detector's own arithmetic tells it the question was answered.

    THE TRAILING SPAN IS A GAP TOO. ETH wants "all details right up to the time
    of application", and the span from the last entry to today is the one most
    likely to exist on a real applicant's CV -- the months between finishing a
    degree and applying. Its answer is stored with NO END DATE, which this
    function already reads as "still running": an end date of today would leave
    the gap reopening a day later and re-firing 93 days after that.

    A between-entries gap's stored span runs from the end of the previous entry
    to the start of the next, so it overlaps each neighbour by a day.
    Deliberate: the alternative is +/- 1 day arithmetic that leaves a one-day
    hole the next run could round back into a gap, and at the month granularity
    the CV prints, the overlap is invisible.

    An entry with no end date is still running, so it covers the timeline up to
    today: end_date=None renders as "present" everywhere else in this codebase
    and means the same thing here. An entry with no start date cannot be placed
    and is skipped rather than guessed at.
    """
    spans: list[tuple[date, date]] = []
    for category in (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.TIMELINE,
    ):
        for fact in _current(student, category):
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            start = _read_date(payload.get("start_date"))
            # An entry that has not started yet -- an accepted place beginning
            # next September -- covers nothing so far. Counted, it would make
            # the months before it a gap ending in the future, and the student
            # would be asked to account for time that has not happened.
            if start is None or start > date.today():
                continue
            end = _read_date(payload.get("end_date")) or date.today()
            if end >= start:
                spans.append((start, end))
    # Not `< 2`, as it was while this only looked BETWEEN entries: one entry
    # that ended two years ago is a trailing gap on its own.
    if not spans:
        return ()
    spans.sort()
    questions: list[GapQuestion] = []
    covered_to = spans[0][1]
    for start, end in spans[1:]:
        if (start - covered_to).days > _MIN_GAP_DAYS:
            questions.append(_timeline_question(covered_to, start))
        covered_to = max(covered_to, end)
    if (date.today() - covered_to).days > _MIN_GAP_DAYS:
        questions.append(_timeline_question(covered_to, None))
    return tuple(questions)


def _timeline_question(covered_to: date, start: date | None) -> GapQuestion:
    """One gap, as a question that creates a TIMELINE fact.

    ``start`` is the next entry's start, or None for the span running to today.
    The None case writes no end_date at all -- see timeline_gaps on why.
    """
    until = f"{start:%b %Y}" if start else "now"
    return GapQuestion(
        kind=Kind.TIMELINE_GAP,
        fact_id=None,
        category=VerifiedFact.Category.TIMELINE,
        # The span is in the slug because there can be several gaps on one
        # form and field_name keys on it: two gaps sharing a slug would share
        # one input box. "present" rather than a date for the trailing one,
        # which would otherwise get a new slug -- and a second input -- every
        # day that passes.
        slug=f"timeline-gap:{covered_to:%Y-%m-%d}:{start:%Y-%m-%d}" if start
        else f"timeline-gap:{covered_to:%Y-%m-%d}:present",
        payload_key="statement",
        group_keys=("statement",),
        # The dates are the detector's, not the student's: they are the gap it
        # found, and asking for them would be asking someone to retype what is
        # already on the screen. Sorted by key, matching _group_questions.
        defaults=(
            (("end_date", f"{start:%Y-%m-%d}"), ("start_date", f"{covered_to:%Y-%m-%d}"))
            if start
            else (("start_date", f"{covered_to:%Y-%m-%d}"),)
        ),
        prompt=(
            f"What were you doing between {covered_to:%b %Y} and {until}? One line -- or "
            "pick one of the suggestions. Several destinations require the CV to account "
            "for every month: TUM refuses a gap longer than three months, ETH asks for "
            "periods with no study or work listed explicitly."
        ),
        evidence=(
            f"Nothing on file covers {covered_to:%d %b %Y} to "
            + (f"{start:%d %b %Y}." if start else "today.")
        ),
    )
```

- [ ] **Step 5b: Refuse an over-long statement where the answer arrives**

In `answer_questions`, in the `fact_id is None` branch, immediately after the
`category is None` check:

```python
            # The ledger stores whatever string it is handed, and generation
            # validates TimelineEntry.statement against TIMELINE_STATEMENT_MAX:
            # an over-long answer accepted here is a fact that makes every
            # later CV for this student fail. Refused at the door instead,
            # which the form already shows as an error.
            if (
                question.category == VerifiedFact.Category.TIMELINE
                and len(value) > TIMELINE_STATEMENT_MAX
            ):
                raise UnanswerableQuestion(
                    f"keep it to {TIMELINE_STATEMENT_MAX} characters"
                )
```

Import `TIMELINE_STATEMENT_MAX` from `.schemas`. Add the same `maxlength` to the timeline input in
Step 7, so the browser stops the typing before the server has to refuse it.

- [ ] **Step 6: Move it from `gap_notes` to `gap_questions`**

```python
def gap_notes(student: Membership) -> tuple[GapNote, ...]:
    """Everything worth showing that nobody is asked to answer.

    One detector left. Timeline gaps were the other, until the TIMELINE
    category gave their answer somewhere to live.
    """
    if unsuperseded_facts(student).exists():
        return (_CERTIFICATES_NOTE,)
    return ()
```

And in `gap_questions`, insert `timeline_gaps(student)` after `missing_language_detail(student)`
— the spec calls it "the largest single omission of the first draft" and it is binding at TUM,
ETH, DAAD PRIME, uni-assist and Harvard GSD, which puts it above a degree's thesis detail and
below a language certificate.

- [ ] **Step 7: Offer the statements on the form**

In `apps/documents/templates/documents/gap_interview.html`, attach a shared `<datalist>` to the
timeline inputs. Change only these two places. `claude/student-dashboard` rewrites this file to
extend `base.html`; keeping the change to one attribute and one block makes it a two-hunk
re-apply for whichever branch merges second. `maxlength="300"` must equal
`TIMELINE_STATEMENT_MAX`; Step 10's view test pins that. Inside the `{% for name, question in fields %}` loop, the input becomes:

```html
            <input type="text" id="q{{ forloop.counter }}" name="{{ name }}"{% if question.kind == "TIMELINE_GAP" %} list="gap-statements" maxlength="300"{% endif %}>
```

And immediately before `</form>`:

```html
        {% comment %}
           A gap question is the one question in this interview a student may
           not want to answer, and it is also the one that cannot be dismissed:
           it stops firing only when a fact covers the span. So the way to make
           it go away is to answer it, and these are the answers -- S-045's
           Cambridge guidance is "a simple statement, with a positive slant
           where appropriate", warning in the same breath against "too much
           honesty: don't dwell on perceived negatives". Military service is
           here because R-042 requires it to be accounted for.

           A datalist and not a select: the student may always type their own,
           and a browser that does not support it renders an ordinary text box,
           which is what this was before.

           Whatever is picked here is what prints on the CV, verbatim -- see
           verification.py's TIMELINE spec, which compares the statement.
        {% endcomment %}
        <datalist id="gap-statements">
          <option value="Personal reasons."></option>
          <option value="Career break."></option>
          <option value="Full-time job-hunting."></option>
          <option value="Family responsibilities."></option>
          <option value="Illness, now recovered."></option>
          <option value="Parental leave."></option>
          <option value="Travel."></option>
          <option value="Military service."></option>
        </datalist>
```

- [ ] **Step 8: Update the module docstring**

In `apps/documents/gaps.py`'s opening docstring:

- "Fourteen deterministic detectors ... eleven unconditional and one programme-gated one in
  gap_questions, plus two in gap_notes" → "Fourteen deterministic detectors over the fact
  ledger, run before generation rather than after it: twelve unconditional and one
  programme-gated one in gap_questions, plus one in gap_notes."
- "two of them exist because the ledger has no shape for the answer: a timeline gap (no
  TimelineEntry) and a certificate (no CERTIFICATE category)" → "one of them exists because
  the ledger has no shape for the answer: a certificate (no CERTIFICATE category). A timeline
  gap was the other until the TIMELINE category landed, which is the shape of that fix --
  the note is the placeholder, and the category is what retires it."
- In the create-path paragraph, add timeline to the list of groups and note the exception:
  "A timeline gap is a create group too, and the only one that does not use `_already_created`:
  its answer covers the span it was asked about, so the detector's own arithmetic stops it
  re-firing. That also makes it the only question here with no way to be dismissed, which is
  why the form offers a list of statements -- answering is the only exit, so there has to be
  an answer for a student who will not explain."

- [ ] **Step 9: Run the whole documents suite**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents -q
```

Expected: PASS. If `tests/documents/test_gap_interview_view.py` asserts a note count or a
question count, update it to the new split rather than weakening the assertion.

- [ ] **Step 10: Add the form tests**

Append to `tests/documents/test_gap_intake.py`:

```python
def test_a_timeline_answer_round_trips_through_the_form(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )
    question = next(
        q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"
    )

    written = submit_answers(
        {field_name(question): "Full-time carer for a family member."}, student=student
    )

    assert len(written) == 1
    assert written[0].category == VerifiedFact.Category.TIMELINE
    assert not [
        q for q in timeline_gaps(student) if q.slug == "timeline-gap:2023-06-30:2023-11-01"
    ]
```

And to `tests/documents/test_gap_interview_view.py`, with that file's own fixtures and `URL`:

```python
def test_a_gap_question_offers_the_statements(client, domain_a, user_a, membership_a) -> None:
    with tenant_scope(domain_a.agency_id):
        make_fact(
            membership_a,
            VerifiedFact.Category.EDUCATION,
            {
                "degree_as_awarded": "BSc",
                "institution_original": "ADA University",
                "start_date": "2019-09-01",
                "end_date": "2023-06-30",
            },
        )
    client.force_login(user_a)

    html = client.get(URL, HTTP_HOST=domain_a.host).content.decode()

    assert 'list="gap-statements"' in html
    assert f'maxlength="{TIMELINE_STATEMENT_MAX}"' in html
    assert "Personal reasons." in html
```

Import `TIMELINE_STATEMENT_MAX` from `apps.documents.schemas`. If the existing tests in that file
call `verify_mfa_session` before a `get`, do the same here.

- [ ] **Step 11: Run them**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_gap_intake.py tests/documents/test_gap_interview_view.py -q
```

Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add apps/documents/gaps.py apps/documents/templates/documents/gap_interview.html tests/documents/test_gaps.py tests/documents/test_gap_intake.py tests/documents/test_gap_interview_view.py
git commit -m "documents: a timeline gap is a question now -- to today as well as between entries, and answerable by someone who will not explain"
```

---

### Task 7: A gap statement never reaches a letter model

`apps/documents/letters.py::_facts_payload` serialises every fact it is handed into the letter
prompt, and its callers hand it `generatable_facts(student)` whole
(`management/commands/draft_letter.py:84`). Once TIMELINE facts exist, "Illness, now
recovered." is in that list, and a motivation-letter model told to tell the student's story
will use it. The CV prints the line because ETH and TUM require the months accounted for; no
source asks a letter to explain them, and a model narrating a student's illness or caring is
the opposite of the one-line, not-dwelt-on statement S-045 describes.

The guard goes in `_facts_payload` and nowhere else, because every letter path builds its
prompt through it. **This is a default, not an owner decision**: if the owner wants a letter
able to mention a gap, that becomes an opt-in the student makes per letter, in a separate
change.

**Files:**
- Modify: `apps/documents/letters.py` (`_facts_payload`, around line 189)
- Test: `tests/documents/test_letters.py`

**Interfaces:**
- Consumes: `VerifiedFact.Category.TIMELINE` (Task 1).
- Produces: `_facts_payload` omits TIMELINE facts; its signature is unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/documents/test_letters.py` (add `_facts_payload` to its `from
apps.documents.letters import (...)`, and `VerifiedFact` if absent). Unsaved rows are enough:
`_facts_payload` reads only `id`, `category`, `payload` and `confirmed_by_id`, and `id` defaults
to a fresh `uuid4`.

```python
def test_a_gap_statement_never_reaches_the_letter_prompt():
    """A gap is accounted for on the CV, where ETH and TUM require it, and
    nowhere else. Its statement is health or family data more often than not
    (S-045's own samples are caring and illness), and a letter model asked for
    the student's story would tell it."""
    carer = VerifiedFact(
        category=VerifiedFact.Category.TIMELINE,
        payload={
            "start_date": "2023-06-30",
            "end_date": "2023-11-01",
            "statement": "Full-time carer for a family member.",
        },
    )
    degree = VerifiedFact(
        category=VerifiedFact.Category.EDUCATION,
        payload={"degree_as_awarded": "BSc", "institution_original": "ADA University"},
    )

    payload = _facts_payload({carer.id: carer, degree.id: degree})

    assert "carer" not in payload
    assert "TIMELINE" not in payload
    assert "ADA University" in payload
```

- [ ] **Step 2: Run it and watch it fail**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents/test_letters.py -q -k gap_statement
```

Expected: FAIL on `"carer" not in payload`.

- [ ] **Step 3: Filter in `_facts_payload`**

```python
def _facts_payload(facts: dict[UUID, VerifiedFact]) -> str:
    # TIMELINE is left out on purpose: a gap statement is printed on the CV
    # because ETH and TUM require every month accounted for, and is no
    # material for a letter -- S-045's samples are caring, illness and
    # unemployment. Filtered here because every letter path builds its prompt
    # through this function.
    return json.dumps(
        [
            {
                "id": str(fact_id),
                "category": fact.category,
                "payload": fact.payload,
                "confirmed": fact.confirmed_by_id is not None,
            }
            for fact_id, fact in facts.items()
            if fact.category != VerifiedFact.Category.TIMELINE
        ],
        sort_keys=True,
        default=str,
    )
```

- [ ] **Step 4: Run the letter suites**

```bash
POSTGRES_DB=tehsil_cvtimeline uv run pytest tests/documents -q -k letter
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/letters.py tests/documents/test_letters.py
git commit -m "documents: a gap statement is printed on the CV and nowhere else -- never in a letter prompt"
```

---

### Task 8: Full validation, docs, and the security gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-cv-counsellor-review-design.md` §1b
- Modify: `docs/superpowers/plans/2026-09-17-cv-counsellor-review-phase-1.md` (the follow-up list)

- [ ] **Step 1: Run every gate**

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=tehsil_cvtimeline uv run pytest -q
POSTGRES_DB=tehsil_cvtimeline uv run python manage.py check
POSTGRES_DB=tehsil_cvtimeline uv run python manage.py makemigrations --check --dry-run
uv run bandit -c pyproject.toml -r apps config
git diff --stat origin/master...HEAD
git status --short
```

Expected: ruff, mypy and bandit clean; **more than 6368 passed**, 72 skipped, 2 xfailed; no
missing migration; and `git status` clean.

If pytest reports the database is in use, another session holds it; pick a different
`POSTGRES_DB` name rather than terminating their backends.

- [ ] **Step 2: Run the security review**

Invoke the `security-review` skill over the branch diff. The one question it must answer, and
the answer this plan takes:

> May a timeline entry reach europa.eu, or a letter model? **No, and no.** A gap statement is the most sensitive line on
> the document — Cambridge's own printed samples are caring, illness and unemployment, which
> is health and family data — and `apps/documents/europass.py` is the one path carrying
> student PII off-platform. Europass has no field for it, so mapping one would mean choosing a
> field it does not belong in. Task 3 pins the absence with a test rather than leaving it to
> the fact that nobody wrote the mapping. Task 7 does the same for the letter prompt, the
> other place a model reads the whole ledger.

A finding is a real bug to fix or a documented `# nosec` false positive, never something to
silence.

- [ ] **Step 3: Update the spec and the phase-1 follow-up list**

In the spec's §1b, replace the sentence "Until it exists this detector fires as a NOTE, not a
QUESTION" with a line recording that `TimelineEntry` shipped, dated, naming the category and
where it renders — **in date order among the experience entries, on ETH's "also list periods
when you did not attend school, study or work" (S-047) and S-041's gap-filler-among-the-roles
shape, not in a section at the foot** — and stating the two limits: **the funder templates
print no gap row, and no timeline entry is mapped to Europass.**

Amend §1b's "every uncovered span **between** the entries" too: the span from the last entry to
today is asked as well, on ETH's "right up to the time of application", and its answer carries
no end date so it closes permanently. And record that a gap question cannot be dismissed — the
form offers a list of statements because answering is its only exit.

In `docs/superpowers/plans/2026-09-17-cv-counsellor-review-phase-1.md`'s follow-up list, strike
item 2 and note where it landed. Items 1 (detector 3), 3 (a `CERTIFICATE` category) and 4 (the
`apps/funding` pack prerequisite) stand unchanged. Note that it landed from the 2026-10-05
refresh of the plan, not the 2026-09-17 draft.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-16-cv-counsellor-review-design.md docs/superpowers/plans/
git commit -m "docs: the timeline note is a question, and the gap statement is the one thing that never goes to europa.eu"
```

---

## Self-review against the spec

**Covered:** §1b in full — the gap-entry shape (`TimelineEntry`: start, end, one-line
statement, Task 2), the note→question conversion (Task 6), the 92-day/TUM threshold (unchanged),
and C-002 finally reaching a render with something to act on (Task 3).

**Also covered, and not in the spec — the trailing span.** §1b says "every uncovered span
between the entries", which leaves the span from the last entry to today unasked. ETH's own
wording is "all details **right up to the time of application**", and that span is the one most
likely to exist on a real applicant's CV. Task 6 asks it, storing the answer with no end date
so it closes permanently rather than reopening as the calendar moves.

**Also covered, and not in the spec — refusing.** A timeline gap is the only question in the
interview that cannot be dismissed: it stops firing when a fact covers the span, and nothing
else. Task 6 makes answering the exit for a student who will not explain, by offering a
`<datalist>` of neutral statements on the timeline inputs. Whatever is picked prints on the CV
verbatim, which is the honest version of a "prefer not to say".

**Also covered, and not in the spec — placement.** §1b says a `TimelineEntry` is needed and
does not say where it prints. The catalog does: ETH (S-047, binding where the admissions page
states it) asks the applicant to "leave no time gaps: **also list** periods when you did not
attend school, study or work"; TUM requires a "chronological and tabular" CV that "must not
contain any gaps longer than 3 months"; S-041's UCC puts the gap-filler among the roles. A
block at the foot of the CV satisfies none of those on their own wording, so Task 3 renders
the gap in date order inside the Experience section instead. This is a change from the first
draft of this plan, made on the catalog rather than on taste.

**Not covered, each deliberate:**

- **One merged whole-CV chronology.** S-001 (education and research before employment for a
  master's applicant) and R-027's track ordering both require the section structure, so
  merging every dated section into one list breaks two rules to satisfy one. The gap joins the
  Experience chronology, not a document-wide one.
- **A gap between two degrees still prints under Experience**, not under Education. ETH's own
  wording groups a gap with "did not attend school, study or work" — a period, not a
  qualification — and it is listed, dated and in order, which is what "also list" asks.
- **The funder templates** (`cv_funder_rhodes.html`, `cv_funder_sisgp.html`) print no gap row.
  They do not extend `cv_base.html`, they iterate `content.experience` themselves, and their
  sections are the funder's, not ours.
- **Europass** carries no timeline entry, by decision, pinned by a test (Task 3).
- **Letters** never see a timeline fact, by default, pinned by a test (Task 7). Opening that
  is an owner decision.
- **Detector 3, the `CERTIFICATE` category, and the `apps/funding` country gate** remain where
  phase 1 left them.

**Risks this plan carries:**

- **`_experience_rows` reads the ordering direction back off `experience`** by comparing it to
  `_newest_first(content.experience)`. That is correct for the two directions the funnel can
  produce and would be wrong if a future directive introduced a third — a section sorted by
  something other than date. Nothing does today; `_DATED_SECTIONS` and
  `derive._ORDER_VALUE` between them allow exactly `chronological` and `reverse_chronological`.
- **This is the branch's first migration.** Every branch carrying a migration collides with the
  squash CLAUDE.md's "Migrations: squash once" section describes, and that window is still open.
  Accepted: the category cannot exist without one. Another branch landing a `documents/0025`
  first is caught by `makemigrations --check`; renumber then, never merge two 0025s.
- **`gap_interview.html` is also rewritten on `claude/student-dashboard`.** Task 6 keeps its edit
  to one attribute and one `<datalist>` block so the second merge re-applies two hunks by hand.
- **A `TIMELINE` fact in a pre-existing ledger is impossible**, so no backfill is needed and no
  existing CV changes. A CV generated before this lands still validates: `timeline` defaults
  to `()`.
- **The overlap-by-a-day storage** means a student's own uploaded CV, ingested later, could
  produce a `TIMELINE` fact whose span is a day off a hand-answered one. Both close the gap;
  the duplicate is a verification concern, not a detector one, and `identity=("start_date",
  "end_date")` will read the second as a separate entry. Left alone: two facts that both
  account for the same months is visible to the student on the confirm screen, not a silent
  failure.
