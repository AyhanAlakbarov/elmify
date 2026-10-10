"""What a table's column header says a date in that column is (dates research 2026-10-03 §1(c)).

36 of 55 dates in the f7 key were Korean month cells under 신청시기 ("application period") or
선발시기 ("selection period"); read without the header, a bare month has no role. The cue is
context shown to Jev beside the cell, never the role on its own. Data, not code: the cues are
docs/research/date-header-cues.csv.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from functools import cache
from pathlib import Path

from apps.research.locale_names import fold

DATE_HEADER_CUES_FILE = (
    Path(__file__).resolve().parents[3] / "docs" / "research" / "date-header-cues.csv"
)
ROLES = ("application_window", "deadline", "selection", "funding_period", "results")


def _pattern(cue: str) -> re.Pattern[str]:
    """A cue in a script without case (Hangul, Han) is a substring: Korean headers run words
    together ("신청시기"). A cue of three letters or fewer ("son", "до") is a whole word; a longer
    one starts a word and may take an ending ("выплата", "müraciətlər")."""
    if cue.upper() == cue.lower():
        return re.compile(re.escape(cue))
    if len(cue) <= 3:
        return re.compile(rf"(?<!\w){re.escape(cue)}(?!\w)", re.IGNORECASE)
    return re.compile(rf"(?<!\w){re.escape(cue)}", re.IGNORECASE)


@cache
def _cues() -> tuple[tuple[re.Pattern[str], int, str], ...]:
    with DATE_HEADER_CUES_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    cues = [(fold(unicodedata.normalize("NFC", row["cue"])), row["role"]) for row in rows]
    return tuple((_pattern(cue), len(cue), role) for cue, role in cues)


def header_cue(text: str) -> str | None:
    """The role the longest cue in `text` names, or None: "Son müraciət tarixi" is a deadline
    although it also contains "müraciət". Two longest cues of equal length naming different roles
    are a tie, and a tie is never guessed (None)."""
    folded = fold(unicodedata.normalize("NFC", text))
    found = [(length, role) for pattern, length, role in _cues() if pattern.search(folded)]
    if not found:
        return None
    longest = max(length for length, _ in found)
    roles = {role for length, role in found if length == longest}
    return roles.pop() if len(roles) == 1 else None
