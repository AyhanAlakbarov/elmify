"""Read one closed list into the register (spec 6.2) and print the ladder report.

Operator-run. One register today -- VGM, Türkiye's scholarship-giving
foundations -- and adding one is adding a choice to `--register`, never a
country-specific command. Nothing here searches.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import vgm
from apps.research.fetch import SweepBudget


class Command(BaseCommand):
    help = "Read a closed list into the Organisation register and print the ladder report."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--register", required=True, choices=["vgm"])
        parser.add_argument(
            "--max-pages", type=int, default=None, help="Probe knob: stop after N pages"
        )
        parser.add_argument("--firecrawl-credits", type=int, default=400)
        parser.add_argument(
            "--start-page",
            type=int,
            default=1,
            help="Resume from this page; start on a full page, not the register's last short one",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        slug = vgm.REGISTER
        budget = SweepBudget({
            **settings.FETCH_SWEEP_CREDITS,
            "FIRECRAWL": options["firecrawl_credits"],
        })
        now = timezone.now()
        totals: Counter[str] = Counter()
        start_page = options["start_page"]
        if start_page > 1:
            self.stdout.write(f"resuming from page {start_page}")
        try:
            for page in vgm.read_vgm(
                max_pages=options["max_pages"],
                budget=budget,
                start_page=start_page,
            ):
                report = vgm.record_vgm(page, now=now)
                totals.update(asdict(report))
                self.stdout.write(f"page: listed {report.listed}, resolved {report.resolved}")
        except vgm.RegisterShape as error:
            raise CommandError(str(error)) from error
        cov = vgm.register_coverage(slug)
        self.stdout.write(f"listed: {totals['listed']}")
        self.stdout.write(f"resolved: {totals['resolved']}  unresolved: {totals['unresolved']}")
        self.stdout.write(
            f"organisations new: {totals['organisations_new']}  "
            f"known: {totals['organisations_known']}"
        )
        self.stdout.write(f"name-keyed rows: {totals['name_keyed']}")
        self.stdout.write(f"bodies known ÷ listed: {cov.bodies_known}/{cov.listed}")
        self.stdout.write(f"classified: {cov.classified}  funds_students: {cov.funds_students}")
        self.stdout.write(f"vendor credits spent: {budget.usd():.4f} USD")
