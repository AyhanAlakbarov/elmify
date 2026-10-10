from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        # Minimal dependency, not the leaf makemigrations picked: it chose
        # tenancy.0009_membership_application_email, which forces tenancy fully
        # forward whenever documents is applied and breaks
        # tests/migrations/test_task7_migrations.py's ability to pin tenancy to
        # an older state -- the plan then has to unapply and reapply this
        # migration in one go, which Django refuses. The constraint below
        # touches only verifiedfact.supersedes, a self-FK, so documents' own
        # predecessor is the whole dependency. Same reasoning as
        # documents/migrations/0012_draft_funding_opportunity.py.
        ("documents", "0012_draft_funding_opportunity"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="verifiedfact",
            constraint=models.UniqueConstraint(
                condition=models.Q(("supersedes__isnull", False)),
                fields=("supersedes",),
                name="verifiedfact_one_superseder",
            ),
        ),
    ]
