from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("research", "0001_initial")]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE research_consultantresearchtask ENABLE ROW LEVEL SECURITY;
            ALTER TABLE research_consultantresearchtask FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON research_consultantresearchtask
            USING (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            )
            WITH CHECK (
                tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
            );
            """,
            """
            DROP POLICY IF EXISTS tenant_isolation ON research_consultantresearchtask;
            ALTER TABLE research_consultantresearchtask DISABLE ROW LEVEL SECURITY;
            """,
        )
    ]
