"""Tenant isolation for audit_pseudonym, matching 0002_tenant_guards.

Two guards, and the model needs both for the same reasons DeletionRequest does.
The row-level policy keeps one tenant from reading another's rows; the composite
foreign key keeps a row in tenant A from pointing at a membership in tenant B,
which a plain student_id FK permits.
"""

from django.db import migrations

TABLES = ("audit_pseudonym",)

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
        ("audit", "0007_pseudonym"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE audit_pseudonym
                ADD CONSTRAINT pseudonym_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE audit_pseudonym DROP CONSTRAINT pseudonym_student_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
