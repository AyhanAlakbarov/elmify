"""The pointer columns on RegisterEntry, through roles that cannot bypass RLS.

No new table, so the columns inherit research/0007's policies as funding/0049
left them. The engine's UPDATE matching one row is the control that shows the
tenant's zero is the policy's refusal, not a WHERE clause that matched nothing.
"""

import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import RegisterEntry

pytestmark = pytest.mark.django_db

_UPDATE = (
    "UPDATE research_registerentry SET pointer_quote = 'a line', "
    "pointer_url = 'https://example-agency.az/x' WHERE external_key = 'k'"
)


def _entry() -> RegisterEntry:
    return RegisterEntry.objects.create(
        register="pointer", external_key="k", name="Body", names=["Body"],
        resolution=RegisterEntry.Resolution.UNRESOLVED, last_seen=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_the_engine_writes_the_pointer_columns(role_connection) -> None:
    _entry()
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_UPDATE)
        assert cursor.rowcount == 1
    assert RegisterEntry.objects.get().pointer_quote == "a line"


@pytest.mark.django_db(transaction=True)
def test_a_tenant_reads_the_row_and_its_update_matches_nothing(runtime_connection) -> None:
    _entry()
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("GRANT UPDATE ON TABLE {} TO {}").format(
            sql.Identifier("public", "research_registerentry"), role))
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT pointer_quote FROM research_registerentry")
        assert cursor.fetchall() == [("",)]
        cursor.execute(_UPDATE)
        assert cursor.rowcount == 0
    assert RegisterEntry.objects.get().pointer_url == ""
