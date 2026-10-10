from django.db import migrations, models


RLS_SQL = """
ALTER TABLE tenancy_membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenancy_membership FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tenancy_membership
USING (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
)
WITH CHECK (
    tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
);
"""

REVERSE_RLS_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON tenancy_membership;
ALTER TABLE tenancy_membership DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0001_initial")]

    operations = [
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.UniqueConstraint(
                fields=("tenant", "id"), name="membership_tenant_id_id_uniq"
            ),
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
