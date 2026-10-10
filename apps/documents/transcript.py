"""Read an uploaded transcript: OCR cuts, code finds the candidates, Jev picks, code copies.

No generative model reads a transcript (spec 3.1, T19). The OCR program (ocr.py) returns each
page's text lines and table grids. Code drops everything that identifies the student, then turns
the rest into candidates: table columns, table rows, the other lines, and the numbers and dates
on those lines. Jev answers closed questions about them (transcript_questions.py) through the
decision layer's one client, and code copies the chosen cell or span verbatim. A Jev answer only
ever chooses which printed text is copied; code does every count and sum (transcript_checks.py).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field

from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.research.decisions import Answer, Client, DecisionsUnavailable, ask, provider_for
from apps.tenancy.models import Membership

from . import transcript_questions as questions
from .credits import CreditUnit, to_ects
from .ingestion import UnsupportedUpload
from .models import VerifiedFact
from .ocr import OcrPage

#: Cells shown per column when Jev is asked what the column holds: the header and enough values.
_CELLS_PER_COLUMN = 20
#: Three questions per row, 40 rows a request: 16-18k tokens by decisions.py's own estimate on
#: the real OCR output of four sample transcripts (2026-09-26), inside decisions.MAX_STATE_TOKENS
#: (32k, the OpenRouter endpoint's context). The first request -- columns, lines, numbers,
#: dates -- measured 3-12k.
_ROWS_PER_REQUEST = 40
_MAX_ROWS = 240
_MAX_CANDIDATES = 200
_MAX_DATES = 50

RowKind = Literal[
    "course", "semester_heading", "semester_total", "overall_total", "header", "other"
]
CourseStatus = Literal["COMPLETED", "IN_PROGRESS", "SUPERSEDED_ATTEMPT"]

#: A line or table row carrying one of these is never sent anywhere (owner, 2026-09-26: TypeSafe
#: and OpenRouter see course tables, not the student). A label ending its line takes the next line
#: with it -- that is where its value is printed.
_PERSONAL_LABEL = re.compile(
    r"family name|given name|first name|last name|surname|full name|patronymic|"
    r"date of birth|place of birth|birth date|student (?:id|no|number)|identification number|"
    r"passport|national id|^\s*(?:student\s+)?name\s*:|"
    r"soyad|doğum|dogum|kimlik|öğrenci no|öğrenci numara|atasının adı|baba adı|^\s*adı\s*:|"
    r"şəxsiyyət|fin kod|"
    r"фамилия|\bимя\b|отчество|\bф\.?\s?и\.?\s?о\b|дата рождения|место рождения|паспорт|"
    r"зач[её]тной книжки",
    re.IGNORECASE,
)
#: Six digits or more: a student, diploma, passport or ID number. A line holding one is dropped;
#: in a table cell it is masked, because a numeric course code (0301101) is one too.
_ID_NUMBER = re.compile(r"\d{6,}")
#: ponytail: numeric dates only. "16 марта 2026 года" is no candidate, so a transcript printing
#: its dates in words gets the graduation question (Task 5); add month names when one needs it.
_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMBER = re.compile(r"\b\d{1,4}(?:[.,]\d{1,3})?\b")


class TranscriptCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    #: As printed, in the transcript's own unit. Never bounded here: an impossible figure is a
    #: failed range check the student sees, not a reading that fails to load.
    credits: Decimal | None = None
    grade: str | None = Field(default=None, max_length=50)
    #: A failed attempt later retaken is kept by the reader and dropped by academic_record, so
    #: the credits of one course are never counted twice.
    status: CourseStatus


class TranscriptContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Empty when no printed line was chosen: the record then fails AcademicRecord and is not
    #: prefilled, so the student types it rather than confirms a blank.
    institution: str = Field(default="", max_length=200)
    country_code: str = Field(default="", pattern=r"^([A-Z]{2})?$")
    qualification: str = Field(default="", max_length=100)
    field: str = Field(default="", max_length=200)
    overall_grade: str | None = Field(default=None, max_length=50)
    grading_scale: str | None = Field(default=None, max_length=100)
    credit_unit: CreditUnit
    #: ponytail: never set by the reader -- no measured transcript prints a full-time year's
    #: load. A LOCAL unit therefore converts to no ECTS figure; spec 4.4 adds named systems.
    local_credits_per_year: Decimal | None = None
    courses: tuple[TranscriptCourse, ...] = Field(default=(), max_length=150)
    completed_on: date | None = None
    expected_completion: date | None = None


class Highlight(BaseModel):
    """One thing the summary screen marks (spec T2): a failed check, a check that could not run,
    or an answer Jev was unsure of, or a credit or grade cell the reader was unsure of. Never a
    spelling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal[
        "credit_total_mismatch",
        "credit_total_not_checked",
        "grade_above_scale",
        "credit_out_of_range",
        "mixed_script",
        "unsure",
        "low_confidence",
    ]
    #: A row (ref: its index), a semester (ref: the index of the row printing its total), the
    #: whole transcript (ref: empty or what was unsure), or a field of the record (ref: its name).
    #: A row index names an entry of `Reading.rows`, stored as `TranscriptReading.rows`.
    scope: Literal["row", "semester", "transcript", "field"]
    ref: str = ""


@dataclass(frozen=True)
class Row:
    """One course-table row as code cut it and Jev labelled it.

    `index` is its place in reading order -- what a highlight on it names. Cells are verbatim;
    a column the table does not have reads as "".
    """

    index: int
    kind: RowKind
    title: str
    credits: str
    grade: str
    status: CourseStatus | None


@dataclass(frozen=True)
class Reading:
    content: TranscriptContent
    rows: tuple[Row, ...]
    #: A total-credits figure printed outside any table, when Jev found one.
    total_credits_line: str | None
    #: Answers below questions.UNSURE_BELOW, as highlights.
    doubts: tuple[Highlight, ...]


class TranscriptReadingDisabled(RuntimeError):
    """Raised instead of DecisionsUnavailable when TRANSCRIPT_JEV_ENABLED is off.

    A closed launch gate is not "the provider did not answer, retry": the gate
    does not open between retries, so treating it like DecisionsUnavailable
    (transcript_pages.read_upload delays that one and retries it) retries a
    condition retrying can never fix. read_upload catches this one specifically
    and fails the upload as reading_off immediately, with no OCR ever invoked."""


def number(text: str) -> Decimal | None:
    """A printed number as a Decimal -- '6', '7.5', '7,5' -- or None for anything else."""
    match = re.fullmatch(r"\s*(\d{1,4})(?:[.,](\d{1,3}))?\s*", text)
    if match is None:
        return None
    return Decimal(match[1] if match[2] is None else f"{match[1]}.{match[2]}")


def _fold(text: str) -> str:
    """Casefold a word so any case or script-variant spelling of the same letters matches.

    Plain `.casefold()` fails on the Turkish/Azerbaijani dotted capital İ: it casefolds to a
    plain "i" plus a combining dot above (U+0307), which then reads as two separate word
    characters and splits "ALİYEV" into "ali"/"yev" -- neither matching the account's "aliyev"
    (measured 2026-09-26, review round 1). NFKD decomposes İ into "I" + that combining mark,
    stripping combining marks removes it, and casefold then gives plain "i". The dotless
    lowercase ı (U+0131) has no decomposition of its own, so it is mapped to "i" by hand. This
    also folds other accented Latin letters (ç, ş, ö, ü, ğ) to their base letter -- erring
    toward matching too much only widens what gets redacted, never lets identifying text
    through. The Azerbaijani schwa Ə/ə has no decomposition either and is written "a" in
    Latin transliteration (Əliyev → Aliyev), so it is folded to "a" after casefolding.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.replace("ı", "i").casefold().replace("ə", "a")


def _nfc(text: str) -> str:
    """Canonically compose text before it is ever split into words.

    OCR can emit İ as a precomposed character or, just as validly, as a plain "I" followed by
    its own combining dot above (U+0307) -- Unicode's NFD form. `\\w+` treats a combining mark
    as a word boundary, so the decomposed form splits "ALİYEV" into "ALI"/"YEV" before `_fold`
    (above) ever runs, regardless of how well `_fold` folds a single already-intact word
    (review round 2, item 2). Composing to NFC first turns any decomposed run back into one
    character per letter, so splitting on `\\w+` afterwards sees the same word either way.
    """
    return unicodedata.normalize("NFC", text)


def _normalised(pages: tuple[OcrPage, ...]) -> tuple[OcrPage, ...]:
    """The OCR pages with every line and cell composed to NFC (see `_nfc`) -- once, so every
    reader downstream (label and name matching, and the text that survives into the state
    handed to Jev) works from the same canonical form."""
    return tuple(
        OcrPage(
            lines=tuple(_nfc(line) for line in page.lines),
            tables=tuple(
                tuple(tuple(_nfc(cell) for cell in row) for row in table) for table in page.tables
            ),
            cell_confidence=page.cell_confidence,
            source=page.source,
            api_version=page.api_version,
        )
        for page in pages
    )


def personal_names(student: Membership) -> frozenset[str]:
    """The student's name words, from the account and from any identity fact read off a CV.

    Called inside a tenant-scoped transaction: VerifiedFact is behind row-level security.
    """
    names = [student.user.get_full_name()]
    for fact in VerifiedFact.objects.filter(
        student=student, category=VerifiedFact.Category.IDENTITY
    ):
        if isinstance(fact.payload, dict):
            names.append(str(fact.payload.get("full_name", "")))
    return frozenset(
        _fold(word)
        for name in names
        for word in re.findall(r"\w+", _nfc(name))
        if len(word) >= 2
    )


#: The word or two a document prints right after one of its own labels: "Фамилия Иванов",
#: "Surname: Aliyev". Learned first, so a page header repeating the name without a label --
#: every page of the Russian specimen carries one, in Cyrillic, which no Latin account name
#: matches -- is recognised too. A value starting with a digit (a birth date) teaches nothing.
_VALUE_AFTER_LABEL = re.compile(r"\w*[\s:.]+([^\W\d_]{2,})(?:\s+([^\W\d_]{2,}))?")
_WORD = re.compile(r"[^\W\d_]{2,}")


def _has_label(text: str) -> bool:
    return _PERSONAL_LABEL.search(text) is not None


def _label_ends(text: str) -> bool:
    """A label that prints nothing else on its line/cell -- its value is printed elsewhere."""
    return any(
        not text[match.end() :].strip(" :.-\t") for match in _PERSONAL_LABEL.finditer(text)
    )


def _learned(pages: tuple[OcrPage, ...]) -> set[str]:
    """Words a document teaches as the student's own.

    Two layouts: the value on the SAME line/cell as its label ("Фамилия Иванов", "Surname:
    Aliyev"), and the value on the NEXT line, or the row below a row of labels -- a label
    printed with nothing else on it points at where its value is, one line or one row away.
    """
    words: set[str] = set()
    for page in pages:
        texts = [*page.lines, *(cell for table in page.tables for row in table for cell in row)]
        for text in texts:
            for label in _PERSONAL_LABEL.finditer(text):
                value = _VALUE_AFTER_LABEL.match(text, label.end())
                if value is not None:
                    words |= {_fold(word) for word in value.groups() if word}
        for index, line in enumerate(page.lines[:-1]):
            if _label_ends(line):
                words |= {_fold(word) for word in _WORD.findall(page.lines[index + 1])}
        for table in page.tables:
            for index, row in enumerate(table[:-1]):
                if any(_has_label(cell) for cell in row):
                    words |= {
                        _fold(word) for cell in table[index + 1] for word in _WORD.findall(cell)
                    }
    return words


def _names_in(text: str, names: frozenset[str]) -> bool:
    # Two of the student's name words, never one: "Ali" alone is also Azerbaijani for "higher",
    # and "Ali riyaziyyat" is a course.
    found = names & {_fold(word) for word in re.findall(r"\w+", text)}
    return bool(names) and len(found) >= min(2, len(names))


def _minimised(pages: tuple[OcrPage, ...], names: frozenset[str]) -> tuple[
    list[str], list[list[list[str]]], list[list[list[float | None]]]
]:
    pages = _normalised(pages)
    names = names | _learned(pages)
    lines: list[str] = []
    skip_next = False
    for line in (line for page in pages for line in page.lines):
        consumed = skip_next
        skip_next = _label_ends(line)
        if consumed:
            continue
        if _has_label(line) or _ID_NUMBER.search(line) or _names_in(line, names):
            continue
        lines.append(line)
    tables: list[list[list[str]]] = []
    confidences: list[list[list[float | None]]] = []
    for page in pages:
        # No grid (a text-layer page, or a caller that never set one): no cell has a doubt.
        page_conf = page.cell_confidence or tuple(
            tuple(tuple(None for _ in row) for row in table) for table in page.tables
        )
        for table, table_conf in zip(page.tables, page_conf, strict=True):
            kept: list[list[str]] = []
            kept_conf: list[list[float | None]] = []
            drop_next = False
            for row, row_conf in zip(table, table_conf, strict=True):
                labelled = any(_has_label(cell) for cell in row)
                # A date alone does not drop a course row -- an exam-date column is ordinary
                # (review round 2, item 1: dropping the row emptied every course after it). The
                # date is masked the same way a six-digit ID is; only a label, a name match, or
                # sitting under a row of labels drops the whole row.
                should_drop = drop_next or labelled or _names_in(" ".join(row), names)
                drop_next = labelled
                if should_drop:
                    continue
                kept.append([_ID_NUMBER.sub("#", _DATE.sub("#", cell)) for cell in row])
                kept_conf.append(list(row_conf))
            if kept:
                tables.append(kept)
                confidences.append(kept_conf)
    return lines, tables, confidences


def _candidates(lines: list[str]) -> tuple[list[tuple[str, int]], list[tuple[date, str, int]]]:
    """Numbers and dates printed on the lines, each with the index of its line."""
    numbers: list[tuple[str, int]] = []
    dates: list[tuple[date, str, int]] = []
    for index, line in enumerate(lines):
        for match in _DATE.finditer(line):
            if match[1]:
                day, month, year = match[1], match[2], match[3]  # day first: AZ, TR, RU
            else:
                day, month, year = match[6], match[5], match[4]
            try:
                dates.append((date(int(year), int(month), int(day)), match[0], index))
            except ValueError:
                continue
        numbers += [(found, index) for found in _NUMBER.findall(_DATE.sub(" ", line))]
    return numbers[:_MAX_CANDIDATES], dates[:_MAX_DATES]


def _groups(kinds: list[str]) -> list[list[int]]:
    """A table's columns in course blocks: one block, or one per semester printed side by side.

    Only a second title column starts a block, and it starts where the first block's layout puts
    it: [code, title, credits, grade, code, title, credits, grade] splits before the second code.
    A repeated credits column does not split -- NKU prints ECTS and local credits side by side
    (measured 2026-09-26), and the first, ECTS, is the one read. Nor does a split leaving a side
    with no credits or grade column: that is a course name printed twice, one column per
    language, and splitting there read every course twice, half the copies without credits.
    """
    titles = [position for position, kind in enumerate(kinds) if kind == "course_title"]
    starts = [0, *(title - titles[0] for title in titles[1:])] if titles else [0]
    ends = [*starts[1:], len(kinds)]
    blocks: list[list[int]] = []
    for start, end in zip(starts, ends, strict=True):
        block = list(range(start, end))
        if blocks and not (_scored(blocks[-1], kinds) and _scored(block, kinds)):
            blocks[-1] += block
        else:
            blocks.append(block)
    return blocks


def _scored(block: list[int], kinds: list[str]) -> bool:
    return any(kinds[position] in ("credits", "grade") for position in block)


@dataclass(frozen=True)
class _Cut:
    cells: list[str]
    #: column kind -> position in `cells`, first occurrence
    where: dict[str, int]
    #: Azure's confidence per cell, aligned with `cells`; None where there is none.
    confs: list[float | None]

    def cell(self, kind: str) -> str:
        return self.cells[self.where[kind]] if kind in self.where else ""

    def doubtful(self, kinds: tuple[str, ...], below: float) -> bool:
        return any(
            (conf := self.confs[self.where[kind]]) is not None and conf < below
            for kind in kinds
            if kind in self.where
        )


def _course_rows(
    tables: list[list[list[str]]],
    kinds: list[list[str]],
    confidences: list[list[list[float | None]]],
) -> list[_Cut]:
    """Every row of every course block, block after block, so a side-by-side layout reads its
    left semester to the end before its right one."""
    cut: list[_Cut] = []
    for table, table_kinds, table_conf in zip(tables, kinds, confidences, strict=True):
        for group in _groups(table_kinds):
            where: dict[str, int] = {}
            for offset, position in enumerate(group):
                where.setdefault(table_kinds[position], offset)
            if "course_title" not in where:
                continue
            cut += [
                _Cut(
                    [row[position] for position in group],
                    where,
                    [conf[position] for position in group],
                )
                for row, conf in zip(table, table_conf, strict=True)
            ]
    return cut


def _unsure(answer: Answer) -> bool:
    return answer.confidence < questions.UNSURE_BELOW


def _norm(title: str) -> str:
    return " ".join(title.casefold().split())


def _clip(text: str, limit: int) -> str:
    # Verbatim, and cut only where a field cannot hold more: never text the page did not print.
    return text[:limit]


def check_gates() -> None:
    """The provider check and both launch gates (spec T19, §3.1, §4), before any file is opened.

    No generative model reads a transcript (spec T19). DECISIONS_PROVIDER is a shared mapping
    another decision could repoint: a `transcript` entry, or a `default` naming anything but
    `typesafe`, refuses here, before the document is opened, so a transcript's minimised content
    can never be routed to an OpenAI or Anthropic adapter.
    """
    provider = provider_for(questions.DECISION)
    if provider != "typesafe":
        raise DecisionsUnavailable(
            f"transcript decisions must go through typesafe, DECISIONS_PROVIDER routes them "
            f"to {provider!r}"
        )
    if not settings.TRANSCRIPT_JEV_ENABLED:
        # Real students' transcripts go to Jev, through OpenRouter, only after TypeSafe's
        # DPA is accepted and OpenRouter's terms are reviewed (spec
        # 2026-09-25-tailored-programme-finding-design.md §3.1 launch gate). Checked here,
        # before the document is even opened, for the same reason as the provider check
        # above: a misconfiguration must never be able to route real transcript content
        # through before that review is done. A distinct exception from the provider-routing
        # DecisionsUnavailable above: transcript_pages.read_upload fails the upload at once
        # and transcript_pages.assemble waits an hour, rather than spending retries on a gate
        # no retry can open.
        raise TranscriptReadingDisabled(
            "transcript reading is off: TRANSCRIPT_JEV_ENABLED is not set"
        )
    if not settings.TRANSCRIPT_AZURE_ENABLED:
        # Spec 2026-10-03-transcript-reader-redesign §4: no real transcript reaches Azure until
        # Microsoft's data-processing terms are reviewed. Same handling as the Jev gate above.
        raise TranscriptReadingDisabled(
            "transcript reading is off: TRANSCRIPT_AZURE_ENABLED is not set"
        )


def read_from_pages(
    pages: tuple[OcrPage, ...], names: frozenset[str], *, client: Client | None = None
) -> Reading:
    """Turn read pages into a Reading: minimise, ask Jev, copy what it chose (module docstring)."""
    lines, tables, confidences = _minimised(pages, names)
    lines = lines[:_MAX_CANDIDATES]
    numbers, dates = _candidates(lines)

    # A column is shown by rows printing at least half their cells. A heading printing one cell
    # ("1 kurs", "I semestr") sits in the title column and made Jev read it as a semester column
    # in four runs of four (the photographed specimen, 2026-09-26); every row is still cut and
    # asked about below.
    samples = [
        [row for row in table if 2 * sum(bool(cell.strip()) for cell in row) >= len(row)] or table
        for table in tables
    ]
    columns = [
        (t, position, [row[position] for row in samples[t]][:_CELLS_PER_COLUMN])
        for t, table in enumerate(tables)
        for position in range(len(table[0]))
        if any(row[position] for row in table)
    ]
    first = ask(
        {
            "columns": {f"c{k}": {"cells": cells} for k, (_, _, cells) in enumerate(columns)},
            "lines": [{"id": f"l{i}", "text": line} for i, line in enumerate(lines)],
            "numbers": [
                {"id": f"n{i}", "text": text, "line": f"l{k}"}
                for i, (text, k) in enumerate(numbers)
            ],
            "dates": [
                {"id": f"d{i}", "text": text, "line": f"l{k}"}
                for i, (_, text, k) in enumerate(dates)
            ],
        },
        {f"column:{k}": questions.column(k) for k in range(len(columns))}
        | questions.transcript(
            [f"l{i}" for i in range(len(lines))],
            [f"n{i}" for i in range(len(numbers))],
            [f"d{i}" for i in range(len(dates))],
        ),
        decision=questions.DECISION,
        # Never cached: DecisionRecord is shared-catalog data, and this state is one
        # student's transcript.
        record=False,
        client=client,
    )
    doubts: dict[Highlight, None] = {}
    kinds = [["other"] * len(table[0]) for table in tables]
    for k, (t, position, _) in enumerate(columns):
        kinds[t][position] = str(first[f"column:{k}"].value)
        if _unsure(first[f"column:{k}"]):
            doubts[Highlight(kind="unsure", scope="transcript", ref="columns")] = None
    for qid, answer in first.items():
        if not qid.startswith("column:") and _unsure(answer):
            doubts[Highlight(kind="unsure", scope="field", ref=qid)] = None

    cut = _course_rows(tables, kinds, confidences)
    if len(cut) > _MAX_ROWS:
        raise UnsupportedUpload("more table rows than one transcript holds")
    labels: dict[str, Answer] = {}
    for start in range(0, len(cut), _ROWS_PER_REQUEST):
        batch = cut[start : start + _ROWS_PER_REQUEST]
        answered = ask(
            {"rows": {f"r{i}": row.cells for i, row in enumerate(batch)}},
            {
                f"{name}:{i}": build(i)
                for i in range(len(batch))
                for name, build in (
                    ("kind", questions.row_kind),
                    ("in_progress", questions.in_progress),
                    ("failed", questions.failed),
                )
            },
            decision=questions.DECISION,
            record=False,
            client=client,
        )
        for qid, answer in answered.items():
            name, local = qid.split(":")
            labels[f"{name}:{start + int(local)}"] = answer
            if _unsure(answer):
                doubts[Highlight(kind="unsure", scope="row", ref=str(start + int(local)))] = None

    course_titles = [
        _norm(row.cell("course_title")) if labels[f"kind:{i}"].value == "course" else ""
        for i, row in enumerate(cut)
    ]
    rows = []
    for i, row in enumerate(cut):
        kind = cast(RowKind, labels[f"kind:{i}"].value)
        status: CourseStatus | None = None
        if kind == "course":
            if labels[f"failed:{i}"].value is True and course_titles[i] in course_titles[i + 1 :]:
                status = "SUPERSEDED_ATTEMPT"
            elif labels[f"in_progress:{i}"].value is True:
                status = "IN_PROGRESS"
            else:
                status = "COMPLETED"
        if kind == "course" and not row.cell("course_title").strip():
            # A course row with no title is a cut that went wrong (a merged or shifted row);
            # it stays in the credit sums, and the student is shown where.
            doubts[Highlight(kind="unsure", scope="row", ref=str(i))] = None
        if kind == "course" and row.doubtful(
            ("credits", "grade"), settings.TRANSCRIPT_LOW_CONFIDENCE_BELOW
        ):
            doubts[Highlight(kind="low_confidence", scope="row", ref=str(i))] = None
        rows.append(
            Row(i, kind, row.cell("course_title"), row.cell("credits"), row.cell("grade"), status)
        )

    def picked(qid: str) -> str | None:
        answer = first.get(qid)
        return None if answer is None or answer.value == questions.NONE else str(answer.value)

    def line(qid: str, limit: int) -> str:
        chosen = picked(qid)
        if chosen is None:
            return ""
        text = lines[int(chosen[1:])]
        label, _, value = text.partition(":")
        return _clip((value if value.strip() else label).strip(), limit)

    def printed(qid: str) -> str | None:
        chosen = picked(qid)
        return None if chosen is None else numbers[int(chosen[1:])][0]

    def dated(qid: str) -> date | None:
        chosen = picked(qid)
        return None if chosen is None else dates[int(chosen[1:])][0]

    courses = tuple(
        TranscriptCourse(
            title=_clip(row.title, 200),
            credits=number(row.credits),
            grade=_clip(row.grade, 50) or None,
            status=row.status,
        )
        for row in rows
        if row.kind == "course" and row.status is not None and row.title.strip()
    )
    if len(courses) > 150:
        raise UnsupportedUpload("more courses than one transcript holds")
    country = picked("country")
    if country is not None and country not in ISO_3166_ALPHA2_CODES:
        # Jev's own options are exactly this list plus "none" (transcript_questions.column), so
        # an off-list pick is a provider misbehaving, not a country the transcript names -- it is
        # treated the same as an unsure answer, never copied into a two-letter-pattern field.
        doubts[Highlight(kind="unsure", scope="field", ref="country")] = None
        country = None
    return Reading(
        content=TranscriptContent(
            institution=line("institution", 200),
            country_code=country or "",
            qualification=line("qualification", 100),
            field=line("field", 200),
            overall_grade=printed("overall_grade"),
            grading_scale=printed("grading_scale"),
            credit_unit=cast(CreditUnit, first["credit_system"].value),
            courses=courses,
            completed_on=dated("completed_on"),
            expected_completion=dated("expected_completion"),
        ),
        rows=tuple(rows),
        total_credits_line=printed("total_credits"),
        doubts=tuple(doubts),
    )


def _ects(content: TranscriptContent, course: TranscriptCourse) -> Decimal | None:
    if course.credits is None:
        return None
    ects = to_ects(
        course.credits, content.credit_unit, local_credits_per_year=content.local_credits_per_year
    )
    # The profile's CourseRecord holds at most 100. A larger figure has already failed the range
    # check the student sees; the record carries "unknown" rather than refusing the whole reading.
    return ects if ects is not None and ects <= 100 else None


def academic_record(content: TranscriptContent) -> dict[str, object]:
    courses = [
        {
            "title": course.title,
            "ects": None if (ects := _ects(content, course)) is None else str(ects),
            "grade": course.grade,
            "in_progress": course.status == "IN_PROGRESS",
        }
        for course in content.courses
        if course.status != "SUPERSEDED_ATTEMPT"
    ]
    payload = {
        "institution": content.institution,
        "country_code": content.country_code,
        "qualification": content.qualification,
        "field": content.field,
        "grade": content.overall_grade or "not stated",
        "grading_scale": content.grading_scale or "not stated",
        "completed_on": content.completed_on,
        "expected_completion": content.expected_completion,
        "courses": courses,
    }
    return cast("dict[str, object]", json.loads(json.dumps(payload, default=str)))
