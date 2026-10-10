"""RLS and tenant guards for the demand-cell tables (build item 14).

Five tenant tables, ENABLE + FORCE with the `tenant_isolation` policy text every
other tenant migration uses (documents/0017, research/0002). Each student or
intra-tenant edge carries a composite `(tenant_id, <fk>_id)` foreign key, so a
row can never point at another tenant's membership, profile version, wallet or
tap even when the ORM filter is bypassed -- the pattern of
documents/0017_narrative_input_tenant_guards.

SearchTap's edges to funding (`run_id`, `pack_version_id`) are NOT here:
research may not depend on funding (research/0003's docstring), so
funding/0054_pack_coverage adds them, depending on this migration.

`research_areasweep` is shared catalogue in the research/0012 shape exactly:
ENABLE (no FORCE), `shared_catalog_select`, `runtime_engine_write`, the engine
granted DML and `runtime_web` revoked -- the catalogue boundary is a GRANT
(tests/tenancy/test_catalog_grants.py), and default privileges would otherwise
hand the new table to the web tier. The two roles are ensured here for the same
reason research/0012 gives: this may run before or after funding/0049.
"""

from django.db import migrations

TENANT_TABLES = (
    "research_profilecellselection",
    "research_searchwallet",
    "research_searchtap",
    "research_walletcharge",
    "research_cellcoverage",
)

RLS_SQL = "".join(
    f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON {table}
USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
"""
    for table in TENANT_TABLES
)

REVERSE_RLS_SQL = "".join(
    f"""
DROP POLICY IF EXISTS tenant_isolation ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
    for table in reversed(TENANT_TABLES)
)

#: (table, constraint, local column, referenced table)
_GUARDS = (
    ("research_profilecellselection", "profilecellselection_student_tenant_fk",
     "student_id", "tenancy_membership"),
    ("research_profilecellselection", "profilecellselection_profile_tenant_fk",
     "profile_version_id", "accounts_studentprofileversion"),
    ("research_searchwallet", "searchwallet_student_tenant_fk",
     "student_id", "tenancy_membership"),
    ("research_searchtap", "searchtap_student_tenant_fk",
     "student_id", "tenancy_membership"),
    ("research_searchtap", "searchtap_wallet_tenant_fk",
     "wallet_id", "research_searchwallet"),
    ("research_walletcharge", "walletcharge_wallet_tenant_fk",
     "wallet_id", "research_searchwallet"),
    ("research_walletcharge", "walletcharge_tap_tenant_fk",
     "tap_id", "research_searchtap"),
)

GUARD_SQL = "".join(
    f"""
ALTER TABLE {table}
    ADD CONSTRAINT {name}
    FOREIGN KEY (tenant_id, {column})
    REFERENCES {target} (tenant_id, id);
"""
    for table, name, column, target in _GUARDS
)

REVERSE_GUARD_SQL = "".join(
    f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name};\n"
    for table, name, _column, _target in reversed(_GUARDS)
)

_SHARED = "research_areasweep"

_ENSURE_ROLES = """
DO $$ BEGIN
    IF (SELECT count(*) FROM pg_roles
         WHERE rolname IN ('runtime_engine', 'runtime_web')) < 2
       AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'runtime_engine / runtime_web do not both exist: run '
            'scripts/create_runtime_role.sql as the admin role, then re-run the migration';
    END IF;
END $$;
""" + "".join(
    f"""
DO $$ BEGIN
    CREATE ROLE {role} NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
"""
    for role in ("runtime_engine", "runtime_web")
)

SHARED_SQL = _ENSURE_ROLES + f"""
ALTER TABLE public.{_SHARED} ENABLE ROW LEVEL SECURITY;
CREATE POLICY shared_catalog_select ON public.{_SHARED}
    FOR SELECT USING (true);
CREATE POLICY runtime_engine_write ON public.{_SHARED}
    FOR ALL TO runtime_engine USING (true) WITH CHECK (true);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.{_SHARED} TO runtime_engine;
REVOKE ALL ON public.{_SHARED} FROM runtime_web;
"""

REVERSE_SHARED_SQL = f"""
DROP POLICY IF EXISTS runtime_engine_write ON public.{_SHARED};
DROP POLICY IF EXISTS shared_catalog_select ON public.{_SHARED};
ALTER TABLE public.{_SHARED} DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("research", "0013_demand_cells"),
        ("accounts", "0001_initial"),
        ("tenancy", "0002_rls"),
    ]

    operations = [
        migrations.RunSQL(GUARD_SQL, REVERSE_GUARD_SQL),
        migrations.RunSQL(RLS_SQL, REVERSE_RLS_SQL),
        migrations.RunSQL(SHARED_SQL, REVERSE_SHARED_SQL),
    ]
