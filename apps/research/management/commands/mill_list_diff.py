"""Diff the pinned Wikipedia mill list against today's revision (spec §5.4).

The list is pinned by revision in docs/research/mill-list.csv. A new or removed
entry is printed for the operator, so a vandalised edit is visible, and a
person maps any new mill to its DOMAIN in that file, then moves the revision.
Nothing here writes a row: the list is a reviewed diff, never a name match.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

from apps.research.blocking import (
    WIKIPEDIA_TITLE,
    current_revision,
    read_mill_list,
    revision_url,
    wikipedia_entries,
)
from apps.research.fetch import CATALOG_ROLE_NOTE, FetchedPage, fetch_page
from apps.research.recognition import readable_page

PAGE = f"https://en.wikipedia.org/wiki/{WIKIPEDIA_TITLE}"


def _read(url: str, label: str) -> bytes:
    fetched: FetchedPage = fetch_page(url, purpose="provenance")
    if not readable_page(fetched):
        raise CommandError(f"{label}: {fetched.outcome} {fetched.reason}")
    if urlsplit(fetched.final_url).hostname != "en.wikipedia.org":
        raise CommandError(f"{label}: landed on {fetched.final_url}, not en.wikipedia.org")
    return fetched.body


class Command(BaseCommand):
    help = (
        "Show entries added to or removed from the pinned Wikipedia mill list."
        + CATALOG_ROLE_NOTE
    )

    def handle(self, *args: Any, **options: Any) -> None:
        pinned = max(
            (row.source_revision for row in read_mill_list() if row.source == "wikipedia"), key=int
        )
        current_body = _read(PAGE, PAGE)
        current = current_revision(current_body)
        if current == pinned:
            self.stdout.write(f"unchanged at revision {pinned}")
            return
        before = wikipedia_entries(_read(revision_url(pinned), f"revision {pinned}"))
        after = wikipedia_entries(current_body)
        self.stdout.write(f"pinned {pinned}, current {current}")
        for name in sorted(after - before):
            self.stdout.write(f"+ {name}")
        for name in sorted(before - after):
            self.stdout.write(f"- {name}")
        self.stdout.write(
            "Review these names; map any new mill to its domain in docs/research/mill-list.csv "
            "and move source_revision to the new revision."
        )
