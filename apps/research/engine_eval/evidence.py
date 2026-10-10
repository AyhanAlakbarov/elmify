"""Deterministic evidence a 'yes' can lean on (research 2026-10-03: a second bar, not a gate).

The scorer gives each tier two bars -- one for lines where code found this evidence, one for
lines where it did not -- so evidence lowers the bar where it exists instead of hiding facts
code missed.
"""

from __future__ import annotations

import re

from apps.research.candidates.amounts import find_amounts
from apps.research.candidates.dates import find_dates, find_relative_dates
from apps.research.candidates.who import find_levels

_NATIONALITY = re.compile(
    r"citizen|national|international student|foreign|resident|"
    r"vətəndaş|əcnəbi|xarici|"
    r"vatandaş|uluslararası öğrenci|yabancı|"
    r"граждан|иностран|соотечественник|резидент", re.IGNORECASE)
_THRESHOLD = re.compile(
    r"gpa|cgpa|ielts|toefl|gre|gmat|ümumi orta|üomg|\bdil\b|yaş|age|не старше|не моложе|"
    r"не менее|at least|minimum|en az|ən azı|\b\d{2,3}\s*(?:\+|%|bal|балл|points?)\b|"
    r"\b[0-4][.,]\d{1,2}\b", re.IGNORECASE)


def amounts(text: str) -> list[str]:
    """The production amount finder's spans, so the scorer leans on the finder the reader uses."""
    return [a.text for a in find_amounts(text)]


def evidence(question_id: str, text: str) -> bool:
    if question_id == "application_date":
        return bool(find_dates(text) or find_relative_dates(text))
    if question_id == "level_rule":
        return bool(find_levels(text))
    if question_id == "nationality_rule":
        return bool(_NATIONALITY.search(text))
    if question_id == "requirement_rule":
        return bool(_THRESHOLD.search(text))
    if question_id == "money_to_student":
        return bool(amounts(text))
    return True
