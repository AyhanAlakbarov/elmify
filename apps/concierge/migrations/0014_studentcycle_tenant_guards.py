from django.db import migrations

TABLE = "concierge_studentcycle"

RLS_SQL = f"""
ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {TABLE}
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE {TABLE}
    ADD CONSTRAINT studentcycle_student_tenant_fk
    FOREIGN KEY (tenant_id, student_id)
    REFERENCES tenancy_membership (tenant_id, id);
"""

REVERSE_SQL = f"""
ALTER TABLE {TABLE} DROP CONSTRAINT studentcycle_student_tenant_fk;
DROP POLICY IF EXISTS tenant_isolation ON {TABLE};
ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("concierge", "0013_studentcycle"),
        ("tenancy", "0002_rls"),
    ]

    operations = [migrations.RunSQL(RLS_SQL, REVERSE_SQL)]
