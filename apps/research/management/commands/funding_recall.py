"""Report how many known programme-attached awards the reader has found.

    uv run python manage.py funding_recall [--csv docs/research/programme-funding-known-answers.csv]

Recall is REPORTED, never asserted: the exit code is always 0 and no test
hard-codes a rate (spec section 11). Per known answer:

- PENDING: no snapshot at that programme's host has been funding-read
  (OfficialSourceSnapshot.funding_read_at is null on every one, or none exists);
- MISSED: a snapshot there was funding-read and no row quotes the award --
  including a read that found nothing at all;
- UNSERVED: a row quotes it, but the three readings did not agree;
- PASS: a served row quotes it;
- BADPATTERN: the row's own `pattern` is not a valid regular expression.

Hosts compare case-insensitively with a leading "www." stripped on both sides.
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandParser

from apps.funding.models import FundingOpportunity, OfficialSourceSnapshot

DEFAULT_CSV = Path("docs/research/programme-funding-known-answers.csv")


def _origin(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold().removeprefix("www.")


def status_for(pattern: str, programme_url: str) -> str:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return "BADPATTERN"
    origin = _origin(programme_url)
    # icontains pre-filters; the exact host comparison decides.
    read_urls = OfficialSourceSnapshot.objects.filter(
        funding_read_at__isnull=False, source__canonical_url__icontains=origin
    ).values_list("source__canonical_url", flat=True)
    if not any(_origin(url) == origin for url in read_urls):
        return "PENDING"
    candidates = (
        FundingOpportunity.objects.filter(evidence_claims__source__canonical_url__icontains=origin)
        .prefetch_related("evidence_claims__source")
        .distinct()
    )
    matched = [
        row
        for row in candidates
        if any(
            _origin(claim.source.canonical_url) == origin and regex.search(claim.claim)
            for claim in row.evidence_claims.all()
        )
    ]
    if not matched:
        return "MISSED"
    return "PASS" if any(row.served for row in matched) else "UNSERVED"


class Command(BaseCommand):
    help = "Report the reader's recall against the known-answer set of programme-attached awards"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)

    def handle(self, *_args: object, **options: object) -> None:
        path = Path(str(options["csv"]))
        counts: Counter[str] = Counter()
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                status = status_for(row["pattern"], row["programme_url"])
                counts[status] += 1
                self.stdout.write(f"{status:<9} {row['country_iso']} {row['programme_url']}")
        self.stdout.write(
            f"pass={counts['PASS']} unserved={counts['UNSERVED']} "
            f"missed={counts['MISSED']} pending={counts['PENDING']} "
            f"badpattern={counts['BADPATTERN']}"
        )
