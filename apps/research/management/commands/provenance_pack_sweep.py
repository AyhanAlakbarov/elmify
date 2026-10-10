"""Carry provenance verdict changes into published packs, and re-run students
whose pending checks resolved (spec §7.1, §7.3). Run after provenance_check.

Reads the verdict catalogue: run in the worker (DATABASE_ROLE=runtime_engine),
never on the web tier. Exits non-zero when any student, run or enqueue failed,
after printing the report, so a scheduled run that failed is not a clean one.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.provenance_sweep import sweep


class Command(BaseCommand):
    help = (
        "Carry provenance verdict changes into published packs (spec §7.3). "
        "Worker only: run with DATABASE_ROLE=runtime_engine."
    )

    def handle(self, *args: Any, **options: Any) -> None:
        report = sweep(now=timezone.now())
        self.stdout.write(
            f"packs revised {report.revised}, removed {report.removed}, kept with a note "
            f"{report.kept}, re-runs {report.reruns}, pending cleared {report.cleared}, "
            f"named checks queued {report.named}, bodies queued {report.checks}"
        )
        if report.errors:
            raise CommandError(f"{report.errors} failure(s); see the log")
