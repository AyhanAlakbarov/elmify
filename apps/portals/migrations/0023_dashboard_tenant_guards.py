from django.db import migrations


class Migration(migrations.Migration):

    # funding.0001 and mailbox.0001 create the (tenant_id, id) keys these
    # reference; the earliest edges that satisfy them, as 0022 explains.
    dependencies = [
        ("funding", "0001_initial"),
        ("mailbox", "0001_initial"),
        ("portals", "0022_dashboard_fields"),
    ]

    operations = [
        # The composite guards every other tenant-to-tenant FK here carries
        # (0015_reminder_item_tenant_guard.py is the nullable SET_NULL
        # precedent). Without them candidate and outcome_evidence could name a
        # row in another tenant, and the suite's BYPASSRLS role never notices.
        migrations.RunSQL(
            """
            ALTER TABLE portals_application
                ADD CONSTRAINT portal_app_candidate_tenant_fk
                FOREIGN KEY (tenant_id, candidate_id)
                REFERENCES funding_recommendationcandidate (tenant_id, id);
            """,
            """
            ALTER TABLE portals_application DROP CONSTRAINT portal_app_candidate_tenant_fk;
            """,
        ),
        migrations.RunSQL(
            """
            ALTER TABLE portals_application
                ADD CONSTRAINT portal_app_evidence_tenant_fk
                FOREIGN KEY (tenant_id, outcome_evidence_id)
                REFERENCES mailbox_mailsignal (tenant_id, id);
            """,
            """
            ALTER TABLE portals_application DROP CONSTRAINT portal_app_evidence_tenant_fk;
            """,
        ),
    ]
