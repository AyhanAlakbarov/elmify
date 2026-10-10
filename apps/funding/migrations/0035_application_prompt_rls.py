# funding_applicationprompt is shared-catalog data (task-5 report, fix round 1, finding 1):
# every tenant's letter generation reads the same programme prompt, and Task 5 is the first
# writer to put page-derived content in it. It shipped in 0033 with no RLS -- absent from
# _SHARED_TABLES and unprotected against the runtime role's blanket INSERT/UPDATE/DELETE grant
# (scripts/create_runtime_role.sql) -- unlike every other shared-catalog table (pattern:
# 0021_program_competency_rls.py). Every writer of ApplicationPrompt (load_application_prompts,
# prompt_resolution.py, letter_shape.py::apply_derived_shape) is catalog ingestion, either an
# explicit management command or reached only through apps.documents.program_rules.py's
# read_and_derive, which has no production caller today -- so this closes the gap without
# breaking any writer.
from django.db import migrations

TABLE = "funding_applicationprompt"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY catalog_ingestion_write ON public.{TABLE}
    FOR ALL TO catalog_ingestion USING (true) WITH CHECK (true);
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS catalog_ingestion_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('funding', '0034_letter_shape'),
    ]

    operations = [
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
    ]
