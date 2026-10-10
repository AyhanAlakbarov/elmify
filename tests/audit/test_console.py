"""The lifecycle a human drives. advance_deletion holds the mechanics."""

import pytest
from django.utils import timezone

from apps.audit.console import request_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _policy(agency):
    RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())


def test_an_ordinary_request_reaches_approved_with_a_date(agency_a, membership_a):
    """The one-click flow: nothing in flight, nothing held, clock running."""
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(
            student=membership_a, reason=DeletionRequest.Reason.SWITCHING_AGENCY
        )

    assert request.state == "APPROVED"
    assert request.execute_after is not None
    assert request.review_reason == ""
    assert request.reason == "SWITCHING_AGENCY"


@pytest.mark.parametrize("in_flight", ["SUBMITTED", "CONFIRMED"])
def test_an_application_in_flight_diverts_to_review(agency_a, membership_a, in_flight):
    """A student with work at a university does not get the one-click path.

    Thirty days later ApplicationStep.detail and every document are redacted,
    and the agency can no longer act on the application, contact the applicant
    or answer a request for documents. The student is told, and a human
    decides.
    """
    from apps.portals.models import Application, PortalForm

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        form = PortalForm.objects.create(portal_host="tum.de", form_key="msc")
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=membership_a.id,
            portal_form=form,
            state=in_flight,
        )
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)

    assert request.state == "RETENTION_REVIEW"
    assert request.review_reason == "APPLICATIONS_IN_FLIGHT"
    assert request.execute_after is None, "a held request waits on a human, not a clock"


def test_a_finished_application_does_not_divert(agency_a, membership_a):
    """PREPARING is not in flight -- nothing has been sent anywhere."""
    from apps.portals.models import Application, PortalForm

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        form = PortalForm.objects.create(portal_host="tum.de", form_key="msc")
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=membership_a.id,
            portal_form=form,
            state="PREPARING",
        )
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.OTHER)

    assert request.state == "APPROVED"


def test_a_legal_hold_diverts_to_review(agency_a, membership_a):
    """advance_deletion raises DeletionBlocked; the service records why."""
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(
            student=membership_a,
            reason=DeletionRequest.Reason.PRIVACY,
            _legal_hold_for_test=True,
        )

    assert request.state == "RETENTION_REVIEW"
    assert request.review_reason == "LEGAL_HOLD"


def test_a_missing_retention_policy_diverts_to_review(agency_a, membership_a):
    """No policy row is an agency configuration gap, not a student problem."""
    with tenant_scope(agency_a.id):
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)

    assert request.state == "RETENTION_REVIEW"
    assert request.review_reason == "NO_RETENTION_POLICY"


def test_the_request_is_audited_even_when_it_is_diverted(agency_a, membership_a):
    """deletion.requested is written before the walk, so a held request still
    records that the student asked. Without that, a diverted request looks like
    something the agency invented.
    """
    with tenant_scope(agency_a.id):
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)
        events = list(AuditEvent.objects.filter(object_id=request.id))

    assert [e.event for e in events] == ["deletion.requested"]
    assert events[0].actor_id == membership_a.id
    assert events[0].actor_kind == "HUMAN"


def test_a_student_can_cancel_their_own_request(agency_a, membership_a):
    from apps.audit.console import cancel_deletion

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.OTHER)
        cancelled = cancel_deletion(request=request, student=membership_a)

    assert cancelled.state == "CANCELLED"


def test_cancelling_is_audited_against_the_student(agency_a, membership_a):
    from apps.audit.console import cancel_deletion

    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.OTHER)
        cancel_deletion(request=request, student=membership_a)
        events = [e.event for e in AuditEvent.objects.filter(object_id=request.id)]

    assert events == ["deletion.requested", "deletion.cancelled"]


def test_an_executed_request_cannot_be_cancelled(agency_a, membership_a):
    """Nothing left to restore. advance_deletion's table already says so; this
    pins that the service does not route around it.
    """
    from apps.audit.console import cancel_deletion
    from apps.audit.deletion import DeletionBlocked

    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="EXECUTED"
        )
        with pytest.raises(DeletionBlocked):
            cancel_deletion(request=request, student=membership_a)


def _connection(agency, student, status="ACTIVE"):
    from apps.mailbox.models import MailboxConnection

    return MailboxConnection.objects.create(
        tenant=agency,
        membership=student,
        provider=MailboxConnection.Provider.GOOGLE,
        address="leyla@example.com",
        status=status,
    )


@pytest.mark.parametrize("status", ["ACTIVE", "ERROR"])
def test_requesting_deletion_revokes_the_mailbox_and_destroys_its_token(
    agency_a, membership_a, monkeypatch, status
):
    """Immediately, not thirty days later.

    The sync reads MailboxConnection.status, which redaction keeps, so a live
    row would keep reading an erasing student's mail for the whole window.
    ERROR too: a degraded connection still has a live refresh token.
    """
    from apps.audit import console

    destroyed = []
    monkeypatch.setattr(
        console, "delete_student_mailbox_tokens", lambda **kwargs: destroyed.append(kwargs) or 1
    )
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        connection = _connection(agency_a, membership_a, status)
        request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)
        connection.refresh_from_db()

    assert connection.status == "REVOKED"
    assert connection.revoked_at is not None
    assert destroyed == [{"tenant_id": agency_a.id, "student_id": membership_a.id}]


def test_a_student_with_no_mailbox_asks_secrets_manager_nothing(
    agency_a, membership_a, monkeypatch
):
    """Positive control for the test above: most students never connect one."""
    from apps.audit import console

    monkeypatch.setattr(
        console,
        "delete_student_mailbox_tokens",
        lambda **kwargs: pytest.fail("no connection, so no token to destroy"),
    )
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)

    assert request.state == "APPROVED"


def test_a_refused_destroy_does_not_stop_the_student_filing_the_request(
    agency_a, membership_a, monkeypatch
):
    """Here the destroy only ends the grant early; at EXECUTED it is the erasure."""
    from apps.audit import console

    def _refuse(**kwargs):
        raise RuntimeError("AccessDenied")

    monkeypatch.setattr(console, "delete_student_mailbox_tokens", _refuse)
    with tenant_scope(agency_a.id):
        _policy(agency_a)
        connection = _connection(agency_a, membership_a)
        request = request_deletion(student=membership_a, reason=DeletionRequest.Reason.PRIVACY)
        connection.refresh_from_db()
        stored = DeletionRequest.objects.get(pk=request.pk)

    assert stored.state == "APPROVED"
    assert connection.status == "REVOKED"
