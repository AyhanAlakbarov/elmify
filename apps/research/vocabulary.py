"""The data the resolver's six rules read (spec 6.5), and nothing the resolver decides.

Kinds, places and common words are rows from Wikidata with a retrieved-on date
(principle 7: nothing names a scheme, funder, country or page in code). The
2026-09-18 hold-out failed precisely where these were typed by hand: v4 knew
"Türkiye", "Berlin" and "Stuttgart" because someone typed them, and v5 knew none.
"""

from __future__ import annotations

import functools
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import wikidata
from .names import tokens

DATA_DIR = Path(__file__).resolve().parent / "resolver_data"

_ISO2 = re.compile(r"^[A-Z]{2}$")
#: Assertions, not tuning: a count outside these bounds is a changed query or a
#: dropped filter, and the build stops rather than writing it (the VGM rule).
_GEO_FLOOR, _GEO_CEILING = 20, 150_000
_ORG_FLOOR, _ORG_LIMIT = 50, 30_000
_KINDS_FLOOR, _KINDS_CEILING = 20, 3_000
#: A token in at least this share of the country's organisation names, and in
#: at least ten of them, is common vocabulary -- never evidence of which body.
_GENERIC_SHARE, _GENERIC_MIN_LABELS = 0.01, 10
#: Kind items: subclasses of organization (Q43229) with at least this many
#: sitelinks -- enough languages to label them (rule 1: "~50 kinds, 26+ languages").
_KIND_SITELINKS = 30

_COUNTRY_Q = """SELECT ?country ?lang ?tld WHERE {{
  ?country wdt:P297 "{iso2}" ; wdt:P31 wd:Q6256 .
  FILTER NOT EXISTS {{ ?country wdt:P576 [] }}
  OPTIONAL {{ ?country wdt:P37 ?l . ?l wdt:P424 ?lang . }}
  OPTIONAL {{ ?country wdt:P78 ?t . ?t rdfs:label ?tld . FILTER(LANG(?tld) = "en") }}
}}"""

_GEO_Q = """SELECT DISTINCT ?label WHERE {{
  {{ BIND(wd:{qid} AS ?place) }}
  UNION {{ ?place wdt:P17 wd:{qid} ; wdt:P31/wdt:P279* wd:Q515 . }}
  UNION {{ wd:{qid} wdt:P150 ?place . }}
  {{ ?place rdfs:label ?label }} UNION {{ ?place skos:altLabel ?label }}
  UNION {{ ?place wdt:P1549 ?label }}
  FILTER(LANG(?label) IN ({langs}))
}}"""

_ORG_Q = """SELECT ?label WHERE {{
  ?org wdt:P17 wd:{qid} ; wdt:P856 [] ; rdfs:label ?label .
  FILTER(LANG(?label) IN ({langs}))
}} LIMIT {limit}"""

_KIND_PATHS = {
    2: "wdt:P279|wdt:P279/wdt:P279",
    3: "wdt:P279|wdt:P279/wdt:P279|wdt:P279/wdt:P279/wdt:P279",
}
_KINDS_Q = """SELECT ?kind ?label WHERE {{
  {{ BIND(wd:Q43229 AS ?kind) }} UNION {{ ?kind {path} wd:Q43229 . }}
  ?kind wikibase:sitelinks ?links . FILTER(?links >= {sitelinks})
  {{ ?kind rdfs:label ?label }} UNION {{ ?kind skos:altLabel ?label }}
  FILTER(LANG(?label) IN ({langs}))
}}"""

Sparql = Callable[[str], list[dict[str, str]]]


class VocabularyShape(ValueError):
    """Wikidata answered with something other than what the build measured."""


class VocabularyMissing(LookupError):
    """No committed vocabulary for this country: run build_resolver_vocabulary."""


@dataclass(frozen=True)
class Vocabulary:
    country_code: str
    country_qid: str
    #: The country-code TLD without its dot ("tr"), for the +0.25 tiebreak.
    cctld: str
    #: The country's official languages (Wikidata P37 -> P424), then en, ru.
    languages: tuple[str, ...]
    #: Folded single-token kind word -> the Wikidata kind items it labels.
    #: A set because one word labels several kinds ("fund").
    kinds: Mapping[str, frozenset[str]]
    #: Folded tokens of the country's names, demonyms, cities and first-level
    #: divisions (rule 2) -- never evidence of WHICH organisation.
    geo: frozenset[str]
    #: Folded tokens frequent across the country's organisation names -- the
    #: v2 finding that "a lone common word is not evidence", measured per
    #: country instead of typed.
    generic: frozenset[str]
    kinds_by_prefix: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)
    kind_cache: dict[str, frozenset[str]] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        buckets: dict[str, list[str]] = {}
        for word in self.kinds:
            buckets.setdefault(word[:3], []).append(word)
        # Longest first, so "stiftungen" meets "stiftung" before "stift".
        object.__setattr__(
            self,
            "kinds_by_prefix",
            {k: tuple(sorted(v, key=lambda w: (-len(w), w))) for k, v in buckets.items()},
        )


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


_LANG = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)*$")


def _in(languages: Sequence[str]) -> str:
    # Language codes come back from Wikidata (P424) and are interpolated into
    # the next query: refuse anything that is not shaped like one.
    bad = [lang for lang in languages if not _LANG.match(lang)]
    if bad:
        raise VocabularyShape(f"not a language code: {bad}")
    return ", ".join(f'"{lang}"' for lang in languages)


def build_country_doc(
    iso2: str, *, retrieved_on: str, sparql: Sparql = wikidata.sparql
) -> dict[str, Any]:
    if not _ISO2.match(iso2):
        raise ValueError(f"not an ISO 3166-1 alpha-2 code: {iso2!r}")
    rows = sparql(_COUNTRY_Q.format(iso2=iso2))
    qids = {_qid(row["country"]) for row in rows if row.get("country")}
    if len(qids) != 1:
        raise VocabularyShape(f"{iso2}: {len(qids)} current countries carry this P297")
    qid = qids.pop()
    if not wikidata._QID.match(qid):
        # Re-interpolated into the next two queries, like the language codes.
        raise VocabularyShape(f"{iso2}: country item {qid!r} is not a QID")
    languages = list(dict.fromkeys(
        [*sorted({r["lang"] for r in rows if r.get("lang")}), "en", "ru"]
    ))
    tld = next((r["tld"].lstrip(".").lower() for r in rows if r.get("tld")), iso2.lower())

    geo: set[str] = set()
    for row in sparql(_GEO_Q.format(qid=qid, langs=_in(languages))):
        toks = tokens(row["label"])
        geo.update(t for t in toks if len(t) >= 3)
        if len(toks) > 1:
            geo.add("".join(toks))  # "Ha Noi" is "hanoi" in a domain label
    if not _GEO_FLOOR <= len(geo) <= _GEO_CEILING:
        raise VocabularyShape(f"{iso2}: {len(geo)} place tokens")

    labels = [
        set(tokens(row["label"]))
        for row in sparql(_ORG_Q.format(qid=qid, langs=_in(languages), limit=_ORG_LIMIT))
    ]
    if len(labels) < _ORG_FLOOR:
        raise VocabularyShape(f"{iso2}: only {len(labels)} organisation labels")
    frequency = Counter(t for toks in labels for t in toks)
    threshold = max(_GENERIC_MIN_LABELS, math.ceil(len(labels) * _GENERIC_SHARE))
    return {
        "iso2": iso2, "country_qid": qid, "cctld": tld, "languages": languages,
        "geo": sorted(geo),
        "generic": sorted(t for t, n in frequency.items() if n >= threshold),
        "organisation_labels": len(labels), "generic_threshold": threshold,
        "retrieved_on": retrieved_on, "source": wikidata.ENDPOINT,
        "queries": {"country": _COUNTRY_Q, "geo": _GEO_Q, "organisations": _ORG_Q},
    }


def build_kinds_doc(
    languages: Sequence[str], *, depth: int, retrieved_on: str,
    sparql: Sparql = wikidata.sparql,
) -> dict[str, Any]:
    rows = sparql(_KINDS_Q.format(
        path=_KIND_PATHS[depth], sitelinks=_KIND_SITELINKS, langs=_in(sorted(languages))
    ))
    kinds: dict[str, set[str]] = {}
    for row in rows:
        toks = tokens(row["label"])
        if len(toks) == 1 and len(toks[0]) >= 3:
            kinds.setdefault(_qid(row["kind"]), set()).add(toks[0])
    if not _KINDS_FLOOR <= len(kinds) <= _KINDS_CEILING:
        raise VocabularyShape(f"{len(kinds)} kinds")
    return {
        "kinds": {qid: sorted(words) for qid, words in sorted(kinds.items())},
        "languages": sorted(languages), "depth": depth, "sitelinks_min": _KIND_SITELINKS,
        "retrieved_on": retrieved_on, "source": wikidata.ENDPOINT, "query": _KINDS_Q,
    }


@functools.cache
def load_vocabulary(country_code: str) -> Vocabulary:
    path = DATA_DIR / f"{country_code.upper()}.json"
    if not path.exists():
        raise VocabularyMissing(f"{path.name}: run manage.py build_resolver_vocabulary")
    country = json.loads(path.read_text("utf-8"))
    kinds_path = DATA_DIR / "kinds.json"
    if not kinds_path.exists():
        raise VocabularyMissing(f"{kinds_path.name}: run manage.py build_resolver_vocabulary")
    kinds_doc = json.loads(kinds_path.read_text("utf-8"))
    stale = set(country["languages"]) - set(kinds_doc["languages"])
    if stale:
        raise VocabularyMissing(f"kinds.json lacks {sorted(stale)}: rebuild it")
    kinds: dict[str, set[str]] = {}
    for qid, words in kinds_doc["kinds"].items():
        for word in words:
            kinds.setdefault(word, set()).add(qid)
    return Vocabulary(
        country_code=country["iso2"], country_qid=country["country_qid"],
        cctld=country["cctld"], languages=tuple(country["languages"]),
        kinds={word: frozenset(qids) for word, qids in kinds.items()},
        geo=frozenset(country["geo"]), generic=frozenset(country["generic"]),
    )
