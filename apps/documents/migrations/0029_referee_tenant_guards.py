from django.db import migrations

RLS_SQL = """
ALTER TABLE documents_referee ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_referee FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_referee
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE documents_referee
    ADD CONSTRAINT referee_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
ALTER TABLE documents_refereerequest ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents_refereerequest FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents_refereerequest
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
-- No ON DELETE CASCADE: a professor is marked, never deleted (RefereeRequest.referee
-- is PROTECT), so the guard refuses the delete too.
ALTER TABLE documents_refereerequest
    ADD CONSTRAINT refereerequest_referee_tenant_fk
    FOREIGN KEY (tenant_id, referee_id)
    REFERENCES documents_referee (tenant_id, id);
ALTER TABLE documents_refereerequest
    ADD CONSTRAINT refereerequest_application_tenant_fk
    FOREIGN KEY (tenant_id, application_id)
    REFERENCES portals_application (tenant_id, id) ON DELETE CASCADE;
"""

# Requests reference referees, so the request table's constraints and policy go first.
REVERSE_SQL = """
ALTER TABLE documents_refereerequest DROP CONSTRAINT refereerequest_referee_tenant_fk;
ALTER TABLE documents_refereerequest DROP CONSTRAINT refereerequest_application_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_refereerequest;
ALTER TABLE documents_refereerequest DISABLE ROW LEVEL SECURITY;
ALTER TABLE documents_referee DROP CONSTRAINT referee_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON documents_referee;
ALTER TABLE documents_referee DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0028_referees"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
