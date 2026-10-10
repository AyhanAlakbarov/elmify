"""Enumerate docs/research/wikidata-enumerations.csv into the register (CANDIDATE only)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import wikidata
from apps.research.egress import SourceBlocked
from apps.research.fetch import CATALOG_ROLE_NOTE


class Command(BaseCommand):
    help = "Enumerate Wikidata class x country x P856 into the register." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--slug", action="append", default=[], dest="slugs")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        now, failed = timezone.now(), []
        for row in wikidata.read_enumerations():
            if options["slugs"] and row.slug not in options["slugs"]:
                continue
            try:
                items = wikidata.fetch_items(row)
            except (wikidata.EnumerationShape, SourceBlocked) as error:
                self.stderr.write(f"{row.slug}: {error}")
                failed.append(row.slug)
                continue
            if options["dry_run"]:
                self.stdout.write(f"{row.slug}: items {len(items)} (dry run, nothing written)")
                continue
            report = wikidata.record_items(row, items, now=now)
            self.stdout.write(
                f"{row.slug}: items {report.listed}, bound {report.bound}, "
                f"conflicts {report.conflicts}, unkeyable {report.unkeyable}"
            )
        if failed:
            raise CommandError(f"failed: {', '.join(failed)}")
