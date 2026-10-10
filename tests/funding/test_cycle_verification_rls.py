"""RLS and grants on FundingCycleVerification, verified through roles that cannot bypass them.

Shared catalog: every tenant reads it, `runtime_engine` alone writes it
(`runtime_engine_write`), and `runtime_web` holds no table grant at all. The
test role bypasses RLS and grants alike (CLAUDE.md), so each claim is made
through a real NOBYPASSRLS login: `runtime_connection` (a member of neither
runtime role, so `runtime_engine_write` never applies to it) and
`role_connection` (a member of one).

The write-refusal test grants INSERT first: an ungranted role is refused with
the same SQLSTATE a real policy raises, so only the message separates the two
(the negative control from test_site_job_record_rls.py).
"""

import psycopg
import pytest
from django.db import IntegrityError, connection
from psycopg import sql

from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.tenancy.models import TenantScopedModel

pytestmark = pytest.mark.django_db
TABLE = "funding_fundingcycleverification"

_INSERT = (
    f"INSERT INTO {TABLE} (id, opportunity_id, intake_start_year, state, evidence, "
    "trail, cycles_observed, projection_lapsed, page_removed, ladder_step, cost_usd, "
    "cost_detail, cost_complete, created_at, updated_at) VALUES (gen_random_uuid(), "
    "%s, 2027, 'UNVERIFIED', '[]', '[]', '[]', false, false, '', 0, '{}', true, "
    "now(), now())"
)


def _opportunity():
    return FundingOpportunity.objects.create(
        canonical_key="read:test-award", name="Test Award", family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL",
    )


@pytest.mark.django_db(transaction=True)
def test_a_verification_is_readable_by_every_tenant(runtime_connection):
    FundingCycleVerification.objects.create(opportunity=_opportunity(), intake_start_year=2027)
    with runtime_connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert cursor.fetchone()[0] == 1


@pytest.mark.django_db(transaction=True)
def test_a_runtime_role_cannot_write_one(runtime_connection):
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(sql.Identifier("public", TABLE), role)
        )
    opportunity = _opportunity()
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(%s, %s, 'INSERT')",
            [runtime_connection.info.user, f"public.{TABLE}"],
        )
        assert cursor.fetchone() == (True,), "grant did not take"
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(_INSERT, [opportunity.id])
        assert "row-level security policy" in str(refused.value)


@pytest.mark.django_db(transaction=True)
def test_the_engine_writes_one(role_connection):
    """`runtime_engine` is what the verifier runs as -- the catalogue's only writer."""
    opportunity = _opportunity()
    with role_connection("runtime_engine") as conn, conn.cursor() as cursor:
        cursor.execute(_INSERT, [opportunity.id])
        assert cursor.rowcount == 1
    assert FundingCycleVerification.objects.filter(opportunity=opportunity).count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_web_tier_cannot_even_read_one(role_connection):
    """The catalogue boundary is a GRANT, not a policy: permission denied,
    never an empty answer."""
    FundingCycleVerification.objects.create(opportunity=_opportunity(), intake_start_year=2027)
    with role_connection("runtime_web") as conn, conn.cursor() as cursor:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as refused:
            cursor.execute(f"SELECT count(*) FROM {TABLE}")
        assert "permission denied" in str(refused.value)


def test_one_row_per_award_per_intake():
    opportunity = _opportunity()
    FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)
    with pytest.raises(IntegrityError):
        FundingCycleVerification.objects.create(opportunity=opportunity, intake_start_year=2027)


def test_the_row_can_reach_no_person():
    """No FK to a tenant-scoped model: a shared row that could reach a student
    is a personal datum outside the erasure sweep (CLAUDE.md, derived data)."""
    for field in FundingCycleVerification._meta.get_fields():
        target = getattr(field, "related_model", None)
        if target is not None:
            assert not issubclass(target, TenantScopedModel), field.name
