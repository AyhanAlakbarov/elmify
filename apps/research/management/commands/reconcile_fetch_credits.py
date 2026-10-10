"""Spec 9.2, layer 3: our credit ledger against the vendor's own figure.

A gap over 5% is a defect in OUR accounting, not the vendor's. That matters
because layer 2 -- the per-sweep, per-vendor ceiling -- is the only thing
between a bug and a bill, and a ceiling summing the wrong number is not a
ceiling. The vendor's total is passed in rather than fetched: the credit-usage
endpoints differ per vendor and the figure is read once a month by a person
who is already looking at the invoice.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Sum
from django.utils import timezone

from apps.research.models import FetchAttempt

#: Spec 9.2. Above this the difference is not rounding.
_TOLERANCE = 0.05


class Command(BaseCommand):
    help = "Compare summed FetchAttempt credits against a vendor's own monthly total."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--vendor", required=True)
        parser.add_argument("--vendor-total", type=int, required=True)
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args: Any, **options: Any) -> None:
        since = timezone.now() - timedelta(days=options["days"])
        ours = (
            FetchAttempt.objects.filter(vendor=options["vendor"], created_at__gte=since).aggregate(
                total=Sum("credits")
            )["total"]
            or 0
        )
        theirs = options["vendor_total"]
        # Relative to OURS, not theirs: this reconciliation exists to catch a
        # defect in OUR ledger (module docstring), so the percentage answers
        # "how wrong is our own count", not "how far off is the vendor's
        # total from ours". A defect that halves our own recorded credits
        # reads as a 100% gap either way; a small vendor overage on a large
        # ledger should not be reported small just because the vendor's
        # number is the bigger one.
        gap = abs(ours - theirs) / ours if ours else (1.0 if theirs else 0.0)
        line = f"{options['vendor']}: ours {ours} theirs {theirs} gap {gap * 100:.1f}%"
        self.stdout.write(f"DEFECT {line}" if gap > _TOLERANCE else line)
