"""Confirm each reviewed closed-list row's website (spec §13.8).

A person mapped the website, often from search with the origin never fetched
(az_heis.csv says so row by row). The row counts as admission evidence only
once its origin answered on the listed domain and named the institution.
Operator-run, idempotent; failures are printed, never swallowed.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.provenance import Reason
from apps.research.recognition import read_sources, verify_list_origins


class Command(BaseCommand):
    help = "Verify each reviewed closed-list row's website against its origin." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--list", action="append", default=[], dest="slugs")

    def handle(self, *args: Any, **options: Any) -> None:
        slugs = options["slugs"] or [
            source.slug for source in read_sources() if source.role == Reason.CURATED_LIST
        ]
        for register, key, outcome in verify_list_origins(slugs, now=timezone.now()):
            self.stdout.write(f"{register} {key}: {outcome}")
