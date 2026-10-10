import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.portals.models import Application, PortalForm
from apps.portals.reminders import email_student
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        membership_a.application_email = "student@example.test"
        membership_a.save(update_fields=["application_email"])
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            deadline=timezone.now() + timedelta(days=3),
        )


def test_nothing_is_sent_while_no_from_address_is_configured(settings, application):
    """Dormant is the shipped state: no company domain exists yet."""
    settings.REMINDER_EMAIL_FROM = ""

    assert email_student(application, timedelta(days=3)) is False
    assert mail.outbox == []


def test_a_configured_sender_reaches_the_application_address(settings, application):
    settings.REMINDER_EMAIL_FROM = "reminders@tehsil.example"

    assert email_student(application, timedelta(days=3)) is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["student@example.test"]
    assert mail.outbox[0].from_email == "reminders@tehsil.example"
    assert "3 days" in mail.outbox[0].body


def test_a_student_with_no_confirmed_address_is_skipped(
    settings, agency_a, application
):
    """No fallback to user.email -- that address is signup and login only, and
    Membership.application_email's own docstring says so."""
    settings.REMINDER_EMAIL_FROM = "reminders@tehsil.example"
    with tenant_scope(agency_a.id):
        application.student.application_email = ""
        application.student.save(update_fields=["application_email"])

    assert email_student(application, timedelta(days=3)) is False
    assert mail.outbox == []
