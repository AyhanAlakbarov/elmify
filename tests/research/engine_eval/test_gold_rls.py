"""research_golditem is platform-only, proven as a NOBYPASSRLS role (the test role bypasses RLS).

Same policy shape as research_resolutionitem (tests/research/resolution/test_rls.py): the
platform's host reads and updates, an agency sees nothing, and nobody deletes.
"""

from uuid import uuid4

import psycopg
import pytest
from django.db import connection
from psycopg import sql

from apps.research.models import GoldItem
from tests.research.resolution import conftest as _resolution

TABLE = "public.research_golditem"

platform = _resolution.platform  # the resolution console's platform fixture


@pytest.fixture
def item(db):
    return GoldItem.objects.create(
        run="r1", kind="deadline", question="application_date", language="az",
        page_url="https://edu.gov.az/x", line_text="Müraciət 15 yanvar 2027-dək.",
        claim="c", round=1, purpose="improvement",
    )


def _grant_dml(runtime_connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_golditem"),
                sql.Identifier(runtime_connection.info.user),
            )
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user, %s, 'DELETE')", [TABLE])
        assert cursor.fetchone() == (True,)


def _as_tenant(cursor, tenant_id) -> None:
    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])


@pytest.mark.django_db(transaction=True)
def test_an_agency_sees_nothing_and_changes_nothing(runtime_connection, item, platform, agency_a):
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, agency_a.id)
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (0,)
        cursor.execute(f"UPDATE {TABLE} SET verdict = 'wrong'")
        assert cursor.rowcount == 0


@pytest.mark.django_db(transaction=True)
def test_the_platform_updates_the_verdict_but_never_deletes(runtime_connection, item, platform):
    _grant_dml(runtime_connection)
    with runtime_connection.transaction(), runtime_connection.cursor() as cursor:
        _as_tenant(cursor, platform.id)
        cursor.execute(f"SELECT id FROM {TABLE}")
        assert cursor.fetchall() == [(item.id,)]
        cursor.execute(f"UPDATE {TABLE} SET verdict = 'correct' WHERE id = %s", [item.id])
        assert cursor.rowcount == 1
        cursor.execute(f"DELETE FROM {TABLE} WHERE id = %s", [item.id])
        assert cursor.rowcount == 0
    item.refresh_from_db()
    assert item.verdict == "correct"


@pytest.mark.django_db(transaction=True)
def test_neither_runtime_role_holds_delete(role_connection, item):
    """Rows are kept as regression data: no DELETE grant, so it is refused by the grant itself."""
    for role in ("runtime_web", "runtime_engine"):
        with role_connection(role) as conn, conn.cursor() as cursor, pytest.raises(
            psycopg.errors.InsufficientPrivilege
        ):
            cursor.execute(f"DELETE FROM {TABLE}")


_INSERT = (
    f"INSERT INTO {TABLE} (id, run, kind, question, language, page_url, line_text, line_sha256,"
    " heading, claim, round, purpose, verdict, fix, created_at)"
    " VALUES (%s, 'r2', 'money', 'q', 'en', 'https://x.org', 'l', 'h', '', 'c', 1,"
    " 'improvement', '', '', now())"
)


@pytest.mark.django_db(transaction=True)
def test_the_web_role_labels_only_as_the_platform(role_connection, item, platform, agency_a):
    """0024's own GRANT, for the production role: the console (runtime_web) selects and updates
    under the platform's GUC, cannot insert, and sees nothing under an agency's."""
    with role_connection("runtime_web") as conn:
        with conn.transaction(), conn.cursor() as cursor:
            _as_tenant(cursor, platform.id)
            cursor.execute(f"SELECT id FROM {TABLE}")
            assert cursor.fetchall() == [(item.id,)]
            cursor.execute(
                f"UPDATE {TABLE} SET verdict = 'wrong', fix = 'f', labelled_at = now()"
                " WHERE id = %s",
                [item.id],
            )
            assert cursor.rowcount == 1
        with conn.transaction(), conn.cursor() as cursor:
            _as_tenant(cursor, platform.id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(_INSERT, [uuid4()])
        with conn.transaction(), conn.cursor() as cursor:
            _as_tenant(cursor, agency_a.id)
            cursor.execute(f"SELECT count(*) FROM {TABLE}")
            assert cursor.fetchone() == (0,)
    item.refresh_from_db()
    assert (item.verdict, item.fix) == ("wrong", "f") and item.labelled_at is not None


@pytest.mark.django_db(transaction=True)
def test_the_engine_role_files_without_any_guc(role_connection, item):
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_INSERT, [uuid4()])
        assert cursor.rowcount == 1
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone() == (2,)
