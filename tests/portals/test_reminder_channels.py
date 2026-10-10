import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application, PortalForm
from apps.portals.reminders import notify_counselor, notify_student, reminder_item
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            deadline=timezone.now() + timedelta(days=3),
            deadline_timezone="Europe/Berlin",
        )


def test_the_reminder_item_is_created_once_and_reused(agency_a, application):
    with tenant_scope(agency_a.id):
        first = reminder_item(application)
        second = reminder_item(application)

        assert first.id == second.id
        assert RoadmapItem.objects.filter(student=application.student).count() == 1
        application.refresh_from_db()
        assert application.reminder_item_id == first.id


def test_the_reminder_item_carries_the_portal_deadline(agency_a, application):
    with tenant_scope(agency_a.id):
        item = reminder_item(application)

    assert item.deadline == application.deadline
    assert item.stage == RoadmapItem.Stage.SUBMISSION


def test_the_student_is_told_how_long_is_left(agency_a, application):
    with tenant_scope(agency_a.id):
        item = reminder_item(application)
        note = notify_student(application, item, timedelta(days=3))

    assert note.recipient_id == application.student_id
    assert "3 days" in note.message
    assert "portal.example.test" in note.message


def test_the_counselor_is_asked_to_use_whatsapp(
    agency_a, application, counselor_membership
):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=application.student,
            active=True,
        )
        item = reminder_item(application)
        note = notify_counselor(application, item, timedelta(hours=6))

    assert note is not None
    assert note.recipient_id == counselor_membership.id
    assert "WhatsApp" in note.message
    assert note.roadmap_item_id == item.id


def test_a_student_with_no_counselor_gets_no_counselor_task(agency_a, application):
    """A direct-to-student account has nobody to hand the task to. Silence here
    is correct, and is stated in a test because it looks exactly like a bug."""
    with tenant_scope(agency_a.id):
        item = reminder_item(application)
        note = notify_counselor(application, item, timedelta(hours=6))

        assert note is None
        assert Notification.objects.filter(roadmap_item=item).count() == 0


def test_an_inactive_assignment_is_not_a_counselor(
    agency_a, application, counselor_membership
):
    """Same trap escalation.py records: the model keeps inactive rows, so
    dropping the filter routes a task to someone who left the agency."""
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=application.student,
            active=False,
        )
        item = reminder_item(application)

        assert notify_counselor(application, item, timedelta(hours=6)) is None
