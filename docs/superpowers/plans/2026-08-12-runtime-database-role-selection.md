# Runtime Database Role Selection Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make `DATABASE_ROLE=runtime` select a dedicated non-owner PostgreSQL login and prove RLS through that real connection.

**Architecture:** Production selects credentials from one of two explicit role-specific pairs. Local and test settings retain their existing generic PostgreSQL credentials only when no role is selected. A separate `psycopg` connection uses the runtime settings to prove the login identity and default-deny RLS behavior.

**Tech Stack:** Python 3.12, Django 5.2, psycopg 3, pytest, PostgreSQL RLS.

## Global Constraints

- Production accepts only `DATABASE_ROLE=runtime` or `DATABASE_ROLE=migration`; missing, invalid, or incomplete role credentials fail closed.
- Runtime uses `POSTGRES_RUNTIME_USER` and `POSTGRES_RUNTIME_PASSWORD`; migrations use `POSTGRES_MIGRATION_USER` and `POSTGRES_MIGRATION_PASSWORD`; both share `POSTGRES_DB`, `POSTGRES_HOST`, and optional `POSTGRES_PORT`.
- Do not use `SET ROLE` to prove the runtime boundary. The proof opens a real PostgreSQL login connection.
- The runtime role is `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`, owns no protected table, and sees no rows until transaction-scoped `app.tenant_id` is set.
- Preserve current generic local/test `POSTGRES_USER` and `POSTGRES_PASSWORD` behavior only when `DATABASE_ROLE` is absent.
- Do not run AWS or Docker validation.

### Task 1: Add role-aware database configuration

**Files:**
- Create: `config/settings/database.py`
- Modify: `config/settings/base.py`
- Modify: `config/settings/production.py`
- Test: `tests/tenancy/test_database_settings.py`

**Interfaces:**
- Produces: `database_config(environ: Mapping[str, str], *, require_explicit_role: bool) -> dict[str, dict[str, object]]`
- Test seam: explicit environment mappings passed to `database_config`.

- [x] **Step 1: Write failing configuration tests**

Test runtime and migration pair selection, generic local fallback, and production rejection of missing, invalid, or incomplete role values.

- [x] **Step 2: Confirm RED**

Run: `uv run pytest tests/tenancy/test_database_settings.py -q`

Expected: FAIL because no role-aware settings builder exists.

- [x] **Step 3: Implement the minimal settings builder**

Use only the two supported role names and `django.core.exceptions.ImproperlyConfigured`; base calls it with `require_explicit_role=False`, production with `True`.

- [x] **Step 4: Confirm GREEN**

Run: `uv run pytest tests/tenancy/test_database_settings.py -q`

Expected: all configuration-selection tests pass.

- [x] **Step 5: Commit**

Commit: `git commit -m "fix: select database credentials by role"`

### Task 2: Provision and prove the runtime login

**Files:**
- Modify: `scripts/create_runtime_role.sql`
- Modify: `tests/tenancy/test_database_isolation.py`
- Modify: `docs/architecture/0001-runtime-and-boundaries.md`

**Interfaces:**
- Consumes: `database_config` and an actual temporary runtime role created by the migration-owner connection.
- Produces: an idempotent psql role-bootstrap contract using `runtime_role` and `runtime_password`; an integration test that connects with the selected runtime credentials.
- Test seam: a distinct `psycopg` connection built from `database_config`.

- [x] **Step 1: Write a failing real-login RLS test**

Create a temporary `LOGIN NOBYPASSRLS` role with a known password, build runtime credentials through `database_config`, then connect through psycopg. Assert `current_user`, no protected-table ownership, zero rows without `app.tenant_id`, and only the selected tenant inside a transaction-local setting.

- [x] **Step 2: Confirm RED**

Run: `uv run pytest tests/tenancy/test_database_isolation.py -q`

Expected: FAIL because the existing test only simulates a role with `SET ROLE`.

- [x] **Step 3: Harden bootstrap and replace the stand-in test**

Make the SQL consume psql `runtime_role` and `runtime_password` variables, create or harden the non-owner login role, and grant the existing runtime table privileges. Replace the `SET ROLE` fixture with the temporary-login psycopg test.

- [x] **Step 4: Document the production contract**

Record the runtime and migration environment variable pairs in the existing runtime-and-boundaries architecture decision. State that AWS secret injection remains Task 17.

- [x] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/tenancy/test_database_settings.py tests/tenancy/test_database_isolation.py -q
uv run pytest tests/tenancy -q
uv run ruff check .
uv run mypy apps config
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

Commit: `git commit -m "fix: select non-owner runtime database role"`
