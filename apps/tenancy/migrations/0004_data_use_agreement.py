import django.db.models.deletion
import uuid
from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


GUARDS_SQL = """
ALTER TABLE public.tenancy_agencydatauseagreementversion
    ADD CONSTRAINT data_use_agreement_purposes_nonempty_array CHECK (
        jsonb_typeof(permitted_purposes) = 'array'
        AND jsonb_array_length(permitted_purposes) > 0
    ),
    ADD CONSTRAINT data_use_agreement_purposes_allowed CHECK (
        jsonb_typeof(permitted_purposes) <> 'array'
        OR permitted_purposes <@ '["EVALUATION", "PRODUCT_IMPROVEMENT", "MODEL_TRAINING"]'::jsonb
    ),
    ADD CONSTRAINT data_use_agreement_categories_nonempty_array CHECK (
        jsonb_typeof(eligible_categories) = 'array'
        AND jsonb_array_length(eligible_categories) > 0
    ),
    ADD CONSTRAINT data_use_agreement_categories_allowed CHECK (
        jsonb_typeof(eligible_categories) <> 'array'
        OR eligible_categories <@ '["STRUCTURED_PROFILE_FACTS", "RECOMMENDATION_DECISIONS",
                                  "APPLICATION_OUTCOMES", "DOCUMENT_STRUCTURE"]'::jsonb
    ),
    ADD CONSTRAINT data_use_agreement_creator_tenant_fk
        FOREIGN KEY (tenant_id, created_by_id)
        REFERENCES public.tenancy_membership (tenant_id, id);
ALTER TABLE public.tenancy_agencydatauseagreementversion ENABLE ROW LEVEL SECURITY;
CREATE POLICY agreement_tenant_select
    ON public.tenancy_agencydatauseagreementversion FOR SELECT
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE FUNCTION public.tenancy_reject_data_use_agreement_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'data-use agreement versions are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER tenancy_data_use_agreement_append_only
BEFORE UPDATE OR DELETE ON public.tenancy_agencydatauseagreementversion
FOR EACH ROW EXECUTE FUNCTION public.tenancy_reject_data_use_agreement_mutation();
"""

REVERSE_GUARDS_SQL = """
DROP TRIGGER IF EXISTS tenancy_data_use_agreement_append_only
    ON public.tenancy_agencydatauseagreementversion;
DROP FUNCTION IF EXISTS public.tenancy_reject_data_use_agreement_mutation();
DROP POLICY IF EXISTS agreement_tenant_select
    ON public.tenancy_agencydatauseagreementversion;
ALTER TABLE public.tenancy_agencydatauseagreementversion DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenancy_agencydatauseagreementversion
    DROP CONSTRAINT IF EXISTS data_use_agreement_creator_tenant_fk,
    DROP CONSTRAINT IF EXISTS data_use_agreement_categories_allowed,
    DROP CONSTRAINT IF EXISTS data_use_agreement_categories_nonempty_array,
    DROP CONSTRAINT IF EXISTS data_use_agreement_purposes_allowed,
    DROP CONSTRAINT IF EXISTS data_use_agreement_purposes_nonempty_array;
"""


def refuse_populated_reverse(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM public.tenancy_agencydatauseagreementversion)")
        if cursor.fetchone()[0]:
            raise RuntimeError("refusing reverse while agreement table is populated")


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0003_agency_branding")]

    operations = [
        migrations.CreateModel(
            name="AgencyDataUseAgreementVersion",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("agreement_id", models.UUIDField()),
                ("version", models.PositiveIntegerField()),
                ("agreement_reference", models.CharField(max_length=200)),
                ("permitted_purposes", models.JSONField()),
                ("eligible_categories", models.JSONField()),
                (
                    "lawful_basis_review_state",
                    models.CharField(
                        choices=[
                            ("NOT_REVIEWED", "Not reviewed"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                        ],
                        max_length=20,
                    ),
                ),
                ("effective_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="tenancy.membership",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="tenancy.agency",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=("tenant", "agreement_id", "-version"),
                        name="agreement_tenant_version_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tenant", "id"),
                        name="data_use_agreement_tenant_id_uniq",
                    ),
                    models.UniqueConstraint(
                        fields=("tenant", "agreement_id", "version"),
                        name="data_use_agreement_tenant_version_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(version__gt=0),
                        name="data_use_agreement_version_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            lawful_basis_review_state__in=(
                                "NOT_REVIEWED",
                                "APPROVED",
                                "REJECTED",
                            )
                        ),
                        name="data_use_agreement_review_state_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(revoked_at__isnull=True)
                        | models.Q(revoked_at__gte=models.F("effective_at")),
                        name="data_use_agreement_chronology",
                    ),
                ],
            },
        ),
        migrations.RunSQL(GUARDS_SQL, REVERSE_GUARDS_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_populated_reverse),
    ]
