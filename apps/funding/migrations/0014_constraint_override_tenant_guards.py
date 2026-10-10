from django.db import migrations

TABLES = ("funding_constraintoverride",)

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

COMPOSITE_FK_SQL = """
ALTER TABLE funding_constraintoverride
    ADD CONSTRAINT constraintoverride_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE funding_constraintoverride
    ADD CONSTRAINT constraintoverride_decided_by_tenant_fk
    FOREIGN KEY (tenant_id, decided_by_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_COMPOSITE_FK_SQL = """
ALTER TABLE funding_constraintoverride DROP CONSTRAINT constraintoverride_decided_by_tenant_fk;
ALTER TABLE funding_constraintoverride DROP CONSTRAINT constraintoverride_student_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("funding", "0013_cv_format_requirement"),
        ("tenancy", "0002_rls"),
    ]

    operations = [
        migrations.RunSQL(COMPOSITE_FK_SQL, REVERSE_COMPOSITE_FK_SQL),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
