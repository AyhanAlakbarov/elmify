from datetime import timedelta

import pytest
from django.utils import timezone

from apps.concierge.models import Notification
from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope
from apps.watch.heartbeat import record_run
from apps.watch.mailbox_health import alert_stale_mailboxes_for_tenant

pytestmark = pytest.mark.django_db


def _connection(agency, student, *, synced_hours_ago):
    with tenant_scope(agency.id):
        connection = MailboxConnection.objects.create(
            tenant=agency,
            membership=student,
            provider=MailboxConnection.Provider.MICROSOFT,
            address="leyla@outlook.test",
        )
        MailboxConnection.objects.filter(pk=connection.pk).update(
            last_sync_at=timezone.now() - timedelta(hours=synced_hours_ago)
        )
    return connection


def test_a_stale_inbox_raises_one_urgent_alert(agency_a, membership_a):
    record_run("sync_mailboxes")
    _connection(agency_a, membership_a, synced_hours_ago=7)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 1
    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a, urgent=True).count() == 1


def test_a_fresh_inbox_is_left_alone(agency_a, membership_a):
    record_run("sync_mailboxes")
    _connection(agency_a, membership_a, synced_hours_ago=1)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0


def test_no_alerts_while_the_sweep_itself_is_not_running(agency_a, membership_a):
    """Then every inbox is stale; the job-silence alarm owns that, not each student."""
    _connection(agency_a, membership_a, synced_hours_ago=7)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0


def test_a_student_being_erased_gets_no_alert(agency_a, membership_a):
    """An open DeletionRequest locks the dashboard the alert points at."""
    from apps.audit.models import DeletionRequest

    record_run("sync_mailboxes")
    _connection(agency_a, membership_a, synced_hours_ago=7)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a)

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 0


def test_an_error_connection_is_not_double_alerted(agency_a, membership_a):
    """Fix round 1, finding 1 (controller ruling): a connection that flipped to
    ERROR is already announced urgently by apps.mailbox.sync.announce_lost_grant
    at the moment of the flip. Widening this query to ERROR would raise a
    second alert for the same outage, so ERROR (like REVOKED) stays excluded --
    only ACTIVE connections are considered stale here."""
    record_run("sync_mailboxes")
    connection = _connection(agency_a, membership_a, synced_hours_ago=7)
    with tenant_scope(agency_a.id):
        MailboxConnection.objects.filter(pk=connection.pk).update(
            status=MailboxConnection.Status.ERROR
        )

    assert alert_stale_mailboxes_for_tenant(agency_a.id) == 0


def test_the_alert_message_is_neutral_across_connection_kinds(agency_a, membership_a):
    """Fix round 1, finding 4: MailboxConnection.kind defaults to EVERYDAY, so
    the message must not claim it is "your application inbox" for every
    connection -- and it must never name an address or a subject."""
    record_run("sync_mailboxes")
    _connection(agency_a, membership_a, synced_hours_ago=7)

    alert_stale_mailboxes_for_tenant(agency_a.id)

    with tenant_scope(agency_a.id):
        message = Notification.objects.get().message
    assert "application" not in message
    assert "@" not in message


def test_a_connection_already_claimed_is_not_alerted_again_in_the_same_pass(
    agency_a, membership_a
):
    """Fix round 1, finding 3: two overlapping watch_applications runs must not
    both alert one outage. The claim is a compare-and-swap update, not a
    check-then-act read -- proved directly here rather than by racing threads:
    a second claim of the same row, at the same moment, updates zero rows."""
    from apps.watch.mailbox_health import _claim

    connection = _connection(agency_a, membership_a, synced_hours_ago=7)
    moment = timezone.now()
    with tenant_scope(agency_a.id):
        assert _claim(connection, moment) is True
        assert _claim(connection, moment) is False
