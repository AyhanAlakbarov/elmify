"""Compare two funding_yield --cost-csv runs page by page (item 15's gate).

Reads two files and prints numbers; calls no model and touches no database.
`--repeat` is a second run of BEFORE's own configuration: the verdict deltas
between those two are the run-to-run noise floor, and a tier change whose
verdict deltas exceed it has changed what the reader decides, not only what
it costs.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.research.cost_compare import compare, read_cost_csv


class Command(BaseCommand):
    help = "Compare two funding_yield --cost-csv files page by page."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("before")
        parser.add_argument("after")
        parser.add_argument("--repeat", default="")

    def handle(self, *_args: object, **options: object) -> None:
        try:
            before = read_cost_csv(Path(str(options["before"])))
            after = read_cost_csv(Path(str(options["after"])))
            repeat = read_cost_csv(Path(str(options["repeat"]))) if options["repeat"] else None
        except (OSError, ValueError) as error:
            raise CommandError(str(error)) from error
        for line in compare(before, after).lines():
            self.stdout.write(line)
        if repeat is not None:
            noise = compare(before, repeat)
            self.stdout.write(f"noise floor (before vs its repeat): {noise.verdict_line()}")
