"""Write one (country, family)'s angle set -- operator-run, one call per language.

The kind words come from `kind_words.load_kind_words()`: the committed
`resolver_data/kind_words.json`, built from Wikidata by `manage.py
build_kind_words`. Where that file is absent this command refuses rather than
let the model translate "foundation" itself (lever 3), and names the one
interim the spec permits: `--from-steering`, which writes today's hand-written
STEERING query as a single labelled angle. A language the file has no word in
is reported `no_vocabulary` and not generated.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.angles import (
    PASS_SHAPES,
    generate_angles,
    openrouter_parser,
    steering_angle,
)
from apps.research.domains import STEERING
from apps.research.kind_words import load_kind_words
from apps.research.languages import _ISO2, CldrLanguages, home_language, pass_languages


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
        vocabulary = load_kind_words()
        if vocabulary is None:
            raise CommandError(
                "no kind-word vocabulary: run manage.py build_kind_words -- kind words are never "
                "translated by the generator. The spec's interim is --from-steering: one angle, "
                "labelled."
            )
        languages = pass_languages(
            country, family, source=CldrLanguages(), home_language=home
        )
        if options["dry_run"]:
            self.stdout.write(f"would generate {country}/{family} in {', '.join(languages)}")
            return
        outcomes = generate_angles(
            country_code=country, family=family, languages=languages, vocabulary=vocabulary,
            parser=openrouter_parser(),
            now=timezone.now(),
            home_language=home, regenerate=options["regenerate"],
        )
        for language, outcome in outcomes.items():
            self.stdout.write(f"{language}: {outcome}")
