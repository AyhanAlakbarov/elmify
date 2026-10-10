"""Create this cycle's monitors: one per host, split at 50 targets.

Targets are the URLs that actually yielded a rule -- not every URL ever
fetched. A monitor over the whole catalog pays 1 credit a page a month for
pages nothing derives from.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.funding.models import ProgramStatement
from apps.research.fetch.monitor import MonitorBudgetExceeded, build_targets, create_monitor


class Command(BaseCommand):
    help = "Create the admissions cycle's Firecrawl monitors."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--cycle", required=True)
        parser.add_argument(
            "--reserve",
            type=int,
            default=10_000,
            help="credits left for the sweeps, not the monitors",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        cycle = options["cycle"]
        urls = sorted(
            {
                str(url)
                for url in ProgramStatement.objects.filter(
                    snapshot__admissions_cycle=cycle
                ).values_list("snapshot__final_url", flat=True)
                if url
            }
        )
        by_host: dict[str, list[str]] = {}
        for url in urls:
            by_host.setdefault((urlsplit(url).hostname or "").lower(), []).append(url)
        committed = 0
        for host, host_urls in sorted(by_host.items()):
            batches = build_targets(host_urls, hosts=(host,), include_paths=("document",))
            for index, batch in enumerate(batches):
                name = f"{cycle}:{host}" + (f":{index}" if index else "")
                if options["dry_run"]:
                    self.stdout.write(f"{name}  {len(batch)} targets")
                    continue
                try:
                    created = create_monitor(
                        api_key=settings.FIRECRAWL_API_KEY,
                        name=name,
                        targets=batch,
                        already_committed=committed,
                        reserve=options["reserve"],
                    )
                except MonitorBudgetExceeded as error:
                    # Stop, do not skip: the hosts are sorted, so stopping
                    # leaves a prefix monitored and a suffix not, which is
                    # reproducible. Skipping would leave an arbitrary set.
                    self.stdout.write(f"stopping: {error}")
                    return
                committed += created.estimated_credits_per_month
                self.stdout.write(
                    f"{name}  {created.monitor_id}  "
                    f"{created.estimated_credits_per_month} credits/month"
                )
        self.stdout.write(f"{committed} credits/month committed for {cycle}")
