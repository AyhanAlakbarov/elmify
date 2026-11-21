# Elmify Staff Can View Any Student's Files, Every View Logged — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elmify's own staff (Membership role `PLATFORM_ADMIN`) can view AND download any student's files in any agency at any time, with no support grant. Every view and every download is recorded, and the records can be read.

**Owner decisions, 2026-10-11:**
- "Elmify staff may look at any student's files", with every view logged. This was chosen over a one-click support grant and over a Elmify-own-students-only rule.
- Staff may also download files. Every download is logged too, and the agency sees both.

**What this replaces:**
- **CLAUDE.md, "The rule for crossing tenants" #2:** today it says a person's data never crosses tenants, and a platform admin takes a `SupportGrant`. That rule becomes: a platform admin may VIEW any student's files without a grant, and every view is audited.
- **`docs/runbooks/support-access.md`:** "there is no permanent support admin role" no longer holds for file viewing.
- **Support grants remain for everything else:** editing, acting for a student, and reading other personal data.

**Architecture:**
- **No new database privilege.** Staff work on each agency's own site, as they already do for support. They need a `PLATFORM_ADMIN` membership in that agency, and every request runs under that agency's tenant (RLS unchanged, no `BYPASSRLS`, no widened policy).
- **What changes is the application rule.** The pages and file routes that today admit "the student, or an assigned counsellor or owner" also admit a `PLATFORM_ADMIN` for any student of that agency. Every such file view first writes an audit record, and the file is served only after the record is stored.
- **View and download.** Staff get the inline view counsellors have, plus a download: the same bytes with `Content-Disposition: attachment`. Counsellors stay view-only. A download is audited exactly like a view, as event `staff.file_downloaded`.

## Global Constraints
- **The audit record comes first.** A view or download is served only if its audit record was written. A failed write means 404 and no bytes.
- **What a record holds:** who (the staff membership), which student, which document (kind and id), when, and the agency. It never holds file content or a filename.
- **Two places a view is recorded:**
  - an `AuditEvent` in the agency (`actor_kind=HUMAN`, `event="staff.file_viewed"` or `"staff.file_downloaded"`), shown on the agency owner's console, so the agency can see Elmify looked;
  - a structured log line `StaffFileView action=view|download tenant=<id> staff=<id> student=<id> document=<kind>:<id>`, so `manage.py staff_file_views` and a CloudWatch metric can list them across all agencies.
- **No new cross-tenant read path in the database.** Every query stays under the agency's tenant GUC. The cross-agency list comes from the logs, never from a widened policy.
- **Paused students:** a student who requested deletion or stopped processing is not viewable by staff either. This matches the counsellor rule and PR #192's answers page.
- **Erasure:** an `AuditEvent` row survives erasure as today, with the student id and no name. The log lines expire with the log group's retention.
- **The privacy notice and the agency data-processing agreement must say Elmify staff can view and download files.** This plan drafts the wording. A lawyer reviews it before it is published as a new notice version. Publishing the new notice version is the owner's step.
- **Repo commands:**
  - `uv run ruff check .` (never `ruff format`);
  - `uv run mypy apps config`;
  - `POSTGRES_DB=elmify_copilot_docprep uv run pytest -q <paths>`;
  - `uv run python manage.py makemigrations --check --dry-run`.
- **Worktree:** `/home/orkhan/Desktop/copilot-docprep`, branch `claude/copilot-document-prep`. Use `git -C` and absolute paths. Never `git stash`, never push.

## Review Focus
1. **Staff of agency A open a student of agency B by changing the URL:** 404. The view runs under A's tenant, so B's rows do not exist there. A test proves this through `rls_enforced_orm`.
2. **The audit write fails (database error):** no bytes are served, and the response is a 404.
3. **A `PLATFORM_ADMIN` views a file:** the agency owner's console lists the view, and `manage.py staff_file_views --since 1d` lists it with the agency id.
4. **A counsellor without an assignment, or a counsellor asking for a download:** still 404. Only `PLATFORM_ADMIN` gains anything, and only staff can download.
5. **A paused student:** 404 for staff too.

---

### Task 1: The rule — staff may view, audited
**Files:**
- Modify: `apps/documents/storage.py`: next to `may_read_student`, add `staff_may_view(membership, student) -> bool`. It is True when `membership.role == PLATFORM_ADMIN`, in the same tenant, and the student is not paused.
- Create: `apps/audit/staff_access.py`: `record_staff_access(staff, student, *, action, kind, document_id) -> None`, where `action` is `"view"` or `"download"`. It writes the AuditEvent inside `tenant_transaction` and logs the `StaffFileView` line, raising if the write fails.
- Modify: `apps/portals/views.py::prepared_view`:
  - let PLATFORM_ADMIN through via `staff_may_view`, keeping COUNSELOR/OWNER via assignment;
  - call `record_staff_view` before reading the bytes; on failure, respond 404.
- Modify: `apps/documents/storage.py::download_document`: a PLATFORM_ADMIN downloads any student's draft of the agency via `staff_may_view` instead of an assignment, and each download is recorded with `record_staff_access(action="download")` first. This closes today's gap, where an assigned admin downloaded with no record.
- Create:
  - `draft_view` (approved draft) and `upload_view` (AVAILABLE, not retired): inline, for staff and assigned counsellors.
  - `staff_download` variants of the prepared and upload routes: attachment, staff only. They reuse `apps/portals/http.py::inert_response`.
  - Inline routes share the prepared view's headers: `inline`, `nosniff`, `no-store`, and CSP `default-src 'none'; img-src 'self'; object-src 'self'; frame-ancestors 'none'`.
  - Every refusal is a 404, and every staff response is recorded first.
- Tests: `tests/portals/test_staff_file_access.py` covering every Review Focus line, and the RLS cross-agency case through `rls_enforced_orm`.

### Task 2: Staff see every student of the agency on the counsellor pages
**Files:**
- Modify: `apps/dashboard/views.py`: the counsellor student list and student board admit a PLATFORM_ADMIN for any student of the agency, not only assigned ones. The board's "Prepared files" section and each documents-table cell get "View" links (draft, upload, prepared) for staff and assigned counsellors. Staff also get "Download" links; counsellors get none.
- Read-only: staff get no write actions on those pages (upload, offers, messages stay counsellor-only). Test that each POST returns 404 for a PLATFORM_ADMIN.
- Tests in `tests/dashboard/`.

### Task 3: The records can be read
**Files:**
- Modify: `apps/audit/views.py` (the owner console): a "Elmify staff views" list for the agency owner, showing date, staff member and document kind (no student name, as `deletion_console` does).
- Create: `apps/audit/management/commands/staff_file_views.py`: `--since 1d|7d|<date>`. It reads the `StaffFileView` log lines from CloudWatch Logs (`WebLogGroup`), or from a local file in dev, and prints tenant, staff, student id, document and time.
- Modify: `infra/template.yaml`: a metric filter `StaffFileViews` on the literal `StaffFileView`, with no alarm (views are expected now). Pin it in `tests/infra/test_template.py`.
- Tests: the console list, the command against a fixture log, and the infra pin.

### Task 4: Rules, runbook and legal wording
**Files:**
- Modify: `CLAUDE.md`, "The rule for crossing tenants": record the owner decision of 2026-10-11 and the new rule (staff may view any file, view only, audited first; support grants still cover everything else). Keep the reasoning for why widening database policies stays ruled out.
- Modify: `docs/runbooks/support-access.md`: add the staff-view exception and how to read the records.
- Modify: `docs/legal/2026-10-03-agency-data-processing-agreement.md` and draft a new privacy-notice version under `apps/privacy/legal/`. The new notice is a draft, not activated. Wording: "Elmify's own support staff can view and download your documents to help with your application; every view and download is recorded and your agency can see it." Mark both for lawyer review.
- No tests (docs). Run `uv run pytest tests/privacy -q` to confirm the draft notice is not picked up as a published version.
