from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_cvfixrevert ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_cvfixrevert FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_cvfixrevert
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_cvfixrevert
    ADD CONSTRAINT cvfixrevert_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_SQL = """
ALTER TABLE documents_cvfixrevert DROP CONSTRAINT cvfixrevert_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_cvfixrevert;
ALTER TABLE documents_cvfixrevert DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0039_cv_fix_revert_and_applied_fixes"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
