# funding_program_awarding_institutions joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: which
# universities award a programme is the same fact for every tenant.
# Same shape as 0026_institution_identifier_rls -- both the
# shared_catalog_select read policy and the catalog_ingestion_write policy,
# from the start.
from django.db import migrations

TABLE = "funding_program_awarding_institutions"

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
        ('funding', '0029_program_providers'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
