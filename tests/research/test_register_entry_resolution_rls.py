"""The resolver's five columns on RegisterEntry, through roles that cannot bypass RLS.

No new table, so the columns inherit research/0007's policies as funding/0049
left them: `shared_catalog_select` for every tenant, `runtime_engine_write`
for the engine alone, and no table grant at all for `runtime_web`. CLAUDE.md:
the test role bypasses RLS, so each claim is made through a real NOBYPASSRLS
login -- `runtime_connection` (a member of neither runtime role) and
`role_connection` (a member of one). An UPDATE the policy refuses does not
raise, it matches zero rows -- which is why resolve_entries checks its row
count -- so the engine's UPDATE matching one row is the control that shows the
zero is the policy, not a WHERE clause that matched nothing.
"""

import psycopg
import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import RegisterEntry

pytestmark = pytest.mark.django_db

#: All five new columns, in a shape the constraint accepts.
_UPDATE = (
    "UPDATE research_registerentry SET resolution = 'RESOLVED', resolved_via = 'DIFFBOT', "
    "unresolved_reason = '', names = ARRAY['BİLİM VE SANAT VAKFI', 'x'], "
    "resolution_attempted_at = now(), diffbot_asked_at = now() WHERE external_key = 'k'"
)


def _entry() -> RegisterEntry:
    return RegisterEntry.objects.create(
        register="vgm_tr", external_key="k", name="BİLİM VE SANAT VAKFI",
        names=["BİLİM VE SANAT VAKFI"], resolution=RegisterEntry.Resolution.UNRESOLVED,
        last_seen=timezone.now(),
    )


@pytest.mark.django_db(transaction=True)
def test_a_tenant_reads_the_row_and_its_update_matches_nothing(runtime_connection) -> None:
    """The UPDATE grant is given first, so the zero is the POLICY's refusal:
    an ungranted role would raise InsufficientPrivilege instead."""
    _entry()
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("GRANT UPDATE ON TABLE {} TO {}").format(
            sql.Identifier("public", "research_registerentry"), role))
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT names, resolved_via FROM research_registerentry")
        assert cursor.fetchall() == [(["BİLİM VE SANAT VAKFI"], "")], (
            "the policy must still let every tenant read")
        cursor.execute(_UPDATE)
        assert cursor.rowcount == 0
    entry = RegisterEntry.objects.get(external_key="k")
    assert (entry.resolution, entry.resolved_via, entry.diffbot_asked_at) == (
        "UNRESOLVED", "", None)


@pytest.mark.django_db(transaction=True)
def test_the_engine_writes_the_new_columns(role_connection) -> None:
    """`runtime_engine` is what resolve_register runs as."""
    _entry()
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_UPDATE)
        assert cursor.rowcount == 1
    entry = RegisterEntry.objects.get(external_key="k")
    assert (entry.resolution, entry.resolved_via) == ("RESOLVED", "DIFFBOT")
    assert entry.names == ["BİLİM VE SANAT VAKFI", "x"] and entry.diffbot_asked_at is not None


@pytest.mark.django_db(transaction=True)
def test_the_web_tier_cannot_even_read_the_row(role_connection) -> None:
    """The catalogue boundary is a GRANT, not a policy: permission denied,
    never an empty answer."""
    _entry()
    with role_connection("runtime_web") as conn, conn.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cursor.execute("SELECT names, resolved_via FROM research_registerentry")
