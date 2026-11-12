"""research_winnercohortprofile: platform-only, same policies as research_golditem (0024).

Readable and updatable by `runtime_web` only when `app.tenant_id` is the platform agency
(`research_platformagency`), and writable by `runtime_engine`. B2B agencies see zero rows.
"""

from django.db import migrations

TABLE = "research_winnercohortprofile"
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
GRANT SELECT, INSERT, UPDATE ON public.{TABLE} TO runtime_engine, runtime_web;
REVOKE DELETE ON public.{TABLE} FROM runtime_engine, runtime_web;
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS platform_operator_update ON public.{TABLE};
DROP POLICY IF EXISTS platform_operator_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0032_winner_cohort_profile"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
