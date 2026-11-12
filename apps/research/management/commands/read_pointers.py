"""Read the bodies pointers named, once the resolver placed them (spec 2026-09-27 4.7).

The same reader every other route uses -- `run_discovery` with both model
families, each page paid for and rate-limited before its first reading by
`pipeline._pay_for_funding` (`rate_limited("discovery-extraction", ...)`) --
fed by `PointerSource`. Placing is `manage.py resolve_register --register
pointer --write`; a name nothing placed is a SITE_UNKNOWN item, not a lead.
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

from apps.research.discovery import DiscoveryQuery, RunBudget
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE, SweepBudget
from apps.research.funding_judge import FUNDING_READS, MAX_CHUNKS
from apps.research.pipeline import PacedFetch, run_discovery
from apps.research.pointers import POINTER_REGISTER, PointerSource
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope


class Command(BaseCommand):
    help = "Read the bodies pointers named, once the resolver placed them." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--max-leads", type=int, default=60)
        parser.add_argument("--cycle", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            if not os.environ.get(key):
                raise CommandError(f"{key} is unset: a row is served only when two families agree")
        tenant_id = UUID(options["tenant"])
        max_leads = int(options["max_leads"])
        # As read_closed_list counts it: a homepage fetch, and up to three chunks
        # of three readings.
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
                    DiscoveryQuery(field=POINTER_REGISTER, country_code="", max_leads=max_leads),
                    [PointerSource()],
                    tenant_id=tenant_id,
                    store=S3ObjectStore(),
                    admissions_cycle=options["cycle"] or str(timezone.now().year + 1),
                    fetch=fetch,
                    budget=budget,
                    funding_parser=cast(ResponsesAPI, OpenAI().responses),
                    funding_claude=cast(MessagesAPI, anthropic.Anthropic().messages),
                )
        except ProgrammingError as error:
            raise CommandError(
                "a database write was refused: the shared catalogue is writable only by "
                f"runtime_engine (run with DATABASE_ROLE=runtime_engine). ({error})"
            ) from error
        self.stdout.write(
            f"leads={report.leads} blocked={report.blocked} "
            f"degraded={','.join(report.degraded) or 'none'} funding: {report.funding}"
        )
        self.stdout.write(f"pointers these pages named: {len(report.pointer_names)}")
