from django.db import migrations, models


class Migration(migrations.Migration):
    """Written by hand: makemigrations asks interactively whether a field was renamed."""

    dependencies = [("documents", "0021_transcript_reading_tenant_guards")]

    operations = [
        migrations.RenameField("transcriptreading", "uncertain", "highlights"),
        migrations.AddField(
            "transcriptreading", "key_numbers", models.JSONField(default=dict)
        ),
    ]
