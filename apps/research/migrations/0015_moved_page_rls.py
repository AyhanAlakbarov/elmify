"""research_movedpage is shared catalogue: the shape research/0010 uses.

Which page replaced which is the same fact for every tenant and describes the
web, not a person, so every tenant reads it (`shared_catalog_select`) and only
`runtime_engine` writes it (`runtime_engine_write`) -- the resolution applier,
`manage.py apply_resolutions`, is its one writer. `runtime_web` holds no table
grant at all: the catalogue boundary is a GRANT, not a policy
(tests/tenancy/test_catalog_grants.py), and default privileges handed it DML
when 0014 created the table, so it is revoked here explicitly. A UUID primary
key, so there is no sequence to revoke.

Like 0010 and 0013, this cannot depend on funding/0049 (which creates the two
roles): the dependency makes research downstream of funding and seven tests in
tests/migrations then fail with InvalidMigrationPlan. So it names the roles
itself, creating them NOLOGIN on a superuser-run database where 0049 has not
run yet, and refusing a non-superuser as 0049 does.
"""

from django.db import migrations

TABLE = "research_movedpage"

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
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{TABLE}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO runtime_engine;
REVOKE ALL ON public.{TABLE} FROM runtime_web;
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0014_resolution_writebacks"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
