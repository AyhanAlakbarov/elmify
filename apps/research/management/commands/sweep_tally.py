"""Print the cumulative sweep tallies; optionally retire dead angles.

Operator-run and read-only unless --retire-dead: a tally is reported, and a
retirement is a recorded decision with its numbers in `retired_reason`.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.languages import home_language
from apps.research.models import SweepAngle
from apps.research.tally import (
    angle_yield,
    found_by,
    language_yield,
    retire_dead_angles,
)


class Command(BaseCommand):
    help = "Cumulative sweep tallies by (family, provider), angle and language."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--country", required=True)
        parser.add_argument("--family", required=True)
        parser.add_argument("--home-language", action="append", default=[])
        parser.add_argument("--retire-dead", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        country, family = options["country"].upper(), options["family"]
        try:
            home = home_language(family, options["home_language"])
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write("novel hosts found (classified family, provider):")
        for (fam, provider), count in sorted(found_by(country_code=country).items()):
            self.stdout.write(f"  {fam:<28} {provider:<10} {count}")
        self.stdout.write("per language (asks, verified):")
        for language, (asks, verified) in sorted(language_yield(country, family, home).items()):
            self.stdout.write(f"  {language:<6} {asks:>5} {verified:>5}")
        self.stdout.write("per angle (asks, verified):")
        names = {
            a.pk: a
            for a in SweepAngle.objects.filter(
                country_code=country, family=family, home_language=home
            )
        }
        for angle_id, (asks, verified) in angle_yield(country, family, home).items():
            a = names[angle_id]
            state = "retired" if a.retired_at else "live"
            self.stdout.write(
                f"  v{a.version} {a.language} {a.angle:<12} s{a.sample} {state:<8} "
                f"{asks:>4} {verified:>4}"
            )
        if options["retire_dead"]:
            count = retire_dead_angles(
                country, family, now=timezone.now(), home_language=home
            )
            self.stdout.write(f"retired: {count}")
