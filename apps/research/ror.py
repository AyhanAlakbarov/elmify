"""ROR v2 as an enumerator -- gated (spec 6.2's ROR row).

CC0. Used two ways only: an exact `domains:` lookup, and a country x type
enumeration. Never a name lookup's top hit -- "the fuzzy top hit is sometimes
a different organisation" (spec 6.2) -- so the name half of the gate below
measures ROR's matching for item 8's resolver and nothing here uses it.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from .egress import SourceBlocked, fetch_json_api
from .hosts import registrable_domain

ENDPOINT = "https://api.ror.org/v2/organizations"
_PASS_SHARE = 0.95

Call = Callable[..., dict[str, object]]


def _headers() -> dict[str, str]:
    return {"Client-Id": settings.ROR_CLIENT_ID} if settings.ROR_CLIENT_ID else {}


def _items(body: dict[str, object]) -> list[dict[str, object]]:
    items = body.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def by_domain(domain: str, *, call: Call = fetch_json_api) -> list[dict[str, object]]:
    return _items(call(ENDPOINT, params={"query.advanced": f"domains:{domain}"},
                       headers=_headers()))


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def website_domain(record: dict[str, object]) -> str:
    for link in _list(record.get("links")):
        if isinstance(link, dict) and link.get("type") == "website" and link.get("value"):
            return registrable_domain(str(link["value"]))
    domains = _list(record.get("domains"))
    return registrable_domain(str(domains[0])) if domains else ""


def website_link_domain(record: dict[str, object]) -> str:
    """The `website` link only -- what the gate grades. `domains` is what the
    record was FOUND by, so falling back to it would count every record
    without a website as agreeing with its own query."""
    for link in _list(record.get("links")):
        if isinstance(link, dict) and link.get("type") == "website" and link.get("value"):
            return registrable_domain(str(link["value"]))
    return ""


def all_names(record: dict[str, object]) -> tuple[str, ...]:
    return tuple(
        str(name["value"]) for name in _list(record.get("names"))
        if isinstance(name, dict) and name.get("value")
    )


@dataclass(frozen=True)
class RorGate:
    hosts: int
    known: int
    website_match: int
    names: int
    name_known: int
    exact_name: int
    #: Of the names ROR chose a record for, how many carry the website we
    #: know is the body's -- the number item 8's resolver needs. Not gated.
    name_website_match: int = 0

    @property
    def passed(self) -> bool:
        return self.known > 0 and self.website_match >= _PASS_SHARE * self.known


def ror_gate(
    hosts: list[str], names: list[tuple[str, str]], *, call: Call = fetch_json_api
) -> RorGate:
    known = matched = 0
    for host in hosts:
        records = by_domain(host, call=call)
        if records:
            known += 1
            matched += website_link_domain(records[0]) == host
    name_known = exact = name_site = 0
    for name, domain in names:
        body = call(ENDPOINT, params={"affiliation": name}, headers=_headers())
        chosen = [
            organization for item in _items(body)
            if item.get("chosen") and isinstance(organization := item.get("organization"), dict)
        ]
        if chosen:
            name_known += 1
            exact += name.casefold() in {label.casefold() for label in all_names(chosen[0])}
            name_site += website_domain(chosen[0]) == domain
    return RorGate(len(hosts), known, matched, len(names), name_known, exact, name_site)


@dataclass(frozen=True)
class RorFacts:
    """What ROR says about one domain, and only when a record's `domains[]` or
    `links[website]` IS that domain (spec §5.2 rule 2). Identity, never
    legitimacy: 7 of 13 unaccredited-list institutions are active ROR records.

    Two measured limits, neither fixed by this code (preflight m4):
    (1) `by_domain` queries `domains:<d>`, so a record whose `domains[]`
    differs from its own website (ESMT: esmt.org vs esmt.berlin) is never
    RETURNED for a lookup on the website domain -- the `links[website]`
    comparison below only ever fires against a record ROR's own domain query
    already found some other way, never live on esmt.berlin itself; (2) no
    shipped register has `id_scheme=WIKIDATA`, so `ror_recognitions` binds
    nothing today. Do not count ROR toward any known answer."""

    country_code: str = ""
    identifiers: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    lookup_failed: bool = False


#: ROR external-id types that name one of OrganisationIdentifier.SCHEMES.
_EXTERNAL_SCHEMES = {"wikidata": "WIKIDATA"}


def _country(record: dict[str, object]) -> str:
    for location in _list(record.get("locations")):
        if isinstance(location, dict) and isinstance(
            details := location.get("geonames_details"), dict
        ):
            return str(details.get("country_code") or "").upper()
    return ""


def ror_facts(domain: str, *, call: Call = fetch_json_api) -> RorFacts:
    """See `RorFacts`'s docstring for the two measured limits on this lookup
    (preflight m4) -- neither is fixed by this function."""
    try:
        records = by_domain(domain, call=call)
    except (SourceBlocked, ValueError):
        return RorFacts(lookup_failed=True)
    for record in records:
        domains = {registrable_domain(str(value)) for value in _list(record.get("domains"))}
        if domain not in domains | {website_link_domain(record)}:
            continue
        identifiers: set[tuple[str, str]] = set()
        if record.get("id"):
            identifiers.add(("ROR", str(record["id"]).rstrip("/").rsplit("/", 1)[-1]))
        for external in _list(record.get("external_ids")):
            if isinstance(external, dict) and (
                scheme := _EXTERNAL_SCHEMES.get(str(external.get("type")))
            ):
                identifiers |= {(scheme, str(value)) for value in _list(external.get("all"))}
        return RorFacts(country_code=_country(record), identifiers=frozenset(identifiers))
    return RorFacts()


def read_hosts(path: Path) -> list[str]:
    return [
        line.split("\t")[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def read_names(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [(row["name"], row["domain"]) for row in csv.DictReader(handle)]
