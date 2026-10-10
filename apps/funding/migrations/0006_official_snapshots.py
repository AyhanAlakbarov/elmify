import uuid

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
import django.db.models.deletion


TABLE = "funding_officialsourcesnapshot"
CATALOG_TABLES = (
    "funding_institution",
    "funding_program",
    "funding_fundingopportunity",
    "funding_fundingbenefit",
    "funding_costcomponent",
    "funding_benefitrule",
    "funding_officialsource",
    "funding_officialevidenceclaim",
    "funding_institution_evidence_claims",
    "funding_program_evidence_claims",
    "funding_fundingopportunity_programs",
    "funding_fundingopportunity_evidence_claims",
    "funding_fundingbenefit_evidence_claims",
    "funding_costcomponent_evidence_claims",
    "funding_benefitrule_evidence_claims",
)


def refuse_populated_reverse(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM public.{TABLE})")
        if cursor.fetchone()[0]:
            raise RuntimeError("refusing reverse while official snapshots exist")


RLS_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'catalog_ingestion') THEN
        CREATE ROLE catalog_ingestion NOLOGIN;
    END IF;
END
$$;
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR INSERT TO catalog_ingestion WITH CHECK (true);
"""
RLS_SQL += "\n".join(
    f"""
    CREATE POLICY catalog_ingestion_write ON public.{table}
        FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
    """
    for table in CATALOG_TABLES
)


REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""
REVERSE_RLS_SQL += "\n".join(
    f"DROP POLICY IF EXISTS catalog_ingestion_write ON public.{table};" for table in CATALOG_TABLES
)


class Migration(migrations.Migration):
    dependencies = [("funding", "0005_recommendation_dispatch")]

    operations = [
        migrations.CreateModel(
            name="OfficialSourceSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("s3_key", models.CharField(max_length=2048)),
                ("s3_version_id", models.CharField(max_length=255)),
                ("sha256", models.CharField(max_length=64)),
                ("final_url", models.URLField(max_length=2048)),
                ("redirect_chain", models.JSONField(default=list)),
                ("retrieved_at", models.DateTimeField()),
                ("admissions_cycle", models.CharField(max_length=50)),
                ("content_type", models.CharField(max_length=100)),
                ("byte_size", models.PositiveBigIntegerField()),
                (
                    "retrieval_status",
                    models.CharField(
                        choices=[
                            ("CURRENT", "Current"),
                            ("STALE", "Stale"),
                            ("BLOCKED", "Blocked"),
                            ("FAILED", "Failed"),
                        ],
                        default="CURRENT",
                        max_length=20,
                    ),
                ),
                ("dom_object_key", models.CharField(blank=True, max_length=2048, null=True)),
                ("screenshot_object_key", models.CharField(blank=True, max_length=2048, null=True)),
                ("render_status", models.CharField(blank=True, max_length=20, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="funding.officialsource"
                    ),
                ),
                (
                    "supersedes",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="replacements",
                        to="funding.officialsourcesnapshot",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source", "sha256"), name="snapshot_source_sha256_uniq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(byte_size__gte=0), name="snapshot_byte_size_nonnegative"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            retrieval_status__in=("CURRENT", "STALE", "BLOCKED", "FAILED")
                        ),
                        name="snapshot_retrieval_status_valid",
                    ),
                ]
            },
        ),
        migrations.AddField(
            model_name="officialevidenceclaim",
            name="snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="funding.officialsourcesnapshot",
            ),
        ),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
