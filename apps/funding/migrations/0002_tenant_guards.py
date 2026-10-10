from django.db import migrations


TABLES = (
    "funding_evidenceclaim",
    "funding_recommendationrun",
    "funding_recommendationcandidate",
    "funding_packversion",
    "funding_approval",
    "funding_auditevent",
)

RLS_SQL = "\n".join(
    f"""
    ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """
    for table in TABLES
)

REVERSE_RLS_SQL = "\n".join(
    f"""
    DROP POLICY IF EXISTS tenant_isolation ON {table};
    ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """
    for table in reversed(TABLES)
)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_tenant_guards"),
        ("funding", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE funding_recommendationrun
                ADD CONSTRAINT run_profile_tenant_fk
                FOREIGN KEY (tenant_id, profile_version_id)
                REFERENCES accounts_studentprofileversion (tenant_id, id);
            ALTER TABLE funding_recommendationcandidate
                ADD CONSTRAINT candidate_run_tenant_fk
                FOREIGN KEY (tenant_id, run_id)
                REFERENCES funding_recommendationrun (tenant_id, id);
            ALTER TABLE funding_recommendationcandidate
                ADD CONSTRAINT candidate_evidence_tenant_fk
                FOREIGN KEY (tenant_id, evidence_id)
                REFERENCES funding_evidenceclaim (tenant_id, id);
            ALTER TABLE funding_packversion
                ADD CONSTRAINT pack_run_tenant_fk
                FOREIGN KEY (tenant_id, run_id)
                REFERENCES funding_recommendationrun (tenant_id, id);
            ALTER TABLE funding_packversion
                ADD CONSTRAINT pack_candidate_tenant_fk
                FOREIGN KEY (tenant_id, candidate_id)
                REFERENCES funding_recommendationcandidate (tenant_id, id);
            ALTER TABLE funding_approval
                ADD CONSTRAINT approval_pack_tenant_fk
                FOREIGN KEY (tenant_id, object_version_id)
                REFERENCES funding_packversion (tenant_id, id);
            ALTER TABLE funding_approval
                ADD CONSTRAINT approval_actor_tenant_fk
                FOREIGN KEY (tenant_id, actor_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE funding_auditevent
                ADD CONSTRAINT event_actor_tenant_fk
                FOREIGN KEY (tenant_id, actor_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE funding_auditevent DROP CONSTRAINT event_actor_tenant_fk;
            ALTER TABLE funding_approval DROP CONSTRAINT approval_actor_tenant_fk;
            ALTER TABLE funding_approval DROP CONSTRAINT approval_pack_tenant_fk;
            ALTER TABLE funding_packversion DROP CONSTRAINT pack_candidate_tenant_fk;
            ALTER TABLE funding_packversion DROP CONSTRAINT pack_run_tenant_fk;
            ALTER TABLE funding_recommendationcandidate DROP CONSTRAINT candidate_evidence_tenant_fk;
            ALTER TABLE funding_recommendationcandidate DROP CONSTRAINT candidate_run_tenant_fk;
            ALTER TABLE funding_recommendationrun DROP CONSTRAINT run_profile_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
