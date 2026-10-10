"""Rung 5: re-enter the ladder for fetches whose retry window has come.

Scheduled, not immediate, because the failures this queue holds are the ones
time fixes -- an outage, a rate-limit window, a deploy. A host still inside its
cool-off is RESCHEDULED rather than spent: retrying it now would defeat the
very cool-off the block set, and the host would answer 403 again for free.

`BUDGET` rows are picked up alongside `RETRY_SCHEDULED` (Task 7 ruling): a
sweep's credit ceiling was never the host's fault, so it is written with its
own outcome and a `retry_after` rather than as a spent RETRY_SCHEDULED round.

There is no round marker on FetchAttempt, so "what is this URL's current
state" rests on `created_at` -- `_due` windows to the LATEST attempt per URL,
because an older RETRY_SCHEDULED/BUDGET row keeps its now-past `retry_after`
even after a later attempt supersedes it, and re-selecting it would re-spend a
round that already happened. Left unbounded, that is a loop with no exit: the
same stale row would be re-fetched, at real vendor cost, on every run forever.

One `SweepBudget` covers the WHOLE run, not one per row. Unattended and
six-hourly, a per-row `default_budget()` is no aggregate ceiling at all --
5,000 due rows would be 5,000 uncapped ladder walks -- and it also makes
`sweep_id`'s own promise ("one sweep's rows can be totalled without guessing
at timestamps") false for every row this worker writes. `--limit` is the other
ceiling: credits bound what a run spends, rows bound what it attempts, and a
cheap outcome costs a request without costing credits.

**What a successful retry does NOT do, and it is owed work, not an oversight.**
It re-enters the ladder and stops at the fetched page: no snapshot is
persisted, no reader is re-run, no consultant task is closed. So a served
retry warms the `HostProfile` and closes the ledger row, and the caller that
originally needed the page still fetches and pays for it again. Delivering the
page means deciding whose `OfficialSource` a retry's snapshot belongs to -- a
provenance question (CLAUDE.md, "Decision B vouches for the SOURCE ROW") that
this worker must not settle alone, because it runs with no tenant and no idea
which caller's read the original fetch was serving.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from ...fetch import SweepBudget, fetch_page
from ...fetch.types import SERVED, Outcome
from ...models import FetchAttempt, HostProfile
from ...services import DomainBusy, acquire_domain_lease

#: Rung 5's own RETRY_SCHEDULED, and a budget boundary's BUDGET (Task 7): both
#: carry a `retry_after` and both are this queue's job to come back for.
_DUE_OUTCOMES = (str(Outcome.RETRY_SCHEDULED), str(Outcome.BUDGET))


def _due(now: datetime) -> list[FetchAttempt]:
    """The due rows, one per URL: only the LATEST attempt for that URL counts.

    `fetch_attempt_url_idx` on (url, -created_at) exists for exactly this
    question (its own docstring: "the latest attempt for a URL"); this reuses
    it rather than trusting every RETRY_SCHEDULED/BUDGET row's own timestamp.
    """
    latest = (
        FetchAttempt.objects.filter(url=OuterRef("url")).order_by("-created_at").values("id")[:1]
    )
    return list(
        FetchAttempt.objects.filter(
            id=Subquery(latest), outcome__in=_DUE_OUTCOMES, retry_after__lte=now,
        ).order_by("retry_after")
    )


class Command(BaseCommand):
    help = "Re-enter the fetch ladder for every scheduled retry that is now due."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--limit", type=int, help="attempt at most this many due rows, oldest first"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        lease = timedelta(seconds=settings.FETCH_RETRY_LEASE_SECONDS)
        budget = SweepBudget(settings.FETCH_SWEEP_CREDITS)
        # `[:None]` is the whole list, so the unbounded run needs no branch.
        due = _due(now)[: options["limit"]]
        self.stdout.write(f"{len(due)} due  caps={budget.caps}")

        served = 0
        for row in due:
            profile = HostProfile.objects.filter(host=row.host).first()
            if profile and profile.blocked_until and profile.blocked_until > now:
                # Rescheduled, not spent: a due retry inside the host's own
                # cool-off would defeat the very block that set it, for free.
                row.retry_after = profile.blocked_until
                row.save(update_fields=["retry_after"])
                continue

            try:
                acquire_domain_lease(row.host, interval=lease)
            except DomainBusy:
                # A sweep, or another copy of this command, is already on this
                # host. Leave the row due -- it is picked up next run, never
                # raced here.
                continue

            # Past the cap, fetch_page's own `check` refuses every rung before
            # a request is made and returns BUDGET with a fresh retry_after, so
            # the rest of the run records why it stopped instead of going quiet.
            page = fetch_page(row.url, purpose=row.purpose, budget=budget)
            if page.outcome in SERVED:
                served += 1
                row.retry_after = None
                row.save(update_fields=["retry_after"])

        self.stdout.write(f"{served} served")
        self.stdout.write(f"credits spent {budget.spent}  USD {budget.usd():.4f}")
