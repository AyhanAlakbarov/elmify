# funding_institutionidentifier joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: which
# code a register knows an institution by is the same fact for every tenant.
# Same shape as 0023_register_tables_rls -- both the shared_catalog_select
# read policy and the catalog_ingestion_write policy, from the start.
#
# This is also what makes load_institution_identifiers need an elevated role.
# An INSERT under the runtime role raises rather than passing silently; the
# silent case is UPDATE and DELETE, which is why that command carries a guard
# it does not strictly need yet.
from django.db import migrations

TABLE = "funding_institutionidentifier"

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
        ('funding', '0025_institution_identifier'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
