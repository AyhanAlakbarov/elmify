"""portals_application and portals_remindersent carry composite tenant FKs on
their child-of-another-tenant-table columns. The model-side test cannot see
either: Django writes neither, and the suite's role bypasses RLS. This reads
the catalog for existence and proves each one actually rejects a cross-tenant
row at the database level, the way tests/funding/test_tenant_constraints.py
does for its own named constraints.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.concierge.models import RoadmapItem
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope

_COMPOSITE_FKS = {
    "portals_application": {
        "portal_app_exception_tenant_fk",
        "portal_app_reminder_tenant_fk",
        "portal_app_candidate_tenant_fk",
        "portal_app_evidence_tenant_fk",
    },
    "portals_remindersent": {"remindersent_app_tenant_fk"},
    "portals_applicationlink": {"portal_link_from_tenant_fk", "portal_link_to_tenant_fk"},
}


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


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application_a(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
        )


@pytest.fixture
def roadmap_item_b(agency_b, membership_b):
    with tenant_scope(agency_b.id):
        return RoadmapItem.objects.create(
            tenant=agency_b,
            student=membership_b,
            stage=RoadmapItem.Stage.SUBMISSION,
            owner=membership_b,
            owner_kind=RoadmapItem.OwnerKind.HUMAN,
            deadline=timezone.now(),
        )


def test_an_applications_reminder_item_cannot_name_another_tenants_roadmap_item(
    agency_a, application_a, roadmap_item_b
) -> None:
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE portals_application SET reminder_item_id = %s WHERE id = %s",
            [roadmap_item_b.id, application_a.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "portal_app_reminder_tenant_fk"


def test_a_remindersent_row_cannot_name_another_tenants_application(
    agency_a, agency_b, membership_a, membership_b, portal_form
) -> None:
    with tenant_scope(agency_b.id):
        application_b = Application.objects.create(
            tenant=agency_b,
            student=membership_b,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
        )
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO portals_remindersent
                (id, tenant_id, application_id, rung, sent, sent_at)
            VALUES (%s, %s, %s, 'D7', false, now())
            """,
            [uuid.uuid4(), agency_a.id, application_b.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "remindersent_app_tenant_fk"


def test_an_application_cannot_be_added_from_another_tenants_candidate(
    agency_a, agency_b, membership_a, membership_b
) -> None:
    from tests.funding.conftest import make_db_candidate, make_run

    candidate_b = make_db_candidate(agency_b, make_run(agency_b, membership_b))
    with (
        tenant_scope(agency_a.id),
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
    ):
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            candidate=candidate_b,
        )
    assert caught.value.__cause__.diag.constraint_name == "portal_app_candidate_tenant_fk"


def test_an_applications_outcome_evidence_cannot_name_another_tenants_mail(
    agency_b, membership_b, application_a
) -> None:
    from apps.mailbox.models import MailboxConnection, MailSignal

    with tenant_scope(agency_b.id):
        connection_b = MailboxConnection.objects.create(
            tenant=agency_b,
            membership=membership_b,
            provider="MICROSOFT",
            address="b@outlook.test",
        )
        signal_b = MailSignal.objects.create(
            tenant=agency_b,
            connection=connection_b,
            provider_message_id="m-b",
            sender_domain="tum.de",
            received_at=timezone.now(),
            label="DECISION",
        )
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE portals_application SET outcome_evidence_id = %s WHERE id = %s",
            [signal_b.id, application_a.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "portal_app_evidence_tenant_fk"
