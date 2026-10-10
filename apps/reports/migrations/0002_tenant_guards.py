from django.db import migrations, models


TABLES = (
    "reports_consultationpayment",
    "reports_consultationreport",
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
        ("reports", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="consultationpayment",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=("PENDING", "PAID", "FAILED", "REFUNDED")),
                name="payment_status_valid",
            ),
        ),
        migrations.RunSQL(
            """
            ALTER TABLE reports_consultationreport
                ADD CONSTRAINT report_pack_tenant_fk
                FOREIGN KEY (tenant_id, pack_version_id)
                REFERENCES funding_packversion (tenant_id, id);
            ALTER TABLE reports_consultationpayment
                ADD CONSTRAINT payment_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            """,
            """
            ALTER TABLE reports_consultationpayment DROP CONSTRAINT payment_student_tenant_fk;
            ALTER TABLE reports_consultationreport DROP CONSTRAINT report_pack_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
