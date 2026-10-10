"""Enumerate every EMJM from EACEA's project records into the register.

Projects land on the `eacea_emjm` list (ENUMERATE_ONLY); partners become
CANDIDATE bodies of kind UNSTATED plus one `RegisterEntryPartner` row per
participation. The sum of the API's own totals is the list's printed size.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import eacea
from apps.research.egress import SourceBlocked
from apps.research.fetch import CATALOG_ROLE_NOTE


class Command(BaseCommand):
    help = "Enumerate every EMJM project and its partners from EACEA." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        # Every action is fetched and its total asserted before anything is
        # written: a silently ignored filter is a stop, never a partial load.
        fetched, failed = [], []
        for row in eacea.read_actions():
            try:
                fetched.append((row, *eacea.fetch_projects(row)))
            except (eacea.TotalShape, SourceBlocked) as error:
                self.stderr.write(f"{row.code}: {error}")
                failed.append(row.code)
        if failed:
            raise CommandError(f"failed: {', '.join(failed)}")
        grand_total = sum(total for _row, total, _projects in fetched)
        if options["dry_run"]:
            for row, total, projects in fetched:
                self.stdout.write(
                    f"{row.code}: projects {len(projects)} / total {total} "
                    "(dry run, nothing written)"
                )
            return
        now = timezone.now()
        projects_seen = partners = 0
        histogram: dict[str, int] = {}
        for row, total, projects in fetched:
            report = eacea.record_projects(projects, now=now)
            projects_seen += report.projects
            partners += report.partners
            for disposition, count in report.by_disposition:
                histogram[disposition] = histogram.get(disposition, 0) + count
            self.stdout.write(f"{row.code}: projects {report.projects} / total {total}")
        eacea.set_printed_size(grand_total)
        conflicts = histogram.get(eacea.Disposition.CONFLICT, 0)
        share = 100 * conflicts / partners if partners else 0.0
        self.stdout.write(f"projects {projects_seen} / total {grand_total}")
        for disposition, count in sorted(histogram.items()):
            self.stdout.write(f"  {disposition}: {count}")
        self.stdout.write(f"conflict share {share:.1f}% of {partners} participations")
