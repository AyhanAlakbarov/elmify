"""What the summary screen shows about a reading: four numbers, and where to look.

Code checks what the document itself lets it check (spec 3.1, "What the reader checks"): credits
against every printed credit total, a value outside its scale, a word mixing Latin and Cyrillic
letters. **A failed check is shown, never repaired** -- nothing here writes a value into the
reading; filling a missing credit from a printed total would put a number on the screen the
document never showed. Averages are not checked: they are weighted, rounded and sometimes count
failed attempts, so a misread single grade barely moves them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .credits import CreditUnit
from .transcript import Highlight, Reading, Row, number

#: ponytail: one range for every credit system -- a 30-credit thesis is the largest single
#: course in the measured set, and a 60-credit "course" is a misread column. Per-unit ranges when
#: spec 4.4 names the local systems.
_MAX_COURSE_CREDITS = Decimal("30")


class KeyNumbers(BaseModel):
    """The four numbers that decide eligibility and are typed into portals (spec 3.1 step 3)."""

    model_config = ConfigDict(extra="forbid")

    overall_grade: str | None
    grading_scale: str | None
    total_credits: str | None
    #: False when no total is printed: the figure is then our sum of the completed courses'
    #: credits, and the screen says so rather than presenting it as the transcript's.
    total_credits_printed: bool
    credit_unit: CreditUnit
    graduation_date: date | None


def _credits(rows: Sequence[Row]) -> list[Decimal]:
    return [credits for row in rows if (credits := number(row.credits)) is not None]


def _sums(courses: Sequence[Row]) -> set[Decimal]:
    """What a printed total may be counting: every course, every course but a failed attempt
    later retaken, or completed courses only. Transcripts differ; a total matching none of the
    three is the one that is flagged."""

    def total(rows: Sequence[Row]) -> Decimal:
        return sum(_credits(rows), Decimal(0))

    return {
        total(courses),
        total([row for row in courses if row.status != "SUPERSEDED_ATTEMPT"]),
        total([row for row in courses if row.status == "COMPLETED"]),
    }


def _credit_totals(rows: Sequence[Row], total_line: str | None) -> Iterator[Highlight]:
    semester: list[Row] = []
    courses: list[Row] = []
    printed_totals = 0
    for row in rows:
        if row.kind == "semester_heading":
            semester = []
        elif row.kind == "course":
            semester.append(row)
            courses.append(row)
        elif row.kind == "semester_total" and (printed := number(row.credits)) is not None:
            printed_totals += 1
            if printed not in _sums(semester):
                yield Highlight(kind="credit_total_mismatch", scope="semester", ref=str(row.index))
            semester = []
    overall = [(row.credits, str(row.index)) for row in rows if row.kind == "overall_total"]
    if total_line is not None:
        overall.append((total_line, "total_credits"))
    for text, ref in overall:
        if (printed := number(text)) is None:
            continue
        printed_totals += 1
        if printed not in _sums(courses):
            yield Highlight(kind="credit_total_mismatch", scope="transcript", ref=ref)
    if printed_totals == 0:
        yield Highlight(kind="credit_total_not_checked", scope="transcript")


def _ranges(reading: Reading) -> Iterator[Highlight]:
    grade = number(reading.content.overall_grade or "")
    scale = number(reading.content.grading_scale or "")
    if grade is not None and scale is not None and grade > scale:
        yield Highlight(kind="grade_above_scale", scope="field", ref="overall_grade")
    for row in reading.rows:
        credits = number(row.credits) if row.kind == "course" else None
        if credits is not None and not Decimal(0) <= credits <= _MAX_COURSE_CREDITS:
            yield Highlight(kind="credit_out_of_range", scope="row", ref=str(row.index))


def _mixed(text: str) -> bool:
    """A word holding both Latin and Cyrillic letters -- "Rуsсkий" -- which no language writes."""
    for word in re.findall(r"\w+", text):
        scripts = {unicodedata.name(ch, "").split(" ")[0] for ch in word if ch.isalpha()}
        if {"LATIN", "CYRILLIC"} <= scripts:
            return True
    return False


def _mixed_scripts(reading: Reading) -> Iterator[Highlight]:
    content = reading.content
    for name in ("institution", "qualification", "field"):
        if _mixed(getattr(content, name)):
            yield Highlight(kind="mixed_script", scope="field", ref=name)
    for row in reading.rows:
        if row.kind == "course" and _mixed(row.title):
            yield Highlight(kind="mixed_script", scope="row", ref=str(row.index))


def highlights(reading: Reading) -> tuple[Highlight, ...]:
    """Every failed check, every check that could not run, and every unsure answer, once each."""
    found = [
        *_credit_totals(reading.rows, reading.total_credits_line),
        *_ranges(reading),
        *_mixed_scripts(reading),
        *reading.doubts,
    ]
    return tuple(dict.fromkeys(found))


def key_numbers(reading: Reading) -> KeyNumbers:
    content = reading.content
    overall = [row for row in reading.rows if row.kind == "overall_total"]
    printed = [row.credits for row in overall if number(row.credits) is not None]
    if reading.total_credits_line is not None:
        printed.append(reading.total_credits_line)
    if printed:
        total: str | None = printed[-1]
    else:
        completed = _credits([row for row in reading.rows if row.status == "COMPLETED"])
        total = str(sum(completed, Decimal(0))) if completed else None
    return KeyNumbers(
        overall_grade=content.overall_grade,
        grading_scale=content.grading_scale,
        total_credits=total,
        total_credits_printed=bool(printed),
        credit_unit=content.credit_unit,
        graduation_date=content.completed_on or content.expected_completion,
    )
