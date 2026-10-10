# Fix: 0016_catalog_rule granted the shared_catalog_select read policy but
# omitted the catalog_ingestion_write policy that every other shared catalog
# table has (added in 0006_official_snapshots). Without it, the dedicated
# catalog_ingestion role has no write path onto funding_catalogrule, unlike
# its siblings -- caught by tests/tenancy/test_database_isolation.py's
# test_task7_rls_policy_shapes_and_runtime_acl once the table was added to
# _SHARED_TABLES.
from django.db import migrations

TABLE = "funding_catalogrule"

RLS_SQL = f"""
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
"""


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0017_funder_cv_format_requirement'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
