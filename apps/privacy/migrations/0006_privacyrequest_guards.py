"""Tenant isolation for privacy_privacyrequest, same shape as 0004.

The row-level policy keeps one tenant from reading another's rows; the composite
foreign keys keep a request in tenant A from naming a membership in tenant B, as
its student or as the staff member who handled it. MATCH SIMPLE (the default)
skips the handled_by check while handled_by_id is NULL, which is every open request.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("privacy", "0005_privacyrequest"),
        ("tenancy", "0002_rls"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE privacy_privacyrequest
                ADD CONSTRAINT privacy_request_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE privacy_privacyrequest DROP CONSTRAINT privacy_request_student_tenant_fk;
            """,
        ),
        migrations.RunSQL(
            """
            ALTER TABLE privacy_privacyrequest
                ADD CONSTRAINT privacy_request_handled_by_tenant_fk
                FOREIGN KEY (tenant_id, handled_by_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE privacy_privacyrequest
                DROP CONSTRAINT privacy_request_handled_by_tenant_fk;
            """,
        ),
        migrations.RunSQL(
            """
            ALTER TABLE privacy_privacyrequest ENABLE ROW LEVEL SECURITY;
            ALTER TABLE privacy_privacyrequest FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON privacy_privacyrequest
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            """,
            """
            DROP POLICY IF EXISTS tenant_isolation ON privacy_privacyrequest;
            ALTER TABLE privacy_privacyrequest DISABLE ROW LEVEL SECURITY;
            """,
        ),
    ]
