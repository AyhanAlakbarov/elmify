"""The Fill Packet and the counsellor's kit view: one preparation, two renderings.

The packet is what the extension types into the student's own portal tab. The
kit is the same preparation as plain answers, shown read-only to the assigned
counsellor as a debugging view (``apps/dashboard/views.py::application_answers``);
a student is shown no by-hand page (owner, 2026-10-10), because applying goes
through the extension. They are built from one source here so they cannot
disagree about what this student is applying with.

The asymmetry is deliberate and load-bearing: build_kit never raises and
degrades (a counsellor debugging an unfillable portal needs to see why),
mint_packet refuses.

mint_packet has no production caller today. It is reached only from tests
until a later plan adds a device-token-authenticated route for the extension
-- minting one over HTTP without that authentication would be an
unauthenticated packet endpoint, handing out verified facts to whoever knows
an application id. This repository has twice had a session mistake
present-but-unwired code for absent, so this says it here rather than relying
on anyone to notice the missing caller.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from apps.concierge.models import DocumentVersion
from apps.documents import document_reading
from apps.documents.fact_labels import FIELD_LABELS
from apps.documents.file_rules import DRAFT_DOCUMENTS, UPLOAD_DOCUMENTS
from apps.documents.models import DocumentDraft, NarrativeInput, TranscriptUpload
from apps.documents.table import ROWS
from apps.documents.verification import disowned_refs, retired_refs
from apps.funding.models import ApplicationPrompt, Program, ProgramStatement
from apps.funding.requirements import RequirementItem, letter_kit_steps
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from .fact_reading import KIND_FOR_PREFIX, request_fact_reading
from .http import SERVED_TYPES, TYPE_BY_EXTENSION
from .models import (
    Application,
    ApplicationStep,
    FieldMap,
    PortalAccount,
    PortalAnswer,
    PortalForm,
    PreparedDocument,
)
from .prepare import bundle_line, current_prepared, note_text, prepared_upload
from .profile import (
    NARRATIVE_FIELDS,
    document_offers,
    document_sources,
    expired_id_document,
    field_class,
    narrative_values,
    verified_values,
)
from .rules import apply_rules
from .session import FieldAction, is_fillable
from .slots import HeldDocument, pair_slots, parse_slots
from .tags import account_for, addresses_for

logger = logging.getLogger(__name__)

#: A packet is a snapshot of verified facts. Two hours keeps a tab left open
#: overnight from filling yesterday's answers; the extension refetches.
PACKET_TTL = timedelta(hours=2)

#: The oldest extension build whose semantics match this packet shape. An older
#: one refuses the packet and asks to update rather than filling on a guess.
MIN_EXTENSION_VERSION = "0.2.0"


class NoFieldMap(Exception):
    """The portal form has never been learned. A caller must run the learn pass."""


class PacketRefused(Exception):
    """No packet for this application, with a stable machine-readable reason.

    The reason is matched on by the HTTP layer and by the dashboard, so it must
    not become a sentence anyone will later reword.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class KitQuestion:
    """One field of the portal's form, with the answer we hold for it."""

    profile_field: str
    label: str
    answer: str
    missing: bool


@dataclass(frozen=True)
class KitDocument:
    """One approved document, and where the student downloads it."""

    label: str
    filename: str
    download_path: str
    draft_id: UUID | None
    prepared_id: UUID | None = None
    kind: str = ""
    content_type: str = "application/pdf"
    #: A reason the panel can show: why this file could not be prepared, or a
    #: note on a prepared one (signed, too_large, name_needs_name_parts, ...).
    note: str = ""
    #: `note` as a sentence for the student; never the raw code.
    note_text: str = ""


@dataclass(frozen=True)
class KitNote:
    """A held upload whose prepared copy carries a note. No link: the kit
    serves uploads nowhere in this plan, it only says why."""

    label: str
    note_text: str


@dataclass(frozen=True)
class ApplicationKit:
    application_id: UUID
    portal_host: str
    form_url: str
    apply_with_email: str
    deadline: datetime | None
    deadline_timezone: str
    state: str
    questions: tuple[KitQuestion, ...]
    requirements: tuple[str, ...]
    #: The letter requirements NOBODY but the applicant can perform -- a
    #: hand-signed declaration, a handwritten letter, the page's own student
    #: actions. Separate from `requirements`, which is the programme's REQUIRED
    #: statements as a checklist: these are the ones that fail silently if the
    #: student never sees them, because nothing in this system can do them.
    your_actions: tuple[RequirementItem, ...]
    #: Which admissions cycle `your_actions` was read for. Carried because the
    #: kit picks the cycle itself (see `_letter_actions`), and a reader who can
    #: see the cycle can tell a stale requirement from a current one.
    letter_cycle: str
    documents: tuple[KitDocument, ...]
    not_fillable_reason: str
    #: One kit-level line when the whole-application PDF could not be built:
    #: bundle_failed's sentence, then the reason's. Shown even with no documents.
    bundle_note: str = ""
    upload_notes: tuple[KitNote, ...] = ()


class PacketField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: str
    method: str
    value: str
    #: The fact this selector is supposed to ask for, in profile.py vocabulary.
    #: Carried so the extension can check the control's own accessible name
    #: against it before typing -- the server has no page to check against, and
    #: read-back cannot catch a wrong-but-consistent map. Vocabulary only: it
    #: names a category and a key, never a student value.
    profile_field: str
    #: Typed back from this student's own earlier answer on this portal form
    #: (owner, 2026-10-09, decision B). The extension skips the label check for
    #: it (the student chose the box) and marks it "From your earlier answer".
    from_answer: bool = False
    #: Filled from a value a document read proved: "passport", "diploma" or
    #: "certificate". The mark says "From your passport". "" for anything else.
    source_kind: str = ""


class PacketOffer(BaseModel):
    """A value a document read left doubtful (spec 2026-10-12 §7.2): shown to the
    student as "We read X from your passport — use it?" and typed only after their
    tap confirms it through ext_api.confirm_offer. The method is the map's own."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: UUID
    value: str
    method: str
    source_kind: Literal["passport", "diploma", "certificate"]


class PacketHint(BaseModel):
    """A control the map thinks asks for `profile_field` and that is the
    student's to fill. No value is typed into it unless the student taps an offer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selector: str
    profile_field: str
    #: "unsure": the map only thinks this box asks for it. "no_fact": the map is
    #: sure, and this student holds no fact for it yet (owner, 2026-10-09).
    reason: Literal["unsure", "no_fact"]
    offer: PacketOffer | None = None
    #: The upload kind that would supply this field when the student has none
    #: (spec §3: "Upload your passport once…"). "" when one is uploaded.
    upload_kind: str = ""
    #: Every ID document has expired: the latest expiry, so the panel can say when.
    expired_on: str = ""


class PacketDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    download_path: str
    draft_id: UUID | None = None
    upload_id: UUID | None = None
    #: A draft's prepared copy (plan 4), or the whole-application bundle.
    prepared_id: UUID | None = None
    #: The learned upload box this document goes into. None keeps the
    #: extension's name-match path, as every packet before slots did.
    selector: str | None = None
    #: FILE_FIELDS document: CV, TRANSCRIPT, ..., EVERY_DOCUMENT.
    kind: str = "CV"
    content_type: str = "application/pdf"
    #: Why the file could not be prepared, or a note on a prepared one (a code).
    note: str = ""

    @model_validator(mode="after")
    def _one_source(self) -> PacketDocument:
        sources = (self.draft_id, self.upload_id, self.prepared_id)
        if sum(source is not None for source in sources) != 1:
            raise ValueError("a packet document is exactly one draft, upload or prepared file")
        return self


class PacketNote(BaseModel):
    """A note with no document of its own in the packet: an upload the extension does not
    attach, or the refused whole-application bundle. Codes only: the panel says each in
    the student's language, never the code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str  # FILE_FIELDS document: DIPLOMA, TRANSCRIPT, ..., EVERY_DOCUMENT
    note: str  # a prepare.NOTE_TEXT code


class PacketChoice(BaseModel):
    """A held document code could not place: the student picks its box in the panel."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    download_path: str
    kind: str
    draft_id: UUID | None = None
    upload_id: UUID | None = None
    prepared_id: UUID | None = None
    selectors: tuple[str, ...]


class FillPacket(BaseModel):
    """What the extension types, and nothing else.

    No credential, no token, no payment field. `entries` rather than `fields`
    or `values`: both shadow Pydantic model attributes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    application_id: UUID
    portal_form_id: UUID
    field_map_version: int
    form_url: str
    entries: tuple[PacketField, ...]
    documents: tuple[PacketDocument, ...]
    hints: tuple[PacketHint, ...] = ()
    choices: tuple[PacketChoice, ...] = ()
    issued_at: datetime
    expires_at: datetime
    min_extension_version: str
    #: PortalForm.confirmation_markers, or None where the portal has none.
    #: None keeps detectConfirmation off; see that column's own comment for
    #: why an empty tuple would be a different and worse answer.
    confirmation_markers: tuple[str, ...] | None = None
    #: The contact.email value without our tag, "" when it carries none. The
    #: extension types it instead when the portal refuses the tagged address
    #: (spec §2a) -- the student's own address, in the student's own browser.
    plain_email: str = ""
    #: Upload notes and the refused bundle, once each (plan 4b final review I1).
    notes: tuple[PacketNote, ...] = ()
    #: PortalForm.readback_equivalences: field class -> the one rule the bench
    #: taught for this portal. Empty means read-back is exact.
    equivalences: dict[str, str] = Field(default_factory=dict)


def _not_fillable_reason(form: PortalForm | None, field_map: FieldMap | None) -> str:
    if form is None:
        return "no_portal"
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        return "automation_prohibited"
    if field_map is None:
        return "no_field_map"
    return ""


_PROSE_FIELDS = frozenset({
    *NARRATIVE_FIELDS,
    "personal.summary",
    "experience.bullets",
    "timeline.statement",
})
_INDEXED_PROSE_RE = re.compile(r"^(?:experience|timeline)\.\d+\.(?:bullets|statement)$")


def _is_prose_field(field: str) -> bool:
    return field in _PROSE_FIELDS or bool(_INDEXED_PROSE_RE.match(field))


_DESC_CHAR_LIMIT_RE = re.compile(
    r"(?:max(?:imum)?\.?\s*|up\s+to\s+|limit(?:\s+of)?\s*:?\s*|bis\s+zu\s+|не\s+более\s+|макс\.?\s*|\b\d+\s*[-–—to]+\s*)"
    r"(\d{2,5})\s*(?:char(?:acter)?s?|zeichen\w*|caract[èe]res?|символ\w*|simvol\w*|karakter\w*)\b",
    re.IGNORECASE,
)
_DESC_WORD_LIMIT_RE = re.compile(
    r"(?:max(?:imum)?\.?\s*|up\s+to\s+|limit(?:\s+of)?\s*:?\s*|bis\s+zu\s+|не\s+более\s+|макс\.?\s*|\b\d+\s*[-–—to]+\s*)"
    r"(\d{1,4})\s*(?:words?|w[öo]rter\w*|mots?|слов\w*|söz\w*|kelime\w*)\b",
    re.IGNORECASE,
)


def _fit_max_length(field: str, value: str, max_length: int) -> str:
    """Trim a prose answer to fit a control's character cap at a sentence or word boundary.

    Identifiers, dates, and structured fields are never truncated (truncating a
    passport number or date would corrupt it). Prose fields are trimmed at the
    last complete sentence within ``max_length`` when possible, else the last
    word boundary, so read-back against a maxlength-capped control succeeds.
    """
    if max_length <= 0 or len(value) <= max_length or not _is_prose_field(field):
        return value
    prefix = value[:max_length]
    sentence_ends = list(re.finditer(r"[.!?](?=\s|$)", prefix))
    if sentence_ends:
        return prefix[: sentence_ends[-1].end()].rstrip()
    last_space = prefix.rfind(" ")
    if last_space > 0:
        return prefix[:last_space].rstrip()
    return prefix


def _fit_word_limit(field: str, value: str, max_words: int) -> str:
    """Trim a prose answer to at most ``max_words`` words at a sentence or word boundary."""
    if max_words <= 0 or not _is_prose_field(field):
        return value
    tokens = list(re.finditer(r"\S+", value))
    if len(tokens) <= max_words:
        return value
    cap_index = tokens[max_words - 1].end()
    return _fit_max_length(field, value, cap_index)


def _fit_entry_limits(
    field: str, value: str, max_length: object, description: str = ""
) -> str:
    """Apply explicit HTML ``max_length`` and any character/word cap in ``description``."""
    out = _fit_max_length(field, value, max_length) if isinstance(max_length, int) else value
    if description:
        if char_match := _DESC_CHAR_LIMIT_RE.search(description):
            out = _fit_max_length(field, out, int(char_match.group(1)))
        if word_match := _DESC_WORD_LIMIT_RE.search(description):
            out = _fit_word_limit(field, out, int(word_match.group(1)))
    return out


def _questions_from_map(field_map: FieldMap, values: dict[str, str]) -> tuple[KitQuestion, ...]:
    """FieldMap.entries is a shared table this plan never writes, so a row's
    shape is not this function's to assume. build_kit never raises: an entry
    with no usable profile_field is skipped rather than trusted."""
    questions = []
    for entry in field_map.entries:
        raw_field = entry.get("profile_field")
        if not raw_field:
            continue
        field = str(raw_field)
        answer = (values.get(field) or "").strip()
        action = entry.get("action") or {}
        description = str(action.get("description") or "") if isinstance(action, dict) else ""
        if answer:
            answer = _fit_entry_limits(field, answer, entry.get("max_length"), description)
        questions.append(
            KitQuestion(
                profile_field=field,
                label=description or field,
                answer=answer,
                missing=not answer,
            )
        )
    return tuple(questions)


def _questions_from_values(values: dict[str, str]) -> tuple[KitQuestion, ...]:
    """Every answer we hold, in a stable order.

    Used only when no field map exists. The portal's real questions are
    unknown then, and making some up would put words in the portal's mouth.
    """
    return tuple(
        KitQuestion(profile_field=field, label=_readable(field), answer=answer, missing=False)
        for field, answer in sorted(values.items())
        if answer.strip()
    )


def _readable(field: str) -> str:
    """"identity.full_name" -> "Identity: full name". The keys are the facts'
    own payload keys, an open set, so no label table could cover them."""
    category, _, key = field.partition(".")
    category = category.replace("_", " ").capitalize()
    return f"{category}: {key.replace('_', ' ')}" if key else category


def _requirements(application: Application) -> tuple[str, ...]:
    """The programme's own REQUIRED sentences, as a checklist.

    Shared-catalog rows, read outside the tenant transaction on purpose:
    ProgramStatement carries no tenant column. Worker-side only, through
    `capture_requirements`: the web tier holds no grant on this table.
    """
    return tuple(
        ProgramStatement.objects.filter(
            program_id=application.program_id,
            requirement=ProgramStatement.Requirement.REQUIRED,
        )
        .order_by("text")
        .values_list("text", flat=True)
    )


def _letter_actions(application: Application) -> tuple[tuple[RequirementItem, ...], str]:
    """The letter steps only the applicant can take, and the cycle they came from.

    `apps/funding/requirements.py` has said since the kit was designed that
    this is the seam -- "when it lands it reads letter_kit_steps(prompt)". The
    kit landed and this was never wired, so a page saying the letter must be
    hand-signed reached the letter PANE and never the kit a student actually
    applies from. Nothing else in this system can sign a letter.

    **The cycle is a guess, and it is returned so it can be shown.** An
    `Application` carries a `program_id` and no cycle -- a column this function
    is not worth a migration for -- so the newest prompt in the catalog wins,
    which is right for an application being prepared now and wrong at a cycle
    boundary. Returning the cycle is what keeps that visible instead of silent.

    Shared-catalog rows, read outside the tenant transaction like
    `_requirements` and, like it, worker-side only (`capture_requirements`).
    Every failure degrades to no steps: the kit promises never to raise, and
    `letter_shape_sources` is catalog JSON this
    function has no more right to trust than `_parse_entry` has to trust a
    `FieldMap` row.
    """
    prompt = (
        ApplicationPrompt.objects.filter(programme_id=application.program_id)
        .order_by("-cycle")
        .first()
    )
    if prompt is None:
        return (), ""
    try:
        return letter_kit_steps(prompt), prompt.cycle
    except Exception:
        logger.warning("kit: letter steps unreadable for prompt %s", prompt.id, exc_info=True)
        return (), prompt.cycle


#: A prepared row's document (FILE_FIELDS vocabulary) -> the document table's label.
_UPLOAD_LABEL = {kind: label for kind, label in ROWS if kind in UPLOAD_DOCUMENTS}
_PREPARED_LABEL = {
    **_UPLOAD_LABEL,
    "MOTIVATION_LETTER": "Motivation letter",
    "EVERY_DOCUMENT": "Combined application file",
}


def prepared_label(document: str) -> str:
    return _PREPARED_LABEL.get(document, document.replace("_", " ").capitalize())


def _refused_bundle(prepared: dict[str, PreparedDocument]) -> PreparedDocument | None:
    bundle = prepared.get("EVERY_DOCUMENT")
    return bundle if bundle is not None and bundle.state != PreparedDocument.State.READY else None


def _noted_uploads(prepared: dict[str, PreparedDocument]) -> list[PreparedDocument]:
    """Each held upload's prepared row that carries a note. Uploads are not packet
    documents, so nothing else in the packet carries these."""
    return [
        row for slot, row in sorted(prepared.items())
        if slot != "EVERY_DOCUMENT" and row.reason
        and any(source.get("source") == "upload" for source in row.sources)
    ]


def _kit_notes(prepared: dict[str, PreparedDocument]) -> tuple[str, tuple[KitNote, ...]]:
    """The kit-level bundle line, and each held upload whose prepared row has a note."""
    bundle = _refused_bundle(prepared)
    uploads = tuple(
        KitNote(label=_UPLOAD_LABEL.get(row.document, row.document),
                note_text=note_text(row.reason))
        for row in _noted_uploads(prepared)
    )
    return (bundle_line(bundle.reason) if bundle else ""), uploads


def _packet_notes(prepared: dict[str, PreparedDocument]) -> tuple[PacketNote, ...]:
    notes = [PacketNote(kind="EVERY_DOCUMENT", note=bundle.reason)
             for bundle in [_refused_bundle(prepared)] if bundle is not None]
    for row in _noted_uploads(prepared):
        note = PacketNote(kind=row.document, note=row.reason)
        if note not in notes:  # two signed diplomas are one line
            notes.append(note)
    return tuple(notes)


#: Prepared-row documents (FILE_FIELDS vocabulary) that are also our documents table's rows.
_TABLE_KINDS = UPLOAD_DOCUMENTS | DRAFT_DOCUMENTS


def document_notes(
    applications: list[Application],
) -> tuple[dict[tuple[str, UUID], list[str]], dict[UUID, str]]:
    """For the student's documents table: each (row kind, application) cell's prepared-note
    sentences, and each application's refused-bundle line. Sentences only, never a code.
    Only applications holding a noted row are read in full (`current_prepared`)."""
    noted = set(
        PreparedDocument.objects.filter(application__in=applications)
        .exclude(reason="").values_list("application_id", flat=True)
    )
    cells: dict[tuple[str, UUID], list[str]] = {}
    bundles: dict[UUID, str] = {}
    for application in applications:
        if application.id not in noted:
            continue
        prepared = current_prepared(application)
        if (bundle := _refused_bundle(prepared)) is not None:
            bundles[application.id] = bundle_line(bundle.reason)
        for slot, row in sorted(prepared.items()):
            if slot == "EVERY_DOCUMENT" or not row.reason or row.document not in _TABLE_KINDS:
                continue
            sentences = cells.setdefault((row.document, application.id), [])
            if (sentence := note_text(row.reason)) not in sentences:
                sentences.append(sentence)
    return cells, bundles


def kit_cv_drafts(application: Application) -> list[DocumentDraft]:
    """At most one approved, rendered CV for `application` (CV build step 4.2):
    - the newest approved, rendered CV with `application=application`;
    - else the newest approved general CV (`is_general=True`);
    - else, for legacy drafts (`application__isnull=True, requirements__isnull=True`),
      the newest approved draft with `programme_id=application.program_id`, else
      the newest legacy draft with `programme`, `funding_opportunity` and
      `application` all null.
    """
    base = (
        DocumentDraft.objects.filter(
            student=application.student,
            status=DocumentDraft.Status.APPROVED,
            kind=DocumentDraft.Kind.CV,
        )
        .exclude(rendered_filename="")
        .order_by("-version")
    )
    own = base.filter(application=application).first()
    if own is not None:
        return [own]
    general = base.filter(is_general=True).first()
    if general is not None:
        return [general]
    legacy = base.filter(application__isnull=True, requirements__isnull=True)
    by_programme = legacy.filter(programme_id=application.program_id).first()
    if by_programme is not None:
        return [by_programme]
    legacy_general = legacy.filter(
        programme_id__isnull=True, funding_opportunity_id__isnull=True
    ).first()
    if legacy_general is not None:
        return [legacy_general]
    return []


def kit_letter_drafts(application: Application) -> list[DocumentDraft]:
    """At most one approved, rendered motivation letter for `application`:
    - the newest approved, rendered MOTIVATION_LETTER with `application=application`;
    - else, for legacy drafts (`application__isnull=True`), the newest approved,
      rendered draft with `programme_id=application.program_id` and no scholarship.
    A motivation letter is always programme- or application-specific (matching
    apps/documents/table.py), never general across unrelated programmes.
    """
    base = (
        DocumentDraft.objects.filter(
            student=application.student,
            status=DocumentDraft.Status.APPROVED,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
        )
        .exclude(rendered_filename="")
        .order_by("-version")
    )
    own = base.filter(application=application).first()
    if own is not None:
        return [own]
    if application.program_id:
        by_programme = base.filter(
            application__isnull=True,
            programme_id=application.program_id,
            funding_opportunity_id__isnull=True,
        ).first() or base.filter(
            application__isnull=True,
            funding_opportunity_id=application.program_id,
        ).first()
        if by_programme is not None:
            return [by_programme]
    return []


def _kit_documents(
    application: Application, prepared: dict[str, PreparedDocument]
) -> tuple[KitDocument, ...]:
    """Approved, rendered documents for this application, linked through the
    one route that exists.

    `download_document` is @login_required, refuses anything not APPROVED and
    answers 404 to every refusal, so the kit links to it rather than minting a
    presigned URL -- `apps/documents/storage.py` says never a presigned URL and
    means it.

    `kit_cv_drafts` serves at most one CV and `kit_letter_drafts` serves at most
    one motivation letter for this application. Every filter reads the draft's
    own FK columns, never a catalogue row.

    Only drafts with a stored `rendered_filename`: that is the name the object
    was written under (`storage.store_document`), so the link cannot name an
    object that does not exist, and nothing here resolves a variant from the
    programme or funder -- the web tier holds no grant on the catalogue. An
    approved draft still rendering is simply not in the kit yet.
    """
    drafts = [*kit_cv_drafts(application), *kit_letter_drafts(application)]
    raw = tuple(
        KitDocument(
            label=prepared_label(draft.kind),
            filename=draft.rendered_filename,
            download_path=reverse(
                "documents-download", args=[draft.id, draft.rendered_filename]
            ),
            draft_id=draft.id,
            kind=draft.kind,
        )
        for draft in drafts
    )
    # Prepared rows are tenant tables only (prepare.current_prepared), so this
    # still reads nothing from the catalogue.
    if (bundle := prepared.get("EVERY_DOCUMENT")) is not None:
        if bundle.state == PreparedDocument.State.READY:
            return (_prepared_entry(bundle),)
        # The originals, each marked as a bundle fallback: the bundle's own reason
        # (e.g. a signed diploma) is the kit-level line's, never the CV's.
        raw = tuple(replace(d, note="bundle_failed", note_text=note_text("bundle_failed"))
                    for d in raw)
    out = []
    for entry in raw:
        row = prepared.get(f"{entry.kind}:{entry.draft_id}")
        if row is None:
            out.append(entry)
        elif row.state == PreparedDocument.State.READY:
            out.append(_prepared_entry(row))
        else:
            out.append(replace(entry, note=row.reason, note_text=note_text(row.reason)))
    return tuple(out)


def _prepared_entry(row: PreparedDocument) -> KitDocument:
    # On a READY row `reason` is a name note, which is why it is still carried.
    return KitDocument(
        label=row.document,
        filename=row.filename,
        download_path=reverse("portals-prepared-download", args=[row.id, row.filename]),
        draft_id=None,
        prepared_id=row.id,
        kind=row.document,
        content_type=row.content_type,
        note=row.reason,
        note_text=note_text(row.reason),
    )


def capture_requirements(application: Application) -> None:
    """Copy the kit's catalogue-derived parts onto the Application. Worker-side only.

    The web tier (`runtime_web`) holds no grant on the shared catalogue, so
    `build_kit` -- served from a web view -- reads only what this stored. This
    is the one place ProgramStatement and ApplicationPrompt are read for a kit.
    It also copies `Program.file_rules` (empty when the programme row is gone).

    Its caller is the document worker (`document_worker.py`, action
    `capture_requirements`), queued on commit by `applications.add_application`
    and re-queued by a repeat Add while the copy is still empty. Until it runs,
    the kit shows an empty checklist and no letter steps -- silently, since
    empty is also what an unread programme looks like. The copy goes stale when
    the programme page is re-read and NOTHING re-captures it today: re-running
    this after a re-read is owed by whoever builds the re-read trigger, not
    done by the catalogue.
    """
    your_actions, letter_cycle = _letter_actions(application)
    application.kit_requirements = list(_requirements(application))
    application.kit_your_actions = [asdict(item) for item in your_actions]
    application.kit_letter_cycle = letter_cycle
    application.kit_file_rules = list(
        Program.objects.filter(id=application.program_id)
        .values_list("file_rules", flat=True).first() or []
    )
    with tenant_transaction(application.tenant_id):
        application.save(
            update_fields=[
                "kit_requirements", "kit_your_actions", "kit_letter_cycle", "kit_file_rules",
            ]
        )


def _stored_requirements(
    application: Application,
) -> tuple[tuple[str, ...], tuple[RequirementItem, ...]]:
    """The copy capture_requirements wrote, or nothing. Never raises.

    The row is ours, but build_kit's contract is that it never raises, so a
    copy this code cannot read degrades to no checklist -- logged, not silent.
    """
    try:
        requirements = tuple(str(text) for text in application.kit_requirements)
        your_actions = tuple(RequirementItem(**item) for item in application.kit_your_actions)
    except (TypeError, ValueError):
        logger.warning(
            "kit: stored requirements unreadable for application %s",
            application.id,
            exc_info=True,
        )
        return (), ()
    return requirements, your_actions


def _merge_scoped_narrative(
    values: dict[str, str],
    unscoped_narrative: dict[str, str],
    scoped_narrative: dict[str, str],
) -> dict[str, str]:
    base_values = {
        k: v
        for k, v in values.items()
        if not (
            k in unscoped_narrative
            and k not in scoped_narrative
            and v == unscoped_narrative[k]
        )
    }
    return {**base_values, **scoped_narrative} if scoped_narrative else dict(base_values)


def _readonly_portal_address(
    student: Membership, form: PortalForm | None, account: PortalAccount | None
) -> str:
    if account is not None and account.address:
        return account.address
    if form is not None:
        return student.application_email or ""
    return ""


def _merged_with_portal_email(
    application: Application, values: dict[str, str], *, issue: bool = True
) -> tuple[dict[str, str], str, str]:
    """Not a verified fact: the address the student applies with on THIS
    portal, tagged where the portal keeps tags (spec §2a), plus any
    application- or programme-scoped narrative units from approved letter drafts.
    Shared by build_kit and mint_packet so they cannot disagree about
    contact.email or application-specific narrative answers.

    Returns the merged values, the address itself ("" when the student has no
    application_email) and that address without our tag ("" when untagged).
    """
    unscoped_narrative = narrative_values(application.student)
    scoped_narrative = narrative_values(
        application.student,
        program_id=application.program_id,
        application_id=application.id,
    )
    merged = _merge_scoped_narrative(values, unscoped_narrative, scoped_narrative)
    if issue:
        address, plain = addresses_for(application)
    else:
        address = _readonly_portal_address(
            application.student, application.portal_form, account_for(application)
        )
        plain = ""
    if not address:
        return merged, "", ""
    return {**merged, "contact.email": address}, address, plain


def build_kit(
    application: Application, *, issue_address: bool = True, documents: bool = True
) -> ApplicationKit:
    """The answers we would submit, as plain data. Never raises.

    `issue_address=False` writes nothing: the counsellor's view must not
    create the student's portal account or hand out an address as a side effect.

    Reads no catalogue table for the checklist or the letter steps: those come
    from the copy `capture_requirements` stored on the Application, and are
    empty until it has run.

    `documents=False` skips the documents and their prepared-file lookups
    (the dashboard board reads only the questions).

    Known kit/packet difference: the co-pilot packet may type a student's own
    earlier answer back (labelled), while this hand-apply kit still lists that
    question.
    """
    form = application.portal_form
    field_map = FieldMap.current_for(form, application.tenant_id) if form is not None else None
    with tenant_transaction(application.tenant_id):
        values = verified_values(application.student)
        values, address, _plain = _merged_with_portal_email(
            application, values, issue=issue_address
        )
        kit_documents: tuple[KitDocument, ...] = ()
        bundle_note = ""
        upload_notes: tuple[KitNote, ...] = ()
        if documents:
            prepared = current_prepared(application)
            kit_documents = _kit_documents(application, prepared)
            bundle_note, upload_notes = _kit_notes(prepared)
    return _kit_from_loaded(
        application,
        form=form,
        field_map=field_map,
        values=values,
        address=address,
        kit_documents=kit_documents,
        bundle_note=bundle_note,
        upload_notes=upload_notes,
    )


def _kit_from_loaded(
    application: Application,
    *,
    form: PortalForm | None,
    field_map: FieldMap | None,
    values: dict[str, str],
    address: str,
    kit_documents: tuple[KitDocument, ...] = (),
    bundle_note: str = "",
    upload_notes: tuple[KitNote, ...] = (),
) -> ApplicationKit:
    """Assemble an ApplicationKit from preloaded values, field map, and document rows."""
    formatted = (
        {k: apply_rules(form, k, v) for k, v in values.items()} if form is not None else values
    )
    reason = _not_fillable_reason(form, field_map)
    requirements, your_actions = _stored_requirements(application)
    questions = (
        _questions_from_map(field_map, formatted)
        if field_map
        else _questions_from_values(formatted)
    )
    return ApplicationKit(
        application_id=application.id,
        portal_host=form.portal_host if form is not None else "",
        form_url=form.form_url if form is not None else "",
        apply_with_email=address or application.student.application_email,
        deadline=application.deadline,
        deadline_timezone=application.deadline_timezone,
        state=application.state,
        questions=questions,
        requirements=requirements,
        your_actions=your_actions,
        letter_cycle=application.kit_letter_cycle,
        documents=kit_documents,
        not_fillable_reason=reason,
        bundle_note=bundle_note,
        upload_notes=upload_notes,
    )


def build_kits_for_board(
    student: Membership, applications: Sequence[Application]
) -> dict[UUID, ApplicationKit]:
    """Batch-build read-only (`issue_address=False, documents=False`) kits for `board_for`.

    Preloads the student's verified facts, narrative inputs/drafts, and portal
    accounts once across all cards instead of repeating ~20 SQL queries per card.
    """
    if not applications:
        return {}
    forms_by_id = {app.portal_form.id: app.portal_form for app in applications if app.portal_form}
    field_maps: dict[UUID, FieldMap | None] = {}
    if forms_by_id:
        all_maps = list(
            FieldMap.objects.filter(
                portal_form_id__in=forms_by_id.keys(),
                superseded_at__isnull=True,
            )
            .filter(Q(learned_by_tenant__isnull=True) | Q(learned_by_tenant_id=student.tenant_id))
            .order_by("-version")
        )
        for form_id, pform in forms_by_id.items():
            shared = next(
                (
                    m
                    for m in all_maps
                    if m.portal_form_id == form_id and m.learned_by_tenant_id is None
                ),
                None,
            )
            scoped = next(
                (
                    m
                    for m in all_maps
                    if m.portal_form_id == form_id and m.learned_by_tenant_id == student.tenant_id
                ),
                None,
            )
            field_maps[form_id] = FieldMap.pick_current(pform, shared, scoped)

    with tenant_transaction(student.tenant_id):
        raw_values = verified_values(student)
        inputs = list(NarrativeInput.objects.filter(student=student).order_by("created_at"))
        drafts = list(
            DocumentDraft.objects.filter(
                student=student,
                kind__in=(DocumentDraft.Kind.CORE_NARRATIVE, DocumentDraft.Kind.MOTIVATION_LETTER),
                status=DocumentDraft.Status.APPROVED,
            ).order_by("version", "created_at")
        )
        unscoped_narrative = narrative_values(student, _inputs=inputs, _drafts=drafts)
        accounts_by_host = {
            acc.portal_host: acc
            for acc in PortalAccount.objects.filter(student=student)
        }

    out: dict[UUID, ApplicationKit] = {}
    for application in applications:
        form = application.portal_form
        field_map = field_maps.get(form.id) if form is not None else None
        scoped_narrative = narrative_values(
            student,
            program_id=application.program_id,
            application_id=application.id,
            _inputs=inputs,
            _drafts=drafts,
        )
        values = _merge_scoped_narrative(raw_values, unscoped_narrative, scoped_narrative)
        account = accounts_by_host.get(form.portal_host) if form is not None else None
        address = _readonly_portal_address(student, form, account)
        if address:
            values["contact.email"] = address
        out[application.id] = _kit_from_loaded(
            application,
            form=form,
            field_map=field_map,
            values=values,
            address=address,
        )
    return out


def _record_packet(application: Application, packet: FillPacket, missing: list[str]) -> None:
    """The §5.5 row for what the platform prepared.

    Its own short transaction, matching services._record: the trail must
    survive a later failure in the same request.
    """
    named: tuple[PacketDocument | PacketChoice, ...] = (*packet.documents, *packet.choices)
    with tenant_transaction(application.tenant_id):
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind="PACKET",
            detail={
                "field_map_version": packet.field_map_version,
                # A list, not {selector: value}: two field-map entries can
                # target the same selector, and a dict keyed by selector would
                # collapse them to one recorded value in the authoritative
                # audit row.
                # profile_field: which field each box was typed for, so an
                # answer the student later types over it records that field
                # (answers.record_answers). Vocabulary, never a value.
                "values": [
                    {
                        "selector": entry.selector,
                        "value": entry.value,
                        "profile_field": entry.profile_field,
                    }
                    for entry in packet.entries
                ],
                "documents": [
                    {
                        "draft_id": str(d.draft_id) if d.draft_id else None,
                        "prepared_id": str(d.prepared_id) if d.prepared_id else None,
                        "filename": d.filename,
                    }
                    for d in named
                    if d.upload_id is None
                ],
                # What lets ext_api.document::_named_for serve an upload, and
                # what keeps every other upload of this student unservable.
                "uploads": [
                    {"upload_id": str(d.upload_id)}
                    for d in named
                    if d.upload_id is not None
                ],
                "notes": [{"kind": note.kind, "note": note.note} for note in packet.notes],
                "hints": [
                    {
                        "selector": hint.selector,
                        "profile_field": hint.profile_field,
                        "reason": hint.reason,
                        "offer_fact_id": str(hint.offer.fact_id) if hint.offer else "",
                    }
                    for hint in packet.hints
                ],
                "missing_fields": missing,
            },
        )


def _parse_entry(entry: dict[str, object]) -> tuple[str, FieldAction]:
    """The one place mint_packet reads a raw FieldMap.entries row.

    FieldMap is a shared table this plan never writes, so a row's shape is
    not this function's to trust. No usable profile_field, no "action" key,
    or an action that fails FieldAction's schema are all the same class of
    malformed row, and mint_packet's contract is a stable machine-readable
    reason -- never a raw KeyError/ValidationError escaping to a caller that
    matches on it, including the HTTP layer a later plan adds.

    Deliberately asymmetric with build_kit's _questions_from_map, which
    skips a malformed entry and still returns a kit: a human reading a
    partial answer sheet is better off than one facing an error page.
    mint_packet refuses the WHOLE packet on the same malformed row instead,
    because a partial packet would have the extension type an incomplete
    application into a real portal.
    """
    field = entry.get("profile_field")
    if not field:
        raise PacketRefused("malformed_field_map")
    try:
        action = FieldAction.model_validate(entry.get("action"))
    except ValidationError as exc:
        raise PacketRefused("malformed_field_map") from exc
    return str(field), action


#: Kinds a student holds one of per degree.
PER_DEGREE_KINDS = frozenset({"TRANSCRIPT", "DIPLOMA"})


def _held_uploads(application: Application, degree_count: int) -> list[HeldDocument]:
    """The newest clean, promoted uploads, never every historical version: one
    per (kind, variant), except a per-degree kind (transcript, diploma), which
    keeps the newest `degree_count` -- a student with two degrees holds both
    transcripts, and pair_slots puts the two-box pairing to them as a choice.
    A transcript's variant is its TranscriptUpload role; every other upload is
    an ORIGINAL. The caller holds the tenant transaction: DocumentVersion and
    TranscriptUpload are FORCE RLS.
    """
    roles = dict(
        TranscriptUpload.objects.filter(student=application.student).values_list(
            "document_id", "role"
        )
    )
    disowned_ids = {
        UUID(ref.removeprefix("document:"))
        for ref in disowned_refs(application.student)
        if ref.startswith("document:")
    }
    refused_tx_ids = set(
        TranscriptUpload.objects.filter(
            student=application.student, state=TranscriptUpload.State.REFUSED
        ).values_list("document_id", flat=True)
    ) - set(
        TranscriptUpload.objects.filter(student=application.student)
        .exclude(state=TranscriptUpload.State.REFUSED)
        .values_list("document_id", flat=True)
    )
    newest: dict[tuple[str, str], list[HeldDocument]] = {}
    uploads = (
        DocumentVersion.objects.filter(
            student=application.student,
            state="AVAILABLE",
            scan_result="NO_THREATS_FOUND",
            retired_at__isnull=True,
        )
        .exclude(promoted_key="")
        .exclude(id__in=disowned_ids | refused_tx_ids)
        .order_by("-created_at")
    )
    for upload in uploads:
        extension = SERVED_TYPES.get(upload.content_type)
        if extension is None:
            continue  # ext_api.document would refuse to serve it anyway
        variant: Literal["ORIGINAL", "TRANSLATION"] = (
            "TRANSLATION" if roles.get(upload.id) == "TRANSLATION" else "ORIGINAL"
        )
        keep = max(degree_count, 1) if upload.kind in PER_DEGREE_KINDS else 1
        held = newest.setdefault((upload.kind, variant), [])
        if len(held) >= keep:
            continue
        held.append(
            HeldDocument(
                source="upload",
                id=upload.id,
                # The name ext_api.document serves it under, extension included.
                filename=f"{upload.kind.lower()}-{upload.id}{extension}",
                kind=upload.kind,
                variant=variant,
                download_path=reverse("portals-ext-document", args=[upload.id]),
            )
        )
    return [document for group in newest.values() for document in group]


def _prepared_row_document(
    row: PreparedDocument, selector: str | None, kind: str
) -> PacketDocument:
    """An upload's prepared copy, through the student's own prepared-file route."""
    return PacketDocument(
        filename=row.filename,
        download_path=reverse("portals-prepared-download", args=[row.id, row.filename]),
        prepared_id=row.id,
        selector=selector,
        kind=kind,
        content_type=row.content_type,
        note=row.reason,
    )


def _packet_document(
    held: HeldDocument,
    selector: str | None,
    kits: dict[UUID | None, KitDocument],
    prepared: dict[str, PreparedDocument],
) -> PacketDocument:
    if held.source == "upload":
        # A current prepared copy goes in place of the original (plan 4's purpose);
        # the original is then neither named nor servable through the packet.
        row = prepared_upload(prepared, held.id, held.kind)
        if row is not None:
            return _prepared_row_document(row, selector, held.kind)
    kit = kits.get(held.id) if held.source == "draft" else None
    if kit is not None:  # a draft, its prepared copy, or the bundle
        return PacketDocument(
            filename=kit.filename,
            download_path=kit.download_path,
            draft_id=kit.draft_id,
            prepared_id=kit.prepared_id,
            selector=selector,
            kind=held.kind,
            content_type=kit.content_type,
            # The refused bundle is said once, in `notes`, never again on each original.
            note="" if kit.note == "bundle_failed" else kit.note,
        )
    return PacketDocument(
        filename=held.filename,
        download_path=held.download_path,
        upload_id=held.id,
        selector=selector,
        kind=held.kind,
        content_type=TYPE_BY_EXTENSION.get(PurePosixPath(held.filename).suffix, "application/pdf"),
    )


def _own_answers(application: Application) -> dict[tuple[str, str], str]:
    """This student's newest typed answer per (box, field) on this portal form.

    Keyed by the field as well as the box (preflight #2): a portal that
    re-orders its form gives an old selector a new question, and the answer to
    the old one must never be typed into it. An answer counts for the field the
    packet named for the box and for the fact it matched. Nobody else's: the
    filter is the student, and RLS is the tenant. The caller holds the tenant
    transaction (FORCE RLS).
    """
    newest: dict[tuple[str, str], str] = {}
    for selector, guessed, matched, value in (
        PortalAnswer.objects.filter(
            student=application.student, portal_form=application.portal_form
        )
        .order_by("created_at")
        .values_list("selector", "guessed_field", "matched_field", "value")
    ):
        for field in {guessed, matched} - {""}:
            newest[(selector, field)] = value
    return newest


def _build_packet_hint(
    form: PortalForm,
    field: str,
    action: FieldAction,
    *,
    unsure: bool,
    offers: dict[str, Any],
    held_kinds: set[str],
    expired_on: str,
) -> PacketHint:
    """Build one PacketHint for an unsure or fact-less control."""
    offer = None if unsure else offers.get(field)
    wanted = (
        next((kind for prefix, kind in KIND_FOR_PREFIX if field.startswith(prefix)), "")
        if not unsure and field_class(field) in FIELD_LABELS
        else ""
    )
    if wanted and not document_reading.kind_enabled(wanted):
        wanted = ""
    return PacketHint(
        selector=action.selector,
        profile_field=field,
        reason="unsure" if unsure else "no_fact",
        offer=(
            PacketOffer(
                fact_id=offer.fact_id,
                value=apply_rules(form, field, offer.value),
                method=(action.method or "").strip(),
                source_kind=offer.source_kind,
            )
            if offer is not None
            else None
        ),
        upload_kind=wanted if offer is None and wanted not in held_kinds else "",
        expired_on=expired_on if not unsure and field.startswith("id_document.") else "",
    )


def _resolve_packet_entries(
    form: PortalForm,
    field_map: FieldMap,
    *,
    values: dict[str, str],
    own: dict[tuple[str, str], str],
    sources: dict[str, str],
    offers: dict[str, Any],
    held_kinds: set[str],
    expired_on: str,
) -> tuple[list[PacketField], list[PacketHint], list[str]]:
    """Validate FieldMap rows up front and partition into entries, hints, and missing fields."""
    parsed_entries = [_parse_entry(entry) for entry in field_map.entries]
    entries: list[PacketField] = []
    hints: list[PacketHint] = []
    for raw, (field, action) in zip(field_map.entries, parsed_entries, strict=True):
        if not is_fillable(action):
            raise PacketRefused("unsafe_action")
        unsure = raw.get("sure", True) is False
        if unsure or not (values.get(field) or "").strip():
            answered = own.get((action.selector, field), "")
            if answered.strip():
                entries.append(
                    PacketField(
                        selector=action.selector,
                        method=(action.method or "").strip(),
                        value=answered,
                        profile_field=field,
                        from_answer=True,
                    )
                )
                continue
            hints.append(
                _build_packet_hint(
                    form,
                    field,
                    action,
                    unsure=unsure,
                    offers=offers,
                    held_kinds=held_kinds,
                    expired_on=expired_on,
                )
            )
            continue
        formatted = apply_rules(form, field, values[field])
        formatted = _fit_entry_limits(
            field, formatted, raw.get("max_length"), action.description
        )
        entries.append(
            PacketField(
                selector=action.selector,
                method=(action.method or "").strip(),
                value=formatted,
                profile_field=field,
                source_kind=sources.get(field, ""),
            )
        )
    missing = sorted(
        {field for field, _ in parsed_entries if not (values.get(field) or "").strip()}
    )
    return entries, hints, missing


def _pair_packet_documents(
    field_map: FieldMap,
    *,
    documents: tuple[KitDocument, ...],
    uploads: list[HeldDocument],
    prepared: dict[str, PreparedDocument],
    degree_count: int,
) -> tuple[list[PacketDocument], list[PacketChoice]]:
    """Pair held drafts and uploads to learned upload slots and deduplicate merged files."""
    if any(d.kind == "EVERY_DOCUMENT" for d in documents):
        uploads = []
    elif documents:
        draft_kinds = {d.kind for d in documents if d.kind}
        uploads = [upload for upload in uploads if upload.kind not in draft_kinds]
    kits = {(d.prepared_id or d.draft_id): d for d in documents}
    drafts = [
        HeldDocument(
            source="draft",
            id=key,
            filename=d.filename,
            kind=d.kind or "CV",
            variant="ORIGINAL",
            download_path=d.download_path,
        )
        for key, d in kits.items()
        if key is not None
    ]
    pairing = pair_slots(parse_slots(field_map.slots), [*drafts, *uploads], degree_count)
    packet_documents = [
        _packet_document(held, slot.selector, kits, prepared) for slot, held in pairing.assigned
    ]
    choices: list[PacketChoice] = []
    for held, options in pairing.choices:
        if held.source == "draft" and len(options) < 2:
            packet_documents.append(_packet_document(held, None, kits, prepared))
            continue
        chosen = _packet_document(held, None, kits, prepared)
        choices.append(
            PacketChoice(
                filename=chosen.filename,
                download_path=chosen.download_path,
                kind=held.kind,
                draft_id=chosen.draft_id,
                upload_id=chosen.upload_id,
                prepared_id=chosen.prepared_id,
                selectors=tuple(slot.selector for slot in options),
            )
        )
    packet_documents += [
        _packet_document(h, None, kits, prepared) for h in pairing.unplaced if h.source == "draft"
    ]
    sent: set[UUID] = set()

    def _first(item: PacketDocument | PacketChoice) -> bool:
        if item.prepared_id is None:
            return True
        if item.prepared_id in sent:
            return False
        sent.add(item.prepared_id)
        return True

    return [d for d in packet_documents if _first(d)], [c for c in choices if _first(c)]


def mint_packet(application: Application) -> FillPacket:
    """Prepare one application for the extension, or refuse and say why.

    Runs the same pre-checks prepare_application ran before it opened a
    browser, in the same order and for the same reason: there is no point
    handing a student a portal tab for an application that cannot be completed.
    """
    form = application.portal_form
    if form is None:
        raise PacketRefused("no_portal")
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        raise PacketRefused("automation_prohibited")
    field_map = FieldMap.current_for(form, application.tenant_id)
    if field_map is None:
        raise NoFieldMap(f"{form.portal_host} has no current field map")
    with tenant_transaction(application.tenant_id):
        values = verified_values(application.student)
        values, _, plain_email = _merged_with_portal_email(application, values)
        # How many degrees the student holds facts for (education.<n>.*).
        degree_count = len(
            {key.split(".")[1] for key in values if re.fullmatch(r"education\.\d+\.\w+", key)}
        )
        prepared = current_prepared(application)
        documents = _kit_documents(application, prepared)
        notes = _packet_notes(prepared)
        uploads = _held_uploads(application, degree_count)
        own = _own_answers(application)
        sources = document_sources(application.student, values)
        offers = document_offers(application.student)
        expired_on = expired_id_document(application.student)
        # A passport read as someone else's, or replaced (verification.
        # disowned_refs covers both), does not count as held: the box still
        # asks for the student's own, current upload.
        disowned = [
            UUID(ref.removeprefix("document:"))
            for ref in disowned_refs(application.student) | retired_refs(application.student)
        ]
        # "Held" is apps/documents/table.py's rule (AVAILABLE or CHECKING, unretired),
        # so the documents page and the panel agree on "you have it".
        held_kinds = set(
            DocumentVersion.objects.filter(student=application.student)
            .filter(state__in=("AVAILABLE", "CHECKING"), retired_at__isnull=True)
            .exclude(id__in=disowned)
            .values_list("kind", flat=True)
        )
    entries, hints, missing = _resolve_packet_entries(
        form,
        field_map,
        values=values,
        own=own,
        sources=sources,
        offers=offers,
        held_kinds=held_kinds,
        expired_on=expired_on,
    )
    packet_documents, choices = _pair_packet_documents(
        field_map,
        documents=documents,
        uploads=uploads,
        prepared=prepared,
        degree_count=degree_count,
    )
    issued_at = timezone.now()
    packet = FillPacket(
        application_id=application.id,
        portal_form_id=form.id,
        field_map_version=field_map.version,
        form_url=form.form_url,
        entries=tuple(entries),
        hints=tuple(hints),
        documents=tuple(packet_documents),
        choices=tuple(choices),
        notes=notes,
        issued_at=issued_at,
        expires_at=issued_at + PACKET_TTL,
        min_extension_version=MIN_EXTENSION_VERSION,
        confirmation_markers=(
            tuple(form.confirmation_markers) if form.confirmation_markers else None
        ),
        plain_email=plain_email,
        equivalences=dict(form.readback_equivalences or {}),
    )
    _record_packet(application, packet, missing)
    if missing:
        request_fact_reading(application, missing)
    return packet


def viewable_prepared(
    student: Membership,
) -> list[tuple[Application, list[tuple[PreparedDocument, str, str]]]]:
    """For the counsellor board: each application's current READY prepared files as
    (row, kind label, note sentence). The counsellor views these; staff also download."""
    ready_app_ids = set(
        PreparedDocument.objects.filter(
            application__student=student, state=PreparedDocument.State.READY
        ).values_list("application_id", flat=True)
    )
    if not ready_app_ids:
        return []
    out = []
    for application in Application.objects.filter(
        student=student, id__in=ready_app_ids
    ).select_related("candidate", "student", "portal_form"):
        files = [
            (row, prepared_label(row.document), note_text(row.reason))
            for slot, row in sorted(current_prepared(application).items())
            if row.state == PreparedDocument.State.READY
        ]
        if files:
            out.append((application, files))
    return out
