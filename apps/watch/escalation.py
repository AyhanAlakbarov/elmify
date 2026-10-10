"""An urgent alert counts once a person acknowledges it; until then it climbs.

Level 1 emails the student at the address they sign in to us with (User.email),
not application_email -- that may be the application inbox they rarely open
(spec §4). Level 2 asks the assigned counsellor to reach them on WhatsApp, the
channel the reminder-ladder design found this cohort actually reads.

Design: docs/superpowers/specs/2026-09-25-application-watch-design.md §4.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application
from apps.portals.reminders import held_for_quiet_hours
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment

from .models import Expectation
from .rules import escalation_target
from .watchdog import being_erased

logger = logging.getLogger(__name__)

_TOP_LEVEL = 2


def _pending() -> QuerySet[Notification]:
    """Urgent alerts still owed a climb.

    Not one whose question is already answered (the application it asked about
    has left SUBMITTED); not one to a student being erased, open or executed --
    an EXECUTED erasure sets Membership.active=False but leaves this
    Notification and any CounselorAssignment standing
    (apps/audit/deletion.py::advance_deletion), so `recipient__active` must be
    checked as well as the open-DeletionRequest lock (the watchdog already
    filters `student__active=True` for the same reason).
    """
    return Notification.objects.filter(
        urgent=True,
        acknowledged_at__isnull=True,
        escalation_level__lt=_TOP_LEVEL,
        recipient__active=True,
    ).exclude(
        Exists(
            Expectation.objects.filter(alerted=OuterRef("pk")).exclude(
                application__state=Application.State.SUBMITTED
            )
        )
    ).exclude(being_erased("recipient"))


def escalate_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    moment = now or timezone.now()
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            pending = list(_pending().values_list("id", flat=True))
        raised = 0
        for notification_id in pending:
            try:
                with tenant_transaction(tenant_id):
                    if _escalate_one(notification_id, moment):
                        raised += 1
            except Exception:
                logger.exception("EscalationFailed notification=%s", notification_id)
        return raised


def _escalate_one(notification_id: UUID, moment: datetime) -> bool:
    # Locked, and the whole pending predicate re-checked: two overlapping sweeps
    # must not both send level 1, and an acknowledgement, confirmation or
    # deletion request since the listing ends the climb.
    note = (
        _pending()
        .select_for_update()
        .select_related("recipient__user", "roadmap_item")
        .filter(id=notification_id)
        .first()
    )
    if note is None:
        return False
    target = escalation_target(note.created_at, moment, note.roadmap_item.deadline)
    if target <= note.escalation_level:
        return False
    if held_for_quiet_hours(note.recipient, moment):
        return False
    for level in range(note.escalation_level + 1, target + 1):
        if level == 1:
            _email_student(note)
        elif level == 2:
            _tell_counselor(note)
    # Sent before this save commits: a transaction failure here re-sends next
    # sweep. Accepted, the same shape as apps/portals/reminders._remind_one.
    note.escalation_level = target
    note.save(update_fields=["escalation_level"])
    return True


def _email_student(note: Notification) -> None:
    if not settings.REMINDER_EMAIL_FROM:
        logger.info("EscalationEmailSkipped reason=unconfigured notification=%s", note.id)
        return
    address = note.recipient.user.email
    if not address:
        logger.info("EscalationEmailSkipped reason=no_address notification=%s", note.id)
        return
    try:
        send_mail(
            subject="Action needed on your applications",
            message=f"{note.message}\n\nOpen your dashboard to see it and mark it done.",
            from_email=settings.REMINDER_EMAIL_FROM,
            recipient_list=[address],
        )
    except Exception as error:
        # Undeliverable falls through to the next channel (spec §5), so the
        # level still rises. Type only: SMTP and SES messages carry the address.
        logger.warning(
            "EscalationEmailFailed notification=%s error=%s", note.id, type(error).__name__
        )


def _tell_counselor(note: Notification) -> None:
    assignment = (
        CounselorAssignment.objects.filter(student=note.recipient, active=True)
        .select_related("counselor")
        .first()
    )
    if assignment is None:
        # Direct-to-student account: nobody else to tell (spec, open decision 1).
        logger.info("EscalationEnds reason=no_counselor notification=%s", note.id)
        return
    Notification.objects.create(
        tenant=note.tenant,
        recipient=assignment.counselor,
        roadmap_item=note.roadmap_item,
        message=(
            f"Unanswered by your student: {note.message} "
            "Message this student on WhatsApp now."
        ),
    )
