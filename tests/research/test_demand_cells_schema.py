"""The demand-cell tables' database-level edges (build item 14, Task 4).

SearchTap's run and pack edges are plain UUID columns in Django (research may
not depend on funding), so the ONLY thing holding them is the pair of
composite FKs funding/0054_pack_coverage adds. These tests pin both in
pg_constraint and exercise each: a constraint nothing checks is a constraint a
later migration can drop in silence.

The default test role is a superuser, which bypasses RLS but NOT foreign keys,
so the cross-tenant refusals here are real. RLS itself is proved behind a
NOBYPASSRLS role elsewhere (tests/tenancy, and the plan's Task 13).
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction

from apps.funding.models import PackVersion
from apps.research.models import AreaSweep, SearchTap, SearchWallet
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import make_run

pytestmark = pytest.mark.django_db


def _constraint(name: str) -> tuple[str, str, str, list[str] | None]:
    """(table, referenced table, ON DELETE action, SET NULL column list)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conrelid::regclass::text, c.confrelid::regclass::text,
                   c.confdeltype,
                   (SELECT array_agg(a.attname ORDER BY a.attname)
                      FROM pg_attribute AS a
                     WHERE a.attrelid = c.conrelid
                       AND a.attnum = ANY (c.confdelsetcols))
              FROM pg_constraint AS c
             WHERE c.conname = %s AND c.contype = 'f'
            """,
            [name],
        )
        row = cursor.fetchone()
    assert row is not None, f"{name} is missing"
    return row


def _columns(name: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.attname
              FROM pg_constraint AS c
              JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, n) ON true
              JOIN pg_attribute AS a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
             WHERE c.conname = %s
             ORDER BY k.n
            """,
            [name],
        )
        return [row[0] for row in cursor.fetchall()]


def test_the_tap_run_edge_is_a_tenant_guarded_cascade() -> None:
    table, target, action, _ = _constraint("searchtap_run_tenant_fk")
    assert (table, target, action) == (
        "research_searchtap", "funding_recommendationrun", "c"
    )
    assert _columns("searchtap_run_tenant_fk") == ["tenant_id", "run_id"]


def test_the_tap_pack_edge_nulls_only_the_pack_column() -> None:
    # A bare SET NULL would null tenant_id too (NOT NULL), so a pack delete
    # would fail; the column list is what makes it work.
    table, target, action, set_null = _constraint("searchtap_pack_version_tenant_fk")
    assert (table, target, action) == ("research_searchtap", "funding_packversion", "n")
    assert set_null == ["pack_version_id"]
    assert _columns("searchtap_pack_version_tenant_fk") == ["tenant_id", "pack_version_id"]


@pytest.mark.parametrize(
    ("name", "table", "column", "target"),
    [
        ("profilecellselection_student_tenant_fk", "research_profilecellselection",
         "student_id", "tenancy_membership"),
        ("profilecellselection_profile_tenant_fk", "research_profilecellselection",
         "profile_version_id", "accounts_studentprofileversion"),
        ("searchwallet_student_tenant_fk", "research_searchwallet",
         "student_id", "tenancy_membership"),
        ("searchtap_student_tenant_fk", "research_searchtap", "student_id", "tenancy_membership"),
        ("searchtap_wallet_tenant_fk", "research_searchtap", "wallet_id", "research_searchwallet"),
        ("walletcharge_wallet_tenant_fk", "research_walletcharge",
         "wallet_id", "research_searchwallet"),
        ("walletcharge_tap_tenant_fk", "research_walletcharge", "tap_id", "research_searchtap"),
    ],
)
def test_every_intra_tenant_edge_carries_a_composite_guard(name, table, column, target) -> None:
    got_table, got_target, _action, _ = _constraint(name)
    assert (got_table, got_target) == (table, target)
    assert _columns(name) == ["tenant_id", column]


def _wallet(agency, membership) -> SearchWallet:
    with tenant_scope(agency.id):
        return SearchWallet.objects.create(
            student=membership, intended_intake=date(2027, 9, 1), budget_usd=Decimal("50")
        )


def test_a_tap_cannot_point_at_another_tenants_run(
    agency_a, membership_a, agency_b, membership_b
) -> None:
    wallet = _wallet(agency_a, membership_a)
    foreign_run = make_run(agency_b, membership_b)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        SearchTap.objects.create(
            student=membership_a, wallet=wallet, run_id=foreign_run.id,
            allowance_usd=Decimal("25"),
        )


def test_a_tap_cannot_point_at_another_tenants_pack(
    agency_a, membership_a, agency_b, membership_b
) -> None:
    wallet = _wallet(agency_a, membership_a)
    run = make_run(agency_a, membership_a)
    foreign_run = make_run(agency_b, membership_b)
    with tenant_scope(agency_b.id):
        foreign_pack = PackVersion.objects.create(run=foreign_run, version=1)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        SearchTap.objects.create(
            student=membership_a, wallet=wallet, run_id=run.id,
            pack_version_id=foreign_pack.id, allowance_usd=Decimal("25"),
        )


def test_deleting_a_pack_keeps_the_tap_and_forgets_the_pack(agency_a, membership_a) -> None:
    wallet = _wallet(agency_a, membership_a)
    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1)
        tap = SearchTap.objects.create(
            student=membership_a, wallet=wallet, run_id=run.id, pack_version_id=pack.id,
            allowance_usd=Decimal("25"),
        )
        pack.delete()
        tap.refresh_from_db()
    assert tap.pack_version_id is None and tap.tenant_id == agency_a.id


def test_a_wallet_cannot_be_opened_for_another_tenants_student(
    agency_a, membership_b
) -> None:
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        SearchWallet.objects.create(
            student=membership_b, intended_intake=date(2027, 9, 1), budget_usd=Decimal("50")
        )


def test_an_area_has_at_most_one_open_sweep_and_only_a_swept_family() -> None:
    AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    with pytest.raises(IntegrityError), transaction.atomic():
        AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION")
    AreaSweep.objects.create(country_code="AZ", family="PRIVATE_FOUNDATION", state="DONE")
    with pytest.raises(IntegrityError), transaction.atomic():
        AreaSweep.objects.create(country_code="DE", family="UNIVERSITY_WIDE")
