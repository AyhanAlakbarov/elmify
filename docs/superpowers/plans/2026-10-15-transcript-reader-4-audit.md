# Transcript reader plan 4: the audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A random sample of accepted transcripts is checked by a person against the original, cell by cell, so we learn how many wrong values reach a student's record without being flagged — the only way to know whether showing the student 0–3 cells is enough.

**Architecture:** On acceptance (plan 3b), a reading is drawn into the audit at a configured rate, always when it carries many student-entered values or one that raises a credit total or grade (spec §6.6). Audits are tenant rows: an agency's sample is audited by that agency's counsellor inside its tenant; a direct student's by platform staff in the platform tenant. The audit page shows the original upload beside the stored values and takes a verdict per deciding cell. Nothing waits on the audit.

**Tech Stack:** Django, Postgres RLS, the existing staff/counsellor access helpers (`storage.admit`, `staff_may_view`, `audit.staff_access.record_staff_access`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` §6.5–6.6; `docs/superpowers/specs/2026-10-15-onboarding-and-transcript-friction-design.md` variant E. Depends on plan 3b (acceptance, student-entered values).

## Global Constraints

- Lint, types and tests as in plan 3b.
- **Never crosses tenants** (`.claude/rules/row-level-security.md`, "The rule for crossing tenants"): every audit row is in the student's own tenant; an owner auditing an agency's sample works inside that agency, and viewing the original is recorded like any staff file view (`StaffFileAccess`, owner decision 2026-10-11). **Correcting a student's record after a finding** is an edit, so it still follows the support-access rule in force (today a `SupportGrant`; the owner's 2026-10-14 "staff do everything" decision awaits its own design and is not assumed here).
- The audit table follows the tenant-table recipe (RLS, composite tenant guard) and has REDACT/KEEP entries; its verdict notes are personal data.
- Settings with env overrides: `TRANSCRIPT_AUDIT_RATE` (default `0.05`, 1 in 20 at launch, spec §6.5) and `TRANSCRIPT_AUDIT_ALWAYS_EDITS` (default `3`).

## Review Focus

1. **Sampling is random and reproducible in tests** — draw with `secrets.SystemRandom` in production and an injected chooser in tests; never by tenant or student order.
2. **A student-entered value that raises a credit total or a grade** is always audited (spec §6.6), whatever the rate.
3. **An agency counsellor** sees only their own agency's sampled readings and only for students they are assigned to; staff see direct students' samples.
4. **A finding never edits the record silently**: the correction is a separate, recorded action, and the student is told (spec §6.5).
5. **Erasure** removes audit verdicts with the student.

---

### Task 1: The audit record and the draw

**Files:**
- Modify: `apps/documents/models.py` (`TranscriptAudit`), new migration with the RLS block
- Modify: `apps/documents/transcript_check.py` (`accept` calls `maybe_sample(reading)`)
- Modify: `config/settings/base.py` (two settings)
- Modify: `apps/audit/redaction.py`
- Test: `tests/documents/test_transcript_audit.py` (new)

**Interfaces:**
- `TranscriptAudit(TenantScopedModel)`: `id`, `reading` OneToOne `TranscriptReading` (PROTECT), `student` FK `Membership`, `reason` ∈ {`sampled`, `many_edits`, `raised_value`}, `drawn_at`, `completed_at` (null), `auditor` FK `Membership` (null), `verdicts` JSON `{"<cell ref>": "correct"|"missed"|"flagged_fixed"|"flagged_confirmed_wrong"}`, `notes` text.
- `maybe_sample(reading, *, chooser=None) -> TranscriptAudit | None`.

- [ ] **Step 1: Failing tests**: with rate 1.0 every accepted reading is drawn; with rate 0 none is, except one with four student-entered values (`many_edits`) and one whose fix raised a grade (`raised_value`); REDACT covers `verdicts` and `notes`; another tenant cannot read the row (`rls_enforced_orm`).
- [ ] **Step 2: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents/test_transcript_audit.py` — FAIL.
- [ ] **Step 3: Implement** (migration RLS block copied from `documents/0026_transcript_pages_tenant_guards.py`, guards on `student_id` and `reading_id`).
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/documents tests/audit tests/tenancy` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): accepted readings are sampled into an audit" -- apps/documents/models.py apps/documents/migrations apps/documents/transcript_check.py config/settings/base.py apps/audit/redaction.py tests/documents/test_transcript_audit.py`

---

### Task 2: The audit page

**Files:**
- Create: an audit list and an audit page (counsellor side under the existing counsellor student views; staff side beside `_staff_files_page`), templates `counselor/transcript_audit_list.html`, `counselor/transcript_audit.html`
- Test: `tests/dashboard/test_transcript_audit_page.py`

**Interfaces:**
- List: open audits the viewer may see (assigned counsellor for agency students; `PLATFORM_ADMIN` in the platform tenant for direct students).
- Page: the original upload (through the existing recorded file view, `storage.admit`), and a table of every deciding cell — each course's credits, grade and in-progress status, and the four key numbers — showing the reader's value, the student's value where they answered, and a verdict select. Titles are not audited (spec §6.5). **Save** stores verdicts and `completed_at`.

- [ ] **Step 1: Failing tests**: the assigned counsellor sees and completes an audit; another counsellor gets 404; staff see a direct student's audit and not an agency student's; opening the original records a staff/counsellor file access.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `SHOULD BE DONE BY AYKHAN` on the side-by-side layout.
- [ ] **Step 4: Run** `POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q tests/dashboard tests/documents` — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): the audit page — the original beside the stored values, a verdict per cell" -- apps/dashboard/views.py apps/dashboard/urls.py templates/counselor/transcript_audit_list.html templates/counselor/transcript_audit.html tests/dashboard/test_transcript_audit_page.py`

---

### Task 3: What a finding does, and the numbers

**Files:**
- Modify: the audit page view (a **Correct the record** action, behind the support-access rule in force, that writes a new accepted value as `corrected_by_audit`, re-runs plan 3b's fact write, and posts the student a message "We corrected <course> on your transcript record: <old> → <new>")
- Create: `apps/documents/management/commands/transcript_audit_report.py` — per tenant and overall: audited count, missed per transcript, flagged-and-fixed, flagged-confirmed-wrong, and the share of audited transcripts with at least one missed value (spec §6.5's revisit trigger: more than about 1 in 20)
- Test: `tests/documents/test_transcript_audit.py`

- [ ] **Step 1: Failing tests**: correcting writes the new value beside the old (never overwrites the reader's), re-writes the EDUCATION fact, and sends the student one message; the report prints the missed-rate and flags it when above 5%.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `git commit -m "feat(transcript): an audit finding corrects the record openly; the missed-value rate is reported" -- apps/dashboard/views.py apps/documents/management/commands/transcript_audit_report.py tests/documents/test_transcript_audit.py`

---

### Task 4: Every gate

```bash
uv run ruff check .
uv run mypy apps config
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py check
POSTGRES_DB=elmify_letter_plan_2 uv run python manage.py makemigrations --check --dry-run
POSTGRES_DB=elmify_letter_plan_2 uv run pytest -q
```
