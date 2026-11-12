"""The transcript check (plan 3b, spec §6.3): the doubtful cells a student is asked about, one by
one, each with its reason in plain words. Unflagged cells are never asked about -- and never
labelled "verified" either."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.utils import timezone
from pydantic import ValidationError

from apps.accounts.forms import normalize_country_code
from apps.accounts.models import StudentProfileVersion
from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import AcademicRecord, StudentProfileSnapshot
from apps.reference_data import ISO_3166_ALPHA2_CODES
from apps.tenancy.models import Membership

from .degree_match import match_record, same_degree
from .fact_writer import tip_of
from .models import TranscriptReading, VerifiedFact
from .transcript import (
    Highlight,
    Reading,
    Row,
    TranscriptContent,
    academic_record,
    courses_of,
    number,
    row_from_json,
)
from .transcript_checks import highlights
from .verification import unsuperseded_facts

logger = logging.getLogger(__name__)

Cell = Literal["title", "credits", "grade", "field", "degree"]

#: The cells of a flagged row the student is asked about -- and shown a picture of
#: (transcript_pages cuts a crop for each, plan 3a). A semester or transcript total is about a
#: sum, not one cell, so it has none.
DOUBTFUL_CELLS: dict[str, tuple[Cell, ...]] = {
    "low_confidence": ("credits", "grade"),
    "credit_out_of_range": ("credits",),
    "grade_above_scale": ("grade",),
    "unsure": ("title",),
    "mixed_script": ("title",),
}

REASONS: dict[str, str] = {
    "low_confidence": "We weren't sure we read this correctly.",
    "credit_total_mismatch": (
        "The credits in this semester add up to {sum}; the transcript prints {printed}."
    ),
    "credit_total_mismatch_total": (
        "The course credits add up to {sum}; the transcript prints {printed} as the total."
    ),
    "grade_above_scale": "This grade is above the scale printed on the transcript ({scale}).",
    "credit_out_of_range": "This credit value is unusually large or small.",
    "unsure": "We weren't sure what this row is.",
    "mixed_script": "This text mixes Latin and Cyrillic letters.",
    "blank": "We couldn't read your {label} from the transcript. Type it here.",
    "blank_country": "Which country is your university in?",
}

#: A field highlight's ref (the reader's question id) -> where the reader's value is kept: the
#: four headline numbers in `key_numbers` as printed, every other field in `record`
#: (transcript.academic_record), whose own key differs for the country.
_KEY_NUMBERS = {
    "overall_grade": "overall_grade",
    "grading_scale": "grading_scale",
    "total_credits": "total_credits",
    "credit_system": "credit_unit",
}
_RECORD_KEYS = {"country": "country_code"}

_CELL_ORDER = {"field": 0, "title": 1, "credits": 2, "grade": 3}


@dataclass(frozen=True)
class CheckItem:
    #: "<row index>:<cell>" for a row, "field:<name>" for a field of the record,
    #: "semester:<row index>" for a semester total, "total:<ref>" for the transcript's total,
    #: "degree:same" for "is this the degree you already have?" (Task 7).
    ref: str
    row_title: str
    cell: Cell
    reader_value: str
    reason: str
    #: The key of `TranscriptReading.crops` holding this cell's picture, if one was cut.
    crop_ref: str | None
    #: A record field the reading left blank: there is nothing to match, so the student types it.
    typed_only: bool = False


def _total(courses: list[Row]) -> str:
    total = sum((c for row in courses if (c := number(row.credits)) is not None), Decimal(0))
    return str(total)


def _items(
    highlight: Highlight,
    rows: dict[int, Row],
    effective: dict[int, Row],
    reading: TranscriptReading,
) -> list[tuple[tuple[int, int, int], CheckItem]]:
    """Each item a highlight asks, with its place in reading order: the record's fields
    first, then the rows by index, then the transcript's total. The value shown is the
    reader's (`rows`); a sum in a reason counts the student's fixes (`effective`)."""
    kind = highlight.kind
    if highlight.scope == "field":
        name = highlight.ref
        if name in _KEY_NUMBERS:
            value = reading.key_numbers.get(_KEY_NUMBERS[name])
        else:
            value = reading.record.get(_RECORD_KEYS.get(name, name))
        # "unsure" reads "what this row is"; on a field it is the reader's doubt about a value.
        reason = REASONS["low_confidence" if kind == "unsure" else kind].format(
            scale=reading.key_numbers.get("grading_scale") or ""
        )
        item = CheckItem(
            f"field:{highlight.ref}", "", "field", str(value or ""), reason, None
        )
        return [((0, 0, 0), item)]
    if kind == "credit_total_mismatch":
        if highlight.scope == "semester":
            index = int(highlight.ref)
            courses: list[Row] = []
            for row in sorted(effective.values(), key=lambda r: r.index):
                if row.index >= index:
                    break
                if row.kind in ("semester_heading", "semester_total"):
                    courses = []
                elif row.kind == "course":
                    courses.append(row)
            total = rows[index]
            reason = REASONS[kind].format(sum=_total(courses), printed=effective[index].credits)
            item = CheckItem(
                f"semester:{index}", total.title, "credits", total.credits, reason, None
            )
            return [((1, index, 0), item)]
        everything = [row for row in effective.values() if row.kind == "course"]
        if highlight.ref.isdigit():
            index = int(highlight.ref)
            title, read, printed = rows[index].title, rows[index].credits, effective[index].credits
        else:  # a total printed outside any table: the line the summary's numbers show
            title, read = "", str(reading.key_numbers.get("total_credits") or "")
            printed = _fixes(reading).get("total_credits", read)
        reason = REASONS["credit_total_mismatch_total"].format(
            sum=_total(everything), printed=printed)
        item = CheckItem(f"total:{highlight.ref}", title, "credits", read, reason, None)
        return [((2, 0, 0), item)]
    if highlight.scope != "row":
        # "not checked" and an unsure column layout are notes on the summary: neither names a
        # value the student could match or fix.
        return []
    flagged = rows.get(int(highlight.ref))
    if flagged is None:
        # Only a reading stored between highlights and rows being kept (migrations 0022/0023).
        logger.warning("highlight names row %s, which reading %s does not store",
                       highlight.ref, reading.id)
        return []
    found = []
    for cell in DOUBTFUL_CELLS.get(kind, ()):
        ref = f"{flagged.index}:{cell}"
        item = CheckItem(
            ref, flagged.title, cell, getattr(flagged, cell), REASONS[kind],
            ref if ref in reading.crops else None,
        )
        found.append(((1, flagged.index, _CELL_ORDER[cell]), item))
    return found


def check_items(reading: TranscriptReading) -> tuple[CheckItem, ...]:
    """One item per doubtful cell, in reading order. A cell two checks doubt is asked once,
    with the first check's reason. Once the student has fixed a value, the checks run again on
    the fixed values (spec §6.6): a fix that breaks a printed total is asked about again."""
    rows = {stored["index"]: row_from_json(stored) for stored in reading.rows}
    effective = {row.index: row for row in effective_rows(reading)}
    found: dict[str, tuple[tuple[int, int, int], CheckItem]] = {}
    for highlight in _current_highlights(reading):
        for place, item in _items(highlight, rows, effective, reading):
            found.setdefault(item.ref, (place, item))
    for name in _REQUIRED:
        # A blank the academic record cannot hold (final review, finding 1): the student types
        # it, or the reading could never be accepted.
        ref = f"field:{name}"
        if not str(reading.record.get(_RECORD_KEYS.get(name, name)) or "").strip():
            place, asked = found.get(ref, ((0, 0, 0), None))
            reason = REASONS["blank_country" if name == "country" else "blank"].format(
                label=FIELD_LABELS[name].lower())
            found[ref] = (place, replace(
                asked or CheckItem(ref, "", "field", "", reason, None),
                reader_value="", reason=reason, typed_only=True))
    degree = _degree_item(reading)
    if degree is not None:
        found[degree.ref] = ((-1, 0, 0), degree)
    return tuple(item for _, item in sorted(found.values(), key=lambda pair: pair[0]))


#: The record fields an academic record cannot leave blank (accounts.schemas.AcademicRecord).
_REQUIRED = ("institution", "country", "qualification", "field")

DEGREE = "degree:same"


@dataclass(frozen=True)
class _Candidate:
    """A degree the transcript may be: a ledger fact, or one the student typed in the
    questionnaire ("profile:<index>" -- typed degrees are not facts)."""

    key: str
    payload: dict[str, Any]
    where: str
    fact: VerifiedFact | None


def _profile_records(student_id: UUID) -> list[dict[str, Any]]:
    latest = (StudentProfileVersion.objects.filter(student_id=student_id, schema_version=3)
              .order_by("-version").first())
    history = latest.snapshot.get("academic_history") if latest is not None else None
    return [record for record in history or [] if isinstance(record, dict)]


def _as_fact(record: dict[str, Any]) -> dict[str, Any]:
    """A profile's academic record in an EDUCATION fact's keys, for the matcher."""
    return {"institution_original": record.get("institution"),
            "degree_as_awarded": record.get("qualification"), "country": record.get("country_code"),
            "end_date": record.get("completed_on") or record.get("expected_completion")}


def _candidate(reading: TranscriptReading) -> _Candidate | None:
    """The degree the student is asked about: the one they answered about, or the first the
    matcher is not sure of -- in the ledger first, then among the degrees typed in the
    questionnaire (spec audit P2: an English typed degree, an Azerbaijani transcript)."""
    if reading.student_id is None:
        return None
    given = reading.answers.get(DEGREE)
    key = str(given["value"]) if given is not None else None
    records = _profile_records(reading.student_id)
    if key is not None and key.startswith("profile:"):
        index = int(key.removeprefix("profile:"))
        if index >= len(records):
            return None
        return _Candidate(key, _as_fact(records[index]), "in your profile", None)
    if key is not None:
        fact = VerifiedFact.objects.filter(id=key, student_id=reading.student_id).first()
        return _Candidate(key, fact.payload, _where(fact), fact) if fact else None
    verdict, found = match_record(reading.student, reading.record)
    if verdict == "ask" and found is not None:
        return _Candidate(str(found.id), found.payload, _where(found), found)
    if verdict == "same":
        return None
    for index, record in enumerate(records):
        if same_degree(_as_fact(record), reading.record) == "ask":
            return _Candidate(f"profile:{index}", _as_fact(record), "in your profile", None)
    return None


def _where(fact: VerifiedFact) -> str:
    return "on your CV" if fact.source_ref.startswith("upload:") else "in your profile"


def _degree_item(reading: TranscriptReading) -> CheckItem | None:
    candidate = _candidate(reading)
    if candidate is None:
        return None
    payload = candidate.payload
    named = ", ".join(str(part) for part in (
        payload.get("degree_as_awarded"), payload.get("institution_original"),
        str(payload.get("end_date") or "")[:4],
    ) if part)
    where = candidate.where
    record = reading.record
    read = ", ".join(str(record.get(key)) for key in ("qualification", "institution")
                     if record.get(key))
    return CheckItem(DEGREE, named, "degree", read,
                     f"Is this the same degree as {named} {where}?", None)

_CHOICES = ("matches", "fix", "cant_read")
_DEGREE_CHOICES = ("same", "different")

#: Highlights code computes from the values, re-run on the student's fixes. The others --
#: "unsure", "low_confidence" -- are the reader's own doubts and stay whatever is typed.
_CHECKED = frozenset(
    {"credit_total_mismatch", "credit_total_not_checked", "grade_above_scale",
     "credit_out_of_range", "mixed_script"}
)

#: The record fields transcript_checks reads (ranges, mixed scripts, the total line). A fix
#: of any other -- the country, a date, the credit system -- re-runs nothing.
_CHECKED_FIELDS = frozenset(
    {"total_credits", "overall_grade", "grading_scale", "institution", "qualification", "field"}
)

#: The longest value each row cell holds (transcript.courses_of). A longer fix is refused, not
#: cut: the student's claim is stored as typed (spec §6.2).
_LIMITS = {"title": 200, "grade": 50}


def _cell(ref: str) -> tuple[int, str] | str:
    """The row cell -- (index, cell) -- or the record field a ref's value is in."""
    scope, _, rest = ref.partition(":")
    if scope == "field":
        return rest
    if scope in ("semester", "total"):
        return (int(rest), "credits") if rest.isdigit() else rest
    return int(scope), rest


def _fixes(reading: TranscriptReading) -> dict[Any, str]:
    return {
        _cell(ref): given["value"]
        for ref, given in reading.answers.items()
        if given["choice"] == "fix"
    }


def effective_rows(reading: TranscriptReading) -> list[Row]:
    """The reader's rows with each of the student's fixes applied. `reading.rows` itself is
    never changed: the reader's value stays beside the student's."""
    fixes = _fixes(reading)
    rows = []
    for stored in reading.rows:
        row = row_from_json(stored)
        rows.append(replace(
            row,
            title=fixes.get((row.index, "title"), row.title),
            credits=fixes.get((row.index, "credits"), row.credits),
            grade=fixes.get((row.index, "grade"), row.grade),
        ))
    return rows


def _content(reading: TranscriptReading, rows: list[Row]) -> TranscriptContent:
    """The reading's content again -- `record` and `key_numbers` with the student's field
    fixes applied, and the courses of `rows`."""
    record, numbers = reading.record, reading.key_numbers
    values = {
        **{name: record.get(_RECORD_KEYS.get(name, name)) for name in (
            "institution", "country", "qualification", "field", "completed_on",
            "expected_completion",
        )},
        **{name: numbers.get(key) for name, key in _KEY_NUMBERS.items()},
        **{name: value for name, value in _fixes(reading).items() if isinstance(name, str)},
    }
    return TranscriptContent(
        institution=values["institution"] or "",
        country_code=values["country"] or "",
        qualification=values["qualification"] or "",
        field=values["field"] or "",
        overall_grade=values["overall_grade"],
        grading_scale=values["grading_scale"],
        credit_unit=values["credit_system"],
        courses=courses_of(rows),
        completed_on=values["completed_on"],
        expected_completion=values["expected_completion"],
    )


def _total_line(reading: TranscriptReading, rows: list[Row]) -> str | None:
    """The total printed outside any table, if the reading had one: key_numbers keeps it as
    the total when one was printed, and an overall total row prints the same figure."""
    fixed = _fixes(reading).get("total_credits")
    if fixed is not None:
        return fixed
    total = reading.key_numbers.get("total_credits")
    if not reading.key_numbers.get("total_credits_printed") or total is None:
        return None
    overall = [row.credits for row in rows if row.kind == "overall_total"
               and number(row.credits) is not None]
    return None if overall and overall[-1] == total else total


def _current_highlights(reading: TranscriptReading) -> tuple[Highlight, ...]:
    stored = tuple(Highlight.model_validate(raw) for raw in reading.highlights)
    if not any(isinstance(cell, tuple) or cell in _CHECKED_FIELDS for cell in _fixes(reading)):
        return stored  # no fix touches a value a check reads
    rows = effective_rows(reading)
    doubts = tuple(h for h in stored if h.kind not in _CHECKED)
    return highlights(Reading(_content(reading, rows), tuple(rows), _total_line(reading, rows),
                              doubts))


def _open(reading: TranscriptReading) -> tuple[CheckItem, ...]:
    return tuple(item for item in check_items(reading) if item.ref not in reading.answers)


def answer(
    reading: TranscriptReading, ref: str, choice: str, value: str = ""
) -> tuple[CheckItem, ...]:
    """Record the student's answer to one item and return the items still open. A fixed
    credit re-opens every total: the sums it is part of changed."""
    if choice not in (_DEGREE_CHOICES if ref == DEGREE else _CHOICES):
        raise ValueError(f"unknown choice {choice!r}")
    value = value.strip() if choice == "fix" else ""
    if choice == "fix" and not value:
        raise ValueError("a fix needs the value the transcript shows")
    asked = {item.ref: item for item in check_items(reading)}
    if ref not in asked:
        raise ValueError(f"{ref!r} is not asked on this reading")
    if asked[ref].typed_only and choice != "fix":
        raise ValueError("this one is typed")
    if ref == "field:country" and choice == "fix":
        value = normalize_country_code(value) if len(value.strip()) > 2 else value.upper()
    if ref == DEGREE:
        candidate = _candidate(reading)
        if candidate is None:  # the degree went between reading the page and answering
            raise ValueError("that degree is gone")
        value = candidate.key
        given = {"choice": choice, "value": value, "at": timezone.now().isoformat()}
        reading.answers = {**reading.answers, ref: given}
        reading.save(update_fields=["answers"])
        return _open(reading)
    cell = _cell(ref)
    if choice == "fix" and cell == "total_credits" and number(value) is None:
        raise ValueError("credits must be a number")
    if choice == "fix" and cell == "country" and value not in ISO_3166_ALPHA2_CODES:
        # The record takes an active ISO code only (spec audit P3: "UK" passed the
        # two-letter pattern and then made accepting impossible).
        raise ValueError("not a country code")
    if choice == "fix" and isinstance(cell, tuple):
        if cell[1] == "credits" and number(value) is None:
            raise ValueError("credits must be a number")
        if len(value) > _LIMITS.get(cell[1], 200):
            raise ValueError("too long")
    answers = dict(reading.answers)
    if choice == "fix" and isinstance(cell, tuple) and not ref.startswith(("semester:", "total:")):
        answers = _without_sums(answers)
    answers[ref] = {"choice": choice, "value": value, "at": timezone.now().isoformat()}
    before, reading.answers = reading.answers, answers
    try:
        _content(reading, effective_rows(reading))
    except ValidationError as error:
        reading.answers = before
        raise ValueError("the record cannot hold that value") from error
    reading.save(update_fields=["answers"])
    return _open(reading)


def _without_sums(answers: dict[str, Any]) -> dict[str, Any]:
    """The answers without those on a semester or transcript total: a fixed course credit
    changed the sums they answered."""
    return {key: given for key, given in answers.items()
            if not key.startswith(("semester:", "total:"))}


def accept(reading: TranscriptReading, *, student: Membership) -> None:
    """The student continues with the reading: `accepted` becomes the academic record with
    their fixes applied. A cell they could not read keeps the reader's value and asks for a
    review -- it never blocks."""
    if reading.student_id != student.id:
        raise ValueError("not this student's reading")
    items = check_items(reading)
    if any(item.ref not in reading.answers for item in items):
        raise ValueError("unanswered")
    try:
        record = AcademicRecord.model_validate(
            academic_record(_content(reading, effective_rows(reading)))
        )
    except ValidationError as error:
        raise ValueError("the reading is not a valid academic record") from error
    unreadable_items = [item for item in items
                        if reading.answers[item.ref]["choice"] == "cant_read"]
    unreadable = [describe(item) for item in unreadable_items]
    if unreadable:
        note = "Couldn't read: " + ", ".join(unreadable)
        if note not in reading.review_reason:
            reading.review_reason = "\n".join(filter(None, [reading.review_reason, note]))[:500]
        reading.review_requested_at = reading.review_requested_at or timezone.now()
    reading.accepted = record.model_dump(mode="json")
    reading.save(update_fields=["accepted", "review_reason", "review_requested_at"])
    given = reading.answers.get(DEGREE)
    answered = (int(str(given["value"]).removeprefix("profile:"))
                if given is not None and given["choice"] == "same"
                and str(given["value"]).startswith("profile:") else None)
    _follow_profile(student, record, reading.record, answered)
    unread_rows = {int(cell[0]) for item in unreadable_items
                   if isinstance(cell := _cell(item.ref), tuple)}
    # record.courses holds the rows courses_of keeps, minus a failed attempt retaken
    # (academic_record): matched by place, so two courses of one title stay apart.
    kept = [row for row in effective_rows(reading)
            if row.kind == "course" and row.status is not None and row.title.strip()
            and row.status != "SUPERSEDED_ATTEMPT"]
    unread_courses = {place for place, row in enumerate(kept) if row.index in unread_rows}
    unread_fields = {cell for item in unreadable_items
                     if item.cell == "field" and isinstance(cell := _cell(item.ref), str)}
    _write_degree(reading, student, record, unread_courses, unread_fields)


#: A record field the student could not read -> the EDUCATION key it would fill: left out of
#: the fact, so no letter or portal takes it as the student's (final review, finding 2). The
#: degree's name stays: it is what identifies the degree.
_UNREAD_KEYS = {"overall_grade": "grade_native", "grading_scale": "grade_scale",
                "country": "country", "completed_on": "end_date",
                "expected_completion": "end_date"}


def _write_degree(
    reading: TranscriptReading, student: Membership, record: AcademicRecord,
    unread_courses: set[int], unread_fields: set[str],
) -> None:
    """The checked courses join the student's degree (owner decision 2026-10-15): inside the
    matching EDUCATION fact -- kept in the CV's wording, so it never prints twice -- or a new
    one from the transcript when the student holds no such degree. Once per reading."""
    ref = f"transcript:{reading.id}"
    if VerifiedFact.objects.filter(student=student, source_ref=ref).exists():
        return  # accepted before: the degree already carries these courses
    courses = [course.model_dump(mode="json") for course in record.courses]
    payload: dict[str, object] = {
        "courses": [c for i, c in enumerate(courses) if i not in unread_courses],
        "courses_unconfirmed": [c for i, c in enumerate(courses) if i in unread_courses],
    }
    given = reading.answers.get(DEGREE)
    fact: VerifiedFact | None
    if given is not None:
        candidate = _candidate(reading) if given["choice"] == "same" else None
        fact = candidate.fact if candidate is not None else None
    else:
        verdict, fact = match_record(student, record.model_dump(mode="json"))
        fact = fact if verdict == "same" else None
    now = timezone.now()
    if fact is not None:
        tip = tip_of(fact)
        aliases = [str(a) for a in tip.payload.get("aliases") or ()]
        aliases += [name for name in (record.institution, record.qualification)
                    if name not in aliases]
        # An unconfirmed CV claim is never built on: it stays the student's to confirm.
        confirmed = tip.confirmed_at is not None
        VerifiedFact.objects.create(
            student=student, category=VerifiedFact.Category.EDUCATION,
            payload={**tip.payload, **payload, "aliases": aliases},
            source_tier=tip.source_tier, source_ref=ref,
            confirmed_by=student if confirmed else None, confirmed_at=now if confirmed else None,
            supersedes=tip, created_by=student,
        )
        return
    end = record.completed_on or record.expected_completion
    stated = {
        "country": record.country_code,
        "end_date": end.isoformat() if end else None,
        "grade_native": record.grade, "grade_scale": record.grading_scale,
    }
    unread = {_UNREAD_KEYS[name] for name in unread_fields if name in _UNREAD_KEYS}
    rec_json = record.model_dump(mode="json")
    bridged = next(
        (
            f
            for f in unsuperseded_facts(student).filter(
                category=VerifiedFact.Category.EDUCATION,
                source_ref__startswith="profile-bridge:",
                confirmed_at__isnull=True,
            )
            if isinstance(f.payload, dict)
            and (
                same_degree(f.payload, rec_json) == "same"
                or (
                    given is not None
                    and given["choice"] == "same"
                    and str(given["value"]).startswith("profile:")
                    and f.source_ref.endswith(f":{str(given['value']).removeprefix('profile:')}")
                )
            )
        ),
        None,
    )
    VerifiedFact.objects.create(
        student=student, category=VerifiedFact.Category.EDUCATION,
        payload={
            "institution_original": record.institution,
            "degree_as_awarded": record.qualification,
            # academic_record writes "not stated" for a grade the transcript does not print.
            **{key: value for key, value in stated.items()
               if value != "not stated" and key not in unread},
            **payload, "aliases": [],
        },
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref=ref,
        confirmed_by=student, confirmed_at=now, supersedes=bridged, created_by=student,
    )


def _same_degree(held: AcademicRecord, *records: dict[str, Any]) -> bool:
    def fold(text: object) -> str:
        return " ".join(str(text or "").casefold().split())

    return any((fold(held.institution), fold(held.qualification))
               == (fold(r.get("institution")), fold(r.get("qualification"))) for r in records)


def _follow_profile(
    student: Membership, record: AcademicRecord, read: dict[str, Any], answered: int | None,
) -> None:
    """A profile finalized before the check holds the reader's record, or the degree the
    student typed: a new version carries the checked one instead -- the degree they said is
    the same one (`answered`), else one the names or the matcher are sure of. Never an edit:
    profile versions are immutable (accounts/0006)."""
    latest = (
        StudentProfileVersion.objects.filter(student=student, schema_version=3)
        .order_by("-version")
        .first()
    )
    if latest is None or not isinstance(latest.snapshot, dict):
        return  # the questionnaire pre-fills from `accepted` when it gets there
    raw_snap = (
        {k: v for k, v in latest.snapshot.items() if k != "weights"}
        if latest.snapshot.get("weights") == {}
        else latest.snapshot
    )
    try:
        snapshot = StudentProfileSnapshot.model_validate(raw_snap)
    except ValidationError:
        logger.warning("profile version %s does not validate; the check left it alone",
                       latest.id)
        return
    history = list(snapshot.academic_history)
    checked = record.model_dump(mode="json")
    for i, held in enumerate(history):
        if answered is not None:
            if i != answered:
                continue
        # The checked record or the reader's: a fixed name still finds the degree the
        # questionnaire took from the reading (final review, finding 4).
        elif not (_same_degree(held, checked, read)
                  or same_degree(_as_fact(held.model_dump(mode="json")), checked) == "same"):
            continue
        if record.completed_on is None and record.expected_completion is None:
            # An undated transcript: the questionnaire's graduation answer stays.
            record = record.model_copy(update={
                "completed_on": held.completed_on, "expected_completion": held.expected_completion,
            })
        if record == held:
            return
        history[i] = record
        updated_snapshot = snapshot.model_copy(update={"academic_history": tuple(history)})
        create_profile_version(
            student=student,
            snapshot=updated_snapshot,
            allow_identity_override=True,
        )
        from .profile_bridge import has_score_progression, request_score_progression_rebuild

        if has_score_progression(snapshot, updated_snapshot):
            request_score_progression_rebuild(student)
        return


def request_review(reading: TranscriptReading, reason: str) -> None:
    """"Something's wrong": someone looks at the reading. Never blocks accepting it."""
    # A second request adds to the first: someone reads both (spec audit).
    said = "\n".join(filter(None, [reading.review_reason, reason.strip()]))
    reading.review_reason = said[:500]
    reading.review_requested_at = timezone.now()
    reading.save(update_fields=["review_reason", "review_requested_at"])


#: What the summary notes without asking: neither names a value to match or fix.
NOTES: dict[tuple[str, str], str] = {
    ("credit_total_not_checked", ""): (
        "This transcript prints no credit total, so the credits were not added up against one."
    ),
    ("unsure", "columns"): (
        "We weren't sure which column holds the credits and which the grades — check them below."
    ),
}


def notes(reading: TranscriptReading) -> list[str]:
    return [NOTES[(raw["kind"], raw.get("ref", ""))] for raw in reading.highlights
            if (raw["kind"], raw.get("ref", "")) in NOTES]


def transcript_to_check(student: Membership) -> TranscriptReading | None:
    """The student's newest reading, while it is unaccepted. An accepted newest reading stays
    the record; an older unaccepted one was superseded and is never offered."""
    reading = TranscriptReading.objects.filter(student=student).order_by("-created_at").first()
    return reading if reading is not None and reading.accepted is None else None


def fixed_cells(reading: TranscriptReading) -> set[tuple[int, str]]:
    """The (row index, cell) pairs the student changed."""
    return {cell for cell in _fixes(reading) if isinstance(cell, tuple)}


def checked_numbers(reading: TranscriptReading) -> dict[str, Any]:
    """`key_numbers` with the student's fixes to them applied."""
    fixes = _fixes(reading)
    return {**reading.key_numbers, **{key: fixes[name] for name, key in _KEY_NUMBERS.items()
                                      if name in fixes}}


def review_requested(student: Membership) -> TranscriptReading | None:
    """The student's latest transcript review request, for the person who looks at it."""
    return (
        TranscriptReading.objects.filter(student=student, review_requested_at__isnull=False)
        .order_by("-review_requested_at")
        .first()
    )


#: What a card calls the value it asks about (the page's label, never a code).
FIELD_LABELS = {
    "institution": "University", "country": "Country", "qualification": "Degree",
    "field": "Field of study", "overall_grade": "Overall grade", "grading_scale": "Grading scale",
    "credit_system": "Credit system", "completed_on": "Graduation date",
    "expected_completion": "Expected graduation", "total_credits": "Total credits",
}
_CELL_LABELS = {"title": "Course name", "credits": "Credits", "grade": "Grade"}


def label(item: CheckItem) -> str:
    """"Credits", "Field of study", "Semester total": what the student compares."""
    scope, _, name = item.ref.partition(":")
    if scope == "field":
        return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())
    if scope == "semester":
        return "Semester total"
    if scope == "total":
        return "Total credits"
    return _CELL_LABELS.get(item.cell, item.cell)


def describe(item: CheckItem) -> str:
    """What one card was about, in words: "Physics — Grade", "Field of study"."""
    if item.cell == "degree":
        return "Same degree as on your CV?"
    if item.cell == "field" or not item.row_title:
        return label(item)
    return f"{item.row_title} — {label(item)}"


def degree_line(reading: TranscriptReading) -> str:
    """"BSc in Physics — Baku State University, 2025": which degree the student is checking,
    with their own fixes to its fields."""
    fixes = {name: value for name, value in _fixes(reading).items() if isinstance(name, str)}
    record = {**reading.record, **{_RECORD_KEYS.get(k, k): v for k, v in fixes.items()}}
    degree = str(record.get("qualification") or "").strip()
    field = str(record.get("field") or "").strip()
    named = f"{degree} in {field}" if degree and field else degree or field
    year = str(record.get("completed_on") or record.get("expected_completion") or "")[:4]
    where = ", ".join(p for p in (str(record.get("institution") or "").strip(), year) if p)
    return " — ".join(p for p in (named, where) if p)


def reopen(reading: TranscriptReading, ref: str) -> None:
    """Take an answer back ("Back", or "Change" on the summary): the item is asked again. A
    course credit fix taken back changes the sums, so their answers go too, as in `answer`."""
    if ref not in reading.answers:
        raise ValueError(f"{ref!r} is not answered")
    answers = dict(reading.answers)
    given = answers.pop(ref)
    cell = _cell(ref) if ref != DEGREE else None
    if given["choice"] == "fix" and isinstance(cell, tuple) \
            and not ref.startswith(("semester:", "total:")):
        answers = _without_sums(answers)
    reading.answers = answers
    reading.save(update_fields=["answers"])


def last_answered(reading: TranscriptReading) -> str | None:
    """The answer "Back" takes back: the latest one given."""
    if not reading.answers:
        return None
    latest: str = max(reading.answers, key=lambda ref: str(reading.answers[ref].get("at", "")))
    return latest


def accepted_reading(student: Membership) -> TranscriptReading | None:
    """The transcript the student last checked: the newest accepted reading."""
    return (TranscriptReading.objects.filter(student=student, accepted__isnull=False)
            .order_by("-created_at").first())


def cards(items: tuple[CheckItem, ...]) -> list[list[CheckItem]]:
    """The cards the student sees: a row's doubtful cells with one reason share a card -- the
    reader doubts the row, not one cell, so asking credits and grade apart doubles the taps
    (spec audit: three doubtful rows made six cards). Everything else is a card of its own."""
    grouped: dict[tuple[str, str], list[CheckItem]] = {}
    for item in items:
        row = item.ref.partition(":")[0]
        key = (row, item.reason) if row.isdigit() else (item.ref, "")
        grouped.setdefault(key, []).append(item)
    return list(grouped.values())
