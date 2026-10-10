# research_decisionrecord joins _SHARED_TABLES
# (tests/tenancy/test_database_isolation.py) as shared catalog data: no student
# data is ever in a decision state, and which sentence a page states is the
# same fact for every tenant.
#
# CLAUDE.md's recipe for a new catalogue table (2026-09-25): the shared read
# policy, a write policy for runtime_engine -- never catalog_ingestion, which
# funding/0049 dropped -- and REVOKE from runtime_web in the same migration,
# because 0049's default privileges grant every new table to both runtime roles.
# The boundary is the GRANT: an absent grant fails closed with `permission
# denied`, where a policy returning zero rows looks like an empty table.
#
# Depends on funding/0049 because that is what creates runtime_engine and
# runtime_web on a superuser-migrated database; without the edge this policy
# could be created before its role exists.
#
# ENABLE without FORCE, matching every shared catalog table
# (test_task7_rls_policy_shapes_and_runtime_acl asserts (True, False)). FORCE
# is for TENANT tables, where CLAUDE.md's failure mode 3 applies; a table
# whose read policy is USING (true) has nothing to force.
#
# UUID primary key: no sequence to revoke.
from django.db import migrations

TABLE = "research_decisionrecord"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{TABLE}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
REVOKE ALL ON public.{TABLE} FROM runtime_web;
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0021_decision_record"),
        ("funding", "0049_catalog_grants"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
