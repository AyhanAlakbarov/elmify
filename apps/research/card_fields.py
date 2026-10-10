"""The card's own fields, checked by code against the line they came from.

Spec: docs/superpowers/specs/2026-09-22-funding-search-engine-master-design.md
section 8.3 -- amount, currency, period and duration "as written" -- and 10.4,
the card. Pure apart from reading one data file once.

The readings copy a value as the page wrote it; this module decides whether
the copy is on the line and which number, if any, it states. A reading can
therefore mislabel a figure the page printed but never put one on a card that
the page did not print -- the guarantee `funding_lines` already gives the quote.

**Code computes; the readings only copy and classify.** A reading never
converts a figure, a currency or a duration: "1.200" becomes twelve hundred and
"2 years" becomes 24 months here, where a test pins it. That is the typed-
decisions spec's rule (section 3.1a) applied to the readings this reader keeps.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path

from apps.reference_data import ISO_4217_CODES

from .reader import normalize

#: Data, not code (spec section 3, principle 7). Deliberately NOT a vocabulary
#: in docs/research/vocabulary.csv: a vocabulary there may only ever ADD a
#: candidate, and this file decides whether a number is written at all. So only
#: an unambiguous form confirms. A missing form costs a number -- the card shows
#: the text as printed -- while a wrong one would put a figure in the wrong
#: currency in front of a student, which is the failure worth paying to avoid.
EVIDENCE_FILE = (
    Path(__file__).resolve().parents[2] / "docs" / "research" / "currency-evidence.csv"
)

#: Digits in any script -- a str pattern's \d is Unicode-aware -- joined by the
#: marks pages print between digit groups.
_NUMBER = re.compile(r"\d[\d.,'’   ]*\d|\d")
_GROUP_SPACE = re.compile(r"['’   ]")
_GROUP = re.compile(r"[_.,]")
_CENTS = re.compile(r"[.,](\d{2})$")
#: An ISO 4217 code as a page prints one: three capitals standing alone.
_CODE = re.compile(r"(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])")
#: No master's award runs longer than ten years; a figure above it is a misread.
_MAX_MONTHS = 120


@dataclass(frozen=True)
class EvidenceRow:
    form: str
    currency: str
    kind: str
    review_status: str


def on_line(value: str, line: str) -> bool:
    """Whether `value` is printed on `line`, compared the way quotes are."""
    wanted = normalize(value)
    return bool(wanted) and wanted in normalize(line)


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in text)


def _figure(token: str) -> Decimal | None:
    """One printed number, or None when its marks are ambiguous.

    Money's rules, not a locale's: a mark followed by exactly two final digits
    is the decimal mark (1.200,50 and 1,200.50); every other mark separates
    groups of exactly three (1.200, 1,200, 1 200, 1'200). A lakh grouping, one
    digit after a mark, or two different marks in the whole part is refused.
    """
    plain = _GROUP_SPACE.sub("_", _ascii_digits(token))
    whole, cents = plain, ""
    tail = _CENTS.search(plain)
    if tail is not None and any(ch.isdigit() for ch in plain[: tail.start()]):
        whole, cents = plain[: tail.start()], tail.group(1)
    groups = _GROUP.split(whole)
    if len(set(_GROUP.findall(whole))) > 1 or not all(group.isdigit() for group in groups):
        return None
    if len(groups) > 1 and not (
        1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])
    ):
        return None
    try:
        return Decimal("".join(groups) + (f".{cents}" if cents else ""))
    except InvalidOperation:
        return None


def parse_amount(text: str) -> Decimal | None:
    """The one figure `text` states, or None when it states none or several."""
    found = [match.group().strip() for match in _NUMBER.finditer(text)]
    return _figure(found[0]) if len(found) == 1 else None


def evidence_rows(path: Path = EVIDENCE_FILE) -> tuple[EvidenceRow, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(
            EvidenceRow(row["form"], row["currency"], row["kind"], row["review_status"])
            for row in csv.DictReader(handle)
        )


def _pattern(form: str, kind: str) -> re.Pattern[str]:
    """A sign may touch its figure ("5000元", "₼500") but, when it begins with a
    letter, may not continue a word ("ca$" is not "a$"). A name or an
    abbreviation stands alone ("euro" is not inside "euros")."""
    if form == "원":  # "원서" (application form) is not won: a figure or numeral must precede
        return re.compile(r"(?<=[\d만천억백십])원|(?<=[\d만천억백십] )원")
    if kind == "symbol":
        start = r"(?<![^\W\d_])" if form[0].isalpha() else ""
        return re.compile(start + re.escape(form))
    return re.compile(r"(?<!\w)" + re.escape(form) + r"(?!\w)")


@cache
def _forms() -> tuple[tuple[re.Pattern[str], str], ...]:
    """Every form that names exactly one currency, as a pattern.

    A form listed for two currencies ($, kr, ¥, manat, som) is left out
    entirely: it confirms neither.
    """
    by_form: dict[str, tuple[str, set[str]]] = {}
    for row in evidence_rows():
        kind, codes = by_form.setdefault(row.form.casefold(), (row.kind, set()))
        codes.add(row.currency)
    return tuple(
        (_pattern(form, kind), next(iter(codes)))
        for form, (kind, codes) in by_form.items()
        if len(codes) == 1
    )


def currencies_in(text: str) -> frozenset[str]:
    """Every currency `text` names unambiguously: an ISO code, or a listed form."""
    named = {code for code in _CODE.findall(text) if code in ISO_4217_CODES}
    folded = text.casefold()
    named.update(code for pattern, code in _forms() if pattern.search(folded))
    return frozenset(named)


def confirmed_currency(claimed: str, amount_text: str) -> str | None:
    """The reading's currency, when the copied amount names it and nothing else.

    Checked on the copy, not on the whole line: a line saying "€1,000 (about
    US$1,100)" names two, and only the copy says which one the figure is in.
    """
    return claimed if currencies_in(amount_text) == {claimed} else None


def duration_months(text: str, unit: str) -> int | None:
    """Months, from the one figure the copy prints and the unit the readings chose.

    The readings classify the unit (MONTHS, YEARS, OTHER); code multiplies. A
    number word, a range, a semester count or an implausible figure keeps its
    text on the card and gives no number.
    """
    figures = re.findall(r"\d+", _ascii_digits(text))
    if unit not in ("MONTHS", "YEARS") or len(figures) != 1:
        return None
    months = int(figures[0]) * (12 if unit == "YEARS" else 1)
    return months if 0 < months <= _MAX_MONTHS else None
