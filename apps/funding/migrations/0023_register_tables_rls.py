# funding_registerlisting and funding_registercoverage join _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: what a
# government register says about an institution is the same fact for every
# tenant, not tenant-owned rows. Same shape as
# 0021_program_competency_rls -- both the shared_catalog_select read policy and
# the catalog_ingestion_write policy, from the start.
#
# The hazard the ProgramStatement rule exists for is absent here and that is
# worth stating rather than assuming: no model reads a register. These are
# structured government files parsed by field access, pinned by
# tests/research/test_registers.py. The RLS restriction still applies -- these
# are third-party bytes every tenant reads, and only catalog ingestion writes.
from django.db import migrations

TABLES = ("funding_registerlisting", "funding_registercoverage")

RLS_SQL = "\n".join(
    f"""
ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{table}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{table}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""
    for table in TABLES
)

REVERSE_RLS_SQL = "\n".join(
    f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};
DROP POLICY IF EXISTS shared_catalog_select ON public.{table};
ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY;
"""
    for table in TABLES
)


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0022_register_listing_and_coverage'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
