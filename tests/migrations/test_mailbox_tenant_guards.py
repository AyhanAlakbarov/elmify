"""The mailbox tables carry RLS and their composite tenant FKs.

The model-side test cannot see either: Django writes neither, and the suite's
role bypasses the policy. This reads the catalog.
"""

from __future__ import annotations

import pytest
from django.db import connection

_RLS_TABLES = ("mailbox_mailboxconnection", "mailbox_mailsignal")

_COMPOSITE_FKS = {
    "mailbox_mailboxconnection": {"mailbox_connection_membership_tenant_fk"},
    "mailbox_mailsignal": {
        "mailbox_signal_connection_tenant_fk",
        "mailbox_signal_app_tenant_fk",
    },
}


@pytest.mark.django_db
@pytest.mark.parametrize("table", _RLS_TABLES)
def test_row_level_security_is_enabled_and_forced(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
            [f"public.{table}"],
        )
        assert cursor.fetchone() == (True, True)


@pytest.mark.django_db
@pytest.mark.parametrize("table", _RLS_TABLES)
def test_the_isolation_policy_exists(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT polname FROM pg_policy WHERE polrelid = %s::regclass", [f"public.{table}"]
        )
        assert [row[0] for row in cursor.fetchall()] == ["tenant_isolation"]


@pytest.mark.django_db
@pytest.mark.parametrize("table", sorted(_COMPOSITE_FKS))
def test_the_composite_tenant_foreign_keys_exist(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'",
            [f"public.{table}"],
        )
        found = {row[0] for row in cursor.fetchall()}
    assert _COMPOSITE_FKS[table] <= found
