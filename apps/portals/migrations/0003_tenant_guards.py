from django.db import migrations


TABLES = ("portals_application", "portals_applicationstep")

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
        ("portals", "0002_application"),
        ("tenancy", "0002_rls"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE portals_application
                ADD CONSTRAINT portal_app_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE portals_applicationstep
                ADD CONSTRAINT portal_step_app_tenant_fk
                FOREIGN KEY (tenant_id, application_id)
                REFERENCES portals_application (tenant_id, id);
            """,
            """
            ALTER TABLE portals_applicationstep DROP CONSTRAINT portal_step_app_tenant_fk;
            ALTER TABLE portals_application DROP CONSTRAINT portal_app_student_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
