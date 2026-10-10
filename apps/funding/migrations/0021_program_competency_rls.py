# funding_programcompetency joins _SHARED_TABLES (tests/tenancy/test_database_isolation.py)
# as shared catalog data: a programme's stated requirements are the same fact
# for every tenant, not tenant-owned rows. Every table in that list carries
# both the shared_catalog_select read policy and the catalog_ingestion_write
# policy (0006_official_snapshots, 0016_catalog_rule + 0018's follow-up fix
# after that one shipped without it) -- adding both here from the start
# avoids repeating 0018's oversight.
from django.db import migrations

TABLE = "funding_programcompetency"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0020_program_competency'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
