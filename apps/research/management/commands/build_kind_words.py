"""Build the angle generator's kind words from Wikidata (spec 6.5 rule 1).

Operator-run and free (the query service is CC0 and unauthenticated). It
reads `resolver_data/holder_kinds.json` and writes `kind_words.json` beside
it: every label and alias of each mapped item, in every language Wikidata
has. Commit what it writes; re-running changes the file only when Wikidata
or the map changed.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import kind_words, vocabulary
from apps.research.egress import SourceBlocked


class Command(BaseCommand):
    help = "Write apps/research/resolver_data/kind_words.json from Wikidata."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            doc = kind_words.build_kind_words_doc(
                retrieved_on=timezone.now().date().isoformat()
            )
        except (ValueError, SourceBlocked) as error:
            # VocabularyShape is a ValueError; a refused or failed query is
            # SourceBlocked. Either stops the build before the file is written.
            raise CommandError(str(error)) from error
        (vocabulary.DATA_DIR / kind_words._WORDS_FILE).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), "utf-8"
        )
        for kind, by_language in doc["words"].items():
            self.stdout.write(f"{kind}: {len(by_language)} languages")
