"""Tenant isolation for EvidenceReading, the 0021/0029 pattern.

FORCE ROW LEVEL SECURITY so the table owner is filtered too, and composite foreign
keys so a reading in tenant A can name neither a student nor an upload in tenant B.
The runtime grants come from funding/0049's default privileges, as for every
documents table since.
"""

from django.db import migrations

TABLE = "documents_evidencereading"

RLS_SQL = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {TABLE}
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE {TABLE}
    ADD CONSTRAINT evidencereading_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE {TABLE}
    ADD CONSTRAINT evidencereading_document_tenant_fk
    FOREIGN KEY (tenant_id, document_id)
    REFERENCES concierge_documentversion (tenant_id, id);
"""

REVERSE_SQL = f"""
ALTER TABLE {TABLE} DROP CONSTRAINT evidencereading_document_tenant_fk;
ALTER TABLE {TABLE} DROP CONSTRAINT evidencereading_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0031_evidencereading"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
