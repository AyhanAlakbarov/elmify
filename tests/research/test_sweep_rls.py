"""RLS on the sweep harness's four tables, through a role that cannot bypass it.

CLAUDE.md: the test role bypasses RLS, so only `runtime_connection` proves a
policy. The write test grants INSERT first, because an ungranted role is refused
with the same `InsufficientPrivilege` a policy raises -- the message is what
separates the two (the negative control `test_site_job_record_rls.py` carries).

None of these tables' `id` columns carry a database-level default (`uuid4` is
applied by the ORM, not the schema), so `INSERT ... DEFAULT VALUES` raises
`NotNullViolation` on `id` before the RLS policy is ever reached -- confirmed
by running this test against the schema migration alone, before the RLS
migration existed. Each write attempt below therefore supplies a full,
constraint-valid row (as `test_closed_list_rls.py` does), with any FK targets
pre-created through the ORM connection, which bypasses RLS.
"""

from datetime import UTC, datetime

import psycopg
import pytest
from django.db import connection
from psycopg import sql

from apps.research.models import Organisation, SweepAngle, SweepQuery, SweepRun

pytestmark = pytest.mark.django_db

_TABLES = (
    "research_sweepangle",
    "research_sweeprun",
    "research_sweepquery",
    "research_sweepdiscovery",
)


def _angle() -> SweepAngle:
    return SweepAngle.objects.create(
        country_code="TR", family="PRIVATE_FOUNDATION", language="tr", angle="APPLICATION",
        sample=0, version=1, cycle="2026-2027",
        query="Vakfımız her yıl yüksek lisans öğrencilerine burs vermektedir.",
        brave_terms='intitle:vakfı "burs başvurusu"', written_by="test",
    )


def _run() -> SweepRun:
    return SweepRun.objects.create(
        country_code="TR", family="PRIVATE_FOUNDATION", languages=["tr"], rung=4, register="",
        cycle="2026-2027", started_at=datetime(2026, 9, 26, tzinfo=UTC),
    )


def _query(run: SweepRun, angle: SweepAngle) -> SweepQuery:
    return SweepQuery.objects.create(run=run, batch_number=1, angle=angle, provider="exa")


def _organisation() -> Organisation:
    return Organisation.objects.create(
        primary_domain="sweep-rls-test.example", name="Sweep RLS Test", kind="PRIVATE_FOUNDATION"
    )


_INSERT_SQL = {
    "research_sweepangle": (
        "INSERT INTO research_sweepangle "
        "(id, country_code, family, language, angle, sample, version, cycle, query, "
        "brave_terms, written_by, written_at, retired_reason) "
        "VALUES (gen_random_uuid(), 'TR', 'PRIVATE_FOUNDATION', 'tr', 'APPLICATION', 1, 1, "
        "'2026-2027', 'q', '', 'test', now(), '')"
    ),
    "research_sweeprun": (
        "INSERT INTO research_sweeprun "
        "(id, country_code, family, languages, rung, register, cycle, started_at, "
        "stop_reason, batches, search_usd, fetch_usd, recaptured, dropped_providers) "
        "VALUES (gen_random_uuid(), 'TR', 'PRIVATE_FOUNDATION', '{tr}', 4, '', "
        "'2026-2027', now(), '', 0, 0.0, 0.0, 0, '{}')"
    ),
}


@pytest.mark.django_db(transaction=True)
def test_an_angle_is_readable_by_the_runtime_role(runtime_connection):
    _angle()
    with runtime_connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM research_sweepangle")
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("table", _TABLES)
def test_the_runtime_role_cannot_write(runtime_connection, table):
    if table == "research_sweepquery":
        run, angle = _run(), _angle()
        insert_sql = (
            "INSERT INTO research_sweepquery "
            "(id, run_id, batch_number, angle_id, provider, seen, denied, novel, cost_usd) "
            f"VALUES (gen_random_uuid(), '{run.id}', 1, '{angle.id}', 'exa', 0, 0, 0, 0.0)"
        )
    elif table == "research_sweepdiscovery":
        run, angle = _run(), _angle()
        query = _query(run, angle)
        org = _organisation()
        insert_sql = (
            "INSERT INTO research_sweepdiscovery "
            "(id, run_id, query_id, organisation_id, verified_in_pass) "
            f"VALUES (gen_random_uuid(), '{run.id}', '{query.id}', '{org.id}', false)"
        )
    else:
        insert_sql = _INSERT_SQL[table]

    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(sql.Identifier("public", table), role)
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(%s, %s, 'INSERT')",
            [runtime_connection.info.user, f"public.{table}"],
        )
        assert cursor.fetchone() == (True,), "grant did not take"
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(insert_sql)
        assert "row-level security policy" in str(refused.value)
