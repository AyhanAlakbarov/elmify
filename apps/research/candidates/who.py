"""Who may apply: places, degree levels and entry requirements, found by code.

A place inside an institution's name ("Azərbaycan Dövlət Aqrar Universiteti") is still a place
candidate: whether students of that institution may apply is the reader's `eligible_pN` question
(owner gold, 2026-10-05). A group this code cannot expand to countries ("developing countries", the
DAC list, the CIS, "foreign nationals") is `unknown_group`: counted as no_candidate, never guessed
(verified-catalog §5 step 4); its count says which `funding/regions.py` row to add, with its
defining URL.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Callable, Iterable
from decimal import Decimal
from functools import cache
from pathlib import Path

from apps.research.locale_names import country_forms, fold, inflected, lookup

from . import Level, Place, Requirement

_DOCS = Path(__file__).resolve().parents[3] / "docs" / "research"
REGION_NAMES_FILE = _DOCS / "region-names.csv"
PLACE_ALIASES_FILE = _DOCS / "place-aliases.csv"
#: Country names that are ordinary words on these pages: Turkish "mali" (financial, "Mali destek
#: programı"), Russian "того" (of that). "Mali'den" still reads as Mali.
_NOT_PLACES = frozenset({"того", "mali"})
#: A capitalised "Mali"/"Того" at the start of a line may be a sentence-initial ordinary word.
_AMBIGUOUS_INITIAL = frozenset({"Mali", "Того"})
#: Phrases whose place-looking word is part of something else ("Latin American", "New Jersey").
_STOP_PHRASES = re.compile(
    r"(?<!\w)(?:Latin American|South American|North American|British Columbia|"
    r"New Jersey)(?!\w)", re.IGNORECASE)
_TURKIC_LANGUAGE_NAME = re.compile(r"(?:ca|ce|ça|çe)$", re.IGNORECASE)
_GROUPS = re.compile(
    r"(?<!\w)(?:developing countries|partner countries|programme countries|program countries|"
    r"non-(?-i:[A-Z]{2,}(?:/[A-Z]{2,})*)|DAC list|least developed countries|CIS countries|"
    r"Commonwealth of Independent States|"
    r"СНГ|Turkic States|Türk Dövlətləri|Türk Devletleri|OIC|İslam Əməkdaşlıq|İslam İşbirliği|"
    r"üçüncü ölkələr|third countries|en az gelişmiş ülkeler|"
    r"foreign nationals?|foreign citizens?|international students?|иностранн\w* граждан|"
    r"иностранн\w* студент|xarici vətəndaş|xarici tələbə|əcnəbi|yabancı uyruklu|"
    r"uluslararası öğrenci|ODA[- ]eligible|иностранн\w* гражданств|без гражданства)\w*",
    re.IGNORECASE)
_LEVELS = (
    ("postdoc", r"post-?doc\w*|postdoctoral|doktora sonrası|postdoktorantura|постдок\w*|박사후|"
                r"博士后|ポスドク"),
    ("postgraduate", r"post-?graduate\w*|(?<!\w)graduate (?:students?|stud\w+|programmes?|"
                     r"programs?|degrees?|school)|lisansüstü|послевузовск\w*"),
    ("master", r"(?<!\w)master'?s?(?!\w)|(?<!\w)(?-i:MA|MSc|MSC|M\.Sc\.?)(?!\w)|"
               r"(?<!\w)magistr(?!ate)\w*|yüksek lisans|магистр\w*|mesterképzés|석사|硕士|修士"),
    ("phd", r"(?<!\w)ph\.?\s?d(?:s|\.)?(?!\w)|doctoral|doctorate|doktorantura|doktora(?! sonrası)|"
            r"аспирант\w*|"
            r"докторант\w*|doktori|doctorat|박사(?!후)|博士(?!后)"),
    ("bachelor", r"(?<!\w)bachelor'?s?(?!\w)|undergraduate|bakalavr\w*|(?<!yüksek )lisans(?!üstü)|"
                 r"бакалавр\w*|специалитет\w*|alapképzés|(?<!\w)(?-i:BA|BSc|BSC|B\.Sc\.?)"
                 r"(?!\w)|학사|本科|学士"),
)
_GAP = r"Academic|General|overall|total|minimum|min|Test|English|iBT|score|of|level|band"
_TEST = r"IELTS|TOEFL(?:\s*iBT)?|Duolingo|TOEIC|PTE|TOPIK|HSK|YDS|YÖKDİL|YOKDIL|e-YDS"
_LANGUAGE_CUE = re.compile(
    r"(?<!\w)(?:english|german|french|russian|turkish|language|level|cefr|ingilis|alman|fransız|"
    r"türk(?!iye)|rus|dil|səviyyə|seviye|английск|немецк|французск|русск|турецк|язык|уровн|niveau|sprach|deutsch)",
    re.IGNORECASE)


def _decimal(text: str | None) -> Decimal | None:
    return Decimal(text.replace(",", ".")) if text else None


def _language_test(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "language_test",
                       test=" ".join(m.group("test").split()), score=_decimal(m.group("score")))


def _grade(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "grade", score=_decimal(m.group("score")),
                       scale=_decimal(m.groupdict().get("scale")))


def _age_below(m: re.Match[str]) -> Requirement:
    # "under 35", "35 yaşını doldurmamış": not yet 35, so 34 at most
    return Requirement(m.group(0), m.start(), m.end(), "age", age_max=int(m.group("age")) - 1)


def _age_max(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "age", age_max=int(m.group("age")))


def _age_min(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "age", age_min=int(m.group("age")))


def _age_span(m: re.Match[str]) -> Requirement:
    return Requirement(m.group(0), m.start(), m.end(), "age", age_min=int(m.group("lo")),
                       age_max=int(m.group("age")))


def _age_ru(m: re.Match[str]) -> Requirement:
    # "до 35 лет" reads like "under 35" (34) unless "включительно"
    top = int(m.group("age")) - (0 if m.group("incl") else 1)
    lo = m.group("lo") if "lo" in m.groupdict() else None
    return Requirement(m.group(0), m.start(), m.end(), "age",
                       age_min=int(lo) if lo else None, age_max=top)


_REQUIREMENTS: tuple[tuple[str, Callable[[re.Match[str]], Requirement]], ...] = (
    (rf"(?<!\w)(?P<test>{_TEST})[®™]?[\s():≥]*(?:(?:{_GAP})[\s():≥]+){{0,3}}"
     r"(?P<score>\d{1,3}(?:[.,]\d)?)(?:\s?급)?(?!\d)", _language_test),
    (r"(?<!\w)(?:C?GPA|ÜOMG|ortalama\w*|средний балл)\s*(?:of\s*)?(?:at least\s*|minimum\s*|"
     r"min\.?\s*|en az\s*|ən azı\s*|:\s*)?(?P<score>\d{1,3}(?:[.,]\d{1,2})?)"
     r"(?:\s*/\s*(?P<scale>\d{1,3}(?:[.,]\d{1,2})?))?(?![\d.,]?\d)", _grade),
    (r"(?<![\d.,])(?P<score>\d[.,]\d{1,2})(?:\s*/\s*(?P<scale>\d(?:[.,]\d{1,2})?))?"
     r"\s*C?GPA\b", _grade),
    (r"(?<![\d.,])(?P<score>\d{2,3})\s*(?:bal|балл\w*|points?|puan)\b", _grade),
    (r"(?:under|below|younger than)\s+the age of\s+(?P<age>\d{2})(?!\d)", _age_below),
    # punctuation or end of line cues an age for "under"/"younger than" only: "average below 70."
    # is a grade, and "below" never carries an age without a unit
    (r"(?:under|younger than)\s+(?P<age>\d{2})(?!\d)"
     r"(?=\s*(?:$|[,;.:)]|years?|yaş|лет|y/?o\b|of age))", _age_below),
    (r"(?:under|below|younger than)\s+(?P<age>\d{2})(?!\d)"
     r"(?=\s*(?:years?|yaş|лет|y/?o\b|of age))", _age_below),
    (r"в возрасте\s+от\s+(?P<lo>\d{2})\s+до\s+(?P<age>\d{2})\s*лет(?P<incl>\s+включительно)?",
     _age_ru),
    (r"(?:в возрасте\s+)?до\s+(?P<age>\d{2})\s*лет(?P<incl>\s+включительно)?", _age_ru),
    (r"between the ages? of\s+(?P<lo>\d{2})\s+and\s+(?P<age>\d{2})(?!\d)", _age_span),
    (r"(?<!\d)(?P<age>\d{2})\s*yaşını\s+doldurmamış", _age_below),
    (r"(?:not older than|no older than|up to the age of|не старше)\s+(?P<age>\d{2})(?!\d)"
     r"(?:\s*(?:лет|years?))?", _age_max),
    (r"(?<!\d)(?P<age>\d{2})\s*(?:yaşdan|yaşından)\s+(?:çox olmayan|büyük olmayan)", _age_max),
    (r"(?:yaş sınırı|yaş həddi|age limit)\s*:?\s*(?P<age>\d{2})(?!\d)", _age_max),
    (r"(?:at least|не моложе|not younger than)\s+(?P<age>\d{2})\s*(?:years? old|лет)", _age_min),
    (r"(?<!\w)(?:aged?|ages|yaş(?:ı|ları)?)\s+(?P<lo>\d{2})\s*(?:[–-]|to)\s*(?P<age>\d{2})(?!\d)",
     _age_span),
)


@cache
def _csv_forms(path: Path, column: str) -> tuple[tuple[str, str, str], ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple((row["name"], row["language"], row[column]) for row in csv.DictReader(handle))


def _acronym(name: str) -> bool:
    """"EU", "UK", "U.S.", "РФ": matched in capitals only ("us" is a pronoun)."""
    letters = name.replace(".", "")
    return " " not in name and len(letters) <= 5 and letters.isupper()


def _alternation(forms: Iterable[tuple[str, str, str]]) -> re.Pattern[str]:
    forms = list(forms)
    names = inflected((name, lang) for name, lang, _ in forms if not _acronym(name))
    acronyms = sorted({re.escape(name) for name, _, _ in forms if _acronym(name)},
                      key=len, reverse=True)
    if acronyms:
        names += rf"|(?-i:(?<!\w)(?:{'|'.join(acronyms)})(?!\w))"
    return re.compile(names, re.IGNORECASE)


def _folded(forms: Iterable[tuple[str, str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple((" ".join(fold(name).split()), lang, value) for name, lang, value in forms)


@cache
def _regions() -> tuple[re.Pattern[str], tuple[tuple[str, str, str], ...]]:
    forms = _csv_forms(REGION_NAMES_FILE, "region")
    return _alternation(forms), _folded(forms)


@cache
def _countries() -> tuple[re.Pattern[str], tuple[tuple[str, str, str], ...]]:
    forms = _csv_forms(PLACE_ALIASES_FILE, "code") + country_forms()
    return _alternation(forms), _folded(forms)


def find_places(line: str) -> list[Place]:
    out = [Place(m.group(0), m.start(), m.end(), None, "unknown_group")
           for m in _GROUPS.finditer(line)]
    stops = list(_STOP_PHRASES.finditer(line))
    for pattern, forms, kind in (_regions() + ("region",), _countries() + ("country",)):
        for m in pattern.finditer(line):
            if any(p.start < m.end() and m.start() < p.end for p in out):
                continue
            text = m.group(0)
            if fold(text) in _NOT_PLACES and (text.islower() or (
                    text in _AMBIGUOUS_INITIAL and m.start() == 0)):
                continue
            if any(s.start() < m.end() and m.start() < s.end() for s in stops):
                continue
            if kind == "country" and _TURKIC_LANGUAGE_NAME.search(text) and not any(
                    fold(text) == name for name, _, _ in forms):
                continue  # "İtalyanca", "Hollandaca": a language, not a place
            code = lookup(text, forms)
            if code is not None:
                out.append(Place(m.group(0), m.start(), m.end(), code, kind))
    return sorted(out, key=lambda p: p.start)


def find_levels(line: str) -> list[Level]:
    out: list[Level] = []
    for level, pattern in _LEVELS:
        for m in re.finditer(pattern, line, re.IGNORECASE):
            if not any(found.start <= m.start() < found.end for found in out):
                out.append(Level(m.group(0), m.start(), m.end(), level))
    return sorted(out, key=lambda found: found.start)


def _cefr(line: str) -> list[Requirement]:
    """A CEFR level counts only beside a language or level word: "Room B2" is a room."""
    out: list[Requirement] = []
    for m in re.finditer(r"(?<![\w-])(?P<cefr>[ABC][12])(?![\w-])", line):
        lo = max(0, m.start() - 25)
        before = line[lo:m.start()]
        if lo and line[lo - 1].isalnum():  # the slice starts mid-word: drop the fragment
            before = re.sub(r"^\w+", "", before)
        context = before + " " + line[m.end():m.end() + 15]
        if _LANGUAGE_CUE.search(context):
            out.append(Requirement(m.group(0), m.start(), m.end(), "cefr", cefr=m.group("cefr")))
    return out


def find_requirements(line: str) -> list[Requirement]:
    out = _cefr(line)
    for pattern, read in _REQUIREMENTS:
        for m in re.finditer(pattern, line, re.IGNORECASE):
            if not any(r.start < m.end() and m.start() < r.end for r in out):
                out.append(read(m))
    return sorted(out, key=lambda r: r.start)
