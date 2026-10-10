"""Run one (host country, family) sweep pass and print its curve.

Operator-run. The register ladder runs first (spec 6.2): the rung is read
from the register survey (`ClosedList`, loaded from
`docs/research/closed-lists.csv`), never a flag -- `ladder_rung` picks the
lowest rung listing a kind this pass searches for (ruling R12), and refuses a
rung below 4 whose register that survey has not read (spec 6.7, ruling R6). Angles come
from `generate_sweep_angles`; languages from Wikidata P37 plus English, or
`--language` to pin them for a measurement. A diaspora pass is keyed (host
country, home language): it takes exactly one `--home-language` and runs in
it, then English (decision 37).

Novel hosts are classified in-pass (spec 6.6) because the stop rule counts
VERIFIED hosts; that is the only fetch a sweep makes.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.angles import PASS_SHAPES, cycle_label
from apps.research.classify import FrontierClassifier, classify_organisation
from apps.research.extraction import ResponsesAPI
from apps.research.fetch import SweepBudget
from apps.research.harness import PassConfig, ladder_rung, run_pass
from apps.research.languages import (
    _ISO2,
    _LANG,
    MAX_LANGUAGE_LEN,
    WikidataLanguages,
    home_language,
    ordered_languages,
    pass_languages,
)
from apps.research.models import Organisation, SweepDiscovery
from apps.research.providers import SearchProvider
from apps.research.providers.brave import BraveProvider
from apps.research.providers.exa import ExaProvider


class Command(BaseCommand):
    help = "Sweep one (host country, family) for funder hosts the register does not hold."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", required=True, help="ISO-3166 alpha-2 host country")
        parser.add_argument("--family", required=True, choices=sorted(PASS_SHAPES))
        parser.add_argument(
            "--home-language", action="append", default=[],
            help="The one home language of an AFFINITY_OR_DIASPORA pass; refused for any other",
        )
        parser.add_argument(
            "--language", action="append", default=[],
            help="Pin the language loop (measurement only); default is Wikidata P37 + en",
        )
        parser.add_argument("--budget-usd", type=float, default=None)
        parser.add_argument("--firecrawl-credits", type=int, default=300)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        # Refused before any query: both end up in angle and run keys.
        country, family = options["country"].upper(), options["family"]
        if not _ISO2.match(country):
            raise CommandError(f"not an ISO 3166-1 alpha-2 code: {options['country']!r}")
        options["language"] = [code.lower() for code in options["language"]]
        if long := [code for code in options["language"] if len(code) > MAX_LANGUAGE_LEN]:
            raise CommandError(f"language code longer than {MAX_LANGUAGE_LEN} characters: {long}")
        if bad := [code for code in options["language"] if not _LANG.match(code)]:
            raise CommandError(f"not a language code: {bad}")
        try:
            home = home_language(family, options["home_language"])
        except ValueError as error:
            raise CommandError(str(error)) from error

        providers: list[SearchProvider] = []
        if settings.EXA_API_KEY:
            providers.append(ExaProvider(api_key=settings.EXA_API_KEY))
        if settings.BRAVE_API_KEY:
            providers.append(BraveProvider(api_key=settings.BRAVE_API_KEY))
        # Tavily is not a discovery provider (roster: resolution and /map);
        # it decayed 62 -> 5 first-discoverers across 99 queries.
        if not providers:
            raise CommandError("no provider key is set: EXA_API_KEY, BRAVE_API_KEY")

        try:
            rung, register = ladder_rung(country, family)
        except ValueError as error:
            raise CommandError(str(error)) from error
        if options["language"]:
            languages = ordered_languages(options["language"])
        else:
            try:
                languages = pass_languages(
                    country, family, source=WikidataLanguages(), home_language=home,
                )
            except ValueError as error:
                raise CommandError(str(error)) from error

        names = ", ".join(p.name for p in providers)
        key = f"{country}/{family}" + (f"/{home}" if home else "")
        if options["dry_run"]:
            self.stdout.write(
                f"would sweep {key} rung {rung} in {', '.join(languages)} with: {names}"
            )
            return

        from openai import OpenAI

        classifier = FrontierClassifier(cast(ResponsesAPI, OpenAI().responses))
        fetch_budget = SweepBudget({
            **settings.FETCH_SWEEP_CREDITS, "FIRECRAWL": options["firecrawl_credits"],
        })
        run_id, now = uuid4(), timezone.now()

        def classify(org: Organisation) -> str:
            return classify_organisation(
                org, classifier=classifier, run_id=run_id, budget=fetch_budget, now=now
            )

        try:
            budget_usd = (
                options["budget_usd"]
                if options["budget_usd"] is not None
                else settings.SWEEP_PASS_BUDGET_USD
            )
            run = run_pass(
                PassConfig(
                    country_code=country, family=family, languages=languages, rung=rung,
                    register=register, cycle=cycle_label(now), budget_usd=budget_usd,
                    home_language=home,
                ),
                providers=providers, classify=classify, fetch_budget=fetch_budget, now=now,
            )
        except ValueError as error:
            raise CommandError(str(error)) from error

        discoveries = SweepDiscovery.objects.filter(run=run)
        novel = discoveries.count()
        verified = discoveries.filter(verified_in_pass=True).count()
        precision = f"{verified / novel:.2%}" if novel else "n/a"
        self.stdout.write(f"run: {run.id}")
        self.stdout.write(f"stopped: {run.stop_reason} after {run.batches} batches")
        self.stdout.write(f"languages: {', '.join(run.languages)}; providers: {names}")
        self.stdout.write(f"dropped providers: {run.dropped_providers or 'none'}")
        self.stdout.write(f"novel hosts: {novel}; new verified: {verified}")
        self.stdout.write(f"precision (verified / novel): {precision}")
        self.stdout.write(
            f"against the register ({register or 'none -- rung 4'}): "
            f"recaptured {run.recaptured}, verified outside it {verified}"
        )
        self.stdout.write(f"spend: search ${run.search_usd:.4f}, fetch ${run.fetch_usd:.4f}")
        self.stdout.write("tallies: manage.py sweep_tally --country ... --family ...")
