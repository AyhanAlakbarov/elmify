"""Find each country's official programme catalogue and scholarship database.

Writes candidates to a CSV for a person to confirm (`status` stays "candidate"
until they do): `national_databases` has the two routes and why. Spends a
little: one vendor fetch per EC profile (Firecrawl, 1 credit each) and up to three
Exa searches per country (about $0.01 each).
"""

from __future__ import annotations

import csv
from typing import Any

from babel import Locale
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import national_databases as nd
from apps.research.fetch import fetch_page
from apps.research.languages import _ISO2, CldrLanguages
from apps.research.providers import SearchMeter, SearchRequest
from apps.research.providers.exa import ExaProvider

FIELDS = ("country_code", "kind", "url", "label", "route", "government_host", "found_on",
          "status", "checked_on")


def _key(name: str) -> str:
    return name.casefold().strip().removeprefix("the ")


class Command(BaseCommand):
    help = "Write candidate national programme and scholarship databases to a CSV for review."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--countries", required=True, help="comma-separated ISO2")
        parser.add_argument("--out", default="docs/research/national-study-databases.csv")
        parser.add_argument("--results", type=int, default=10, help="Exa results per query")
        parser.add_argument(
            "--deep",
            action="store_true",
            help=(
                "Search all 7 database tiers (including QUALIFICATIONS_REGISTER, "
                "SUBNATIONAL_SCHOLARSHIPS, FOUNDATION_DIRECTORIES, EXCELLENCE_GRADUATE_SCHOOLS) "
                "in both English and official local languages, even for EC profile countries."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        countries = [c.strip().upper() for c in options["countries"].split(",") if c.strip()]
        if bad := [c for c in countries if not _ISO2.match(c)]:
            raise CommandError(f"not ISO 3166-1 alpha-2 codes: {bad}")
        deep_mode = bool(options.get("deep"))
        cldr = CldrLanguages() if deep_mode else None
        names = Locale("en").territories
        index = fetch_page(nd.EC_INDEX, purpose="read", tag="national-databases")
        if not index.body:
            raise CommandError(f"the EC country-profile index did not load: {index.outcome}")
        profiles = {_key(name): url for name, url in nd.profile_links(index.body).items()}
        found: list[nd.Candidate] = []
        meter = SearchMeter()
        exa: ExaProvider | None = None
        for country in countries:
            name = names.get(country, "")
            profile = profiles.get(_key(name))
            rows: list[nd.Candidate] = []
            if profile:
                page = fetch_page(profile, purpose="read", tag="national-databases")
                rows = nd.profile_candidates(country, profile, page.body or b"")
            missing = (
                list(nd.ALL_QUERIES)
                if deep_mode
                else [k for k in nd.QUERIES if not any(r.kind == k for r in rows)]
            )
            if missing:
                if exa is None:
                    if not settings.EXA_API_KEY:
                        raise CommandError("EXA_API_KEY is not set: needed for the search route")
                    exa = ExaProvider(api_key=settings.EXA_API_KEY)
                provider = exa

                def search(query: str, country: str = country) -> list[str]:
                    request = SearchRequest(query=query, country_code=country, language="en",
                                            phrasing="english", max_results=options["results"],
                                            denylist=())
                    return list(provider.search(request, meter))

                if deep_mode and cldr is not None:
                    def search_local(query: str, lang: str, country: str = country) -> list[str]:
                        request = SearchRequest(
                            query=query,
                            country_code=country,
                            language=lang,
                            phrasing="local",
                            max_results=options["results"],
                            denylist=(),
                        )
                        return list(provider.search(request, meter))

                    rows += nd.search_deep_candidates(
                        country,
                        name or country,
                        search,
                        languages=cldr.languages(country),
                        search_local=search_local,
                        kinds=missing,
                    )
                else:
                    rows += nd.search_candidates(country, name or country, search, missing)
            found.extend(rows)
            self.stdout.write(
                f"{country} {'profile' if profile else 'search':7} "
                f"{'+search ' if profile and missing else '        '}"
                f"{sum(r.kind == nd.PROGRAMMES for r in rows):3} programme, "
                f"{sum(r.kind == nd.SCHOLARSHIPS for r in rows):3} scholarship, "
                f"{sum(r.kind == nd.INSTITUTIONS for r in rows):3} institution register"
            )
        today = timezone.now().date().isoformat()
        with open(options["out"], "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(FIELDS)
            for r in found:
                writer.writerow((r.country_code, r.kind, r.url, r.label, r.route,
                                 "yes" if r.government_host else "", r.found_on,
                                 "candidate", today))
        self.stdout.write(f"{len(found)} candidates -> {options['out']}; "
                          f"Exa spend ${meter.total():.3f}")
