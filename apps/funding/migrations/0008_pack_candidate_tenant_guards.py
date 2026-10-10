from django.db import migrations


TABLES = (
    "funding_packcandidate",
    "funding_studentdecision",
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
        ("funding", "0007_pool_candidates_and_decisions"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE funding_packcandidate
                ADD CONSTRAINT packcandidate_pack_tenant_fk
                FOREIGN KEY (tenant_id, pack_version_id)
                REFERENCES funding_packversion (tenant_id, id);
            ALTER TABLE funding_packcandidate
                ADD CONSTRAINT packcandidate_candidate_tenant_fk
                FOREIGN KEY (tenant_id, candidate_id)
                REFERENCES funding_recommendationcandidate (tenant_id, id);
            ALTER TABLE funding_studentdecision
                ADD CONSTRAINT studentdecision_candidate_tenant_fk
                FOREIGN KEY (tenant_id, candidate_id)
                REFERENCES funding_recommendationcandidate (tenant_id, id);
            ALTER TABLE funding_studentdecision
                ADD CONSTRAINT studentdecision_actor_tenant_fk
                FOREIGN KEY (tenant_id, actor_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE funding_studentdecision DROP CONSTRAINT studentdecision_actor_tenant_fk;
            ALTER TABLE funding_studentdecision DROP CONSTRAINT studentdecision_candidate_tenant_fk;
            ALTER TABLE funding_packcandidate DROP CONSTRAINT packcandidate_candidate_tenant_fk;
            ALTER TABLE funding_packcandidate DROP CONSTRAINT packcandidate_pack_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
