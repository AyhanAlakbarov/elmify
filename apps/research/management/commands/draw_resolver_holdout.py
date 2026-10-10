"""Draw the resolver's fresh-script hold-out from Wikidata (build item 8, Task 10).

Free and read-only: Wikidata's query service, no vendor, no database write.
Writes docs/research/resolver-holdout-<cc>.csv with the names the resolver
will see, the truth it will not, and the digest of the resolver being tested.
Run once, after the resolver (every component of holdout.digest_components,
this country's resolver_data/ file included) is committed and frozen -- and
never again for the same country: a re-draw after seeing a result is a
hold-out chosen by someone.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.research import holdout, wikidata
from apps.research.vocabulary import VocabularyMissing, load_vocabulary

#: Items asked per slot. A row is an item now (DRAW_QUERY groups by it) and
#: items already drawn are excluded in the query, so the slack is only for
#: items whose every website is an aggregator or unkeyable -- common where
#: a Facebook page is the website. The query is free and its cost is the
#: class closure, which LIMIT does not shrink, so the slack is generous.
_ITEMS_PER_SLOT = 10


def holdout_path(code: str) -> Path:
    return Path(settings.BASE_DIR) / "docs" / "research" / f"resolver-holdout-{code.lower()}.csv"


class Command(BaseCommand):
    help = "Draw the resolver's blind hold-out for one country from Wikidata. Once."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", default="VN")
        parser.add_argument("--language", default="vi")

    def handle(self, *args: Any, **options: Any) -> None:
        code = options["country"].upper()
        language = options["language"]
        out = holdout_path(code)
        if out.exists():
            raise CommandError(f"{out} exists: a hold-out is drawn once, never re-drawn")
        try:
            country_qid = load_vocabulary(code).country_qid
        except VocabularyMissing as error:
            raise CommandError(
                f"no resolver vocabulary for {code}: {error} (manage.py "
                "build_resolver_vocabulary, committed BEFORE the draw -- it is in the digest)"
            ) from error
        try:
            # Checked before the first query, so a bad --language spends nothing.
            holdout.draw_query(cls=holdout.TOP_UP[1], country_qid=country_qid,
                               lang=language, limit=1)
        except ValueError as error:
            raise CommandError(str(error)) from error

        taken: set[str] = set()
        drawn: list[holdout.Drawn] = []
        shortfall = 0

        def draw(cls: str, n: int, stratum: str) -> list[holdout.Drawn]:
            # Items an earlier stratum took are excluded IN the query, before
            # its LIMIT: classes overlap (a foundation is a nonprofit), and a
            # LIMIT filled with taken items starves the later stratum.
            rows = wikidata.sparql(holdout.draw_query(
                cls=cls, country_qid=country_qid, lang=language,
                limit=n * _ITEMS_PER_SLOT, exclude=taken))
            return holdout.pick(rows, n=n, taken=taken, stratum=stratum)

        for stratum, cls, n in holdout.STRATA:
            got = draw(cls, n, stratum)
            shortfall += n - len(got)
            drawn += got
        if shortfall:
            label, cls = holdout.TOP_UP
            drawn += draw(cls, shortfall, label)
        if not drawn:
            raise CommandError(f"Wikidata returned nothing drawable for {code}/{language}")

        digest = holdout.frozen_digest(code)
        # Per component too, so a gate refusing a changed resolver can say
        # WHICH part moved; `resolver_digest` stays the one number compared.
        parts = json.dumps(holdout.digest_components(code), sort_keys=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["qid", "stratum", "names", "truth", "salt", "resolver_digest",
                             "resolver_digest_parts"])
            for d in drawn:
                writer.writerow([d.qid, d.stratum, " | ".join(d.names), " ".join(d.truth),
                                 holdout.SALT, digest, parts])
        self.stdout.write(f"{len(drawn)} drawn ({shortfall} to top up) -> {out}")
        if len(drawn) < sum(n for _, _, n in holdout.STRATA):
            least_correct, most_wrong = holdout.thresholds(len(drawn))
            self.stdout.write(
                f"short draw, n={len(drawn)}: correct >= {least_correct}, confident-wrong <= "
                f"{most_wrong} (the gate applies these itself; copy them into the results "
                "note before it runs, plan Task 10)")
