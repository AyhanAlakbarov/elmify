from django.db import migrations

TABLES = (
    "documents_documentdraft",
    "documents_documentdraftfact",
    "documents_revisionrequest",
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

COMPOSITE_FK_SQL = """
ALTER TABLE documents_documentdraft
    ADD CONSTRAINT documentdraft_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_documentdraft
    ADD CONSTRAINT documentdraft_approved_by_tenant_fk
    FOREIGN KEY (tenant_id, approved_by_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_documentdraftfact
    ADD CONSTRAINT documentdraftfact_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES documents_documentdraft (tenant_id, id);
ALTER TABLE documents_documentdraftfact
    ADD CONSTRAINT documentdraftfact_fact_tenant_fk
    FOREIGN KEY (tenant_id, fact_id)
    REFERENCES documents_verifiedfact (tenant_id, id);
ALTER TABLE documents_revisionrequest
    ADD CONSTRAINT revisionrequest_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES documents_documentdraft (tenant_id, id);
ALTER TABLE documents_revisionrequest
    ADD CONSTRAINT revisionrequest_requested_by_tenant_fk
    FOREIGN KEY (tenant_id, requested_by_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_revisionrequest
    ADD CONSTRAINT revisionrequest_resulting_draft_tenant_fk
    FOREIGN KEY (tenant_id, resulting_draft_id)
    REFERENCES documents_documentdraft (tenant_id, id);
ALTER TABLE documents_revisionrequest
    ADD CONSTRAINT revisionrequest_superseding_fact_tenant_fk
    FOREIGN KEY (tenant_id, superseding_fact_id)
    REFERENCES documents_verifiedfact (tenant_id, id);
"""

REVERSE_COMPOSITE_FK_SQL = """
ALTER TABLE documents_revisionrequest DROP CONSTRAINT revisionrequest_superseding_fact_tenant_fk;
ALTER TABLE documents_revisionrequest DROP CONSTRAINT revisionrequest_resulting_draft_tenant_fk;
ALTER TABLE documents_revisionrequest DROP CONSTRAINT revisionrequest_requested_by_tenant_fk;
ALTER TABLE documents_revisionrequest DROP CONSTRAINT revisionrequest_document_tenant_fk;
ALTER TABLE documents_documentdraftfact DROP CONSTRAINT documentdraftfact_fact_tenant_fk;
ALTER TABLE documents_documentdraftfact DROP CONSTRAINT documentdraftfact_document_tenant_fk;
ALTER TABLE documents_documentdraft DROP CONSTRAINT documentdraft_approved_by_tenant_fk;
ALTER TABLE documents_documentdraft DROP CONSTRAINT documentdraft_student_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0003_document_draft"),
        ("tenancy", "0002_rls"),
    ]

    operations = [
        migrations.RunSQL(COMPOSITE_FK_SQL, REVERSE_COMPOSITE_FK_SQL),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
