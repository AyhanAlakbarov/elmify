"""Write one (country, family)'s angle set -- operator-run, one call per language.

The vocabulary is item 8's kind-word store. Item 8's `apps/research/vocabulary.py`
exists but holds no per-language kind words for our holder kinds: it maps a folded
word to Wikidata kind QIDs with no language key and no map from our holder kinds,
and ships no committed data file. An adapter from it is owed -- per-language labels
kept in kinds.json, and a holder-kind -> Wikidata-QID map -- before this command can
generate. Until it exists this command refuses rather than let the model translate
"foundation" itself (lever 3), and names the one interim the spec permits:
`--from-steering`, which writes today's hand-written STEERING query as a single
labelled angle.
"""

from __future__ import annotations

from typing import Any, cast

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.angles import PASS_SHAPES, KindVocabulary, generate_angles, steering_angle
from apps.research.domains import STEERING
from apps.research.extraction import ResponsesAPI
from apps.research.languages import _ISO2, WikidataLanguages, home_language, pass_languages


def _vocabulary() -> KindVocabulary | None:
    """Item 8's store, once it lands. Replace this body with its constructor;
    until then there is none, and that is a refusal, not a fallback."""
    return None


class Command(BaseCommand):
    help = "Generate the page-voiced angle set for one (country, family) sweep pass."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", required=True)
        parser.add_argument("--family", required=True)
        parser.add_argument(
            "--home-language", action="append", default=[],
            help="The one home language of an AFFINITY_OR_DIASPORA pass; refused for any other",
        )
        parser.add_argument("--from-steering", action="store_true")
        parser.add_argument(
            "--regenerate", action="store_true",
            help="Write a new version even where this cycle's set is already active",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        country, family = options["country"].upper(), options["family"]
        if not _ISO2.match(country):
            raise CommandError(f"not an ISO 3166-1 alpha-2 code: {options['country']!r}")
        if family not in PASS_SHAPES:
            raise CommandError(f"{family} has no open-web sweep (spec 6.3): {sorted(PASS_SHAPES)}")
        try:
            home = home_language(family, options["home_language"])
        except ValueError as error:
            raise CommandError(str(error)) from error
        if options["from_steering"]:
            if family != "PRIVATE_FOUNDATION":
                raise CommandError("the STEERING interim exists for PRIVATE_FOUNDATION only")
            if country not in STEERING:
                raise CommandError(
                    f"no STEERING row for {country}; countries with one: {sorted(STEERING)}"
                )
            try:
                row = steering_angle(country, now=timezone.now())
            except ValueError as error:
                raise CommandError(str(error)) from error
            self.stdout.write(f"wrote 1 STEERING angle ({row.language}): {row.query}")
            return
        vocabulary = _vocabulary()
        if vocabulary is None:
            raise CommandError(
                "no kind-word vocabulary (build item 8) -- kind words are never translated by "
                "the generator. The spec's interim is --from-steering: one angle, labelled."
            )
        languages = pass_languages(
            country, family, source=WikidataLanguages(), home_language=home
        )
        if options["dry_run"]:
            self.stdout.write(f"would generate {country}/{family} in {', '.join(languages)}")
            return
        from openai import OpenAI

        outcomes = generate_angles(
            country_code=country, family=family, languages=languages, vocabulary=vocabulary,
            parser=cast(ResponsesAPI, OpenAI().responses), now=timezone.now(),
            home_language=home, regenerate=options["regenerate"],
        )
        for language, outcome in outcomes.items():
            self.stdout.write(f"{language}: {outcome}")
