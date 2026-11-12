# Runbook: support access

Platform-admin access to a tenant's data, except the staff file access described below, goes through
`apps.tenancy.services.require_active_support_grant` and the
`SupportGrant` model (`apps/tenancy/migrations/0006_platform_admin_and_support_grant.py`),
surfaced at `admin_support_grant` (`apps/concierge/views.py`). Every grant
is a time-bounded, auditable exception to normal tenant isolation — not a
standing permission.

## Exception: staff file access (owner decision, 2026-10-11)

Elmify staff (Membership role `PLATFORM_ADMIN`) may **view and download** any student's files in an
agency without a support grant. Counsellors remain view-only. Every view and download is recorded
first (`apps/audit/staff_access.py::record_staff_access`): a `StaffFileAccess` row
that the agency owner sees, and a `StaffFileView` log line. Editing, acting
for a student and any other personal data still need a grant. The database wall is unchanged: staff
work inside each agency's own site; no `BYPASSRLS`, no widened policy.

**Only Elmify creates a `PLATFORM_ADMIN` membership** (Django admin or a management command).
No agency owner, counsellor or invitation may ever create or grant one: that role sees every
active student's files in its agency without a grant.

How to read the records:

- Agency owner console (`/owner/deletions/`): the staff-views list reads `StaffFileAccess` and shows when,
  which staff member and what kind of document (action and kind, never a student name or filename).
- Across agencies: `manage.py staff_file_views --since 1d --log-group /elmify/app/<stack>/web`
  (`WebLogGroup` in `infra/template.yaml`; no task sets `WEB_LOG_GROUP`, so pass the group). It
  reads the log lines, which CloudWatch keeps **30 days** (`RetentionInDays: 30`). The
  `StaffFileAccess` rows are kept in the database with no expiry and survive a student's erasure
  (they carry no name), so for anything older read the owner console or the table.
- CloudWatch metric filter `StaffFileViews` on the web log group. It has no alarm: routine support
  use is expected, so review the list rather than act on each line.

## Alarm

`SupportGrantAlarm` (`Elmify/App SupportGrantsUsed`, filtered from
`WebLogGroup` on the literal `"SupportGrant"`) fires on any evaluation
period with at least one match. Support access should be rare enough that
every firing gets looked at, not tuned into silence.

## On alarm

1. Identify which tenant and which platform admin from the app's
   `SupportGrant` table (`starts_at`, `tenant_id`, `granted_to`) for the
   alarm's time window.
2. Confirm the grant has a linked justification/ticket. If it doesn't,
   treat it as unauthorized access and escalate immediately — do not wait
   for the grant to expire.
3. If justified, confirm the grant's scope and duration match what was
   requested; support access should default to the shortest duration that
   accomplishes the task.
4. Cross-reference `CrossTenantDenialAlarm` and `ApprovalBypassAlarm` for
   the same time window — a support session that also triggers those is
   higher-priority to review.

## Principles

- `PostgreSQL RLS is secondary defense`: `require_active_support_grant`
  denies at the application layer first; RLS (and the runtime role's
  `NOBYPASSRLS`, see `scripts/create_runtime_role.sql`) is the backstop if
  that check is ever bypassed. Never grant the runtime Postgres role
  `BYPASSRLS` as a shortcut for support access — use a grant instead.
- Support grants are tenant-scoped and time-bounded by construction. The
  only standing staff power is the audited file view and download above;
  nothing else is permanent. If a recurring need
  keeps generating grants, that is a product gap to fix, not a reason to
  widen the grant.
