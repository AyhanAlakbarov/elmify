# The institution-safety screen is removed -- decision 2026-09-14, recorded in
# CLAUDE.md. Nothing ever read these three tables: `screen.py` was never built,
# and the whole system held one binding row.
#
# `kind`/`parent` go with them. They were added for one screen finding (YOK's
# exclusion list names institutes and chairs inside otherwise reputable
# universities, which an institution-keyed register cannot express), and outside
# the screen's own tests nothing set either. Leaving two columns on a core
# catalogue table to serve a deleted feature is the residue this change exists
# to avoid.
#
# The RLS policies on all three tables (0023, 0026) need no explicit teardown:
# DROP TABLE takes its policies with it. `catalog_ingestion` itself stays --
# ProgramStatement, ProgramCompetency and the awarding-institutions table are
# still written under it.
#
# DROP is safe because nothing is deployed: these tables exist in developer and
# CI databases only, and the register rehearsal ran against a throwaway database
# that was never promoted. There is no production data to preserve.
#
# WRITTEN BY HAND, and the shape matters. `makemigrations` emits RemoveField for
# each FK on a model it is about to DeleteModel. That is correct forwards and
# breaks backwards: reversing DeleteModel re-creates the table from the state
# that the RemoveFields already stripped, so create_model reads
# register_listing_subject_axis_audience_uniq, finds no `institution` field and
# raises FieldDoesNotExist. Ten tests in tests/migrations/ migrate backwards past
# this point, so they caught it. Deleting the models whole keeps their fields and
# constraints in the state DeleteModel captures, which is what makes the reverse
# re-create a complete table. The RemoveFields were never needed here in the
# first place -- they exist to break FK cycles, and none of these three models is
# pointed at by anything.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("funding", "0031_cv_directives_undecided_unreadable"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="institution", name="institution_kind_valid"),
        migrations.RemoveConstraint(model_name="institution", name="institution_parent_not_self"),
        migrations.RemoveField(model_name="institution", name="kind"),
        migrations.RemoveField(model_name="institution", name="parent"),
        migrations.DeleteModel(name="InstitutionIdentifier"),
        migrations.DeleteModel(name="RegisterCoverage"),
        migrations.DeleteModel(name="RegisterListing"),
    ]
