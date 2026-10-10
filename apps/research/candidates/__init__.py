"""Every value a funding card can show, found by code on one line (verified-catalog §5 step 4).

Jev never reads a number, a date or a place off a page: code finds the candidates, Jev picks among
them, code copies the pick. A funding line where code finds nothing is `no_candidate`, and that
count is what improves these finders.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, NamedTuple

#: A label word right before a figure ("Year 1", "Room 101", "Step 2"): the figure numbers
#: something and is never the low end of a range. A closed list, because "Stipend 800–1,200 EUR"
#: and "Applications 1–15 March" are ranges. Shared by amounts and dates.
LABEL_BEFORE = re.compile(
    r"(?<!\w)(?<!per )(?<!a )(?<!each )(?<!every )(?<!/)"
    r"(?:year|yr|category|cat\.?|room|step|round|phase|stage|level|group|class|intake|tier|band|"
    r"grade|option|type|part|no\.?|nr\.?|number|#|il|kurs|sinif|qrup|kateqoriya|mərhələ|səviyyə|"
    r"tur|aşama|seviye|grup|sınıf|kategori|год|курс|категория|группа|этап|уровень|тур|класс|№)"
    r"\s*$", re.IGNORECASE)


def _after_plain_word(line: str, pos: int) -> bool:
    """A label word ("Year 1 – ", "Room 101 - ") right before the figure: it numbers something
    and is not the low end of a range."""
    return LABEL_BEFORE.search(line[:pos]) is not None


@dataclass(frozen=True)
class Amount:
    text: str            # verbatim span, joined ends for a range
    start: int
    end: int
    low: Decimal | None  # None when the figure's marks are ambiguous
    high: Decimal | None  # == low unless bound == "range"
    currency: str | None  # ISO code, only when the span names exactly one
    bound: str | None    # "range" | "approximately" | None (Jev asks exact/up_to/at_least)
    converted_from: int | None = None  # index, in this line, of the amount this one converts
    currencies: frozenset[str] = frozenset()  # every currency the span's form could name


@dataclass(frozen=True)
class Date:
    text: str
    start: int
    end: int
    year: int | None
    month: int | None
    day: int | None          # None when the page states no day: never invented
    end_year: int | None = None
    end_month: int | None = None
    end_day: int | None = None
    order_ambiguous: bool = False  # "10/11/2026": Jev's date_order question decides
    first: int | None = None       # the two numbers of an ambiguous date, in printed order
    second: int | None = None
    end_first: int | None = None
    end_second: int | None = None


@dataclass(frozen=True)
class RelativeDate:
    text: str
    start: int
    end: int
    low: int                 # 15, or 11 in "11 or 12"
    high: int                # == low unless a range
    unit: str                # "months" | "weeks" | "days" | "years"
    direction: str           # "before" | "after"
    anchor: str              # verbatim: "the anticipated start of the grant"
    approximately: bool


@dataclass(frozen=True)
class Duration:
    text: str
    start: int
    end: int
    count: int | None   # None for "the standard period of study"
    unit: str           # "months" | "years" | "semesters" | "programme"
    months: int | None  # count*12 for years, count for months; None for semesters and programme


@dataclass(frozen=True)
class Intake:
    text: str
    start: int
    end: int
    start_year: int
    end_year: int | None
    season: str | None  # verbatim season word, "Fall", "Payız", "Wintersemester"


@dataclass(frozen=True)
class Place:
    text: str
    start: int
    end: int
    code: str | None   # ISO alpha-2, or a REGIONS key; None for an unknown group
    kind: str          # "country" | "region" | "unknown_group"


@dataclass(frozen=True)
class Level:
    text: str
    start: int
    end: int
    level: str  # "bachelor" | "master" | "phd" | "postdoc" | "postgraduate" (master or phd)


@dataclass(frozen=True)
class Requirement:
    text: str
    start: int
    end: int
    kind: str                      # "language_test" | "cefr" | "grade" | "age"
    test: str | None = None        # "IELTS", "TOEFL iBT", "TOPIK", "YDS", ...
    score: Decimal | None = None   # a test score or a grade
    cefr: str | None = None        # "B2"
    scale: Decimal | None = None   # 4.0 in "GPA 3.0/4.0"
    age_min: int | None = None
    age_max: int | None = None     # inclusive: "under 35" is 34


@dataclass(frozen=True)
class Line:
    """One line of a page: its text, the heading it sits under, and, for a table cell, the
    column header ("신청시기") the cell's value is read with."""

    text: str
    heading: str = ""
    header: str = ""


class Found[T](NamedTuple):
    line: int          # index of the line in the list `find_all` was given
    value: T
    from_header: bool  # found in the line's column header, not in its text


@dataclass(frozen=True)
class Candidates:
    amounts: dict[str, Found[Amount]]                # "m1"
    dates: dict[str, Found[Date]]                    # "d1"
    relative_dates: dict[str, Found[RelativeDate]]   # "r1"
    durations: dict[str, Found[Duration]]            # "u1"
    intakes: dict[str, Found[Intake]]                # "i1"
    places: dict[str, Found[Place]]                  # "p1"
    levels: dict[str, Found[Level]]                  # "l1"
    requirements: dict[str, Found[Requirement]]      # "c1"
    conversion_of: dict[str, str] = field(default_factory=dict)  # "m3" -> "m2"

    def _groups(self) -> dict[str, Mapping[str, Found[Any]]]:
        return {"amounts": self.amounts, "dates": self.dates, "relative_dates": self.relative_dates,
                "durations": self.durations, "intakes": self.intakes, "places": self.places,
                "levels": self.levels, "requirements": self.requirements}

    def state(self) -> dict[str, dict[str, dict[str, object]]]:
        """{"amounts": {"m1": {"text": ..., "line": 0, ...}}, ...} -- Jev's state, keyed by name."""
        out: dict[str, dict[str, dict[str, object]]] = {}
        for group, items in self._groups().items():
            out[group] = {}
            for key, found in items.items():
                entry: dict[str, object] = {"text": found.value.text, "line": found.line,
                                            "from_header": found.from_header}
                if group == "amounts":
                    entry["conversion_of"] = self.conversion_of.get(key)
                out[group][key] = entry
        return out

    def no_candidate(self, kind: str, flagged: Iterable[int]) -> list[int]:
        """The flagged line indexes where the `kind` finder ("amounts", "dates", ...) found
        nothing: the lines a reader said carry such a value and code could not show one."""
        seen = {found.line for found in self._groups()[kind].values()}
        return sorted({n for n in flagged if n not in seen})


def _fold(text: str) -> str:
    return " ".join(text.casefold().split())


def _keyed[T](prefix: str, finder: Callable[[str], Sequence[T]],
              rows: Sequence[tuple[int, str, bool]]) -> dict[str, Found[T]]:
    out: dict[str, Found[T]] = {}
    in_text: set[tuple[int, str]] = set()  # (line, folded span) already found in a line's text
    for n, text, from_header in rows:
        for value in finder(text):
            span = (n, _fold(value.text))  # type: ignore[attr-defined]
            if from_header and span in in_text:
                continue  # the header repeats what the text says: one fact, one candidate
            if not from_header:
                in_text.add(span)
            out[f"{prefix}{len(out) + 1}"] = Found(n, value, from_header)
    return out


def find_all(lines: Sequence[Line | str]) -> Candidates:
    """Every candidate on every line, keyed by name. A line's column header is read too, and what
    it yields is marked `from_header`."""
    # The finder modules import the dataclasses above, so they are imported here, not at the top.
    from .amounts import find_amounts
    from .dates import find_dates, find_relative_dates
    from .spans import find_durations, find_intakes
    from .who import find_levels, find_places, find_requirements

    rows: list[tuple[int, str, bool]] = []
    for n, raw in enumerate(lines):
        line = Line(raw) if isinstance(raw, str) else raw
        rows.append((n, line.text, False))
        if line.header:
            rows.append((n, line.header, True))

    amounts: dict[str, Found[Amount]] = {}
    conversion_of: dict[str, str] = {}
    in_text: dict[tuple[int, str], str] = {}
    for n, text, from_header in rows:
        keys: list[str] = []
        for amount in find_amounts(text):
            span = (n, _fold(amount.text))
            if from_header and span in in_text:
                keys.append(in_text[span])  # a repeat of the text's amount: reuse its key
                continue
            key = f"m{len(amounts) + 1}"
            amounts[key] = Found(n, amount, from_header)
            keys.append(key)
            if not from_header:
                in_text[span] = key
            if amount.converted_from is not None:
                conversion_of[key] = keys[amount.converted_from]

    return Candidates(
        amounts, _keyed("d", find_dates, rows), _keyed("r", find_relative_dates, rows),
        _keyed("u", find_durations, rows), _keyed("i", find_intakes, rows),
        _keyed("p", find_places, rows), _keyed("l", find_levels, rows),
        _keyed("c", find_requirements, rows), conversion_of,
    )
