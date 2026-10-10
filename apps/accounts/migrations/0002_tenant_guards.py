from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE accounts_studentprofileversion
                ADD CONSTRAINT profile_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE accounts_studentprofileversion ENABLE ROW LEVEL SECURITY;
            ALTER TABLE accounts_studentprofileversion FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON accounts_studentprofileversion
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            """,
            """
            DROP POLICY IF EXISTS tenant_isolation ON accounts_studentprofileversion;
            ALTER TABLE accounts_studentprofileversion DISABLE ROW LEVEL SECURITY;
            ALTER TABLE accounts_studentprofileversion DROP CONSTRAINT profile_student_tenant_fk;
            """,
        )
    ]
