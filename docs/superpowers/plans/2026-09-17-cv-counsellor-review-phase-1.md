# Counsellor Review, Phase 1 (no model) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `apps/documents/gaps.py` from four null-checks into the spec's deterministic
detectors 1, 1b and 2 — every question the catalog can ask without a model call.

**Architecture:** `gaps.py` stays a pure function over the fact ledger. Two shapes are added
to it: a `slug` on `GapQuestion` so several questions can build one new fact, and a separate
`GapNote` type for output the student cannot act on. No model, no new model class, no
migration except the one schema field the spec names.

**Tech Stack:** Django 5, pydantic v2, pytest + pytest-django, uv.

**Spec:** `docs/superpowers/specs/2026-09-16-cv-counsellor-review-design.md` — read it,
including the `## Read against the code, 2026-09-17` section, which corrects six of its own
claims and is where every non-obvious decision below comes from.

**Out of scope, deliberately:**
- **Detector 3 (the model checks).** Its own plan, after this one lands. It is the only part
  that owes a rate limiter and a cache, and it is worth nothing until detectors 1 and 2 have
  populated the ledger.
- **The pack-gated moment** (country, ECTS, German level, `relevant_coursework`). Blocked:
  `funding.RecommendationCandidate` carries `program_name` as free text with no
  `country_code` and no FK to `Program`, so no pack can be read for a country or a
  discipline. It is another session's app. Spec states the dependency; this plan honours it.
- **The thesis-grade question** (spec detector 1, "Was the thesis graded separately"). No
  field can hold the answer — `EducationEntry` has `grade_native`, `grade_scale`,
  `grade_conversion` and `class_rank`, none of which is a thesis mark — and no render
  decision has been taken about printing one. A question whose answer nothing stores is
  worse than no question. Recorded, not built.
- **The talk-vs-poster question** (spec detector 1, "Was this a talk or a poster?"). Same
  reason: `PublicationEntry.is_presentation` is already `True` by the time it would fire, and
  there is no field distinguishing the two.
- **A `CERTIFICATE` fact category.** Spec correction 4: certificates fire as a NOTE here. The
  category is a change of its own (model choice, `_CategorySpec`, `CVContent` entry,
  `_PAYLOAD_KEYS`, ingestion prompt, a render section, a Europass mapping).

## Global Constraints

- **Test database, every run:** `POSTGRES_DB=tehsil_gapreview uv run pytest ...`. A shared
  `test_tehsil` is killed by the other session working in this repo; that cost two live
  attempts on 2026-09-15.
- **Never run `ruff format` in this repo.** ruff 0.16.6 rewrites this repo's except-tuples
  into invalid Python, and no gate runs the formatter. `uv run ruff check apps tests` only.
- **Validation commands** (repo-canonical): `uv run ruff check apps tests`,
  `uv run mypy apps/documents`, `POSTGRES_DB=tehsil_gapreview uv run pytest -q`.
- **Every fact written by this module is a candidate:** `source_tier=STUDENT_STATEMENT`,
  `source_ref="gap-interview"`, `confirmed_by=None`. `answer_questions` already does this;
  no new writer is added.
- **A payload key is only askable if `payload_keys(category)` carries it.** `answer_questions`
  refuses anything else and a question nobody can answer is worse than none. The key lists,
  read from `apps/documents/verification.py`:
  - `EDUCATION`: `institution_original`, `degree_as_awarded`, `city`, `country`,
    `start_date`, `end_date`, `degree_english`, `institution_english`, `grade_native`,
    `grade_scale`, `grade_conversion`, `ects_credits`, `thesis_title`, `class_rank`,
    `supervisor`, `funding`, `relevant_coursework`
  - `EXPERIENCE`: `employer`, `title`, `city`, `country`, `start_date`, `end_date`,
    `bullets`, `supervisor`, `project`, `group`
  - `PUBLICATION`: `title`, `year`, `doi`, `authors`, `self_author_index`, `venue`, `status`,
    `volume`, `issue`, `pages`, `is_presentation`, `url`
  - `AWARD`: `title`, `date`, `awarding_body`, `detail`
  - `LANGUAGE`: `language`, `cefr_level`, `test_name`, `test_score`, `listening`, `reading`,
    `spoken_interaction`, `spoken_production`, `writing`, `mother_tongue`
  - `REFERENCE`: `name`, `email`, `position`, `institution`, `phone`, `do_not_contact`
- **No `required` attribute on any input.** Every question is skippable; a blank is an
  ordinary skip, not an error. The template's own comment says so.
- **Question order is value order** (spec correction 5). `gap_questions` appends detectors in
  the order below and nothing sorts afterwards. No cap: a dropped question is a fact the
  ledger never gets and nothing ever asks for again.

---

### Task 1: Question identity — `slug`, grouped creations, all-or-nothing writes

Today `gap_intake.field_name` is `f"{question.fact_id}:{question.payload_key}"` and exactly
one question has no fact, so `"None:title"` is unique. Detectors 1 and 2 add several
create-path questions, and two that both write `title` would post under one name and receive
one student sentence. Worse: `EducationEntry` needs `institution_original` *and*
`degree_as_awarded`, and `ExperienceEntry` needs `employer`, `title` and a bullet — so a new
entry cannot be built from a single answer at all, and `answer_questions` writes one key per
creation today.

Both are fixed by the same thing: a `slug` naming the question's target, and creations grouped
by it.

**Files:**
- Modify: `apps/documents/gaps.py` (`GapQuestion`, `answer_questions`, `missing_award`)
- Modify: `apps/documents/gap_intake.py` (`field_name`)
- Test: `tests/documents/test_gaps.py`, `tests/documents/test_gap_intake.py`

**Interfaces:**
- Produces:
  - `GapQuestion(kind, fact_id, payload_key, prompt, evidence, category=None, slug=None)`
    — frozen dataclass, unchanged field order, `slug: str | None` appended last.
    `__post_init__` raises `ValueError` when `fact_id is None and slug is None`.
  - `gap_intake.field_name(question) -> str` == `f"{question.fact_id or question.slug}:{question.payload_key}"`
  - `answer_questions(answers, *, student)` unchanged signature; creations now grouped by
    `slug` and written only when every question sharing that slug was answered.

- [ ] **Step 1: Write the failing tests**

In `tests/documents/test_gaps.py`:

```python
def test_a_create_question_without_a_slug_is_a_programming_error():
    with pytest.raises(ValueError):
        GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=None,
            payload_key="title",
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.AWARD,
        )


def test_two_create_questions_sharing_a_slug_write_one_fact(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    group = [
        GapQuestion(
            kind=Kind.EDUCATION_COMPLETENESS,
            fact_id=None,
            payload_key=key,
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.EDUCATION,
            slug="exchange-programme",
        )
        for key in ("institution_original", "degree_as_awarded")
    ]

    written = answer_questions(
        [(group[0], "TU Delft"), (group[1], "Erasmus exchange semester")], student=student
    )

    assert len(written) == 1
    assert written[0].payload == {
        "institution_original": "TU Delft",
        "degree_as_awarded": "Erasmus exchange semester",
    }


def test_a_half_answered_create_group_writes_nothing(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    group = [
        GapQuestion(
            kind=Kind.EDUCATION_COMPLETENESS,
            fact_id=None,
            payload_key=key,
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.EDUCATION,
            slug="exchange-programme",
        )
        for key in ("institution_original", "degree_as_awarded")
    ]

    assert answer_questions([(group[0], "TU Delft"), (group[1], "")], student=student) == ()
    assert not unsuperseded_facts(student).filter(
        category=VerifiedFact.Category.EDUCATION
    ).exists()
```

In `tests/documents/test_gap_intake.py`:

```python
def test_two_create_questions_with_the_same_key_get_different_field_names():
    def question(slug):
        return GapQuestion(
            kind=Kind.ABSENT_SECTION,
            fact_id=None,
            payload_key="title",
            prompt="?",
            evidence="?",
            category=VerifiedFact.Category.AWARD,
            slug=slug,
        )

    assert field_name(question("merit-award")) != field_name(question("voluntary-role"))
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/orkhan/Desktop/tehsil_agent
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_intake.py -q
```
Expected: FAIL — `GapQuestion` has no `slug`, so every new test errors on an unexpected
keyword argument, and `test_a_create_question_without_a_slug_is_a_programming_error` does
not raise.

- [ ] **Step 3: Add `slug` to `GapQuestion`**

In `apps/documents/gaps.py`, add the field and the guard at the end of the dataclass:

```python
    #: Names what a create-path question BUILDS, so several questions can fill
    #: one new fact and two questions writing the same key stay distinct. It is
    #: also half the form field name (gap_intake.field_name), so it must be
    #: stable between a render and the submit that follows it -- the detector's
    #: own name for the question, never anything derived from a row's position.
    #:
    #: Required whenever fact_id is None: without it every create-path question
    #: posts under "None:<key>", and two of them share one input.
    slug: str | None = None

    def __post_init__(self) -> None:
        if self.fact_id is None and self.slug is None:
            raise ValueError("a question with no fact must carry a slug")
```

Give `missing_award`'s question `slug="merit-award"`.

- [ ] **Step 4: Group creations by slug in `answer_questions`**

Replace the `creations: list[tuple[str, dict[str, str]]]` accumulator and its write loop:

```python
    # slug -> (category, answered fields, keys the group asked about). A new
    # entry takes several answers -- an EducationEntry needs an institution AND
    # a degree, an ExperienceEntry an employer, a title and a bullet -- so the
    # group is the unit of creation, not the question.
    creations: dict[str, tuple[str, dict[str, str], set[str]]] = {}
```

In the answer loop, replace the `question.fact_id is None` branch with:

```python
        if question.fact_id is None:
            if question.category is None:
                raise UnanswerableQuestion("a question with no fact must name a category")
            slug = question.slug
            assert slug is not None  # GapQuestion.__post_init__ guarantees it
            category, fields, asked = creations.setdefault(slug, (question.category, {}, set()))
            if category != question.category:
                raise UnanswerableQuestion(f"{slug} names two categories")
            asked.add(question.payload_key)
            fields[question.payload_key] = value
            continue
```

Note the loop already `continue`s past a blank answer before this, so `asked` collects only
answered keys. The unanswered ones are recovered by re-deriving the group — see the write
loop.

Replace the creation write loop with:

```python
    for slug, (category, fields, asked) in creations.items():
        # All or nothing. A half-answered group writes a fact no reader can use
        # -- an EDUCATION row holding an institution and no degree gives
        # generation nothing to build an entry from, and the model's only legal
        # move is to invent the other half. A dropped partial answer costs one
        # re-ask, which the interview does on its own because the detector
        # still fires.
        if asked != _group_keys(slug):
            continue
        unknown = sorted(set(fields) - set(payload_keys(category)))
        if unknown:
            raise UnanswerableQuestion(f"{category} facts do not carry {', '.join(unknown)}")
        written.append(
            VerifiedFact.objects.create(
                student=student,
                category=category,
                payload=fields,
                source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
                source_ref="gap-interview",
                confirmed_by=None,
                supersedes=None,
                created_by=student,
            )
        )
```

`_group_keys` cannot re-run a detector — `answer_questions` has no ledger to run it against
that is not already mid-transaction — so the keys travel with the answers instead. Add above
`answer_questions`:

```python
#: A create-path question group's full key set, by slug. Declared here rather
#: than derived from the answers, because "every key was answered" is not a
#: property of the submission -- a form that omits one input entirely would
#: otherwise look complete.
_CREATE_GROUPS: dict[str, tuple[str, ...]] = {
    "merit-award": ("title",),
}


def _group_keys(slug: str) -> set[str]:
    return set(_CREATE_GROUPS[slug])
```

Every later task that adds a create group adds its slug here, and the test in Task 10 asserts
no detector emits a slug this table does not know.

- [ ] **Step 5: Point `field_name` at the slug**

In `apps/documents/gap_intake.py`:

```python
def field_name(question: GapQuestion) -> str:
    """The form field name a question's answer comes back under.

    The contract between whatever renders the form and this module: both sides
    call this, neither invents the string.

    Keyed by the fact (or, for a question that builds a new one, its slug) and
    the payload key rather than by position, because the ledger can move
    between the render and the submit -- a second tab, a counsellor edit, a
    double submit. Positional names silently land an answer on whatever shifted
    into that slot; a stale name here matches no re-derived question and is
    dropped.

    The slug half is what keeps two create-path questions writing the same key
    apart: before it existed both posted under "None:title" and one answer
    landed in both facts.
    """
    return f"{question.fact_id or question.slug}:{question.payload_key}"
```

- [ ] **Step 6: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_intake.py tests/documents/test_gap_interview_view.py -q
```
Expected: PASS, including every pre-existing test in those three modules.

- [ ] **Step 7: Commit**

```bash
git add apps/documents/gaps.py apps/documents/gap_intake.py tests/documents/test_gaps.py tests/documents/test_gap_intake.py
git commit -m "documents: a create-path question names what it builds, so several can fill one fact"
```

---

### Task 2: Notes, and the timeline-gap detector

A note is output the student cannot act on: the counsellor sees it, nobody is asked something
the ledger cannot hold. It is its own type rather than a `GapQuestion` with a null
`payload_key`, because that nullability would have to be guarded in `answer_questions`,
`submit_answers` and `field_name` — the whole write path — for a thing that never writes.

Its first producer is the timeline detector. Every uncovered span longer than three months
between the student's education and experience entries is a note: ETH ("leave no time gaps"),
TUM ("must not contain any gaps longer than 3 months" — the threshold, the strictest stated),
DAAD PRIME R-011, uni-assist R-020, Harvard GSD. It is a note and not a question because
S-045 measured that every gap Cambridge prints carries no employer ("Full-time carer for
family member"), so it is not an `ExperienceEntry` — that model requires an employer and a
bullet — and no `TimelineEntry` exists yet.

**Files:**
- Modify: `apps/documents/gaps.py` (`GapNote`, `timeline_gaps`, `gap_notes`)
- Modify: `apps/documents/views.py` (`_page`)
- Modify: `apps/documents/templates/documents/gap_interview.html`
- Test: `tests/documents/test_gaps.py`, `tests/documents/test_gap_interview_view.py`

**Interfaces:**
- Consumes: `apps/documents/dates.py::parse_cv_date`, already used by `gaps._degree_complete`.
- Produces:
  - `GapNote(text: str, evidence: str)` — frozen dataclass, no fact, no key, no answer.
  - `timeline_gaps(student: Membership) -> tuple[GapNote, ...]`
  - `gap_notes(student: Membership) -> tuple[GapNote, ...]` — every note detector, in order.
    Later tasks append to it.

- [ ] **Step 1: Write the failing tests**

In `tests/documents/test_gaps.py`:

```python
def test_a_four_month_gap_between_two_entries_is_a_note(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
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
            "title": "Research Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )

    notes = timeline_gaps(student)

    assert len(notes) == 1
    assert "2023" in notes[0].text


def test_a_two_month_gap_is_not_a_note(student):
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
            "title": "Research Intern",
            "start_date": "2023-08-15",
            "end_date": "2024-02-29",
        },
    )

    assert timeline_gaps(student) == ()


def test_overlapping_entries_leave_no_gap(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc",
            "institution_original": "Strasbourg",
            "start_date": "2023-09-01",
            "end_date": "2025-06-30",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "EPFL",
            "title": "Intern",
            "start_date": "2024-02-01",
            "end_date": "2024-08-31",
        },
    )

    assert timeline_gaps(student) == ()


def test_an_entry_still_running_ends_the_timeline_today(student):
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


def test_a_note_is_never_a_question(student):
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

    assert timeline_gaps(student)
    assert not any(
        "between" in question.prompt.lower() for question in gap_questions(student)
    )
```

In `tests/documents/test_gap_interview_view.py`, following that module's existing pattern for
logging a student in:

```python
def test_a_note_is_rendered_and_has_no_input(client, student_user):
    make_fact(
        student_user,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )
    make_fact(
        student_user,
        VerifiedFact.Category.EXPERIENCE,
        {
            "employer": "ICIQ",
            "title": "Intern",
            "start_date": "2023-11-01",
            "end_date": "2024-02-29",
        },
    )

    body = client.get("/student/gap-interview/").content.decode()

    assert "What were you doing" in body
    assert body.count("<input type=\"text\"") == len(
        [1 for _ in gap_questions(student_user)]
    )
```

Read `tests/documents/test_gap_interview_view.py` first and reuse its own fixture names and
URL constant rather than the placeholders above if they differ.

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k "gap or note" -q
```
Expected: FAIL — `cannot import name 'timeline_gaps' from 'apps.documents.gaps'`.

- [ ] **Step 3: Implement `GapNote`, `timeline_gaps` and `gap_notes`**

In `apps/documents/gaps.py`, after `GapQuestion`:

```python
@dataclass(frozen=True)
class GapNote:
    """Something worth reading that nobody is asked to answer.

    Its own type, not a GapQuestion with a null payload_key: a note has no
    fact to supersede, no key to land in and no answer, so putting it in the
    question tuple would push a nullable key through answer_questions,
    submit_answers and field_name -- the entire write path, which is the only
    part of this module with a trust boundary in it -- for a thing that never
    writes.

    Notes are the preferred output wherever the student cannot act: one costs a
    second to read and skip, a question costs a decision, and a long form is
    where a student abandons.
    """

    #: What the counsellor and student read. A statement, not a request.
    text: str
    #: What in the student's own material produced it, same contract as
    #: GapQuestion.evidence.
    evidence: str
```

Then the detector. `_MIN_GAP_DAYS = 92` — three months, TUM's figure.

```python
#: TUM: a CV "must not contain any gaps longer than 3 months". The strictest
#: threshold any source states, so it is the one used: a gap that clears TUM
#: clears ETH, DAAD PRIME (R-011), uni-assist (R-020) and Harvard GSD too.
#: 92 days rather than a month count, because the ledger holds dates.
_MIN_GAP_DAYS = 92


def timeline_gaps(student: Membership) -> tuple[GapNote, ...]:
    """Uncovered spans between the education and experience entries.

    A NOTE and not a question, and the reason is the schema rather than taste.
    S-045 measured what Cambridge actually prints for a gap -- "Full-time carer
    for family member", "3 months' full-time job-hunting" -- and neither has an
    employer or a bullet, which ExperienceEntry requires both of. There is
    nowhere to put the answer, so it is not asked. A TimelineEntry (start, end,
    one line) turns every note here into a question and nothing else changes.

    An entry with no end date is still running, so it covers the timeline up to
    today: end_date=None renders as "present" everywhere else in this codebase
    and means the same thing here. An entry with no start date cannot be placed
    and is skipped rather than guessed at.
    """
    spans: list[tuple[date, date]] = []
    for category in (VerifiedFact.Category.EDUCATION, VerifiedFact.Category.EXPERIENCE):
        for fact in _current(student, category):
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            start = _read_date(payload.get("start_date"))
            if start is None:
                continue
            end = _read_date(payload.get("end_date")) or date.today()
            if end >= start:
                spans.append((start, end))
    if len(spans) < 2:
        return ()
    spans.sort()
    notes: list[GapNote] = []
    covered_to = spans[0][1]
    for start, end in spans[1:]:
        if (start - covered_to).days > _MIN_GAP_DAYS:
            notes.append(
                GapNote(
                    text=(
                        "What were you doing between "
                        f"{covered_to:%b %Y} and {start:%b %Y}? Several destinations "
                        "require the CV to account for every month -- TUM refuses a gap "
                        "longer than three months, ETH asks for periods with no study or "
                        "work listed explicitly."
                    ),
                    evidence=(
                        f"Nothing on file covers {covered_to:%d %b %Y} to {start:%d %b %Y}."
                    ),
                )
            )
        covered_to = max(covered_to, end)
    return tuple(notes)


def _read_date(raw: object) -> date | None:
    """A ledger date as a date, or nothing. Never a guess.

    The ledger stores dates as the CV printed them ("June 2024", "2024-06-30"),
    so parse_cv_date does the reading. Unparseable is None and the entry is
    skipped: a span placed on a misread date invents a gap the student has to
    argue with.
    """
    if not raw:
        return None
    try:
        return parse_cv_date(raw)
    except (TypeError, ValueError):
        return None


def gap_notes(student: Membership) -> tuple[GapNote, ...]:
    """Everything worth showing that nobody is asked to answer."""
    return timeline_gaps(student)
```

Move the local imports out of `_degree_complete` to module level — `from datetime import date`
and `from .dates import parse_cv_date` — now that two functions need them, and have
`_degree_complete` keep its own behaviour for an unparseable date (it treats one as complete,
deliberately; `_read_date` returning None there would change it).

- [ ] **Step 4: Render notes in the view**

In `apps/documents/views.py::_page`, add to the context:

```python
            "notes": gap_notes(student),
```

and import `gap_notes` alongside `gap_questions`. In
`apps/documents/templates/documents/gap_interview.html`, above the `{% if fields %}` block:

```html
    {% if notes %}
      <section>
        <h2>Worth knowing</h2>
        <p>Nothing to answer here -- these are for you and your counsellor.</p>
        <ul>
          {% for note in notes %}
            <li>{{ note.text }} <small>{{ note.evidence }}</small></li>
          {% endfor %}
        </ul>
      </section>
    {% endif %}
```

and change the empty case from `{% if fields %}...{% else %}Nothing to ask right now.` to fire
its "nothing to ask" line only when there are neither fields nor notes:

```html
    {% if not fields and not notes %}<p>Nothing to ask right now.</p>{% endif %}
```

- [ ] **Step 5: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_interview_view.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/documents/gaps.py apps/documents/views.py apps/documents/templates/documents/gap_interview.html tests/documents/test_gaps.py tests/documents/test_gap_interview_view.py
git commit -m "documents: the timeline's uncovered months are a note, because no entry shape holds the answer"
```

---

### Task 3: Language questions — the test score first

R-041 and S-014. The highest-value single item in the spec: nearly every international
programme wants a certificate, and the real CV reads "English — Advanced (C1)" with no test
at all. Two questions, in this order: the missing test score, then the missing CEFR level.

A mother tongue is not asked for a test score — `mother_tongue=True` is the one case where
"no certificate" is the right answer — but it *is* asked for a CEFR level, because the ledger
prints a level for it and R-041 wants one in Europe.

**Files:**
- Modify: `apps/documents/gaps.py` (`Kind.MISSING_LANGUAGE`, `missing_language_detail`, `gap_questions`)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `GapQuestion` from Task 1.
- Produces: `missing_language_detail(student: Membership) -> tuple[GapQuestion, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_language_with_no_test_score_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.LANGUAGE,
        {"language": "English", "cefr_level": "C1"},
    )

    questions = missing_language_detail(student)

    assert [q.payload_key for q in questions] == ["test_score"]
    assert "IELTS" in questions[0].prompt


def test_a_mother_tongue_is_not_asked_for_a_test_score(student):
    make_fact(
        student,
        VerifiedFact.Category.LANGUAGE,
        {"language": "Azerbaijani", "cefr_level": "C2", "mother_tongue": True},
    )

    assert missing_language_detail(student) == ()


def test_a_language_with_no_level_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.LANGUAGE,
        {"language": "French", "test_name": "DELF", "test_score": "B2"},
    )

    questions = missing_language_detail(student)

    assert [q.payload_key for q in questions] == ["cefr_level"]
    assert "French" in questions[0].prompt


def test_the_test_score_is_asked_before_the_level(student):
    make_fact(student, VerifiedFact.Category.LANGUAGE, {"language": "German"})

    assert [q.payload_key for q in missing_language_detail(student)] == [
        "test_score",
        "cefr_level",
    ]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k language -q
```
Expected: FAIL — `cannot import name 'missing_language_detail'`.

- [ ] **Step 3: Implement**

Add `MISSING_LANGUAGE = "MISSING_LANGUAGE"` to `Kind`, then:

```python
def missing_language_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """A language entry with no certificate and no level.

    The test score is the highest-value question in this module. R-041 and
    S-014 both want it, nearly every international programme asks for a
    certificate, and the real CV printed "English -- Advanced (C1)" with
    nothing behind it. Asked first for that reason.

    Never asked of a mother tongue: "no IELTS" is the correct state for one,
    and asking reads as not having read the CV. The LEVEL is still asked, for
    a mother tongue too -- the ledger prints one, and R-041 wants a CEFR value
    in Europe.

    The score and the test name are one question with one input, because a
    score without its test ("7.5") means nothing and two inputs for one fact
    the student reads off one certificate is two decisions for one answer. The
    answer lands in test_score verbatim; test_name stays for a source that
    states them apart.
    """
    questions: list[GapQuestion] = []
    scores: list[GapQuestion] = []
    levels: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.LANGUAGE):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        language = str(payload.get("language") or "this language")
        if not payload.get("test_score") and not payload.get("mother_tongue"):
            scores.append(
                GapQuestion(
                    kind=Kind.MISSING_LANGUAGE,
                    fact_id=fact.id,
                    payload_key="test_score",
                    prompt=(
                        f"Do you have a language certificate for {language} -- an "
                        "IELTS, TOEFL, DELF, TestDaF or Cambridge result? Give the "
                        "test and the score together, for example 'IELTS 7.5'."
                    ),
                    evidence=f"{language} is on file with no test result.",
                )
            )
        if not payload.get("cefr_level"):
            levels.append(
                GapQuestion(
                    kind=Kind.MISSING_LANGUAGE,
                    fact_id=fact.id,
                    payload_key="cefr_level",
                    prompt=(
                        f"What is your level in {language} on the CEFR scale -- "
                        "A1 to C2, or 'native'?"
                    ),
                    evidence=f"{language} is on file with no CEFR level.",
                )
            )
    questions.extend(scores)
    questions.extend(levels)
    return tuple(questions)
```

Add `+ missing_language_detail(student)` to `gap_questions`, immediately after
`missing_contact(student)` — it is the highest-value detector and the order is value order.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: ask for the language certificate every destination in the pack will want"
```

---

### Task 4: Degree detail questions — thesis, supervisor, rank

S-037/S-040 (the degree's own thesis, and who supervised it) and S-027/UCC (where the student
ranked, which US credential guidance calls more telling than a converted GPA). Three
questions, each a null-check on a field `EducationEntry` already has.

Only the **most recent** degree is asked for a thesis title: a bachelor's thesis on a CV whose
master's is in progress is rarely what a reader wants, and asking every degree turns one
question into three. Most recent = the largest `start_date`; a degree with no start date is
never the most recent.

`class_rank` is asked only of a **completed** degree that already has a grade: a rank is a
transcript fact, an in-progress student does not have a final one, and a degree with no grade
at all is already being asked for the grade by `missing_grade`.

**Files:**
- Modify: `apps/documents/gaps.py` (`Kind.MISSING_DEGREE_DETAIL`, `missing_degree_detail`, `gap_questions`)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `_degree_complete` and `_read_date` from Task 2.
- Produces: `missing_degree_detail(student: Membership) -> tuple[GapQuestion, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_most_recent_degree_is_asked_for_its_thesis(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
            "grade_native": "88/100",
        },
    )
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    theses = [q for q in missing_degree_detail(student) if q.payload_key == "thesis_title"]

    assert len(theses) == 1
    assert "MSc Chemoinformatics" in theses[0].prompt


def test_a_degree_with_a_thesis_is_asked_who_supervised_it(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
            "thesis_title": "Hierarchical GTM for reaction space",
        },
    )

    questions = missing_degree_detail(student)

    assert [q.payload_key for q in questions if q.payload_key == "supervisor"] == [
        "supervisor"
    ]
    assert not [q for q in questions if q.payload_key == "thesis_title"]


def test_a_completed_graded_degree_is_asked_for_a_rank(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
            "grade_native": "88/100",
        },
    )

    assert "class_rank" in [q.payload_key for q in missing_degree_detail(student)]


def test_an_in_progress_degree_is_not_asked_for_a_rank(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
            "grade_native": "15.8/20.0 to date",
        },
    )

    assert "class_rank" not in [q.payload_key for q in missing_degree_detail(student)]


def test_a_degree_with_no_grade_is_not_asked_for_a_rank(student):
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

    assert "class_rank" not in [q.payload_key for q in missing_degree_detail(student)]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k degree_detail -q
```
Expected: FAIL — `cannot import name 'missing_degree_detail'`.

- [ ] **Step 3: Implement**

Add `MISSING_DEGREE_DETAIL = "MISSING_DEGREE_DETAIL"` to `Kind`, then:

```python
def _most_recent_degree(facts: list[VerifiedFact]) -> VerifiedFact | None:
    """The degree that started last, or nothing.

    A degree with no readable start date is never the most recent: the answer
    would be whichever row the database returned first, which is not a fact
    about the student.
    """
    dated = [
        (start, fact)
        for fact in facts
        if (start := _read_date((fact.payload or {}).get("start_date"))) is not None
    ]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[0])[1]


def missing_degree_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """What an education entry carries beyond the degree and the institution.

    S-040, from UCC's own list: "dates, qualification, supervisor,
    dissertation, papers and awards". Toronto's worked CV prints
    "Dissertation: ..." then "Supervisor: Dr. Carine Mendelsson" under the
    degree. We printed neither, because nothing ever asked.

    The thesis is asked of the MOST RECENT degree only. A bachelor's thesis on
    a CV whose master's is in progress is rarely what an admissions reader
    wants, and asking every degree turns one question into three for one fact
    a reader uses once.

    A rank is asked only of a COMPLETED degree that already has a grade. UCC
    wants the cohort size beside a foreign grade -- "interpret grades ...
    indicate range of scores and size of class" -- and US credential guidance
    calls a rank more telling than a converted GPA. But an in-progress student
    has no final rank, and a degree with no grade at all is already being asked
    for the grade by missing_grade; a second question about the same line is
    where a form starts feeling like an interrogation.
    """
    facts = _current(student, VerifiedFact.Category.EDUCATION)
    recent = _most_recent_degree(facts)
    questions: list[GapQuestion] = []
    for fact in facts:
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        degree = str(payload.get("degree_as_awarded") or "your degree")
        if fact is recent and not payload.get("thesis_title"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="thesis_title",
                    prompt=(
                        f"What is the title of your {degree} thesis or dissertation? "
                        "If it is not finished, give the working title."
                    ),
                    evidence=f"{degree} is on file with no thesis title.",
                )
            )
        if payload.get("thesis_title") and not payload.get("supervisor"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="supervisor",
                    prompt=f"Who supervised your {degree} thesis?",
                    evidence=(
                        f"{degree} states a thesis and names nobody who supervised it."
                    ),
                )
            )
        if payload.get("grade_native") and not payload.get("class_rank") and _degree_complete(
            payload
        ):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_DEGREE_DETAIL,
                    fact_id=fact.id,
                    payload_key="class_rank",
                    prompt=(
                        f"Where did you rank in your cohort for {degree}, if your "
                        "institution states it? For example '3rd of 120' or 'top 5%'. "
                        "Leave this blank if it was never published."
                    ),
                    evidence=(
                        f"{degree} has a grade and no rank; a reader abroad cannot tell "
                        "what that grade is worth without the cohort."
                    ),
                )
            )
    return tuple(questions)
```

Add `+ missing_degree_detail(student)` to `gap_questions` after `missing_grade(student)`.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: the degree carries a thesis, a supervisor and a rank, and nothing asked for any"
```

---

### Task 5: `EducationEntry.medium_of_instruction`, and the question that fills it

The spec's highest-value find (S-050, sourced to Cornell, USC, BU, ASU and R-065): a degree
taught in English can waive the language requirement, the conditions differ by destination —
USC also requires the country's only official language to be English, BU requires the
transcript to say *sole* language of instruction — and no field can hold the fact. The
standard layer gathers it; the programme layer decides, per destination, whether it earns an
exemption. **The question must not imply a waiver**, which is the boundary the spec's Scope
section states.

The field is gathered and deliberately **not printed**: which templates show it, and whether
it belongs on a CV at all rather than on an application form, is a render decision nobody has
taken. Carried in the ledger and in `_PAYLOAD_KEYS` (never compared — it is a sentence
transcribed from a certificate), reaching the programme layer when that is built.

**Files:**
- Modify: `apps/documents/schemas.py` (`EducationEntry`)
- Modify: `apps/documents/verification.py` (`_PAYLOAD_KEYS` education block)
- Modify: `apps/documents/ingestion.py` (the education prompt sentences)
- Modify: `apps/documents/generation.py` (the carry-through prompt lines)
- Modify: `apps/documents/gaps.py` (`Kind.MEDIUM_OF_INSTRUCTION`, `missing_medium_of_instruction`, `gap_questions`)
- Test: `tests/documents/test_schemas.py`, `tests/documents/test_verification.py`, `tests/documents/test_gaps.py`

**Interfaces:**
- Produces:
  - `EducationEntry.medium_of_instruction: str | None` (max_length 200)
  - `missing_medium_of_instruction(student: Membership) -> tuple[GapQuestion, ...]`

- [ ] **Step 1: Write the failing tests**

In `tests/documents/test_schemas.py`:

```python
def test_an_education_entry_holds_its_medium_of_instruction():
    entry = EducationEntry(
        degree_as_awarded="BSc Chemical Engineering",
        institution_original="ADA University",
        medium_of_instruction="English",
    )

    assert entry.medium_of_instruction == "English"
```

In `tests/documents/test_verification.py`:

```python
def test_the_medium_of_instruction_reaches_the_ledger():
    assert "medium_of_instruction" in payload_keys(VerifiedFact.Category.EDUCATION)
```

In `tests/documents/test_gaps.py`:

```python
def test_the_highest_completed_degree_is_asked_its_medium_of_instruction(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc Chemical Engineering",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
        },
    )

    questions = missing_medium_of_instruction(student)

    assert [q.payload_key for q in questions] == ["medium_of_instruction"]
    assert "waive" not in questions[0].prompt.lower()
    assert "exempt" not in questions[0].prompt.lower()


def test_an_in_progress_degree_is_not_asked_its_medium_of_instruction(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
        },
    )

    assert missing_medium_of_instruction(student) == ()


def test_a_degree_that_states_its_medium_is_not_asked_again(student):
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "BSc",
            "institution_original": "ADA University",
            "start_date": "2019-09-01",
            "end_date": "2023-06-30",
            "medium_of_instruction": "English",
        },
    )

    assert missing_medium_of_instruction(student) == ()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_schemas.py tests/documents/test_verification.py tests/documents/test_gaps.py -k medium -q
```
Expected: FAIL — `extra="forbid"` rejects `medium_of_instruction`, `payload_keys` lacks it,
and the detector does not exist.

- [ ] **Step 3: Add the schema field**

In `apps/documents/schemas.py::EducationEntry`, after `relevant_coursework`:

```python
    #: The language the degree was TAUGHT in, as the institution states it --
    #: not the language the document is written in. S-050, sourced to Cornell,
    #: USC, BU and ASU (and R-065): a degree taught in English can stand in for
    #: a language certificate, and the conditions differ at every destination --
    #: USC also requires the country's only official language to be English, BU
    #: requires the transcript to say it was the SOLE language of instruction.
    #:
    #: So this holds the FACT and nothing decides anything from it here. The
    #: waiver is a per-destination rule and belongs to the programme layer;
    #: gathering it is the standard layer's job (design, "Scope: this is the
    #: STANDARD layer"). Nothing prints it today either -- whether a CV should
    #: carry the line at all, or only the application form, is a render
    #: decision nobody has taken.
    medium_of_instruction: str | None = Field(default=None, max_length=200)
```

- [ ] **Step 4: Carry it to the ledger**

In `apps/documents/verification.py`, add `"medium_of_instruction"` to the `spec.field ==
"education"` tuple in `_PAYLOAD_KEYS`, beside `relevant_coursework`, and extend that block's
existing comment:

```python
            # medium_of_instruction joins them: it is a sentence transcribed
            # off a certificate ("English", "instruction in English and
            # Azerbaijani"), so comparing it would block a draft over wording.
            "medium_of_instruction",
```

- [ ] **Step 5: Tell ingestion and generation about it**

Read the education field sentences in `apps/documents/ingestion.py` and the carry-through
lines in `apps/documents/generation.py` and add one sentence each, in the voice already used
there:

- ingestion: `"medium_of_instruction: the language the degree was taught in, only if the document states it. Never inferred from the language the CV is written in or from the country."`
- generation: `"Carry medium_of_instruction through unchanged when a fact states it."`

- [ ] **Step 6: Implement the detector**

Add `MEDIUM_OF_INSTRUCTION = "MEDIUM_OF_INSTRUCTION"` to `Kind`, then:

```python
def missing_medium_of_instruction(student: Membership) -> tuple[GapQuestion, ...]:
    """What language the student's highest COMPLETED degree was taught in.

    S-050's highest-value find and the one that promises nothing. Cornell, USC,
    BU and ASU all accept an English-taught degree in place of a test, and all
    on different terms, so this asks the fact and says nothing about a waiver:
    the prompt must not imply an exemption it cannot grant, because the layer
    that grants one reads a programme's page and this layer never does.

    Completed only. A degree still running has no certifiable medium yet, and a
    fourth-year applicant asked to produce one is being asked for a document
    their registrar will not issue.
    """
    completed = [
        fact
        for fact in _current(student, VerifiedFact.Category.EDUCATION)
        if _degree_complete(fact.payload if isinstance(fact.payload, dict) else {})
    ]
    highest = _most_recent_degree(completed)
    if highest is None:
        return ()
    payload = highest.payload if isinstance(highest.payload, dict) else {}
    if payload.get("medium_of_instruction"):
        return ()
    degree = str(payload.get("degree_as_awarded") or "your degree")
    return (
        GapQuestion(
            kind=Kind.MEDIUM_OF_INSTRUCTION,
            fact_id=highest.id,
            payload_key="medium_of_instruction",
            prompt=(
                f"What language was {degree} taught in, and can your university "
                "issue a letter confirming it? Several universities ask for this in "
                "writing; what they do with it differs, so we record what yours says."
            ),
            evidence=f"{degree} is on file with no language of instruction.",
        ),
    )
```

Add `+ missing_medium_of_instruction(student)` to `gap_questions`, immediately after
`missing_language_detail(student)` — the spec ranks it the highest of the nine S-050 finds.

- [ ] **Step 7: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents -q && uv run mypy apps/documents
```
Expected: PASS, mypy clean. A failure in `test_extraction_accuracy.py` or `test_render.py`
means a template or a corpus fixture reads education keys positionally — fix it there, do not
drop the field.

- [ ] **Step 8: Commit**

```bash
git add apps/documents/schemas.py apps/documents/verification.py apps/documents/ingestion.py apps/documents/generation.py apps/documents/gaps.py tests/documents/
git commit -m "documents: record what language a degree was taught in, and decide nothing from it"
```

---

### Task 6: Publication questions — a resolvable identifier, authorship, a year

S-011. Three questions per publication, in value order: an item with neither a DOI nor a URL
is unverifiable; `self_author_index=None` is what decides whether the applicant's own name is
bolded; a missing year makes a citation incomplete.

`self_author_index` is an `int` on the schema and the answer arrives as a typed string. It is
stored as the student typed it — the ledger is a record of claims, and `PublicationEntry`'s
own validator is what refuses a value that does not point at one of the authors when the draft
is built. The prompt asks for a position, and names the authors on file so the student can
count.

**Files:**
- Modify: `apps/documents/gaps.py` (`Kind.MISSING_PUBLICATION_DETAIL`, `missing_publication_detail`, `gap_questions`)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Produces: `missing_publication_detail(student: Membership) -> tuple[GapQuestion, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_publication_with_no_identifier_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "Hierarchical GTM for reaction space",
            "authors": ["Abdullayev, O.", "Schwaller, P."],
            "self_author_index": 0,
            "year": 2025,
        },
    )

    questions = missing_publication_detail(student)

    assert [q.payload_key for q in questions] == ["doi"]
    assert "landing page" in questions[0].prompt


def test_a_publication_with_a_url_is_not_asked_for_a_doi(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "An IAC proceedings paper",
            "authors": ["Abdullayev, O."],
            "self_author_index": 0,
            "year": 2023,
            "url": "https://dl.iafastro.directory/event/IAC-2023/paper/76798/",
        },
    )

    assert missing_publication_detail(student) == ()


def test_a_publication_with_no_self_author_index_asks_which_position(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "A paper",
            "authors": ["Roe, R.", "Abdullayev, O."],
            "doi": "10.1000/abcd",
            "year": 2024,
        },
    )

    questions = missing_publication_detail(student)

    assert [q.payload_key for q in questions] == ["self_author_index"]
    assert "Roe, R." in questions[0].evidence


def test_a_publication_with_no_year_is_asked_for_one(student):
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {
            "title": "A paper",
            "authors": ["Abdullayev, O."],
            "self_author_index": 0,
            "doi": "10.1000/abcd",
        },
    )

    assert [q.payload_key for q in missing_publication_detail(student)] == ["year"]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k publication -q
```
Expected: FAIL — `cannot import name 'missing_publication_detail'`.

- [ ] **Step 3: Implement**

Add `MISSING_PUBLICATION_DETAIL = "MISSING_PUBLICATION_DETAIL"` to `Kind`, then:

```python
def missing_publication_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """A citation a reader cannot resolve, place or attribute.

    S-011 asks for a resolvable DOI, the applicant's own name bolded and author
    order preserved. Two of the three need a field the extractor often cannot
    fill: a DOI is not on every CV, and which position in a byline is the
    applicant is something only they know when the surname repeats.

    The answer to the authorship question lands in self_author_index as the
    student typed it. PublicationEntry's own validator refuses an index that
    does not point at one of the authors when a draft is built, which is the
    right place for that check -- the ledger records the claim, the schema
    refuses the document.
    """
    questions: list[GapQuestion] = []
    for fact in _current(student, VerifiedFact.Category.PUBLICATION):
        payload = fact.payload if isinstance(fact.payload, dict) else {}
        title = str(payload.get("title") or "a publication on your CV")
        if not payload.get("doi") and not payload.get("url"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_PUBLICATION_DETAIL,
                    fact_id=fact.id,
                    payload_key="doi",
                    prompt=(
                        f'Does "{title}" have a DOI? If not, is there a landing page '
                        "for it?"
                    ),
                    evidence=f'"{title}" has neither a DOI nor an address, so a reader cannot find it.',
                )
            )
        if payload.get("self_author_index") is None:
            authors = payload.get("authors")
            byline = ", ".join(str(name) for name in authors) if isinstance(authors, list) else ""
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_PUBLICATION_DETAIL,
                    fact_id=fact.id,
                    payload_key="self_author_index",
                    prompt=(
                        f'Which author are you on "{title}"? Give the position -- 1 for '
                        "first author, 2 for second, and so on."
                    ),
                    evidence=(
                        f'The byline on "{title}" is: {byline}. We cannot tell which '
                        "name is yours, so none is emphasised."
                        if byline
                        else f'"{title}" lists no authors we can match you against.'
                    ),
                )
            )
        if not payload.get("year"):
            questions.append(
                GapQuestion(
                    kind=Kind.MISSING_PUBLICATION_DETAIL,
                    fact_id=fact.id,
                    payload_key="year",
                    prompt=f'What year was "{title}" published?',
                    evidence=f'"{title}" is on file with no year.',
                )
            )
    return tuple(questions)
```

Add `+ missing_publication_detail(student)` to `gap_questions` after
`incomplete_entry(student)`.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: ask a citation for the identifier, the position and the year it lacks"
```

---

### Task 7: An award's awarding body

S-035: the awarding body was the one field every worked sample carried and the one this model
could not hold until 2026-09-15. It holds it now, and nothing asks. Per award, so a student
with three awards and one body on file is asked twice, not three times.

This is distinct from the existing `missing_award`, which asks whether there is an award at
all and creates one. Both keep `Kind.MISSING_AWARD`: from the student's side they are the same
subject.

**Files:**
- Modify: `apps/documents/gaps.py` (`missing_award_detail`, `gap_questions`)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Produces: `missing_award_detail(student: Membership) -> tuple[GapQuestion, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_an_award_with_no_awarding_body_is_asked_who_gave_it(student):
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {"title": "Dean's Honour List", "date": "2022-06-01"},
    )

    questions = missing_award_detail(student)

    assert [q.payload_key for q in questions] == ["awarding_body"]
    assert "Dean's Honour List" in questions[0].prompt


def test_an_award_that_names_its_body_is_not_asked(student):
    make_fact(
        student,
        VerifiedFact.Category.AWARD,
        {"title": "Dean's Honour List", "awarding_body": "ADA University"},
    )

    assert missing_award_detail(student) == ()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k award_detail -q
```
Expected: FAIL — `cannot import name 'missing_award_detail'`.

- [ ] **Step 3: Implement**

```python
def missing_award_detail(student: Membership) -> tuple[GapQuestion, ...]:
    """An honour with nobody's name behind it.

    S-035: the awarding body is the field every worked sample carries --
    Toronto prints "Instructor of the Year" over "Doctor of Pharmacy program,
    University of Toronto"; Berkeley bolds "Chancellor's Fellowship ..., UC
    Berkeley". AwardEntry has held the field since 2026-09-15 and nothing ever
    asked for it, so every award generated from a CV that did not print one
    stays anonymous.

    Per award rather than one question for the section: which one is missing a
    body is the whole content of the question.
    """
    return tuple(
        GapQuestion(
            kind=Kind.MISSING_AWARD,
            fact_id=fact.id,
            payload_key="awarding_body",
            prompt=(
                f'Who awarded "{title}" -- which faculty, institution or funding body?'
            ),
            evidence=f'"{title}" is on file with nobody named as the awarding body.',
        )
        for fact in _current(student, VerifiedFact.Category.AWARD)
        if isinstance(fact.payload, dict)
        and not fact.payload.get("awarding_body")
        and (title := str(fact.payload.get("title") or "an award on your CV"))
    )
```

Add `+ missing_award_detail(student)` to `gap_questions` directly after `missing_award(student)`.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: an award names who gave it, which the model could hold and nothing asked"
```

---

### Task 8: Absent sections — voluntary work, referees, certificates

Detector 2. "This ledger holds no facts of category X" is itself a fact, and the catalog says
which categories a master's CV should have. Three, and they do not all end the same way:

- **Voluntary / community activity** (S-039, S-042) — Oxford makes it one of three headings,
  Utrecht lists it, Campus France names it, SISGP mandates it. Asked **unconditionally**: no
  country was found whose guidance excludes it, so a country gate on this field would return
  "ask" in every case there is evidence for. A create group of three questions, because an
  `ExperienceEntry` needs an employer, a title and a bullet.
- **Referees** (R-051) — asked when the ledger holds no `REFERENCE` fact and the student looks
  research-track (`_is_research_applicant`, which already exists and already refuses to
  keyword-match employer strings). One question: the name. `ReferenceEntry` requires nothing
  else.
- **Certificates and training** (S-036) — a **NOTE**. There is no `VerifiedFact.Category` for
  one, no `CVContent` entry and no template section, which is S-036's own complaint and why
  the real CV filed a summer school under Awards. Askable, not storable.

**Files:**
- Modify: `apps/documents/gaps.py` (`Kind.ABSENT_SECTION`, `absent_sections`, `absent_section_notes`, `_CREATE_GROUPS`, `gap_questions`, `gap_notes`)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Consumes: `GapQuestion.slug` and `_CREATE_GROUPS` from Task 1; `GapNote` from Task 2.
- Produces:
  - `absent_sections(student: Membership) -> tuple[GapQuestion, ...]`
  - `absent_section_notes(student: Membership) -> tuple[GapNote, ...]`
  - `_CREATE_GROUPS` gains `"voluntary-role": ("employer", "title", "bullets")` and
    `"referee": ("name",)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_voluntary_work_is_asked_unconditionally(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    questions = absent_sections(student)
    voluntary = [q for q in questions if q.slug == "voluntary-role"]

    assert {q.payload_key for q in voluntary} == {"employer", "title", "bullets"}
    assert all(q.category == VerifiedFact.Category.EXPERIENCE for q in voluntary)


def test_an_empty_ledger_is_asked_nothing(student):
    assert absent_sections(student) == ()
    assert absent_section_notes(student) == ()


def test_a_research_applicant_with_no_referee_is_asked_for_one(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )

    referees = [q for q in absent_sections(student) if q.slug == "referee"]

    assert [q.payload_key for q in referees] == ["name"]


def test_a_student_who_already_named_a_referee_is_not_asked(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )
    make_fact(student, VerifiedFact.Category.REFERENCE, {"name": "Prof. Someone"})

    assert [q for q in absent_sections(student) if q.slug == "referee"] == []


def test_certificates_are_a_note_and_never_a_question(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    notes = absent_section_notes(student)

    assert len(notes) == 1
    assert "certificate" in notes[0].text.lower()
    assert not any("certificate" in q.prompt.lower() for q in gap_questions(student))


def test_a_voluntary_role_answered_in_full_becomes_one_experience_fact(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q for q in absent_sections(student) if q.slug == "voluntary-role"
    }

    written = answer_questions(
        [
            (by_key["employer"], "Azerbaijani Chemistry Society"),
            (by_key["title"], "Volunteer tutor"),
            (by_key["bullets"], "Taught weekly chemistry classes to 20 school students."),
        ],
        student=student,
    )

    assert len(written) == 1
    assert written[0].category == VerifiedFact.Category.EXPERIENCE
    assert written[0].payload["title"] == "Volunteer tutor"
```

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k "absent or voluntary or referee or certificate" -q
```
Expected: FAIL — `cannot import name 'absent_sections'`.

- [ ] **Step 3: Implement**

Add `ABSENT_SECTION = "ABSENT_SECTION"` to `Kind`, extend `_CREATE_GROUPS`:

```python
_CREATE_GROUPS: dict[str, tuple[str, ...]] = {
    "merit-award": ("title",),
    "voluntary-role": ("employer", "title", "bullets"),
    "referee": ("name",),
}
```

then:

```python
def absent_sections(student: Membership) -> tuple[GapQuestion, ...]:
    """Questions about what the ledger holds no facts of at all.

    Nothing in a document reveals what it does not mention, so these fire on
    ABSENCE and would otherwise ask a student who has uploaded nothing about a
    CV that does not exist -- the same guard missing_award carries, for the
    same reason.

    Voluntary work is asked UNCONDITIONALLY and deliberately not gated on a
    country. Searched 2026-09-15: no country's guidance was found that excludes
    voluntary or community activity from an admissions CV, and it is named
    positively in the UK, Netherlands, France, Germany, Ireland and the US
    (S-042). A gate returning "ask" in every case there is evidence for is a
    table that does nothing.

    Three questions for one role, not one: an ExperienceEntry needs an
    employer, a title and at least one bullet, so a single free-text answer
    builds a fact generation cannot turn into an entry. They share a slug, so
    answer_questions writes them as one fact and writes nothing if the student
    answers only part (see that function).

    Referees are asked of a research-track applicant only (R-051), judged by
    _is_research_applicant -- the student's own ledger, never a keyword list
    over employer strings.
    """
    if not unsuperseded_facts(student).exists():
        return ()
    questions: list[GapQuestion] = []
    if not any(
        (fact.payload or {}).get("unpaid")
        for fact in _current(student, VerifiedFact.Category.EXPERIENCE)
        if isinstance(fact.payload, dict)
    ):
        evidence = (
            "Your CV lists no voluntary or community activity. Oxford makes it one of "
            "three headings, and the Swedish Institute requires it."
        )
        for key, prompt in (
            (
                "employer",
                "Have you done any voluntary, community or society work? Which "
                "organisation was it with?",
            ),
            ("title", "What was your role there?"),
            (
                "bullets",
                "What did you do in that role? One or two lines, starting with what "
                "you did rather than what you were responsible for.",
            ),
        ):
            questions.append(
                GapQuestion(
                    kind=Kind.ABSENT_SECTION,
                    fact_id=None,
                    category=VerifiedFact.Category.EXPERIENCE,
                    slug="voluntary-role",
                    payload_key=key,
                    prompt=prompt,
                    evidence=evidence,
                )
            )
    if _is_research_applicant(student) and not _current(
        student, VerifiedFact.Category.REFERENCE
    ):
        questions.append(
            GapQuestion(
                kind=Kind.ABSENT_SECTION,
                fact_id=None,
                category=VerifiedFact.Category.REFERENCE,
                slug="referee",
                payload_key="name",
                prompt=(
                    "Who would write you a reference -- a supervisor or a lecturer who "
                    "knows your work? Give one name; we will ask for their details "
                    "when a destination needs them."
                ),
                evidence=(
                    "Your CV names no referee, and European research applications "
                    "routinely expect one."
                ),
            )
        )
    return tuple(questions)


def absent_section_notes(student: Membership) -> tuple[GapNote, ...]:
    """Sections the catalog wants and this ledger cannot hold.

    Certificates and training (S-036, from Queensland, Toronto, Berkeley and
    German guidance) is a real gap and an unanswerable question: there is no
    VerifiedFact category for a certificate, no CVContent entry and no template
    section. That absence IS S-036's complaint -- the real CV filed a summer
    school under Awards because there was nowhere else -- and it is why this is
    a note. A CERTIFICATE category is its own change: a model choice, a
    _CategorySpec, a schema entry, _PAYLOAD_KEYS, an ingestion sentence, a
    render section and a Europass mapping.
    """
    if not unsuperseded_facts(student).exists():
        return ()
    return (
        GapNote(
            text=(
                "Certificates, licences, professional registration and short courses "
                "belong in their own section, and this CV has nowhere to put them yet. "
                "If you hold any, keep the paperwork -- we will ask once there is a "
                "place for it."
            ),
            evidence=(
                "Queensland, Toronto, Berkeley and German guidance all list a "
                "certificates or training section; nothing on file holds one."
            ),
        ),
    )
```

Add `+ absent_sections(student)` to `gap_questions`, last before the programme block, and
`+ absent_section_notes(student)` to `gap_notes`.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_intake.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: ask what the ledger holds none of -- voluntary work, a referee -- and note what it cannot hold"
```

---

### Task 9: Education completeness — the degrees ETH says you must list

ETH, verbatim: "every university attended, including any mobility or exchange programmes and
study programmes which were not completed". ETH treats the omission as the applicant's fault,
and an exchange semester is an `EducationEntry` the student never thinks to list. Two create
groups, each of two questions — an `EducationEntry` needs an institution and a degree title.

Also the society/committee role (Toronto Mississauga's checklist, Cambridge, HKS). S-039 still
refuses a memberships *section*; as a question it is one line and feeds the leadership content
three destinations want. A create group of three, like the voluntary role.

Fired unconditionally, and that is the point: nothing in the ledger can reveal a degree the
student never mentioned. Each group is skippable in one click, which is what a "no" costs.

**Files:**
- Modify: `apps/documents/gaps.py` (`Kind.EDUCATION_COMPLETENESS`, `education_completeness`, `_CREATE_GROUPS`, `gap_questions`)
- Test: `tests/documents/test_gaps.py`

**Interfaces:**
- Produces:
  - `education_completeness(student: Membership) -> tuple[GapQuestion, ...]`
  - `_CREATE_GROUPS` gains `"exchange-programme": ("institution_original", "degree_as_awarded")`,
    `"unfinished-programme": ("institution_original", "degree_as_awarded")` and
    `"society-role": ("employer", "title", "bullets")`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_exchange_and_an_unfinished_programme_are_both_asked(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    slugs = {q.slug for q in education_completeness(student)}

    assert slugs == {"exchange-programme", "unfinished-programme", "society-role"}


def test_each_education_group_asks_for_an_institution_and_a_degree(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})

    for slug in ("exchange-programme", "unfinished-programme"):
        keys = {q.payload_key for q in education_completeness(student) if q.slug == slug}
        assert keys == {"institution_original", "degree_as_awarded"}


def test_education_completeness_asks_an_empty_ledger_nothing(student):
    assert education_completeness(student) == ()


def test_an_exchange_answered_in_full_becomes_one_education_fact(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    by_key = {
        q.payload_key: q
        for q in education_completeness(student)
        if q.slug == "exchange-programme"
    }

    written = answer_questions(
        [
            (by_key["institution_original"], "TU Delft"),
            (by_key["degree_as_awarded"], "Erasmus exchange semester, Applied Chemistry"),
        ],
        student=student,
    )

    assert len(written) == 1
    assert written[0].category == VerifiedFact.Category.EDUCATION


def test_every_create_slug_a_detector_emits_is_declared(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0},
    )

    emitted = {q.slug for q in gap_questions(student) if q.fact_id is None}

    assert emitted
    assert emitted <= set(_CREATE_GROUPS)
    for slug in emitted:
        keys = {
            q.payload_key
            for q in gap_questions(student)
            if q.fact_id is None and q.slug == slug
        }
        assert keys == set(_CREATE_GROUPS[slug])
```

That last test is the one that keeps Task 1's all-or-nothing rule honest: a detector that asks
for two keys while `_CREATE_GROUPS` declares three would silently write nothing, forever.

- [ ] **Step 2: Run them to verify they fail**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k "completeness or exchange or create_slug" -q
```
Expected: FAIL — `cannot import name 'education_completeness'`.

- [ ] **Step 3: Implement**

Add `EDUCATION_COMPLETENESS = "EDUCATION_COMPLETENESS"` to `Kind`, extend `_CREATE_GROUPS`
with the three slugs above, then:

```python
def education_completeness(student: Membership) -> tuple[GapQuestion, ...]:
    """Study and roles the student has, and never thought to write down.

    ETH, verbatim: list "every university attended, including any mobility or
    exchange programmes and study programmes which were not completed". ETH
    treats the omission as the applicant's fault, and neither an Erasmus
    semester nor an abandoned programme is a thing anyone volunteers -- the
    first reads as not a real degree, the second as a failure.

    Unconditional, and it has to be: nothing in a ledger built from the
    student's own CV can reveal a degree the CV never mentioned. The cost is
    three groups a student with none of them skips, which is one click each;
    the alternative is a requirement ETH says it will refuse the application
    over.

    Two questions per programme because an EducationEntry needs an institution
    AND a degree title, and they share a slug so answer_questions writes one
    fact. A society role needs three, like a voluntary one.

    S-039 still refuses a memberships SECTION and this does not add one: the
    answer is an ExperienceEntry, which is where a role with responsibilities
    belongs.
    """
    if not unsuperseded_facts(student).exists():
        return ()
    eth = (
        "ETH Zurich asks for every university attended, including exchange "
        "programmes and programmes that were not completed."
    )
    groups: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
        (
            "exchange-programme",
            VerifiedFact.Category.EDUCATION,
            eth,
            (
                (
                    "institution_original",
                    "Did you spend a semester or a year at another university -- an "
                    "Erasmus or exchange programme, or part of a double degree? Which "
                    "university was it?",
                ),
                (
                    "degree_as_awarded",
                    "What was that exchange or double-degree programme called?",
                ),
            ),
        ),
        (
            "unfinished-programme",
            VerifiedFact.Category.EDUCATION,
            eth,
            (
                (
                    "institution_original",
                    "Did you start any degree or programme you did not finish? Which "
                    "university was it at?",
                ),
                ("degree_as_awarded", "What was that programme called?"),
            ),
        ),
        (
            "society-role",
            VerifiedFact.Category.EXPERIENCE,
            "Toronto, Cambridge and the Harvard Kennedy School all ask for positions "
            "held in student societies and committees.",
            (
                (
                    "employer",
                    "Have you held a position in a student society, committee or "
                    "association? Which one?",
                ),
                ("title", "What was your position there?"),
                (
                    "bullets",
                    "What did the position involve? One or two lines, starting with "
                    "what you did.",
                ),
            ),
        ),
    )
    return tuple(
        GapQuestion(
            kind=Kind.EDUCATION_COMPLETENESS,
            fact_id=None,
            category=category,
            slug=slug,
            payload_key=key,
            prompt=prompt,
            evidence=evidence,
        )
        for slug, category, evidence, asks in groups
        for key, prompt in asks
    )
```

Add `+ education_completeness(student)` to `gap_questions`, after `absent_sections(student)`.
Export `_CREATE_GROUPS` from the module as-is — the test imports it by name, which is
deliberate: the table is a contract between the detectors and the writer, and a test is the
only thing that can hold it.

- [ ] **Step 4: Run the tests**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py tests/documents/test_gap_intake.py tests/documents/test_gap_interview_view.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py tests/documents/test_gaps.py
git commit -m "documents: ask for the exchange, the unfinished programme and the society role ETH and Toronto require"
```

---

### Task 10: The module's own account of itself, and full validation

`gaps.py`'s docstring still says "Three field-null tests" and names the design doc from
2026-08-30. It is now ten detectors and two output kinds, and the docstring is what the next
session reads before anything else — CLAUDE.md records a session misreporting that portal
automation did not exist because a heading said so.

**Files:**
- Modify: `apps/documents/gaps.py` (module docstring, `gap_questions` docstring)
- Modify: `apps/documents/gap_intake.py` (module docstring — the note half)
- Test: `tests/documents/test_gaps.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the failing test**

```python
def test_the_interview_asks_the_real_cv_more_than_the_old_four_checks_did(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(
        student,
        VerifiedFact.Category.EDUCATION,
        {
            "degree_as_awarded": "MSc Chemoinformatics",
            "institution_original": "University of Strasbourg",
            "start_date": "2023-09-01",
        },
    )
    make_fact(student, VerifiedFact.Category.LANGUAGE, {"language": "English"})

    kinds = {q.kind for q in gap_questions(student)}

    assert kinds >= {
        Kind.MISSING_CONTACT,
        Kind.MISSING_LANGUAGE,
        Kind.MISSING_GRADE,
        Kind.MISSING_DEGREE_DETAIL,
        Kind.ABSENT_SECTION,
        Kind.EDUCATION_COMPLETENESS,
    }


def test_the_language_certificate_is_asked_before_a_publication_year(student):
    make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": "A Student"})
    make_fact(student, VerifiedFact.Category.LANGUAGE, {"language": "English"})
    make_fact(
        student,
        VerifiedFact.Category.PUBLICATION,
        {"title": "A paper", "authors": ["Abdullayev, O."], "self_author_index": 0,
         "doi": "10.1000/abcd"},
    )

    keys = [q.payload_key for q in gap_questions(student)]

    assert keys.index("test_score") < keys.index("year")
```

- [ ] **Step 2: Run them**

```bash
POSTGRES_DB=tehsil_gapreview uv run pytest tests/documents/test_gaps.py -k "real_cv or before_a_publication" -q
```
Expected: PASS already, if Tasks 3–9 placed their detectors in the stated order. A failure
here means the order in `gap_questions` is wrong — fix the order, not the test.

- [ ] **Step 3: Rewrite the module docstring**

Replace the first paragraph of `apps/documents/gaps.py`'s docstring:

```
"""The counsellor's review: what the ledger is missing, and what it cannot hold.

Ten deterministic detectors over the fact ledger, run before generation rather
than after it. Asking after generating burns a generation, shows a document
built on a gap, and then asks; asking first costs nothing and produces a better
first draft.

Two output kinds. A GapQuestion is answerable and writes a fact; a GapNote is
not and writes nothing -- see GapNote on why that is a separate type rather
than a nullable payload_key. Notes are the preferred output wherever the
student cannot act, and two of them exist because the ledger has no shape for
the answer: a timeline gap (no TimelineEntry) and a certificate (no
CERTIFICATE category).

No model call anywhere in this module -- these are the checks that need none.
The design's third detector will call one, and the change that wires it up owes
the per-student rate limiter CLAUDE.md requires. Nothing here does, and this
module must not be used as evidence that a limiter exists.

Not here, and not by omission:

- **Country-gated questions** (photo, date of birth, signature, secondary
  school) and the pack-gated ones (German level, ECTS, relevant coursework).
  Both need a pack's countries or disciplines, and funding.RecommendationCandidate
  carries program_name as free text with no country_code and no FK to Program.
  Degradation is the correct behaviour: asking a UK-bound student for a passport
  photo is the mistake, asking nobody is a missed prompt.
- **A thesis grade** (S-027, DE/NL/Nordic). No field holds one -- grade_native
  is the degree's -- and no render decision has been taken about printing it.
- **Prose rewriting.** A limit, not a backlog item: an accepted rewrite would
  make a model the author of the student's claim on a submitted document.
```

Keep the rest of the existing docstring — the three things the first caller owes are all still
true — and update its "Design:" line to name both specs:

```
Design: docs/superpowers/specs/2026-08-30-cv-gap-interview-design.md
        docs/superpowers/specs/2026-09-16-cv-counsellor-review-design.md
```

In `gap_questions`'s docstring, replace "Everything the ledger can be asked about without a
model call" 's second paragraph with the current order and why:

```
    Ordered by value, highest first, and the order is the only thing spent: a
    contact line and a language certificate come before a publication's year,
    so a student who stops a third of the way down has answered the questions
    every destination asks. There is no cap, deliberately -- a dropped question
    is a fact the ledger never gets and nothing ever asks for again, which is
    the silent failure this repo keeps recording.
```

In `apps/documents/gap_intake.py`'s docstring, add one bullet:

```
- **Notes are not submitted.** ``gap_notes`` output never reaches this module:
  a note has no field name, so there is nothing for ``submitted`` to carry and
  nothing to look up. That is the whole reason it is a separate type.
```

- [ ] **Step 4: Full validation**

```bash
cd /home/orkhan/Desktop/tehsil_agent
uv run ruff check apps tests
uv run mypy apps/documents
POSTGRES_DB=tehsil_gapreview uv run pytest -q
git diff --stat
git status --short
```
Expected: ruff clean, mypy clean, the whole suite green (2474 passed / 45 skipped was the
count before this plan; it goes up, never down), and `git status` showing no change to
`DESIGN.md`, `apps/research/pipeline.py`, `docs/research/2026-08-21-humanizer-assessment.md`,
`skill-observations/*`, `tests/research/test_discovery_pipeline.py`, `.agents/product-marketing.md`
or `website-proposal.md` — those are another session's and must be left exactly as they are.

If `uv run pytest` reports a database still in use, another session holds it; use a different
`POSTGRES_DB` name rather than terminating their backends.

- [ ] **Step 5: Commit**

```bash
git add apps/documents/gaps.py apps/documents/gap_intake.py tests/documents/test_gaps.py
git commit -m "documents: the module says what it is now -- ten detectors, two output kinds, and what is deliberately absent"
```

---

## Self-review against the spec

**Covered:** detector 1's ten catalog rows (grade-in-progress already shipped at `c48ccd5`;
language ×2 → Task 3; thesis, supervisor, rank → Task 4; publication ×3 → Task 6; awarding
body → Task 7), four of the five S-050 finds (medium of instruction → Task 5; exchange,
unfinished, double degree → Task 9; society role → Task 9), detector 1b → Task 2,
detector 2's three sections → Task 8, the output-kinds contract → Tasks 1 and 2, the write
contract and server-side key validation → Task 1 (and `answer_questions`, unchanged).

**Not covered, each with a reason stated in the plan header or the task:** detector 3,
the country gate, the pack-gated three, `relevant_coursework`, the thesis grade, talk-vs-poster,
a `CERTIFICATE` category. (`TimelineEntry` was on this list; it landed 2026-10-05, follow-up 2.)

**Follow-ups this plan creates, in the order they are worth doing:**
1. Detector 3 (the model checks) — its own plan; it owes the rate limiter and the
   cache-in-the-cache-backend that spec correction 3 specifies.
2. ~~`TimelineEntry` (start, end, one line) — turns every Task 2 note into a question and
   finally gives C-002 something to act on.~~ Landed 2026-10-05 on `claude/cv-timeline-entry`, from
   the 2026-10-05 refresh of the plan, not the 2026-09-17 draft (see spec §1b). C-002 now acts on
   it: the render's gap check counts a statement where the variant prints it. An open-ended
   answer closes at the next entry's start. Every consumer reads the statement (owner, 2026-10-06):
   letters, storyline, tailoring, portal values and europa.eu.
3. A `CERTIFICATE` fact category — turns the Task 8 note into a question.
4. The pack prerequisite in `apps/funding` (`country_code`, or an FK to `Program`, on
   `RecommendationCandidate`) — unblocks the country gate and the field gate at once.
