"""The 30-card hand check (spec 8.8; build item 13's gate). Writes no row.

    card_check --sample cards.csv --count 30 --seed 13 --out check.csv
    card_check --score check.csv

`--sample` takes WHOLE cards -- every filled field of each sampled award --
because the question is "is this card right", not "is this field right".
A person marks each row's `correct` column yes or no against the quote and the
page; `--score` then fails on: any row left unmarked; any wrong `amount` (the
figure a student budgets on); any wrong `condition` (the spec's zero false
eligibility); or overall precision below 90%.
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

_PASS = 0.90
_ZERO_TOLERANCE = ("amount", "condition")


class Command(BaseCommand):
    help = "Sample served cards for a hand check, or score a checked sample."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--sample", default="")
        parser.add_argument("--count", type=int, default=30)
        parser.add_argument("--seed", type=int, default=13)
        parser.add_argument("--out", default="")
        parser.add_argument("--score", default="")

    def handle(self, *_args: object, **options: object) -> None:
        if options["sample"]:
            self._sample(
                Path(str(options["sample"])), int(str(options["count"])),
                int(str(options["seed"])), Path(str(options["out"])),
            )
        elif options["score"]:
            self._score(Path(str(options["score"])))
        else:
            raise CommandError("give --sample or --score")

    def _sample(self, source: Path, count: int, seed: int, out: Path) -> None:
        rows = [
            row for row in csv.DictReader(source.open(encoding="utf-8"))
            if row["state"] == "FILLED"
        ]
        cards = sorted({(row["page_url"], row["award"]) for row in rows})
        if len(cards) < count:
            raise CommandError(f"only {len(cards)} filled cards to sample from, asked for {count}")
        chosen = set(random.Random(seed).sample(cards, count))  # nosec B311 - QA sampling, not crypto
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[*rows[0], "correct", "note"])
            writer.writeheader()
            for row in rows:
                if (row["page_url"], row["award"]) in chosen:
                    writer.writerow({**row, "correct": "", "note": ""})
        self.stdout.write(f"{count} cards written to {out}; mark `correct` yes or no")

    def _score(self, path: Path) -> None:
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        unmarked = [row for row in rows if row["correct"] not in ("yes", "no")]
        if unmarked:
            raise CommandError(f"{len(unmarked)} unmarked rows; mark every row yes or no")
        wrong = Counter(row["field"] for row in rows if row["correct"] == "no")
        total = Counter(row["field"] for row in rows)
        for name in sorted(total):
            self.stdout.write(f"{name}: {total[name] - wrong[name]}/{total[name]} correct")
        right = sum(total.values()) - sum(wrong.values())
        precision = right / sum(total.values())
        self.stdout.write(f"overall {right}/{sum(total.values())} = {precision:.1%}")
        for name in _ZERO_TOLERANCE:
            if wrong[name]:
                raise CommandError(f"gate FAILED: {wrong[name]} wrong {name} row(s)")
        if precision < _PASS:
            raise CommandError(f"gate FAILED: {precision:.1%} is under {_PASS:.0%}")
        self.stdout.write("gate PASSED")
