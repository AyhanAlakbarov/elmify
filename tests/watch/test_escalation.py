from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.concierge.services import acknowledge_notification
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from apps.watch.escalation import escalate_for_tenant

pytestmark = pytest.mark.django_db


def _alert(agency, student, *, hours_ago, urgent=True, deadline_in=timedelta(days=30)):
    with tenant_scope(agency.id):
        item = RoadmapItem.objects.create(
            tenant=agency,
            student=student,
            stage=RoadmapItem.Stage.MONITORING,
            owner=student,
            deadline=timezone.now() + deadline_in,
        )
        note = Notification.objects.create(
            tenant=agency, recipient=student, roadmap_item=item, message="TUM: act", urgent=urgent
        )
        Notification.objects.filter(pk=note.pk).update(
            created_at=timezone.now() - timedelta(hours=hours_ago)
        )
        note.refresh_from_db()
        return note


@pytest.fixture
def with_email(settings, user_a):
    settings.REMINDER_EMAIL_FROM = "alerts@example.test"
    user_a.email = "leyla@example.test"
    user_a.save(update_fields=["email"])


@pytest.fixture
def counselled(agency_a, membership_a, counselor_membership):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    return counselor_membership


def test_after_12h_the_student_is_emailed_at_the_address_they_sign_in_with(
    agency_a, membership_a, with_email
):
    note = _alert(agency_a, membership_a, hours_ago=13)

    assert escalate_for_tenant(agency_a.id) == 1

    note.refresh_from_db()
    assert note.escalation_level == 1
    assert [m.to for m in mail.outbox] == [["leyla@example.test"]]


def test_after_24h_the_counsellor_is_told_too(
    agency_a, membership_a, counselled, with_email
):
    _alert(agency_a, membership_a, hours_ago=25)

    escalate_for_tenant(agency_a.id)

    with tenant_scope(agency_a.id):
        told = Notification.objects.filter(recipient=counselled)
        assert told.count() == 1
        assert "WhatsApp" in told.get().message
    assert len(mail.outbox) == 1


def test_an_acknowledged_alert_never_escalates(agency_a, membership_a, with_email):
    note = _alert(agency_a, membership_a, hours_ago=25)
    with tenant_scope(agency_a.id):
        acknowledge_notification(note)

    assert escalate_for_tenant(agency_a.id) == 0
    assert mail.outbox == []


def test_a_non_urgent_notification_is_never_escalated(agency_a, membership_a, with_email):
    _alert(agency_a, membership_a, hours_ago=100, urgent=False)

    assert escalate_for_tenant(agency_a.id) == 0


def test_each_level_happens_once(agency_a, membership_a, counselled, with_email):
    _alert(agency_a, membership_a, hours_ago=25)
    escalate_for_tenant(agency_a.id)

    assert escalate_for_tenant(agency_a.id) == 0
    assert len(mail.outbox) == 1
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselled).count() == 1


def test_near_a_deadline_the_ladder_is_fast(agency_a, membership_a, with_email):
    note = _alert(agency_a, membership_a, hours_ago=3, deadline_in=timedelta(hours=30))

    escalate_for_tenant(agency_a.id)

    note.refresh_from_db()
    assert note.escalation_level == 1


def test_no_counsellor_records_the_level_and_tells_no_one_else(
    agency_a, membership_a, with_email, caplog
):
    """Direct-to-student accounts: the chain ends at the student (spec, open decision 1)."""
    note = _alert(agency_a, membership_a, hours_ago=25)

    with caplog.at_level("INFO"):
        escalate_for_tenant(agency_a.id)

    note.refresh_from_db()
    assert note.escalation_level == 2
    with tenant_scope(agency_a.id):
        assert Notification.objects.exclude(recipient=membership_a).count() == 0
    assert "EscalationEnds" in caplog.text


def test_dormant_email_still_advances_the_level(settings, agency_a, membership_a):
    """No sending domain yet: the level rises so the counsellor step is not held up."""
    settings.REMINDER_EMAIL_FROM = ""
    note = _alert(agency_a, membership_a, hours_ago=13)

    escalate_for_tenant(agency_a.id)

    note.refresh_from_db()
    assert note.escalation_level == 1
    assert mail.outbox == []


def test_quiet_hours_defer_escalation(agency_a, membership_a, with_email):
    note = _alert(agency_a, membership_a, hours_ago=13)
    now = timezone.now()
    with tenant_scope(agency_a.id):
        # A window around `now`, so the test holds at any hour it runs.
        membership_a.timezone = "UTC"
        membership_a.quiet_hours_start = (now - timedelta(hours=1)).time()
        membership_a.quiet_hours_end = (now + timedelta(hours=1)).time()
        membership_a.save(update_fields=["timezone", "quiet_hours_start", "quiet_hours_end"])

    assert escalate_for_tenant(agency_a.id, now=now) == 0
    note.refresh_from_db()
    assert note.escalation_level == 0


def _confirmation_alert(agency, student, *, hours_ago):
    """An urgent alert raised by the watchdog for a still-SUBMITTED application."""
    import uuid

    from apps.portals.models import Application, PortalForm
    from apps.watch.models import Expectation

    note = _alert(agency, student, hours_ago=hours_ago)
    form = PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")
    with tenant_scope(agency.id):
        application = Application.objects.create(
            tenant=agency,
            student=student,
            program_id=uuid.uuid4(),
            portal_form=form,
            state="SUBMITTED",
        )
        Expectation.objects.create(
            tenant=agency,
            application=application,
            kind=Expectation.Kind.CONFIRMATION,
            due_at=timezone.now(),
            alerted=note,
        )
    return note, application


def test_an_alert_whose_application_is_confirmed_stops_climbing(
    agency_a, membership_a, counselled, with_email
):
    """The confirmation arrived after the alert: nobody should be chased for it."""
    note, application = _confirmation_alert(agency_a, membership_a, hours_ago=25)
    with tenant_scope(agency_a.id):
        application.state = "CONFIRMED"
        application.save(update_fields=["state"])

    assert escalate_for_tenant(agency_a.id) == 0

    note.refresh_from_db()
    assert note.escalation_level == 0
    assert mail.outbox == []
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselled).count() == 0


def test_an_alert_whose_application_is_still_submitted_climbs(
    agency_a, membership_a, with_email
):
    _confirmation_alert(agency_a, membership_a, hours_ago=13)

    assert escalate_for_tenant(agency_a.id) == 1


def test_a_failed_email_still_reaches_the_counsellor_and_leaks_no_address(
    agency_a, membership_a, counselled, with_email, monkeypatch, caplog
):
    """Spec §5: an alert that cannot be delivered falls through to the next channel."""
    import smtplib

    def _refused(**_kwargs):
        raise smtplib.SMTPRecipientsRefused({"leyla@example.test": (550, b"no such user")})

    monkeypatch.setattr("apps.watch.escalation.send_mail", _refused)
    note = _alert(agency_a, membership_a, hours_ago=25)

    with caplog.at_level("INFO"):
        assert escalate_for_tenant(agency_a.id) == 1

    note.refresh_from_db()
    assert note.escalation_level == 2
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselled).count() == 1
    assert "EscalationEmailFailed" in caplog.text
    assert "SMTPRecipientsRefused" in caplog.text
    assert "leyla@example.test" not in caplog.text


def test_a_student_being_erased_is_not_chased(agency_a, membership_a, counselled, with_email):
    """Locked out by an open DeletionRequest, they cannot open the dashboard the
    email points at, and the counsellor must not be sent after them."""
    from apps.audit.models import DeletionRequest

    note = _alert(agency_a, membership_a, hours_ago=25)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a)

    assert escalate_for_tenant(agency_a.id) == 0

    note.refresh_from_db()
    assert note.escalation_level == 0
    assert mail.outbox == []


def test_a_student_whose_erasure_has_executed_is_not_chased(
    agency_a, membership_a, counselled, with_email
):
    """advance_deletion sets Membership.active=False at EXECUTED but leaves the
    Notification and CounselorAssignment rows standing (apps/audit/deletion.py).
    Erasure having finished must stop the climb the same as erasure being open."""
    note = _alert(agency_a, membership_a, hours_ago=25)
    with tenant_scope(agency_a.id):
        membership_a.active = False
        membership_a.save(update_fields=["active"])

    assert escalate_for_tenant(agency_a.id) == 0

    note.refresh_from_db()
    assert note.escalation_level == 0
    assert mail.outbox == []
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=counselled).count() == 0
