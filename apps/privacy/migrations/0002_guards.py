"""Both runtime roles read legal documents; only the owner writes them.

Same shape as research/0013's platform-agency marker, and for the same reason:
the text a student accepted must not be editable by the web tier. No RLS -- the
table holds no person and every tenant shows the same documents. Depends on
funding/0049, whose default privileges grant DML on every new table to both
runtime roles; this migration takes the writes back.
"""

from django.db import migrations

TABLE = "privacy_legaldocument"

FORWARD = f"""
REVOKE ALL ON public.{TABLE} FROM runtime_engine, runtime_web;
GRANT SELECT ON public.{TABLE} TO runtime_engine, runtime_web;

CREATE FUNCTION public.privacy_legaldocument_owner_only() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF NOT pg_has_role(
        current_user, (SELECT relowner FROM pg_class WHERE oid = TG_RELID), 'USAGE'
    ) THEN
        RAISE EXCEPTION 'only the owner of % may write it: run manage.py '
            'publish_legal_documents with DATABASE_ROLE=migration', TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER privacy_legaldocument_owner_only
    BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{TABLE}
    FOR EACH STATEMENT EXECUTE FUNCTION public.privacy_legaldocument_owner_only();
"""

REVERSE = f"""
DROP TRIGGER IF EXISTS privacy_legaldocument_owner_only ON public.{TABLE};
DROP FUNCTION IF EXISTS public.privacy_legaldocument_owner_only();
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{TABLE} TO runtime_engine, runtime_web;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("privacy", "0001_initial"),
        ("funding", "0049_catalog_grants"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
