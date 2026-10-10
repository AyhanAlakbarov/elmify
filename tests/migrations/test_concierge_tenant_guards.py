"""Concierge tenant guards. Django writes only single-column FKs and the suite's
role bypasses RLS, so this reads the catalog for the RLS policies and composite
tenant FKs, and proves one guard rejects a cross-tenant row at the database
level, as test_portals_tenant_guards.py does.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope

_RLS_TABLES = ("concierge_studentcycle",)
_COMPOSITE_FKS = {
    "concierge_notification": {"notification_application_tenant_fk"},
    "concierge_studentcycle": {"studentcycle_student_tenant_fk"},
}


@pytest.mark.django_db
@pytest.mark.parametrize("table", _RLS_TABLES)
def test_table_forces_row_level_security_with_a_tenant_policy(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
            [f"public.{table}"],
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute("SELECT polname FROM pg_policy WHERE polrelid = %s::regclass", [f"public.{table}"])
        assert {row[0] for row in cursor.fetchall()} == {"tenant_isolation"}


@pytest.mark.django_db
@pytest.mark.parametrize("table", sorted(_COMPOSITE_FKS))
def test_the_composite_tenant_foreign_keys_exist(table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'",
            [f"public.{table}"],
        )
        found = {row[0] for row in cursor.fetchall()}
    assert _COMPOSITE_FKS[table] <= found, f"missing on {table}: {sorted(_COMPOSITE_FKS[table] - found)}"


@pytest.mark.django_db
def test_a_notification_cannot_name_another_tenants_application(
    agency_a, agency_b, membership_a, membership_b
) -> None:
    with tenant_scope(agency_b.id):
        application_b = Application.objects.create(
            tenant=agency_b, student=membership_b, program_id=uuid.uuid4()
        )
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.SUBMISSION,
            owner=membership_a,
            owner_kind=RoadmapItem.OwnerKind.HUMAN,
            deadline=timezone.now(),
        )
        with pytest.raises(IntegrityError) as caught, transaction.atomic():
            Notification.objects.create(
                tenant=agency_a,
                recipient=membership_a,
                roadmap_item=item,
                message="m",
                application=application_b,
            )
    assert caught.value.__cause__.diag.constraint_name == "notification_application_tenant_fk"
