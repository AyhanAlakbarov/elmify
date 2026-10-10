"""RLS on ClosedList and RegisterEntryPartner, through a role that cannot bypass it.

CLAUDE.md: the test role bypasses RLS, so everything here goes through
`runtime_connection`. The write test grants INSERT first, so the refusal is
the POLICY's -- an ungranted role raises the identical InsufficientPrivilege
(tests/research/test_site_job_record_rls.py carries the same control). The
write policy names `runtime_engine` (funding/0049), and `runtime_connection`
is a member of neither runtime role.
"""

from datetime import date

import psycopg
import pytest
from django.db import connection
from django.utils import timezone
from psycopg import sql

from apps.research.models import ClosedList, RegisterEntry, RegisterEntryPartner

pytestmark = pytest.mark.django_db


def _rows() -> None:
    ClosedList.objects.create(
        slug="igo_regional_global", title="IGO", holder_kinds=["INTERGOVERNMENTAL"], rung=1,
        source_url="https://example.org/list", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="FUNDING_READ", verified_on=date(2026, 9, 25),
    )
    entry = RegisterEntry.objects.create(
        register="eacea_emjm", external_key="p1", name="EMJM", resolution="UNRESOLVED",
        last_seen=timezone.now(),
    )
    RegisterEntryPartner.objects.create(
        entry=entry, role="PARTNER", listed_name="NGO", listed_identifier="1",
        disposition="NO_KEY",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("table", ["research_closedlist", "research_registerentrypartner"])
def test_every_tenant_reads_the_rows(runtime_connection, table: str) -> None:
    _rows()
    with runtime_connection.cursor() as cursor:
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
def test_the_runtime_role_cannot_write_a_list(runtime_connection) -> None:
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_closedlist"), role
            )
        )
    with runtime_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                "INSERT INTO research_closedlist (slug, title, country_code, holder_kinds, "
                "rung, source_url, maintainer, carries_purpose, carries_website, "
                "reuse_terms, reuse_terms_url, is_denominator, read_policy, verified_on) "
                "VALUES ('x', 'x', '', '{}', 1, 'https://x.example/', 'x', true, true, "
                "'OPEN', '', true, 'CLASSIFY', '2026-09-25')"
            )
        assert "row-level security policy" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_the_runtime_role_cannot_write_a_partner(runtime_connection) -> None:
    _rows()
    entry_id = RegisterEntry.objects.get(external_key="p1").id
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(
                sql.Identifier("public", "research_registerentrypartner"), role
            )
        )
    with runtime_connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(
                "INSERT INTO research_registerentrypartner (id, entry_id, role, listed_name, "
                "listed_identifier, listed_domain, country_code, disposition) "
                "VALUES (gen_random_uuid(), %s, 'PARTNER', 'x', '2', '', '', 'NO_KEY')",
                [entry_id],
            )
        assert "row-level security policy" in str(refused.value)
