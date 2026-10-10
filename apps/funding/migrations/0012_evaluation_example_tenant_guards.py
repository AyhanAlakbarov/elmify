from django.db import migrations


RLS_SQL = """
ALTER TABLE funding_evaluationexample ENABLE ROW LEVEL SECURITY;
ALTER TABLE funding_evaluationexample FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON funding_evaluationexample
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
"""

REVERSE_RLS_SQL = """
DROP POLICY IF EXISTS tenant_isolation ON funding_evaluationexample;
ALTER TABLE funding_evaluationexample DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0011_audit_event_append_only'),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE funding_evaluationexample
                ADD CONSTRAINT evalexample_source_event_tenant_fk
                FOREIGN KEY (tenant_id, source_event_id)
                REFERENCES funding_auditevent (tenant_id, id);
            """,
            """
            ALTER TABLE funding_evaluationexample DROP CONSTRAINT evalexample_source_event_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
