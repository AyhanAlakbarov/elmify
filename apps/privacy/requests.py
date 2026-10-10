"""Privacy requests: their deadline, and the processing stop an objection or withdrawal causes.

Azerbaijan's Law on Personal Data Art. 7.2: processing stops immediately on an
objection; Art. 12.4: reply within 7 working days (memo section 2). Weekends are
skipped; public holidays are not modelled (# ponytail: add a holiday calendar if
a deadline is ever missed because of one).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.utils import timezone

from apps.documents.audit import record_event
from apps.privacy.models import PrivacyRequest
from apps.tenancy.models import Membership

STOPPING_KINDS = (PrivacyRequest.Kind.OBJECTION, PrivacyRequest.Kind.WITHDRAWAL)
#: A reasoned refusal, or the student asking to resume, ends the stop. `done` keeps
#: it: an honoured objection or withdrawal means processing stays stopped.
LIFTING_OUTCOMES = (PrivacyRequest.Outcome.DECLINED, PrivacyRequest.Outcome.RESUMED)
DUE_WORKING_DAYS = 7


#: Art. 12.4's working days are Azerbaijan's: a request at 02:00 Saturday in Baku is
#: still Friday in UTC, and counting in UTC would hand back an extra day.
BAKU = ZoneInfo("Asia/Baku")


def working_days_after(start: datetime, days: int) -> datetime:
    """`days` working days after an aware `start`, counted on the Baku calendar."""
    moment = timezone.localtime(start, BAKU)
    while days > 0:
        moment += timedelta(days=1)
        if moment.weekday() < 5:
            days -= 1
    return moment


def record(
    student: Membership, *, kind: str, channel: str, received_at: datetime
) -> PrivacyRequest:
    if kind not in PrivacyRequest.Kind.values:
        raise ValueError(f"unknown privacy request kind {kind!r}")
    if channel not in PrivacyRequest.Channel.values:
        raise ValueError(f"unknown privacy request channel {channel!r}")
    row = PrivacyRequest.objects.create(
        student=student,
        kind=kind,
        channel=channel,
        received_at=received_at,
        due_at=working_days_after(received_at, DUE_WORKING_DAYS),
    )
    record_event(actor=None, event=f"privacy.request.{kind}", object_id=row.id)
    return row


def stopping_requests() -> QuerySet[PrivacyRequest]:
    """Requests that stop processing for their student: the one predicate every guard uses."""
    return PrivacyRequest.objects.filter(kind__in=STOPPING_KINDS).exclude(
        outcome__in=LIFTING_OUTCOMES
    )


def processing_stopped(student: Membership) -> bool:
    if student.role != Membership.Role.STUDENT:
        return False
    return stopping_requests().filter(student=student).exists()
