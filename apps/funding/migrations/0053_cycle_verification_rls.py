"""RLS and grants for funding_fundingcycleverification (funding engine item 11).

RLS class: SHARED CATALOG. Whether an award's money is there for an intake is
the same fact for every tenant, and the row carries no person -- it points at a
FundingOpportunity and nothing tenant-scoped -- so it joins `_SHARED_TABLES`
(tests/tenancy/test_database_isolation.py).

The block is the recipe for a new catalogue table (CLAUDE.md, "The role
model"), the shape research/0010 uses: every tenant reads
(`shared_catalog_select`), only `runtime_engine` writes (`runtime_engine_write`;
`catalog_ingestion` was dropped by funding/0049), and `runtime_web` holds no
table grant at all -- the catalogue boundary is a GRANT, not a policy. Default
privileges grant every new table to both runtime roles, so without the REVOKE
the web tier could read this table; tests/tenancy/test_catalog_grants.py fails
until it is revoked. UUID primary key: no sequence to revoke.

This migration follows funding/0049 on the funding chain, so both roles exist
and it need not create them. Verified in tests/funding/test_cycle_verification_rls.py
through `runtime_connection` and `role_connection` -- never through the test
role, which bypasses RLS and grants alike.
"""

from django.db import migrations

TABLE = "funding_fundingcycleverification"

RLS_SQL = f"""
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
    dependencies = [("funding", "0052_cycle_verification")]
    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
