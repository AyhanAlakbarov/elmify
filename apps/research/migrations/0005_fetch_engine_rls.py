"""`research_hostprofile` and `research_fetchattempt` as shared catalog.

Both join `_SHARED_TABLES` (tests/tenancy/test_database_isolation.py): which
rung reads a ministry's website is the same fact for every tenant, and neither
table describes a person. Same policy shape as
`funding/0030_program_awarding_institutions_rls` -- both the
`shared_catalog_select` read policy and the `catalog_ingestion_write` policy,
from the start. `ENABLE` without `FORCE`, like every other shared-catalog table
here: `FORCE` locks the migration role, which owns them, out of its own tables.

Django never writes an RLS operation, `makemigrations` will not produce one, and
a squash regenerating an initial would silently drop it (CLAUDE.md).

**The `catalog_ingestion` role is created by `funding/0006_official_snapshots`,
and this migration cannot depend on it.** Naming that dependency from `research`
makes research downstream of funding, and the six tests in
`tests/migrations/test_task7_migrations.py` that roll funding back to
`0004_phase1_catalog` while other apps stay at their head then produce a plan
containing both directions, which Django refuses with `InvalidMigrationPlan`.
That was measured on `research/0003`, which is why the register's own policies
live in `funding/0044_organisation_fk` instead.

A full `migrate` happens to order this after `funding/0006` -- `leaf_nodes()` is
sorted and `funding` < `research` -- but `manage.py migrate research` on a fresh
cluster does not, and nothing pins the alphabet. So the role is ensured here the
same way `funding/0006` itself ensures it: idempotently, in a `DO` block, before
any policy names it. Do not verify this by running it locally -- a Postgres role
is a CLUSTER object, so any database on the same cluster that has ever run
`funding/0006` leaves `catalog_ingestion` in place and a local run proves only
that the role outlived another database.
"""

from django.db import migrations

TABLES = ("research_hostprofile", "research_fetchattempt")

ENSURE_ROLE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'catalog_ingestion') THEN
        CREATE ROLE catalog_ingestion NOLOGIN;
    END IF;
END
$$;
"""

RLS_SQL = ENSURE_ROLE_SQL + "".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{table}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""
    for table in TABLES
)

# The role is deliberately not dropped on reverse: it is cluster-wide and every
# other shared-catalog table's policy still names it (funding/0032 says the same).
REVERSE_RLS_SQL = "".join(
    f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in TABLES
)


class Migration(migrations.Migration):

    dependencies = [
        ("research", "0004_fetch_engine"),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
