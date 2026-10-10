"""Score the funnel against the labelled corpus's exact-URL labels (spec 13).

Three numbers, and the third is the one nobody thinks to measure:

* per-stage FIRST-FIND counts -- a stage that never finds a page the earlier
  ones missed is removed, not kept for comfort (spec 7.0);
* misses, kept apart from blocks, because 'found nothing' and 'could not
  look' are different rows and a score that merges them re-creates the exact
  failure this engine exists to remove, inside the instrument meant to
  measure it;
* FALSE STOPS -- a job that stopped `found` on a page the corpus says is not
  the programme's. A stop rule scored only on recall looks perfect while
  stopping on the wrong page every time, and the rule is only as good as D3's
  `documents-list` kind.

The corpus is a JSON list of {source_url, admissions_cycle, requirement_urls}.
Keyed on (source_url, admissions_cycle), not `program_id`: a UUID committed to
the repository resolves only in the database that wrote it (corpus spec
§3.2). `SiteJobRecord` already carries both, so the join is on those two.

Run with `maxConcurrency: 1` in the sweep that produced the rows: Firecrawl
documents that crawl results vary between runs of the same configuration, and
set equality has already failed three designs on this repo.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.research.models import SiteJobRecord


class Command(BaseCommand):
    help = "Score funnel outcomes against the labelled corpus."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--corpus", type=Path, required=True)
        parser.add_argument("--cycle", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        labels = {
            (str(row["source_url"]), str(row["admissions_cycle"])): {
                str(url) for url in row.get("requirement_urls") or []
            }
            for row in json.loads(options["corpus"].read_text())
        }
        rows = SiteJobRecord.objects.all()
        if options["cycle"]:
            rows = rows.filter(admissions_cycle=options["cycle"])
        counts = {
            "found": 0, "no_cv_required": 0, "blocked": 0, "not_found": 0,
            "false_stops": 0,
            "stage1_first": 0, "stage2_first": 0, "stage3_first": 0, "stage4_first": 0,
        }
        matched = 0
        for row in rows.order_by("created_at"):
            wanted = labels.get((row.source_url, row.admissions_cycle))
            if wanted is None:
                # Not in the corpus -- nothing to score it against.
                continue
            matched += 1
            counts[row.outcome] = counts.get(row.outcome, 0) + 1
            hit = wanted & set(row.leads or [])
            if row.outcome == SiteJobRecord.Outcome.FOUND:
                if hit:
                    counts[f"stage{row.stopped_at_stage}_first"] += 1
                else:
                    # It stopped. The corpus says it stopped on the wrong
                    # page. That is not a miss and it is not a find.
                    counts["false_stops"] += 1
        self.stdout.write(
            " ".join(f"{name}={count}" for name, count in counts.items())
            + f" programmes={matched}"
        )
