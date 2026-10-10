"""RegisterEntry -- the closed-list denominator -- and the classifier's four
columns on Organisation.

The RLS block is the same shape as research/0005's for the fetch engine and the
shape funding/0044 uses for register tables: named `catalog_ingestion` role,
every tenant reads the list, only the ingestion role writes it. A shared-catalog
table without this block is readable by nobody under the runtime role, which no
test can see (CLAUDE.md, "Row-level security").
Numbered after the fetch engine's 0004-0006, on whose branch this is built.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models

_TABLE = "research_registerentry"

RLS_SQL = f"""
ALTER TABLE public.{_TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{_TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{_TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{_TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{_TABLE};
ALTER TABLE public.{_TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0005_fetch_engine_rls"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation", name="funds_students",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="organisation", name="classified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="organisation", name="classified_by",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="organisation", name="classifier_confidence",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="RegisterEntry",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("register", models.CharField(max_length=40)),
                ("external_key", models.CharField(max_length=120)),
                ("name", models.CharField(max_length=300)),
                ("city", models.CharField(blank=True, default="", max_length=120)),
                ("contact_domain", models.CharField(blank=True, default="", max_length=253)),
                ("resolution", models.CharField(choices=[("RESOLVED", "Resolved"), ("UNRESOLVED", "Unresolved")], max_length=12)),
                ("first_seen", models.DateTimeField(auto_now_add=True)),
                ("last_seen", models.DateTimeField()),
                ("organisation", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="register_entries", to="research.organisation")),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("register", "external_key"), name="register_entry_key_uniq")],
                "indexes": [models.Index(fields=("register", "resolution"), name="register_entry_res_idx")],
            },
        ),
        migrations.RunSQL(RLS_SQL, reverse_sql=REVERSE_RLS_SQL),
    ]
