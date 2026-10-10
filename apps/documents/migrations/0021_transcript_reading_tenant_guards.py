from django.db import migrations

TABLE = "documents_transcriptreading"

RLS_SQL = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {TABLE}
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE {TABLE}
    ADD CONSTRAINT transcriptreading_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE {TABLE}
    ADD CONSTRAINT transcriptreading_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES concierge_documentversion (tenant_id, id);
"""

REVERSE_SQL = f"""
ALTER TABLE {TABLE} DROP CONSTRAINT transcriptreading_document_tenant_fk;
ALTER TABLE {TABLE} DROP CONSTRAINT transcriptreading_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0020_transcript_reading"),
        ("concierge", "0007_documentversion_kind"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
