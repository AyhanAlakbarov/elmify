from django.db import migrations

TABLES = ("documents_europassrendercache",)

RLS_SQL = "\n".join(
    f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """
    for table in TABLES
)

REVERSE_RLS_SQL = "\n".join(
    f"""
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """
    for table in reversed(TABLES)
)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0010_europass_pipeline"),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
