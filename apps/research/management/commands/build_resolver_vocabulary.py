"""Build the resolver's vocabulary files from Wikidata (spec 6.5, rules 1-3).

Operator-run, free (the query service is CC0 and unauthenticated), and
deterministic enough to diff: re-running it changes a file only when
Wikidata changed. Commit what it writes; the files are the data, the
queries in them are the provenance.

Names reach `vocabulary` through the module, not `from ... import`, so the
directory and the builders are read at call time -- which is what lets a test
point the command at a temporary directory and fake Wikidata.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import vocabulary
from apps.research.egress import SourceBlocked


class Command(BaseCommand):
    help = "Write apps/research/resolver_data/<CC>.json and kinds.json from Wikidata."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--countries", required=True, help="comma-separated ISO2, e.g. TR,DE")
        parser.add_argument("--kind-depth", type=int, default=2, choices=(2, 3))

    def handle(self, *args: Any, **options: Any) -> None:
        today = timezone.now().date().isoformat()
        data_dir = vocabulary.DATA_DIR
        data_dir.mkdir(exist_ok=True)
        try:
            for code in [c.strip().upper() for c in options["countries"].split(",") if c.strip()]:
                doc = vocabulary.build_country_doc(code, retrieved_on=today)
                (data_dir / f"{code}.json").write_text(
                    json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
                self.stdout.write(f"{code}: {len(doc['geo'])} place tokens, "
                                  f"{len(doc['generic'])} common words over "
                                  f"{doc['organisation_labels']} names, "
                                  f"languages {doc['languages']}")
            # Every committed country's languages, not only this run's: a kinds
            # file narrower than any country file fails that country's load.
            languages = sorted({
                lang for path in data_dir.glob("[A-Z][A-Z].json")
                for lang in json.loads(path.read_text("utf-8"))["languages"]
            })
            kinds = vocabulary.build_kinds_doc(
                languages, depth=options["kind_depth"], retrieved_on=today
            )
        except (ValueError, SourceBlocked) as error:
            # VocabularyShape is a ValueError, as is a malformed --countries
            # code; a refused or failed query is SourceBlocked. Each stops the
            # build before kinds.json is written.
            raise CommandError(str(error)) from error
        (data_dir / "kinds.json").write_text(
            json.dumps(kinds, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
        words = sum(len(w) for w in kinds["kinds"].values())
        self.stdout.write(
            f"kinds: {len(kinds['kinds'])} items, {words} words, {len(languages)} languages"
        )
