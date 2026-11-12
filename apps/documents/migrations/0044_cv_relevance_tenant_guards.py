from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_cvrelevanceanswer ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_cvrelevanceanswer FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_cvrelevanceanswer
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_cvrelevanceanswer
    ADD CONSTRAINT cvrelevanceanswer_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_cvitemchoice ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_cvitemchoice FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_cvitemchoice
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_cvitemchoice
    ADD CONSTRAINT cvitemchoice_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_SQL = """
ALTER TABLE documents_cvitemchoice DROP CONSTRAINT cvitemchoice_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_cvitemchoice;
ALTER TABLE documents_cvitemchoice DISABLE ROW LEVEL SECURITY;
ALTER TABLE documents_cvrelevanceanswer DROP CONSTRAINT cvrelevanceanswer_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_cvrelevanceanswer;
ALTER TABLE documents_cvrelevanceanswer DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0043_cv_relevance_tables"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
