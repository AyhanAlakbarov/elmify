"""Read a date the way a CV writes one, or read nothing at all.

Measured, not assumed (`docs/superpowers/research/2026-08-31-cv-extraction-baseline.md`):
asked for a `date`, the extraction model returned 0944-09-01, 0200-01-01 and
0527-01-01 from text that plainly said "September 2020". The model was doing
two jobs -- reading the page and converting what it read into a number format
-- and it garbled the second. So it now copies the string as printed and this
module converts it. A parser cannot invent a year that is not in front of it.

Failure is `None`, never an exception and never a guess. `None` reaches the
gap interview, which asks the student. A plausible-looking wrong year reaches
nobody: it agrees with the fact it was written from, so every verdict comes
back SUPPORTED and it prints on the CV.

Deliberately NOT dateutil, which is installed and would have been fewer lines.
`dateutil.parser.parse("0944")` returns a date, and a missing component is
filled in from today, so a bare "September" becomes September of this year.
The whole problem here is a model producing plausible garbage; a parser that
turns garbage into dates makes it worse. These patterns refuse what they do
not recognise.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from contextvars import ContextVar
from datetime import date
from enum import StrEnum
from functools import partial

#: Same bounds as schemas.CVDate. A CV date outside them is a garbled token,
#: not an unusual life.
_MIN_YEAR, _MAX_YEAR = 1900, 2100


class Convention(StrEnum):
    """Which number comes first in an all-numeric date."""

    DAY_FIRST = "DAY_FIRST"
    MONTH_FIRST = "MONTH_FIRST"


#: Resolved per document by ingestion (from the document's own unambiguous
#: dates first, then the student's nationality) and read here. A ContextVar
#: rather than an argument because the pydantic validator that calls this sees
#: one field value and nothing else -- not the siblings, not the student.
date_convention: ContextVar[Convention] = ContextVar(
    "date_convention", default=Convention.DAY_FIRST
)

_MONTHS: dict[str, int] = {}


def _register(month: int, *names: str) -> None:
    for name in names:
        _MONTHS[_fold(name)] = month


def _fold(text: str) -> str:
    """Casefold and strip diacritics, so "märz" and "marz" are one key."""
    stripped = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in stripped if not unicodedata.combining(c)).strip(" .")


# English, German, French, Turkish, Azerbaijani. The launch markets are
# Azerbaijan and Türkiye; German and French are where the applicants go.
_register(1, "january", "jan", "januar", "janvier", "ocak", "yanvar")
_register(2, "february", "feb", "februar", "fevrier", "février", "subat", "şubat", "fevral")
_register(3, "march", "mar", "marz", "märz", "mars", "mart")
_register(4, "april", "apr", "avril", "nisan", "aprel")
_register(5, "may", "mai", "mayis", "mayıs")
_register(6, "june", "jun", "juni", "juin", "haziran", "iyun")
_register(7, "july", "jul", "juli", "juillet", "temmuz", "iyul")
_register(8, "august", "aug", "aout", "août", "agustos", "ağustos", "avqust")
_register(9, "september", "sep", "sept", "septembre", "eylul", "eylül", "sentyabr")
_register(10, "october", "oct", "oktober", "octobre", "ekim", "oktyabr")
_register(11, "november", "nov", "novembre", "kasim", "kasım", "noyabr")
_register(12, "december", "dec", "dezember", "decembre", "décembre", "aralik", "aralık", "dekabr")

#: An end date the document leaves open. cv_dates.month_year already renders a
#: null end_date as "present", so None is the representation, not a sentinel.
_OPEN_ENDED = frozenset(
    {"present", "current", "ongoing", "to date", "now", "date", "today", "-", "--", "—", "–"}
)

#: (first month, last month, whether the last month falls in the NEXT year).
#: Northern hemisphere. "Fall 2020" on an Australian CV means March, and this
#: will read it as September -- the markets are Azerbaijan and Türkiye, so this
#: is the right default and the wrong answer for a Melbourne degree.
_SEASONS: dict[str, tuple[int, int, bool]] = {
    "spring": (3, 5, False),
    "summer": (6, 8, False),
    "fall": (9, 11, False),
    "autumn": (9, 11, False),
    "winter": (1, 2, False),
    # The German academic year: Wintersemester runs 1 Oct - 31 Mar, and its end
    # is in the following calendar year. Sommersemester runs 1 Apr - 30 Sep.
    "ws": (10, 3, True),
    "wintersemester": (10, 3, True),
    "ss": (4, 9, False),
    "sommersemester": (4, 9, False),
}

_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_ISO_MONTH = re.compile(r"^(\d{4})[-/](\d{1,2})$")
_YEAR_ONLY = re.compile(r"^(\d{4})$")
_MONTH_YEAR_NUMERIC = re.compile(r"^(\d{1,2})[/.](\d{4})$")
_TRIPLE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")
_SEASON = re.compile(r"^([a-z]+)\.?\s*(\d{4})(?:\s*/\s*\d{2,4})?$")
_MONTH_FIRST_NAME = re.compile(r"^([a-z]+)\.?,?\s*(?:(\d{1,2})(?:st|nd|rd|th)?,?\s*)?(\d{4})$")
_DAY_FIRST_NAME = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\.?\s*([a-z]+)\.?,?\s*(\d{4})$")
#: Any all-numeric date in free text, for convention_from_text.
_TRIPLE_IN_TEXT = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")


def _build(year: int, month: int, day: int | None, *, position: str) -> date | None:
    """One date from parts, or None if the parts name no real day."""
    if not _MIN_YEAR <= year <= _MAX_YEAR or not 1 <= month <= 12:
        return None
    last = calendar.monthrange(year, month)[1]
    if day is None:
        day = last if position == "end" else 1
    if not 1 <= day <= last:
        return None
    return date(year, month, day)


def convention_from_text(text: str) -> Convention | None:
    """Which way round this document writes its numeric dates, if it shows us.

    Evidence from the page beats an assumption about the person: an Azerbaijani
    who did a master's in Boston writes American dates, and the CV shows it
    while the passport does not. A component over twelve can only be a day, so
    one such date settles the whole document. Returns None when nothing is
    decisive -- the caller then falls back to nationality.
    """
    for first, second, _year in _TRIPLE_IN_TEXT.findall(text):
        if int(first) > 12:
            return Convention.DAY_FIRST
        if int(second) > 12:
            return Convention.MONTH_FIRST
    return None


#: Where the day comes second. Everywhere else in the world writes it first,
#: so this is the exception list rather than the rule.
_MONTH_FIRST_NATIONALITIES = frozenset({"US", "CA", "PH", "FM", "MH", "PW"})


_YEAR_IN_TEXT = re.compile(r"\b(?:19|20)\d{2}\b")


def carry_year(start: object, end: object) -> object:
    """Give the start of a range the year only its end states.

    "June - Aug 2025" is one range carrying one year, and the two ends are
    extracted into separate fields -- so parsed alone the start has no year at
    all and reads as nothing. Measured: six dates on the Harvard engineering
    résumé came back empty in both runs for exactly this reason.

    One direction only. "September 2020 - June" would need June's year
    inferred from the start's, and a range can span a year boundary, so 2020
    and 2021 are both defensible and neither is stated. That one stays empty
    and the gap interview asks.
    """
    if not isinstance(start, str) or not isinstance(end, str):
        return start
    if _YEAR_IN_TEXT.search(start):
        return start
    year = _YEAR_IN_TEXT.search(end)
    return f"{start.strip()} {year.group()}" if year and start.strip() else start


def resolve_convention(text: str, *, nationality: str | None = None) -> Convention:
    """Which way this document writes numeric dates: page, then passport, then
    day-first.

    The page outranks the passport deliberately. An Azerbaijani who did a
    master's in Boston writes American dates and the CV shows it; the profile
    only says where he is from. Day-first is the fallback because it is what
    most of the world writes, and because the launch markets are Azerbaijan
    and Türkiye.
    """
    from_document = convention_from_text(text)
    if from_document is not None:
        return from_document
    if nationality and nationality.upper() in _MONTH_FIRST_NATIONALITIES:
        return Convention.MONTH_FIRST
    return Convention.DAY_FIRST


def parse_cv_date(value: object, *, position: str = "start") -> date | None:
    """Read one written date. ``position="end"`` resolves a range's far end.

    A month resolves to its first day as a start and its last as an end, so
    "Fall 2020 - Spring 2022" covers what it says rather than stopping two
    months short.
    """
    if isinstance(value, date):
        return value if _MIN_YEAR <= value.year <= _MAX_YEAR else None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    folded = _fold(raw)
    if not folded or folded in _OPEN_ENDED:
        return None

    if match := _ISO_DAY.match(raw):
        year, month, day = (int(g) for g in match.groups())
        return _build(year, month, day, position=position)
    if match := _ISO_MONTH.match(raw):
        return _build(int(match[1]), int(match[2]), None, position=position)
    if match := _YEAR_ONLY.match(raw):
        year = int(match[1])
        return _build(year, 12 if position == "end" else 1, None, position=position)
    if match := _MONTH_YEAR_NUMERIC.match(raw):
        return _build(int(match[2]), int(match[1]), None, position=position)
    if match := _TRIPLE.match(raw):
        first, second, year = (int(g) for g in match.groups())
        # A component over twelve can only be a day, whatever the convention.
        if first > 12:
            day, month = first, second
        elif second > 12:
            day, month = second, first
        elif date_convention.get() is Convention.MONTH_FIRST:
            day, month = second, first
        else:
            day, month = first, second
        return _build(year, month, day, position=position)

    if match := _DAY_FIRST_NAME.match(folded):
        named = _MONTHS.get(match[2])
        if named is not None:
            return _build(int(match[3]), named, int(match[1]), position=position)
    if match := _MONTH_FIRST_NAME.match(folded):
        named = _MONTHS.get(match[1])
        if named is not None:
            written_day = match[2]
            return _build(
                int(match[3]),
                named,
                int(written_day) if written_day else None,
                position=position,
            )
    if match := _SEASON.match(folded):
        season = _SEASONS.get(match[1])
        if season is not None:
            first_month, last_month, spans_years = season
            season_year = int(match[2])
            if position == "end":
                return _build(
                    season_year + 1 if spans_years else season_year,
                    last_month,
                    None,
                    position="end",
                )
            return _build(season_year, first_month, None, position="start")
    return None


#: pydantic's BeforeValidator takes the value alone, so the far end needs its
#: own one-argument callable.
parse_end_date = partial(parse_cv_date, position="end")
