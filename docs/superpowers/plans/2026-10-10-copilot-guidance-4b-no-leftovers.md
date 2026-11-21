# Co-pilot Guidance 4b — Plan 4 With Nothing Left For Later — Implementation Plan

> Note (2026-10-11): staff view and download of files without a grant is covered by `docs/superpowers/plans/2026-10-11-staff-file-access.md`; where this plan says counsellor-only or grant-required, that plan supersedes it for platform staff.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every item plan 4 deferred, plus the owner's two additions of 2026-10-10:
- **Counsellors:** they can see a student's prepared files without a download.
- **Naming:** a programme's file-naming rule ("Name_Surname_CV") is applied from the student's own confirmed name.

**Architecture:** Each task extends what plan 4 built on `claude/copilot-document-prep`.
- **Big bundles (Task 1):** a whole-application bundle that would be over 4 MB is compressed to fit 4 MB, never below 150 dpi. If it still cannot fit, it is refused with a reason, and refusals are counted. There is no cloud change.
- **Deleting replaced copies (Task 3):** a replaced prepared copy is deleted under a delete grant narrowed to `tenants/*/students/*/prepared/*`. Owner-approved.

Everything else is application code.

**Tech Stack:** Django 5.2 / Python 3.14, the `ocr/` parser (Python 3.12, Pillow, pypdf, pypdfium2), CloudFormation (`infra/template.yaml`, pinned by `tests/infra/test_template.py`), TypeScript (extension), pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-09-copilot-on-page-guidance-design.md` §7, D4, §10. Plan 4: `docs/superpowers/plans/2026-10-09-copilot-guidance-4-document-prep.md` ("Owner decisions, 2026-10-09"). File-name extraction itself belongs to the engine (verified-catalog spec §3.5, commit 1398bba0, elmify-3d / elmify-82). This plan only keeps the grammar reader's fallback consistent with it.

## Owner decisions, 2026-10-10
- Nothing from plan 4 is left for later.
- **Old prepared copies are deleted as soon as they are replaced**, under a delete permission limited to prepared copies (Task 3).
- **Bundles over 4 MB are compressed to fit 4 MB.**
  - Compression never goes below 150 dpi.
  - A bundle that still does not fit tells the student to upload the documents separately, and the refusal is counted.
  - The one-file write permit and response streaming were compared and not chosen:
    - the permit needs a cloud change and a new write path from the isolated parser;
    - streaming needs a custom Python runtime, and transfers over 6 MB run at a capped speed;
    - only one measured programme (R-008) asks for a bundle at all.
  - Revisit only if counted refusals appear.
- Counsellors can read a student's files to see them, but get no download.
- File-naming requirements such as `name_surname_CV` are extracted by the engine (elmify-3d confirmed, spec §3.5). Prepared files use them once the engine's set is certified, and the grammar reader's fallback until then.

## Global Constraints
- Everything in plan 4's Global Constraints still binds, verbatim:
  - Uploads are transformed only in the isolated parser.
  - What fits is served byte for byte.
  - A signed PDF is never rewritten.
  - A rule nobody wrote changes nothing.
  - Sizes are decimal.
  - Values come from the page.
  - Filenames are `^[A-Za-z0-9._-]{1,100}$`.
  - Tenant tables get RLS, guards and redaction.
  - The web tier reads no catalogue.
- **The parser never holds an S3 write grant** (unchanged). Every prepared result comes back in the Lambda answer, at most 4,000,000 bytes.
- **Compression floor:** a page image is never scaled below 1,650 px on its long side (about 150 dpi on A4) to meet a cap.
- **A counsellor can see a file but gets no download link.** The view responds `inline` with `Cache-Control: no-store`. Only a counsellor with an active `CounselorAssignment` to the student may view. **Limit, stated to the owner:** a browser can always save what it displays. "No download" means the platform offers none; it cannot stop a counsellor's own browser.
- **Names are never guessed.** `{surname}` and `{given_name}` come only from confirmed IDENTITY facts the student gave on the dashboard. `{full_name}` comes from `full_name`.
- **A job failure is not an outage:**
  - A Lambda timeout, out-of-memory or other function error on ONE job marks that job `CANNOT_FIT` / `timed_out`, and the run continues.
  - A transport failure (throttling, connection, permissions) stops the run, as before.
- Repo commands:
  - `uv run ruff check .` (never `ruff format`);
  - `uv run mypy apps config`;
  - `POSTGRES_DB=elmify_copilot_docprep uv run pytest -q <paths>`;
  - `uv run python manage.py makemigrations --check --dry-run`;
  - `uv run --project ocr pytest ocr -q`;
  - `npm --prefix extension run check`;
  - `uv run pytest tests/portals/test_extension_e2e.py -m extension -q`;
  - `uv run pytest tests/infra -q`.
- Worktree `/home/orkhan/Desktop/copilot-docprep`, branch `claude/copilot-document-prep`. Use `git -C` for git, and absolute paths everywhere. Never `git stash`, never push.

## Review Focus
1. **A replaced prepared copy whose delete fails** (S3 error): the new file is still served, a warning is logged, and erasure's prefix purge remains the backstop (Task 3).
2. **A 9 MB bundle under a 10 MB rule (R-008):** it is compressed to at most 4 MB at no less than 150 dpi, and served. If it cannot fit, the student is told to upload separately (Task 1).
3. **One job times out and the next is fine:** the first is `timed_out`, the second is prepared, and the run does not stop (Task 2).
4. **A student with a bachelor's and a master's diploma, under "all diplomas as one PDF":** both are merged in upload order. A re-upload with REPLACE retires only the one it replaces (Task 6).
5. **An unassigned counsellor, a counsellor of another tenant, or a student opening the counsellor view URL:** 404 for each (Task 4).

---

### Task 1: A bundle over 4 MB is compressed to fit, never below 150 dpi, and refusals are counted

**Files:**
- Modify: `apps/portals/prepare.py`:
  - **Cap:** the target sent to the parser uses `min(rule.max_bytes or ∞, PARSER_RETURN_MAX)` for every job. `PARSER_RETURN_MAX = 4_000_000` is imported from `apps/documents/ocr.py`'s existing constant.
  - **Why:** a bundle whose page cap (e.g. 10 MB) is above what the parser can hand back is shrunk to fit what it can hand back, instead of being refused unshrunk.
  - **Refusals:** each `CANNOT_FIT` is logged once at info as `prepare.refused reason=<code> document=<kind> application=<id>`, so refusals can be counted. No student value is logged.
- Modify: `ocr/read_pages.py`: the JPEG step table never goes below a long side of 1,650 px. `_JPEG_STEPS = ((2400, 85), (2000, 75), (1650, 70), (1650, 60), (1650, 50))`. Below that, `too_large`.
- Modify: `NOTE_TEXT` and i18n for `too_large_to_return` and `too_large`: "We could not make this small enough without making it hard to read. Upload the documents separately, or check the portal's size limit."
- Test: `ocr/test_read_pages.py`, `tests/portals/test_prepare.py`.

- [ ] **Step 1: Failing tests.**
  - A bundle job under a 10 MB rule sends the parser `max_bytes == 4_000_000` (Review Focus 2). A 2 MB rule still sends 2,000,000.
  - A large smooth scan is shrunk to a long side of at least 1,650 px and comes in under the cap.
  - An incompressible input that cannot fit at 1,650 px / q50 is refused `too_large`.
  - A refusal logs one `prepare.refused` line.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run (ocr suite, portals prepare tests); expect PASS.**
- [ ] **Step 5: Commit** `prepare: a bundle over 4 MB is compressed to fit, never below 150 dpi; refusals are counted`.

### Task 2: A failed job is not an outage; parser odds and ends

**Files:**
- Modify: `apps/documents/ocr_errors.py`: `OcrUnavailable` gains `kind: Literal["outage", "job"] = "outage"`.
- Modify: `apps/documents/ocr.py`:
  - `_invoke_event` maps a `FunctionError` whose `errorType` is `Sandbox.Timedout`, `Runtime.OutOfMemory`, `Runtime.ExitError` or any other function-side error to `OcrUnavailable(kind="job")`, and a botocore or transport error to `kind="outage"`.
  - `prepare_files` refuses an upload part whose row is not `AVAILABLE` in Lambda mode too (the deferred T5 minor): `Prepared(refused="unreadable")`.
- Modify: `apps/portals/prepare.py`: a `kind="job"` error writes `CANNOT_FIT` / `timed_out` for that slot and continues; `kind="outage"` stops the run as now. Add `timed_out` to `NOTE_TEXT`: "Preparing this file took too long, so we left it as it is."
- Modify: `extension/src/panel/i18n.ts`: `n_timed_out` in az/tr/ru/en.
- Modify: `ocr/read_pages.py`:
  - the module docstring lists every refusal reason (deferred T4 minor);
  - a part whose base64 does not decode answers `{"refused": "unreadable"}` instead of raising (deferred T4 minor);
  - the `--prepare` stdin limit is `MAX_PARTS * MAX_BYTES * 4 // 3 + 1_000_000` (final-review M3).
- Test: `tests/documents/test_ocr_prepare.py`, `tests/portals/test_prepare.py`, `ocr/test_read_pages.py`, the extension i18n test.

- [ ] **Step 1: Failing tests.**
  - Three jobs where the second raises `kind="job"`: the first and third are READY and the second is `CANNOT_FIT` / `timed_out` (Review Focus 3).
  - A raise with `kind="outage"` after the first job stops the run.
  - A Lambda `FunctionError` payload `{"errorType": "Sandbox.Timedout"}` maps to `kind="job"`; a `ClientError` maps to `kind="outage"`.
  - A non-AVAILABLE upload part gives `refused="unreadable"`.
  - Bad base64 gives `refused="unreadable"`.
  - Every `NOTE_TEXT` code has four panel strings.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement as described.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit** `prepare: a job that times out is recorded and skipped; an outage still stops the run`.

### Task 3: A replaced prepared copy is deleted, and so are rows for slots no longer wanted (owner-approved 2026-10-10)

**Files:**
- Modify: `infra/template.yaml`:
  - `DocumentWorkerTaskRole` adds `s3:DeleteObject` and `s3:DeleteObjectVersion` on `${EvidenceBucket.Arn}/tenants/*/students/*/prepared/*` and nothing wider.
  - Its comment says why: these are the platform's own derived copies. Erasure of everything else stays WorkerTaskRole's.
- Modify: `tests/infra/test_template.py`: pin the exact resource, and pin that no other delete was added to the role.
- Modify: `apps/research/storage.py`: `S3ObjectStore.delete_version(key, version_id)`.
- Modify: `apps/portals/models.py`: `PreparedDocument.object_version = CharField(max_length=1024, blank=True)`. Add a migration, and add the field to the redaction KEEP list.
- Modify: `apps/portals/prepare.py`:
  - **Store:** after the new row is written, `delete_version(old_key, old_version)` for the slot's previous object. `store_prepared` returns the version id.
  - **Sweep:** at the end of a run, rows whose slot is no longer in `jobs_for(application)` are deleted together with their object version.
  - **Failure:** a delete failure logs a warning and never fails the run. The erasure prefix purge remains the backstop.
- Test: `tests/portals/test_prepare.py`, `tests/infra/test_template.py`

- [ ] **Step 1: Failing tests.**
  - Re-preparing a slot removes exactly the old version from a fake store, and keeps the new one.
  - A slot dropped from the rules (rules re-read with no CV rule) loses its row and its object.
  - A delete that raises leaves the run READY and logs at warning.
  - The infra pins.
- [ ] **Steps 2–5:** run (FAIL), implement, run (PASS), commit `prepare: replaced and unwanted prepared copies are deleted under a prepared-only grant`.


### Task 4: Counsellors view prepared files, without a download

**Files:**
- Modify: `apps/portals/views.py`: `prepared_view(request, prepared_id)`, routed at `prepared/<uuid:prepared_id>/view` with name `portals-prepared-view`. It:
  - requires a logged-in membership with `role in (COUNSELOR, OWNER)` and an active `CounselorAssignment` to the row's student. This is `documents.storage._may_read`'s rule, so reuse it, extracting it to a shared helper if needed.
  - requires the row to be READY and current (`current_prepared`).
  - answers with the bytes and `Content-Disposition: inline`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, and `Content-Security-Policy: default-src 'none'; img-src 'self'; object-src 'self'`.
  - **Check in Playwright** that Chromium renders a PDF under that CSP. Chrome refuses a PDF under `sandbox`, which is why this route does not use `inert_response`.
  - returns 404 for every refusal.
- Modify: `templates/counselor/student_board.html`, or the partial it includes for applications: for each application, list its READY prepared files by kind label, with a "View" link to `portals-prepared-view`. Show no download link. Show `note_text` where present.
- The student's own download route (`portals-prepared-download`) is unchanged.
- Test: `tests/portals/test_prepared_serving.py`, plus one Playwright check in the e2e suite (or a page test) that the counsellor page renders the file inline.

- [ ] **Step 1: Failing tests.**
  - An assigned counsellor gets 200, `inline`, `no-store`, and no `attachment`.
  - An unassigned counsellor of the same tenant gets 404.
  - A counsellor of another tenant gets 404.
  - The student gets 404 on this route; they keep their own download route.
  - A stale row gets 404.
  - The counsellor board lists the file with a View link and no download link (Review Focus 5).
- [ ] **Steps 2–5:** run (FAIL), implement, run (PASS), commit `portals: counsellors view prepared files inline; no download is offered`.

### Task 5: Surname and given name are collected on the dashboard and fill the naming rule

**Files:**
- Modify: `apps/documents/schemas.py`: `PersonalInformation` gains optional `surname` and `given_name` (`max_length=100` each). Modify `apps/documents/verification.py` so the IDENTITY payload keys include them. They are never compared against `full_name`.
- Modify: `apps/documents/gaps.py`:
  - **Kind:** `Kind.NAME_PARTS`, asked by a new `name_parts(student)` builder (added to `gap_questions` after `missing_contact`).
  - **When:** only when an open application's `kit_file_rules` holds a `name_pattern` using `{surname}` or `{given_name}` and the confirmed IDENTITY fact lacks that part.
  - **Wording:** one question per missing part, asked exactly as on the passport: "Your surname exactly as in your passport (Latin letters)." and "Your given name(s) exactly as in your passport."
  - **Answer:** it supersedes the IDENTITY fact with the part added, through the existing `answer_questions` path. The answer is the student's own and is stored confirmed, as other gap answers are.
- Modify: `apps/portals/prepare.py::file_name`: fill `{given_name}` from the fact, and `{surname}` as now.
  - Keep `name_needs_surname` when the needed part is still missing. Rename it `name_needs_name_parts`, and update `NOTE_TEXT`, i18n and the kit wording: "The programme wants your name in this file's name — add your surname and given name on your profile."
  - After a NAME_PARTS answer, call `queue_for_student`.
- Modify: `apps/documents/grammar_values.py::name_pattern`: a bare "Name" token beside a surname placeholder becomes `{given_name}`, matching engine spec §3.5. Alone, it stays `{full_name}`. This settles plan 4's deferred T1 minor.
- Test: `tests/documents/test_gaps.py`, `tests/portals/test_prepare.py`, `tests/documents/test_grammar_values.py`.

- [ ] **Step 1: Failing tests.**
  - A student with only `full_name`, applying to a programme whose rule is `{given_name}_{surname}_CV.pdf`, gets two NAME_PARTS questions.
  - Answering them yields a confirmed IDENTITY fact with both parts, and the next `jobs_for` filename is `Aysel_Memmedova_CV.pdf` (ASCII-folded).
  - A student whose programmes need no name parts gets no NAME_PARTS question.
  - `name_pattern("Name_Surname_CV.pdf") == "{given_name}_{surname}_CV.pdf"` and `name_pattern("Name_CV.pdf") == "{full_name}_CV.pdf"`.
- [ ] **Steps 2–5:** run (FAIL), implement, run (PASS), commit `documents: the dashboard asks for surname and given name when a programme's file name needs them`.

### Task 6: Several diplomas or transcripts per application (rare, supported)

**Files:**
- Modify: `apps/concierge/models.py`: `DocumentVersion.retired_at = DateTimeField(null=True, blank=True)`. Add a migration and classify it in redaction KEEP.
- Modify: `apps/concierge/documents.py::register` and both upload doors (`apps/documents/api.py`'s student door, `apps/dashboard/views.py::upload`): non-transcript kinds accept `mode` in `REPLACE | ADD`, defaulting to `REPLACE`, which is today's behaviour.
  - When the new upload is promoted (`document_worker`, after `promote_upload`), REPLACE sets `retired_at` on the student's older AVAILABLE rows of the same kind.
  - ADD retires nothing.
  - Transcripts keep `register_transcript`'s own ADD / REPLACE / RETAKE. Check whether its REPLACE already retires the older DocumentVersion, and make it set `retired_at` if not.
- Modify: `apps/documents/table.py`:
  - `table_for` drops retired rows.
  - New `Table.held_all_for(kind, application_id) -> tuple[Held, ...]` returns every usable entry for the cell: the application's own entries if any, else the general ones.
  - `held_for` stays the first of them, so existing callers are unchanged.
  - `sendable` accepts any entry `held_all_for` returns.
- Modify: `apps/portals/prepare.py::_held`:
  - Use `held_all_for`.
  - **Several of one kind:** with `rule_for(...).one_file`, they become ONE job, slot = the document kind, with sources in upload order (oldest first) and filename `{document}.pdf` through `file_name`. Without it, one job each, as now.
  - **Bundle:** includes every held entry.
- Modify: the dashboard documents UI (`templates/student/_documents.html`, `static/dashboard/documents.js`): when the student already holds a DIPLOMA or LANGUAGE_CERTIFICATE, the upload button offers "Replace" (default) and "Add another (e.g. a second degree)". The cell shows a count when there are several.
- Test: `tests/documents/test_table.py`, `tests/portals/test_prepare.py`, the upload-door tests, plus a page test for the two buttons.

- [ ] **Step 1: Failing tests.**
  - Two AVAILABLE diplomas added with ADD both appear in `held_all_for`. Under a DIPLOMA ONE_FILE rule they form one job with both sources, oldest first.
  - A REPLACE upload retires exactly the older diploma once promoted (Review Focus 4).
  - A REPLACE upload still being checked retires nothing.
  - Without ONE_FILE there are two jobs.
  - `sendable` accepts both.
  - The bundle includes both.
  - Existing `held_for` tests are unchanged.
- [ ] **Steps 2–5:** run (FAIL), implement, run (PASS), commit `documents: a student can hold several diplomas; a programme's one-PDF rule merges them`.
- Tell `elmify-15` (the student dashboard session) about `retired_at` and `held_all_for` when this lands.

### Task 7: The rest of plan 4's deferred minors

**Files and changes:**
- **Thousands separator:** in `grammar_values.size_bytes`, a comma followed by exactly three digits and then a unit, with no other decimal mark, is a thousands separator: "10,000 KB" is 10,000,000 bytes. "1,5 MB" stays a decimal comma. (Plan 4 T1 minor.)
- **Overflow log:** `derive.candidates`' overflow warning says how many dropped lines were file-only. (T2 minor.)
- **Wording:** the `active_content` sentence (`NOTE_TEXT` and i18n) becomes: "This file contains active content (scripts or links that run on opening), so we did not change it; it is sent as you uploaded it." (T7 minor.)
- **Term matching:** extension `KIND_TERMS` matching gains a trailing word boundary, so "cv" no longer matches "cvs". (T8 minor.)
- **No-kind fallback:** a document with no kind uses the same exclusive classification as kinds (a box matching its filename terms and no kind's terms), instead of first-match-wins. (T8 minor.)
- **Europass trigger:** the Europass worker calls `queue_for_student` after storing a render. (T6 minor.)
- **Kit links (final-review note):** when a bundle is refused, the kit links each original upload with its own download, not only the CV. Add a student route for an upload's clean copy if none exists, with the same 404-for-every-refusal rule.
- **No change, recorded:** a file-only page with no provider writes `cv_constraints` / `cv_directives` empty, exactly as a page with no candidates does. It is the truthful result for a page whose CV lines are gone.
- Tests: one per item, in the module that owns it.
- [ ] **Steps 1–5:** failing tests, run (FAIL), implement, run (PASS), commit `documents, extension: plan 4's remaining minors`.
