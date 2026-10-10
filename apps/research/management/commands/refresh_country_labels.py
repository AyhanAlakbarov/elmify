"""Regenerate docs/research/country-labels.csv from Wikidata (CC0).

A contracted-API call through `wikidata._query` (itself `egress.fetch_json_api`,
master spec 7) -- a data source, not a page, so never a fetch vendor. Run by
hand when a language is added to the truth set; commit the file it writes.

Until it has been run live the committed file is its header row alone, so
`deadline_conditions.default_countries()` is empty and every country phrase
normalises to `OTHER:<text>` -- shown as written, never guessed.
"""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.research.wikidata import ENDPOINT as SPARQL_URL
from apps.research.wikidata import _query

#: The truth set's languages (master spec 9.3) plus English.
LANGUAGES = ("en", "de", "tr", "az", "fr", "nl", "sv", "hu", "it")
#: ~250 ISO countries x nine languages x label + demonym is thousands of rows.
#: A 200 carrying fewer than this is a failed or truncated query, not the
#: world; written, it would send every country phrase to OTHER in silence.
MIN_ROWS = 200
_QUERY = """
SELECT ?code ?label ?kind WHERE {{
  ?country wdt:P297 ?code .
  {{ ?country rdfs:label ?label . BIND("label" AS ?kind) }}
  UNION {{ ?country wdt:P1549 ?label . BIND("demonym" AS ?kind) }}
  FILTER(LANG(?label) IN ({languages}))
}}
"""


class Command(BaseCommand):
    help = "Write docs/research/country-labels.csv from Wikidata labels and demonyms."

    def add_arguments(self, parser: CommandParser) -> None:
        default = Path(__file__).resolve().parents[4] / "docs" / "research" / "country-labels.csv"
        parser.add_argument("--out", default=str(default))

    def handle(self, *args: Any, **options: Any) -> None:
        languages = ", ".join(f'"{language}"' for language in LANGUAGES)
        # The raw body, not wikidata.sparql()'s flattened {var: value} rows:
        # this command needs each binding's xml:lang, which sparql() drops.
        data = _query(_QUERY.format(languages=languages))
        results: Any = data.get("results") or {}
        today = timezone.now().date().isoformat()
        rows = sorted(
            {
                (
                    binding["label"]["value"],
                    binding["code"]["value"].upper(),
                    binding["label"].get("xml:lang", ""),
                    binding["kind"]["value"],
                )
                for binding in results.get("bindings", [])
                if len(binding["code"]["value"]) == 2
            }
        )
        if len(rows) < MIN_ROWS:
            raise CommandError(
                f"{len(rows)} labels from Wikidata, fewer than {MIN_ROWS}: "
                f"{options['out']} left unchanged"
            )
        out = Path(options["out"])
        # A temp file beside the target, then one rename: a crash mid-write
        # never leaves a half-written vocabulary in place.
        fd, temp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("label", "iso2", "language", "kind", "source", "fetched_on"))
                for label, code, language, kind in rows:
                    writer.writerow((label, code, language, kind, SPARQL_URL, today))
            os.replace(temp, out)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        self.stdout.write(f"{len(rows)} labels -> {options['out']}")
