"""Dates as the page printed them: code parses day, month and year; Jev is asked only a date's role,
and its order when a slash date is ambiguous (verified-catalog §5 step 4).

Measured 2026-10-03 on session f7's v5 key: 208 of 211 key dates found across 8 languages once
year-only and academic-year spans go to the intake finder. A span with no day is a month, never
given one: the 2026-09-27 run's every "wrong day" was "February 2027" clipped to "February 20".
"""

from __future__ import annotations

import calendar
import datetime
import math
import re
from functools import cache

from apps.research.locale_names import inflected, lookup, month_forms

from . import Date, RelativeDate, _after_plain_word

_ORDINAL = r"(?:st|nd|rd|th|er|-?(?:ci|cı|cu|cü|si|sı|su|sü|inci|ıncı|nci|ncı))?"
#: Joiners that make a range on their own; "and"-words make one only after a lead
#: ("between October and January"), otherwise they list ("1 April and 1 October 2026").
_FREE_JOIN = re.compile(
    r"^\s*(?:[–—~～-]|to|until|till|through|по|до|-?(?:dək|dek|qədər|kadar)|bis|au|부터|إلى|الى|حتى|から)\s*$",
    re.IGNORECASE)
_LEAD_JOIN = re.compile(r"^\s*(?:and|и|ve|və|et|ile|ilə|및|و)\s*$", re.IGNORECASE)
_RANGE_LEAD = re.compile(
    r"(?:from|between|с|от|entre|du|vom|von|zwischen|من|بين)\s*$", re.IGNORECASE
)

#: Islamic Hijri month names (Arabic and English transliterations) -> Hijri month number (1..12).
_HIJRI_MONTH_MAP: dict[str, int] = {
    "محرم": 1,
    "شهر محرم": 1,
    "muharram": 1,
    "صفر": 2,
    "safar": 2,
    "ربيع الأول": 3,
    "ربيع الاول": 3,
    "rabi' al-awwal": 3,
    "rabi al-awwal": 3,
    "ربيع الثاني": 4,
    "ربيع الآخر": 4,
    "ربيع الاخر": 4,
    "rabi' al-thani": 4,
    "rabi al-thani": 4,
    "rabi al-akhir": 4,
    "جمادى الأولى": 5,
    "جمادى الاولى": 5,
    "jumada al-ula": 5,
    "jumada al-awwal": 5,
    "جمادى الآخرة": 6,
    "جمادى الاخرة": 6,
    "جمادى الثانية": 6,
    "jumada al-akhirah": 6,
    "jumada al-thani": 6,
    "رجب": 7,
    "rajab": 7,
    "شعبان": 8,
    "sha'ban": 8,
    "shaban": 8,
    "رمضان": 9,
    "شهر رمضان": 9,
    "ramadan": 9,
    "ramadhan": 9,
    "شوال": 10,
    "shawwal": 10,
    "ذو القعدة": 11,
    "ذي القعدة": 11,
    "dhu al-qi'dah": 11,
    "dhu al-qidah": 11,
    "dhul qadah": 11,
    "ذو الحجة": 12,
    "ذي الحجة": 12,
    "dhu al-hijjah": 12,
    "dhul hijjah": 12,
}

_HIJRI_MONTH_PATTERN = "|".join(
    re.escape(k) for k in sorted(_HIJRI_MONTH_MAP, key=len, reverse=True)
)
_HIJRI_ERA_SUFFIX = r"(?:\s*(?:هـ|هجرية|هجري|AH|A\.H\.))?"


def hijri_to_gregorian(hy: int, hm: int, hd: int) -> datetime.date | None:
    """Convert an Islamic Hijri date `(hy, hm, hd)` in `1400..1500 AH` to a Gregorian `date`
    using the standard tabular/civil Islamic calendar (epoch JDN 1948440)."""
    if not (1400 <= hy <= 1500 and 1 <= hm <= 12 and 1 <= hd <= 30):
        return None
    jd = hd + math.ceil(29.5 * (hm - 1)) + (hy - 1) * 354 + (3 + 11 * hy) // 30 + 1948439
    return datetime.date.fromordinal(jd - 1721425)
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
        # Islamic Hijri numeric & named-month dates (1430..1469 AH -> Gregorian)
        rf"(?<!\d)(?P<hy>14[3-6]\d)[/-](?P<hmo>\d{{1,2}})[/-](?P<hd>\d{{1,2}}){_HIJRI_ERA_SUFFIX}(?!\d)",
        rf"(?<!\d)(?P<hd>\d{{1,2}})[/-](?P<hmo>\d{{1,2}})[/-](?P<hy>14[3-6]\d){_HIJRI_ERA_SUFFIX}(?!\d)",
        rf"(?:(?<!\d)(?P<hd>\d{{1,2}}){_ORDINAL}\.?\s+)?(?P<hmn>{_HIJRI_MONTH_PATTERN})\.?,?\s+"
        rf"(?P<hy>14[3-6]\d){_HIJRI_ERA_SUFFIX}(?!\d)",
        # Japanese Imperial Era (Reiwa 令和N年M月D日 -> Gregorian 2018 + N)
        r"令和\s?(?P<reiwa>元|\d{1,2})\s?年\s?(?P<mo>\d{1,2})\s?月(?:\s?(?P<d>\d{1,2})\s?日)?",
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
    text, start, end = match.group(0), match.start(), match.end()
    if g.get("hy"):
        hy = int(g["hy"])
        hm = (
            int(g["hmo"])
            if g.get("hmo")
            else _HIJRI_MONTH_MAP.get(" ".join(g["hmn"].split()).casefold())
        )
        hd = int(g["hd"]) if g.get("hd") else None
        if hm is None or not (1 <= hm <= 12):
            return None
        if hd is not None:
            greg = hijri_to_gregorian(hy, hm, hd)
            if greg is None:
                return None
            return Date(text, start, end, greg.year, greg.month, greg.day)
        greg_mid = hijri_to_gregorian(hy, hm, 15)
        if greg_mid is None:
            return None
        return Date(text, start, end, greg_mid.year, greg_mid.month, None)
    if g.get("reiwa"):
        reiwa_num = 1 if g["reiwa"] == "元" else int(g["reiwa"])
        year: int | None = 2018 + reiwa_num
    else:
        year = int(g["y"]) if g.get("y") else None
        if year is not None and year < 100:
            year += 2000
    if g.get("sep"):
        return _ambiguous(match, year)
    month = int(g["mo"]) if g.get("mo") else (_month_number(g["mn"]) if g.get("mn") else None)
    day = int(g["d"]) if g.get("d") else None
    if month is None or not 1 <= month <= 12 or (day is not None and not 1 <= day <= 31):
        return None
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
