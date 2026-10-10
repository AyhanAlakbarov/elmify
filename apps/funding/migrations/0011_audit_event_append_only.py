from django.db import migrations

_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION funding_auditevent_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event rows are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER funding_auditevent_no_update
    BEFORE UPDATE ON funding_auditevent
    FOR EACH ROW EXECUTE FUNCTION funding_auditevent_append_only();

CREATE TRIGGER funding_auditevent_no_delete
    BEFORE DELETE ON funding_auditevent
    FOR EACH ROW EXECUTE FUNCTION funding_auditevent_append_only();
"""

_DROP_SQL = """
DROP TRIGGER IF EXISTS funding_auditevent_no_update ON funding_auditevent;
DROP TRIGGER IF EXISTS funding_auditevent_no_delete ON funding_auditevent;
DROP FUNCTION IF EXISTS funding_auditevent_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("funding", "0010_review_hardening")]
    operations = [migrations.RunSQL(_TRIGGER_SQL, reverse_sql=_DROP_SQL)]
