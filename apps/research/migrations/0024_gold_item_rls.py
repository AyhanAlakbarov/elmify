"""research_golditem: platform-only, the same policies as research_resolutionitem (0013).

Read 0013's docstring for why the policy asks "is this the platform's own request?" through the
tenant GUC, and why ENABLE without FORCE. Differences from 0013:

- Rows are kept as regression data, so neither runtime role may DELETE. Default privileges hand
  both roles full DML on every new table, so DELETE is REVOKEd, not merely left ungranted;
  `runtime_engine_write` is FOR ALL, so the grant is what stops the engine.
- The platform marker's grants and owner-only trigger are 0013's and are not repeated here.
"""

from django.db import migrations

TABLE = "research_golditem"
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
        ("research", "0023_gold_item"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
