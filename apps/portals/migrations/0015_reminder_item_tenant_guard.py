from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("portals", "0014_reminder_ladder"),
    ]

    operations = [
        # The composite guard exception_item already carries (0004_escalation).
        # Without it, reminder_item could name a RoadmapItem in another
        # tenant -- structurally impossible for exception_item, merely
        # unlikely for this one, until now.
        migrations.RunSQL(
            """
            ALTER TABLE portals_application
                ADD CONSTRAINT portal_app_reminder_tenant_fk
                FOREIGN KEY (tenant_id, reminder_item_id)
                REFERENCES concierge_roadmapitem (tenant_id, id);
            """,
            """
            ALTER TABLE portals_application DROP CONSTRAINT portal_app_reminder_tenant_fk;
            """,
        ),
    ]
