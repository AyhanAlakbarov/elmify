"""Manual-operation, notification, and messaging helpers for the concierge app.

Every action in this module is a human-recorded fact (a counselor manually
filed a form, acknowledged a task, sent a message) — never an automated call
into a payment processor or a portal. See tests/concierge/test_roadmap.py's
test_no_payment_or_portal_automation_call.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.tenancy.models import Membership

from .models import ConversationMessage, ManualOperation, Notification, RoadmapItem


@transaction.atomic
def record_manual_operation(
    roadmap_item: RoadmapItem, actor: Membership, description: str
) -> ManualOperation:
    """Record that a consultant manually performed a step, closing out the item."""
    if roadmap_item.state == RoadmapItem.State.DONE:
        raise ValueError("roadmap item is already done")
    operation = ManualOperation.objects.create(
        tenant=roadmap_item.tenant,
        roadmap_item=roadmap_item,
        actor=actor,
        description=description,
    )
    roadmap_item.state = RoadmapItem.State.DONE
    roadmap_item.save(update_fields=["state"])
    return operation


def acknowledge_notification(notification: Notification) -> Notification:
    notification.acknowledged_at = timezone.now()
    notification.save(update_fields=["acknowledged_at"])
    return notification


def send_message(
    *, student: Membership, counselor: Membership, sender: Membership, body: str
) -> ConversationMessage:
    if sender.id not in (student.id, counselor.id):
        raise ValueError("sender must be the student or the assigned counselor")
    return ConversationMessage.objects.create(
        tenant=sender.tenant,
        student=student,
        counselor=counselor,
        sender=sender,
        body=body,
    )


#: The one cap on a message body. The counselor's send (dashboard Task 20) uses
#: clean_message_body too, so the rule is written once.
MESSAGE_MAX_LENGTH = 4000


class MessageBodyError(ValueError):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def clean_message_body(raw: str) -> str:
    """The stripped body, or MessageBodyError carrying the message and HTTP status."""
    body = raw.strip()
    if not body:
        raise MessageBodyError("A message is required.", 403)
    if len(body) > MESSAGE_MAX_LENGTH:
        raise MessageBodyError(
            f"Messages must be {MESSAGE_MAX_LENGTH} characters or fewer.", 400
        )
    return body
