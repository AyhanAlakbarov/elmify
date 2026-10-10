from django.db import migrations


RLS_SQL = """
ALTER TABLE tenancy_counselorassignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenancy_counselorassignment FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenancy_counselorassignment
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
"""

REVERSE_RLS_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON tenancy_counselorassignment;
ALTER TABLE tenancy_counselorassignment DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0006_platform_admin_and_support_grant'),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE tenancy_counselorassignment
                ADD CONSTRAINT assignment_counselor_tenant_fk
                FOREIGN KEY (tenant_id, counselor_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE tenancy_counselorassignment
                ADD CONSTRAINT assignment_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE tenancy_counselorassignment DROP CONSTRAINT assignment_student_tenant_fk;
            ALTER TABLE tenancy_counselorassignment DROP CONSTRAINT assignment_counselor_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
