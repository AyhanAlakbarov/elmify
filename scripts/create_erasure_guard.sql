-- The cross-tenant erasure guard: one role, one function, one boolean.
--
-- Run this as a database admin AFTER migrations, once per environment
-- (docs/runbooks/deploy.md). It is deliberately not a Django migration:
-- tehsil_erasure_guard needs BYPASSRLS, only a role that already has BYPASSRLS
-- may create one with it, and the migration role has neither. A migration that
-- tried would pass every local check -- CI and developer databases migrate as a
-- superuser -- and fail at deploy.
--
-- Keeping it here also keeps the migration role out of it. Transferring the
-- function's ownership from a migration would require GRANT tehsil_erasure_guard
-- TO tehsil_migration, and that grant is one `SET ROLE` away from full
-- cross-tenant read for whoever holds the migration password.
--
-- Why the function exists at all: apps/audit/identity.py must ask "does this
-- person still hold an active membership at ANY agency?" before scrubbing a
-- login. tenancy_membership is FORCE ROW LEVEL SECURITY on app.tenant_id, which
-- applies to the table owner too, so no ordinary query and no owner-owned
-- definer function can answer it. Measured 2026-09-09; see
-- docs/superpowers/specs/2026-09-09-identity-erasure-design.md.

-- PRIVILEGES THIS SCRIPT REQUIRES of the role running it, which is not the
-- application's own migration or runtime role:
--   * CREATE ROLE ... BYPASSRLS -- which only a role that already has BYPASSRLS
--     may do, and which is the whole reason this is not a migration;
--   * SET ROLE to tehsil_erasure_guard, for ALTER FUNCTION ... OWNER TO;
--   * GRANT SELECT on public.tenancy_membership, a table owned by the migration
--     role -- so ownership of it, grant option on it, or superuser.
-- A local superuser has all three. **An RDS master user is not a superuser**,
-- and whether it has all three has NOT been verified against a real instance --
-- nothing is deployed yet. Verify before the first production run; the whole
-- script is one transaction, so a shortfall fails loudly and changes nothing.

\set ON_ERROR_STOP on

BEGIN;

-- Ordering guard. The function body is validated at creation, so running this
-- before migrations fails with "relation does not exist" -- true but cryptic
-- about which of the two steps was skipped.
DO $$
BEGIN
    IF to_regclass('public.tenancy_membership') IS NULL THEN
        RAISE EXCEPTION 'public.tenancy_membership does not exist; run migrations '
            'before this script (docs/runbooks/deploy.md)';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tehsil_erasure_guard') THEN
        CREATE ROLE tehsil_erasure_guard NOLOGIN NOINHERIT BYPASSRLS;
    END IF;
END $$;

-- Membership is database state, not file text. An earlier version of
-- scripts/create_runtime_role.sql carried GRANT tehsil_erasure_guard TO
-- <migration_role>, so ownership could be transferred from a migration; deleting
-- that line revokes nothing on a database already bootstrapped with it, and the
-- migration credential stays one SET ROLE from BYPASSRLS. Revoke here, on every
-- run, so the removal is an action rather than an absence.
--
-- CURRENT_USER is exempt: transferring the function's ownership below requires
-- the caller to be a member of the new owner, so a non-superuser admin may
-- legitimately hold it for the duration of this transaction.
DO $$
DECLARE
    member text;
BEGIN
    FOR member IN
        SELECT grantee.rolname
        FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS grantee ON grantee.oid = membership.member
        WHERE granted.rolname = 'tehsil_erasure_guard'
          AND grantee.rolname <> CURRENT_USER
    LOOP
        EXECUTE format('REVOKE tehsil_erasure_guard FROM %I', member);
        RAISE NOTICE 'revoked stale membership of tehsil_erasure_guard from %', member;
    END LOOP;
END $$;

-- NOLOGIN, so the function body is the only route to these privileges, and the
-- loop above leaves nothing but the running admin a member of it.
ALTER ROLE tehsil_erasure_guard WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION BYPASSRLS;
-- Postgres requires a function's new owner to hold CREATE on its schema.
GRANT CREATE ON SCHEMA public TO tehsil_erasure_guard;

-- search_path is pinned. An unpinned SECURITY DEFINER function is a textbook
-- privilege-escalation vector: the definer's privileges plus a caller-controlled
-- name resolution path.
CREATE OR REPLACE FUNCTION public.user_has_active_membership(target_user_id bigint)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.tenancy_membership
        WHERE user_id = target_user_id AND active
    );
$$;

-- BEFORE the ownership transfer. Postgres grants EXECUTE to PUBLIC on every new
-- function, and after the transfer this REVOKE runs only on the strength of the
-- caller's membership of the new owner -- which a NOINHERIT caller does not
-- carry. It then emits "WARNING: no privileges could be revoked" and changes
-- nothing. Measured on PG 17: revoking after leaves '{=X/guard,guard=X/guard}'
-- and PUBLIC still able to execute; revoking before leaves '{guard=X/guard}'.
REVOKE ALL ON FUNCTION public.user_has_active_membership(bigint) FROM PUBLIC;
ALTER FUNCTION public.user_has_active_membership(bigint) OWNER TO tehsil_erasure_guard;
-- The owning role owns this function and nothing else, and reads this one table.
GRANT SELECT ON public.tenancy_membership TO tehsil_erasure_guard;
-- runtime_engine alone: redact_identity calls this only on the EXECUTED
-- transition, and only the worker command execute_due_erasures makes that
-- transition -- the owner console makes every other one. runtime_web gets
-- nothing, so an agency request cannot ask the cross-tenant question at all;
-- a web path that ever needs it fails with "permission denied", not silently.
-- The name is literal (scripts/create_runtime_role.sql creates the role before
-- the first migrate), so this script takes no psql variables.
GRANT EXECUTE ON FUNCTION public.user_has_active_membership(bigint) TO runtime_engine;

-- Assert the outcome rather than trusting the order: a silent REVOKE is the one
-- failure this script cannot afford, and a privilege REVOKE does not raise on
-- its own. The membership revoke above needs no such check -- measured: REVOKE
-- of a ROLE without admin option is an ERROR, not a warning, so that loop either
-- revokes every member or aborts the transaction.
DO $$
BEGIN
    IF has_function_privilege(
        'public', 'public.user_has_active_membership(bigint)', 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC retained EXECUTE on the erasure guard; the '
            'cross-tenant oracle would be callable by every role in the database';
    END IF;
END $$;

COMMIT;
