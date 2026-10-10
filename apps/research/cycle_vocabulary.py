"""The cycle vocabulary of spec 9.2 -- data, never a list in code (principle 7).

Two roles. `cycle` terms steer the step-1 crawl (`includePaths`) toward the
pages where a funder announces a call; `apply` terms pick the one own-site hop
of step 2. Neither decides anything: a path pattern that matches nothing costs
nothing, and whether a page is evidence is the reader's and validity's question.

The file ships only the terms the spec names. A language missing here shows up
as low per-country recall in the gate (Task 13) and is added then, with a
source -- never ahead of a measurement.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from anyascii import anyascii

from apps.research.harvest import anchors

_CSV = Path(__file__).resolve().parents[2] / "docs" / "research" / "cycle-vocabulary.csv"
_ROLES = frozenset({"cycle", "apply"})


@dataclass(frozen=True)
class Term:
    language: str
    role: str
    term: str
    source: str
    verified_on: str


@cache
def terms() -> tuple[Term, ...]:
    with _CSV.open(encoding="utf-8", newline="") as handle:
        rows = tuple(
            Term(**{key: (value or "").strip() for key, value in row.items()})
            for row in csv.DictReader(handle)
        )
    for row in rows:
        if row.role not in _ROLES or not (row.term and row.source and row.verified_on):
            raise ValueError(f"cycle-vocabulary row is incomplete: {row}")
    return rows


def for_languages(role: str, languages: Iterable[str]) -> tuple[str, ...]:
    """English plus the host's languages; every language when none is recorded.

    Every language, not English alone, for an unknown host: a missing local term
    costs the page, an extra one costs nothing.
    """
    wanted = {language.casefold() for language in languages}
    rows = [row for row in terms() if row.role == role]
    if wanted:
        rows = [row for row in rows if row.language in {"en", *wanted}]
    return tuple(dict.fromkeys(row.term for row in rows))


def _fold(term: str) -> str:
    """Transliterate, never drop: NFKD-then-ignore turned `müraciət` into
    `muracit`, since ə, ı and ß do not decompose. Case is kept."""
    return anyascii(term)


def include_paths(languages: Iterable[str], *, today: dt.date) -> tuple[str, ...]:
    """Plain terms for `site.crawl(include_paths=...)`, which escapes them.

    A URL path carries `basvuru` or `son-tarih` far more often than `başvuru`
    or `son tarih`, so each term also goes out folded and hyphenated. Unmeasured
    per host; the gate's step-1 recall is what says whether it is enough.
    """
    found: list[str] = []
    for term in (*for_languages("cycle", languages), *year_tokens(today)):
        for variant in (term, _fold(term)):
            hyphenated = variant.replace(" ", "-")
            if hyphenated and hyphenated not in found:
                found.append(hyphenated)
    return tuple(found)


def year_tokens(today: dt.date) -> tuple[str, ...]:
    """The previous two, the current and the next year (spec 9.2)."""
    return tuple(str(today.year + delta) for delta in (-2, -1, 0, 1))


def mentions_award(text: str, *, name: str, years: Iterable[str]) -> bool:
    """Spec 9.2: a crawled page reaches the reader only if it names the award
    or carries a year token. String matching, no model."""
    folded = text.casefold()
    if name and re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", folded):
        return True
    return any(re.search(rf"(?<!\d){re.escape(year)}(?!\d)", folded) for year in years)


def apply_links(body: bytes, *, base_url: str, languages: Iterable[str]) -> tuple[str, ...]:
    """Anchors whose href or text carries an `apply` term, in page order."""
    from urllib.parse import urljoin

    wanted = [term.casefold() for term in for_languages("apply", languages)]
    found: list[str] = []
    for anchor in anchors(body):
        absolute = urljoin(base_url, anchor.href)
        haystack = f"{absolute} {anchor.text}".casefold()
        if absolute.startswith(("http://", "https://")) and any(t in haystack for t in wanted):
            if absolute not in found:
                found.append(absolute)
    return tuple(found)
