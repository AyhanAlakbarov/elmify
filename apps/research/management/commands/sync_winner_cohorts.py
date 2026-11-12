"""Sync anonymised LinkedIn winner cohort distributions (`WinnerCohortProfile`)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.funding.models import FundingOpportunity, Program
from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.winner_scraper import (
    default_winner_provider,
    sync_winner_cohort_for_opportunity,
    sync_winner_cohort_for_program,
)


class Command(BaseCommand):
    help = (
        "Sync PII-free LinkedIn winner cohort distributions for programmes and scholarships."
        + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", default="", help="Filter by 2-letter ISO country code.")
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of programmes/opportunities to sync in one run.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = default_winner_provider()
        if provider is None:
            self.stdout.write(
                "LINKEDIN_WINNER_PROVIDER_URL is not set; 0 winner cohorts synced."
            )
            return

        country = str(options.get("country") or "").strip().upper()
        limit = max(1, int(options.get("limit") or 50))

        programs = Program.objects.order_by("name")
        opportunities = FundingOpportunity.objects.filter(
            served=True, suspension_quote=""
        ).order_by("name")
        if country:
            programs = programs.filter(country_code=country)
            opportunities = opportunities.filter(country_code=country)

        prog_synced = 0
        for program in programs[:limit]:
            if sync_winner_cohort_for_program(program, provider=provider) is not None:
                prog_synced += 1

        opp_synced = 0
        for opportunity in opportunities[:limit]:
            if sync_winner_cohort_for_opportunity(opportunity, provider=provider) is not None:
                opp_synced += 1

        self.stdout.write(
            f"synced {prog_synced} programme cohorts and {opp_synced} scholarship cohorts"
        )
