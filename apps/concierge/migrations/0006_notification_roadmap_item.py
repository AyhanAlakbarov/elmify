from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Add the subject link with no default.

    No default is deliberate. concierge_notification is empty in every
    environment -- nothing is deployed, and PortalDesiredCount ships 0 so the
    escalation path that writes Notification has never run -- so this applies
    cleanly. If some environment does hold rows, it fails loudly with a NOT NULL
    violation rather than backfilling a wrong subject, and the right response is
    to backfill from RoadmapItem explicitly, not to supply a placeholder.
    """

    dependencies = [
        ("concierge", "0005_roadmap_item_agent_owner"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="roadmap_item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="concierge.roadmapitem",
            ),
        ),
    ]
