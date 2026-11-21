"""Email alerts for the staff inbox, and the student's "you have a reply" mail.

Neither mail carries the message text: a message is read in the app, behind the login
(and, for staff, the two-step code), never in a mailbox. A failed send is logged and
never fails the request that triggered it: the message is already saved and shows in
the inbox either way.
"""

from __future__ import annotations

import logging
from uuid import UUID

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpRequest
from django.urls import reverse

from apps.concierge.models import ConversationMessage
from apps.tenancy.models import Membership

logger = logging.getLogger(__name__)


def _send(subject: str, body: str, recipients: list[str]) -> None:
    if not recipients:
        return
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
    except Exception:  # noqa: BLE001 -- mail is best effort; the message itself is saved
        logger.exception("StaffDeskMailFailed recipients=%d", len(recipients))


def staff_addresses(tenant_id: UUID) -> list[str]:
    return sorted(
        {
            email
            for email in Membership.objects.filter(
                tenant_id=tenant_id, role=Membership.Role.PLATFORM_ADMIN, active=True
            ).values_list("user__email", flat=True)
            if email
        }
    )


def alert_staff_of_message(request: HttpRequest, message: ConversationMessage) -> None:
    """Tell every Elmify staff member a student wrote to the team."""
    inbox = request.build_absolute_uri(reverse("staff-thread", args=[message.student_id]))
    recipients = staff_addresses(message.tenant_id)
    body = f"A student wrote to the Elmify team.\n\nRead and reply: {inbox}\n"
    transaction.on_commit(lambda: _send("New message from a student", body, recipients))


def alert_student_of_reply(request: HttpRequest, message: ConversationMessage) -> None:
    """Tell the student the team answered (no text in the mail)."""
    email = message.student.user.email
    if not email:
        return
    link = request.build_absolute_uri(reverse("student-messages"))
    body = f"The Elmify team replied to you.\n\nRead it in Elmify: {link}\n"
    transaction.on_commit(lambda: _send("Elmify replied to your message", body, [email]))
