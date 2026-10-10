"""The Application Kit and the Fill Packet: one object, two renderings.

The kit is what a human reads and types by hand -- any device, no extension,
nothing of ours touching the portal. The packet is the same preparation with
selectors attached, for the extension to type. They are built from one source
here so they cannot disagree about what this student is applying with.

The asymmetry is deliberate and load-bearing: build_kit never raises and
degrades, mint_packet refuses. A student whose portal cannot be filled
automatically has lost speed, not the application.

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
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, ValidationError

from apps.documents.models import DocumentDraft
from apps.funding.models import ApplicationPrompt, ProgramStatement
from apps.funding.requirements import RequirementItem, letter_kit_steps
from apps.tenancy.db import tenant_transaction

from .escalation import Trigger, escalate
from .models import Application, ApplicationStep, FieldMap, PortalForm
from .profile import verified_values
from .session import FieldAction, is_fillable
from .tags import addresses_for

logger = logging.getLogger(__name__)

#: A packet is a snapshot of verified facts. Two hours keeps a tab left open
#: overnight from filling yesterday's answers; the extension refetches.
PACKET_TTL = timedelta(hours=2)

#: The oldest extension build whose semantics match this packet shape. An older
#: one refuses the packet and asks to update rather than filling on a guess.
MIN_EXTENSION_VERSION = "0.1.0"


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
    draft_id: UUID


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


class PacketDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str
    download_path: str
    draft_id: UUID


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


def _not_fillable_reason(form: PortalForm | None, field_map: FieldMap | None) -> str:
    if form is None:
        return "no_portal"
    if form.terms_posture == PortalForm.TermsPosture.PROHIBITS_AUTOMATION:
        return "automation_prohibited"
    if field_map is None:
        return "no_field_map"
    return ""


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
        questions.append(
            KitQuestion(
                profile_field=field,
                label=str(action.get("description") or field),
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


def _kit_documents(application: Application) -> tuple[KitDocument, ...]:
    """Approved, rendered documents for this application, linked through the
    one route that exists.

    `download_document` is @login_required, refuses anything not APPROVED and
    answers 404 to every refusal, so the kit links to it rather than minting a
    presigned URL -- `apps/documents/storage.py` says never a presigned URL and
    means it.

    A draft with no programme is the student's general document and belongs in
    every kit; one attached to another programme belongs in none of them. The
    programme filter reads the draft's own FK column, never the catalogue row.

    Only drafts with a stored `rendered_filename`: that is the name the object
    was written under (`storage.store_document`), so the link cannot name an
    object that does not exist, and nothing here resolves a variant from the
    programme or funder -- the web tier holds no grant on the catalogue. An
    approved draft still rendering is simply not in the kit yet.

    Filtered to Kind.CV: it is the only kind with a stored, renderable
    artefact today (a raw draft.kind label would show a counselor-facing enum
    member like MOTIVATION_LETTER or CORE_NARRATIVE, an internal artefact,
    verbatim to a student). Revisit this filter when a second kind gets a
    rendered artefact.
    """
    drafts = (
        DocumentDraft.objects.filter(
            student=application.student,
            status=DocumentDraft.Status.APPROVED,
            kind=DocumentDraft.Kind.CV,
        )
        .exclude(rendered_filename="")
        .filter(Q(programme_id=application.program_id) | Q(programme__isnull=True))
        .order_by("kind", "version")
    )
    return tuple(
        KitDocument(
            # draft.kind, not get_kind_display(): TextChoices derives the
            # label from the member name, so DocumentDraft.Kind.CV
            # displays as "Cv". Measured, not assumed.
            label=draft.kind,
            filename=draft.rendered_filename,
            download_path=reverse(
                "documents-download", args=[draft.id, draft.rendered_filename]
            ),
            draft_id=draft.id,
        )
        for draft in drafts
    )


def capture_requirements(application: Application) -> None:
    """Copy the kit's catalogue-derived parts onto the Application. Worker-side only.

    The web tier (`runtime_web`) holds no grant on the shared catalogue, so
    `build_kit` -- served from a web view -- reads only what this stored. This
    is the one place ProgramStatement and ApplicationPrompt are read for a kit.

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
    with tenant_transaction(application.tenant_id):
        application.save(
            update_fields=["kit_requirements", "kit_your_actions", "kit_letter_cycle"]
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


def _merged_with_portal_email(
    application: Application, values: dict[str, str]
) -> tuple[dict[str, str], str, str]:
    """Not a verified fact: the address the student applies with on THIS
    portal, tagged where the portal keeps tags (spec §2a). Shared by
    build_kit and mint_packet so they cannot disagree about contact.email.

    Returns the merged values, the address itself ("" when the student has no
    application_email) and that address without our tag ("" when untagged).
    """
    address, plain = addresses_for(application)
    if not address:
        return values, "", ""
    return {**values, "contact.email": address}, address, plain


def build_kit(application: Application) -> ApplicationKit:
    """Everything a human needs to apply by hand. Never raises.

    Reads no catalogue table for the checklist or the letter steps: those come
    from the copy `capture_requirements` stored on the Application, and are
    empty until it has run.
    """
    form = application.portal_form
    field_map = FieldMap.current_for(form, application.tenant_id) if form is not None else None
    with tenant_transaction(application.tenant_id):
        values = verified_values(application.student)
        values, address, _plain = _merged_with_portal_email(application, values)
        apply_with_email = address or application.student.application_email
        documents = _kit_documents(application)
    reason = _not_fillable_reason(form, field_map)
    requirements, your_actions = _stored_requirements(application)
    questions = (
        _questions_from_map(field_map, values) if field_map else _questions_from_values(values)
    )
    return ApplicationKit(
        application_id=application.id,
        portal_host=form.portal_host if form is not None else "",
        form_url=form.form_url if form is not None else "",
        apply_with_email=apply_with_email,
        deadline=application.deadline,
        deadline_timezone=application.deadline_timezone,
        state=application.state,
        questions=questions,
        requirements=requirements,
        your_actions=your_actions,
        letter_cycle=application.kit_letter_cycle,
        documents=documents,
        not_fillable_reason=reason,
    )


def _record_packet(application: Application, packet: FillPacket) -> None:
    """The §5.5 row for what the platform prepared.

    Its own short transaction, matching services._record: the trail must
    survive a later failure in the same request.
    """
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
                "values": [
                    {"selector": entry.selector, "value": entry.value}
                    for entry in packet.entries
                ],
                "documents": [
                    {"draft_id": str(document.draft_id), "filename": document.filename}
                    for document in packet.documents
                ],
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
        documents = _kit_documents(application)
    # Every row is read (and, if malformed, refused) up front, so a bad row
    # anywhere in the map is caught before missing_fact or unsafe_action ever
    # gets to reason about it.
    parsed_entries = [_parse_entry(entry) for entry in field_map.entries]
    missing = sorted(
        field for field, _ in parsed_entries if not (values.get(field) or "").strip()
    )
    if missing:
        escalate(application, Trigger.MISSING_FACT, detail=", ".join(missing))
        raise PacketRefused("missing_fact")
    entries = []
    for field, action in parsed_entries:
        if not is_fillable(action):
            # A row stored before is_fillable existed outlives it. Refusing
            # here is the third enforcement point, matching fill.py's pre-pass.
            raise PacketRefused("unsafe_action")
        entries.append(
            PacketField(
                selector=action.selector,
                method=(action.method or "").strip(),
                value=values[field],
                profile_field=field,
            )
        )
    issued_at = timezone.now()
    packet = FillPacket(
        application_id=application.id,
        portal_form_id=form.id,
        field_map_version=field_map.version,
        form_url=form.form_url,
        entries=tuple(entries),
        documents=tuple(
            PacketDocument(
                filename=document.filename,
                download_path=document.download_path,
                draft_id=document.draft_id,
            )
            for document in documents
        ),
        issued_at=issued_at,
        expires_at=issued_at + PACKET_TTL,
        min_extension_version=MIN_EXTENSION_VERSION,
        confirmation_markers=(
            tuple(form.confirmation_markers) if form.confirmation_markers else None
        ),
        plain_email=plain_email,
    )
    _record_packet(application, packet)
    return packet
