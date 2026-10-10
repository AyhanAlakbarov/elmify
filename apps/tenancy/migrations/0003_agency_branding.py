from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0002_rls")]

    operations = [
        migrations.AddField(
            model_name="agency",
            name="brand_logo_url",
            field=models.URLField(blank=True, max_length=2048),
        ),
        migrations.AddField(
            model_name="agency",
            name="brand_primary_color",
            field=models.CharField(
                default="#1d4ed8",
                max_length=7,
                validators=[django.core.validators.RegexValidator("^#[0-9A-Fa-f]{6}$")],
            ),
        ),
        migrations.AddConstraint(
            model_name="agency",
            constraint=models.CheckConstraint(
                condition=models.Q(("brand_primary_color__regex", "^#[0-9A-Fa-f]{6}$")),
                name="agency_valid_brand_color",
            ),
        ),
    ]
