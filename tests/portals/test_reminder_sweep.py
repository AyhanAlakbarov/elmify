import uuid
from datetime import time, timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, PortalForm, ReminderSent, Rung
from apps.portals.reminders import send_due_reminders_for_tenant
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _application(agency, student, portal_form, **overrides):
    fields = {
        "tenant": agency,
        "student": student,
        "program_id": uuid.uuid4(),
        "portal_form": portal_form,
        "deadline": timezone.now() + timedelta(days=3, hours=1),
    }
    fields.update(overrides)
    return Application.objects.create(**fields)


def test_a_due_application_is_reminded_once(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal_form)

    assert send_due_reminders_for_tenant(agency_a.id) == 1

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
        # D3 is NOT here: the fixture deadline is 3 days and 1 hour out, so the
        # 3-day rung has not opened yet. D14 and D7 both have, and both are
        # recorded even though only one message was sent.
        assert set(
            ReminderSent.objects.filter(application=application).values_list("rung", flat=True)
        ) == {Rung.D14, Rung.D7}


def test_two_rungs_due_at_once_mark_only_the_tighter_one_sent(
    agency_a, membership_a, portal_form
):
    """An application first seen 5 days before its deadline has both D14 and
    D7 due in the same sweep. Exactly one message goes out -- D7, the
    tighter rung -- and only its row is marked `sent`; D14's row exists only
    to stop it firing stale on a later sweep."""
    with tenant_scope(agency_a.id):
        application = _application(
            agency_a, membership_a, portal_form, deadline=timezone.now() + timedelta(days=5)
        )

    assert send_due_reminders_for_tenant(agency_a.id) == 1

    with tenant_scope(agency_a.id):
        rows = ReminderSent.objects.filter(application=application)
        assert {row.rung for row in rows} == {Rung.D14, Rung.D7}
        sent_rows = ReminderSent.objects.filter(application=application, sent=True)
        assert [row.rung for row in sent_rows] == [Rung.D7]
        superseded_rows = ReminderSent.objects.filter(application=application, sent=False)
        assert [row.rung for row in superseded_rows] == [Rung.D14]


def test_a_second_sweep_sends_nothing(agency_a, membership_a, portal_form):
    """The constraint, not a check: this is the test that fails if the sweep
    re-notifies every hour forever."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)

    send_due_reminders_for_tenant(agency_a.id)

    assert send_due_reminders_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


def test_a_later_rung_fires_on_a_later_sweep(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a, portal_form)

    send_due_reminders_for_tenant(agency_a.id)
    later = application.deadline - timedelta(hours=5)

    assert send_due_reminders_for_tenant(agency_a.id, now=later) == 1
    with tenant_scope(agency_a.id):
        assert ReminderSent.objects.filter(application=application, rung=Rung.H6).exists()
        assert Notification.objects.filter(recipient=membership_a).count() == 2


def _privacy_request(student, kind, outcome=""):
    from apps.privacy.models import PrivacyRequest

    now = timezone.now()
    return PrivacyRequest.objects.create(
        tenant_id=student.tenant_id,
        student=student,
        kind=kind,
        channel="email",
        received_at=now,
        due_at=now + timedelta(days=9),
        outcome=outcome,
    )


def test_a_student_with_an_open_objection_gets_no_reminder(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)
        _privacy_request(membership_a, "objection")

    assert send_due_reminders_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert not Notification.objects.filter(recipient=membership_a).exists()


def test_declined_and_non_stopping_requests_do_not_silence_or_duplicate_reminders(
    agency_a, membership_a, portal_form
):
    """Two requests that do not stop processing, on a student with two
    applications: each application is reminded exactly once. A join through
    privacy_requests would repeat the rows, and the sweep would drop or double them."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)
        _application(agency_a, membership_a, portal_form)
        _privacy_request(membership_a, "objection", outcome="declined")
        _privacy_request(membership_a, "access")

    assert send_due_reminders_for_tenant(agency_a.id) == 2
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 2


def test_a_resumed_objection_no_longer_silences_reminders(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)
        _privacy_request(membership_a, "objection", outcome="resumed")

    assert send_due_reminders_for_tenant(agency_a.id) == 1


def test_an_application_with_no_deadline_is_not_swept(
    agency_a, membership_a, portal_form
):
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form, deadline=None)

    assert send_due_reminders_for_tenant(agency_a.id) == 0


@pytest.mark.parametrize(
    "state",
    [
        Application.State.SUBMITTED,
        Application.State.CONFIRMED,
        Application.State.BLOCKED_MISSING_FACT,
    ],
)
def test_a_finished_or_blocked_application_is_not_reminded(
    agency_a, membership_a, portal_form, state
):
    """Submitted and confirmed are done. A blocked one is already waiting on a
    human, so telling the student to hurry is noise aimed at someone who
    cannot act."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form, state=state)

    assert send_due_reminders_for_tenant(agency_a.id) == 0


def test_a_rung_due_inside_quiet_hours_is_held(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(
            update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"]
        )
        application = _application(agency_a, membership_a, portal_form)

    asleep = application.deadline.replace(hour=3, minute=0) - timedelta(days=1)

    assert send_due_reminders_for_tenant(agency_a.id, now=asleep) == 0
    with tenant_scope(agency_a.id):
        assert not ReminderSent.objects.filter(application=application).exists()


def test_a_held_rung_fires_once_the_window_ends(agency_a, membership_a, portal_form):
    """Deferral, not a skip. A test asserting only silence at 03:00 passes on a
    version that drops the reminder forever, which is the opposite of the
    feature."""
    with tenant_scope(agency_a.id):
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(
            update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"]
        )
        application = _application(agency_a, membership_a, portal_form)

    asleep = application.deadline.replace(hour=3, minute=0) - timedelta(days=1)
    awake = asleep.replace(hour=8)
    send_due_reminders_for_tenant(agency_a.id, now=asleep)

    assert send_due_reminders_for_tenant(agency_a.id, now=awake) == 1
    with tenant_scope(agency_a.id):
        assert ReminderSent.objects.filter(application=application).exists()


def test_a_student_with_no_zone_is_never_held(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        membership_a.quiet_hours_start = time(22, 0)
        membership_a.quiet_hours_end = time(7, 0)
        membership_a.save(update_fields=["quiet_hours_start", "quiet_hours_end"])
        application = _application(agency_a, membership_a, portal_form)

    asleep = application.deadline.replace(hour=3, minute=0) - timedelta(days=1)

    assert send_due_reminders_for_tenant(agency_a.id, now=asleep) == 1


def test_a_student_with_no_address_still_gets_the_dashboard_rung(
    settings, agency_a, membership_a, portal_form
):
    """Email declining must not take the notification down with it: the
    dashboard is the channel that always works."""
    from django.core import mail

    settings.REMINDER_EMAIL_FROM = "reminders@tehsil.example"
    with tenant_scope(agency_a.id):
        membership_a.application_email = ""
        membership_a.save(update_fields=["application_email"])
        _application(agency_a, membership_a, portal_form)

    assert send_due_reminders_for_tenant(agency_a.id) == 1
    assert mail.outbox == []
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


def test_a_deactivated_students_application_is_not_swept(agency_a, membership_a, portal_form):
    """A deactivated Membership is what advance_deletion sets during the
    30-day deletion-review window and forever after erasure. The sweep must
    not keep reminding an account CLAUDE.md already calls deactivated --
    mirroring pairing.py's authenticate_device, which filters the same way
    for the same reason."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)
        membership_a.active = False
        membership_a.save(update_fields=["active"])

    assert send_due_reminders_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.count() == 0


def test_the_counselor_is_only_asked_inside_a_day(
    agency_a, membership_a, portal_form, counselor_membership
):
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a,
            counselor=counselor_membership,
            student=membership_a,
            active=True,
        )
        application = _application(agency_a, membership_a, portal_form)

    send_due_reminders_for_tenant(agency_a.id)

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselor_membership).count() == 0

    send_due_reminders_for_tenant(
        agency_a.id, now=application.deadline - timedelta(hours=5)
    )

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselor_membership).count() == 1
