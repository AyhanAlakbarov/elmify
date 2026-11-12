"""Existing cards take their fee state from their candidate's fee copy.

None -> UNKNOWN (the default 0037 already wrote), 0 -> NONE, more -> OPEN.
Both tables are FORCE RLS and a migration sets no app.tenant_id, so the
UPDATE would silently match nothing for the (NOBYPASSRLS) migration role;
FORCE is lifted around it and put back, as concierge/0016 does.

No ("funding", "0057_dashboard_fields") dependency, on purpose: portals depends
on funding only at 0001, and a later edge turns the mixed plans in
tests/migrations (test_task7_migrations, test_audit_event_actor_kind, the
holder backfill) into InvalidMigrationPlan -- measured, 8 failures. The block
instead runs only when the fee column exists: every existing database has it
(funding/0057 is on master), and a fresh one has no cards to backfill.
"""

from django.db import migrations

FORWARD = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'funding_recommendationcandidate'
       AND column_name = 'application_fee'
  ) THEN
    ALTER TABLE portals_application NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE funding_recommendationcandidate NO FORCE ROW LEVEL SECURITY;
    UPDATE portals_application AS app
       SET fee_state = CASE WHEN candidate.application_fee = 0 THEN 'NONE' ELSE 'OPEN' END
      FROM funding_recommendationcandidate AS candidate
     WHERE candidate.id = app.candidate_id
       AND candidate.application_fee IS NOT NULL;
    ALTER TABLE funding_recommendationcandidate FORCE ROW LEVEL SECURITY;
    ALTER TABLE portals_application FORCE ROW LEVEL SECURITY;
  END IF;
END
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("portals", "0037_application_fee_state")]

    operations = [migrations.RunSQL(FORWARD, migrations.RunSQL.noop)]
