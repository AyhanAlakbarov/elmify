"""Pointers become leads (government funding spec 2026-09-27 §4.7).

A funding page that names another body's money yields a `PointerLead`: the
line, the award's label and -- copied from the line -- the body's own name.
Each is kept as a row of the `pointer` register, so the resolver that already
reads every other register reads these too (`manage.py resolve_register
--register pointer`), a person answers the ones it cannot place (SITE_UNKNOWN),
and a body it places is read like any other funder (`manage.py read_pointers`).

A pointer is a NAME, never provenance: nothing here trusts a URL printed in
page text, and the row it becomes vouches for nothing but "a page said this".
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from django.utils import timezone

from .discovery import DiscoveryQuery, ResearchLead
from .funding_judge import PointerLead
from .funding_reader import FAMILY_BY_HOLDER
from .hosts import registrable_domain
from .models import (
    Organisation,
    OrganisationDomain,
    RegisterEntry,
    ResolutionItem,
    UnresolvedReason,
)
from .names import fold
from .resolution.writers import file_site_unknown

if TYPE_CHECKING:
    from .resolver import Resolution

#: The register slug every pointer row is kept under.
POINTER_REGISTER = "pointer"


def _country(page_url: str, fallback: str) -> str:
    """Where the naming page's own body is, else the run's country: the name is
    written in that page's language, and the resolver reads a name with its
    country's vocabulary."""
    domain = registrable_domain(page_url)
    known = (
        OrganisationDomain.objects.filter(registrable_domain=domain)
        .values_list("organisation__country_code", flat=True)
        .first()
        if domain
        else None
    )
    return str(known) if known else fallback


def record_pointers(
    pointers: Iterable[PointerLead],
    *,
    page_url: str,
    fallback_country: str,
    now: datetime | None = None,
) -> int:
    """One `pointer` register row per body named; returns how many are new.

    Keyed by the folded name, so one body named on fifty pages is one row.
    The first sighting's quote and page are kept; a later one only moves
    `last_seen`, and never reopens a row a person or the resolver answered.
    """
    at = now or timezone.now()
    country = _country(page_url, fallback_country)
    created = 0
    for pointer in pointers:
        names = list(dict.fromkeys(
            name.strip()[:300] for name in (pointer.funder, pointer.name) if name.strip()
        ))
        key = fold(names[0])[:120] if names else ""
        if not key:
            continue
        entry, new = RegisterEntry.objects.get_or_create(
            register=POINTER_REGISTER,
            external_key=key,
            defaults={
                "name": names[0],
                "names": names,
                "country_code": country,
                "kind": pointer.holder,
                "resolution": RegisterEntry.Resolution.UNRESOLVED,
                "last_seen": at,
                "pointer_quote": pointer.quote[:300],
                "pointer_url": page_url[:2048],
            },
        )
        if not new:
            RegisterEntry.objects.filter(pk=entry.pk).update(last_seen=at)
        created += int(new)
    return created


def pointer_route(entry: RegisterEntry) -> str:
    """`POINTER:<naming host>` for a pointer row -- the route tag
    `closed_lists.has_signal` already reads -- and "" for any other register."""
    if entry.register != POINTER_REGISTER:
        return ""
    host = (urlsplit(entry.pointer_url).hostname or "unknown").lower()
    return f"POINTER:{host}"[:120]


def ask_for_site(entry: RegisterEntry, resolution: Resolution) -> ResolutionItem | None:
    """SITE_UNKNOWN for a pointer the resolver could not place, for good.

    None for any other register (that is the resolution queue plan's call, not
    this one's), for a placed pointer, and for a fetch failure -- the resolver
    retries that after a week (`resolve_entries.FETCH_RETRY_AFTER`), and a
    person asked now would be answering its transient problem.
    """
    if entry.register != POINTER_REGISTER or resolution.domain:
        return None
    if resolution.reason == UnresolvedReason.FETCH_FAILED:
        return None
    host = urlsplit(entry.pointer_url).hostname or "another body's page"
    return file_site_unknown(
        entry,
        names=resolution.names or tuple(entry.names or [entry.name]),
        why=f'named on {host}: "{entry.pointer_quote}"',
    )


@dataclass(frozen=True)
class PointerSource:
    """Placed pointers as FUNDER leads -- a `LeadSource` (spec 2026-09-27 4.7).

    One lead per body, its homepage, most recently named first. Ignores
    `query.country_code`, like `ClosedListSource`: a pointer is scoped by the
    page that named it, not by the run. Reading the body's other funding pages
    is spec 4.2's site reading (plan 2); the reader already finds a homepage's
    funding lines.
    """

    one_programme_per_link: bool = False
    awards_jointly: bool = False

    @property
    def name(self) -> str:
        return POINTER_REGISTER

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        entries = (
            RegisterEntry.objects.filter(
                register=POINTER_REGISTER,
                resolution=RegisterEntry.Resolution.RESOLVED,
                organisation__isnull=False,
            )
            .exclude(organisation__status=Organisation.Status.REJECTED)
            .select_related("organisation")
            .order_by("-last_seen", "external_key")
        )
        seen: set[UUID] = set()
        for entry in entries:
            org = entry.organisation
            assert org is not None  # filtered above; for mypy
            if org.pk in seen:
                continue
            seen.add(org.pk)
            yield ResearchLead.from_url(
                org.official_website or f"https://{org.primary_domain}/",
                source_type="FUNDER",
                funding_family=FAMILY_BY_HOLDER.get(entry.kind or org.kind, ""),
                discovered_by=pointer_route(entry),
            )
