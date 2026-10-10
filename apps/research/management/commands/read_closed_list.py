"""Read one closed list's scheme pages for funding (spec 6.2, 16 item 7).

The same reader every other route uses -- `run_discovery` with both model
families -- fed by `ClosedListSource`, so a list's pages are read, snapshotted,
chunked, budgeted and rate-limited exactly as a catalogue's are. Only
FUNDING_READ and SIGNAL_ONLY lists are read here; an institution list is read
by the classifier, and saying which command is the whole error message.
"""

from __future__ import annotations

import os
from typing import Any, cast
from uuid import UUID

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.utils import ProgrammingError
from django.utils import timezone
from openai import OpenAI

from apps.research.closed_lists import ClosedListSource
from apps.research.discovery import DiscoveryQuery, RunBudget
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE, RUNTIME_ENGINE_WRITE_REFUSED, SweepBudget
from apps.research.funding_judge import FUNDING_READS, MAX_CHUNKS
from apps.research.models import ClosedList
from apps.research.pipeline import PacedFetch, run_discovery
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope

_READ = (ClosedList.ReadPolicy.FUNDING_READ, ClosedList.ReadPolicy.SIGNAL_ONLY)


class Command(BaseCommand):
    help = "Read a closed list's scheme pages through the funding reader." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        # dest stays "list": call_command forwards a required option only when
        # the keyword it is given is the option's dest.
        parser.add_argument("--list", required=True)
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--max-leads", type=int, default=60)
        parser.add_argument("--cycle", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        slug = options["list"]
        spec = ClosedList.objects.filter(slug=slug).first()
        if spec is None:
            raise CommandError(f"no closed list {slug!r}; run load_closed_lists first")
        if spec.read_policy not in _READ:
            raise CommandError(
                f"{slug} is {spec.read_policy}: nothing here reads it. An institution list "
                f"is read by the classifier: classify_organisations --found-via "
                f"R{spec.rung}_LIST:{slug}"
            )
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(key):
                raise CommandError(f"{key} is unset: a row is served only when two families agree")
        tenant_id = UUID(options["tenant"])
        max_leads = int(options["max_leads"])
        # As `discover --funding` counts it: every lead is catalogued (one
        # extraction) before its funding sections get up to three chunks of
        # three readings.
        budget = RunBudget(
            searches=0, fetches=max_leads * 3,
            extractions=max_leads * (1 + FUNDING_READS * MAX_CHUNKS),
        )
        fetch = PacedFetch(
            actor_id=tenant_id, budget=budget, credits=SweepBudget(settings.FETCH_SWEEP_CREDITS)
        )
        try:
            with tenant_scope(tenant_id):
                report = run_discovery(
                    DiscoveryQuery(
                        field=slug, country_code=spec.country_code, max_leads=max_leads
                    ),
                    [ClosedListSource(slug)],
                    tenant_id=tenant_id,
                    store=S3ObjectStore(),
                    admissions_cycle=options["cycle"] or str(timezone.now().year + 1),
                    fetch=fetch,
                    budget=budget,
                    funding_parser=cast(ResponsesAPI, OpenAI().responses),
                    funding_claude=cast(MessagesAPI, anthropic.Anthropic().messages),
                )
        except ProgrammingError as error:
            raise CommandError(RUNTIME_ENGINE_WRITE_REFUSED.format(error=error)) from error
        self.stdout.write(
            f"leads={report.leads} written={report.written} unchanged={report.unchanged} "
            f"blocked={report.blocked} degraded={','.join(report.degraded) or 'none'} "
            f"funding: {report.funding}"
        )
        self.stdout.write(f"then: manage.py closed_list_coverage --list {slug}")
