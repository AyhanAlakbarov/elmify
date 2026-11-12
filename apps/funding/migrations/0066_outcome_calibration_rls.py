"""RLS and grants for funding_outcomecalibrationrecord.

RLS class: SHARED CATALOG. Synced by `runtime_engine` from non-redacted decided applications;
`runtime_web` holds no table grant at all.
"""

from django.db import migrations

TABLE = "funding_outcomecalibrationrecord"

RLS_SQL = f"""
ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{TABLE}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{TABLE}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO runtime_engine;
REVOKE ALL ON public.{TABLE} FROM runtime_web;
"""

REVERSE_RLS_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{TABLE};
DROP POLICY IF EXISTS shared_catalog_select ON public.{TABLE};
ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("funding", "0065_probability_and_outcome_calibration")]
    operations = [migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL)]
