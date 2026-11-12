"""Year-of-study wording names a level through a per-country table (verified-catalog §5.2.1).

"1st–3rd year students", "I, II və III kurs" and "3–4 курс бакалавриата" are bachelor's students
where the bachelor's lasts long enough. Whether a page states its target level as a year of study
is the readers' judgement (`target_level=year_of_study`); which level that year is, is this
table's: `docs/research/year-of-study-levels.csv`, one row per country and wording language, each
citing its source for the bachelor's length. The country is the FUNDER's (owner, 2026-10-13):
wording that names no country means the funder's own system. An unknown funder country, or one
with no row, maps to nothing -- held, never guessed, and no country is a default; the operator's
fix is a row. Prefer the country's own ministry or education law as a row's source.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

YEARS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "year-of-study-levels.csv"


@dataclass(frozen=True)
class YearRow:
    country: str  # the funder's country
    locale: str  # the wording's language
    pattern: re.Pattern[str]
    years: str  # "1-4": the study years the pattern accepts, as the source counts them
    level: str
    source_url: str


@cache
def year_rows() -> tuple[YearRow, ...]:
    with YEARS_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple(
            YearRow(r["country"], r["locale"], re.compile(r["pattern"], re.IGNORECASE), r["years"],
                    r["level"], r["source_url"])
            for r in csv.DictReader(handle)
        )


def level_of_year(text: str, funder_country: str, lang: str = "") -> str | None:
    """The level `text` names as a year of study under a funder from `funder_country`, or None.
    An unknown page language ("") tries every row of the country; a known one only its own."""
    for row in year_rows():
        if (funder_country and row.country == funder_country and lang in ("", row.locale)
                and row.pattern.search(text)):
            return row.level
    return None
