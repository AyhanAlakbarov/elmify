# funding_programcompetency -> funding_programstatement. Postgres keeps RLS
# policies across ALTER TABLE ... RENAME, so 0021's shared_catalog_select and
# catalog_ingestion_write survive; tests/tenancy/test_database_isolation.py's
# _SHARED_TABLES lists the new name and is what verifies that.
#
# The (program, term) unique constraint is dropped on purpose: identity is
# the sentence now, and two sentences may carry one label.
#
# AddField(kind, default="COMPETENCY") reclassifies every pre-existing
# `excerpt` value (now `text`) as though it were a verified verbatim
# sentence, which it was not -- the old rows were a model's paraphrase. This
# is vacuous today: no production rows exist for this table to backfill.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("funding", "0028_nationally_recognised_axis_and_whed_scheme"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="programcompetency", name="program_competency_term_uniq"
        ),
        migrations.RemoveConstraint(
            model_name="programcompetency", name="program_competency_requirement_valid"
        ),
        migrations.RenameModel(old_name="ProgramCompetency", new_name="ProgramStatement"),
        migrations.RenameField(model_name="programstatement", old_name="term", new_name="label"),
        migrations.RenameField(model_name="programstatement", old_name="excerpt", new_name="text"),
        migrations.AddField(
            model_name="programstatement",
            name="kind",
            field=models.CharField(
                choices=[
                    ("COMPETENCY", "Competency"), ("DOCUMENT", "Document"),
                    ("FORMAT", "Format"), ("LANGUAGE", "Language"), ("OTHER", "Other"),
                ],
                default="COMPETENCY",
                max_length=12,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="programstatement",
            name="program",
            field=models.ForeignKey(
                on_delete=models.deletion.CASCADE, related_name="statements", to="funding.program"
            ),
        ),
        migrations.AddConstraint(
            model_name="programstatement",
            constraint=models.CheckConstraint(
                condition=models.Q(("requirement__in", ("REQUIRED", "DESIRED"))),
                name="program_statement_requirement_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="programstatement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("kind__in", ("COMPETENCY", "DOCUMENT", "FORMAT", "LANGUAGE", "OTHER"))
                ),
                name="program_statement_kind_valid",
            ),
        ),
    ]
