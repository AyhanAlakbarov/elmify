import os
from typing import cast
from uuid import UUID

import anthropic
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.utils import ProgrammingError
from django.utils import timezone
from openai import OpenAI

from apps.research.batch_reading import BatchClients
from apps.research.discovery import DiscoveryQuery, RunBudget, normalize_teaching_languages
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE, RUNTIME_ENGINE_WRITE_REFUSED, SweepBudget
from apps.research.funding_judge import FUNDING_READS, MAX_CHUNKS
from apps.research.model_cost import FLEX_TIMEOUT_SECONDS, ReadingTier
from apps.research.pipeline import PacedFetch, default_sources, run_discovery
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope


class Command(BaseCommand):
    help = (
        "Discover funding leads and write shared-catalog rows (design §2.7)."
        + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--field", required=True)
        parser.add_argument("--country", required=True)
        # The run's cost-attribution actor (pipeline.run_discovery). A blocked
        # source no longer needs a tenant: it is filed to the platform's
        # resolution queue or reported in `degraded`, never a tenant's task.
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--languages", default="")
        parser.add_argument("--max-leads", type=int, default=25)
        parser.add_argument("--cycle", default="")
        parser.add_argument("--dry-run", action="store_true")
        # No --render: the browser tier it drove was deleted with the Scrapling
        # ladder, and JS rendering is the vendor's job behind `fetch` now.
        parser.add_argument(
            "--funding",
            action="store_true",
            help="also read each written catalogue page for funding "
            "(up to 9 model calls from two model families; new or changed pages only)",
        )
        parser.add_argument(
            "--reading-tier",
            choices=tuple(tier.value for tier in ReadingTier),
            default=ReadingTier.STANDARD.value,
            help="how --funding readings are bought (item 15); batch waits for both vendors, "
            "up to 24 hours per batch (48 with a tie-break batch); standard until the gate is read",
        )

    def handle(self, *_args: object, **options: object) -> None:
        # No --level: Program.DegreeLevel holds only MASTER, and resolve_program
        # writes MASTER regardless. Add the argument back alongside the second
        # degree level, with the contract check it needs then.
        languages = normalize_teaching_languages(
            value for value in str(options["languages"]).split(",") if value.strip()
        )
        max_leads = int(str(options["max_leads"]))
        query = DiscoveryQuery(
            field=str(options["field"]),
            country_code=str(options["country"]).upper(),
            teaching_languages=languages,
            max_leads=max_leads,
        )
        tenant_id = UUID(str(options["tenant"]))
        funding = bool(options["funding"])
        reading_tier = ReadingTier(str(options["reading_tier"]))
        if funding and not os.environ.get("ANTHROPIC_API_KEY"):
            raise CommandError(
                "--funding needs ANTHROPIC_API_KEY: a funding row is served only when two "
                "model families agree on it"
            )
        # After the key check, so a missing key fails with the reason, not an SDK error.
        openai_client = anthropic_client = None
        if funding:
            openai_client = (
                OpenAI(timeout=FLEX_TIMEOUT_SECONDS)
                if reading_tier is ReadingTier.FLEX
                else OpenAI()
            )
            anthropic_client = anthropic.Anthropic()
        api_key = str(settings.SEARCH_API_KEY)
        if not api_key:
            self.stderr.write("SEARCH_API_KEY is unset: seed catalogues only, no live search.")
        # One catalogue lead costs two fetches (the listing hop), so the fetch
        # ceiling is generous relative to the lead cap; extraction is one per lead,
        # plus up to three chunks of three readings per lead when --funding reads it for money.
        reads = 1 + (FUNDING_READS * MAX_CHUNKS if funding else 0)
        budget = RunBudget(searches=4, fetches=max_leads * 3, extractions=max_leads * reads)
        # RunBudget caps the NUMBER of fetches; SweepBudget caps what they
        # cost. A count ceiling cannot bound cost: scrape.do applies per-domain
        # multipliers of 10-200 credits server-side with no request-time signal,
        # so the same fetch count is anywhere between 1x and 200x the bill.
        # Do not merge the two. The cap is per vendor because a credit is not a
        # unit -- Firecrawl's is 7.16x scrape.do's.
        fetch = PacedFetch(
            actor_id=tenant_id,
            budget=budget,
            credits=SweepBudget(settings.FETCH_SWEEP_CREDITS),
        )
        cycle = str(options["cycle"]) or str(timezone.now().year + 1)
        try:
            # No render= : the browser tier is gone, both the plain and the
            # JS-rendering ladder now live behind the vendor seam that `fetch`
            # already goes through (discovery.retrieve_official_source).
            with tenant_scope(tenant_id):
                report = run_discovery(
                    query,
                    default_sources(
                        api_key=api_key, fetch=fetch, budget=budget, actor_id=tenant_id
                    ),
                    tenant_id=tenant_id,
                    store=S3ObjectStore(),
                    admissions_cycle=cycle,
                    fetch=fetch,
                    budget=budget,
                    dry_run=bool(options["dry_run"]),
                    funding_parser=(
                        cast(ResponsesAPI, openai_client.responses) if openai_client else None
                    ),
                    funding_claude=(
                        cast(MessagesAPI, anthropic_client.messages) if anthropic_client else None
                    ),
                    reading_tier=reading_tier,
                    funding_batch=(
                        BatchClients(openai=openai_client, anthropic=anthropic_client)
                        if funding and reading_tier is ReadingTier.BATCH
                        else None
                    ),
                )
        except ProgrammingError as error:
            raise CommandError(RUNTIME_ENGINE_WRITE_REFUSED.format(error=error)) from error
        self.stdout.write(
            f"leads={report.leads} written={report.written} unchanged={report.unchanged} "
            f"blocked={report.blocked} degraded={','.join(report.degraded) or 'none'}"
            f" funding: {report.funding}"
        )
