"""The third RLS case, verified where it can be verified.

The test role bypasses RLS and grants alike (CLAUDE.md), so every assertion
here runs on a real NOBYPASSRLS login:

- `runtime_connection` for the POLICY: a bare role that is granted exactly the
  DML a test needs, and asserts the grant first, so a refusal is the policy's
  and not the permission layer's -- both raise 42501.
- `role_connection` for the ROLES production runs as: a disposable member of
  `runtime_web` (the console) or `runtime_engine` (the writers and the
  applier), holding only what that membership gives it.
"""

from uuid import uuid4

import psycopg
import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import ResolutionItem

TABLE = "public.research_resolutionitem"
MARKER = "public.research_platformagency"

_INSERT = (
    f"INSERT INTO {TABLE} (id, kind, subject_key, evidence, ask, options, state,"
    " created_at, refreshed_at, expires_at, apply_error, country_code, registered)"
    " VALUES (%s, 'HOST_UNREACHABLE', %s, '{}', '?', '[]', 'OPEN',"
    " now(), now(), now(), '', '', false)"
)


@pytest.fixture
def item(db):
    now = timezone.now()
    return ResolutionItem.objects.create(
        kind="HOST_UNREACHABLE",
        subject_key="host:shut.test",
        evidence={},
        ask="?",
        options=[],
        refreshed_at=now,
        expires_at=now,
    )


def _grant_dml(runtime_connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_resolutionitem"),
                sql.Identifier(runtime_connection.info.user),
            )
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(current_user, %s, 'INSERT'),"
            "       has_table_privilege(current_user, %s, 'DELETE')",
            [TABLE, TABLE],
        )
        assert cursor.fetchone() == (True, True)


def _as_tenant(cursor, tenant_id) -> None:
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])


# --- the policy, on a bare NOBYPASSRLS role -----------------------------------


@pytest.mark.django_db(transaction=True)
def test_no_guc_sees_nothing(runtime_connection, item, platform) -> None:
    with runtime_connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_an_agency_sees_nothing_and_changes_nothing(
    runtime_connection, item, platform, agency_a
) -> None:
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, agency_a.id)
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (0,)
        cursor.execute(f"UPDATE {TABLE} SET state = 'PARKED'")
        assert cursor.rowcount == 0
        cursor.execute(f"DELETE FROM {TABLE}")
        assert cursor.rowcount == 0


@pytest.mark.django_db(transaction=True)
def test_an_unmarked_platform_sees_nothing(runtime_connection, item, agency_a) -> None:
    """No PlatformAgency row: the queue is invisible to everyone. Fails
    closed, never open (the runbook step that sets it says the same)."""
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, agency_a.id)
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (0,)


@pytest.mark.django_db(transaction=True)
def test_the_platform_reads_and_updates_but_never_inserts_or_deletes(
    runtime_connection, item, platform
) -> None:
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, platform.id)
        cursor.execute(f"SELECT id FROM {TABLE}")
        assert cursor.fetchall() == [(item.id,)]
        cursor.execute(f"UPDATE {TABLE} SET state = 'PARKED' WHERE id = %s", [item.id])
        assert cursor.rowcount == 1
        cursor.execute(f"DELETE FROM {TABLE} WHERE id = %s", [item.id])
        assert cursor.rowcount == 0
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, platform.id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute(_INSERT, [uuid4(), "host:x.test"])


@pytest.mark.django_db(transaction=True)
def test_a_platform_update_is_checked_by_the_same_predicate(runtime_connection) -> None:
    """WITH CHECK is the same predicate. It is trivially true for this table,
    since no row carries a tenant, but the policy must state it: an UPDATE
    policy without WITH CHECK falls back to USING silently, and a later edit to
    one would not be seen in the other."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT qual, with_check FROM pg_policies WHERE tablename = 'research_resolutionitem'"
            " AND policyname = 'platform_operator_update'"
        )
        qual, with_check = cursor.fetchone()
    assert qual == with_check


# --- the production roles ---------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_web_role_works_the_queue_only_as_the_platform(
    role_connection, item, platform, agency_a
) -> None:
    """The console runs as runtime_web. It holds DML on this table (it is not
    a catalogue table), so the POLICY is the only gate -- and it admits SELECT
    and UPDATE under the platform's GUC, nothing under an agency's."""
    with role_connection("runtime_web") as conn:
        with conn.transaction(), conn.cursor() as cursor:
            _as_tenant(cursor, platform.id)
            cursor.execute(f"SELECT id FROM {TABLE}")
            assert cursor.fetchall() == [(item.id,)]
            cursor.execute(f"UPDATE {TABLE} SET state = 'PARKED' WHERE id = %s", [item.id])
            assert cursor.rowcount == 1
            cursor.execute(f"DELETE FROM {TABLE} WHERE id = %s", [item.id])
            assert cursor.rowcount == 0
        with conn.transaction(), conn.cursor() as cursor:
            _as_tenant(cursor, platform.id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(_INSERT, [uuid4(), "host:web.test"])
        with conn.transaction(), conn.cursor() as cursor:
            _as_tenant(cursor, agency_a.id)
            cursor.execute(f"SELECT count(*) FROM {TABLE}")
            assert cursor.fetchone() == (0,)
            cursor.execute(f"UPDATE {TABLE} SET state = 'OPEN'")
            assert cursor.rowcount == 0
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {TABLE}")
            assert cursor.fetchone() == (0,)
    item.refresh_from_db()
    assert item.state == "PARKED"


@pytest.mark.django_db(transaction=True)
def test_the_engine_role_files_and_deletes_without_any_guc(role_connection, item) -> None:
    """runtime_engine is the writers' and the applier's role:
    `runtime_engine_write` admits everything, with no tenant in play."""
    new_id = uuid4()
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_INSERT, [new_id, "host:engine.test"])
        assert cursor.rowcount == 1
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (2,)
        cursor.execute(f"DELETE FROM {TABLE} WHERE id IN (%s, %s)", [new_id, item.id])
        assert cursor.rowcount == 2


@pytest.mark.parametrize("role", ["runtime_web", "runtime_engine"])
@pytest.mark.django_db(transaction=True)
def test_neither_runtime_role_can_move_the_platform(role_connection, platform, agency_a, role):
    """The marker is readable by both runtime roles -- the queue's policy
    subquery runs with the CALLER's privileges, so the web role must be able to
    read it -- and writable by neither: moving the platform moves who can read
    the queue, so only the owner (`manage.py set_platform_agency` as the
    migration role) may. A refused GRANT, not a policy: `permission denied`."""
    with role_connection(role) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT agency_id FROM {MARKER}")
            assert cursor.fetchall() == [(platform.id,)]
        for statement, params in (
            (
                f"INSERT INTO {MARKER} (id, singleton, agency_id, created_at)"
                " VALUES (%s, true, %s, now())",
                [uuid4(), agency_a.id],
            ),
            (f"UPDATE {MARKER} SET agency_id = %s", [agency_a.id]),
            (f"DELETE FROM {MARKER}", []),
            (f"TRUNCATE {MARKER}", []),
        ):
            with conn.cursor() as cursor, pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(statement, params)


@pytest.mark.django_db(transaction=True)
def test_the_marker_refuses_a_non_owner_even_when_granted(
    runtime_connection, platform, agency_a
) -> None:
    """The second layer, alone: a role HOLDING full DML on the marker -- what
    any later blanket `GRANT ... ON ALL TABLES` would hand the runtime roles --
    is still refused by the owner-only trigger, loudly and with the same 42501."""
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_platformagency"),
                sql.Identifier(runtime_connection.info.user),
            )
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(current_user, %s, 'UPDATE'),"
            "       has_table_privilege(current_user, %s, 'DELETE')",
            [MARKER, MARKER],
        )
        assert cursor.fetchone() == (True, True)
    for statement, params in (
        (
            f"INSERT INTO {MARKER} (id, singleton, agency_id, created_at)"
            " VALUES (%s, true, %s, now())",
            [uuid4(), agency_a.id],
        ),
        (f"UPDATE {MARKER} SET agency_id = %s", [agency_a.id]),
        (f"DELETE FROM {MARKER}", []),
        (f"TRUNCATE {MARKER}", []),
    ):
        with runtime_connection.cursor() as cursor, pytest.raises(
            psycopg.errors.InsufficientPrivilege, match="only the owner"
        ):
            cursor.execute(statement, params)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT agency_id FROM {MARKER}")
        assert cursor.fetchall() == [(platform.id,)]
