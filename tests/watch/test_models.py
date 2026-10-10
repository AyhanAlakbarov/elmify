"""The watch app's two tables and the tenant guards Django cannot write."""

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.watch.models import Expectation

pytestmark = pytest.mark.django_db


def _application(agency, student, portal_form):
    with tenant_scope(agency.id):
        return Application.objects.create(
            tenant=agency, student=student, program_id=uuid.uuid4(), portal_form=portal_form
        )


def test_one_expectation_per_application_and_kind(agency_a, membership_a, portal_form):
    application = _application(agency_a, membership_a, portal_form)
    due = timezone.now() + timedelta(hours=48)
    with tenant_scope(agency_a.id):
        Expectation.objects.create(
            tenant=agency_a, application=application, kind="CONFIRMATION", due_at=due
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Expectation.objects.create(
                tenant=agency_a, application=application, kind="CONFIRMATION", due_at=due
            )


def test_an_expectation_cannot_name_another_tenants_application(
    agency_a, agency_b, membership_b, portal_form
):
    application_b = _application(agency_b, membership_b, portal_form)
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO watch_expectation (id, tenant_id, application_id, kind, due_at, created_at)
            VALUES (%s, %s, %s, 'CONFIRMATION', now(), now())
            """,
            [uuid.uuid4(), agency_a.id, application_b.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "expectation_app_tenant_fk"


def test_an_expectation_cannot_name_another_tenants_notification(
    agency_a, agency_b, membership_a, membership_b, portal_form
):
    application_a = _application(agency_a, membership_a, portal_form)
    with tenant_scope(agency_b.id):
        item_b = RoadmapItem.objects.create(
            tenant=agency_b,
            student=membership_b,
            stage=RoadmapItem.Stage.MONITORING,
            owner=membership_b,
            deadline=timezone.now(),
        )
        note_b = Notification.objects.create(
            tenant=agency_b, recipient=membership_b, roadmap_item=item_b, message="x"
        )
    with (
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO watch_expectation
                (id, tenant_id, application_id, kind, due_at, alerted_id, created_at)
            VALUES (%s, %s, %s, 'CONFIRMATION', now(), %s, now())
            """,
            [uuid.uuid4(), agency_a.id, application_a.id, note_b.id],
        )
    assert caught.value.__cause__.diag.constraint_name == "expectation_alert_tenant_fk"


def test_expectation_is_forced_behind_row_level_security():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'public.watch_expectation'::regclass"
        )
        assert cursor.fetchone() == (True, True)
