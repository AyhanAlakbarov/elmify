from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("portals", "0025_applicationlink")]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE portals_applicationlink ENABLE ROW LEVEL SECURITY;
            ALTER TABLE portals_applicationlink FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON portals_applicationlink
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            """,
            """
            DROP POLICY IF EXISTS tenant_isolation ON portals_applicationlink;
            ALTER TABLE portals_applicationlink DISABLE ROW LEVEL SECURITY;
            """,
        ),
        # Both ends must be cards of the link's own tenant (the composite
        # guard every tenant-to-tenant FK here carries; 0023 is the precedent).
        migrations.RunSQL(
            """
            ALTER TABLE portals_applicationlink
                ADD CONSTRAINT portal_link_from_tenant_fk
                FOREIGN KEY (tenant_id, from_app_id)
                REFERENCES portals_application (tenant_id, id) ON DELETE CASCADE;
            ALTER TABLE portals_applicationlink
                ADD CONSTRAINT portal_link_to_tenant_fk
                FOREIGN KEY (tenant_id, to_app_id)
                REFERENCES portals_application (tenant_id, id) ON DELETE CASCADE;
            """,
            """
            ALTER TABLE portals_applicationlink DROP CONSTRAINT portal_link_from_tenant_fk;
            ALTER TABLE portals_applicationlink DROP CONSTRAINT portal_link_to_tenant_fk;
            """,
        ),
    ]
