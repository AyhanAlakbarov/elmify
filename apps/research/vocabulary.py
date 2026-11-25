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
_REPO_DATA_DIR = DATA_DIR

_ISO2 = re.compile(r"^[A-Z]{2}$")
#: Assertions, not tuning: a count outside these bounds is a changed query or a
#: dropped filter, and the build stops rather than writing it (the VGM rule).
_GEO_FLOOR, _GEO_CEILING = 20, 150_000
_ORG_FLOOR, _ORG_LIMIT = 50, 30_000
_KINDS_FLOOR, _KINDS_CEILING = 20, 3_000
#: Microstates have fewer cities/divisions and registered organisations in Wikidata,
#: so `build_country_doc` scales `_GEO_FLOOR`, `_ORG_FLOOR`, and `_GENERIC_MIN_LABELS`
#: proportionally for them rather than failing the shape check.
_MICROSTATE_FLOOR_SCALE: Mapping[str, float] = {
    "LU": 0.25,
    "MT": 0.25,
    "IS": 0.25,
    "LI": 0.15,
    "MC": 0.15,
    "AD": 0.15,
    "SM": 0.15,
}
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
#: `hint:optimizer "None"` makes the query service run the patterns in the order
#: written: the subclass walk first, then sitelinks and labels for those ~240
#: items only. Measured 2026-09-27: without it the planner scans sitelinks
#: across every item and times out at 60s on every run, and `{ BIND(...) }
#: UNION` alone turns a 0.5s direct-subclass query into a timeout; with it the
#: whole query answers in 2.4s (236 kinds, 5,256 labels, ten languages).
_KINDS_Q = """SELECT ?kind ?label WHERE {{
  hint:Query hint:optimizer "None" .
  {{ ?kind {path} wd:Q43229 . }} UNION {{ VALUES ?kind {{ wd:Q43229 }} }}
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

    scale = _MICROSTATE_FLOOR_SCALE.get(iso2, 1.0)
    geo_floor = max(1, math.floor(_GEO_FLOOR * scale)) if scale < 1.0 else _GEO_FLOOR
    org_floor = max(1, math.floor(_ORG_FLOOR * scale)) if scale < 1.0 else _ORG_FLOOR
    generic_min = (
        max(2, math.floor(_GENERIC_MIN_LABELS * scale)) if scale < 1.0 else _GENERIC_MIN_LABELS
    )

    geo: set[str] = set()
    for row in sparql(_GEO_Q.format(qid=qid, langs=_in(languages))):
        toks = tokens(row["label"])
        geo.update(t for t in toks if len(t) >= 3)
        if len(toks) > 1:
            geo.add("".join(toks))  # "Ha Noi" is "hanoi" in a domain label
    if not geo_floor <= len(geo) <= _GEO_CEILING:
        raise VocabularyShape(f"{iso2}: {len(geo)} place tokens")

    labels = [
        set(tokens(row["label"]))
        for row in sparql(_ORG_Q.format(qid=qid, langs=_in(languages), limit=_ORG_LIMIT))
    ]
    if len(labels) < org_floor:
        raise VocabularyShape(f"{iso2}: only {len(labels)} organisation labels")
    frequency = Counter(t for toks in labels for t in toks)
    threshold = max(generic_min, math.ceil(len(labels) * _GENERIC_SHARE))
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


_ISO2_COUNTRY_QIDS: Mapping[str, str] = {
    "AD": "Q228",
    "AT": "Q40",
    "AU": "Q408",
    "AZ": "Q227",
    "BE": "Q31",
    "BR": "Q155",
    "CA": "Q16",
    "CH": "Q39",
    "CN": "Q148",
    "CZ": "Q213",
    "DE": "Q183",
    "DK": "Q35",
    "EE": "Q191",
    "ES": "Q29",
    "FI": "Q33",
    "FR": "Q142",
    "GB": "Q145",
    "GE": "Q230",
    "GR": "Q41",
    "HR": "Q224",
    "HU": "Q28",
    "ID": "Q252",
    "IE": "Q27",
    "IN": "Q668",
    "IS": "Q189",
    "IT": "Q38",
    "JP": "Q17",
    "KR": "Q884",
    "KZ": "Q232",
    "LI": "Q347",
    "LT": "Q37",
    "LU": "Q32",
    "LV": "Q211",
    "MC": "Q235",
    "MT": "Q233",
    "MX": "Q96",
    "NL": "Q55",
    "NO": "Q20",
    "NZ": "Q664",
    "PK": "Q843",
    "PL": "Q36",
    "PT": "Q45",
    "RO": "Q218",
    "RS": "Q403",
    "RU": "Q159",
    "SE": "Q34",
    "SG": "Q334",
    "SI": "Q215",
    "SK": "Q214",
    "SM": "Q238",
    "TR": "Q43",
    "US": "Q30",
    "UZ": "Q265",
    "VN": "Q881",
    "ZA": "Q258",
}

_CCTLD_OVERRIDES: Mapping[str, str] = {
    "GB": "uk",
}

_BASELINE_KIND_QIDS: Mapping[str, frozenset[str]] = {
    "foundation": frozenset({"Q157031"}),
    "fondation": frozenset({"Q157031"}),
    "fundacion": frozenset({"Q157031"}),
    "fondazione": frozenset({"Q157031"}),
    "fundacao": frozenset({"Q157031"}),
    "fundacja": frozenset({"Q157031"}),
    "stichting": frozenset({"Q157031"}),
    "stiftelse": frozenset({"Q157031"}),
    "stiftelsen": frozenset({"Q157031"}),
    "yayasan": frozenset({"Q157031"}),
    "stiftung": frozenset({"Q157031"}),
    "vakif": frozenset({"Q157031"}),
    "charity": frozenset({"Q708676", "Q157031"}),
    "trust": frozenset({"Q157031", "Q708676"}),
    "university": frozenset({"Q3918"}),
    "universitat": frozenset({"Q3918"}),
    "universite": frozenset({"Q3918"}),
    "universidad": frozenset({"Q3918"}),
    "universita": frozenset({"Q3918"}),
    "universiteit": frozenset({"Q3918"}),
    "universitet": frozenset({"Q3918"}),
    "uniwersytet": frozenset({"Q3918"}),
    "hochschule": frozenset({"Q3918"}),
    "college": frozenset({"Q189004", "Q3918"}),
    "institute": frozenset({"Q31855", "Q3918"}),
    "institut": frozenset({"Q31855", "Q3918"}),
    "istituto": frozenset({"Q31855", "Q3918"}),
    "instituto": frozenset({"Q31855", "Q3918"}),
    "academy": frozenset({"Q414147", "Q3918"}),
    "akademie": frozenset({"Q414147", "Q3918"}),
    "association": frozenset({"Q48204", "Q15911314"}),
    "asociacion": frozenset({"Q48204", "Q15911314"}),
    "associazione": frozenset({"Q48204", "Q15911314"}),
    "vereniging": frozenset({"Q48204", "Q15911314"}),
    "verein": frozenset({"Q48204", "Q15911314"}),
    "dernegi": frozenset({"Q48204", "Q15911314"}),
    "society": frozenset({"Q48204", "Q1685451"}),
    "federation": frozenset({"Q48204"}),
    "embassy": frozenset({"Q3917681"}),
    "ambassade": frozenset({"Q3917681"}),
    "ambasciata": frozenset({"Q3917681"}),
    "embajada": frozenset({"Q3917681"}),
    "botschaft": frozenset({"Q3917681"}),
    "consulate": frozenset({"Q7843791"}),
    "ministry": frozenset({"Q192350"}),
    "ministere": frozenset({"Q192350"}),
    "ministerio": frozenset({"Q192350"}),
    "ministero": frozenset({"Q192350"}),
    "ministerium": frozenset({"Q192350"}),
    "agency": frozenset({"Q327333"}),
    "company": frozenset({"Q783794"}),
    "enterprise": frozenset({"Q6881511"}),
    "npo": frozenset({"Q163740"}),
}

_UNIVERSAL_GENERIC_TOKENS: frozenset[str] = frozenset({
    "national",
    "nationale",
    "nacional",
    "nazionale",
    "international",
    "internationale",
    "royal",
    "federal",
    "federale",
    "state",
    "public",
    "publique",
    "general",
    "central",
    "education",
    "educational",
    "egitim",
    "pendidikan",
    "bildungs",
    "research",
    "recherche",
    "forschung",
    "ricerca",
    "investigacion",
    "onderzoek",
    "science",
    "sciences",
    "wissenschaft",
    "wetenschappen",
    "scienze",
    "ciencias",
    "scientific",
    "technology",
    "technologie",
    "cultural",
    "culture",
    "kultur",
    "cultura",
    "social",
    "development",
    "health",
    "medical",
    "center",
    "centre",
    "centro",
    "zentrum",
})

_COUNTRY_EXTRA_GEO: Mapping[str, tuple[str, ...]] = {
    "GB": (
        "Britain", "British", "England", "English", "Scotland", "Scottish", "Wales", "Welsh",
        "Northern Ireland", "London", "Oxford", "Cambridge", "Edinburgh", "Glasgow", "Manchester",
        "Birmingham", "Bristol", "Leeds", "Sheffield", "Nottingham", "Southampton", "Warwick",
    ),
    "US": (
        "America", "American", "United States", "New York", "Boston", "Cambridge", "Chicago",
        "San Francisco", "Los Angeles", "Washington", "Philadelphia", "Seattle", "Atlanta",
        "Austin", "Houston", "California", "Texas", "Massachusetts", "Illinois",
    ),
    "FR": (
        "France", "French", "Francais", "Francaise", "Paris", "Lyon", "Marseille", "Toulouse",
        "Bordeaux", "Lille", "Strasbourg", "Grenoble", "Montpellier", "Nantes", "Nice", "Saclay",
    ),
    "NL": (
        "Netherlands", "Nederland", "Nederlandse", "Dutch", "Holland", "Amsterdam", "Rotterdam",
        "Utrecht", "Leiden", "Delft", "Groningen", "Eindhoven", "Maastricht", "Wageningen",
        "Tilburg", "Nijmegen", "Enschede", "Twente", "Den Haag", "The Hague",
    ),
    "IT": (
        "Italy", "Italia", "Italiana", "Italiano", "Italian", "Rome", "Roma", "Milan", "Milano",
        "Bologna", "Turin", "Torino", "Padua", "Padova", "Florence", "Firenze", "Naples", "Napoli",
        "Pisa", "Venice", "Venezia", "Trento", "Trieste", "Sapienza",
    ),
    "ES": (
        "Spain", "Espana", "Espanola", "Espanol", "Spanish", "Madrid", "Barcelona", "Valencia",
        "Seville", "Sevilla", "Granada", "Salamanca", "Bilbao", "Zaragoza", "Malaga", "Catalonia",
        "Catalunya", "Andalucia", "Galicia",
    ),
    "CH": (
        "Switzerland", "Schweiz", "Schweizerische", "Suisse", "Svizzera", "Swiss", "Zurich",
        "Geneva", "Geneve", "Basel", "Bern", "Lausanne", "St Gallen", "Lucerne", "Luzern",
        "Lugano", "Fribourg", "Neuchatel",
    ),
    "SE": (
        "Sweden", "Sverige", "Svenska", "Swedish", "Stockholm", "Uppsala", "Lund", "Gothenburg",
        "Goteborg", "Linkoping", "Umea", "Karolinska", "Malmo",
    ),
    "CA": (
        "Canada", "Canadian", "Canadienne", "Toronto", "Montreal", "Vancouver", "Ottawa",
        "Calgary", "Edmonton", "Waterloo", "Quebec", "McGill", "Ontario", "British Columbia",
        "Alberta",
    ),
    "AU": (
        "Australia", "Australian", "Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
        "Canberra", "Monash", "Queensland", "Victoria", "New South Wales",
    ),
    "JP": (
        "Japan", "Japanese", "Nihon", "Nippon", "Tokyo", "Kyoto", "Osaka", "Tohoku", "Sendai",
        "Nagoya", "Hokkaido", "Sapporo", "Fukuoka", "Kyushu", "Tsukuba", "Kobe", "Yokohama",
    ),
    "KR": (
        "Korea", "Korean", "South Korea", "Hanguk", "Daehan", "Seoul", "Busan", "Daejeon",
        "Incheon", "Daegu", "Gwangju", "Suwon", "Pohang", "Ulsan",
    ),
    "PL": (
        "Poland", "Polska", "Polski", "Polskiej", "Polish", "Warsaw", "Warszawa", "Krakow",
        "Cracow", "Wroclaw", "Poznan", "Gdansk", "Lodz", "Katowice", "Lublin",
    ),
    "LU": ("Luxembourg", "Luxemburg", "Letzebuerg", "Esch-sur-Alzette", "Belval"),
    "MT": ("Malta", "Maltese", "Valletta", "Msida", "Gozo"),
    "IS": ("Iceland", "Island", "Icelandic", "Reykjavik", "Akureyri"),
    "LI": ("Liechtenstein", "Vaduz", "Schaan", "Bendern"),
    "MC": ("Monaco", "Monte Carlo", "Monegasque"),
    "AD": ("Andorra", "Andorra la Vella", "Sant Julia de Loria"),
    "SM": ("San Marino", "Sammarinese"),
}


@functools.cache
def _universal_kinds_map() -> Mapping[str, frozenset[str]]:
    kinds: dict[str, set[str]] = {
        word: set(qids) for word, qids in _BASELINE_KIND_QIDS.items()
    }
    for base_dir in (DATA_DIR, _REPO_DATA_DIR):
        kinds_path = base_dir / "kinds.json"
        if kinds_path.exists():
            try:
                kinds_doc = json.loads(kinds_path.read_text("utf-8"))
                for qid, words in kinds_doc.get("kinds", {}).items():
                    for word in words:
                        if len(word) >= 3:
                            kinds.setdefault(word, set()).add(qid)
            except (OSError, ValueError, KeyError):
                pass
        kw_path = base_dir / "kind_words.json"
        if kw_path.exists():
            try:
                kw_doc = json.loads(kw_path.read_text("utf-8"))
                items_map: Mapping[str, Sequence[str]] = kw_doc.get("items", {})
                words_map: Mapping[str, Mapping[str, Sequence[str]]] = kw_doc.get("words", {})
                for holder_kind, by_lang in words_map.items():
                    qids = tuple(items_map.get(holder_kind, ()))
                    if not qids:
                        continue
                    for lang_words in by_lang.values():
                        for raw_word in lang_words:
                            toks = tokens(raw_word)
                            if len(toks) == 1 and len(toks[0]) >= 3:
                                kinds.setdefault(toks[0], set()).update(qids)
            except (OSError, ValueError, KeyError):
                pass
    return {word: frozenset(qids) for word, qids in kinds.items()}


@functools.cache
def universal_vocabulary_for(country_code: str) -> Vocabulary:
    """Synthesize a deterministic `Vocabulary` for any ISO 3166-1 alpha-2 country code
    using Unicode CLDR (`babel`), `kind_words.json`/`kinds.json`, and `domains.py`."""
    from babel import Locale
    from babel.core import UnknownLocaleError, get_global
    from babel.languages import get_official_languages, get_territory_language_info

    from .domains import CATALOGUE_DOMAINS

    iso2 = country_code.strip().upper()
    if not _ISO2.match(iso2):
        raise ValueError(f"not an ISO 3166-1 alpha-2 code: {country_code!r}")

    share = get_territory_language_info(iso2)
    official: list[str] = []
    for raw in get_official_languages(iso2, regional=True, de_facto=True):
        pct = float(share.get(raw, {}).get("population_percent") or 0.0)
        is_de_facto = raw in get_official_languages(iso2, regional=False, de_facto=True)
        if not is_de_facto and pct < 5.0:
            continue
        lang = raw.split("_")[0].lower()
        if _LANG.match(lang) and lang not in official:
            official.append(lang)
    if "no" in official and "nb" in official:
        official.remove("no")
    languages = tuple(dict.fromkeys([*official, "en", "ru"]))

    cctld = _CCTLD_OVERRIDES.get(iso2, iso2.lower())
    country_qid = _ISO2_COUNTRY_QIDS.get(iso2, f"Q_{iso2}")

    geo: set[str] = set()

    def _add_place_label(label: str) -> None:
        toks = tokens(label)
        geo.update(t for t in toks if len(t) >= 3)
        if len(toks) > 1:
            geo.add("".join(toks))

    probe_locales = tuple(
        dict.fromkeys(
            [*languages, "en", "de", "fr", "es", "it", "nl", "pt", "tr", "ru", "pl", "sv"]
        )
    )
    tz_zones = get_global("territory_zones").get(iso2, ())
    for zone in tz_zones:
        city_slug = zone.rsplit("/", 1)[-1].replace("_", " ")
        _add_place_label(city_slug)

    for loc_code in probe_locales:
        try:
            loc = Locale.parse(loc_code)
        except (UnknownLocaleError, ValueError):
            continue
        terr_name = loc.territories.get(iso2)
        if terr_name:
            _add_place_label(terr_name)
        for zone in tz_zones:
            tz_info = loc.time_zones.get(zone, {})
            city_name = tz_info.get("city") if isinstance(tz_info, Mapping) else None
            if city_name:
                _add_place_label(str(city_name))

    for extra in _COUNTRY_EXTRA_GEO.get(iso2, ()):
        _add_place_label(extra)

    for dom in CATALOGUE_DOMAINS:
        host_parts = dom.lower().split(".")
        if host_parts[-1] in {cctld, iso2.lower()}:
            first = host_parts[0]
            for prefix in ("studyin-", "studyin", "study-in-", "study"):
                if first.startswith(prefix) and len(first) > len(prefix) + 2:
                    _add_place_label(first[len(prefix):])

    if not geo:
        geo.add(iso2.lower())

    return Vocabulary(
        country_code=iso2,
        country_qid=country_qid,
        cctld=cctld,
        languages=languages,
        kinds=_universal_kinds_map(),
        geo=frozenset(geo),
        generic=_UNIVERSAL_GENERIC_TOKENS,
    )


def load_or_build_vocabulary(country_code: str) -> Vocabulary:
    """Load the committed Wikidata vocabulary for `country_code` when present,
    falling back to `universal_vocabulary_for(country_code)` when `resolver_data/{CC}.json`
    is absent."""
    try:
        return load_vocabulary(country_code)
    except VocabularyMissing:
        return universal_vocabulary_for(country_code)
