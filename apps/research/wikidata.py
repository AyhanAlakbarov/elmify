"""Wikidata, read three ways: as an enumerator (class x country x official
website, spec 6.2), as rung 1 of name->site resolution (the entity API's P856,
spec 6.5), and as the source of the resolver's vocabulary (`sparql`, read by
`vocabulary.py`'s builders).

CC0. The enumerator writes CANDIDATE only -- crowd-sourced, it names bodies
and never vouches for them; a curated list promotes (closed_lists.py). The
resolver half writes nothing: `find_item` returns a match or None, and the
caller decides. It is still never "take the first row": `wbsearchentities` is
fuzzy, so a hit is a MATCH only when one of its labels or aliases folds to the
name exactly, it is in the right country (P17) and it is not dissolved (P576)
-- and only when exactly one item passes. Two passing items is ambiguity,
which is not evidence of either (the ROR lesson, 4.13a).

Every call carries `WIKIDATA_USER_AGENT`: Wikimedia's User-Agent policy
throttles or refuses a generic client, on the entity API as on the query
service.

Pinned, and quoted here because spec 6.2's Wikidata row requires it:
- class: `wdt:P31 wd:<class>` -- a direct instance -- unless the row says
  `widen`, which walks `wdt:P31/wdt:P279*`. Türkiye has 229 universities with
  a website under the direct class and 366 when widened (spec 6.2).
- dissolved filter: `FILTER NOT EXISTS { ?item wdt:P576 ?ended }` -- P576 is
  "dissolved, abolished or demolished date"; a body with one is not a body a
  student can apply to.
- website requirement: `wdt:P856` must exist -- the website is the key
  `record_organisation` binds on, and a row without one binds nothing.
- country: `?country wdt:P297 "<ISO2>"`, so no country QID is written anywhere.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction

from .closed_lists import DATA_DIR, valid_cell
from .domains import is_catalogue
from .egress import fetch_json_api
from .hosts import registrable_domain
from .models import (
    Organisation,
    OrganisationIdentifier,
    RegisterEntry,
    ResolvedVia,
    person_decided,
)
from .names import fold
from .register import record_organisation

ENDPOINT = "https://query.wikidata.org/sparql"
#: The entity API: `wbsearchentities` to find candidates, `wbgetentities` to
#: read their labels, aliases and claims (resolver rung 1).
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_SPARQL_TYPES = ("application/sparql-results+json", "application/json")
#: Names searched per entity; each costs one free API call per language.
_MAX_NAMES = 3
#: `wbgetentities` refuses more ids than this in one call.
_MAX_IDS = 50

Get = Callable[..., dict[str, object]]
ENUMERATIONS = DATA_DIR / "wikidata-enumerations.csv"
_ISO2 = re.compile(r"^[A-Z]{2}$")
_QID = re.compile(r"^Q[0-9]+$")
_ENTITY = "http://www.wikidata.org/entity/"
_SPARQL = """SELECT ?item ?website (SAMPLE(?en) AS ?name)
       (GROUP_CONCAT(DISTINCT ?label; separator="\\t") AS ?labels) WHERE {{
  ?country wdt:P297 "{country}" .
  ?item wdt:P31{widen} wd:{klass} ;
        wdt:P17 ?country ;
        wdt:P856 ?website .
  FILTER NOT EXISTS {{ ?item wdt:P576 ?ended }}
  OPTIONAL {{ ?item rdfs:label ?label }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en) = "en") }}
}} GROUP BY ?item ?website"""


class EnumerationShape(ValueError):
    """A count outside the row's bounds: a changed class, a dropped filter."""


@dataclass(frozen=True)
class EnumerationRow:
    slug: str
    country_code: str
    class_qid: str
    kind: str
    widen: bool
    min_count: int
    max_count: int
    home_cells: tuple[str, ...]
    host_cells: tuple[str, ...]


@dataclass(frozen=True)
class Item:
    qid: str
    name: str
    labels: tuple[str, ...]
    websites: tuple[str, ...]


@dataclass(frozen=True)
class EnumerationReport:
    listed: int = 0
    bound: int = 0
    conflicts: int = 0
    unkeyable: int = 0


def read_enumerations(path: Path = ENUMERATIONS) -> tuple[EnumerationRow, ...]:
    rows: list[EnumerationRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            home = tuple(raw["home_cells"].split("|"))
            host = tuple(raw["host_cells"].split("|"))
            if not all(valid_cell(cell) for cell in (*home, *host)):
                raise ValueError(f"{raw['slug']}: bad cell tags")
            rows.append(EnumerationRow(
                slug=raw["slug"], country_code=raw["country_code"], class_qid=raw["class_qid"],
                kind=raw["kind"], widen=raw["widen"] == "yes", min_count=int(raw["min_count"]),
                max_count=int(raw["max_count"]), home_cells=home, host_cells=host,
            ))
    return tuple(rows)


def query_text(row: EnumerationRow) -> str:
    # Our own data, but it is still interpolated into a query language: refuse
    # anything that is not exactly an ISO code and a QID.
    if not _ISO2.match(row.country_code) or not _QID.match(row.class_qid):
        raise ValueError(f"{row.slug}: country {row.country_code!r} / class {row.class_qid!r}")
    return _SPARQL.format(
        country=row.country_code, klass=row.class_qid, widen="/wdt:P279*" if row.widen else ""
    )


def _value(binding: dict[str, dict[str, str]], key: str) -> str:
    return str(binding.get(key, {}).get("value", ""))


def parse_bindings(body: dict[str, object]) -> tuple[Item, ...]:
    """One Item per QID. An item with two websites arrives as two bindings,
    and both websites are kept -- each becomes a domain of the same body."""
    results = body.get("results")
    bindings = results.get("bindings", []) if isinstance(results, dict) else []
    names: dict[str, str] = {}
    labels: dict[str, list[str]] = {}
    websites: dict[str, list[str]] = {}
    for binding in bindings:
        qid = _value(binding, "item").removeprefix(_ENTITY)
        seen_labels = labels.setdefault(qid, [])
        seen_sites = websites.setdefault(qid, [])
        site = _value(binding, "website")
        if site and site not in seen_sites:
            seen_sites.append(site)
        if not names.get(qid):
            names[qid] = _value(binding, "name")
        for label in _value(binding, "labels").split("\t"):
            if label and label not in seen_labels:
                seen_labels.append(label)
    return tuple(
        Item(
            qid=qid,
            name=names[qid] or (labels[qid] or [qid])[0],
            labels=tuple(labels[qid]),
            websites=tuple(websites[qid]),
        )
        for qid in labels
    )


def fetch_items(
    row: EnumerationRow, *, call: Callable[..., dict[str, object]] = fetch_json_api
) -> tuple[Item, ...]:
    body = _query(query_text(row), get=call)
    items = parse_bindings(body)
    if not row.min_count <= len(items) <= row.max_count:
        raise EnumerationShape(
            f"{row.slug}: {len(items)} items outside {row.min_count}-{row.max_count}"
        )
    return items


def record_items(
    row: EnumerationRow, items: tuple[Item, ...], *, now: datetime
) -> EnumerationReport:
    listed = bound = conflicts = unkeyable = 0
    for item in items:
        listed += 1
        domains = list(dict.fromkeys(
            domain for website in item.websites
            if not is_catalogue(urlsplit(website).hostname or "")
            and (domain := registrable_domain(website))
        ))
        listed_facts: dict[str, object] = {
            "name": item.name[:300], "kind": row.kind, "country_code": row.country_code,
            "home_cells": list(row.home_cells), "host_cells": list(row.host_cells),
            "last_seen": now,
        }
        stored = RegisterEntry.objects.filter(
            register=row.slug, external_key=item.qid
        ).values_list("resolution", "resolved_via").first()
        if stored is not None and person_decided(*stored):
            # A person answered this row in the resolution queue -- usually
            # the very CONFLICT below. Re-deriving it would ask them again.
            RegisterEntry.objects.filter(register=row.slug, external_key=item.qid).update(
                **listed_facts
            )
            continue
        entry, _ = RegisterEntry.objects.update_or_create(
            register=row.slug, external_key=item.qid,
            defaults={
                **listed_facts,
                # resolved_via travels with resolution in every write: a row
                # that was RESOLVED/LISTED is UNRESOLVED again until rebound
                # below, and the shape constraint refuses a route beside that.
                "resolution": RegisterEntry.Resolution.UNRESOLVED, "resolved_via": "",
            },
        )
        if not domains:
            if entry.organisation_id is not None:
                entry.organisation = None
                entry.save(update_fields=["organisation"])
            unkeyable += 1
            continue
        if OrganisationIdentifier.objects.filter(
            scheme="WIKIDATA", organisation__domains__registrable_domain__in=domains
        ).exclude(value=item.qid).exists():
            # The website's body is already a different Wikidata item. Adding
            # this QID would merge two items into one body; a person decides.
            entry.resolution, entry.resolved_via = RegisterEntry.Resolution.CONFLICT, ""
            entry.organisation = None
            entry.save(update_fields=["resolution", "resolved_via", "organisation"])
            conflicts += 1
            continue
        try:
            with transaction.atomic():
                for domain in domains:
                    org = record_organisation(
                        domain=domain, name=item.name[:300], names=item.labels, kind=row.kind,
                        country_code=row.country_code, found_via=f"WIKIDATA:{row.slug}",
                        identifiers=[("WIKIDATA", item.qid)],
                        status=Organisation.Status.CANDIDATE,
                    )
        except ValueError:
            # One QID already on another body: a question, not a merge.
            entry.resolution, entry.resolved_via = RegisterEntry.Resolution.CONFLICT, ""
            entry.organisation = None
            entry.save(update_fields=["resolution", "resolved_via", "organisation"])
            conflicts += 1
            continue
        entry.resolution, entry.resolved_via = RegisterEntry.Resolution.RESOLVED, ResolvedVia.LISTED
        entry.unresolved_reason, entry.organisation = "", org
        entry.save(
            update_fields=["resolution", "resolved_via", "unresolved_reason", "organisation"]
        )
        bound += 1
    return EnumerationReport(listed, bound, conflicts, unkeyable)


# --- The resolver's half (spec 6.5): rung 1 and the vocabulary's source. ---


@dataclass(frozen=True)
class WikidataMatch:
    qid: str
    #: P856 values, preferred rank first, deprecated dropped.
    websites: tuple[str, ...]
    #: Labels and aliases in the vocabulary's languages, in that order --
    #: the names store's contribution from Wikidata (rule 4).
    labels: tuple[str, ...]


def _headers() -> dict[str, str]:
    return {"User-Agent": settings.WIKIDATA_USER_AGENT}


def _query(query: str, *, get: Get = fetch_json_api) -> dict[str, object]:
    """One raw query-service call: the endpoint, `WIKIDATA_USER_AGENT`, the
    service's own 60s timeout plus margin, and the JSON accept types --
    shared by `fetch_items` and `sparql`. `refresh_country_labels` builds its
    own call rather than using this: it needs a binding's `xml:lang`, which
    `sparql()`'s flatten to plain `{var: value}` strings would drop."""
    return get(
        ENDPOINT,
        params={"query": query, "format": "json"},
        headers=_headers(),
        read_timeout=65.0,
        accept=_SPARQL_TYPES,
    )


def sparql(query: str, *, get: Get = fetch_json_api) -> list[dict[str, str]]:
    """One query-service answer flattened to `{var: value}` rows. The caller
    owns the query text and interpolates only values it has validated."""
    data = _query(query, get=get)
    results = data.get("results")
    bindings = results.get("bindings", []) if isinstance(results, dict) else []
    return [
        {
            str(key): str(cell.get("value", "")) if isinstance(cell, dict) else ""
            for key, cell in row.items()
        }
        for row in bindings
        if isinstance(row, dict)
    ]


def _statements(claims: dict[str, Any], prop: str) -> list[Any]:
    kept = [c for c in claims.get(prop) or [] if c.get("rank") != "deprecated"]
    kept.sort(key=lambda c: c.get("rank") != "preferred")
    values = []
    for claim in kept:
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is not None:
            values.append(value)
    return values


def _dissolved(claims: dict[str, Any]) -> bool:
    """Any non-deprecated P576 claim, valued or not: "dissolved, date unknown"
    is a `somevalue` snak with no datavalue, and it is still dissolved."""
    return any(c.get("rank") != "deprecated" for c in claims.get("P576") or [])


def _labels(entity: dict[str, Any], languages: Sequence[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for lang in languages:
        label = ((entity.get("labels") or {}).get(lang) or {}).get("value")
        if label:
            seen.setdefault(label, None)
        for alias in (entity.get("aliases") or {}).get(lang) or []:
            if alias.get("value"):
                seen.setdefault(alias["value"], None)
    return tuple(seen)


def find_item(
    names: Sequence[str],
    *,
    country_qid: str,
    languages: Sequence[str],
    get: Get = fetch_json_api,
) -> WikidataMatch | None:
    """The one Wikidata item these names exactly label in this country, or None."""
    ids: list[str] = []
    for name in names[:_MAX_NAMES]:
        for lang in dict.fromkeys((languages[0], "en")):
            data = get(WIKIDATA_API, params={
                "action": "wbsearchentities", "search": name, "language": lang,
                "uselang": lang, "type": "item", "limit": 10, "format": "json",
            }, headers=_headers())
            hits = data.get("search")
            for hit in hits if isinstance(hits, list) else []:
                qid = str(hit.get("id") or "") if isinstance(hit, dict) else ""
                if qid and qid not in ids:
                    ids.append(qid)
    if not ids:
        return None
    # Every hit is read, in batches the API accepts: an id dropped here is a
    # second exact match nobody sees, and one match reads as unambiguous.
    entities: dict[str, Any] = {}
    for start in range(0, len(ids), _MAX_IDS):
        data = get(WIKIDATA_API, params={
            "action": "wbgetentities", "ids": "|".join(ids[start:start + _MAX_IDS]),
            "props": "labels|aliases|claims", "format": "json",
        }, headers=_headers())
        batch = data.get("entities")
        if not isinstance(batch, dict):
            return None
        entities.update(batch)
    wanted = {fold(name) for name in names}
    all_languages = tuple(dict.fromkeys((*languages, "en", "ru")))
    matches: list[WikidataMatch] = []
    for qid in ids:
        entity = entities.get(qid)
        if not isinstance(entity, dict):
            continue
        claims = entity.get("claims") or {}
        countries = {v.get("id") for v in _statements(claims, "P17") if isinstance(v, dict)}
        if country_qid not in countries or _dissolved(claims):
            continue
        # Exactness is checked against EVERY language's labels, not only the
        # vocabulary's: a name is often recorded in a language nobody searched.
        every_label = _labels(entity, tuple(dict.fromkeys(
            (*(entity.get("labels") or {}), *(entity.get("aliases") or {})))))
        if not wanted & {fold(label) for label in every_label}:
            continue
        websites = tuple(v for v in _statements(claims, "P856") if isinstance(v, str))
        matches.append(WikidataMatch(qid, websites, _labels(entity, all_languages)))
    return matches[0] if len(matches) == 1 else None
