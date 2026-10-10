"""Closed lists as data (spec 6.2's closed-list engine).

A closed list is a finite set of bodies that a publisher -- a regulator, a
ministry, or we ourselves compiling from each body's own page -- names in
full. Its size is the denominator the coverage line divides by, so the list
lives in files a person reviews as a diff, never in code:

- ``docs/research/closed-lists.csv`` -- one sourced row per list;
- ``docs/research/closed-lists/<slug>.csv`` -- the rows of a list read by
  hand: a register with no API -- or, before the owner decision of 2026-09-27
  that reuse terms are recorded and never a gate, one whose terms nobody had
  read (spec 14) -- or a list we compiled because nobody publishes one (the intergovernmental
  bodies, spec 19). Azerbaijan's institutions come from the ministry's list;
  TKTA publishes two NEGATIVE lists as JSON (not recognised; high refusal)
  and still no list of recognised institutions (provenance gate spec §9.6).
  An adapter-read list (VGM, EACEA,
  Wikidata, ROR) has a registry row and no rows file.

A curated list promotes what it names to REGISTERED -- spec 6.1: "a national
register, DEQAR or a curated national file vouched for the domain" -- and
`record_list` is the only code that does, which is why no Wikidata, ROR or
EACEA row passes through it.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
sections 6.1, 6.2, 16 item 7.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from django.db import transaction

from apps.funding.models import _HOLDER_VALUES
from apps.funding.regions import REGIONS

from .discovery import DiscoveryQuery, ResearchLead, canonicalize_url
from .funding_reader import _FAMILY_BY_HOLDER
from .hosts import registrable_domain
from .models import (
    ClosedList,
    Organisation,
    OrganisationDomain,
    RegisterEntry,
    ResolvedVia,
    refreshed_resolution,
)
from .register import record_organisation

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "docs" / "research"
REGISTRY = DATA_DIR / "closed-lists.csv"
LISTS_DIR = DATA_DIR / "closed-lists"

_REGISTRY_COLUMNS = (
    "slug", "title", "country_code", "holder_kinds", "rung", "source_url", "maintainer",
    "carries_purpose", "carries_website", "reuse_terms", "reuse_terms_url",
    "is_denominator", "read_policy", "printed_size", "verified_on",
)
_LIST_COLUMNS = (
    "external_key", "name", "kind", "website", "page_url", "country_code",
    "home_cells", "host_cells", "rejected_reason", "source_url", "verified_on", "notes",
)
_YES_NO = {"yes": True, "no": False}


class ListFileError(ValueError):
    """A list file that does not say what the loader needs, named by line."""


def valid_cell(cell: str) -> bool:
    """ANY, a `REGIONS` key, or an ISO 3166-1 alpha-2 code (upper case)."""
    return (
        cell == "ANY"
        or cell in REGIONS
        or (len(cell) == 2 and cell.isascii() and cell.isalpha() and cell.isupper())
    )


def _cells(raw: str, where: str) -> list[str]:
    tokens = [token.strip() for token in raw.split("|") if token.strip()]
    if not tokens:
        raise ListFileError(f"{where}: no cell tags (write ANY for any country)")
    unknown = [token for token in tokens if not valid_cell(token)]
    if unknown:
        raise ListFileError(f"{where}: unknown cell tags {unknown}")
    if "ANY" in tokens and len(tokens) > 1:
        raise ListFileError(f"{where}: ANY beside other tags means ANY; write ANY alone")
    return tokens


def _url(raw: str, where: str, *, required: bool) -> str:
    raw = raw.strip()
    if not raw:
        if required:
            raise ListFileError(f"{where}: required")
        return ""
    try:
        return canonicalize_url(raw)
    except ValueError as error:
        raise ListFileError(f"{where}: {error}: {raw!r}") from error


def _day(raw: str, where: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as error:
        raise ListFileError(f"{where}: not an ISO date: {raw!r}") from error


def _int(raw: str, where: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as error:
        raise ListFileError(f"{where}: not a whole number: {raw!r}") from error


def _flag(raw: str, where: str) -> bool:
    try:
        return _YES_NO[raw.strip().lower()]
    except KeyError as error:
        raise ListFileError(f"{where}: yes or no, not {raw!r}") from error


def _rows_of(path: Path, columns: tuple[str, ...]) -> Iterator[tuple[str, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ListFileError(f"{path.name}: columns {reader.fieldnames} are not {columns}")
        for line, row in enumerate(reader, start=2):
            yield f"{path.name}:{line}", {key: (value or "") for key, value in row.items()}


def read_registry(path: Path = REGISTRY) -> tuple[dict[str, object], ...]:
    """Every registry row as `ClosedList` field values, validated."""
    specs: list[dict[str, object]] = []
    seen: set[str] = set()
    for where, row in _rows_of(path, _REGISTRY_COLUMNS):
        slug = row["slug"].strip()
        if not slug or slug in seen or len(slug) > 40:
            raise ListFileError(f"{where}: slug missing, repeated or over 40 characters: {slug!r}")
        seen.add(slug)
        kinds = [kind for kind in row["holder_kinds"].split("|") if kind]
        if any(kind not in _HOLDER_VALUES for kind in kinds):
            raise ListFileError(f"{where}: holder_kinds {kinds} outside the holder vocabulary")
        rung = _int(row["rung"], f"{where} rung")
        if not 0 <= rung <= 4:
            raise ListFileError(f"{where}: rung {rung} is not 0-4")
        if row["reuse_terms"] not in ClosedList.Terms.values:
            raise ListFileError(f"{where}: reuse_terms {row['reuse_terms']!r}")
        if row["read_policy"] not in ClosedList.ReadPolicy.values:
            raise ListFileError(f"{where}: read_policy {row['read_policy']!r}")
        country = row["country_code"].strip().upper()
        if country and (country == "ANY" or country in REGIONS or not valid_cell(country)):
            raise ListFileError(f"{where}: country_code {country!r} is not ISO alpha-2")
        specs.append({
            "slug": slug,
            "title": row["title"].strip(),
            "country_code": country,
            "holder_kinds": kinds,
            "rung": rung,
            "source_url": _url(row["source_url"], f"{where} source_url", required=True),
            "maintainer": row["maintainer"].strip(),
            "carries_purpose": _flag(row["carries_purpose"], f"{where} carries_purpose"),
            "carries_website": _flag(row["carries_website"], f"{where} carries_website"),
            "reuse_terms": row["reuse_terms"],
            "reuse_terms_url": _url(row["reuse_terms_url"], f"{where} reuse_terms_url",
                                    required=False),
            "is_denominator": _flag(row["is_denominator"], f"{where} is_denominator"),
            "read_policy": row["read_policy"],
            "printed_size": (
                _int(row["printed_size"], f"{where} printed_size")
                if row["printed_size"].strip() else None
            ),
            "verified_on": _day(row["verified_on"], f"{where} verified_on"),
        })
    return tuple(specs)


def load_registry(path: Path = REGISTRY) -> int:
    """Write every registry row. A row an adapter maintains keeps the
    `printed_size` its adapter measured (EACEA sets it from the API's own
    totals); a blank in the file never erases a measured count."""
    specs = read_registry(path)
    for spec in specs:
        slug = str(spec.pop("slug"))
        if spec["printed_size"] is None:
            spec.pop("printed_size")
        ClosedList.objects.update_or_create(slug=slug, defaults=spec)
    return len(specs)


@dataclass(frozen=True)
class ListRow:
    external_key: str
    name: str
    kind: str
    website: str
    page_url: str
    country_code: str
    home_cells: tuple[str, ...]
    host_cells: tuple[str, ...]
    rejected_reason: str
    source_url: str
    verified_on: date


def read_list_file(spec: ClosedList, path: Path | None = None) -> tuple[ListRow, ...]:
    """Every row of one hand-read list, validated against its registry row."""
    path = path or LISTS_DIR / f"{spec.slug}.csv"
    rows: list[ListRow] = []
    keys: set[str] = set()
    for where, raw in _rows_of(path, _LIST_COLUMNS):
        if any("@" in value for value in raw.values()):
            # A mailbox is a person's or an office's, and a committed file is
            # storage (the 6a plan's rule). Rung 0 reads e-mails from registers
            # at run time and keeps only the domain; a file keeps the website.
            raise ListFileError(f"{where}: an e-mail address; store the website instead")
        key = raw["external_key"].strip()
        if not key or key in keys or len(key) > 120:
            raise ListFileError(f"{where}: external_key missing, repeated or too long: {key!r}")
        keys.add(key)
        name = raw["name"].strip()
        if not name:
            raise ListFileError(f"{where}: name missing")
        kind = raw["kind"].strip()
        if kind not in _HOLDER_VALUES:
            raise ListFileError(f"{where}: kind {kind!r} outside the holder vocabulary")
        if spec.holder_kinds and kind not in spec.holder_kinds:
            raise ListFileError(f"{where}: kind {kind} is not one {spec.slug} covers")
        rejected = raw["rejected_reason"].strip()
        if rejected and rejected not in Organisation.RejectedReason.values:
            raise ListFileError(f"{where}: rejected_reason {rejected!r}")
        # A body whose own site cannot be established is kept with a blank
        # website -- it stays UNRESOLVED, counts in the denominator and reads
        # UNBOUND until the resolver (build item 8) finds it; guessing a domain
        # from a name is the error this avoids. A REJECTED row is the opposite
        # case: the body is recorded dead or out of scope, which needs a body
        # to record it on, so its website is required.
        website = _url(raw["website"], f"{where} website", required=bool(rejected))
        page_url = _url(
            raw["page_url"], f"{where} page_url",
            required=spec.read_policy == ClosedList.ReadPolicy.FUNDING_READ and not rejected,
        )
        if page_url and website and registrable_domain(page_url) != registrable_domain(website):
            # The origin is the only evidence (spec 3.2): a scheme page on
            # another host is that host's page, and reading it for this body
            # would write the wrong holder.
            raise ListFileError(f"{where}: page_url is not on the body's own site ({website})")
        country = raw["country_code"].strip().upper()
        if country and (country == "ANY" or country in REGIONS or not valid_cell(country)):
            raise ListFileError(f"{where}: country_code {country!r} is not ISO alpha-2")
        rows.append(ListRow(
            external_key=key, name=name, kind=kind, website=website, page_url=page_url,
            country_code=country,
            home_cells=tuple(_cells(raw["home_cells"], f"{where} home_cells")),
            host_cells=tuple(_cells(raw["host_cells"], f"{where} host_cells")),
            rejected_reason=rejected,
            source_url=_url(raw["source_url"], f"{where} source_url", required=True),
            verified_on=_day(raw["verified_on"], f"{where} verified_on"),
        ))
    return tuple(rows)


@dataclass(frozen=True)
class ListReport:
    listed: int = 0
    bound: int = 0
    unresolved: int = 0
    organisations_new: int = 0
    promoted: int = 0
    rejected: int = 0


def record_list(spec: ClosedList, rows: Iterable[ListRow], *, now: datetime) -> ListReport:
    """Write a hand-read list's rows and bind each to its body by website.

    A row with a website is RESOLVED/LISTED. A blank-website row is the
    resolver's queue (build item 8, served by resolve_register), so a re-read
    never undoes what the resolver bound there (`resolver_decided`); it is
    still counted `unresolved` here, which means "this list did not bind it".
    A row a person answered in the resolution queue -- bound HUMAN or REFUSED
    -- is kept whole even when the list now carries a website for it
    (`person_decided`), and is counted `unresolved` for the same reason.
    """
    listed = bound = unresolved = new = promoted = rejected = 0
    tag = f"R{spec.rung}_LIST:{spec.slug}"
    vouched = (
        Organisation.Status.REGISTERED if spec.is_denominator
        else Organisation.Status.CANDIDATE
    )
    for row in rows:
        listed += 1
        domain = registrable_domain(row.website) if row.website else ""
        with transaction.atomic():
            stored = RegisterEntry.objects.filter(
                register=spec.slug, external_key=row.external_key
            ).values_list("name", "resolution", "resolved_via").first()
            renamed = stored is not None and stored[0] != row.name
            # Precedence: a person's answer (item 12) > the list's own
            # website > the resolver's earlier binding > withdrawn.
            fields, kept = refreshed_resolution(stored, row.name, domain, ResolvedVia.LISTED)
            refreshed: dict[str, object] = {
                "name": row.name, "kind": row.kind, "country_code": row.country_code,
                "page_url": row.page_url, "home_cells": list(row.home_cells),
                "host_cells": list(row.host_cells), "last_seen": now,
                # The domain this row binds by -- a verdict's domain,
                # and what origin verification must match (spec §13.8).
                "website_domain": domain, "website_url": row.website if domain else "",
            }
            refreshed |= fields
            if renamed and not kept:
                # The resolver answered for the OLD name: a renamed row starts
                # over as never tried, with the list's new name first.
                # Its origin was confirmed for the old name, not this one.
                refreshed |= {
                    "names": [row.name], "unresolved_reason": "",
                    "resolution_attempted_at": None,
                    "origin_verified_domain": "", "origin_verified_at": None,
                }
            entry, _ = RegisterEntry.objects.update_or_create(
                register=spec.slug,
                external_key=row.external_key,
                defaults=refreshed,
                create_defaults={**refreshed, "names": [row.name]},
            )
            if kept or not domain:
                # "unresolved" counts rows THIS LIST did not bind -- a
                # person-decided row included, whatever it is bound to.
                unresolved += 1
                continue
            existed = OrganisationDomain.objects.filter(registrable_domain=domain).exists()
            org = record_organisation(
                domain=domain, name=row.name, names=(row.name,), kind=row.kind,
                country_code=row.country_code, found_via=tag,
                status=Organisation.Status.REJECTED if row.rejected_reason else vouched,
                rejected_reason=row.rejected_reason,
            )
            if _promote(org, row, vouches=spec.is_denominator):
                promoted += 1
            if entry.organisation_id != org.pk:
                entry.organisation = org
                entry.save(update_fields=["organisation"])
        bound += 1
        new += not existed
        rejected += org.status == Organisation.Status.REJECTED
    return ListReport(listed, bound, unresolved, new, promoted, rejected)


def _promote(org: Organisation, row: ListRow, *, vouches: bool) -> bool:
    """A body another route found first, now named by a list that vouches.

    Only upward: CANDIDATE -> REGISTERED, UNSTATED -> the list's kind, a blank
    country -> the list's. A REJECTED body stays rejected and is logged -- a
    list naming it does not undo whatever found it dead or infrastructure.
    Returns whether the status moved.
    """
    if not vouches or row.rejected_reason:
        return False
    if org.status == Organisation.Status.REJECTED:
        logger.warning(
            "closed list names %s, which is REJECTED (%s); left as it is",
            org.primary_domain, org.rejected_reason,
        )
        return False
    changed: list[str] = []
    if org.status == Organisation.Status.CANDIDATE:
        org.status = Organisation.Status.REGISTERED
        changed.append("status")
    if org.kind == "UNSTATED" and row.kind != "UNSTATED":
        org.kind = row.kind
        changed.append("kind")
    if not org.country_code and row.country_code:
        org.country_code = row.country_code
        changed.append("country_code")
    if changed:
        org.save(update_fields=changed)
    return "status" in changed


def has_signal(org: Organisation) -> bool:
    """The cheap positive signal a SIGNAL_ONLY body needs before it is read
    (spec 6.3): another funder's page named it. The domain-restricted Exa call
    is the other signal and belongs to spec 6.4a, not to this module."""
    return any(tag.startswith("POINTER:") for tag in org.found_via)


@dataclass(frozen=True)
class ClosedListSource:
    """A list's scheme pages as FUNDER leads -- a `LeadSource`.

    Ignores `query.country_code` on purpose: a list is already scoped by its
    registry row, the intergovernmental list belongs to no country (spec 19),
    and filtering it by the run's country is the corridor-sizing that list
    exists to avoid.
    """

    slug: str
    one_programme_per_link: bool = False
    awards_jointly: bool = False

    @property
    def name(self) -> str:
        return f"closed-list:{self.slug}"

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        policy = ClosedList.objects.values_list("read_policy", flat=True).get(slug=self.slug)
        if policy not in (ClosedList.ReadPolicy.FUNDING_READ, ClosedList.ReadPolicy.SIGNAL_ONLY):
            return
        entries = (
            RegisterEntry.objects.filter(register=self.slug, organisation__isnull=False)
            .exclude(page_url="")
            .exclude(organisation__status=Organisation.Status.REJECTED)
            .select_related("organisation")
            .order_by("external_key")
        )
        for entry in entries:
            assert entry.organisation is not None  # filtered above; for mypy
            if policy == ClosedList.ReadPolicy.SIGNAL_ONLY and not has_signal(entry.organisation):
                continue
            yield ResearchLead.from_url(
                entry.page_url,
                source_type="FUNDER",
                funding_family=_FAMILY_BY_HOLDER.get(entry.kind or entry.organisation.kind, ""),
                discovered_by=self.name,
            )
