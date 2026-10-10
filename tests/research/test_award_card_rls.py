"""The card's new columns sit behind the catalogue's own policies.

CLAUDE.md: the test role bypasses RLS, so this runs as a real NOBYPASSRLS role
through `runtime_connection` -- a throwaway role that is not a member of
`runtime_engine`, the only role `runtime_engine_write` lets write the shared
catalogue. The UPDATE carries the negative control `test_fetch_models_rls.py`
uses: the role is GRANTed UPDATE first, so zero rows touched is the policy's
doing, not a missing privilege.
"""

from uuid import uuid4

import pytest
from django.db import connection
from psycopg import sql

from apps.funding.models import FundingOpportunity

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_the_card_columns_are_readable_with_no_tenant_and_writable_by_nobody_else(
    runtime_connection,
):
    FundingOpportunity.objects.create(
        canonical_key=f"read:{uuid4()}", name="Award", family="UNIVERSITY_WIDE",
        scope_type="GLOBAL", timing="PRE_ARRIVAL", duration_text="24 months",
        duration_months=24,
    )
    role = sql.Identifier(runtime_connection.info.user)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT, UPDATE ON TABLE public.funding_fundingopportunity TO {}")
            .format(role)
        )
    with runtime_connection.cursor() as cursor:
        cursor.execute(
            "SELECT has_table_privilege(%s, 'public.funding_fundingopportunity', 'UPDATE')",
            [runtime_connection.info.user],
        )
        assert cursor.fetchone() == (True,), "the grant did not take"
        cursor.execute(
            "SELECT timing, duration_text, duration_months FROM public.funding_fundingopportunity"
        )
        assert cursor.fetchall() == [("PRE_ARRIVAL", "24 months", 24)]
        cursor.execute("UPDATE public.funding_fundingopportunity SET timing = 'ROLLING'")
        assert cursor.rowcount == 0
    assert FundingOpportunity.objects.get().timing == "PRE_ARRIVAL"
