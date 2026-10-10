"""Run the vendor fetch path over URLs and print what each host cost -- the §4.5 gate.

Nothing is persisted: no snapshot, no source row, no evidence. Run it over a host
list before a corridor sweep to see the residue (which hosts neither vendor reads)
and after one to see the bill in dollars. A vendor with no key in the environment
fails its rung and is named in the output rather than skipped silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.research.discovery import retrieve_official_source
from apps.research.egress import SourceBlocked
from apps.research.fetch import CATALOG_ROLE_NOTE, FetchBudgetExhausted, SweepBudget


class Command(BaseCommand):
    help = (
        "Fetch each URL through the vendor path; print tier, bytes and credits per host."
        + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("urls", nargs="*")
        parser.add_argument("--urls-file", type=Path, help="one URL per line")

    def handle(self, *args: Any, **options: Any) -> None:
        urls = list(options["urls"])
        if options["urls_file"]:
            lines = options["urls_file"].read_text().splitlines()
            urls += [line.strip() for line in lines if line.strip()]
        budget = SweepBudget(settings.FETCH_SWEEP_CREDITS)
        self.stdout.write(f"caps={budget.caps}")
        for url in urls:
            host = urlsplit(url).hostname or url
            try:
                result = retrieve_official_source(url, budget=budget)
            except FetchBudgetExhausted as error:
                # Before SourceBlocked, which it subclasses: an exhausted budget
                # stops the sweep, where a blocked host only skips one line.
                self.stdout.write(f"{host}  BUDGET  {error}")
                break
            except (SourceBlocked, ValueError) as error:
                # ValueError: an http URL or one the validators refuse -- named, not hidden.
                self.stdout.write(f"{host}  UNREACHABLE  {type(error).__name__}: {error}")
                continue
            self.stdout.write(f"{host}  {result.fetched_via}  {len(result.body)} bytes")
        self.stdout.write(f"credits spent {budget.spent}  USD {budget.usd():.4f}")
