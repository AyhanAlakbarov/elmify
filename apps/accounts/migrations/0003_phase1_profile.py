import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


IMMUTABILITY_SQL = """
CREATE FUNCTION public.accounts_reject_profile_version_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'student profile versions are immutable'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER accounts_profile_version_immutable
BEFORE UPDATE OR DELETE ON public.accounts_studentprofileversion
FOR EACH ROW EXECUTE FUNCTION public.accounts_reject_profile_version_mutation();
"""

REVERSE_IMMUTABILITY_SQL = """
DROP TRIGGER IF EXISTS accounts_profile_version_immutable
    ON public.accounts_studentprofileversion;
DROP FUNCTION IF EXISTS public.accounts_reject_profile_version_mutation();
"""


def refuse_schema_one_reverse(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM public.accounts_studentprofileversion "
            "WHERE schema_version = 1)"
        )
        if cursor.fetchone()[0]:
            raise RuntimeError("refusing reverse while schema-version 1 profiles exist")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_tenant_guards")]

    operations = [
        migrations.AlterField(
            model_name="studentprofileversion",
            name="student",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="tenancy.membership",
            ),
        ),
        migrations.AddField(
            model_name="studentprofileversion",
            name="schema_version",
            field=models.PositiveSmallIntegerField(default=0, db_default=0),
        ),
        migrations.AddConstraint(
            model_name="studentprofileversion",
            constraint=models.CheckConstraint(
                condition=models.Q(version__gt=0), name="profile_version_positive"
            ),
        ),
        migrations.AddConstraint(
            model_name="studentprofileversion",
            constraint=models.CheckConstraint(
                condition=models.Q(schema_version__in=(0, 1)),
                name="profile_schema_version_valid",
            ),
        ),
        migrations.RunSQL(IMMUTABILITY_SQL, REVERSE_IMMUTABILITY_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_schema_one_reverse),
    ]
