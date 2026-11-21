"""Look at the sweep writer's sentences in every language a set of countries runs in.

Spends money, a little: one SWEEP_ANGLE_MODEL call per language (about $0.001
each on DeepSeek V4.1 Flash, 2026-10-13), capped by --max-languages. Stores
nothing. For each language it reports, by code, the share of sentences that
carry a kind word, whether this year's call names the cycle
in digits, and how many sentences or keyword versions the generator would drop
-- the cheap screen run before a country's paid sweep, and again when
SWEEP_ANGLE_MODEL changes (docs/superpowers/research/
2026-10-13-sweep-sentence-writing-comparison.md). Word presence is
`carries`, which counts inflected forms; a low share names a language for
a person who reads it to look at, it does not prove the sentences wrong.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.angles import (
    PASS_SHAPES,
    _brave_terms,
    _usable,
    ask_angle_set,
    cycle_label,
    openrouter_parser,
)
from apps.research.kind_words import load_kind_words
from apps.research.languages import _ISO2, CldrLanguages, pass_languages


def carries(sentence: str, word: str) -> bool:
    """Whether `sentence` uses `word`: some token contains the word's stem (its
    first letters, all but the last two of a long word, never fewer than three).
    Containment, not a prefix, so inflection ("vakfımız" for "vakıf"), Irish
    initial mutation ("bhfondúireacht") and unspaced scripts (財団) all count."""
    first = unicodedata.normalize("NFKD", word).casefold().split()
    if not first:
        return False
    stem = first[0][: max(3, len(first[0]) - 2)]
    tokens = unicodedata.normalize("NFKD", sentence).casefold().split()
    return any(stem in token for token in tokens)



class Command(BaseCommand):
    help = "Screen the sweep writer's sentences per language (spends about $0.001 a language)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--countries", required=True, help="comma-separated ISO2, e.g. FR,KZ")
        parser.add_argument("--family", default="PRIVATE_FOUNDATION")
        parser.add_argument("--max-languages", type=int, default=60)
        parser.add_argument("--out", default="", help="write every sentence as JSON here")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        family = options["family"]
        if family not in PASS_SHAPES or family == "AFFINITY_OR_DIASPORA":
            raise CommandError(f"{family}: a country-keyed sweep family, not a diaspora pass")
        countries = [c.strip().upper() for c in options["countries"].split(",") if c.strip()]
        if bad := [c for c in countries if not _ISO2.match(c)]:
            raise CommandError(f"not ISO 3166-1 alpha-2 codes: {bad}")
        # Each language once, with the first country that runs it as its aim.
        pairs: dict[str, str] = {}
        for country in countries:
            for language in pass_languages(country, family, source=CldrLanguages()):
                pairs.setdefault(language, country)
        if len(pairs) > options["max_languages"]:
            raise CommandError(
                f"{len(pairs)} languages exceeds --max-languages {options['max_languages']}"
            )
        if options["dry_run"]:
            self.stdout.write(" ".join(f"{lang}({c})" for lang, c in pairs.items()))
            return
        vocabulary = load_kind_words()
        if vocabulary is None:
            raise CommandError("no kind-word vocabulary: run manage.py build_kind_words")
        parser = openrouter_parser()
        cycle = cycle_label(timezone.now())
        kinds = PASS_SHAPES[family].kinds
        report: dict[str, Any] = {}
        self.stdout.write(
            "language country  sentences  kind-word  year  dropped  brave-blanked"
        )
        for language, country in pairs.items():
            kind_words = [w for k in kinds for w in vocabulary.words(k, language)]
            if not kind_words:
                self.stdout.write(f"{language:8} {country:7}  no kind words -- not generated")
                continue
            parsed = ask_angle_set(
                country_code=country, family=family, language=language,
                vocabulary=vocabulary, parser=parser, cycle=cycle,
            )
            if parsed is None or not parsed.angles:
                self.stdout.write(f"{language:8} {country:7}  no answer")
                report[language] = {"country": country, "answer": None}
                continue
            rows = parsed.angles
            kind_hits = sum(any(carries(r.query, w) for w in kind_words) for r in rows)
            season = [r for r in rows if r.angle == "SEASON"]
            year = all(cycle.split("-")[0] in r.query for r in season) if season else None
            dropped = sum(not _usable(r) for r in rows)
            blanked = sum(
                _brave_terms(r.brave_terms) == "" and r.brave_terms != "" for r in rows
            )
            n = len(rows)
            self.stdout.write(
                f"{language:8} {country:7}  {n:9}  {kind_hits / n:9.0%}  "
                f"{'-' if year is None else 'yes' if year else 'NO':4}  {dropped:7}  {blanked:13}"
            )
            report[language] = {
                "country": country, "kind_share": kind_hits / n,
                "year_in_digits": year,
                "dropped": dropped, "brave_blanked": blanked,
                "sentences": [{"angle": r.angle, "query": r.query, "brave_terms": r.brave_terms}
                              for r in rows],
            }
        if options["out"]:
            with open(options["out"], "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=1)
