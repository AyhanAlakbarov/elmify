"""The third RLS case: platform-only. And the platform marker's grant surface.

**research_resolutionitem** fits neither shape this repo already has:

- Not tenant-scoped: one question about a shared host would become one row per
  agency that met it, defeating the cross-tenant dedupe spec 11 depends on, and
  every row would carry the tenant id spec 11 forbids.
- Not shared catalog: `shared_catalog_select` is `FOR SELECT USING (true)` to
  PUBLIC, so every agency's request could list the queue -- which hosts we
  cannot open, which awards our readers disagree on -- and decision 26 says
  agencies never see it. Nor is it a catalogue table in the grant sense
  (funding/0049): `runtime_web` keeps its default DML grant, because the
  platform's console runs as `runtime_web`.

So the policies ask a different question: *is this the platform's own
request?* It is phrased through the tenant GUC that HostTenantContextMiddleware
already sets from the VERIFIED domain, looked up in research_platformagency. A
request on an agency's host carries that agency's id and sees zero rows,
whatever the view does. SELECT and UPDATE only: an operator decides and parks,
never inserts or deletes. Inserting and deleting belong to `runtime_engine_write`
-- the writers (discover, classify_organisations, the funding reader, the
resolver) and the applier all run as `runtime_engine` -- and to the owner.
`catalog_ingestion` is gone (funding/0049), so it is named nowhere here.

ENABLE without FORCE, like the shared catalog: FORCE would filter the owner
through the platform predicate too, so every owner-run writer would need the
platform GUC set -- CLAUDE.md failure mode 1 for any that forgets.

This narrows a table holding no tenant data to one tenant. It is NOT the
"widen tenant policies for a platform-admin GUC" that CLAUDE.md rules out: no
GUC is added and no tenant table is touched. It is a fail-closed guard against
mistakes, not a privilege boundary against the application: runtime code can
`set_config('app.tenant_id', ...)` as easily as the policy reads it.

**research_platformagency** has no RLS -- one agency id, no person. Both
runtime roles keep SELECT on it, and must: the policy subquery above runs with
the CALLER's privileges, so a `runtime_web` without SELECT would get
`permission denied` on every queue read. Neither may write it, which is
stronger than a tenancy column would have been (both runtime roles hold UPDATE
on tenancy_agency): moving the platform moves who can read the queue, so only
the owner may, through `manage.py set_platform_agency` run as the migration
role. Two layers say so:

- the GRANT: both roles lose INSERT, UPDATE, DELETE (and everything else but
  SELECT), which default privileges gave them when 0012 created the table;
- a statement trigger refusing any write by a role that is not a member of the
  table's owner, with the same SQLSTATE (42501) a missing grant raises.

The trigger is there because a grant is drift-prone state and this marker is
the one row the queue's whole visibility hangs on. Any later blanket
`GRANT ... ON ALL TABLES` -- funding/0049's forward SQL is exactly that, and
the migration tests unapply and re-apply 0049 while research stays at head --
silently hands the runtime roles DML again. This migration cannot depend on
funding/0049 to order itself after that GRANT: the dependency makes research
downstream of funding, and seven tests in tests/migrations then fail with
InvalidMigrationPlan (measured 2026-09-26; research/0003 records the same
hazard). So it names the two roles itself, as research/0010 does, and the
trigger makes the order irrelevant.

Verify against a NOBYPASSRLS role -- tests/research/resolution/test_rls.py, via
`runtime_connection` and `role_connection` -- never the test role, which
bypasses RLS and grants alike.
"""

from django.db import migrations

TABLE = "research_resolutionitem"
MARKER = "research_platformagency"

_PLATFORM = f"""
EXISTS (
    SELECT 1 FROM public.{MARKER} AS platform
    WHERE platform.agency_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
)
"""

_ENSURE_ROLES = """
DO $$ BEGIN
    IF (SELECT count(*) FROM pg_roles
         WHERE rolname IN ('runtime_engine', 'runtime_web')) < 2
       AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'runtime_engine / runtime_web do not both exist: run '
            'scripts/create_runtime_role.sql as the admin role, then re-run the migration';
    END IF;
END $$;
""" + "".join(
    f"""
DO $$ BEGIN
    CREATE ROLE {role} NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
"""
    for role in ("runtime_engine", "runtime_web")
)

RLS_SQL = _ENSURE_ROLES + f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY platform_operator_select ON public.{TABLE}
    FOR SELECT USING ({_PLATFORM});
CREATE POLICY platform_operator_update ON public.{TABLE}
    FOR UPDATE USING ({_PLATFORM}) WITH CHECK ({_PLATFORM});
CREATE POLICY runtime_engine_write ON public.{TABLE}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO runtime_engine, runtime_web;

REVOKE ALL ON public.{MARKER} FROM runtime_engine, runtime_web;
GRANT SELECT ON public.{MARKER} TO runtime_engine, runtime_web;

CREATE FUNCTION public.research_platformagency_owner_only() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT pg_has_role(
        current_user, (SELECT relowner FROM pg_class WHERE oid = TG_RELID), 'USAGE'
    ) THEN
        RAISE EXCEPTION 'only the owner of % may write it: run manage.py '
            'set_platform_agency with DATABASE_ROLE=migration', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER research_platformagency_owner_only
    BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{MARKER}
    FOR EACH STATEMENT EXECUTE FUNCTION public.research_platformagency_owner_only();
"""

REVERSE_RLS_SQL = f"""
DROP TRIGGER IF EXISTS research_platformagency_owner_only ON public.{MARKER};
DROP FUNCTION IF EXISTS public.research_platformagency_owner_only();
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{MARKER} TO runtime_engine, runtime_web;
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS platform_operator_update ON public.{TABLE};
DROP POLICY IF EXISTS platform_operator_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0012_resolution_item"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
