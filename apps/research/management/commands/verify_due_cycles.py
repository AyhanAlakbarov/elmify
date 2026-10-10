"""Run the verification ladder for every (award, intake) whose check is due.

Platform work: the catalog is shared, so no tenant triggers this and none is
charged for it. It writes shared-catalog rows -- `funding_fundingcycleverification`,
and `funding_fundingopportunity` on a withdrawal -- and every fetch writes a
FetchAttempt/HostProfile row, so it runs as DATABASE_ROLE=runtime_engine, the
catalogue's only writer (`runtime_engine_write`), exactly as the worker task
does. Never as `catalog_ingestion`: that role was dropped by
funding/0049_catalog_grants.py. `runtime_web` holds no grant on these tables at
all, and the migration role, which owns them, would bypass their policies
(ENABLE without FORCE) -- so only runtime_engine runs the path the policies
were written for (CLAUDE.md, "Row-level security").

Its EventBridge rule (`VerifyDueCyclesRule`) ships DISABLED; the reasons are in
infra/template.yaml above the rule.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any, cast

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q
from django.utils import timezone
from openai import OpenAI

from apps.funding.cycle_schedule import tracked_intakes
from apps.funding.models import FundingCycleVerification, FundingOpportunity
from apps.research.cycle_verification import (
    build_seams,
    persist_verdict,
    record_run_error,
    stored_evidence,
    subject_for,
    verify_cycle,
)
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget
from apps.research.metering import Meter

logger = logging.getLogger(__name__)

#: How each award's seams are built. A module attribute so a test can drive the
#: whole loop through scripted seams; production is always `build_seams`.
seams_factory = build_seams


def _verifiable() -> Q:
    return Q(opportunity__agreement="AGREED") & ~Q(opportunity__review="REJECTED")


class Command(BaseCommand):
    help = (
        "Verify every due (award, intake) through the evidence ladder (master spec 9.2-9.3)."
        + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--max", type=int, default=50)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise CommandError(
                "verify_due_cycles needs ANTHROPIC_API_KEY: an award's evidence is read by two "
                "model families, as it is everywhere else"
            )
        today = timezone.now().date()
        if not options["dry_run"]:
            self._ensure_tracked(today)
        due = list(
            FundingCycleVerification.objects.filter(
                _verifiable(), next_check_at__lte=timezone.now()
            )
            .select_related("opportunity__organisation")
            .order_by("next_check_at")[: options["max"]]
        )
        self.stdout.write(f"due {len(due)}")
        for row in due:
            self.stdout.write(f"  {row.intake_start_year} {row.opportunity.name} [{row.state}]")
        if options["dry_run"]:
            return
        run = SweepBudget(settings.CYCLE_RUN_CREDITS)
        parser = cast(ResponsesAPI, OpenAI().responses)
        claude = cast(MessagesAPI, anthropic.Anthropic().messages)
        spent = 0.0
        for row in due:
            if spent >= settings.CYCLE_VERIFY_RUN_BUDGET_USD:
                self.stdout.write(f"run budget ${settings.CYCLE_VERIFY_RUN_BUDGET_USD} reached")
                break
            meter = Meter(run)
            try:
                self._verify(row, meter, parser, claude, today)
            except Exception as error:
                # One award must not crash the run and starve every row behind
                # it: that row would head the due queue again next time, and
                # fail again. Recorded on the row and backed off instead.
                logger.exception("cycle verification failed for %s (%s)",
                                 row.opportunity_id, row.intake_start_year)
                record_run_error(row, error, meter=meter, now=timezone.now())
                self.stdout.write(
                    f"{row.intake_start_year} {row.opportunity.name}: ERROR "
                    f"{type(error).__name__}, retried in {settings.CYCLE_ERROR_BACKOFF_DAYS} day(s)"
                )
            spent += float(meter.total()[0])

    def _verify(
        self, row: FundingCycleVerification, meter: Meter, parser: ResponsesAPI,
        claude: MessagesAPI, today: dt.date,
    ) -> None:
        seams = seams_factory(meter, parser, claude, source_id=str(row.opportunity_id))
        subject = subject_for(row.opportunity)
        stored, looked = stored_evidence(row.opportunity)
        verdict = verify_cycle(subject, intake_year=row.intake_start_year, today=today,
                               seams=seams, meter=meter, stored=stored, looked=looked,
                               history=row.trail)
        persist_verdict(row, verdict, meter=meter, today=today)
        usd, _detail, complete = meter.total()
        self.stdout.write(
            f"{row.intake_start_year} {row.opportunity.name}: {verdict.state} "
            f"at step {verdict.step}, ${usd:.4f}{'' if complete else ' (floor: unpriced)'}"
        )

    def _ensure_tracked(self, today: dt.date) -> None:
        """Every agreed award has a row for each tracked intake; rows whose
        intake has started stop being scheduled."""
        years = tracked_intakes(today)
        FundingCycleVerification.objects.filter(intake_start_year__lt=years[0]).update(
            next_check_at=None
        )
        for opportunity in FundingOpportunity.objects.filter(agreement="AGREED").exclude(
            review="REJECTED"
        ):
            for year in years:
                FundingCycleVerification.objects.get_or_create(
                    opportunity=opportunity, intake_start_year=year,
                    defaults={"next_check_at": timezone.now()},
                )
