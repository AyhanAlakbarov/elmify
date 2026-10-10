# Runbook: support access

Platform-admin access to a tenant's data goes through
`apps.tenancy.services.require_active_support_grant` and the
`SupportGrant` model (`apps/tenancy/migrations/0006_platform_admin_and_support_grant.py`),
surfaced at `admin_support_grant` (`apps/concierge/views.py`). Every grant
is a time-bounded, auditable exception to normal tenant isolation — not a
standing permission.

## Alarm

`SupportGrantAlarm` (`Tehsil/App SupportGrantsUsed`, filtered from
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
- Support grants are tenant-scoped and time-bounded by construction; there
  is no "permanent support admin" role in this system. If a recurring need
  keeps generating grants, that is a product gap to fix, not a reason to
  widen the grant.
