from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_documentreading ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_documentreading FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_documentreading
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_documentreading
    ADD CONSTRAINT documentreading_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_documentreading
    ADD CONSTRAINT documentreading_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES concierge_documentversion (tenant_id, id);
"""

REVERSE_SQL = """
ALTER TABLE documents_documentreading DROP CONSTRAINT documentreading_student_tenant_fk;
ALTER TABLE documents_documentreading DROP CONSTRAINT documentreading_document_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_documentreading;
ALTER TABLE documents_documentreading DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0034_document_reading")]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
