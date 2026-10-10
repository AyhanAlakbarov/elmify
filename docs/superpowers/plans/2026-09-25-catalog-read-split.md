# Splitting `runtime` by caller — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agency's database connection cannot read the catalogue of programmes and scholarships at all, while the worker that builds it still can — and an agency still sees its students' packs, links and reasons in full.

**Architecture:** Replace the single `runtime` role with `runtime_engine` (worker tasks: catalogue read, telemetry write) and `runtime_web` (the agency-facing tier: tenant tables only, no catalogue grant). Enforcement is a table `GRANT`, not RLS — an absent grant fails closed and loudly. The one live request path that reads the catalogue today, packet minting, copies what it needs onto the tenant-scoped packet at mint time, the way the recommendation pack already does.

**Tech Stack:** Django 5.2, PostgreSQL, psycopg 3, CloudFormation, pytest with the repo's test DB.

**Spec:** `docs/superpowers/specs/2026-09-25-catalog-read-split-design.md` — read it before Task 1, especially §4 (the role table and the six task definitions), §7 (why no ordinary test can prove any of this) and §11 (the decided copy-forward and its narrowed scope).

**Base branch:** `claude/catalog-read-split`, forked from master at the ten-PR queue merge. Work in a fresh worktree. Test database: `POSTGRES_DB=tehsil_catalog_split` — never share a test DB between sessions.

## Global Constraints

- **The mechanism is `GRANT`, never RLS.** RLS stays exactly as it is for tenant isolation. Do not express "may this connection read the catalogue" as a policy.
- **No test in this repo can prove a grant by default.** The test role is a superuser and bypasses grants and RLS alike. Every assertion about a role's surface must connect **as that role**, in the shape of `runtime_connection` (`tests/conftest.py:117`). A test that passes under the default role proves nothing.
- **Never `GRANT runtime_engine TO runtime_web`.** Role attributes are not inherited through membership, but `SET ROLE` does not need them to be (CLAUDE.md, the erasure-guard lesson). Membership turns the boundary into a discipline.
- **An unrecognised `DATABASE_ROLE` must raise `ImproperlyConfigured`.** `runtime` is removed, not aliased — a task definition that was missed must fail at boot, not connect as something.
- **Never run `ruff format`** in this repo — it is a lint-only gate (CLAUDE.md).
- **After every task:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `POSTGRES_DB=tehsil_catalog_split uv run pytest`, and `uv run python manage.py makemigrations --check --dry-run` must stay clean.
- **Derive the catalogue table list from `pg_policies` on a migrated database**, never by grepping migrations: several tables named in migration text were later dropped (`funding_registerlisting`, `funding_institutionidentifier` went with the 2026-09-14 register removal).

---

## File Structure

| file | responsibility |
|---|---|
| `scripts/create_runtime_role.sql` (modify) | creates `runtime_engine` and `runtime_web` with their grants; keeps its existing refusal to bootstrap against a superuser or `BYPASSRLS` migration role |
| `config/settings/database.py` (modify) | accepts `runtime_engine`, `runtime_web`, `migration`; rejects `runtime` |
| `tests/conftest.py` (modify) | `runtime_connection` gains a per-role variant; `rls_enforced_orm` likewise |
| `apps/portals/models.py` (modify) | the packet row gains the copied statements |
| `apps/portals/packets.py` (modify) | `mint_packet`/`build_kit` write the copy; readers use it |
| `apps/portals/migrations/00NN_packet_statements.py` (new) | the column |
| `apps/research/migrations/00NN_catalog_grants.py` (new) | repoint write policies to `runtime_engine`, drop `catalog_ingestion`, revoke catalogue `SELECT` from `runtime_web` |
| `infra/template.yaml` (modify) | six `DATABASE_ROLE` values, two new secrets and their IAM, `RetryDueFetchesRule` → `ENABLED` |
| `tests/infra/test_template.py` (modify) | pins the six role assignments and the enabled rule |
| `tests/tenancy/test_catalog_grants.py` (new) | the grant surface, per role, connected as that role |
| `CLAUDE.md`, `docs/runbooks/deploy.md` (modify) | the new role model; the `DATABASE_ROLE=migration` stopgap note comes out |

**Task order is load-bearing.** Task 4 (copy-forward) must land before Task 5 (revoke), or the packet path is broken in between.

---

### Task 1: The two roles exist, and `runtime` no longer does

**Files:**
- Modify: `scripts/create_runtime_role.sql`, `config/settings/database.py`
- Test: `tests/test_settings_database.py` (check whether it exists; create only if not)

**Interfaces:**
- Produces: `DATABASE_ROLE` accepting `runtime_engine` | `runtime_web` | `migration`, backed by `POSTGRES_ENGINE_USER`/`_PASSWORD` and `POSTGRES_WEB_USER`/`_PASSWORD`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_removed_role_name_is_refused_not_silently_accepted() -> None:
    """`runtime` is gone. A task definition still carrying it must fail at boot
    rather than connect as something -- the whole point of the split is that
    which role you are is now load-bearing."""
    with pytest.raises(ImproperlyConfigured):
        database_config({"DATABASE_ROLE": "runtime", "POSTGRES_DB": "d",
                         "POSTGRES_HOST": "h"}, require_explicit_role=True)


@pytest.mark.parametrize("role,user_var", [
    ("runtime_engine", "POSTGRES_ENGINE_USER"),
    ("runtime_web", "POSTGRES_WEB_USER"),
])
def test_each_new_role_reads_its_own_credential_pair(role, user_var) -> None:
    cfg = database_config(
        {"DATABASE_ROLE": role, user_var: "u",
         user_var.replace("_USER", "_PASSWORD"): "p",
         "POSTGRES_DB": "d", "POSTGRES_HOST": "h"},
        require_explicit_role=True,
    )
    assert cfg["default"]["USER"] == "u"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `POSTGRES_DB=tehsil_catalog_split uv run pytest tests/test_settings_database.py -v`
Expected: FAIL — `runtime` is currently accepted, and the two new names are not.

- [ ] **Step 3: Implement**

In `config/settings/database.py`, replace `_ROLE_CREDENTIALS`:

```python
_ROLE_CREDENTIALS = {
    # `runtime` was one role doing two jobs: serving agencies and running the
    # engine. It is deliberately absent rather than aliased -- a task
    # definition still carrying it must fail at boot, because which role you
    # are is now the security boundary (2026-09-25 catalog-read-split design).
    "runtime_engine": ("POSTGRES_ENGINE_USER", "POSTGRES_ENGINE_PASSWORD"),
    "runtime_web": ("POSTGRES_WEB_USER", "POSTGRES_WEB_PASSWORD"),
    "migration": ("POSTGRES_MIGRATION_USER", "POSTGRES_MIGRATION_PASSWORD"),
}
```

In `scripts/create_runtime_role.sql`, create both roles where it creates one. `runtime_engine` keeps the grants `runtime` has today. `runtime_web` gets `CONNECT`, `USAGE ON SCHEMA public`, and DML on tenant tables **only** — Task 5 writes the catalogue revocation, so this task may grant it broadly and let Task 5 narrow it, provided Task 5 lands in the same branch. Keep the script's existing assertion that the migration role is neither superuser nor `BYPASSRLS`.

- [ ] **Step 4: Run the test — expect PASS**
- [ ] **Step 5: Commit** — `feat(db): two runtime roles, split by caller`

---

### Task 2: Test fixtures that can connect as a named role

**Files:**
- Modify: `tests/conftest.py`
- Test: exercised by Task 5; this task's own check is that the existing suites still pass.

**Interfaces:**
- Produces: `role_connection(role_name)` — a psycopg connection logged in as that role; `db_cursor` — an ordinary cursor on the default (superuser) connection, used only to READ `pg_policies` and `pg_has_role`, never to prove a grant; `runtime_connection` keeps its current behaviour by delegating.

- [ ] **Step 1: Write the failing test**

```python
def test_a_role_connection_is_actually_that_role(role_connection) -> None:
    """The instrument this whole design is verified with. If it silently
    connects as the test superuser, every later assertion is vacuous."""
    with role_connection("runtime_web") as conn, conn.cursor() as cur:
        cur.execute("SELECT current_user, "
                    "  (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
                    "  (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)")
        name, is_super, bypasses = cur.fetchone()
    assert name.endswith("web") and not is_super and not bypasses
```

- [ ] **Step 2: Run it and watch it fail** — `role_connection` does not exist.

- [ ] **Step 3: Implement**

Generalise `runtime_connection` (`tests/conftest.py:117`) into a factory taking a role name, creating that role `NOSUPERUSER NOBYPASSRLS` and granting only what the caller asks for. Keep `runtime_connection` as a thin wrapper so `tests/tenancy/test_database_isolation.py` is untouched. Carry over its existing docstring warnings verbatim — the grant-vs-policy trap it describes is exactly what this plan is about, one layer up.

- [ ] **Step 4: Run the test and the isolation suite**

Run: `POSTGRES_DB=tehsil_catalog_split uv run pytest tests/conftest.py tests/tenancy/ -v`
Expected: PASS, with the 13 existing isolation tests unchanged.

- [ ] **Step 5: Commit** — `test: a fixture that connects as a named role`

---

### Task 3: Inventory the catalogue, from the database

**Files:**
- Test: `tests/tenancy/test_catalog_grants.py` (new — the inventory half only)

**Interfaces:**
- Produces: `catalogue_tables()` — the list every later assertion iterates, read from `pg_policies`.

- [ ] **Step 1: Write the test that derives the list**

```python
def catalogue_tables(cursor) -> list[str]:
    """Every table carrying the shared read policy, from the database.

    NOT from grepping migrations: `funding_registerlisting` and
    `funding_institutionidentifier` are named in migration text and were
    dropped with the 2026-09-14 register removal, so a grep over-counts. A
    hardcoded list also goes stale the next time a catalogue table is added,
    which is exactly when this test most needs to be right.
    """
    cursor.execute(
        "SELECT tablename FROM pg_policies "
        "WHERE policyname = 'shared_catalog_select' ORDER BY tablename"
    )
    return [row[0] for row in cursor.fetchall()]


def test_the_catalogue_is_not_empty_and_names_the_corpus(db_cursor) -> None:
    tables = catalogue_tables(db_cursor)
    assert tables, "no shared_catalog_select policies found -- the query is wrong"
    assert "funding_program" in tables and "funding_fundingopportunity" in tables
```

- [ ] **Step 2: Run it** — it should PASS immediately; it is an inventory, not a change. If it fails, the policy name or the migration state is not what the spec assumed — **stop and report** rather than adjusting the assertion.

- [ ] **Step 3: Commit** — `test: derive the catalogue table list from pg_policies`

---

### Task 4: The packet carries its own requirements

**Files:**
- Modify: `apps/portals/models.py`, `apps/portals/packets.py`
- Create: `apps/portals/migrations/00NN_packet_statements.py` (run `ls apps/portals/migrations/` in Step 0 and take the next free number)
- Test: `tests/portals/test_packets.py` (modify)

**Interfaces:**
- Consumes: `ProgramStatement`, `ApplicationPrompt` — at mint time, in the worker.
- Produces: the packet row carries the required statements; `build_kit` and `ext_api.packet` read the stored copy.

- [ ] **Step 0: Take the next free migration number.** `ls apps/portals/migrations/` — the queue merge left `0017_merge_20260925_0848` as the leaf.

- [ ] **Step 1: Write the failing test**

```python
def test_minting_a_packet_reads_the_catalogue_but_serving_one_does_not(...) -> None:
    """The copy-forward the whole design rests on. Minting is worker work and
    may read ProgramStatement; serving is a web request and must not."""
    minted = mint_packet(application)          # worker path: catalogue allowed
    assert minted.required_statements          # the copy exists

    with catalogue_unreadable():               # simulate runtime_web
        served = build_kit(application)
    assert served.requirements == minted.required_statements
```

- [ ] **Step 2: Run it and watch it fail** — `build_kit` currently calls `_requirements()`, which queries `ProgramStatement` (`apps/portals/packets.py:214`).

- [ ] **Step 3: Implement**

Add the copied statements to the packet model as a JSON list. In `packets.py`, `_requirements()` is called **once, at mint time**, and its result stored; `build_kit` and `ext_api.packet` read the stored value. Keep `build_kit`'s existing contract that it never raises and degrades — a packet without the copy degrades to "no statements recorded", never to an exception.

Note what does **not** change: `mint_packet`'s refusal order (`automation_prohibited` → `NoFieldMap` → `malformed_field_map` → `missing_fact` → `unsafe_action`) is load-bearing and tested; the copy happens after the posture check, so a prohibited portal still never reads a verified value.

- [ ] **Step 4: Run the portal suite** — `POSTGRES_DB=tehsil_catalog_split uv run pytest tests/portals/ -v`
- [ ] **Step 5: Commit** — `feat(portals): the packet carries its own requirements`

---

### Task 5: The grant surface — an agency cannot read the catalogue

**Files:**
- Create: `apps/research/migrations/00NN_catalog_grants.py`
- Modify: `tests/tenancy/test_catalog_grants.py`
- Test: as above

**Interfaces:**
- Consumes: `catalogue_tables()` from Task 3, `role_connection` from Task 2.

- [ ] **Step 0: Take the next free migration number.** `ls apps/research/migrations/`.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_agency_connection_cannot_read_the_catalogue(role_connection, db_cursor) -> None:
    """The requirement, asserted at the layer that enforces it. Not 'sees no
    rows' -- `permission denied`, because an absent GRANT fails closed and a
    policy that returns zero rows is indistinguishable from an empty table."""
    tables = catalogue_tables(db_cursor)
    with role_connection("runtime_web") as conn:
        for table in tables:
            with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
            conn.rollback()


def test_the_engine_connection_can_read_the_catalogue(role_connection, db_cursor) -> None:
    tables = catalogue_tables(db_cursor)
    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT 1 FROM {table} LIMIT 1")   # must not raise


def test_the_web_role_holds_no_membership_of_the_engine_role(db_cursor) -> None:
    """SET ROLE does not need inherited attributes. Membership would make the
    boundary a discipline instead of a boundary -- the erasure-guard lesson."""
    db_cursor.execute(
        "SELECT pg_has_role(%s, %s, 'MEMBER')",
        (settings.DATABASES["default"]["USER"], ENGINE_ROLE_NAME),
    )
    assert db_cursor.fetchone()[0] is False, (
        "runtime_web is a member of runtime_engine -- SET ROLE makes the "
        "boundary a discipline instead of a boundary"
    )
```

- [ ] **Step 2: Run them and watch them fail** — today `runtime_web` does not exist as a distinct grantee and the catalogue is readable by anyone who connects.

- [ ] **Step 3: Implement the migration**

`RunSQL`, over the list from `pg_policies` rather than a literal list where possible:
1. `REVOKE SELECT, INSERT, UPDATE, DELETE ON <each catalogue table> FROM runtime_web`.
2. Repoint every `catalog_ingestion_write` policy to `runtime_engine`.
3. `DROP ROLE IF EXISTS catalog_ingestion` — it is `NOLOGIN` with no grant anywhere, so nothing can be holding it.
4. `ALTER DEFAULT PRIVILEGES` so a future catalogue table does not silently become readable by `runtime_web`.

Point 4 is the one that keeps this true over time; without it the next catalogue table inherits the schema-wide grant and the boundary quietly reopens.

- [ ] **Step 4: Add the two guards the spec asks for and the tests above do not cover**

Spec §8.2 — prove the claim the design rests on rather than restating it:

```python
def test_a_students_pack_renders_end_to_end_without_the_catalogue(role_connection, ...) -> None:
    """§3 claims RecommendationCandidate and EvidenceClaim carry everything an
    agency shows a student. This is that claim under the role that cannot fall
    back to the catalogue if it is wrong."""
```

Spec §7 — the one way this fails quietly is a foreign key. It fails loudly at
runtime, but a guard catches it at review instead:

```python
def test_nothing_traverses_a_foreign_key_from_a_tenant_row_into_the_catalogue() -> None:
    """`select_related("program")` on a RecommendationCandidate would make the
    web tier query a table it has no grant on. Verified absent 2026-09-25; this
    keeps it absent. Same forward-FK hazard CLAUDE.md records for
    TenantManager, one layer down."""
```

- [ ] **Step 5: Run the tests — expect PASS**, then the full suite.
- [ ] **Step 6: Commit** — `feat(db): an agency connection cannot read the catalogue`

---

### Task 6: The six task definitions, the two secrets, and the rule that can finally ship on

**Files:**
- Modify: `infra/template.yaml`, `tests/infra/test_template.py`

- [ ] **Step 1: Write the failing tests**

```python
ROLE_BY_TASK = {
    "WorkerTaskDefinition": "runtime_engine",
    "DocumentWorkerTaskDefinition": "runtime_engine",
    "EuropassWorkerTaskDefinition": "runtime_engine",
    "PortalTaskDefinition": "runtime_engine",
    "WebTaskDefinition": "runtime_web",
    "MigrationTaskDefinition": "migration",
}


@pytest.mark.parametrize("task,role", sorted(ROLE_BY_TASK.items()))
def test_each_task_definition_carries_the_role_its_work_needs(template, task, role) -> None:
    """Getting one wrong is a silent outage (engine work as web) or a silent
    leak (web work as engine), and neither shows on any screen."""
    assert _database_role(template, task) == role


def test_the_retry_rule_is_now_enabled(template) -> None:
    """It shipped DISABLED because catalog_ingestion had no login. The engine
    role replaces it, so the reason is gone."""
    assert template["Resources"]["RetryDueFetchesRule"]["Properties"]["State"] == "ENABLED"
```

- [ ] **Step 2: Run and watch them fail** — five task definitions say `runtime` today and the rule says `DISABLED`.

- [ ] **Step 3: Implement** — set the six values, add the two Secrets Manager secrets and grant each task role read on **only** the secret it needs, and flip `RetryDueFetchesRule` to `ENABLED`. Keep `EventsInvokeEcsRole`'s existing exact-ARN scoping; do not widen it.

- [ ] **Step 4: Run `tests/infra/` — expect PASS**
- [ ] **Step 5: Commit** — `feat(infra): each task definition gets the role its work needs`

---

### Task 7: The documentation that the next session will trust

**Files:**
- Modify: `CLAUDE.md`, `docs/runbooks/deploy.md`, `apps/research/management/commands/{discover,fetch_ladder,funding_yield}.py`

- [ ] **Step 1: Rewrite CLAUDE.md's role model.** Its "Row-level security: what actually filters a query" section describes one `runtime` role and RLS as the write gate. It must now say: two runtime roles split by caller; the catalogue boundary is a `GRANT`, not a policy; RLS remains the tenant-isolation mechanism and nothing else. Keep every measured claim in that section — they are why the rest of the file is trusted.

- [ ] **Step 2: Remove the stopgap note.** `discover`, `fetch_ladder` and `funding_yield` say in their `--help` that they must run under `DATABASE_ROLE=migration`. They run as `runtime_engine` now. The same paragraph comes out of `docs/runbooks/deploy.md`, replaced by what an operator actually does: create both roles, put both secrets in place.

- [ ] **Step 3: Record the two standing constraints** where they will be met, not only in the spec: a student-facing action that needs a fetch **queues it to the worker** (§6), and `explanations.draft_explanation`, when wired, **writes to a tenant row** rather than computing from catalogue content at render (§11).

- [ ] **Step 4: Full suite, then commit** — `docs: the catalogue boundary, and the stopgap that is over`

---

## An assumption this plan proceeds on

Spec §12 asks whether **every** table carrying `shared_catalog_select` is
off-limits to an agency. This plan assumes yes, including the two telemetry
tables — an agency has no reason to read `FetchAttempt` or `HostProfile`
either. If any must stay agency-readable, Task 5's revoke list is where that
exception goes, and it needs the owner's word before the task runs.

## What this plan deliberately leaves

- **IAM database authentication.** It would remove both stored passwords, but tokens expire in 15 minutes while Django holds connections via `CONN_MAX_AGE`, so it needs a connection factory that refreshes them. Orthogonal, and its own decision.
- **A platform catalogue UI.** §10 decides that platform catalogue access is ops-side for now; if a browsing UI is ever wanted it gets its own task definition and role, so an agency request cannot reach it by routing mistake.
- **Anything about tenant-table RLS**, which this plan does not touch.

## After the plan

The live question this cannot answer: nothing is deployed, so no assertion here has met a real RDS instance. The grant surface is verified against roles created in a test database, which is the right instrument and still not production. First deploy should re-run Task 5's tests against the real database before any agency has a login.
