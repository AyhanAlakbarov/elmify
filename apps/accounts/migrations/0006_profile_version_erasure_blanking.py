"""Let erasure blank a profile version's snapshot, and nothing else.

0003's trigger refused every UPDATE, and apps/audit/redaction.py blanks
`snapshot`, so every student holding a profile version failed erasure with
"student profile versions are immutable" -- locked out at request time and
never erased. The trigger now admits exactly one change: `snapshot` set to `{}`
(redaction.py's `_empty_value` for a JSONField) with every other column as it
was. A content edit, any other column, and DELETE are refused as before.

Not a session flag erasure sets: any connection can SET a custom GUC, which
would make immutability a convention. The admitted change can only destroy a
snapshot, never forge one. Comparing `to_jsonb(NEW) - 'snapshot'` rather than
naming columns means a column added later is covered without touching this --
except a GENERATED ... STORED column, which a BEFORE trigger sees as NULL in NEW,
so blanking would be refused and erasure would fail loudly.
"""

from django.db import migrations

_REFUSE = """
    RAISE EXCEPTION 'student profile versions are immutable'
        USING ERRCODE = 'integrity_constraint_violation';
"""

FORWARD = f"""
CREATE OR REPLACE FUNCTION public.accounts_reject_profile_version_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.snapshot = '{{}}'::jsonb
       AND (to_jsonb(NEW) - 'snapshot') = (to_jsonb(OLD) - 'snapshot') THEN
        RETURN NEW;
    END IF;
{_REFUSE}
END;
$$;
"""

# 0003's body, equivalent (the interpolation adds blank lines around the RAISE).
REVERSE = f"""
CREATE OR REPLACE FUNCTION public.accounts_reject_profile_version_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
{_REFUSE}
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_profile_schema_version_3")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
