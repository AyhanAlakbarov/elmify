"""Durations and intakes. Code multiplies years into months; a semester count stays a count,
because a semester's length is the institution's, never a guess (card_fields.duration_months'
rule)."""

from __future__ import annotations

import re

from apps.funding.validity import intake_start_year

from . import Duration, Intake
from .dates import find_relative_dates

#: Turkic adjectival/locative suffixes: "2 illik", "2 yıllık", "24 aylıq", "2 ildə".
_TURKIC = r"(?:l[ıiuü][qk]|d[əea])?"
_UNIT = (
    ("months",
     r"months?|ay" + _TURKIC + r"|месяц\w*|мес\.|hónap\w*|mois|monat\w*|개월|个月|か月|ヶ月"),
    ("years", r"years?|(?:il|yıl)" + _TURKIC + r"|год\w*|лет|év\w*|ans?|jahr\w*|년|年"),
    ("semesters", r"semesters?|semestr\w*|dönem|семестр\w*|félév\w*|학기|学期"),
)
#: "1 il əvvəl" (one year before) is an offset, not how long anything lasts.
_OFFSET = r"(?!\s+(?:əvvəl|önce|before|prior|ago|sonra|after|later|назад|спустя))"
_COUNT = re.compile(
    r"(?<![\d.,])(?<!\d[-–—])(?<!\d\s[-–—]\s)(?<!\d\sto\s)"  # never the end of "2-3 years"
    r"(?P<n>\d{1,2})[\s-]?(?P<unit>" + "|".join(p for _, p in _UNIT)
    + r")(?!\w)" + _OFFSET,
    re.IGNORECASE)
_PROGRAMME = re.compile(
    r"standard period of study|regelstudienzeit|full duration of (?:the )?"
    r"(?:study|studies|programme|program)|entire (?:duration|period) of (?:study|the programme)|"
    r"весь период обучения|öğrenim süresi boyunca|tam təhsil müddəti|təhsil müddəti ərzində",
    re.IGNORECASE)
_INTAKE_YEARS = re.compile(r"(?<!\d)(?P<a>\d{4})\s*[/–-]\s*(?P<b>\d{4}|\d{2})(?!\d)")
_SEASON = re.compile(
    r"(?P<s>fall|autumn|spring|winter|summer|payız|yaz|güz|bahar|осен\w*|весн\w*|зим\w*|kış|"
    r"wintersemester|sommersemester)\s+(?P<y>\d{4})", re.IGNORECASE)


def _unit_of(word: str) -> str:
    for unit, pattern in _UNIT:
        if re.fullmatch(pattern, word, re.IGNORECASE):
            return unit
    raise ValueError(word)


def find_durations(line: str) -> list[Duration]:
    relative = [(r.start, r.end) for r in find_relative_dates(line)]
    out: list[Duration] = []
    for m in _COUNT.finditer(line):
        if any(a <= m.start() < b for a, b in relative):
            continue
        count, unit = int(m.group("n")), _unit_of(m.group("unit"))
        months = count * 12 if unit == "years" else count if unit == "months" else None
        out.append(Duration(m.group(0), m.start(), m.end(), count, unit, months))
    for m in _PROGRAMME.finditer(line):
        out.append(Duration(m.group(0), m.start(), m.end(), None, "programme", None))
    return sorted(out, key=lambda d: d.start)


def find_intakes(line: str) -> list[Intake]:
    out: list[Intake] = []
    for m in _INTAKE_YEARS.finditer(line):
        start, tail = int(m.group("a")), m.group("b")
        end = int(tail) if len(tail) == 4 else (start // 100) * 100 + int(tail)
        if not 0 < end - start <= 6:
            continue
        year = intake_start_year(m.group(0))
        if year is not None:
            out.append(Intake(m.group(0), m.start(), m.end(), year, end, None))
    for m in _SEASON.finditer(line):
        out.append(Intake(m.group(0), m.start(), m.end(), int(m.group("y")), None, m.group("s")))
    return sorted(out, key=lambda i: i.start)
