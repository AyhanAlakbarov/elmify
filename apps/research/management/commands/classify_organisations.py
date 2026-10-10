"""Classify unclassified organisations under a credit cap (spec 6.6).

Idempotent on `classified_at`, so it is re-run across months: the whole VGM
register is ~2,700 fetches against a 1,000-credit free tier. Operator-run;
`--dry-run` counts what a run would touch and spends nothing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, cast
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from openai import OpenAI

from apps.research.classify import FrontierClassifier, HostClassifier, classify_organisation
from apps.research.extraction import ResponsesAPI
from apps.research.fetch import SweepBudget
from apps.research.models import Organisation


def _classifier() -> HostClassifier:
    return FrontierClassifier(cast(ResponsesAPI, OpenAI().responses))


class Command(BaseCommand):
    help = "Classify organisations that have no verdict yet; frontier path until a Jev key exists."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--found-via", default="", help="Only rows carrying this route tag")
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--firecrawl-credits", type=int, default=300)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        rows = Organisation.objects.filter(classified_at__isnull=True).exclude(
            status=Organisation.Status.REJECTED
        )
        if options["found_via"]:
            rows = rows.filter(found_via__contains=[options["found_via"]])
        rows = rows.order_by("first_seen")[: options["limit"]]
        if options["dry_run"]:
            self.stdout.write(f"would classify {rows.count()}")
            return
        classifier = _classifier()
        budget = SweepBudget({
            **settings.FETCH_SWEEP_CREDITS,
            "FIRECRAWL": options["firecrawl_credits"],
        })
        run_id, now = uuid4(), timezone.now()
        tally: Counter[str] = Counter()
        for org in rows:
            outcome = classify_organisation(
                org, classifier=classifier, run_id=run_id, budget=budget, now=now
            )
            tally[outcome] += 1
            if tally["rate_limited"] or tally["budget"]:
                break
        for outcome, count in sorted(tally.items()):
            self.stdout.write(f"{outcome}: {count}")
        self.stdout.write(f"vendor credits spent: {budget.usd():.4f} USD")
