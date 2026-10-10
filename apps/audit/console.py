"""The deletion lifecycle a human drives. apps/audit/deletion.py holds the mechanics.

advance_deletion is an engine: it validates transitions and performs the
erasure. What belongs here is the product policy around it -- who may ask, what
blocks a request, and what gets recorded when someone asks. Keeping the two
apart is why the engine has no notion of an application in flight.

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

import logging

from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.mailbox.models import MailboxConnection
from apps.mailbox.secrets import delete_student_mailbox_tokens
from apps.portals.models import Application
from apps.portals.pairing import revoke_all_for
from apps.tenancy.models import Membership

from .deletion import DeletionBlocked, advance_deletion
from .models import DeletionRequest

logger = logging.getLogger(__name__)

#: An application at either of these is sitting with an institution right now.
#: PREPARING and READY_TO_SUBMIT have been sent nowhere, and the BLOCKED_*
#: states are stalled rather than in flight.
IN_FLIGHT_STATES = (Application.State.SUBMITTED, Application.State.CONFIRMED)


def applications_in_flight(student: Membership) -> int:
    """How many of this student's applications are sitting with an institution."""
    return Application.objects.filter(student=student, state__in=IN_FLIGHT_STATES).count()


def request_deletion(
    *,
    student: Membership,
    reason: str,
    _legal_hold_for_test: bool = False,
) -> DeletionRequest:
    """Record a student's erasure request and start the clock, or divert it.

    Returns the request in APPROVED when nothing blocks -- the thirty-day
    window is then running and the scheduler will erase. Returns it in
    RETENTION_REVIEW with review_reason set when something does, which puts it
    on the owner screen for a human instead of on a clock.

    `_legal_hold_for_test` exists because nothing in this codebase writes
    DeletionRequest.legal_hold: it is set out of band, by whoever receives a
    preservation order. Tests need the diverted path reachable; production
    never passes it.
    """
    request = DeletionRequest.objects.create(
        tenant_id=student.tenant_id,
        student=student,
        state="REQUESTED",
        reason=reason,
        legal_hold=_legal_hold_for_test,
    )
    # Before the walk, so a request that is diverted still records that the
    # student asked. Without it a held request looks like something the agency
    # invented.
    AuditEvent.objects.create(
        tenant_id=student.tenant_id,
        actor=student,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.requested",
        object_id=request.id,
    )

    # Before the retention walk, and deliberately not waiting for EXECUTED: the
    # student is locked out of the dashboard from this moment, and a device
    # token that outlived that would keep returning fill packets carrying their
    # verified facts for the whole thirty-day window.
    revoke_all_for(student)

    # Same window, same reason. The sync reads MailboxConnection.status, which
    # redaction keeps, so without this write it keeps reading an erasing
    # student's inbox for all thirty days. Every non-REVOKED row, not just
    # ACTIVE: an ERROR row still has a live refresh token behind it.
    if (
        MailboxConnection.objects.filter(membership=student)
        .exclude(status=MailboxConnection.Status.REVOKED)
        .update(status=MailboxConnection.Status.REVOKED, revoked_at=timezone.now())
    ):
        try:
            delete_student_mailbox_tokens(tenant_id=student.tenant_id, student_id=student.id)
        except Exception as error:
            # Best effort here, loud at EXECUTED: there the destroy IS the
            # erasure, here it only ends the grant early. Letting it raise would
            # roll back the DeletionRequest, so a storage failure would stop a
            # student filing at all. The revoke above is what stops the sync.
            # The type only: botocore's message quotes the secret's name.
            logger.warning(
                "mailbox token destroy failed at deletion request for %s (%s); erasure will retry",
                student.id,
                type(error).__name__,
            )

    advance_deletion(request, "RETENTION_REVIEW")

    # Product policy, deliberately not in the engine. Neither existing guard
    # catches this: legal_hold is a manual flag nobody sets, and the
    # RetentionPolicy check only asserts a policy row exists.
    if applications_in_flight(student):
        return _hold(request, DeletionRequest.ReviewReason.APPLICATIONS_IN_FLIGHT)

    try:
        return advance_deletion(request, "APPROVED")
    except DeletionBlocked:
        # The engine refused. Which of its two guards fired decides what the
        # student is told and what the owner has to do about it.
        blocked_by = (
            DeletionRequest.ReviewReason.LEGAL_HOLD
            if request.legal_hold
            else DeletionRequest.ReviewReason.NO_RETENTION_POLICY
        )
        return _hold(request, blocked_by)


def _hold(request: DeletionRequest, review_reason: str) -> DeletionRequest:
    """Leave the request in RETENTION_REVIEW, saying why.

    execute_after stays NULL: a held request waits on a human, not a clock, and
    the scheduler's execute_after__lte filter must never match it.
    """
    request.review_reason = review_reason
    request.save(update_fields=["review_reason"])
    return request


def cancel_deletion(*, request: DeletionRequest, student: Membership) -> DeletionRequest:
    """Undo a request before it executes. Nothing was erased, so nothing is restored.

    The lock lifts because the middleware's query stops matching -- a property
    of having one source of truth rather than a feature that had to be built.

    Raises DeletionBlocked from EXECUTED, where there is nothing left to
    restore. The caller is responsible for checking that `request` belongs to
    `student`; this writes the audit row that says who did it.
    """
    cancelled = advance_deletion(request, "CANCELLED")
    AuditEvent.objects.create(
        tenant_id=student.tenant_id,
        actor=student,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.cancelled",
        object_id=request.id,
    )
    return cancelled


def release_deletion(*, request: DeletionRequest, owner: Membership) -> DeletionRequest:
    """An owner lets a held request proceed. The thirty-day clock starts now.

    review_reason is deliberately NOT cleared: it is the record of why the
    request was held, and this event says who released it. Clearing it would
    leave a released request indistinguishable from one that was never held.

    The caller checks that `request` belongs to the owner's tenant; this writes
    the audit row that says who acted.
    """
    released = advance_deletion(request, "APPROVED")
    AuditEvent.objects.create(
        tenant_id=owner.tenant_id,
        actor=owner,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.released",
        object_id=request.id,
    )
    return released


def deny_deletion(*, request: DeletionRequest, owner: Membership) -> DeletionRequest:
    """An owner refuses a held request. Nothing is erased and the student stays
    locked out until they restore it themselves -- DENIED is an open state for
    exactly that reason (see views.OPEN_DELETION_STATES).
    """
    denied = advance_deletion(request, "DENIED")
    AuditEvent.objects.create(
        tenant_id=owner.tenant_id,
        actor=owner,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="deletion.denied",
        object_id=request.id,
    )
    return denied
