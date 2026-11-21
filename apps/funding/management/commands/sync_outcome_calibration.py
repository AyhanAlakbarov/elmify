"""Management command to sync decided application outcomes into `OutcomeCalibrationRecord`."""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from apps.funding.probability import sync_outcome_calibration_records


class Command(BaseCommand):
    help = "Sync decided application and scholarship outcomes into OutcomeCalibrationRecord."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--tenant-id",
            type=UUID,
            default=None,
            help="Optional agency tenant UUID to restrict the sync to.",
        )

    def handle(self, *args: object, **options: object) -> None:
        tenant_id = options.get("tenant_id")
        tid = tenant_id if isinstance(tenant_id, UUID) else None
        count = sync_outcome_calibration_records(tenant_id=tid)
        self.stdout.write(f"Synced {count} outcome calibration records.")
