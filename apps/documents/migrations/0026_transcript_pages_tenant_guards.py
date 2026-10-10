from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_transcriptupload ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_transcriptupload FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_transcriptupload
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_transcriptupload
    ADD CONSTRAINT transcriptupload_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_transcriptupload
    ADD CONSTRAINT transcriptupload_cycle_tenant_fk
    FOREIGN KEY (tenant_id, cycle_id)
    REFERENCES concierge_studentcycle (tenant_id, id);
ALTER TABLE documents_transcriptupload
    ADD CONSTRAINT transcriptupload_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES concierge_documentversion (tenant_id, id);
ALTER TABLE documents_transcriptpage ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_transcriptpage FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_transcriptpage
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_transcriptpage
    ADD CONSTRAINT transcriptpage_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_transcriptpage
    ADD CONSTRAINT transcriptpage_cycle_tenant_fk
    FOREIGN KEY (tenant_id, cycle_id)
    REFERENCES concierge_studentcycle (tenant_id, id);
ALTER TABLE documents_transcriptpage
    ADD CONSTRAINT transcriptpage_upload_tenant_fk
    FOREIGN KEY (tenant_id, upload_id)
    REFERENCES documents_transcriptupload (tenant_id, id);
ALTER TABLE documents_transcriptreading
    ADD CONSTRAINT transcriptreading_cycle_tenant_fk
    FOREIGN KEY (tenant_id, cycle_id)
    REFERENCES concierge_studentcycle (tenant_id, id);
"""

# Pages reference uploads, so the page table's constraints and policy go first.
REVERSE_SQL = """
ALTER TABLE documents_transcriptreading DROP CONSTRAINT transcriptreading_cycle_tenant_fk;
ALTER TABLE documents_transcriptpage DROP CONSTRAINT transcriptpage_student_tenant_fk;
ALTER TABLE documents_transcriptpage DROP CONSTRAINT transcriptpage_cycle_tenant_fk;
ALTER TABLE documents_transcriptpage DROP CONSTRAINT transcriptpage_upload_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_transcriptpage;
ALTER TABLE documents_transcriptpage DISABLE ROW LEVEL SECURITY;
ALTER TABLE documents_transcriptupload DROP CONSTRAINT transcriptupload_student_tenant_fk;
ALTER TABLE documents_transcriptupload DROP CONSTRAINT transcriptupload_cycle_tenant_fk;
ALTER TABLE documents_transcriptupload DROP CONSTRAINT transcriptupload_document_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_transcriptupload;
ALTER TABLE documents_transcriptupload DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0025_transcript_pages"),
        ("concierge", "0014_studentcycle_tenant_guards"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
