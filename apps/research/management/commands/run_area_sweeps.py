"""Run the queued bounded area sweeps, highest demand first (spec 10.5 step 5).

Operator-run, like `execute_due_erasures` before its schedule: corridor-scale
sweeps wait for the vendor plans. A scheduled rule is a follow-up. Writes the
catalogue, so run with DATABASE_ROLE=runtime_engine. The area pass is
profile-free: it never reads a student, a tap query or a pack.
"""

from __future__ import annotations

import logging
import os
from argparse import SUPPRESS
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from apps.research.angles import PASS_SHAPES
from apps.research.fetch import CATALOG_ROLE_NOTE, RUNTIME_ENGINE_WRITE_REFUSED
from apps.research.management.commands.apply_resolutions import can_write_catalogue
from apps.research.models import AreaSweep
from apps.research.tap_seams import bound_sweeper

#: Mirrors sweep_organisations' refusal; every PASS_SHAPES family is a funder sweep.
FUNDER_HELD = "funder level check not live (card reader slice 3)"
DIASPORA_NEEDS_HOME = "diaspora area needs a home language, which area rows do not carry"

logger = logging.getLogger(__name__)


def _finish(row: AreaSweep, state: str, reason: str, **fields: Any) -> None:
    AreaSweep.objects.filter(pk=row.pk).update(
        state=state, stop_reason=reason[:200], finished_at=timezone.now(), **fields
    )


class Command(BaseCommand):
    help = "Run the queued area sweeps, highest demand first, each budget-bounded."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=5)
        # Test seam: call_command rejects an option the parser does not declare.
        parser.add_argument("--sweeper", default=None, help=SUPPRESS)

    def handle(self, *args: Any, **options: Any) -> None:
        if not can_write_catalogue():
            raise CommandError(
                "run_area_sweeps writes the shared catalogue and this connection's role "
                "cannot." + CATALOG_ROLE_NOTE
            )
        sweeper = options.get("sweeper")
        if sweeper is None:
            if not (settings.EXA_API_KEY or settings.BRAVE_API_KEY):
                raise CommandError("no provider key is set: EXA_API_KEY, BRAVE_API_KEY")
            if not os.environ.get("OPENAI_API_KEY"):
                raise CommandError("OPENAI_API_KEY is unset: the sweep's classifier needs it")
            sweeper = bound_sweeper()
        queued = AreaSweep.objects.filter(state=AreaSweep.State.QUEUED)
        if not settings.FUNDER_SWEEP_LEVEL_CHECK_LIVE:
            # Queued demand survives until the switch is turned on.
            held = queued.filter(family__in=PASS_SHAPES).order_by("-demand")
            for row in held[: options["limit"]]:
                self.stdout.write(f"{row.country_code}/{row.family}: left QUEUED ({FUNDER_HELD})")
            return
        ids = list(
            queued.order_by("-demand", "requested_at").values_list("pk", flat=True)[
                : options["limit"]
            ]
        )
        for pk in ids:
            with transaction.atomic():
                row = AreaSweep.objects.select_for_update().get(pk=pk)
                if row.state != AreaSweep.State.QUEUED:
                    continue
                row.state = AreaSweep.State.RUNNING
                row.save(update_fields=["state"])
            area = f"{row.country_code}/{row.family}"
            if row.family == "AFFINITY_OR_DIASPORA":
                _finish(row, AreaSweep.State.UNAVAILABLE, DIASPORA_NEEDS_HOME)
                self.stdout.write(f"{area}: UNAVAILABLE ({DIASPORA_NEEDS_HOME})")
                continue
            try:
                outcome = sweeper.run(
                    row.country_code, row.family, budget_usd=settings.CELL_SWEEP_BUDGET_USD
                )
            except ProgrammingError as error:
                AreaSweep.objects.filter(pk=pk).update(state=AreaSweep.State.QUEUED)
                raise CommandError(RUNTIME_ENGINE_WRITE_REFUSED.format(error=error)) from error
            except Exception as error:  # one area's failure must not strand it RUNNING
                logger.exception("area sweep %s failed", area)
                reason = f"error: {type(error).__name__}"
                _finish(row, AreaSweep.State.UNAVAILABLE, reason)
                self.stdout.write(f"{area}: UNAVAILABLE ({reason})")
                continue
            if outcome is None:
                _finish(row, AreaSweep.State.UNAVAILABLE, "no sweep pass could run for this area")
                self.stdout.write(f"{area}: UNAVAILABLE")
                continue
            _finish(
                row, AreaSweep.State.DONE, outcome.stop_reason,
                provider_calls=outcome.provider_calls, cost_usd=outcome.cost_usd,
                new_hosts=outcome.new_hosts, sweep_run_id=outcome.run_id,
            )
            self.stdout.write(
                f"{area}: DONE {outcome.provider_calls} calls ${outcome.cost_usd} "
                f"{outcome.new_hosts} new hosts ({outcome.stop_reason})"
            )
