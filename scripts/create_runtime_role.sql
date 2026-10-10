\set ON_ERROR_STOP on

-- ORDER: run this script BEFORE the first `migrate`, as the admin role. It needs
-- no tables. On PG16+ a non-superuser CREATEROLE role may alter, set the
-- password of, or revoke memberships from only a role it holds ADMIN OPTION on,
-- and creating a role grants that option to its creator alone. So whoever
-- creates runtime_engine/runtime_web is the only non-superuser that can finish
-- this script on them. Run first, the admin creates both and funding/0049's
-- CREATE ROLE is a no-op; run after migrate, the migration role created them
-- and every ALTER below fails. The script checks this and says so.

\if :{?migration_role}
\else
DO $$ BEGIN RAISE EXCEPTION 'migration_role psql variable is required'; END $$;
\endif

SELECT NULLIF(:'migration_role', '') IS NOT NULL AS bootstrap_variables_valid
\gset
\if :bootstrap_variables_valid
\else
DO $$ BEGIN RAISE EXCEPTION 'bootstrap variables must be non-empty'; END $$;
\endif

BEGIN;

-- The two role names are literal, not psql variables like migration_role:
-- runtime_engine (worker tasks) and runtime_web (agency-facing web tier) are
-- named by the grants and policies in apps/funding/migrations/0049_catalog_grants.py,
-- so they cannot be chosen at bootstrap time. That migration owns every table
-- and sequence grant; its CREATE ROLE is for dev/test databases and is a no-op
-- in production, where this script (run first, see ORDER above) created both.
-- This script makes them logins, strips anything else they carry, and grants
-- CONNECT, which needs the database name a migration does not know. Every statement below runs once per
-- role from one VALUES list, except \password, which psql takes per role.

-- The migration role owns every table and runs every migration. If it can
-- bypass RLS, tenant isolation is decided by how the database was bootstrapped
-- rather than by the policies. It is also why the erasure guard's function is
-- owned by a dedicated role and created by scripts/create_erasure_guard.sql,
-- not by this role: a control must not be blind or not depending on how the
-- database happened to be bootstrapped. And it must not be one of the two
-- runtime roles: the owner of every table holds every privilege on it, so the
-- catalogue revocation would be void. Refuse rather than warn.
SELECT EXISTS (
    SELECT FROM pg_roles
    WHERE rolname = :'migration_role' AND NOT rolsuper AND NOT rolbypassrls
      AND rolname NOT IN ('runtime_engine', 'runtime_web')
) AS migration_role_is_constrained
\gset
\if :migration_role_is_constrained
\else
DO $$ BEGIN RAISE EXCEPTION 'migration role must exist, be NOSUPERUSER NOBYPASSRLS, and not be runtime_engine or runtime_web'; END $$;
\endif

SELECT format('CREATE ROLE %I', role.name)
FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = role.name)
\gexec

-- Measured on PG 17: pg_has_role(..., 'MEMBER WITH ADMIN OPTION') is true for
-- the creating role and for a superuser, false for a CREATEROLE role that did
-- not create it (whose ALTER ROLE then fails "permission denied to alter role").
SELECT bool_and(pg_has_role(current_user, role.name, 'MEMBER WITH ADMIN OPTION'))
    AND (SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user)
    AS runtime_roles_administrable
FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)
\gset
\if :runtime_roles_administrable
\else
DO $$ BEGIN RAISE EXCEPTION 'this role cannot administer runtime_engine and runtime_web: run this script as the admin role BEFORE the first migrate, so the admin creates them (a role created by the migration role can be altered only by it or a superuser)'; END $$;
\endif

-- SUPERUSER, CREATEDB, REPLICATION and BYPASSRLS are asserted, not set: PG 17
-- lets only a role holding an attribute change it, even to NO, so setting them
-- would make this script superuser-only. Nobody below superuser can have set
-- them, and a role that carries one is refused rather than repaired.
SELECT format(
    'ALTER ROLE %I WITH LOGIN NOCREATEROLE NOINHERIT '
    'CONNECTION LIMIT -1 VALID UNTIL ''infinity''',
    role.name
)
FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)
\gexec
SELECT NOT EXISTS (
    SELECT FROM pg_roles
    WHERE rolname IN ('runtime_engine', 'runtime_web')
      AND (rolsuper OR rolcreatedb OR rolreplication OR rolbypassrls)
) AS runtime_attributes_constrained
\gset
\if :runtime_attributes_constrained
\else
DO $$ BEGIN RAISE EXCEPTION 'a runtime role is SUPERUSER, CREATEDB, REPLICATION or BYPASSRLS; a superuser must remove it'; END $$;
\endif
\password runtime_engine
\password runtime_web

SELECT format('ALTER ROLE %I RESET ALL', role.name)
FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)
\gexec
SELECT format(
    'ALTER ROLE %I IN DATABASE %I RESET ALL', role.rolname, database.datname
)
FROM pg_db_role_setting AS setting
JOIN pg_roles AS role ON role.oid = setting.setrole
JOIN pg_database AS database ON database.oid = setting.setdatabase
WHERE role.rolname IN ('runtime_engine', 'runtime_web')
\gexec

-- Removal as an action, not an absence: a membership granted by an older
-- script is database state, and deleting a GRANT from this file revokes nothing.
-- Above all runtime_web must never be a member of runtime_engine -- SET ROLE
-- needs no inherited attributes, so membership would make the catalogue
-- boundary a discipline instead of a boundary.
SELECT format(
    'REVOKE %I FROM %I GRANTED BY %I CASCADE',
    granted.rolname,
    member.rolname,
    grantor.rolname
)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted ON granted.oid = membership.roleid
JOIN pg_roles AS member ON member.oid = membership.member
JOIN pg_roles AS grantor ON grantor.oid = membership.grantor
WHERE member.rolname IN ('runtime_engine', 'runtime_web')
\gexec

SELECT NOT EXISTS (
    SELECT FROM pg_auth_members AS membership
    JOIN pg_roles AS member ON member.oid = membership.member
    WHERE member.rolname IN ('runtime_engine', 'runtime_web')
) AS runtime_memberships_cleared
\gset
\if :runtime_memberships_cleared
\else
DO $$ BEGIN RAISE EXCEPTION 'a runtime role retains inherited role membership'; END $$;
\endif

SELECT EXISTS (
    SELECT FROM pg_class AS relation
    JOIN pg_roles AS owner ON owner.oid = relation.relowner
    WHERE owner.rolname IN ('runtime_engine', 'runtime_web')
      AND relation.relrowsecurity
      AND relation.relkind IN ('r', 'p')
) AS runtime_owns_rls
\gset
\if :runtime_owns_rls
DO $$ BEGIN RAISE EXCEPTION 'a runtime role owns an RLS-enabled table'; END $$;
\endif

SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I', current_database(), role.name
)
FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)
\gexec

-- USAGE ON SCHEMA public: in production the migration role does not own the
-- schema (a superuser does), so funding/0049_catalog_grants.py's own GRANT
-- runs as a non-owner and only warns "no privileges were granted for public"
-- -- both roles end up reading it via PUBLIC's default grant instead of this
-- one. The admin, run here before any migration, is the one connection that
-- actually owns public (or is a superuser), so this is the grant that takes.
SELECT format(
    'GRANT USAGE ON SCHEMA public TO %I', role.name
)
FROM (VALUES ('runtime_engine'), ('runtime_web')) AS role(name)
\gexec

COMMIT;
