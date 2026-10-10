"""A connected inbox nobody has checked for hours is a promise quietly broken.

Only while the sweep itself runs: if it has stopped, every inbox is stale and
the job-silence alarm (heartbeat.py) is the one to raise it, not each student.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import JobRun
from .watchdog import being_erased

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=6)
_SWEEP = "sync_mailboxes"
_SWEEP_WINDOW = timedelta(hours=2)


def _claim(connection: MailboxConnection, moment: datetime) -> bool:
    """Compare-and-swap: True only for the run that gets to alert this outage.

    Fix round 1, finding 3: two overlapping watch_applications runs can both
    select the same stale, not-yet-alerted connection. A plain check-then-act
    save would let both create a card; only the update that still finds
    health_alerted_at NULL moves it, the other updates zero rows and does
    nothing further.
    """
    return (
        MailboxConnection.objects.filter(pk=connection.pk, health_alerted_at__isnull=True).update(
            health_alerted_at=moment
        )
        == 1
    )


def alert_stale_mailboxes_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    moment = now or timezone.now()
    last_sweep = JobRun.objects.filter(name=_SWEEP).values_list("last_success_at", flat=True)
    if not last_sweep or moment - last_sweep[0] > _SWEEP_WINDOW:
        return 0
    raised = 0
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            stale = (
                MailboxConnection.objects.filter(
                    # Fix round 1, finding 1 (controller ruling): ERROR is
                    # already announced, urgently, at the moment of the flip
                    # (apps.mailbox.sync.announce_lost_grant) -- widening this
                    # to ERROR would raise a second alert for the same
                    # outage. REVOKED stays excluded too: a deliberate
                    # disconnect or a deletion request, not a broken promise.
                    status=MailboxConnection.Status.ACTIVE,
                    health_alerted_at__isnull=True,
                    membership__active=True,
                )
                .exclude(being_erased("membership"))
                .annotate(seen=Coalesce("last_sync_at", "connected_at"))
                .filter(seen__lt=moment - STALE_AFTER)
                .select_related("membership")
            )
            for connection in stale:
                if not _claim(connection, moment):
                    continue
                Notification.raise_card(
                    student=connection.membership,
                    recipient=connection.membership,
                    owner=connection.membership,
                    stage=RoadmapItem.Stage.PERSONAL_ACTION,
                    deadline=moment + timedelta(days=1),
                    urgent=True,
                    action=Notification.Action.RECONNECT,
                    message=(
                        # Fix round 1, finding 4: neutral across every
                        # MailboxConnection.Kind -- no address, no subject.
                        "We haven't been able to check your connected inbox for a while. "
                        "Open your dashboard and reconnect it."
                    ),
                )
                logger.info("MailboxStale connection=%s", connection.id)
                raised += 1
    return raised
