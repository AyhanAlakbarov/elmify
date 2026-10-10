"""The resolver's acceptance test: a fresh-script hold-out (spec 6.5, 15).

Per-country numbers are development scores; acceptance is a blind hold-out
on a script and morphology the resolver has never seen (owner rule
2026-09-18). The rules below were fixed in the build-item-8 plan before any
hold-out was drawn, and the digest makes "the resolver we drew against" the
one that is scored: tuning after seeing hold-out results turns the hold-out
into development data, which is how Georgia and Kazakhstan were spent (6.5).

Vietnamese, because it is the most distant from every development sample:
Latin script under stacked diacritics, monosyllabic words (the >= 4-letter
distinctive rule is stressed and one-token names are common), and
institutional domains that are English-initials acronyms. Indonesian is kept
unseen as the next hold-out if this one fails.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import NamedTuple

from .classify import _USABLE
from .domains import is_catalogue
from .hosts import registrable_domain
from .vocabulary import _LANG, DATA_DIR
from .wikidata import _QID

#: Committed in the plan before any draw, so the order is reproducible and
#: chosen by nobody. A new hold-out gets a new salt in the same commit as the
#: rule change it measures, before the draw (plan Task 12, step 4b).
SALT = "tehsil-resolver-holdout-vn-2026-09-25"
#: (label, class QID, how many) -- what the resolver will actually be asked,
#: funders and the bodies adjacent to them, not "organisations in item
#: order", which gave Kazakhstan seventeen embassies.
STRATA = (
    ("foundation", "Q157031", 10), ("nonprofit", "Q163740", 10),
    ("agency", "Q327333", 10), ("university", "Q3918", 10),
    ("business", "Q4830453", 5), ("mission", "Q7843791", 5),
)
#: A stratum that cannot fill is topped up from organisation, marked `other`;
#: the total stays 50.
TOP_UP = ("other", "Q43229")
_HERE = Path(__file__).resolve().parent
#: The resolver as drawn against (frozen_digest): its reading of names, its
#: ladder and its vocabulary loader, and every module whose behaviour decides
#: an answer through it -- the aggregator list, the registrable-domain key and
#: both providers' request shapes. classify.py is NOT in it whole: the
#: resolver reads one value from it (`_USABLE`), and a change to the
#: classifier's prompt would otherwise spend a hold-out it cannot affect.
_FROZEN = (
    "names.py", "resolver.py", "vocabulary.py", "domains.py", "hosts.py",
    "providers/tavily.py", "providers/diffbot.py",
)
_FROZEN_EXTRA: tuple[bytes, ...] = ()
#: A frozen file that does not exist (the vocabulary before it is built)
#: hashes as this marker, so "absent" is a state the digest records, not an
#: error, and the same absence gives the same digest every time.
ABSENT = "absent"
_SALT_SHAPE = re.compile(r"^[a-z0-9-]+$")

#: One row per ITEM, so LIMIT counts items, not (item, website) pairs -- an
#: item with five websites used to eat five of a stratum's rows. Websites are
#: every P856 STATEMENT not deprecated: `wdt:P856` is best rank only, so a
#: body whose preferred website is its new one would have lost its old,
#: still-normal one from the truth, and the resolver finding the old one
#: would score `wrong`. Labels are one per language on Wikidata, so SAMPLE
#: picks the only one. `exclude` drops the items an earlier stratum took
#: BEFORE the LIMIT, so a later, overlapping class (every foundation is a
#: nonprofit) is not handed back only items it may not draw.
DRAW_QUERY = """SELECT ?item (GROUP_CONCAT(DISTINCT STR(?site); separator=" ") AS ?sites)
  (SAMPLE(?native) AS ?native) (SAMPLE(?en) AS ?en) (SAMPLE(?ru) AS ?ru)
  (MD5(CONCAT(STR(?item), "{salt}")) AS ?order) WHERE {{
  ?item wdt:P31/wdt:P279* wd:{cls} ; wdt:P17 wd:{country} ; p:P856 ?statement .
  ?statement ps:P856 ?site .
  FILTER NOT EXISTS {{ ?statement wikibase:rank wikibase:DeprecatedRank }}
  FILTER NOT EXISTS {{ ?item wdt:P576 [] }}{exclude}
  ?item rdfs:label ?native . FILTER(LANG(?native) = "{lang}")
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?ru . FILTER(LANG(?ru) = "ru") }}
}} GROUP BY ?item ORDER BY ?order LIMIT {limit}"""


def draw_query(
    *, cls: str, country_qid: str, lang: str, limit: int, exclude: Iterable[str] = ()
) -> str:
    """DRAW_QUERY with its values checked first: they are interpolated into a
    query language, so anything not shaped exactly like a QID, a language
    code, a positive count and our own salt is refused (wikidata.query_text's
    rule). `exclude` is QIDs already drawn, each checked the same way."""
    if not _QID.match(cls) or not _QID.match(country_qid):
        raise ValueError(f"not a QID: class {cls!r} / country {country_qid!r}")
    if not _LANG.match(lang):
        raise ValueError(f"not a language code: {lang!r}")
    if not _SALT_SHAPE.match(SALT) or limit <= 0:
        raise ValueError(f"salt {SALT!r} / limit {limit!r}")
    taken = sorted(set(exclude), key=lambda q: (len(q), q))
    if bad := [q for q in taken if not _QID.match(q)]:
        raise ValueError(f"not a QID: excluded {bad!r}")
    not_in = (
        "\n  FILTER(?item NOT IN (" + ", ".join(f"wd:{q}" for q in taken) + "))"
        if taken else ""
    )
    return DRAW_QUERY.format(cls=cls, country=country_qid, lang=lang, salt=SALT, limit=limit,
                             exclude=not_in)


@dataclass(frozen=True)
class Drawn:
    qid: str
    stratum: str
    #: What the resolver is given: the native label, then en and ru (rule 4).
    names: tuple[str, ...]
    #: The registrable domains of every P856 -- what it is never shown.
    truth: tuple[str, ...]


def pick(
    rows: Iterable[Mapping[str, str]], *, n: int, taken: set[str], stratum: str
) -> list[Drawn]:
    """Up to `n` items in the query's salted order, one row per item with its
    websites space-joined (DRAW_QUERY). An item whose every website is
    unkeyable or an aggregator is skipped for the next in order: it has no
    truth to score against. `taken` is shared across strata, so no item is
    drawn twice -- the query already excludes them; this is the backstop."""
    names: dict[str, dict[str, None]] = {}
    truth: dict[str, dict[str, None]] = {}
    for row in rows:
        qid = row["item"].rsplit("/", 1)[-1]
        # Ordered sets; the dict keeps the salted order of first appearance
        # (and merges an item that did arrive twice).
        item_names = names.setdefault(qid, {})
        item_truth = truth.setdefault(qid, {})
        for key in ("native", "en", "ru"):
            if row.get(key):
                item_names.setdefault(row[key], None)
        for site in (row.get("sites") or "").split():
            domain = registrable_domain(site)
            if domain and not is_catalogue(domain):
                item_truth.setdefault(domain, None)
    picked: list[Drawn] = []
    for qid, item_names in names.items():
        if len(picked) == n:
            break
        if qid in taken or not truth[qid]:
            continue
        picked.append(Drawn(qid, stratum, tuple(item_names), tuple(truth[qid])))
        taken.add(qid)
    return picked


def verdict(domain: str, truth: Iterable[str]) -> str:
    if not domain:
        return "unresolved"
    return "correct" if domain in set(truth) else "wrong"


def adjudicate(
    *, resolved_landed_on: str, truth: Iterable[str], truth_dead: bool,
    resolved_title_names_it: bool,
) -> str:
    """Automatic, so nobody judges after seeing the answer. A `wrong` becomes
    `correct` only on evidence: (i) the resolver's homepage lands on a truth
    domain (a redirect Wikidata's P856 does not know about), or (ii) every
    truth homepage is DEAD and the resolver's title carries a full name
    variant -- the body moved and Wikidata did not follow. Nothing turns a
    `correct` or an `unresolved` into anything else."""
    if resolved_landed_on in set(truth):
        return "correct"
    if truth_dead and resolved_title_names_it:
        return "correct"
    return "wrong"


class Tally(NamedTuple):
    correct: int
    wrong: int
    unresolved: int
    directory_or_aggregator_wrong: int
    diffbot_wrong: int
    #: Rows scored -- the draw's size, which the thresholds scale with.
    n: int


def thresholds(n: int) -> tuple[int, int]:
    """(least correct, most confident-wrong) for a draw of `n`: 40% rounded
    up and 4% rounded down, in integers so 0.4 * 50 cannot land a hair under
    20. For n = 50 exactly the plan's 20 and 2."""
    return -(-2 * n // 5), n // 25


def passes(t: Tally) -> bool:
    """Fixed 2026-09-25, before the draw, from the measured record (4.13a-b):
    confident-wrong is the harm -- dev was 0/25 German and 1/25 Turkish, the
    failed hold-outs 3/25 Georgian and 11/25 Kazakh -- so at most 2 in 50 (4%).
    Correct at least 20 in 50 (40%): between Turkish dev (48%) and the Georgian
    failure (20%). A wrong answer that is a directory or aggregator is a broken
    rule, not a miss, so none is tolerated; Diffbot is new since v4 and gets
    its own ceiling of one wrong.

    A short draw scales the first two as the plan fixed (Task 10: correct >=
    40% rounded up, wrong <= 4% rounded down) -- computed here from `t.n`
    rather than typed into a note, so the gate cannot score a short draw
    against the 50-row numbers. The directory and Diffbot ceilings are
    counts of broken rules and do not scale."""
    least_correct, most_wrong = thresholds(t.n)
    return (
        t.wrong <= most_wrong and t.correct >= least_correct
        and t.directory_or_aggregator_wrong == 0 and t.diffbot_wrong <= 1
    )


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ABSENT


def _tldextract_version() -> str:
    try:
        return version("tldextract")
    except PackageNotFoundError:
        return ABSENT


def digest_components(country_code: str) -> dict[str, str]:
    """Each frozen part of the resolver by name, and its sha256.

    Per country: `resolver_data/kinds.json` and this country's file only, so
    building Indonesia's vocabulary after Vietnam's draw does not spend
    Vietnam. `_USABLE` by value (sorted repr), and tldextract by installed
    version -- its bundled suffix snapshot decides every registrable domain,
    and a `uv lock` bump changes it without touching a file here."""
    parts = {name: _file_digest(_HERE / name) for name in _FROZEN}
    parts["classify._USABLE"] = hashlib.sha256(
        repr(sorted(str(outcome) for outcome in _USABLE)).encode()).hexdigest()
    parts["tldextract"] = _tldextract_version()
    for name in ("kinds.json", f"{country_code.upper()}.json"):
        parts[f"resolver_data/{name}"] = _file_digest(DATA_DIR / name)
    for index, extra in enumerate(_FROZEN_EXTRA):
        parts[f"extra/{index}"] = hashlib.sha256(extra).hexdigest()
    return parts


def frozen_digest(country_code: str) -> str:
    """sha256 over digest_components, in name order. holdout.py itself is not
    in it: the gate may be fixed after the draw, the resolver may not."""
    digest = hashlib.sha256()
    for name, value in sorted(digest_components(country_code).items()):
        digest.update(f"{name}={value}\n".encode())
    return digest.hexdigest()


def changed_components(drawn: Mapping[str, str], now: Mapping[str, str]) -> list[str]:
    """The names whose digest differs between the draw and now -- present on
    one side only included -- so a refusal says what moved."""
    return sorted(name for name in drawn.keys() | now.keys() if drawn.get(name) != now.get(name))
