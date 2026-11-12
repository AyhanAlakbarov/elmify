"""The per-student search's tables and writes, behind roles RLS and grants apply to.

The suite's default role bypasses RLS, so none of this is visible to an ordinary
test (CLAUDE.md). Tenant tables are read through `rls_enforced_orm` (a
NOBYPASSRLS role with DML everywhere, so a refusal is the POLICY's); the shared
catalogue's write side and the tap's real writes go through `engine_role_orm`
(a member of `runtime_engine`); the web tier's missing grant through
`role_connection("runtime_web")`. Rows are committed as the superuser before any
role swap, so those tests are `transaction=True`.
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.funding.models import PackVersion
from apps.research.models import (
    AreaSweep,
    CellCoverage,
    Organisation,
    ProfileCellSelection,
    ProgrammeAngle,
    SearchTap,
    SearchWallet,
    TapQueryRun,
    WalletCharge,
)
from apps.research.register import record_organisation
from apps.research.tap import maybe_queue_area_sweep
from apps.research.tap_seams import NullSeams
from apps.research.wallet import charge
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.funding.conftest import make_run
from tests.research.coverage_factories import make_published_student

pytestmark = pytest.mark.django_db(transaction=True)

@contextmanager
def _as(tenant_id):
    """Both filters: the manager's contextvar and the policy's GUC."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        yield


_TENANT_TABLES = {
    "wallet": SearchWallet, "tap": SearchTap, "charge": WalletCharge,
    "selection": ProfileCellSelection, "cover": CellCoverage,
}


def _side(agency, user_model):
    student = make_published_student(agency, user_model, allowed=("DE",))
    with tenant_scope(agency.id):
        run = make_run(agency, student)
        wallet = SearchWallet.objects.create(
            student=student, intended_intake=date(2027, 9, 1), budget_usd=Decimal("100")
        )
        tap = SearchTap.objects.create(
            student=student, wallet=wallet, run_id=run.id, allowance_usd=Decimal("50")
        )
        made = WalletCharge.objects.create(
            wallet=wallet, tap=tap, kind="SEARCH", provider="exa", usd=Decimal("0.01")
        )
        pack = PackVersion.objects.filter(run__profile_version__student=student).first()
        area = {"country": "DE", "family": "PRIVATE_FOUNDATION", "eligible": 0}
        pack.coverage = {"areas": [area]}
        pack.save(update_fields=["coverage"])
        # make_published_student seeded one ProfileCellSelection per student; a
        # cross-tenant check over an empty table would be vacuous.
        selection = ProfileCellSelection.objects.get(student=student)
        cover = CellCoverage.objects.create(
            holder="PRIVATE_FOUNDATION", host_country="DE", home_country="AZ",
            discipline_bucket="physical_sciences", refreshed_at=timezone.now(),
        )
    return SimpleNamespace(
        tenant_id=agency.id, student=student, wallet=wallet, tap=tap, charge=made, pack=pack,
        ids={"wallet": wallet.id, "tap": tap.id, "charge": made.id,
             "selection": selection.id, "cover": cover.id},
    )


@pytest.fixture
def two(agency_a, agency_b, django_user_model):
    return _side(agency_a, django_user_model), _side(agency_b, django_user_model)


# Fails without the tenant policy: a NOBYPASSRLS role with DML would see both
# tenants' rows. Each side has one committed row per table to hide.
@pytest.mark.parametrize("name", list(_TENANT_TABLES))
def test_a_tenant_sees_only_its_own_rows(two, rls_enforced_orm, name) -> None:
    a, b = two
    model = _TENANT_TABLES[name]
    for side, other in ((a, b), (b, a)):
        with _as(side.tenant_id):
            assert set(model.objects.values_list("id", flat=True)) == {side.ids[name]}
            assert not model.objects.filter(id=other.ids[name]).exists()


@pytest.mark.parametrize("name", list(_TENANT_TABLES))
def test_with_no_tenant_set_a_tenant_table_reads_empty(two, rls_enforced_orm, name) -> None:
    with transaction.atomic():
        assert _TENANT_TABLES[name]._base_manager.count() == 0


def test_the_composite_fk_refuses_a_charge_on_another_tenants_wallet(two, rls_enforced_orm) -> None:
    """Fails if the tenant FKs (migration 0014) are dropped: A's own row, B's wallet."""
    a, b = two
    with pytest.raises(DatabaseError, match="walletcharge_wallet_tenant_fk"), _as(a.tenant_id):
        WalletCharge.objects.create(
            tenant_id=a.tenant_id, wallet_id=b.wallet.id, tap_id=a.tap.id, kind="SEARCH",
            provider="exa", usd=Decimal("0.01"),
        )


def test_the_policy_refuses_a_charge_stamped_with_another_tenant(two, rls_enforced_orm) -> None:
    """Fails if the WITH CHECK is dropped: tenant_id, wallet and tap are all B's, so
    every FK is satisfied and only the policy (GUC = A) can refuse the row."""
    a, b = two
    # Raw SQL: the model's own save() raises "tenant mismatch" before the database is asked.
    with pytest.raises(DatabaseError, match="row-level security"), _as(a.tenant_id):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO research_walletcharge "
                "(id, tenant_id, wallet_id, tap_id, kind, provider, usd, created_at) "
                "VALUES (gen_random_uuid(), %s, %s, %s, 'SEARCH', 'exa', 0.01, now())",
                [b.tenant_id, b.wallet.id, b.tap.id],
            )


_ANGLE = dict(language="en", kind="PROGRAMME", sample=1, version=1, cycle="2026-2027",
              template="{field} master", written_by="test")


@pytest.fixture
def catalogue(two):
    """As the superuser (request before any role fixture): one row in each shared table."""
    ProgrammeAngle.objects.create(**_ANGLE)
    TapQueryRun.objects.create(
        query_sha256="a" * 64, provider="exa", results=10, ran_at=timezone.now()
    )


def test_a_tenant_reads_the_shared_rows_and_cannot_write_them(
    two, catalogue, rls_enforced_orm
) -> None:
    """Needs a committed row. Read: fails without `shared_catalog_select` (RLS on, no
    policy => 0 rows). INSERT: fails without RLS or with a permissive policy. UPDATE and
    DELETE: Postgres gives a role with a SELECT-only policy no error -- the rows are
    simply not visible to those commands, so they affect 0 rows -- hence the asserts on
    the count AND on the row being unchanged. Fails if a tenant write policy exists."""
    a, _ = two
    with _as(a.tenant_id):
        assert ProgrammeAngle.objects.count() == 1 and TapQueryRun.objects.count() == 1
        with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
            ProgrammeAngle.objects.create(**{**_ANGLE, "sample": 2})
        with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
            TapQueryRun.objects.create(
                query_sha256="c" * 64, provider="exa", results=10, ran_at=timezone.now()
            )
        assert ProgrammeAngle.objects.update(template="hijacked") == 0
        assert ProgrammeAngle.objects.all().delete() == (0, {})
        assert TapQueryRun.objects.update(provider="brave") == 0
        assert TapQueryRun.objects.all().delete() == (0, {})
        assert ProgrammeAngle.objects.get().template == _ANGLE["template"]
        assert TapQueryRun.objects.get().provider == "exa"


def test_the_engine_writes_the_shared_rows(two, engine_role_orm) -> None:
    """Fails without the engine's GRANT or `runtime_engine_write` policy."""
    ProgrammeAngle.objects.create(**_ANGLE)
    TapQueryRun.objects.create(
        query_sha256="a" * 64, provider="exa", results=10, ran_at=timezone.now()
    )
    assert ProgrammeAngle.objects.count() == 1 and TapQueryRun.objects.count() == 1


def test_rows_the_engine_wrote_are_read_by_a_tenant_session(two, catalogue, runtime_connection):
    """Raw NOBYPASSRLS connection with a tenant GUC: fails without the SELECT policy."""
    a, _ = two
    with runtime_connection.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", [str(a.tenant_id)])
        for table in ("research_programmeangle", "research_tapqueryrun"):
            cur.execute(f"SELECT count(*) FROM {table}")
            assert cur.fetchone()[0] == 1


def test_an_area_sweep_row_is_readable_as_a_tenant(two, runtime_connection) -> None:
    """Fails without the SELECT policy (0 rows). Its write refusal is pinned by
    test_task7_rls_policy_shapes_and_runtime_acl (research_areasweep is in _SHARED_TABLES)."""
    a, _ = two
    sweep = AreaSweep.objects.create(country_code="DE", family="PRIVATE_FOUNDATION")
    with runtime_connection.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", [str(a.tenant_id)])
        cur.execute("SELECT count(*) FROM research_areasweep WHERE id = %s", [sweep.id])
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("table", ["research_programmeangle", "research_tapqueryrun"])
def test_the_web_tier_has_no_grant_on_the_search_catalogue(role_connection, table) -> None:
    with role_connection("runtime_web") as conn, conn.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
        assert f"permission denied for table {table}" in str(refused.value)


# --- the writes the tap and the area sweep make, as runtime_engine ------------------


def test_record_organisation_writes_a_candidate_as_the_engine(two, engine_role_orm) -> None:
    org = record_organisation(
        domain="new-body-rls.org", name="New Body", kind="PRIVATE_FOUNDATION",
        country_code="DE", found_via="TAP",
    )
    assert Organisation.objects.get(id=org.id).status == Organisation.Status.CANDIDATE


def test_the_area_sweep_is_queued_and_demand_added_as_the_engine(two, engine_role_orm) -> None:
    a, _ = two
    with tenant_scope(a.tenant_id):
        queued = maybe_queue_area_sweep(a.tap, a.pack, NullSeams())
        again = maybe_queue_area_sweep(a.tap, a.pack, NullSeams())
    assert queued is not None
    assert again.id == queued.id
    assert AreaSweep.objects.get(id=queued.id).demand == queued.demand + 1


def test_a_charge_and_the_tap_counters_write_as_the_engine(two, engine_role_orm) -> None:
    a, _ = two
    with tenant_scope(a.tenant_id):
        charge(a.tap, kind="SEARCH", provider="exa", usd=Decimal("0.5"))
    with _as(a.tenant_id):
        assert WalletCharge.objects.filter(tap_id=a.tap.id).count() == 2
        assert SearchWallet.objects.get(id=a.wallet.id).spent_usd == Decimal("0.5")
        a.tap.provider_calls, a.tap.hosts_new, a.tap.queries_reused = 3, 2, 1
        a.tap.save(update_fields=["provider_calls", "hosts_new", "queries_reused"])
        assert SearchTap.objects.get(id=a.tap.id).queries_reused == 1


def test_the_query_run_upsert_works_as_the_engine(two, engine_role_orm) -> None:
    a, _ = two
    key = dict(query_sha256="b" * 64, provider="exa", results=10)
    for _ in range(2):
        with _as(a.tenant_id):
            TapQueryRun.objects.update_or_create(**key, defaults={"ran_at": timezone.now()})
    assert TapQueryRun.objects.filter(**key).count() == 1
