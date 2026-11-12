"""The worker records a page's status on its snapshot; nothing rewrites the evidence.

`funding_officialsourcesnapshot` was created with an INSERT-only write policy
(funding/0006), so every UPDATE by `runtime_engine` matched zero rows while
reporting success. That silently discarded `funding_read_at` and
`funding_read_cost` (discover --funding, read by funding_recall), `readability`
(reader and pipeline), and `retrieval_status` (poll_monitor_checks, the
Firecrawl webhook). funding/0067 adds an UPDATE policy for the engine and
narrows its UPDATE grant to those four status/read columns.

Every assertion connects as a member of a fixed role through `role_connection`.
The superuser test role bypasses grants and RLS alike and would prove nothing
(CLAUDE.md). `transaction=True` because those connections autocommit and must
see a committed row; the flush after each test removes it.
"""

import psycopg
import pytest

_TABLE = "funding_officialsourcesnapshot"


@pytest.mark.django_db(transaction=True)
def test_the_engine_records_status_and_the_read_stamp(
    role_connection, snapshot_factory
) -> None:
    """Every status/read writer's statement lands: one row each, not zero."""
    snapshot = snapshot_factory(final_url="https://uni.example.org/msc/")

    with role_connection("runtime_engine") as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE {_TABLE} SET retrieval_status = 'STALE' WHERE id = %s",
            [snapshot.id],
        )
        assert cur.rowcount == 1, "the UPDATE matched zero rows -- the policy is missing"
        cur.execute(
            f"UPDATE {_TABLE} SET readability = 'SHELL' WHERE id = %s",
            [snapshot.id],
        )
        assert cur.rowcount == 1
        cur.execute(
            f"UPDATE {_TABLE} SET funding_read_at = now(), "
            f"funding_read_cost = '{{\"usd\": 0.01}}'::jsonb WHERE id = %s",
            [snapshot.id],
        )
        assert cur.rowcount == 1

    snapshot.refresh_from_db()
    assert snapshot.retrieval_status == "STALE"
    assert snapshot.readability == "SHELL"
    assert snapshot.funding_read_at is not None
    assert snapshot.funding_read_cost == {"usd": 0.01}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("column", "value"),
    [("sha256", "0" * 64), ("final_url", "https://evil.example/")],
)
def test_the_engine_cannot_rewrite_evidence(
    role_connection, snapshot_factory, column: str, value: str
) -> None:
    """The archived page is evidence of what it said on the day it was read.
    Refused by the column GRANT, loudly: never a policy returning zero rows."""
    snapshot = snapshot_factory(final_url="https://uni.example.org/msc/")

    with (
        role_connection("runtime_engine") as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.InsufficientPrivilege) as refused,
    ):
        cur.execute(f"UPDATE {_TABLE} SET {column} = %s WHERE id = %s", [value, snapshot.id])
    assert f"permission denied for table {_TABLE}" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_the_web_role_still_cannot_touch_the_archive(
    role_connection, snapshot_factory
) -> None:
    snapshot = snapshot_factory(final_url="https://uni.example.org/msc/")

    with (
        role_connection("runtime_web") as conn,
        conn.cursor() as cur,
        pytest.raises(psycopg.errors.InsufficientPrivilege) as refused,
    ):
        cur.execute(
            f"UPDATE {_TABLE} SET retrieval_status = 'STALE' WHERE id = %s",
            [snapshot.id],
        )
    assert f"permission denied for table {_TABLE}" in str(refused.value)
