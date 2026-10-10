# Three additive changes for the 2026-09-13 "CV follows the page" design.
# The confidence check constraint is dropped and re-added because Postgres
# CHECK constraints are immutable: UNDECIDED is a new value the old one
# rejects. No rows carry UNDECIDED yet, so the swap is safe at any time.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("funding", "0029_program_statement"),
        ("funding", "0030_program_awarding_institutions_rls"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="program", name="program_cv_format_confidence_valid"
        ),
        migrations.AlterField(
            model_name="program",
            name="cv_format_confidence",
            field=models.CharField(
                choices=[
                    ("VERIFIED", "Verified"), ("EXTRACTED", "Extracted"),
                    ("UNVERIFIED", "Unverified"), ("UNDECIDED", "Undecided"),
                ],
                default="UNVERIFIED",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="program",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("cv_format_confidence__in", ["VERIFIED", "EXTRACTED", "UNVERIFIED", "UNDECIDED"])
                ),
                name="program_cv_format_confidence_valid",
            ),
        ),
        migrations.AddField(
            model_name="program",
            name="cv_directives",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="officialsourcesnapshot",
            name="unreadable",
            field=models.BooleanField(default=False),
        ),
    ]
