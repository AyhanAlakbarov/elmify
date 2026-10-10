import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, ApplicationStep
from apps.tenancy.context import tenant_scope
from apps.watch.models import Expectation
from apps.watch.watchdog import watch_applications_for_tenant

pytestmark = pytest.mark.django_db


def _submitted(agency, student, portal_form, *, hours_ago, state="SUBMITTED"):
    """An application submitted `hours_ago`, with the SUBMITTED step the
    extension writes (ext_api.py) dated to match."""
    with tenant_scope(agency.id):
        application = Application.objects.create(
            tenant=agency,
            student=student,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            state=state,
            deadline=timezone.now() + timedelta(days=20),
        )
        step = ApplicationStep.objects.create(
            tenant=agency, application=application, sequence=1, kind="SUBMITTED"
        )
        ApplicationStep.objects.filter(pk=step.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )
        return application


def test_an_overdue_confirmation_raises_one_urgent_alert(agency_a, membership_a, portal_form):
    application = _submitted(agency_a, membership_a, portal_form, hours_ago=49)

    assert watch_applications_for_tenant(agency_a.id) == 1

    with tenant_scope(agency_a.id):
        note = Notification.objects.get(recipient=membership_a)
        expectation = Expectation.objects.get(application=application)
    assert note.urgent is True
    assert "portal.example.test" in note.message
    assert expectation.alerted_id == note.id


def test_a_second_sweep_does_not_alert_again(agency_a, membership_a, portal_form):
    _submitted(agency_a, membership_a, portal_form, hours_ago=49)
    watch_applications_for_tenant(agency_a.id)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


def test_a_recent_submission_is_expected_but_not_alerted(agency_a, membership_a, portal_form):
    application = _submitted(agency_a, membership_a, portal_form, hours_ago=5)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        expectation = Expectation.objects.get(application=application)
        assert Notification.objects.filter(recipient=membership_a).count() == 0
    step_time = timezone.now() - timedelta(hours=5)
    assert abs(expectation.due_at - (step_time + timedelta(hours=48))) < timedelta(minutes=1)


def test_a_confirmed_application_is_left_alone(agency_a, membership_a, portal_form):
    _submitted(agency_a, membership_a, portal_form, hours_ago=100, state="CONFIRMED")

    assert watch_applications_for_tenant(agency_a.id) == 0


def test_quiet_hours_defer_the_alert_and_never_skip_it(agency_a, membership_a, portal_form):
    """Owner decision 2026-09-19: quiet hours hold without exception."""
    _submitted(agency_a, membership_a, portal_form, hours_ago=49)
    now = timezone.now()
    with tenant_scope(agency_a.id):
        # A window around `now`, so the test holds at any hour it runs.
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = (now - timedelta(hours=1)).time()
        membership_a.quiet_hours_end = (now + timedelta(hours=1)).time()
        membership_a.save(update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"])

    assert watch_applications_for_tenant(agency_a.id, now=now) == 0

    with tenant_scope(agency_a.id):
        membership_a.quiet_hours_start = None
        membership_a.quiet_hours_end = None
        membership_a.save(update_fields=["quiet_hours_start", "quiet_hours_end"])
    assert watch_applications_for_tenant(agency_a.id, now=now) == 1


def test_another_tenant_is_not_touched(agency_a, membership_a, agency_b, membership_b, portal_form):
    _submitted(agency_b, membership_b, portal_form, hours_ago=49)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_b.id):
        assert Notification.objects.filter(recipient=membership_b).count() == 0


def test_a_student_being_erased_gets_no_alert(agency_a, membership_a, portal_form):
    """An open DeletionRequest locks the dashboard the alert points at."""
    from apps.audit.models import DeletionRequest

    _submitted(agency_a, membership_a, portal_form, hours_ago=49)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a)

    assert watch_applications_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 0


def test_an_application_confirmed_after_listing_is_not_watched(
    agency_a, membership_a, portal_form
):
    """The listing ran in an earlier transaction; the per-application read must
    not trust it."""
    from apps.tenancy.db import tenant_transaction
    from apps.watch.watchdog import _watch_one

    application = _submitted(
        agency_a, membership_a, portal_form, hours_ago=49, state="CONFIRMED"
    )

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert _watch_one(application.id, timezone.now()) is False
        assert not Expectation.objects.filter(application=application).exists()


def test_an_alerted_application_is_not_revisited(agency_a, membership_a, portal_form):
    from unittest import mock

    from apps.watch import watchdog

    _submitted(agency_a, membership_a, portal_form, hours_ago=49)
    watch_applications_for_tenant(agency_a.id)

    with mock.patch.object(watchdog, "_watch_one", wraps=watchdog._watch_one) as visited:
        watch_applications_for_tenant(agency_a.id)
    assert visited.call_count == 0
