"""Dates as the page printed them: code parses day, month and year; Jev is asked only a date's role,
and its order when a slash date is ambiguous (verified-catalog §5 step 4).

Measured 2026-10-03 on session f7's v5 key: 208 of 211 key dates found across 8 languages once
year-only and academic-year spans go to the intake finder. A span with no day is a month, never
given one: the 2026-09-27 run's every "wrong day" was "February 2027" clipped to "February 20".
"""

from __future__ import annotations

import calendar
import re
from functools import cache

from apps.research.locale_names import inflected, lookup, month_forms

from . import Date, RelativeDate, _after_plain_word

_ORDINAL = r"(?:st|nd|rd|th|er|-?(?:ci|cı|cu|cü|si|sı|su|sü|inci|ıncı|nci|ncı))?"
#: Joiners that make a range on their own; "and"-words make one only after a lead
#: ("between October and January"), otherwise they list ("1 April and 1 October 2026").
_FREE_JOIN = re.compile(
    r"^\s*(?:[–—~～-]|to|until|till|through|по|до|-?(?:dək|dek|qədər|kadar)|bis|au|부터)\s*$",
    re.IGNORECASE)
_LEAD_JOIN = re.compile(r"^\s*(?:and|и|ve|və|et|ile|ilə|및)\s*$", re.IGNORECASE)
_RANGE_LEAD = re.compile(r"(?:from|between|с|от|entre|du|vom|von|zwischen)\s*$", re.IGNORECASE)
#: An ablative ending on the first date joins it to the next: "1 fevraldan 31 iyuladək",
#: "15 Ocak'tan 15 Şubat'a kadar", "13 iyuldan 22 iyul".
_ABLATIVE = re.compile(r"(?:['’]?(?:n?d|t)[aeə]n)$", re.IGNORECASE)
#: English month names that are also ordinary words; alone they count only after a preposition
#: and with a capital ("in March"), never in "they march on campus" or "students may apply".
_WORD_MONTHS = {"march", "may"}
_QUALIFIER = r"(?:late|early|mid|end of|beginning of|the end of|start of)"
_PREPOSITION = r"(?:in|by|until|before|after|from|since|during|of)"


@cache
def _forms() -> tuple[tuple[str, str, int], ...]:
    """Every month form; an abbreviation is matched exactly in every language, because a Turkish
    "Mar" free to take endings is the "Mar" of "10 Marmara Üniversitesi"."""
    wide = set(month_forms(wide_only=True))
    return tuple(form if form in wide else (form[0], "", form[2]) for form in month_forms())


@cache
def _month() -> str:
    return inflected((name, lang) for name, lang, _ in _forms())


@cache
def _wide_month() -> str:
    return inflected((name, lang) for name, lang, _ in month_forms(wide_only=True))


@cache
def _bare_month() -> str:
    """A wide month name standing alone ("fevral-aprel", "Noyabr ayından"): 4+ letters, and never
    a name that is also an English word."""
    return inflected(
        (name, lang) for name, lang, _ in month_forms(wide_only=True)
        if len(name) >= 4 and name not in _WORD_MONTHS
    )


def _month_number(token: str) -> int | None:
    return lookup(token.rstrip("."), _forms())


@cache
def _patterns() -> tuple[re.Pattern[str], ...]:
    m, wide, bare = _month(), _wide_month(), _bare_month()
    return tuple(re.compile(p, re.IGNORECASE) for p in (
        r"(?<!\d)(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})(?!\d)",
        rf"(?<!\d)(?P<d1>\d{{1,2}})\s*[–-]\s*(?P<d>\d{{1,2}})\.?\s+(?P<mn>{m})\.?"
        rf"(?:,?\s+(?P<y>\d{{4}}))?",
        # dotted dates carry a four-digit year: "09.03.01" is a Russian specialty code
        r"(?<![\d.])(?P<a>\d{1,2})(?P<sep>[./])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4}|(?<=/)\d{2})"
        r"(?![\d.])",
        rf"(?<!\d)(?P<d>\d{{1,2}}){_ORDINAL}\.?\s+(?P<mn>{m})\.?(?:,?\s+(?P<y>\d{{4}}))?(?!\d)",
        # year first ("2026. február 15.") before month-day, which would take "február 15" alone
        rf"(?<!\d)(?P<y>\d{{4}})\.?\s+(?P<mn>{m})\.?(?:\s+(?P<d>\d{{1,2}})\.?)?",
        rf"(?P<mn>{m})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th|\s?일|\s?日)?(?!\d)"
        rf"(?:,?\s+(?P<y>\d{{4}}))?",
        rf"(?P<mn>{m})\.?,?\s+(?P<y>\d{{4}})(?!\d)",
        r"(?P<y>\d{4})\s?[年년]\s?(?P<mo>\d{1,2})\s?[月월](?:\s?(?P<d>\d{1,2})\s?[日일])?",
        r"(?<![\d.])(?P<mo>\d{1,2})\s?[月월](?:\s?(?P<d>\d{1,2})\s?[日일])?",
        # month to month: "fevral-aprel", "may-iyun", "May–June"
        rf"(?P<mn>{wide})\s*[–—-]\s*(?P<mn2>{wide})",
        rf"{_QUALIFIER}\s+(?P<mn>{wide})",
        rf"(?<!\w){_PREPOSITION}\s+(?P<mn>(?-i:March|May))(?!\w)",
        rf"(?P<mn>{bare})",
    ))


def _real_day(year: int | None, month: int, day: int) -> bool:
    """Whether `day` exists in `month`; with no year February may have its leap 29th."""
    return day <= calendar.monthrange(year or 2000, month)[1]


def _ambiguous(match: re.Match[str], year: int | None) -> Date | None:
    a, b = int(match.group("a")), int(match.group("b"))
    text, start, end = match.group(0), match.start(), match.end()
    if match.group("sep") == ".":           # day-first wherever pages print dots
        day, month = a, b
    elif a > 12 and b <= 12:
        day, month = a, b
    elif b > 12 and a <= 12:
        day, month = b, a
    else:
        if not (1 <= a <= 12 and 1 <= b <= 12):
            return None
        return Date(text, start, end, year, None, None, order_ambiguous=True, first=a, second=b)
    if not (1 <= month <= 12 and 1 <= day <= 31) or not _real_day(year, month, day):
        return None
    return Date(text, start, end, year, month, day)


def _single(match: re.Match[str]) -> Date | None:
    g = match.groupdict()
    year = int(g["y"]) if g.get("y") else None
    if year is not None and year < 100:
        year += 2000
    if g.get("sep"):
        return _ambiguous(match, year)
    month = int(g["mo"]) if g.get("mo") else (_month_number(g["mn"]) if g.get("mn") else None)
    day = int(g["d"]) if g.get("d") else None
    if month is None or not 1 <= month <= 12 or (day is not None and not 1 <= day <= 31):
        return None
    text, start, end = match.group(0), match.start(), match.end()
    if day is not None and not _real_day(year, month, day):
        return None  # "31 April 2027": no such day; a month-only pattern may still read the month
    if g.get("mn2"):  # "fevral-aprel": one candidate, two months, no day
        last = _month_number(g["mn2"])
        if last is None:
            return None
        return Date(text, start, end, None, month, None, None, last, None)
    if g.get("d1"):  # "1–15 March 2026": one candidate, both days in the same month
        first = int(g["d1"])
        if not 1 <= first <= 31 or not _real_day(year, month, first):
            return None
        return Date(text, start, end, year, month, first, year, month, day)
    return Date(text, start, end, year, month, day)


_BARE_DAY = re.compile(r"(?<![\d.])(?P<n>\d{1,2})(?=\D*$)(?P<gap>\D*)$")


def _bare_days(line: str, taken: list[Date]) -> list[Date]:
    """The day left of "15 March" in "1 to 15 March" / "1 and 15 March": the month and year are
    shared, and _joined decides whether the two are a range or a list."""
    out = []
    for date in taken:
        if date.end_month is not None or not date.day or not re.match(r"\d{1,2}(?!\d)", date.text):
            continue
        m = _BARE_DAY.search(line[:date.start])
        if not m or _after_plain_word(line, m.start()):
            continue
        if not (_FREE_JOIN.match(m["gap"]) or _LEAD_JOIN.match(m["gap"])):
            continue
        day = int(m["n"])
        end = m.start("gap")
        if 1 <= day <= 31 and not any(m.start() < t.end and t.start < end for t in taken):
            out.append(Date(m["n"], m.start(), end, date.year, date.month, day))
    return out


def _spans(line: str) -> list[Date]:
    taken: list[Date] = []
    for pattern in _patterns():
        for match in pattern.finditer(line):
            if any(match.start() < t.end and t.start < match.end() for t in taken):
                continue
            if "d1" in pattern.groupindex and _after_plain_word(line, match.start()):
                continue  # "Room 12 - 15 March": the 12 is a label, "15 March" is read alone
            date = _single(match)
            if date is not None:
                taken.append(date)
    return sorted(taken + _bare_days(line, taken), key=lambda d: d.start)


def _reversed(previous: Date, date: Date) -> bool:
    """Both ends printed with a year, and the end is before the start."""
    if not (previous.year and date.year and previous.month and date.month):
        return False
    end = (date.year, date.month, date.day or 0)
    return end < (previous.year, previous.month, previous.day or 0)


def _joined(line: str, previous: Date, date: Date) -> bool:
    if _reversed(previous, date):
        return False
    gap = line[previous.end:date.start]
    if _FREE_JOIN.match(gap):
        return True
    if not gap.strip() and _ABLATIVE.search(previous.text):
        return True
    return bool(_LEAD_JOIN.match(gap) and _RANGE_LEAD.search(line[:previous.start]))


def find_dates(line: str) -> list[Date]:
    out: list[Date] = []
    for date in _spans(line):
        previous = out[-1] if out else None
        if previous is not None and previous.end_month is None and _joined(line, previous, date):
            out[-1] = Date(
                line[previous.start:date.end], previous.start, date.end,
                previous.year or date.year, previous.month or date.month, previous.day,
                date.year or previous.year, date.month, date.day,
                previous.order_ambiguous or date.order_ambiguous,
                previous.first, previous.second, date.first, date.second,
            )
            continue
        out.append(date)
    return out


_UNITS = {
    "month": "months", "months": "months", "месяц": "months", "месяца": "months",
    "месяцев": "months", "ay": "months", "week": "weeks", "weeks": "weeks", "недел": "weeks",
    "hafta": "weeks", "həftə": "weeks", "day": "days", "days": "days", "дн": "days",
    "день": "days", "gün": "days", "year": "years", "years": "years", "год": "years",
    "лет": "years", "yıl": "years", "il": "years",
}
_APPROX = r"approximately|about|around|roughly|some|примерно|около|приблизительно|yaklaşık|təxminən"
_END = r"(?=\s+(?:with|and|while|which|or|и|ile|ve|və)\b|[.,;:]|$)"
_EN = re.compile(
    rf"(?:(?P<ap>{_APPROX})\s+)?(?<![\d.,])(?P<lo>\d{{1,3}})(?:\s*(?:or|to|–|-)\s*(?P<hi>\d{{1,3}}))?\s+"
    rf"(?P<unit>months?|weeks?|days?|years?)\s+(?P<dir>before|after|prior to|ahead of)\s+"
    rf"(?P<anchor>.{{3,80}}?){_END}", re.IGNORECASE)
_RU = re.compile(
    rf"(?:(?P<ap>{_APPROX})\s+)?за\s+(?<![\d.,])(?P<lo>\d{{1,3}})(?:\s*[–-]\s*(?P<hi>\d{{1,3}}))?\s+"
    rf"(?P<unit>месяц\w*|недел\w*|дн\w*|день|год\w*|лет)\s+(?P<dir>до)\s+"
    rf"(?P<anchor>.{{3,80}}?){_END}", re.IGNORECASE)
#: The Turkic offset is found from its number and direction ("2 ay əvvəl"); the anchor, the noun
#: phrase in the ablative before it, is then read from at most 80 characters back. Searching for the
#: anchor first cost 80 steps at every position of the line.
_TURKIC = re.compile(
    rf"(?:(?P<ap>{_APPROX})\s+)?(?<![\d.,])(?P<lo>\d{{1,3}})(?:\s*[–-]\s*(?P<hi>\d{{1,3}}))?\s+"
    rf"(?P<unit>ay|hafta|həftə|gün|yıl|il)\s+(?P<dir>önce|əvvəl|sonra)", re.IGNORECASE)
_TURKIC_ANCHOR = re.compile(
    r"(?P<anchor>[^.,;]{3,80}?)'?(?:n?dan|n?dən|n?den|n?tan|n?tən|n?ten)\s+$", re.IGNORECASE)
_DIRECTION = {"before": "before", "prior to": "before", "ahead of": "before", "до": "before",
              "önce": "before", "əvvəl": "before", "after": "after", "sonra": "after"}


def _unit(word: str) -> str:
    folded = word.casefold()
    for key in sorted(_UNITS, key=len, reverse=True):
        if folded.startswith(key):
            return _UNITS[key]
    raise ValueError(word)


def find_relative_dates(line: str) -> list[RelativeDate]:
    """Offsets from an anchor. The Turkic anchor is the last two words before the ablative
    ending, verbatim ("təhsilin başlanması"); it never becomes a date here."""
    found: list[RelativeDate] = []
    for pattern in (_EN, _RU, _TURKIC):
        for m in pattern.finditer(line):
            start = m.start()
            if pattern is _TURKIC:
                back = max(0, start - 80)
                anchored = _TURKIC_ANCHOR.search(line[back:start])
                if anchored is None:
                    continue
                anchor = " ".join(anchored.group("anchor").split()[-2:])
                start = back + anchored.start() + anchored.group(0).index(anchor)
            else:
                anchor = m.group("anchor").strip()
            low = int(m.group("lo"))
            high = int(m.group("hi")) if m.group("hi") else low
            found.append(RelativeDate(line[start:m.end()], start, m.end(), low, high,
                                      _unit(m.group("unit")),
                                      _DIRECTION[m.group("dir").casefold()], anchor,
                                      bool(m.group("ap"))))
    return sorted(found, key=lambda r: r.start)
