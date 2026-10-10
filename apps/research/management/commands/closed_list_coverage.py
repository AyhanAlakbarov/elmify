"""The coverage line per closed list, and the build-item-7 gate (spec 16).

Records every entry's read state first (read_state.record_read_states), then
prints: listed / printed, bodies known, the state histogram, STALE, PASS|FAIL.
`--gate` turns a FAIL into a non-zero exit, so the gate is a command's exit
code and not a paragraph someone reads.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.models import ClosedList
from apps.research.read_state import list_gate


class Command(BaseCommand):
    help = "Record read states and print each closed list's coverage line." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--list", action="append", default=[], dest="slugs")
        parser.add_argument("--gate", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        slugs = options["slugs"] or list(
            ClosedList.objects.order_by("slug").values_list("slug", flat=True)
        )
        failed: list[str] = []
        for slug in slugs:
            gate = list_gate(slug, now=now)
            printed = "?" if gate.printed_size is None else str(gate.printed_size)
            states = " ".join(f"{key}={value}" for key, value in sorted(gate.states.items()))
            verdict = "PASS" if gate.passed else "FAIL"
            stale = " STALE" if gate.stale else ""
            self.stdout.write(
                f"{slug}  listed {gate.listed}/{printed}  known {gate.bodies_known}  "
                f"{states}{stale}  {verdict}"
            )
            if not gate.passed:
                failed.append(slug)
        if options["gate"] and failed:
            raise CommandError(f"gate failed: {', '.join(failed)}")
