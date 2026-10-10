# research_sitejobrecord joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: what the
# funnel searched for a programme is the same fact for every tenant, and no
# student data is ever in one of these rows.
#
# Both policies from the start, as 0026_institution_identifier_rls has it:
# a read policy for every role and a write policy for catalog_ingestion only.
# Verify against the runtime_connection fixture -- the test role bypasses RLS
# and proves nothing (CLAUDE.md).
from django.db import migrations

TABLE = "research_sitejobrecord"

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
        ("research", "0008_site_job_record"),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
