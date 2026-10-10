"""Resume transcript readings that are waiting or were lost (spec 2026-10-03 §4, §7.1).

Run every 15 minutes by TranscriptResumeRule (infra/template.yaml) on the document worker's task
definition -- the only one holding the Azure key. Picks up, per agency: DELAYED uploads now due,
pages written but never assembled into a reading, uploads stuck READING past the timeout (the
worker died mid-read: the dead-letter gap), and clean-scanned uploads never picked up (a lost
scan message). Each runs alone; one that raises is delayed, so it fails for good after
MAX_ATTEMPTS instead of being retried forever.
"""

import logging
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.documents.models import TranscriptUpload
from apps.documents.transcript_pages import delay, process_upload
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency

logger = logging.getLogger(__name__)

#: Per agency per run: a burst waits for the next run rather than growing one run without bound.
# ponytail: a run may still outlive the next (200 uploads x Azure + Jev can pass 15 minutes),
# and the overlap is safe: _claim's lease and the cycle lock keep two runs from reading or
# charging one upload twice; the worst case is a duplicate Jev call. Add a run lock if the
# overlap is ever measured to cost.
_BATCH = 200


class Command(BaseCommand):
    help = "Resume delayed, stuck and unassembled transcript readings"

    def handle(self, *args: object, **options: object) -> None:
        # Agency carries no RLS policy, so listing it works from the runtime role (the same
        # loop execute_due_erasures uses); every query below runs in that agency's own scope.
        for agency in Agency.objects.all():
            for upload_id in _due(agency.id):
                try:
                    process_upload(agency.id, upload_id)
                except Exception as error:  # one upload must not strand the batch
                    # The type only: the message can quote document text.
                    logger.warning(
                        "TranscriptResumeFailed upload=%s error=%s", upload_id, type(error).__name__
                    )
                    delay(agency.id, upload_id, reason=type(error).__name__)


def _due(tenant_id: UUID) -> list[UUID]:
    now = timezone.now()
    stuck = now - timedelta(minutes=settings.TRANSCRIPT_STUCK_AFTER_MINUTES)
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        return list(
            TranscriptUpload.objects.filter(
                Q(state="DELAYED", next_attempt_at__lte=now)
                | Q(state="READ", assembled=False, next_attempt_at__lte=now)
                | Q(
                    state="READ",
                    assembled=False,
                    next_attempt_at__isnull=True,
                    updated_at__lt=stuck,
                )
                | Q(state="READING", updated_at__lt=stuck)
                | Q(state="PENDING", document__state="AVAILABLE", updated_at__lt=stuck)
            )
            .order_by("updated_at")
            .values_list("id", flat=True)[:_BATCH]
        )
