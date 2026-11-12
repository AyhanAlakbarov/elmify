"""Plan 4: each document an application will attach, prepared to the programme's
written file rules before the student reaches the portal (spec §7, D4).

Worker-side for everything that transforms (`prepare_documents`); web-safe for
the read the kit and packet make (`current_prepared`): it reads tenant rows only
-- Application.kit_file_rules, drafts, uploads, the ledger -- never the catalogue.
Uploads are transformed only in the isolated parser (apps.documents.ocr).

Which documents fill each kind is the document table's choice (`table_for`,
`Table.held_all_for`), never this module's: no CV is sent twice, and no superseded
upload or document made for another programme is prepared.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.concierge.models import DocumentVersion
from apps.documents import storage
from apps.documents.document_queue import DocumentWorkMessage, enqueue_document_work
from apps.documents.file_rules import (
    DRAFT_DOCUMENTS,
    UPLOAD_DOCUMENTS,
    FileRule,
    bundle_rule,
    rule_for,
)
from apps.documents.models import DocumentDraft, TranscriptPage
from apps.documents.ocr import INLINE_MAX, Part, Prepared, prepare_files
from apps.documents.ocr_errors import OcrUnavailable
from apps.documents.table import ROWS, SENDABLE, Cell, table_for
from apps.mailbox.models import MailSignal
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .http import SERVED_TYPES
from .models import Application, PreparedDocument
from .profile import verified_values

logger = logging.getLogger(__name__)

#: A worker run's wall-clock budget for parser calls, shared across a student's
#: applications. Comfortably under the scan queue's 900 s visibility timeout; what
#: it leaves unprepared is served as the original until the next trigger.
PREPARE_BUDGET_SECONDS = 240.0
#: A job the parser failed (timed_out) is tried again on the first trigger after this.
#: Every other refusal is about the file, so it stands until the inputs change.
RETRY_TIMED_OUT_AFTER = timedelta(hours=1)
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_KNOWN_PLACEHOLDERS = frozenset({"{full_name}", "{surname}", "{given_name}"})
_PATTERN_EXTENSION = re.compile(r"\.(?:pdf|jpe?g|png)$", re.I)
_FOLD = str.maketrans(
    {
        "ə": "e",
        "Ə": "E",
        "ı": "i",
        "İ": "I",
        "ß": "ss",
        "ẞ": "SS",
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
    }
)
#: The bundle's order: R-008's own (CV, academic documents, language, references,
#: nationality). ponytail: one fixed order; a page stating another is a note.
_BUNDLE_ORDER = ("CV", "MOTIVATION_LETTER", "DIPLOMA", "TRANSCRIPT", "LANGUAGE_CERTIFICATE",
                 "REFERENCE_LETTER", "PASSPORT")

Source = DocumentDraft | DocumentVersion
#: (source, row, FILE_FIELDS document): "draft" | "upload".
Held = tuple[str, Source, str]
Transform = Callable[[Sequence[Part], FileRule], Prepared]


@dataclass(frozen=True)
class Job:
    slot: str
    document: str
    sources: tuple[tuple[str, UUID], ...]  # ("draft" | "upload", id)
    rule: FileRule
    filename: str
    reason: str  # "", "name_needs_name_parts" or "name_unsafe"
    digest: str
    #: Per source: the 1-based pages taken from it, or None for the whole file.
    pages: tuple[tuple[int, ...] | None, ...] = ()


def _ascii(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.translate(_FOLD))
    return "".join(c for c in folded if c.isascii() and (c.isalnum() or c in "._-") or c == " ")


def _folds(value: str) -> bool:
    """Every letter survives the ASCII fold: "Məmmədova" and "Weiß" do, "Айсель" does not."""
    alpha = [c for c in value if c.isalpha()]
    return bool(alpha) and all(any(ch.isalpha() for ch in _ascii(c)) for c in alpha)


def file_name(pattern: str | None, *, full_name: str, fallback: str,
              extension: str, surname: str = "",
              given_name: str = "") -> tuple[str, str]:
    """The name the page asked for, or the fallback and why. Never a guessed name part:
    surname and given name come from what the student gave (IDENTITY), not from splitting
    the full name."""
    stem = fallback.rsplit(".", 1)[0]
    if not pattern:
        return f"{stem}{extension}", ""
    if any(p not in _KNOWN_PLACEHOLDERS for p in _PLACEHOLDER.findall(pattern)):
        # "{programme}" left in as text would be a name the page never asked for.
        return f"{stem}{extension}", "name_unknown_placeholder"
    if ("{given_name}" in pattern and not given_name) or (
        "{surname}" in pattern and not surname
    ):
        return f"{stem}{extension}", "name_needs_name_parts"
    used = [v for k, v in (("{full_name}", full_name), ("{surname}", surname),
                           ("{given_name}", given_name)) if k in pattern]
    if not all(_folds(v) for v in used):
        # A name the fold would drop leaves the page's pattern without the name.
        return f"{stem}{extension}", "name_unsafe"
    filled = (pattern.replace("{full_name}", full_name).replace("{surname}", surname)
              .replace("{given_name}", given_name))
    # Only the pattern's own extension is replaced: "Aysel M. Məmmədova" has a dot too.
    name = _PATTERN_EXTENSION.sub("", _ascii(filled).replace(" ", "_")).lstrip(".")
    if not name or ".." in name or not storage.SAFE_FILENAME.match(name + extension):
        return f"{stem}{extension}", "name_unsafe"
    return name + extension, ""


def _held(application: Application, *, listed_only: bool = False) -> list[Held]:
    """Each kind this application's cell holds in a sendable state -- the document
    table's choice, never ours.

    `listed_only`: only kinds whose cell is not NOT_NEEDED, i.e. kinds the
    programme's own sentences name. The whole-application bundle uses it (owner,
    2026-10-09): a document nobody asked for is not sent in one PDF."""
    table = table_for(
        application.student, [application],
        MailSignal.objects.filter(application=application).select_related("connection"),
    )
    column = next(
        (i for i, c in enumerate(table.columns) if c.application_id == application.id), None
    )
    if column is None:  # no column: a withdrawn application takes nothing
        return []
    out: list[Held] = []
    for (kind, _label), row in zip(ROWS, table.rows, strict=True):
        if listed_only and row.cells[column] == Cell.NOT_NEEDED:
            continue
        # The table lists newest first; several of one kind go oldest first (Review Focus 4).
        for held in reversed(table.held_all_for(kind, application.id)):
            if held.state not in SENDABLE or held.document_id is None:
                continue
            item: Source | None
            if held.source == "draft":
                document = kind if kind in DRAFT_DOCUMENTS else None
                item = DocumentDraft.objects.filter(id=held.document_id).exclude(
                    rendered_filename="").first()
            else:
                document = kind if kind in UPLOAD_DOCUMENTS else None
                item = DocumentVersion.objects.filter(
                    id=held.document_id, state="AVAILABLE").exclude(promoted_key="").first()
            if document is not None and item is not None:
                out.append((held.source, item, document))
    return out


def _marker(item: Source) -> str:
    """What makes a source's bytes these bytes: an upload's promoted key carries
    its content digest; a draft's version and stored filename name its render."""
    if isinstance(item, DocumentVersion):
        return item.promoted_key
    return f"{item.version}:{item.rendered_filename}"


def _fallback(item: Source, document: str) -> str:
    if isinstance(item, DocumentDraft):
        return item.rendered_filename
    return f"{document.lower()}{SERVED_TYPES.get(item.content_type, '.pdf')}"


def _combined(chosen: list[Held]) -> tuple[list[Held], list[tuple[int, ...] | None]]:
    """What one combined file takes: every document whole, except the transcript, which is
    its LIVE pages in slot order -- a retaken page in place of the one it replaced, never
    both and never after the rest (fix M1). A run of consecutive slots from one file is one
    part. A transcript nothing has read yet has no pages to go by and is taken whole; once
    any is read, one with no live page is left out (it is being read, or refused)."""
    files = {item.id: held for held in chosen
             if held[2] == "TRANSCRIPT" and isinstance(item := held[1], DocumentVersion)}
    runs: list[tuple[UUID, list[int]]] = []
    for document_id, number in (
        TranscriptPage.objects.filter(upload__document_id__in=files, superseded_at__isnull=True)
        .order_by("cycle__created_at", "slot")
        .values_list("upload__document_id", "number")
    ):
        if runs and runs[-1][0] == document_id:
            runs[-1][1].append(number)
        else:
            runs.append((document_id, [number]))
    out: list[Held] = []
    pages: list[tuple[int, ...] | None] = []
    placed = False
    for held in chosen:
        if held[1].id not in files or not runs:
            out.append(held)
            pages.append(None)
        elif not placed:
            placed = True
            for document_id, numbers in runs:
                out.append(files[document_id])
                pages.append(tuple(numbers))
    return out, pages


def jobs_for(application: Application) -> list[Job]:
    """The slots this application sends, each with the digest of its inputs.
    Pure over tenant rows: the caller holds the tenant scope and transaction."""
    records = application.kit_file_rules or []
    facts = verified_values(application.student)
    full_name = facts.get("identity.full_name", "")
    #: Collected on the dashboard (owner, 2026-10-09), confirmed like any fact.
    surname = facts.get("identity.surname", "")
    # A passport read writes given_names (one IDENTITY row per key); a typed answer, given_name.
    given_name = facts.get("identity.given_name") or facts.get("identity.given_names", "")

    def job(slot: str, document: str, chosen: list[Held], rule: FileRule, fallback: str,
            *, combined: bool = False) -> Job:
        extension = ".jpg" if rule.format == "JPG" else ".pdf"
        name, reason = file_name(rule.name_pattern, full_name=full_name, fallback=fallback,
                                 extension=extension, surname=surname,
                                 given_name=given_name)
        if combined:
            chosen, pages = _combined(chosen)
        else:
            pages = [None] * len(chosen)
        digest = hashlib.sha256(json.dumps(
            {"sources": [(s, str(i.id), _marker(i), *([list(p)] if p else []))
                         for (s, i, _), p in zip(chosen, pages, strict=True)],
             "rule": asdict(rule), "name": name}, sort_keys=True).encode()).hexdigest()
        return Job(slot, document, tuple((s, i.id) for s, i, _ in chosen), rule, name, reason,
                   digest, tuple(pages))

    if (bundle := bundle_rule(records)) is not None:
        # A stable sort: several of one kind keep _held's upload order.
        ordered = sorted(_held(application, listed_only=True),
                         key=lambda held: _BUNDLE_ORDER.index(held[2]))
        if not ordered:
            return []
        return [job("EVERY_DOCUMENT", "EVERY_DOCUMENT", ordered, bundle, "application.pdf",
                    combined=True)]
    by_document: dict[str, list[Held]] = {}
    for chosen in _held(application):
        by_document.setdefault(chosen[2], []).append(chosen)
    jobs: list[Job] = []
    for document, chosen_ones in by_document.items():
        rule = rule_for(records, document)
        if rule.empty:
            continue
        if rule.one_file and len(chosen_ones) > 1:
            # "All diplomas as one PDF": one job, slot = the document, oldest first. One
            # file holding several documents is a PDF whatever format the page allows.
            jobs.append(job(document, document, chosen_ones, replace(rule, format="PDF"),
                            f"{document.lower()}.pdf", combined=True))
            continue
        for chosen in chosen_ones:
            item = chosen[1]
            jobs.append(job(f"{document}:{item.id}", document, [chosen], rule,
                            _fallback(item, document)))
    return jobs


def _current(application: Application, jobs: list[Job]) -> dict[str, PreparedDocument]:
    wanted = {j.slot: j.digest for j in jobs}
    rows = PreparedDocument.objects.filter(application=application, slot__in=wanted)
    return {r.slot: r for r in rows if r.inputs_digest == wanted[r.slot]}


def current_prepared(application: Application) -> dict[str, PreparedDocument]:
    """The prepared rows still true of the current sources and rules, by slot.
    A row for a slot no longer wanted (a replaced upload) is never returned."""
    return _current(application, jobs_for(application))


def prepared_upload(
    prepared: dict[str, PreparedDocument], upload_id: UUID, kind: str
) -> PreparedDocument | None:
    """The READY copy of one upload among `current_prepared`'s rows: its own slot, or the
    one-file merge of its kind ("all diplomas as one PDF") that holds it. None when there
    is none, so the caller sends the original."""
    if kind not in UPLOAD_DOCUMENTS:
        return None
    row = prepared.get(f"{kind}:{upload_id}")
    merged = prepared.get(kind)
    if row is None and merged is not None and any(
        source.get("id") == str(upload_id) for source in merged.sources
    ):
        row = merged
    return row if row is not None and row.state == PreparedDocument.State.READY else None


def _parts(job: Job) -> list[Part]:
    parts = []
    for (source, source_id), pages in zip(job.sources, job.pages, strict=True):
        if source == "upload":
            parts.append(Part(upload=DocumentVersion.objects.get(id=source_id), pages=pages))
        else:
            draft = DocumentDraft.objects.get(id=source_id)
            parts.append(Part(own=storage.read_draft(draft, draft.rendered_filename)))
    return parts


def prepare_documents(application: Application, *, transform: Transform = prepare_files,
                      store: S3ObjectStore | None = None,
                      budget: float = PREPARE_BUDGET_SECONDS) -> list[PreparedDocument]:
    """Prepare every slot whose row is missing or stale. Worker-side only.

    Every database read and write runs in a short tenant_transaction: under FORCE
    RLS a query with no `app.tenant_id` matches nothing (CLAUDE.md, failure mode
    1). The parser call runs OUTSIDE any transaction, because it can take minutes.
    The object is stored before its row says READY, so a failed put never leaves
    a READY row pointing at nothing. A replaced object version, and the row and
    object of a slot the application no longer wants, are deleted (owner,
    2026-10-10; the role's delete grant covers prepared/ only). A failed delete
    only logs: the copy served is the new one, and erasure purges the prefix.

    Bounded: no parser call starts after `budget` seconds, and the first
    outage stops the run and is re-raised -- a down parser is down for
    every job, and the worker stops the student's other applications on it too.
    A job the parser itself failed (kind="job": timeout, out of memory) is
    recorded CANNOT_FIT / timed_out and the run goes on; the first trigger after
    RETRY_TIMED_OUT_AFTER tries it again. A run never overwrites a slot another run
    wrote after this one started: it deletes its own just-stored copy instead.
    What is left unprepared is served as the original until the next trigger.
    """
    deadline = time.monotonic() + budget
    run_start = timezone.now()
    tenant_id = application.tenant_id
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            jobs = jobs_for(application)
            retry_before = run_start - RETRY_TIMED_OUT_AFTER
            # A timed_out row stays the kit's note while it waits; it is just not done.
            done = {slot: row for slot, row in _current(application, jobs).items()
                    if not (row.reason == "timed_out" and row.prepared_at < retry_before)}
        results: list[PreparedDocument] = []
        complete = True
        for job in jobs:
            if job.slot in done:
                results.append(done[job.slot])
                continue
            if time.monotonic() >= deadline:
                logger.info("prepare: budget spent for application %s", application.id)
                complete = False
                break
            with tenant_transaction(tenant_id):
                parts = _parts(job)
            try:
                # A cap above what the parser can hand back is shrunk to what it can.
                target = replace(job.rule, max_bytes=min(job.rule.max_bytes or INLINE_MAX,
                                                         INLINE_MAX))
                answer = transform(parts, target)
            except OcrUnavailable as error:
                if error.kind == "outage":
                    logger.warning("prepare: parser unavailable for application %s",
                                   application.id)
                    raise
                # This one file broke the parser: record it and go on to the next.
                logger.warning("prepare: job failed for application %s", application.id)
                answer = Prepared(refused="timed_out")
            fields: dict[str, object] = {
                "tenant_id": tenant_id, "student_id": application.student_id,
                "document": job.document, "inputs_digest": job.digest,
                "sources": [{"source": s, "id": str(i), **({"pages": list(p)} if p else {})}
                            for (s, i), p in zip(job.sources, job.pages, strict=True)],
                "state": PreparedDocument.State.CANNOT_FIT, "reason": answer.refused,
                "filename": "", "content_type": "", "byte_size": None, "object_key": "",
                "object_version": "",
            }
            if answer.refused:
                logger.info("prepare.refused reason=%s document=%s application=%s",
                            answer.refused, job.document, application.id)
            if not answer.refused and answer.content_type is not None:
                key = storage.prepared_key(tenant_id=tenant_id, student_id=application.student_id,
                                           prepared_id=uuid4(), sha256=answer.sha256)
                version = storage.store_prepared(key, answer.body, store=store)
                fields.update(
                    state=PreparedDocument.State.READY, reason=job.reason, object_key=key,
                    object_version=version,
                    filename=job.filename.rsplit(".", 1)[0] + SERVED_TYPES[answer.content_type],
                    content_type=answer.content_type, byte_size=len(answer.body),
                )
            row = None
            try:
                with tenant_transaction(tenant_id):  # a savepoint: the race rolls back alone
                    old = PreparedDocument.objects.select_for_update().filter(
                        application=application, slot=job.slot
                    ).values_list("object_key", "object_version", "prepared_at").first()
                    # A row written since this run started is a fresher run's: our inputs
                    # are older than its, so it stands (final review M6).
                    if old is None or old[2] < run_start:
                        row, _ = PreparedDocument.objects.update_or_create(
                            application=application, slot=job.slot, defaults=fields)
            except IntegrityError:
                # Another worker inserted this slot first (prepareddoc_one_per_slot):
                # a race, not a bug. Its row stands; the next trigger re-checks it.
                row = None
            if row is None:
                logger.info("prepare: slot %s of application %s written concurrently",
                            job.slot, application.id)
                if fields["object_key"]:  # ours alone: the key carries a fresh uuid
                    _delete_object(str(fields["object_key"]), str(fields["object_version"]),
                                   store=store, application=application)
                continue
            results.append(row)
            if old and old[0] != row.object_key:
                _delete_object(old[0], old[1], store=store, application=application)
        if complete:
            _sweep(application, {j.slot for j in jobs}, store, run_start)
    return results


def _delete_object(key: str, version: str, *, store: S3ObjectStore | None,
                   application: Application) -> None:
    """Best effort: a leftover object is the erasure purge's to remove, so a failure
    here logs ids only and never fails the run. No version id (a row from before
    versions were recorded) means nothing exact to delete."""
    if not key or not version:
        return
    try:
        storage.delete_prepared(key, version, store=store)
    except Exception as error:
        logger.warning("prepare: could not delete a replaced file for application %s (%s)",
                       application.id, type(error).__name__)


def _sweep(application: Application, wanted: set[str], store: S3ObjectStore | None,
           run_start: datetime) -> None:
    """Rows for slots the application no longer sends, and their objects. A row
    written since this run started belongs to a fresher run: our `wanted` is stale
    for it, so it stays."""
    with tenant_transaction(application.tenant_id):
        stale = list(PreparedDocument.objects.filter(application=application)
                     .exclude(slot__in=wanted).filter(prepared_at__lt=run_start))
        for row in stale:
            row.delete()
    for row in stale:
        _delete_object(row.object_key, row.object_version, store=store, application=application)


def queue_for_student(tenant_id: UUID, student_id: UUID) -> None:
    """Queue preparation for a student's open applications, after commit. Never
    raises: a lost message only means the original is served, and the action
    that triggered it (approval, Start) must not fail because of it."""
    def _send() -> None:
        try:
            enqueue_document_work(
                DocumentWorkMessage(action="prepare_documents", kind="PREPARE",
                                    tenant_id=tenant_id, student_id=student_id),
                queue_url=settings.DOCUMENT_QUEUE_URL,
            )
        except Exception as error:
            logger.warning("could not queue prepare_documents (%s)", type(error).__name__)

    try:
        transaction.on_commit(_send)
    except Exception as error:
        logger.warning("could not queue prepare_documents (%s)", type(error).__name__)


#: What the student is told, by reason code. The code itself is never shown.
NOTE_TEXT = {
    "signed": "This document is digitally signed, so we did not change it. "
    "Check the portal accepts it as it is.",
    "too_large": "We could not make this small enough without making it hard to read. "
    "Upload the documents separately, or check the portal's size limit.",
    "too_large_to_return": "We could not make this small enough without making it hard to read. "
    "Upload the documents separately, or check the portal's size limit.",
    "image_too_large": "This image is larger than the programme allows and we could not "
    "shrink it enough. Send a smaller one.",
    "timed_out": "We couldn't prepare this file, so we left it as it is. "
    "Upload it as it is, or check the portal's limits.",
    "pages": "This document has more pages than the programme allows. "
    "Cut it down to the page limit before uploading.",
    "encrypted": "This file is password-protected, so we could not change it. "
    "Remove the password and upload it again.",
    "unreadable": "We could not read this file, so we did not change it. "
    "Check it opens, or upload it again.",
    "active_content": "This file contains active content (scripts or links that run on opening), "
    "so we did not change it; it is sent as you uploaded it.",
    "name_needs_name_parts": "The programme wants your name in this file's name "
    "\u2014 add your surname and given name on your profile.",
    "name_unsafe": "The programme's file-name rule could not be applied safely. "
    "Rename the file yourself if the portal asks for a particular name.",
    "name_unknown_placeholder": "The programme asks for a file name we could not work out. "
    "Rename the file yourself if the portal asks for a particular name.",
    # A refused whole-application bundle: carried by each original it fell back
    # to, so no single document is blamed for the bundle's reason.
    "bundle_failed": "The programme asks for all your documents in one PDF, and we could not "
    "combine them. Upload them separately, or combine them yourself.",
}


#: Why a whole-application bundle could not be built, said after bundle_failed's
#: sentence. Never an instruction of its own: bundle_failed already says what to do,
#: and the per-file sentences ("Upload the documents separately...") would repeat it.
BUNDLE_REASON = {
    "too_large": "The combined file would be too large to read clearly.",
    "too_large_to_return": "The combined file would be too large to read clearly.",
    "signed": "One of the documents is digitally signed, so we did not change it.",
    "pages": "The combined file would have more pages than the programme allows.",
    "encrypted": "One of the documents is password-protected.",
    "unreadable": "We could not read one of the documents.",
    "active_content": "One of the documents contains active content "
    "(scripts or links that run on opening).",
    "timed_out": "Combining them did not finish in time.",
}


def bundle_line(reason: str) -> str:
    """The one line for a refused whole-application bundle: what to do, then why."""
    return f"{NOTE_TEXT['bundle_failed']} {BUNDLE_REASON.get(reason, '')}".strip()


def note_text(reason: str) -> str:
    """The sentence for a reason code; an unknown code gets a generic one."""
    if not reason:
        return ""
    return NOTE_TEXT.get(reason, "We could not fully prepare this file. Check it before uploading.")
