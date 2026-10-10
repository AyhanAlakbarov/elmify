from django.db import migrations


class Migration(migrations.Migration):

    # portals.0002 creates portals_application's (tenant_id, id) key; the
    # earliest edge that satisfies it, as 0009 explains.
    dependencies = [
        ("concierge", "0009_dashboard_fields"),
        ("portals", "0002_application"),
    ]

    operations = [
        # The composite guard portals/0015_reminder_item_tenant_guard.py puts on
        # its own nullable SET_NULL column: without it a notification could
        # name an application in another tenant.
        migrations.RunSQL(
            """
            ALTER TABLE concierge_notification
                ADD CONSTRAINT notification_application_tenant_fk
                FOREIGN KEY (tenant_id, application_id)
                REFERENCES portals_application (tenant_id, id);
            """,
            """
            ALTER TABLE concierge_notification
                DROP CONSTRAINT notification_application_tenant_fk;
            """,
        ),
    ]
