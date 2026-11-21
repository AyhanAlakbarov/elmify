# Transcript reader plan 3b: the transcript check, on its own — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The student checks their transcript reading in its own step: one tap when nothing is doubtful, otherwise one card per doubtful cell (*matches / fix / can't read*), a read-only summary, and "something's wrong" that never blocks. Accepting it — not the questionnaire's Confirm — is what marks the reading accepted, updates the profile, and (once the owner settles two questions) puts the courses into the student's confirmed facts.

**Architecture:** A small domain module, `apps/documents/transcript_check.py`, turns a reading's highlights into check items, records each answer beside the reader's value, re-runs the checks after a fix, and accepts. A plain-HTML page at `/student/transcript/` drives it; the dashboard shows "Check your transcript" while a reading is unaccepted. The questionnaire keeps pre-filling from the reading but no longer accepts it.

**Tech Stack:** Django views and templates (plain HTML, Aykhan styles later), Pydantic, Postgres, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` §6.2–6.6; `docs/superpowers/specs/2026-10-15-onboarding-and-transcript-friction-design.md` variants B, 3, 4, 7, D. Depends on plan 3a (crops); a row without a crop is shown without a picture.

## Owner decisions this plan needs (asked 2026-10-15, not yet answered)

1. **How courses are stored as facts.** DECIDED (owner, 2026-10-15): as recommended — inside the matching EDUCATION fact (same institution and degree, `verification._SPECS` identity), created from the transcript if the CV never listed that degree. Alternative: one fact per course (a new category).
2. **Which ledger consumers use courses now.** DECIDED (owner, 2026-10-15): as recommended — letters and stories now; the CV's "relevant coursework" and Europass "main subjects" go to the CV-quality design; portal autofill does not use them. `.claude/rules/cv-and-letters.md` ("One ledger, every consumer") requires the exclusions to be recorded as an owner decision.

Tasks 1–6 do not depend on them. Task 7 (courses into the ledger) follows both decisions; the owner confirmed them on 2026-10-15.

## Global Constraints

- Lint `uv run ruff check .`; types `uv run mypy apps config`; never `ruff format`.
- Tests: `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents tests/accounts tests/concierge`.
- **Never repaired, never overwritten** (spec §6.2, §6.6): a fixed or typed value is stored as student-entered beside the reader's value; the reader's value is never replaced.
- **No "confirm all", nothing pre-selected** on a doubtful cell (spec §6.3).
- **Unflagged cells are never labelled "verified"** (research do/don't 5).
- The page is a web view under `runtime_web`: it reads tenant tables only (readings, uploads, the profile) — no catalogue (`.claude/rules/row-level-security.md`).
- New personal-data fields go into `apps/audit/redaction.py` REDACT; structural ones into KEEP.
- Screens: plain HTML with `SHOULD BE DONE BY AYKHAN` notes.

## Review Focus

1. **A fix that breaks a printed total** must be flagged again on the same screen (spec §6.6: checks run on student-entered values).
2. **A student who accepts, then a newer reading arrives** (a retake or replacement) — the newer reading is offered as a fresh check; the accepted one stays the record until the new one is accepted.
3. **"Can't read" on every item** still lets the student accept; the reading is marked for review and the profile notes those values as unconfirmed.
4. **A reading with no highlights at all** shows the one-tap card; "Something's wrong" there still marks it for review.
5. **The questionnaire's Confirm** no longer writes `TranscriptReading.accepted`; a profile finalized before the check is updated when the check is accepted (a new profile version, not an edit).

---

### Task 1: Store answers and review requests on the reading

**Files:**
- Modify: `apps/documents/models.py` (`TranscriptReading.answers`, `review_requested_at`, `review_reason`), new migration
- Modify: `apps/audit/redaction.py` (`answers`, `review_reason` → REDACT; `review_requested_at` → KEEP)
- Test: `tests/documents/test_transcript_check.py` (new)

**Interfaces:**
- Produces: `answers = JSONField(default=dict)` — `{"<item ref>": {"choice": "matches"|"fix"|"cant_read", "value": "<student value or ''>", "at": "<iso>"}}`; `review_requested_at = DateTimeField(null=True)`; `review_reason = CharField(max_length=500, blank=True)`.

- [ ] **Step 1: Failing test** — a reading saves and reloads an `answers` entry; `REDACT["documents.TranscriptReading"]` contains `answers` and `review_reason`.
- [ ] **Step 2: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_transcript_check.py` — FAIL (no field).
- [ ] **Step 3: Implement** the three fields, `makemigrations documents --name transcript_check_answers`, the redaction entries.
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents tests/audit` — PASS (erasure completeness included).
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): a reading keeps the student's answers and review requests beside the reader's values" -- apps/documents/models.py apps/documents/migrations/<new>.py apps/audit/redaction.py tests/documents/test_transcript_check.py`

---

### Task 2: Check items from highlights

**Files:**
- Create: `apps/documents/transcript_check.py`
- Test: `tests/documents/test_transcript_check.py`

**Interfaces:**
- Produces:
  - `CheckItem(ref: str, row_title: str, cell: Literal["title","credits","grade","field"], reader_value: str, reason: str, crop_ref: str | None)` — frozen dataclass. `ref` is `"<row index>:<cell>"` for a row highlight, `"field:<name>"` for a field highlight, `"semester:<row index>"` for a semester total.
  - `check_items(reading: TranscriptReading) -> tuple[CheckItem, ...]` — one item per doubtful cell, in reading order.
  - `REASONS: dict[str, str]` — the plain-words reason per highlight kind, e.g. `"low_confidence": "We weren't sure we read this correctly."`, `"credit_total_mismatch": "The credits on this page add up to {sum}; the transcript prints {printed}."`, `"grade_above_scale": "This grade is above the scale printed on the transcript ({scale})."`, `"credit_out_of_range": "This credit value is unusually large or small."`, `"unsure": "We weren't sure what this row is."`, `"mixed_script": "This text mixes Latin and Cyrillic letters."`, `"credit_total_not_checked"` → no item (it is shown as a note on the summary, never asked about).

- [ ] **Step 1: Failing tests**

```python
def test_a_low_confidence_row_asks_about_its_credits_and_grade():
    reading = _reading(rows=[_row(1, "Physics", credits="6", grade="B")],
                       highlights=[{"kind": "low_confidence", "scope": "row", "ref": "1"}],
                       crops={"1:credits": "k1", "1:grade": "k2"})
    items = check_items(reading)
    assert [(i.ref, i.reader_value, i.crop_ref) for i in items] == [
        ("1:credits", "6", "1:credits"), ("1:grade", "B", "1:grade")]
    assert items[0].reason == REASONS["low_confidence"]


def test_a_not_checked_total_is_never_asked():
    reading = _reading(highlights=[{"kind": "credit_total_not_checked", "scope": "transcript", "ref": ""}])
    assert check_items(reading) == ()


def test_a_row_without_a_crop_is_still_asked():
    reading = _reading(rows=[_row(1, "Physics")],
                       highlights=[{"kind": "grade_above_scale", "scope": "row", "ref": "1"}], crops={})
    assert check_items(reading)[0].crop_ref is None


def test_no_highlights_means_no_items():
    assert check_items(_reading(highlights=[])) == ()
```

- [ ] **Step 2: Run** — FAIL (module missing).
- [ ] **Step 3: Implement** `check_items` from `reading.highlights` (validated with `transcript.Highlight`), `reading.rows` (by index) and `reading.crops`; semester and field items use the highlight's `ref`. Fill reason templates from `reading.key_numbers` where they need numbers.
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_transcript_check.py` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): the doubtful cells a student is asked about, each with its reason in plain words" -- apps/documents/transcript_check.py tests/documents/test_transcript_check.py`

---

### Task 3: Answer, re-check, accept, ask for review

**Files:**
- Modify: `apps/documents/transcript_check.py`
- Modify: `apps/documents/transcript_checks.py` (expose the check run over a list of rows so it can re-run on student-entered values, if it does not already)
- Test: `tests/documents/test_transcript_check.py`

**Interfaces:**
- Produces:
  - `answer(reading, ref: str, choice: str, value: str = "") -> tuple[CheckItem, ...]` — validates `ref` against `check_items`, `choice` ∈ {matches, fix, cant_read}, `value` required for `fix`; stores it in `reading.answers` with a timestamp; re-runs the checks on the rows with student-entered values applied; returns the items now open (an edit that breaks a total adds the semester item back).
  - `effective_rows(reading) -> list[Row]` — the reader's rows with each `fix` value applied; the reader's value is untouched in `reading.rows`.
  - `accept(reading, *, student: Membership) -> None` — refuses (`ValueError("unanswered")`) while any item has no answer; sets `reading.accepted` to the academic record built from `effective_rows` (courses whose cell was `cant_read` carry the reader's value and are listed in `review_reason`); a `cant_read` anywhere sets `review_requested_at`.
  - `request_review(reading, reason: str) -> None` — "Something's wrong": sets `review_requested_at` and `review_reason`; never blocks `accept`.

- [ ] **Step 1: Failing tests**

```python
def test_a_fix_is_stored_beside_the_readers_value():
    reading = _reading_with_low_confidence_grade(row=1, grade="B")
    answer(reading, "1:grade", "fix", "A")
    assert reading.rows[1]["grade"] == "B"
    assert effective_rows(reading)[1].grade == "A"
    assert reading.answers["1:grade"]["value"] == "A"


def test_a_fix_that_breaks_the_printed_total_is_asked_again():
    reading = _reading_with_balanced_semester(row=1, credits="6", printed_total="30")
    open_items = answer(reading, "1:credits", "fix", "8")
    assert any(i.ref.startswith("semester:") for i in open_items)


def test_accept_refuses_while_an_item_is_unanswered():
    reading = _reading_with_low_confidence_grade(row=1, grade="B")
    with pytest.raises(ValueError, match="unanswered"):
        accept(reading, student=_student())


def test_cant_read_still_accepts_and_marks_for_review():
    reading = _reading_with_low_confidence_grade(row=1, grade="B")
    answer(reading, "1:grade", "cant_read")
    accept(reading, student=_student())
    assert reading.accepted is not None and reading.review_requested_at is not None


def test_somethings_wrong_never_blocks_accepting():
    reading = _reading(highlights=[])
    request_review(reading, "my second semester is missing")
    accept(reading, student=_student())
    assert reading.accepted is not None and reading.review_reason == "my second semester is missing"


def test_a_ref_not_on_the_reading_is_refused():
    with pytest.raises(ValueError):
        answer(_reading(highlights=[]), "9:grade", "matches")
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** as specified; `accept` builds the record with the same function `prefill_from_latest_reading` uses to turn a reading into an academic record, fed `effective_rows`; save with `update_fields`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): answer, re-check after a fix, accept, and ask for review without blocking" -- apps/documents/transcript_check.py apps/documents/transcript_checks.py tests/documents/test_transcript_check.py`

---

### Task 4: The check page

**Files:**
- Add the view to `apps/documents/views.py`, where the other student pages live, `templates/student/transcript_check.html`
- Modify: `apps/documents/urls.py` (`student/transcript/`, name `student-transcript-check`)
- Test: `tests/documents/test_transcript_check_page.py`

**Interfaces:**
- Consumes: Task 2–3 functions; plan 3a's crop endpoint for `<img>` sources.
- Behaviour:
  - No unaccepted reading → "Nothing to check" with a link to the documents page.
  - **No items** (variant 3): one card — "We read {n} courses, {credits} credits, overall {grade} on a {scale} scale. Looks right?" with **Yes** (POST `accept`) and **Something's wrong** (POST `review` with a free-text reason, then the same card with "Thanks — someone will look at it" and **Continue**, which accepts).
  - **Items** (variant 4): one card at a time — the course title, the crop (`<img alt="...">` from the crop endpoint) or the note "No picture for this one", the reader's value, the reason, three buttons *Matches* / *Fix* (reveals one input) / *Can't read*; nothing pre-selected; a progress line "2 of 3".
  - After the last card: a read-only table of every course (title, credits, grade, "you changed this" where fixed), the key numbers, the line "Only the cells we asked about were checked with you", **Accept**, and a **Something's wrong** link.
  - `SHOULD BE DONE BY AYKHAN` on the card and table layout.

- [ ] **Step 1: Failing tests** (Django test client):
  - a reading with no highlights renders the one-tap card and POST `accept` sets `accepted`;
  - a reading with one low-confidence row renders its first card with both crop `<img>` tags and no pre-checked control;
  - POST `answer` with `fix` and a value advances to the next card;
  - the summary lists every course and never contains the word "verified";
  - another student's reading id returns 404.
- [ ] **Step 2: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_transcript_check_page.py` — FAIL.
- [ ] **Step 3: Implement** the view (`@login_required`, the student's own membership, the newest unaccepted reading) and the template.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): the transcript check page — one tap when clean, one card per doubtful cell" -- apps/documents/views.py apps/documents/urls.py templates/student/transcript_check.html tests/documents/test_transcript_check_page.py`

---

### Task 5: The questionnaire stops accepting; the profile follows the check

**Files:**
- Modify: `apps/accounts/consultation.py` (`finalize_consultation` no longer writes `accepted`)
- Modify: `apps/documents/transcript_check.py` (`accept` writes a new profile version when the student's latest profile holds this reading's degree)
- Test: `tests/accounts/test_prefill.py` (`test_finalize_records_what_the_student_kept` changes meaning), `tests/documents/test_transcript_check.py`

**Interfaces:**
- `finalize_consultation` keeps `reading_id` in the draft for provenance but leaves `TranscriptReading.accepted` alone.
- `accept` → if the student's latest `StudentProfileVersion` has an academic record matching the reading's institution and qualification, `create_profile_version` with that record replaced by the accepted one (courses and grade as checked). A profile is never edited in place (`accounts/0006`'s immutability trigger).

- [ ] **Step 1: Failing tests**:
  - finalizing the questionnaire leaves the reading unaccepted;
  - accepting the check after finalizing writes a new profile version whose degree carries the student's fixed grade;
  - accepting before the questionnaire is finished writes no profile version, and the questionnaire's pre-fill then uses the accepted record (no doubts left to show).
- [ ] **Step 2: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/accounts/test_prefill.py tests/documents/test_transcript_check.py` — FAIL.
- [ ] **Step 3: Implement.** In `prefill_from_latest_reading`, an accepted reading is pre-filled from `accepted` (today it is skipped once accepted — change: skip only if the draft already has a degree).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): the check, not the questionnaire, accepts the reading; the profile follows it" -- apps/accounts/consultation.py apps/documents/transcript_check.py tests/accounts/test_prefill.py tests/documents/test_transcript_check.py`

---

### Task 6: "Check your transcript" on the dashboard; review requests visible to the right person

**Files:**
- Modify: `apps/concierge/views.py` (student dashboard context: `transcript_to_check`), `templates/student/dashboard.html`
- Modify: the counsellor's student page and the staff student page (the views `apps/dashboard/views.py::_staff_read` / the counsellor student view use) to show "Transcript: the student asked for a review — <reason>"
- Test: `tests/concierge/test_dashboard.py` (or the file testing the student dashboard), `tests/dashboard/`

**Interfaces:**
- `transcript_to_check(student) -> TranscriptReading | None` — the newest unaccepted reading.
- Direct-to-student students (no active `CounselorAssignment`) surface on the staff page; agency students on their counsellor's page (spec §6.5's split; variant 7).

- [ ] **Step 1: Failing tests**: the dashboard shows a "Check your transcript" link when a reading is unaccepted and not when it is accepted; a counsellor's student page shows the review reason; a direct student's review shows on the staff page and not on any counsellor page.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/concierge tests/dashboard` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): the dashboard asks the student to check their transcript; review requests reach a person" -- apps/concierge/views.py templates/student/dashboard.html apps/dashboard/views.py tests/concierge tests/dashboard`

---

### Task 7: Courses into the confirmed facts — without a second copy of the degree

**Why this task is shaped this way (owner, 2026-10-15):** "attach to the matching degree" will often
find no match. Today `ingestion.ingest_uploaded_cv` writes a new EDUCATION fact every time, and
`verification._identity` treats two degrees as the same only when `institution_original` and
`degree_as_awarded` are equal after `_norm` (case and spacing). A CV saying "Baku State University,
BSc Chemistry" and a transcript saying "Bakı Dövlət Universiteti, Bakalavr" never match, so the
degree would print twice on the CV. Names alone cannot decide this (two languages, abbreviations), so
the matcher uses every signal, decides only when it is sure, and otherwise asks the student one
question inside the check they are already doing.

**Files:**
- Create: `apps/documents/degree_match.py`
- Modify: `apps/documents/transcript_check.py` (a "same degree?" item; `accept` writes or supersedes the fact)
- Modify: `apps/documents/ingestion.py` (a CV read after the transcript uses the same matcher)
- Modify: `apps/documents/verification.py` (`_PAYLOAD_KEYS`: `courses`, `courses_unconfirmed`, `aliases` carried, never compared)
- Modify: `.claude/rules/cv-and-letters.md` ("One ledger, every consumer": the owner's recorded exclusions — courses reach letters and stories now; the CV's coursework line and Europass wait for the CV-quality design; portal autofill never uses them)
- Test: `tests/documents/test_degree_match.py` (new), `tests/documents/test_transcript_check.py`, `tests/documents/test_ingestion.py`

**Interfaces:**
- `degree_level(text: str) -> Literal["bachelor","master","doctorate","other"]` — keyword lists in English, Azerbaijani, Turkish and Russian (bachelor / bakalavr / lisans / бакалавр / BSc / BA; master / magistr / yüksek lisans / магистр / MSc / MA; PhD / doktor / fəlsəfə doktoru / кандидат / аспирантура).
- `institution_key(name: str) -> str` — `anyascii`, casefold, punctuation removed, generic words dropped (university, universiteti, üniversitesi, университет, state, dövlət, devlet, государственный, of, the).
- `same_degree(fact_payload: dict, record: dict) -> Literal["same","different","ask"]`:
  - **different** — the levels differ (both known), or the end dates are more than 12 months apart (both known);
  - **same** — `institution_key` equal, or one name's initials equal the other's (`"BSU"` vs "Baku State University"), or the record's institution or degree is in the fact's `aliases`; *and* the levels are equal or unknown; *and* the end dates are within 6 months or unknown;
  - **ask** — everything else, including the common cross-language case: same country, same level, end dates within 6 months, names that do not match.
- `match_record(student, record) -> tuple[Literal["same","different","ask","none"], VerifiedFact | None]` — runs `same_degree` over the student's live EDUCATION facts; one **same** wins; any **ask** (and no same) returns the first ask candidate; no facts → `none`.
- In the check: when `match_record` says **ask**, `check_items` adds one item `ref="degree:same"` — "Is this the same degree as **{fact degree}, {fact institution}, {fact year}** on your CV?" with *Same degree* / *Different degree*, nothing pre-selected. `accept` refuses while it is unanswered, like any item.
- `accept`: **same** (matched or answered) → a superseding EDUCATION fact that keeps the existing fact's `institution_original` and `degree_as_awarded` (the CV's wording stays what prints) and adds `courses`, `courses_unconfirmed` and `aliases` (the transcript's institution and degree as read, so the next CV upload or the diploma reader matches exactly); **different** or **none** → a new EDUCATION fact from the transcript, `aliases` empty. `confirmed_by` = the student, `source_ref = "transcript:<reading id>"`. A `cant_read` course goes in `courses_unconfirmed`; letters never quote it.
- CV read **after** the transcript (`ingest_uploaded_cv`): for each EDUCATION claim, `match_record` against the live facts; **same** → no new fact (the claim confirms the existing one); **ask** → the candidate fact is written with `possible_duplicate_of=<fact id>` in its payload and the gap interview asks the same one-tap question before it is confirmed; **different/none** → as today.

- [ ] **Step 1: Failing tests** (`test_degree_match.py`, real-looking names):
  - "Baku State University, BSc Chemistry, 2025-06" vs "Bakı Dövlət Universiteti, Bakalavr, 2025-06" → `ask`;
  - "BSU, BSc, 2025" vs "Baku State University, Bachelor of Science, 2025" → `same` (initials);
  - same university, "BSc" vs "MSc" → `different`;
  - same university and level, end dates 2021 vs 2025 → `different`;
  - a record whose institution is in the fact's `aliases` → `same`;
  - `institution_key("Bakı Dövlət Universiteti") == institution_key("Baki Dovlet Universiteti")`.
  In `test_transcript_check.py`: an `ask` match adds the "degree:same" item; answering *Same degree* supersedes the CV's fact (still one live EDUCATION fact for that degree, carrying `courses` and `aliases`, printing the CV's wording); *Different degree* adds a second fact; accepting twice writes no third. In `test_ingestion.py`: a CV uploaded after the transcript whose degree matches an alias creates no new EDUCATION fact; one that is `ask` writes a candidate carrying `possible_duplicate_of`.
- [ ] **Step 2: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_degree_match.py tests/documents/test_transcript_check.py tests/documents/test_ingestion.py` — FAIL.
- [ ] **Step 3: Implement** as specified. The CV renderer is not changed: with no duplicate fact there is nothing to de-duplicate at render.
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): checked courses join the right degree — matched when sure, asked in one tap when not, never printed twice" -- apps/documents/degree_match.py apps/documents/transcript_check.py apps/documents/ingestion.py apps/documents/verification.py .claude/rules/cv-and-letters.md tests/documents/test_degree_match.py tests/documents/test_transcript_check.py tests/documents/test_ingestion.py`

**One matcher, not two (elmify-59, 2026-10-15).** The diploma reader on `claude/fact-reading-design` already has a degree match: `apps/documents/fact_writer.py::_equal` (case, spacing and punctuation folded; year only from a proven end date), a student question "Is this a new degree?" with *Yes, add it* / *No — it's my X* handled by `merge_whole_document`, and `placed_whole_rows`, which stops a merged diploma row also being confirmed as its own degree. Before building this task, check whether that branch has merged:
- **merged:** build `degree_match.py` by extending that matcher (its `_equal` becomes one input to `same_degree`), reuse its question and merge path for the transcript's "same degree?" item, and replace its lookup with `match_record` so CV, transcript and diploma share one decision;
- **not merged:** build as written here and send elmify-59 the branch and SHA; the seam on their side is swapping `_equal` and their lookup for `match_record`.

---

### Task 8: Every gate

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py check
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q
```
