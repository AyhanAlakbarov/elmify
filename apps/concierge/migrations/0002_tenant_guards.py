from django.db import migrations


TABLES = (
    "concierge_roadmapitem",
    "concierge_manualoperation",
    "concierge_requiredaction",
    "concierge_notification",
    "concierge_conversationmessage",
    "concierge_serviceengagement",
    "concierge_applicationfeeledgerentry",
    "concierge_receipt",
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
        ("concierge", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            """
            ALTER TABLE concierge_roadmapitem
                ADD CONSTRAINT roadmap_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_roadmapitem
                ADD CONSTRAINT roadmap_owner_tenant_fk
                FOREIGN KEY (tenant_id, owner_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_manualoperation
                ADD CONSTRAINT manualop_roadmap_tenant_fk
                FOREIGN KEY (tenant_id, roadmap_item_id)
                REFERENCES concierge_roadmapitem (tenant_id, id);
            ALTER TABLE concierge_manualoperation
                ADD CONSTRAINT manualop_actor_tenant_fk
                FOREIGN KEY (tenant_id, actor_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_requiredaction
                ADD CONSTRAINT requiredaction_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_notification
                ADD CONSTRAINT notification_recipient_tenant_fk
                FOREIGN KEY (tenant_id, recipient_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_conversationmessage
                ADD CONSTRAINT message_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_conversationmessage
                ADD CONSTRAINT message_counselor_tenant_fk
                FOREIGN KEY (tenant_id, counselor_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_conversationmessage
                ADD CONSTRAINT message_sender_tenant_fk
                FOREIGN KEY (tenant_id, sender_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_serviceengagement
                ADD CONSTRAINT engagement_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_applicationfeeledgerentry
                ADD CONSTRAINT ledger_student_tenant_fk
                FOREIGN KEY (tenant_id, student_id)
                REFERENCES tenancy_membership (tenant_id, id);
            ALTER TABLE concierge_receipt
                ADD CONSTRAINT receipt_ledger_tenant_fk
                FOREIGN KEY (tenant_id, ledger_entry_id)
                REFERENCES concierge_applicationfeeledgerentry (tenant_id, id);
            """,
            """
            ALTER TABLE concierge_receipt DROP CONSTRAINT receipt_ledger_tenant_fk;
            ALTER TABLE concierge_applicationfeeledgerentry DROP CONSTRAINT ledger_student_tenant_fk;
            ALTER TABLE concierge_serviceengagement DROP CONSTRAINT engagement_student_tenant_fk;
            ALTER TABLE concierge_conversationmessage DROP CONSTRAINT message_sender_tenant_fk;
            ALTER TABLE concierge_conversationmessage DROP CONSTRAINT message_counselor_tenant_fk;
            ALTER TABLE concierge_conversationmessage DROP CONSTRAINT message_student_tenant_fk;
            ALTER TABLE concierge_notification DROP CONSTRAINT notification_recipient_tenant_fk;
            ALTER TABLE concierge_requiredaction DROP CONSTRAINT requiredaction_student_tenant_fk;
            ALTER TABLE concierge_manualoperation DROP CONSTRAINT manualop_actor_tenant_fk;
            ALTER TABLE concierge_manualoperation DROP CONSTRAINT manualop_roadmap_tenant_fk;
            ALTER TABLE concierge_roadmapitem DROP CONSTRAINT roadmap_owner_tenant_fk;
            ALTER TABLE concierge_roadmapitem DROP CONSTRAINT roadmap_student_tenant_fk;
            """,
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
