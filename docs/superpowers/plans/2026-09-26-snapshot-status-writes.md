# Snapshot status writes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The worker can record a page's status on its archived snapshot (`retrieval_status`, `funding_read_at`), and nothing (worker included) can rewrite the evidence columns.

**Architecture:** `funding_officialsourcesnapshot` has only an INSERT write policy, so every UPDATE by `runtime_engine` is legal SQL that matches zero rows and reports success. There are four such writers today. One migration adds an UPDATE policy for `runtime_engine` and narrows its table-wide UPDATE grant to the two status columns. The column grant keeps the evidence immutable: the body pointer, digests, URL and dates. The GRANT is the mechanism, as CLAUDE.md's role model requires. The RLS policy only stops the row filter from hiding the write.

**Tech Stack:** Django 5.2, PostgreSQL 17 (column-level privileges and RLS), psycopg 3, pytest with the repo's `role_connection` fixture.

**Spec:** None separate. The design is recorded in this plan's Architecture and in CLAUDE.md's "Row-level security" section (catalog-read-split, merged as PR #134). The facts it rests on are cited inline below.

## Why, measured and cited

- `apps/funding/migrations/0006_official_snapshots.py:44-46` created the table's write policy `FOR INSERT` only. `0049_catalog_grants.py` renamed it `runtime_engine_write` and kept the command.
- These UPDATE writers all silently change nothing under `runtime_engine`:
  - `apps/research/pipeline.py:359-360` and `:434-435`: `snapshot.save(update_fields=["funding_read_at"])`, used by `discover --funding`.
  - `apps/research/management/commands/poll_monitor_checks.py:70`: `_mark`, setting `retrieval_status`.
  - `apps/research/views.py:65`: the Firecrawl webhook, flag off, which sets `retrieval_status`.
  - `apps/research/snapshot.py:186`: `refresh_snapshot`, which has no production caller.
- The `funding_read_at` loss is a **regression the catalog split exposed**. Before PR #134, operators ran `discover` as `DATABASE_ROLE=migration`, the table owner. The table is `ENABLE`d, not `FORCE`d, so the owner bypassed the policy and the write landed. The docs now say `runtime_engine`, and under that role `funding_recall` (`funding_recall.py:46`) reports every programme PENDING forever. Nothing is deployed, so no data needs repairing.

## Global Constraints

- **The boundary is a GRANT.** Evidence columns become non-updatable by revoking table-wide UPDATE and granting UPDATE on exactly `retrieval_status, funding_read_at`. Never express "which columns may change" as a policy.
- **`runtime_web` gains nothing.** It holds no privilege on this table and must still get `permission denied for table funding_officialsourcesnapshot`.
- **No test in this repo proves a grant or a policy by default.** The test role is a superuser. Every assertion connects through `role_connection("runtime_engine")` or `role_connection("runtime_web")` (`tests/conftest.py:224`).
- **Never run `ruff format`.** This repo's gate is lint-only.
- **After the task, all of these must be clean:** `uv run ruff check apps config tests scripts`, `uv run mypy apps config`, `uv run python manage.py makemigrations --check --dry-run`, and the full suite `POSTGRES_DB=elmify_<worktree> uv run pytest --create-db`, on its own test database and never a shared one.

## Review Focus

1. **An evidence column is updated by the engine.** It must fail loudly (`permission denied for table`), not return zero rows. The test pins `sha256`, and `final_url` also belongs there.
2. **The web role attempts the status write.** It must be refused by the grant, not silently filtered.
3. **Migrating backwards.** The reverse must restore exactly today's surface: table-wide UPDATE and no UPDATE policy. That keeps `tests/tenancy/test_catalog_grants.py`'s `runtime_engine` "has all four" assertion true after a rollback.
4. **`test_catalog_grants.py`'s engine assertion checks table-level UPDATE through `has_table_privilege`.** That returns false once UPDATE is column-scoped on this one table. Carve the exception there with a comment naming this migration, rather than weakening the assertion for every table.
5. **`final_url`-keyed updates hitting several snapshots of the same URL.** That was already true and is not changed here. The test updates by `id` so its row count is exact.

---

## File Structure

| file | responsibility |
|---|---|
| `apps/funding/migrations/0050_snapshot_status_update.py` (new) | narrows the UPDATE grant, adds the UPDATE policy, and reverses both |
| `tests/research/test_snapshot_status_writes.py` (new) | the grant and policy surface, proven as each role |
| `tests/tenancy/test_catalog_grants.py` (modify) | the one-table exception to "engine has all four" |
| `apps/research/management/commands/poll_monitor_checks.py`, `apps/research/views.py`, `apps/research/snapshot.py` (modify comments only) | stop claiming the write is inert |
| `CLAUDE.md` (modify) | the webhook bullet: the UPDATE half is done, and the web-tier half remains |

---

### Task 1: The engine can record status; nobody can rewrite evidence

**Files:**
- Create: `apps/funding/migrations/0050_snapshot_status_update.py`
- Create: `tests/research/test_snapshot_status_writes.py`
- Modify: `tests/tenancy/test_catalog_grants.py` (the engine-has-all-four assertion)
- Modify (comments/docs only): `apps/research/management/commands/poll_monitor_checks.py:58-70`, `apps/research/views.py:54-65`, `apps/research/snapshot.py` (the comment above the `refresh_snapshot` UPDATE, if it claims inertness), `CLAUDE.md` (the Firecrawl webhook bullet)

**Interfaces:**
- Consumes: `role_connection(role_name)` (`tests/conftest.py:224`), a context manager yielding an autocommit psycopg connection as a member of that role. `snapshot_factory(final_url=..., **overrides)` (`tests/research/conftest.py:94`) creates an `OfficialSource` and `OfficialSourceSnapshot` pair.
- Produces: the policy `runtime_engine_update` on `funding_officialsourcesnapshot`, plus column UPDATE on `(retrieval_status, funding_read_at)` for `runtime_engine`.

- [ ] **Step 0: Take the next free migration number and set up the test DB name**

Run: `ls apps/funding/migrations/ | tail -3`. The leaf is `0049_catalog_grants.py` as of `d1f7d106`. If master has moved, depend on the actual leaf.
Use `POSTGRES_DB=elmify_snapshot_status` for every pytest run in this plan.

- [ ] **Step 1: Write the failing tests**

Create `tests/research/test_snapshot_status_writes.py`:

```python
"""The worker records a page's status on its snapshot; nothing rewrites the evidence.

`funding_officialsourcesnapshot` was created with an INSERT-only write policy
(funding/0006), so every UPDATE by `runtime_engine` matched zero rows while
reporting success. That silently discarded `funding_read_at` (discover
--funding, read by funding_recall) and `retrieval_status` (poll_monitor_checks,
the Firecrawl webhook). funding/0050 adds an UPDATE policy for the engine and
narrows its UPDATE grant to those two columns.

Every assertion connects as a member of a fixed role through `role_connection`.
The superuser test role bypasses grants and RLS alike and would prove nothing
(CLAUDE.md). `transaction=True` because those connections autocommit and must
see a committed row; the flush after each test removes it.
"""
import psycopg
import pytest

_TABLE = "funding_officialsourcesnapshot"


@pytest.mark.django_db(transaction=True)
def test_the_engine_records_status_and_the_read_stamp(role_connection, snapshot_factory):
    """Both writers' statements land: one row each, not zero."""
    snapshot = snapshot_factory(final_url="https://uni.example.org/msc/")

    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {_TABLE} SET retrieval_status = 'STALE' WHERE id = %s", [snapshot.id]
        )
        assert cur.rowcount == 1, "the UPDATE matched zero rows -- the policy is missing"
        cur.execute(
            f"UPDATE {_TABLE} SET funding_read_at = now() WHERE id = %s", [snapshot.id]
        )
        assert cur.rowcount == 1

    snapshot.refresh_from_db()
    assert snapshot.retrieval_status == "STALE"
    assert snapshot.funding_read_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("column,value", [("sha256", "0" * 64), ("final_url", "https://evil.example/")])
def test_the_engine_cannot_rewrite_evidence(role_connection, snapshot_factory, column, value):
    """The archived page is evidence of what it said on the day it was read.
    Refused by the column GRANT, loudly: never a policy returning zero rows."""
    snapshot = snapshot_factory(final_url="https://uni.example.org/msc/")

    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cur.execute(f"UPDATE {_TABLE} SET {column} = %s WHERE id = %s", [value, snapshot.id])
    assert f"permission denied for table {_TABLE}" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_the_web_role_still_cannot_touch_the_archive(role_connection, snapshot_factory):
    snapshot = snapshot_factory(final_url="https://uni.example.org/msc/")

    with role_connection("runtime_web") as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cur.execute(
                f"UPDATE {_TABLE} SET retrieval_status = 'STALE' WHERE id = %s", [snapshot.id]
            )
    assert f"permission denied for table {_TABLE}" in str(refused.value)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `POSTGRES_DB=elmify_snapshot_status uv run pytest tests/research/test_snapshot_status_writes.py -v --create-db`
Expected: the first test FAILS with "the UPDATE matched zero rows -- the policy is missing". The evidence tests FAIL with `DID NOT RAISE`, because the engine holds table-wide UPDATE, so the policy silently filters to zero rows. The web test PASSES already, which is the positive control.

- [ ] **Step 3: Write the migration**

Create `apps/funding/migrations/0050_snapshot_status_update.py`:

```python
"""The worker may record a page's status on its snapshot, and nothing else.

funding/0006 created `funding_officialsourcesnapshot` with an INSERT-only write
policy. Every UPDATE -- `funding_read_at` from discover --funding,
`retrieval_status` from poll_monitor_checks and the Firecrawl webhook -- was
legal SQL matching zero rows. Before the catalog split the funding stamp still
landed, because operators ran as the table owner and the table is ENABLE, not
FORCE, row level security. Under `runtime_engine` it vanished
(docs/superpowers/plans/2026-09-26-snapshot-status-writes.md).

Two halves, both needed:
- GRANT, the boundary: the engine's table-wide UPDATE becomes UPDATE on exactly
  the two status columns. The archived page, its digests, its URL and its dates
  are evidence and stay non-updatable. A write to them fails with
  `permission denied`, loudly.
- POLICY, the row filter: without an UPDATE policy, RLS hides every row from
  the UPDATE even where the grant allows it.
`runtime_web` holds no privilege on this table (funding/0049) and gets none here.
"""
from django.db import migrations

TABLE = "public.funding_officialsourcesnapshot"

FORWARD = f"""
REVOKE UPDATE ON {TABLE} FROM runtime_engine;
GRANT UPDATE (retrieval_status, funding_read_at) ON {TABLE} TO runtime_engine;
CREATE POLICY runtime_engine_update ON {TABLE}
    FOR UPDATE TO runtime_engine USING (true) WITH CHECK (true);
"""

REVERSE = f"""
DROP POLICY IF EXISTS runtime_engine_update ON {TABLE};
REVOKE UPDATE (retrieval_status, funding_read_at) ON {TABLE} FROM runtime_engine;
GRANT UPDATE ON {TABLE} TO runtime_engine;
"""


class Migration(migrations.Migration):
    dependencies = [("funding", "0049_catalog_grants")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
```

- [ ] **Step 4: Run the new tests. Expect PASS.**

Run: `POSTGRES_DB=elmify_snapshot_status uv run pytest tests/research/test_snapshot_status_writes.py -v --create-db`
Expected: 4 passed.

- [ ] **Step 5: Carve the one-table exception in the grant-surface test**

Run: `POSTGRES_DB=elmify_snapshot_status uv run pytest tests/tenancy/test_catalog_grants.py -v`
Expected: the test asserting `runtime_engine` holds SELECT/INSERT/UPDATE/DELETE on every catalogue table FAILS on `funding_officialsourcesnapshot` UPDATE, because `has_table_privilege` checks table-level UPDATE. Change only that assertion. For this one table, assert `has_column_privilege('runtime_engine', t, 'retrieval_status', 'UPDATE')` and the same for `funding_read_at`, and add this comment: `# funding/0050: UPDATE is column-scoped here -- the evidence columns are immutable`. Every other table keeps the table-level check. Re-run and expect PASS.

- [ ] **Step 6: Make the comments true**

- `poll_monitor_checks.py:58-70` (`_mark`): delete the "INERT IN PRODUCTION TODAY" paragraph. Replace it with one line: the UPDATE lands because funding/0050 gives `runtime_engine` an UPDATE policy and a column grant on `retrieval_status`.
- `apps/research/views.py:54-65` (webhook): keep that the view must stay off. The **remaining** reason is that it runs on the web tier, where `runtime_web` has no grant, so the write must move to the worker. Delete the claim that an UPDATE policy is also missing.
- `apps/research/snapshot.py` (`refresh_snapshot`): if its comment claims the UPDATE is inert, correct it the same way. Leave the function itself.
- `CLAUDE.md`, the Firecrawl webhook bullet (search `FETCH_WEBHOOKS_ENABLED`): replace "and an UPDATE policy on that table" with a statement that funding/0050 added the UPDATE policy, so the one remaining prerequisite is moving the write off the web tier.

- [ ] **Step 7: Full checks**

Run: `uv run ruff check apps config tests scripts && uv run mypy apps config && uv run python manage.py makemigrations --check --dry-run && POSTGRES_DB=elmify_snapshot_status uv run pytest --create-db`
Expected: all clean, 0 failed. `tests/research/test_monitor_commands.py` and `tests/research/test_firecrawl_webhook.py` are unchanged and still pass. The webhook's web-role test still expects `permission denied`, because that half is not fixed here.

- [ ] **Step 8: Commit**

```bash
git add apps/funding/migrations/0050_snapshot_status_update.py tests/research/test_snapshot_status_writes.py tests/tenancy/test_catalog_grants.py apps/research/management/commands/poll_monitor_checks.py apps/research/views.py apps/research/snapshot.py CLAUDE.md
git commit -m "fix(db): the worker can record a snapshot's status, and only that"
```

---

## What this plan deliberately leaves

- **Nothing reads `retrieval_status` yet.** Making the write land records "this page changed", but no code acts on it by re-reading the page or alerting anyone. That consumer belongs with whatever first re-reads catalogue pages on a schedule. Until then the column is an honest record, not a trigger.
- **The webhook stays off.** Moving its write to the worker needs a message kind with no tenant (`apps/research/queue.py:13-15` groups by tenant), and the poll command already covers the same results. Build it only if polling proves too slow.
- **A DELETE policy for the engine.** The engine holds a DELETE grant but no DELETE policy, so a delete silently removes nothing. No code deletes snapshots, and evidence should not be deleted. If someone ever adds a delete, a test belongs beside it.
