"""Which document each application needs, and where the student stands (spec §6).

`build_table` is pure: rows in, a table out. `table_for` is the one function
that queries, and it reads tenant tables only -- the requirements are the copy
capture_requirements stored on the Application, never ProgramStatement.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from apps.mailbox.models import MailSignal
    from apps.portals.models import Application
    from apps.tenancy.models import Membership


class Cell(StrEnum):
    NOT_NEEDED = "not needed"
    MISSING = "missing"
    UPLOADED = "uploaded"
    #: Scanned clean, upload check pending (Task 14). Shown so the student knows the
    #: file arrived; neither held (no Submit) nor missing (not asked for again).
    CHECKING = "checking…"
    APPROVED = "approved"
    CERTIFIED = "certified copy needed"


#: Rows in reading order: (kind, label). Kinds are concierge.UPLOAD_KINDS or,
#: for the generated documents, DocumentDraft.Kind.
ROWS: tuple[tuple[str, str], ...] = (
    ("PASSPORT", "Passport"),
    ("TRANSCRIPT", "Transcript"),
    ("DIPLOMA", "Diploma"),
    ("LANGUAGE_CERTIFICATE", "Language certificate"),
    ("CV", "CV"),
    ("MOTIVATION_LETTER", "Motivation letter"),
    ("RECOMMENDATION", "Recommendation letters"),
)
EXPIRING = frozenset({"PASSPORT", "LANGUAGE_CERTIFICATE"})
#: The cells a document fills, and so the only ones Submit document may send.
SENDABLE = frozenset({Cell.UPLOADED, Cell.APPROVED})
_WANTING = frozenset({Cell.MISSING, Cell.CERTIFIED})

# ponytail: keyword match over the programme's REQUIRED sentences and the mail's
# document name. It misses a requirement worded unlike these, and a sentence
# naming two documents marks both. Upgrade path: have the statement reader label
# the document kind a sentence names.
_WORDS: dict[str, re.Pattern[str]] = {
    "PASSPORT": re.compile(r"\bpassport", re.I),
    "TRANSCRIPT": re.compile(r"\btranscript|\brecord of (?:study|studies|grades)", re.I),
    "DIPLOMA": re.compile(r"\bdiploma|\bdegree certificate|\bbachelor'?s certificate", re.I),
    "LANGUAGE_CERTIFICATE": re.compile(
        r"\bielts\b|\btoefl\b|\blanguage (?:certificate|proficiency|test)|\bcefr\b"
        r"|\bproof of english|\benglish (?:language )?(?:proficiency|skills)", re.I
    ),
    "CV": re.compile(r"\bcv\b|\bcurriculum vitae\b|\br[ée]sum[ée]\b", re.I),
    "MOTIVATION_LETTER": re.compile(
        r"\bmotivation\b|\bstatement of purpose\b|\bpersonal statement\b|\bcover letter\b"
        r"|\bletter of intent\b",
        re.I,
    ),
    "RECOMMENDATION": re.compile(
        r"\brecommendation\b|\bletters? of reference|\breference letters?"
        r"|\breferees?\b|\b(?:two|three|\d|academic|professional)\s+references\b",
        re.I,
    ),
}
_CERTIFIED = re.compile(r"\bcertified\b|\bnotari[sz]ed\b|\bapostille\b|\battested\b", re.I)


def kinds_named(text: str) -> set[str]:
    return {kind for kind, pattern in _WORDS.items() if pattern.search(text)}


@dataclass(frozen=True)
class ApplicationNeeds:
    application_id: UUID
    title: str
    #: What to send, in the sources' own words: kit requirements, mail requests.
    sentences: tuple[str, ...]


@dataclass(frozen=True)
class Held:
    kind: str
    state: Cell
    expires_on: date | None = None
    #: Set for a document that belongs to one application (a letter, a CV
    #: tailored to its programme); None for one every application may use.
    application_id: UUID | None = None
    document_id: UUID | None = None
    #: "upload" (DocumentVersion) or "draft" (DocumentDraft): what Submit sends.
    source: str = "upload"
    #: A certified copy. Nothing records this yet, so no upload satisfies a
    #: "certified copy needed" cell; the cell stays CERTIFIED.
    certified: bool = False


@dataclass(frozen=True)
class Row:
    kind: str
    label: str
    cells: tuple[Cell, ...]
    expires_on: date | None


@dataclass(frozen=True)
class Table:
    columns: tuple[ApplicationNeeds, ...]
    rows: tuple[Row, ...]
    held: tuple[Held, ...]

    def _index(self, application_id: UUID) -> int | None:
        """None for an application with no column (a withdrawn one; board_for)."""
        return next(
            (i for i, c in enumerate(self.columns) if c.application_id == application_id), None
        )

    def missing_for(self, application_id: UUID) -> tuple[str, ...]:
        index = self._index(application_id)
        if index is None:
            return ()
        return tuple(sorted(row.label for row in self.rows if row.cells[index] in _WANTING))

    def counts_for(self, application_id: UUID) -> tuple[int, int]:
        """(held, needed) for one application: "Documents 4/6" on the card."""
        index = self._index(application_id)
        if index is None:
            return 0, 0
        cells = [row.cells[index] for row in self.rows if row.cells[index] != Cell.NOT_NEEDED]
        return sum(1 for cell in cells if cell in SENDABLE), len(cells)

    def held_for(self, kind: str, application_id: UUID) -> Held | None:
        """What this application's cell for `kind` shows: its own document, else a general one.

        Not necessarily sendable: a re-upload still being checked comes back as a
        Cell.CHECKING entry when nothing usable is held. Submit sends only an UPLOADED or
        APPROVED one."""
        index = self._index(application_id)
        if index is None:
            return None
        needs_certified = _needed(self.columns[index]).get(kind, False)
        usable = [h for h in self.held if h.kind == kind and (h.certified or not needs_certified)]
        own = next((h for h in usable if h.application_id == application_id), None)
        return own or next((h for h in usable if h.application_id is None), None)


def _needed(column: ApplicationNeeds) -> dict[str, bool]:
    """kind -> whether a certified copy is asked for, for every kind named."""
    out: dict[str, bool] = {}
    for sentence in column.sentences:
        # "Certified copies of diploma and transcript; a CV": the word binds
        # only the clause it sits in.
        for clause in sentence.split(";"):
            certified = bool(_CERTIFIED.search(clause))
            for kind in kinds_named(clause):
                out[kind] = out.get(kind, False) or certified
    return out


def build_table(columns: Sequence[ApplicationNeeds], held: Iterable[Held]) -> Table:
    held_rows = tuple(held)
    table = Table(tuple(columns), (), held_rows)
    wanted = [_needed(column) for column in columns]
    rows = []
    for kind, label in ROWS:
        cells = []
        for column, needs in zip(columns, wanted, strict=True):
            if kind not in needs:
                cells.append(Cell.NOT_NEEDED)
            else:
                mine = table.held_for(kind, column.application_id)
                if mine is not None:
                    cells.append(mine.state)
                else:
                    cells.append(Cell.CERTIFIED if needs[kind] else Cell.MISSING)
        general = next((h for h in held_rows if h.kind == kind and h.application_id is None), None)
        expires = general.expires_on if general is not None and kind in EXPIRING else None
        rows.append(Row(kind, label, tuple(cells), expires))
    return Table(tuple(columns), tuple(rows), held_rows)


def vouched(signal: MailSignal) -> bool:
    """A document request that may add a requirement: from trusted mail, or one the
    student named themselves -- a metadata-tier message, or one whose classification
    gave up, since nothing but the student labels either. Anything else is a
    stranger's say-so: shown as unverified, never a cell (``signal.connection`` is
    read, so select_related it)."""
    return signal.trusted or signal.nobody_reads


def table_for(
    student: Membership, applications: Sequence[Application], signals: Iterable[MailSignal]
) -> Table:
    """The table from this student's own rows. Web-tier safe: tenant tables only."""
    from apps.concierge.models import DocumentVersion
    from apps.documents.models import DocumentDraft

    asked: dict[UUID, list[str]] = {}
    for signal in signals:
        if signal.application_id is None:
            continue
        if signal.label == "DOCUMENT_REQUEST" and signal.document_name and vouched(signal):
            asked.setdefault(signal.application_id, []).append(signal.document_name)
    columns = [
        ApplicationNeeds(
            application_id=application.id,
            title=application.title,
            sentences=(
                *(str(text) for text in application.kit_requirements if isinstance(text, str)),
                *asked.get(application.id, []),
            ),
        )
        for application in applications
    ]
    by_programme = {application.program_id: application.id for application in applications}
    held: list[Held] = []
    for draft in DocumentDraft.objects.filter(
        student=student,
        status=DocumentDraft.Status.APPROVED,
        kind__in=(DocumentDraft.Kind.CV, DocumentDraft.Kind.MOTIVATION_LETTER),
    ).exclude(rendered_filename="").order_by("-version"):
        # Unrendered (packets.py's rule): nothing stored yet for the extension to fetch.
        application_id = None
        if draft.programme_id:
            # A document made for a programme this student has no application
            # to is for nobody here, never a general one.
            application_id = by_programme.get(draft.programme_id)
            if application_id is None:
                continue
        if draft.kind == DocumentDraft.Kind.MOTIVATION_LETTER and application_id is None:
            continue
        held.append(
            Held(draft.kind, Cell.APPROVED, application_id=application_id,
                 document_id=draft.id, source="draft")
        )
    uploads = DocumentVersion.objects.filter(
        student=student, state__in=("AVAILABLE", "CHECKING")
    ).order_by("-created_at")
    # A usable upload is listed before one still being checked: held_for takes the first,
    # so a re-upload under check never hides the copy Submit can already send.
    for upload in sorted(uploads, key=lambda upload: upload.state != "AVAILABLE"):
        held.append(
            Held(upload.kind, Cell.UPLOADED if upload.state == "AVAILABLE" else Cell.CHECKING,
                 expires_on=upload.expires_on, document_id=upload.id, source="upload")
        )
    return build_table(columns, held)


def sendable(application: Application, *, document_id: UUID, source: str) -> bool:
    """Whether Submit document may send this document to this application.

    True only for the entry the application's own cell shows (``held_for``),
    in a state that fills it. Ownership is by construction: the table holds
    the student's own rows only. That one lookup is also what refuses a
    document still being checked or rendered, an uncertified copy for a
    certified cell (spec §6), and a draft made for another programme (§5.6).

    A kind the application does not list (a NOT_NEEDED cell) is still sendable:
    it is the student's own clean document to their own application, and the
    requirement copy may simply have missed it. The page offers no button there.
    A withdrawn application takes nothing.
    """
    from apps.mailbox.models import MailSignal

    if application.outcome == "WITHDRAWN":
        return False
    table = table_for(
        application.student,
        [application],
        MailSignal.objects.filter(application=application).select_related("connection"),
    )
    entry = next(
        (h for h in table.held if h.document_id == document_id and h.source == source), None
    )
    return (
        entry is not None
        and entry.state in SENDABLE
        and table.held_for(entry.kind, application.id) == entry
    )
