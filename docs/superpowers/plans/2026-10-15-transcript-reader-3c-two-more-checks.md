# Transcript reader plan 3c: grades that disagree with their letter, and missing pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two checks the transcript spec adds (§6.1): a course whose points and letter disagree under its institution's grading table is flagged, and a transcript with a printed "page X of Y" not covered is caught before reading finishes.

**Architecture:** Grading tables are data (a CSV keyed by institution and date range), never code constants; an institution or year with no table gets "not checked". Page completeness is a refusal reason the quality gate already names (`page_missing`, spec §5) computed from the pages' own text. Both feed `transcript_checks.highlights`, so plan 3b's check shows them with no further change.

**Tech Stack:** Python, CSV data under `docs/research/` or `apps/documents/data/`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` §5 (`page_missing`), §6.1; evidence `docs/superpowers/research/2026-10-03-azerbaijan-e-diploma-and-grading-scales.md`.

## Global Constraints

- Lint, types and tests as in plan 3b (`POSTGRES_DB=elmify_letter_plan_2`).
- **No guessed scale:** a table is used only for an institution and graduation date range it names; anything else is "not checked" (spec §6.1).
- **Sources are cited per row**, and a row resting on an Unverified source says so in a `verified` column; the research file marks order 1060's text Unverified (university copies only) — the national 2008 bands still go in, marked `verified=no`, because the check only flags (a student answers *matches* on a correct grade) and never repairs.
- A failed check is shown, never repaired (§6.2).

## Review Focus

1. **A 1999–2008 transcript graded 86** is "əla" (A) on that scale and "B" under order 1060 — the date range must pick the right table.
2. **Khazar excludes F from its GPA; the national formula keeps it** — this plan checks per-course point–letter agreement only, never recomputes a GPA.
3. **A transcript with letters only (Turkish)** — no points, so no point–letter check, never "failed".
4. **"Page 1 of 1"**, "1/3" in a footer, and a page number inside a course title ("Physics 1/2") — only footer/header page markers count.
5. **A grading-scale reference with no scale page** ("see grading scale overleaf") is `page_missing` with its own message (spec §5 table).

---

### Task 1: Grading tables as data

**Files:**
- Create: `apps/documents/data/grading_tables.csv` — columns `institution_key, valid_from, valid_to, letter, points_min, points_max, source_url, verified`
- Create: `apps/documents/grading.py` — `GradingRow`, `load_tables()`, `table_for(institution: str, graduated: date | None) -> tuple[GradingRow, ...] | None`
- Test: `tests/documents/test_grading.py`

**Interfaces:**
- `institution_key` is a normalised institution name (casefold, whitespace collapsed); `"*AZ-national"` is the national table used for Azerbaijani state universities not listed on their own.
- Rows to enter, each with its citation from the research file: national 2008+ (91–100 A, 81–90 B, 71–80 C, 61–70 D, 51–60 E, 0–50 F; `verified=no`); national 1999–2008 experimental (86–100 əla, 71–85 yaxşı, 51–70 kafi, 0–50 qeyri-kafi; `verified=no`); Khazar, BHOS, ADA, UFAZ only where the research file gives their bands with a source — otherwise no row (they fall to "not checked", never to the national table).

- [ ] **Step 1: Failing tests**: `table_for("Baku State University", date(2025, 6, 30))` returns the 2008 national bands; a 2005 graduation returns the 1999–2008 bands; `table_for("Khazar University", ...)` returns None unless a Khazar row exists; every CSV row has a `source_url`.
- [ ] **Step 2: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_grading.py` — FAIL.
- [ ] **Step 3: Implement** the CSV and loader (read once, cached with `functools.cache`).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): grading tables as cited data, keyed by institution and date" -- apps/documents/data/grading_tables.csv apps/documents/grading.py tests/documents/test_grading.py`

---

### Task 2: The point–letter check

**Files:**
- Modify: `apps/documents/transcript.py` (`Highlight.kind` gains `"points_letter_mismatch"`), `apps/documents/transcript_checks.py`
- Modify: plan 3b's `transcript_check.REASONS` (`"points_letter_mismatch": "The points ({points}) and the letter ({letter}) don't match the grading table for {institution}."`) — if 3b is not yet merged, add the reason there when it is
- Test: `tests/documents/test_transcript_checks.py`

**Interfaces:**
- A row is checked only when its grade cell carries both a number and a letter (e.g. "86 B", "B (86)") and `table_for` returns a table; a mismatch yields `Highlight(kind="points_letter_mismatch", scope="row", ref=<row index>)`.

- [ ] **Step 1: Failing tests**: "95 A" passes and "86 A" fails under the 2008 table; "86 əla" passes under the 1999–2008 table for a 2005 graduate; "B" alone is not checked; an institution with no table produces no highlight.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** a small parser for "<number> <letter>" / "<letter> (<number>)" / "<number> (<word>)" grade cells, mapping Azerbaijani words (əla, çox yaxşı, yaxşı, kafi, qənaətbəxş, qeyri-kafi) to their letters per table.
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): a course whose points and letter disagree is flagged" -- apps/documents/transcript.py apps/documents/transcript_checks.py tests/documents/test_transcript_checks.py`

---

### Task 3: Page completeness

**Files:**
- Modify: `apps/documents/ocr.py` or `apps/documents/transcript_pages.py` (wherever page refusals are decided; `_gate` names the existing reasons)
- Test: `tests/documents/test_transcript_pages.py`

**Interfaces:**
- `missing_pages(pages: Sequence[tuple[int, OcrPage]]) -> tuple[str, ...]` — messages: "Page {n} of {total} is missing." for each uncovered number when at least one page prints "page X of Y" / "X / Y" / "səhifə X / Y" / "стр. X из Y" in a header or footer line (first or last two lines of the page); "Upload the page with the grading scale." when a page references a grading scale and no page contains a grading table (a table whose rows match the grading-table letters).
- `assemble` waits (as for a refused page with retakes left) and the upload status lists the message (`api/documents/transcript` `refusal`), so the student is asked for the page before the check.

- [ ] **Step 1: Failing tests**: pages "1 of 3" and "3 of 3" → "Page 2 of 3 is missing."; "Physics 1/2" in a table cell is ignored; no markers at all → nothing; a scale reference with no scale page → the scale message.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): a missing page is asked for before the check, not discovered after" -- apps/documents/transcript_pages.py apps/documents/ocr.py tests/documents/test_transcript_pages.py`

---

### Task 4: Every gate

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py check
POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q
```
