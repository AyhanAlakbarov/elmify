"""Load the closed-list registry and every hand-read list into the register.

Operator-run, idempotent, and nothing here fetches: the files were read by a
person from the publisher's page (spec 6.2, "read by hand into a versioned
file per country"). Adding a list is adding a registry row and a file, never
a command.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research import closed_lists
from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.models import ClosedList


class Command(BaseCommand):
    help = (
        "Load docs/research/closed-lists.csv and its rows files into the register."
        + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--registry", default=str(closed_lists.REGISTRY))
        parser.add_argument("--lists-dir", default=str(closed_lists.LISTS_DIR))
        parser.add_argument("--list", action="append", default=[], dest="slugs")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            count = closed_lists.load_registry(Path(options["registry"]))
        except closed_lists.ListFileError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"registry: {count} lists")
        now = timezone.now()
        lists_dir = Path(options["lists_dir"])
        specs = ClosedList.objects.order_by("slug")
        if options["slugs"]:
            specs = specs.filter(slug__in=options["slugs"])
        for spec in specs:
            path = lists_dir / f"{spec.slug}.csv"
            if not path.exists():
                continue  # an adapter-read list: VGM, EACEA, Wikidata, ROR
            try:
                report = closed_lists.record_list(
                    spec, closed_lists.read_list_file(spec, path), now=now
                )
            except closed_lists.ListFileError as error:
                raise CommandError(str(error)) from error
            fields = asdict(report)
            self.stdout.write(
                f"{spec.slug}: listed {fields['listed']}, bound {fields['bound']}, "
                f"unresolved {fields['unresolved']}, new {fields['organisations_new']}, "
                f"promoted {fields['promoted']}, rejected {fields['rejected']}"
            )
