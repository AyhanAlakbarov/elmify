"""The catalogue grant surface: an agency connection cannot read the catalogue.

2026-09-25 catalog-read-split design, §4. Two fixed roles, split by caller:

- `runtime_engine` (workers): DML on every table, and the catalogue's writer --
  every `catalog_ingestion_write` policy is repointed to it and renamed
  `runtime_engine_write`, each keeping its own command (`ALTER POLICY ... TO`
  cannot change a command, so nothing is widened).
- `runtime_web` (the agency-facing web tier): DML on every table EXCEPT the
  shared catalogue, where it holds no privilege at all. The mechanism is GRANT,
  not RLS: an absent grant fails closed with `permission denied`, where a policy
  returning zero rows looks exactly like an empty table.

The catalogue list is read from `pg_policies` (`shared_catalog_select`) at run
time, never written out here: a literal list goes stale the day a catalogue
table is added. Default privileges grant every FUTURE table to both roles,
because tenant tables need that, so a new catalogue table becomes readable by
`runtime_web` until its own migration revokes it --
`tests/tenancy/test_catalog_grants.py` fails until it does. That test, not a
default privilege, is the guard.

`runtime_web` is never made a member of `runtime_engine`: SET ROLE needs no
inherited attributes, so membership would make the boundary a discipline.

The grants live here rather than in `scripts/create_runtime_role.sql` because a
grant that exists only in a psql script is invisible to every test. The script
still makes the two roles LOGIN with passwords and grants CONNECT.

Who creates the two roles depends on who runs this. A SUPERUSER (dev, CI, the
test database) gets them created here NOLOGIN if absent -- cluster-global, so
race-safely. Anyone else -- production's `tehsil_migration` -- is refused
before anything is created, when either role is missing: "run
scripts/create_runtime_role.sql as the admin role, then re-run the migration".
Letting a non-superuser create them would be permanent: on PG16+ only a role
holding the ADMIN OPTION may ALTER a role, and a creator is granted that
implicitly, so the admin bootstrap could then never make them logins, set their
passwords or clear their memberships. `scripts/deploy.sh` runs the migration
straight after the stack deploy, so the first production deploy reaches this
refusal unless the bootstrap already ran -- which is the runbook's order
(docs/runbooks/deploy.md, step 4).

`catalog_ingestion` is dropped: it was a name in a policy with nobody able to be
it. Roles are cluster-global, so another database on the same cluster may still
have policies naming it; then DROP ROLE fails, the role is left for that
database, and this one is asserted to reference it nowhere.

EXECUTE on `user_has_active_membership` is not granted here and cannot be: the
function is created after migrations, and owned by `tehsil_erasure_guard`, by
`scripts/create_erasure_guard.sql`, which grants it to `runtime_engine` only
(the worker's `execute_due_erasures` is its one caller). No other function needs a grant (trigger functions are executable by
PUBLIC and are checked at CREATE TRIGGER, not when they fire).
"""

from django.db import migrations

_ROLES = "runtime_engine, runtime_web"

#: GRANT USAGE ON SCHEMA public below works as written only when the runner
#: owns the schema (a superuser in dev/test/CI). In production the migration
#: role does not own `public`, so that GRANT only warns "no privileges were
#: granted for public" and grants nothing -- both roles read the schema via
#: PUBLIC's default USAGE grant instead. `scripts/create_runtime_role.sql`,
#: run by the admin before the first migrate, carries the GRANT that actually
#: takes in production; this one is kept so a superuser-run dev/test/CI
#: database is self-contained without also running that script.
_ENSURE_ROLES = (
    """
DO $$ BEGIN
    IF (SELECT count(*) FROM pg_roles
         WHERE rolname IN ('runtime_engine', 'runtime_web')) < 2
       AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
        RAISE EXCEPTION 'runtime_engine / runtime_web do not both exist: run '
            'scripts/create_runtime_role.sql as the admin role, then re-run the migration';
    END IF;
END $$;
"""
    + "".join(
        f"""
DO $$ BEGIN
    CREATE ROLE {role} NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
"""
        for role in ("runtime_engine", "runtime_web")
    )
)

#: Sequences owned by a catalogue table: serial (deptype 'a') or identity ('i').
_CATALOGUE_SEQUENCES = """
    SELECT sequence.oid::regclass
      FROM pg_class AS sequence
      JOIN pg_depend AS dep
        ON dep.objid = sequence.oid
       AND dep.classid = 'pg_class'::regclass
       AND dep.refclassid = 'pg_class'::regclass
      JOIN pg_class AS owner ON owner.oid = dep.refobjid
     WHERE sequence.relkind = 'S'
       AND owner.relname IN (
           SELECT tablename FROM pg_policies
            WHERE schemaname = 'public' AND policyname = 'shared_catalog_select')
"""

FORWARD = (
    _ENSURE_ROLES
    + f"""
GRANT USAGE ON SCHEMA public TO {_ROLES};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_ROLES};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_ROLES};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_ROLES};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO {_ROLES};

DO $$
DECLARE
    name text;
    seq regclass;
BEGIN
    FOR name IN
        SELECT tablename FROM pg_policies
         WHERE schemaname = 'public' AND policyname = 'shared_catalog_select'
    LOOP
        EXECUTE format('REVOKE ALL ON public.%I FROM runtime_web', name);
    END LOOP;
    FOR seq IN {_CATALOGUE_SEQUENCES}
    LOOP
        EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM runtime_web', seq);
    END LOOP;

    FOR name IN
        SELECT tablename FROM pg_policies
         WHERE schemaname = 'public' AND policyname = 'catalog_ingestion_write'
    LOOP
        EXECUTE format(
            'ALTER POLICY catalog_ingestion_write ON public.%I TO runtime_engine', name
        );
        EXECUTE format(
            'ALTER POLICY catalog_ingestion_write ON public.%I RENAME TO runtime_engine_write',
            name
        );
    END LOOP;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_ingestion') THEN
        BEGIN
            DROP ROLE catalog_ingestion;
        EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE 'catalog_ingestion kept: another database on this cluster '
                'still depends on it';
        END;
    END IF;
    IF EXISTS (
        SELECT FROM pg_shdepend AS dep
          JOIN pg_roles AS role ON role.oid = dep.refobjid
         WHERE role.rolname = 'catalog_ingestion'
           AND dep.dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
    ) THEN
        RAISE EXCEPTION 'this database still references catalog_ingestion';
    END IF;
END $$;
"""
)

# Back to the pre-migration state: no grants for either role (the bootstrap no
# longer grants any), and catalog_ingestion as the writer. The two runtime roles
# are not dropped -- they are cluster-global and other databases use them.
REVERSE = f"""
DO $$ BEGIN
    CREATE ROLE catalog_ingestion NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;

DO $$
DECLARE
    name text;
BEGIN
    FOR name IN
        SELECT tablename FROM pg_policies
         WHERE schemaname = 'public' AND policyname = 'runtime_engine_write'
    LOOP
        EXECUTE format(
            'ALTER POLICY runtime_engine_write ON public.%I TO catalog_ingestion', name
        );
        EXECUTE format(
            'ALTER POLICY runtime_engine_write ON public.%I RENAME TO catalog_ingestion_write',
            name
        );
    END LOOP;
END $$;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_ROLES};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE USAGE, SELECT ON SEQUENCES FROM {_ROLES};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_ROLES};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {_ROLES};
REVOKE USAGE ON SCHEMA public FROM {_ROLES};
"""


class Migration(migrations.Migration):
    # Deliberately NOT every app's leaf. Tests roll one app back while every
    # other app stays at its head (tests/migrations/test_task7_migrations.py,
    # test_audit_event_actor_kind.py, test_task9_ingestion_migrations.py); a
    # migration depending on all leaves makes each of those plans both forward
    # and backward, which Django refuses (InvalidMigrationPlan, measured: 7
    # failures). Nothing is lost: tables that exist when this runs get the
    # GRANT ... ON ALL TABLES, and any table created after it, in any app, by
    # the same migration role gets the default privileges. The dependencies
    # are the two apps whose catalogue policies this rewrites.
    dependencies = [
        ("funding", "0048_merge_20260925_0838"),
        ("research", "0009_site_job_record_rls"),
    ]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
