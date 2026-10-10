from django.db import migrations

TABLES = ("documents_verifiedfact",)

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

# Every tenant-scoped FK on the table, paired to the referenced table's
# (tenant_id, id) unique index. NULL fk columns are exempt under MATCH SIMPLE,
# which is exactly what the nullable ones need.
COMPOSITE_FK_SQL = """
ALTER TABLE documents_verifiedfact
    ADD CONSTRAINT verifiedfact_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_verifiedfact
    ADD CONSTRAINT verifiedfact_created_by_tenant_fk
    FOREIGN KEY (tenant_id, created_by_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_verifiedfact
    ADD CONSTRAINT verifiedfact_confirmed_by_tenant_fk
    FOREIGN KEY (tenant_id, confirmed_by_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_verifiedfact
    ADD CONSTRAINT verifiedfact_supersedes_tenant_fk
    FOREIGN KEY (tenant_id, supersedes_id)
    REFERENCES documents_verifiedfact (tenant_id, id);
"""

REVERSE_COMPOSITE_FK_SQL = """
ALTER TABLE documents_verifiedfact DROP CONSTRAINT verifiedfact_supersedes_tenant_fk;
ALTER TABLE documents_verifiedfact DROP CONSTRAINT verifiedfact_confirmed_by_tenant_fk;
ALTER TABLE documents_verifiedfact DROP CONSTRAINT verifiedfact_created_by_tenant_fk;
ALTER TABLE documents_verifiedfact DROP CONSTRAINT verifiedfact_student_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
        # 0002_rls, not 0001_initial: the composite FK above references
        # tenancy_membership (tenant_id, id), and that unique index is added by
        # tenancy/0002_rls. Depending on 0001_initial makes this migration fail
        # on a fresh database with "there is no unique constraint matching the
        # given keys for referenced table".
        ("tenancy", "0002_rls"),
    ]

    operations = [
        migrations.RunSQL(COMPOSITE_FK_SQL, REVERSE_COMPOSITE_FK_SQL),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
