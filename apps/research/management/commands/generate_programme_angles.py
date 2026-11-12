"""Write the programme query templates for one or more languages -- operator-run."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.research.angles import openrouter_parser
from apps.research.models import ProgrammeAngle
from apps.research.programme_angles import generate_programme_angles


class Command(BaseCommand):
    help = "Generate programme query templates (PROGRAMME / MONEY / RECENCY) per language."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--language", action="append", required=True)
        parser.add_argument("--regenerate", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        languages = options["language"]
        if options["dry_run"]:
            self.stdout.write(f"would generate programme templates in {', '.join(languages)}")
            return
        parser = openrouter_parser()
        for language in languages:
            outcome = generate_programme_angles(
                language=language, parser=parser, now=timezone.now(),
                regenerate=options["regenerate"],
            )
            self.stdout.write(f"{language}: {outcome}")
            rows = ProgrammeAngle.objects.filter(
                level="MASTER", language=language, retired_at__isnull=True
            ).order_by("kind", "sample")
            for row in rows:
                self.stdout.write(f"{row.kind} {row.sample}: {row.template}")
