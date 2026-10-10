"""The fetch engine's two shared-catalog tables, and the policy that shapes them.

The RLS test here runs as a real NOBYPASSRLS role through `runtime_connection`.
CLAUDE.md's rule is why: the test database role bypasses RLS, so a policy
assertion taken on the ordinary test connection passes whether or not the policy
exists. It carries a negative control for the second half of that trap -- a role
with no privilege on a table is refused at the permission layer with the same
SQLSTATE the policy raises, so "the write failed" proves nothing on its own.
"""

import psycopg
import pytest
from django.db import connection
from psycopg import sql

from apps.research.fetch.types import Outcome
from apps.research.models import FetchAttempt, HostProfile

pytestmark = pytest.mark.django_db

_TABLES = ("research_hostprofile", "research_fetchattempt")


@pytest.mark.django_db(transaction=True)
def test_both_tables_are_shared_catalog_under_a_real_policy(runtime_connection) -> None:
    """Readable, at the policy layer, by everyone with no tenant GUC set;
    writable by nobody but `runtime_engine` (and `runtime_web` holds no
    table grant at all -- a GRANT, not this policy, keeps the web out).

    The negative control is the whole point. The runtime role is granted
    SELECT, INSERT, UPDATE and DELETE on both tables first, and the test asserts
    it holds them -- so when the INSERT is refused it is refused by the policy,
    and when the UPDATE and DELETE touch zero rows it is because
    `shared_catalog_select` covers SELECT alone and leaves them no USING clause.
    Without the grant the same three outcomes arrive from a table the role
    cannot see at all, and the test would pass with no policy on either table.
    """
    HostProfile.objects.create(host="shared.test", start_rung=3)
    FetchAttempt.objects.create(
        url="https://shared.test/a",
        host="shared.test",
        rung=1,
        vendor="FIRECRAWL",
        outcome=Outcome.FETCHED,
    )
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        for table in _TABLES:
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {} TO {}").format(
                    sql.Identifier("public", table), role
                )
            )

    with runtime_connection.cursor() as cursor:
        for table in _TABLES:
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, 'INSERT'),"
                "       has_table_privilege(%s, %s, 'UPDATE'),"
                "       has_table_privilege(%s, %s, 'DELETE')",
                [runtime_connection.info.user, f"public.{table}"] * 3,
            )
            assert cursor.fetchone() == (True, True, True), f"{table}: grant did not take"

        cursor.execute("SELECT host FROM public.research_hostprofile")
        assert cursor.fetchall() == [("shared.test",)]
        cursor.execute("SELECT host FROM public.research_fetchattempt")
        assert cursor.fetchall() == [("shared.test",)]

        # Every column is named because Django keeps its defaults in Python, so
        # the table has none: a column added later belongs in this list, or the
        # refusal under test arrives as a NOT NULL violation instead.
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                "INSERT INTO public.research_hostprofile (host, start_rung, geo_code, "
                "languages, wait_selector, custom_wait_ms, timeout_ms, "
                "consecutive_blocks, updated_at) "
                "VALUES ('nope.test', 1, '', '[]'::jsonb, '', 0, 0, 0, now())"
            )
        # The control: this SQLSTATE is also what a missing GRANT raises, so the
        # message is what separates "the policy refused it" from "the role never
        # reached the table".
        assert "row-level security policy" in str(refused.value)

    with runtime_connection.cursor() as cursor:
        cursor.execute("UPDATE public.research_hostprofile SET start_rung = 1")
        assert cursor.rowcount == 0
        cursor.execute("DELETE FROM public.research_fetchattempt")
        assert cursor.rowcount == 0

    assert HostProfile.objects.get(host="shared.test").start_rung == 3
    assert FetchAttempt.objects.count() == 1
