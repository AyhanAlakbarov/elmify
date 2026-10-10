"""Read a monitor's checks and act on each page's status (spec 8).

The delivery path until a public HTTPS endpoint exists; polling costs no
credits. Runs on the same 6-hour EventBridge rule as `retry_due_fetches`.

`changed` sets the snapshot's `retrieval_status` to STALE -- the reader's own
trigger, already in the schema -- rather than enqueueing a ResearchMessage.
That queue is FIFO **by tenant**, and this command runs platform-wide with no
tenant scope, so every message it wrote would land in one arbitrary group.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from apps.funding.models import OfficialSourceSnapshot
from apps.research.fetch import fetch_page
from apps.research.fetch.monitor import list_checks


class Command(BaseCommand):
    help = "Poll Firecrawl monitor checks and act on each page's status."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--monitor", required=True, action="append", dest="monitors")

    def handle(self, *args: Any, **options: Any) -> None:
        # Seeded so a status the run never saw still prints as 0 -- "changed=0"
        # and a missing "changed" read differently on an operator's terminal.
        counts: Counter[str] = Counter(
            {"same": 0, "changed": 0, "new": 0, "removed": 0, "error": 0}
        )
        for monitor_id in options["monitors"]:
            for page in list_checks(api_key=settings.FIRECRAWL_API_KEY, monitor_id=monitor_id):
                counts[page.status] += 1
                if page.status == "changed":
                    _mark(page.url, OfficialSourceSnapshot.RetrievalStatus.STALE)
                elif page.status == "removed":
                    # Spec 8 calls this a catalog review row. It is NOT a
                    # ConsultantResearchTask: that model is tenant-scoped and
                    # this command has no tenant, so the row would be written
                    # under a null tenant and be invisible to every agency.
                    # The snapshot's own FAILED status is the catalog-visible
                    # fact the owner console already reads.
                    _mark(page.url, OfficialSourceSnapshot.RetrievalStatus.FAILED)
                elif page.status in {"new", "error"}:
                    # `new`: never fetched by us, so there is no snapshot to
                    # mark. `error`: the monitor's own fetch failed, which is
                    # the per-URL ladder's question, not the monitor's.
                    fetch_page(page.url)
        self.stdout.write(" ".join(f"{name}={count}" for name, count in sorted(counts.items())))


def _mark(url: str, status: str) -> None:
    # INERT IN PRODUCTION TODAY, and silently so (CLAUDE.md, RLS failure mode 1).
    # `funding_officialsourcesnapshot` carries `shared_catalog_select` (SELECT,
    # everyone) and `runtime_engine_write` (INSERT, `runtime_engine`) and
    # NO UPDATE policy -- `apps/funding/migrations/0006_official_snapshots.py`.
    # funding/0049 repointed that write policy to `runtime_engine` (the role
    # this command runs as on the worker) and dropped `catalog_ingestion`, so
    # the writing role now exists; the UPDATE policy still does not. Under
    # `runtime_engine` this UPDATE is legal SQL matching zero rows, so nothing
    # is marked STALE and no error is raised. No test can see it: the test role
    # bypasses RLS. Closing it needs an UPDATE policy `TO runtime_engine`.
    # Until then this command reports work it did not do.
    OfficialSourceSnapshot.objects.filter(final_url=url).update(retrieval_status=status)
