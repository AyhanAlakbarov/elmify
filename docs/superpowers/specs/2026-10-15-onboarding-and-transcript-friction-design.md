# Onboarding and transcript check: friction findings and the variants chosen

**Date:** 2026-10-15
**Status:** approved by the owner in conversation, 2026-10-15 ("YES" to writing the plans)
**Amends:** `docs/superpowers/specs/2026-10-03-transcript-reader-redesign-design.md` §6.3–6.4
(the summary screen) and the onboarding questionnaire (`apps/accounts/`).
**Evidence:** `docs/superpowers/research/2026-10-04-end-user-confirmation-of-low-confidence-fields.md`
(comparable products, partial-highlighting risk, do/don't), not repeated here.

## 1. What a student meets today (measured on `master` ad38ed14)

- **Five answers are raw JSON text boxes** (`apps/accounts/forms.py`, `_JSON_VALUES`):
  `academic_history`, `language_evidence`, `application_budget`, `self_funding_capacity`,
  `budget_stretch`. No student can fill them in.
- **A fast student hits the worst path.** `academic_history` is pre-filled only if the transcript
  reading has finished (`consultation.prefill_from_latest_reading`); otherwise it is the JSON box,
  and a reading that finishes later is never offered (a filled answer is left alone).
- **The transcript cannot be checked.** The review page
  (`templates/student/_consultation_step.html`) prints the record through the `answer` filter as one
  run-on line, every course in it; no answer has a "Change" link; the reader's doubts
  (`ConsultationDraft.highlights`) are stored and never shown; the pre-filled question is skipped.
- **Accepting the transcript is bundled with "Confirm and start research"** and the payment check.
- **A transcript cannot be uploaded from the documents page at all.** `static/dashboard/documents.js`
  never sends `role` (original or translation), and `transcript_pages._transcript_upload` refuses
  that with 400 `invalid_role`.
- **The draft lives in the login session** (`consultation.read_draft/write_draft`), so a student who
  signs in on another device starts over.

The transcript spec's own design (§6.3: four numbers, only the doubtful cells, crop + reason,
matches / fix / can't read, no "confirm all") matches the best comparable products; it was never
built.

## 2. Variants chosen (owner, 2026-10-15)

| # | Variant | Plan |
|---|---|---|
| 1 | The five JSON boxes become plain fields: money as amount + currency; the degree as a short form (university, country, degree, field, grade, grading scale, dates); up to three language-evidence rows. Courses are never typed. | Onboarding plan |
| 2 | Never wait for the reading: the short degree form is always available; a reading that finishes later is offered on the review page ("Your transcript has been read — use it?") and, once the profile exists, by the transcript check. | Onboarding plan; transcript plan 3 |
| 8 | The questionnaire draft is stored on the server per student, not in the session. | Onboarding plan |
| — | The documents page sends original or translation, so a transcript can be uploaded. | Onboarding plan |
| B | The transcript check is its own step, accepted on its own, never bundled with starting the search or payment. | Transcript plan 3 |
| 3 | One tap when nothing is doubtful: "We read N courses, X credits, average Y. Looks right? [Yes] [Something's wrong]". | Transcript plan 3 |
| 4 | One doubtful cell per card: crop of the original cell, the value, the reason in words, *matches / fix / can't read*; nothing pre-selected, no "confirm all". | Transcript plan 3 |
| 7 | "Something's wrong" and "can't read" never block: the reading is marked for a person (the counsellor for agency students, staff for direct students) and the student carries on. | Transcript plan 3 |
| D | Courses become confirmed facts only when the student accepts the transcript check — never at the questionnaire's Confirm. | Transcript plan 3, consumed by letter plan 2 |
| E | The audit sample (transcript spec §6.5). | Transcript plan 4 |
| 5 | Confirm a grade when a letter is about to quote it. | Letter plan 3 (story) |
| 6 | Pre-fill nationality and date of birth from the passport reader, language evidence from the transcript's medium of instruction. | After `claude/fact-reading-design` merges |

## 3. Order

1. Onboarding plan (1, 2, 8): removes the dead ends for every student, transcript or not.
2. Transcript plan 3a: where each cell came from, and crops of the doubtful ones (nothing records a cell's position today).
3. Transcript plan 3b (B, 3, 4, 7, D): the check, and courses into the ledger.
4. Transcript plan 3c: the point–letter and page-completeness checks (spec §6.1).
5. Transcript plan 4 (E): the audit.
6. Letter plan 2 then consumes the course facts plan 3 writes.

## 4. Limits stated

- Variant 5 has no published product precedent; it is a design inference.
- Screens are Aykhan's (`frontend-work-belongs-to-aykhan`): behaviour ships on today's plain-HTML
  pages with a `SHOULD BE DONE BY AYKHAN` note where the presentation matters.
