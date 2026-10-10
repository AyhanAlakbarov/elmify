from django.db import migrations


TABLES = (
    "audit_deletionrequest",
    "audit_retentionpolicy",
)

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
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE audit_deletionrequest
                ADD CONSTRAINT deletion_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE audit_deletionrequest DROP CONSTRAINT deletion_student_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
