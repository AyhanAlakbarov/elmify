"""Tenant isolation for privacy_acceptance, matching audit/0008, and append-only.

The row-level policy keeps one tenant from reading another's rows; the composite
foreign key keeps an acceptance in tenant A from naming a membership in tenant B,
which a plain student_id FK permits.

funding/0049's default privileges give both runtime roles full DML on every new
table. An acceptance is the record of what a student agreed to; nothing at
runtime may rewrite or remove one. Erasure does not need to either: it redacts
REDACT models only, and Acceptance is KEEP-only (apps/audit/redaction.py).
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("privacy", "0003_acceptance"),
        ("tenancy", "0002_rls"),
        ("funding", "0049_catalog_grants"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE privacy_acceptance
                ADD CONSTRAINT acceptance_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE privacy_acceptance DROP CONSTRAINT acceptance_student_tenant_fk;
            """,
        ),
        migrations.RunSQL(
            """
            ALTER TABLE privacy_acceptance ENABLE ROW LEVEL SECURITY;
            ALTER TABLE privacy_acceptance FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON privacy_acceptance
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            """,
            """
            DROP POLICY IF EXISTS tenant_isolation ON privacy_acceptance;
            ALTER TABLE privacy_acceptance DISABLE ROW LEVEL SECURITY;
            """,
        ),
        migrations.RunSQL(
            "REVOKE UPDATE, DELETE ON public.privacy_acceptance FROM runtime_engine, runtime_web;",
            "GRANT UPDATE, DELETE ON public.privacy_acceptance TO runtime_engine, runtime_web;",
        ),
    ]
