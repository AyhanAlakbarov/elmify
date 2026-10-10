"""One-off: file an AWARD_DISPUTED item for every reader row written before the queue.

    uv run python manage.py file_award_disputes

Walks the rows the old `funding_review` listed (`kind` I*, unserved,
unreviewed) and files each one the reader would file today
(`writers.award_needs_a_person`), bound to the page version its latest quote
came from. ABSTAINED, WITHDRAWN and suspended rows are skipped, as the reader
skips them. Idempotent: `file_item` keeps one item per subject.

Reads the catalogue and inserts into the queue, so it runs as `runtime_engine`
or the owner -- the same role check as `apply_resolutions`.
Plan: docs/superpowers/plans/2026-09-25-human-resolution-queue.md, Task 8.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.funding.models import FundingOpportunity, OfficialSourceSnapshot
from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.management.commands.apply_resolutions import can_write_catalogue
from apps.research.resolution.writers import award_needs_a_person, file_award_dispute


def _latest_snapshot(row: FundingOpportunity) -> OfficialSourceSnapshot | None:
    return (
        OfficialSourceSnapshot.objects.filter(
            id__in=row.evidence_claims.exclude(snapshot=None).values("snapshot_id")
        )
        .select_related("source")
        .order_by("-retrieved_at")
        .first()
    )


class Command(BaseCommand):
    help = "File AWARD_DISPUTED items for unserved reader rows written before the queue existed."

    def handle(self, *_args: object, **_options: object) -> None:
        if not can_write_catalogue():
            raise CommandError(
                "file_award_disputes reads the catalogue and files queue items, and this "
                "connection's role cannot." + CATALOG_ROLE_NOTE
            )
        filed = skipped = 0
        rows = FundingOpportunity.objects.filter(
            kind__startswith="I", served=False, review=""
        ).order_by("canonical_key")
        for row in rows.iterator():
            snapshot = _latest_snapshot(row) if award_needs_a_person(row) else None
            with transaction.atomic():
                item = file_award_dispute(row, snapshot) if snapshot is not None else None
            if item is None:
                skipped += 1
            else:
                filed += 1
        self.stdout.write(f"filed={filed} skipped={skipped}")
