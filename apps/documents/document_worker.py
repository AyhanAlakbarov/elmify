"""The document queues' handlers. Worker-side only.

Nothing here may be called from a view. Generation costs up to two model
calls against a 30-second gunicorn worker, and render.py:764-769 records that
the web tier must not call render_draft at all.

# ponytail: each handler holds one transaction across its slow call (a model
# call in the CV scan path, weasyprint in the render path). The transcript
# path does not: its OCR runs for minutes, so transcript_pages.process_upload
# runs it in short transactions around each slow step. RLS reads the
# app.tenant_id GUC, which SET LOCAL only holds inside a transaction, and both generate_cv and
# ingest_uploaded_cv read the ledger themselves -- so the call cannot sit
# outside one without splitting those functions' reads from their writes. One
# worker task at ~100 documents/day makes the held connection acceptable.
# Split them if that stops being true.
"""

from __future__ import annotations

import hashlib
import logging
import re
from uuid import UUID

from django.conf import settings

from apps.concierge.documents import SCAN_STATES, apply_scan_result
from apps.concierge.models import UPLOAD_REJECTIONS, DocumentVersion
from apps.funding.models import Program
from apps.research.provenance import Verdict, programme_verdict
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from . import storage
from .document_queue import DocumentWorkMessage, ScanResultEvent
from .drafts import create_draft
from .europass_queue import EuropassRenderMessage, enqueue_europass_render
from .generation import generate_cv
from .ingestion import UnsupportedUpload, ingest_uploaded_cv
from .models import DocumentDraft, TranscriptUpload, VerifiedFact
from .ocr import inspect_upload
from .render import UnsupportedRenderVariant, render_draft, resolve_variant
from .storage import DocumentStoreRefused, artefact_filename, store_document
from .transcript_pages import delay, process_upload
from .verification import generatable_facts

logger = logging.getLogger(__name__)

#: The exact shape register() derives: quarantine/{tenant_uuid}/{document_uuid},
#: hex and slashes only. Matching it is how the tenant scope for the write is
#: taken from a key WE minted rather than from anything in the event.
_KEY_PATTERN = re.compile(
    r"^quarantine/(?P<tenant_id>[0-9a-fA-F-]{36})/[0-9a-fA-F-]{36}$"
)


def handle_scan_result(event: ScanResultEvent) -> None:
    """Apply one GuardDuty verdict, and ingest the file if it came back clean.

    The object key is the ONLY value trusted out of the event -- it is a key
    register() derived, its shape is checked, and the tenant scope for every
    write below comes out of it. Nothing else in the envelope influences which
    row is written.

    An event that cannot find a row is logged and returns normally, so the
    message is DELETED rather than redelivered forever. There is no future
    delivery in which an unknown key becomes known.
    """
    tenant_id = _tenant_of(event)
    if tenant_id is None:
        return
    if event.scan_result not in SCAN_STATES:
        # apply_scan_result puts it in REVIEW_REQUIRED; this is the line that
        # makes an unknown status visible instead of merely survivable.
        logger.warning(
            "DocumentScanUnknownStatus status=%s key=%s", event.scan_result, event.object_key
        )

    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        document = DocumentVersion.objects.filter(object_key=event.object_key).first()
        if document is None:
            logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
            return
        if document.state in UPLOAD_REJECTIONS:
            # A redelivered clean verdict never reopens an upload the check refused.
            return
        apply_scan_result(document, event.scan_result)
        if document.state != "AVAILABLE":
            return
        if not document.promoted_key:
            # AVAILABLE means checked and promoted. Until _check_and_promote answers, a
            # clean upload is CHECKING; this overwrite shares apply_scan_result's
            # transaction, so AVAILABLE is never committed for an unchecked file.
            document.state = "CHECKING"
            # The version this verdict is about, and the only one ever checked, copied or
            # read: the key's latest version may be a later upload nobody scanned.
            document.scanned_version = event.version_id or ""
            document.save(update_fields=["state", "scanned_version"])
    # CHECKING is committed before the check, as the transcript read does: the check is a
    # call to the isolated function, and a task that dies during it leaves the document
    # CHECKING for the redelivery. Nothing below runs on an unchecked file.
    if document.state == "CHECKING" and not _check_and_promote(tenant_id, document):
        return
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        if document.kind == "CV":
            _ingest_cv(document, event.object_key)
            return
        if document.kind != "TRANSCRIPT":
            # A passport, diploma, certificate or letter is stored for the
            # student to attach (dashboard spec §6). Nothing reads its contents.
            return
        upload = (
            TranscriptUpload.objects.filter(document=document).values_list("id", flat=True).first()
        )
        if upload is None:
            # Registered by neither upload door (both call register_transcript), so no cycle was
            # ever checked as paid (R13).
            logger.warning("TranscriptWithoutUpload document=%s", document.id)
            document.state = "READ_FAILED"
            document.save(update_fields=["state"])
            return
    process_upload(tenant_id, upload)


def _check_and_promote(tenant_id: UUID, document: DocumentVersion) -> bool:
    """The upload check, then the copy the extension fetches (dashboard spec §6, "Upload
    safety"). The only way out of CHECKING: AVAILABLE (promoted) only on NO_THREATS_FOUND
    AND an allowed type AND no active content; otherwise a terminal state the student sees.

    Pinned twice to what was scanned: the bytes are the version the verdict named (never the
    key's latest -- the upload form stays valid for 900 s), and they are copied only when
    their digest is the one the check reports judging. The check runs in the isolated OCR
    function, which can write nothing, so the copy is ours. OcrUnavailable is not caught:
    the file stays CHECKING, the message is redelivered, and the last delivery's
    mark_read_failed ends it REVIEW_REQUIRED.
    """
    if not document.scanned_version:
        logger.warning("DocumentScanNoVersion document=%s", document.id)
        _settle(tenant_id, document, "REVIEW_REQUIRED")
        return False
    store = _object_store()
    body = store.get_version(document.object_key, document.scanned_version)
    verdict = inspect_upload(document, body)
    if verdict.sha256 != hashlib.sha256(body).hexdigest():
        # The check judged other bytes than these. No retry makes them agree.
        logger.warning("DocumentUploadMismatch document=%s", document.id)
        _settle(tenant_id, document, "REVIEW_REQUIRED")
        return False
    if verdict.type is None:
        rejected = "REJECTED_TYPE"
    elif verdict.active_content:
        rejected = "REJECTED_ACTIVE_CONTENT"
    else:
        try:
            with tenant_scope(tenant_id), tenant_transaction(tenant_id):
                storage.promote_upload(document, body, content_type=verdict.type, store=store)
        except DocumentStoreRefused:
            # Another verdict was written while this one was checked; it stands.
            logger.info("DocumentUploadSuperseded document=%s", document.id)
            return False
        return True
    if _settle(tenant_id, document, rejected):
        logger.warning(
            "DocumentUploadRejected document=%s state=%s found=%s",
            document.id, rejected, ",".join(verdict.active_content),
        )
    return False


def _settle(tenant_id: UUID, document: DocumentVersion, state: str) -> bool:
    """End CHECKING for the version that was checked, and only that: a verdict written
    meanwhile (BLOCKED, or a newer version under check) is never overwritten."""
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        settled = DocumentVersion.objects.filter(
            id=document.id, state="CHECKING", scanned_version=document.scanned_version
        ).update(state=state)
    if settled:
        document.state = state
    return bool(settled)


def _tenant_of(event: ScanResultEvent) -> UUID | None:
    if event.bucket_name != settings.EVIDENCE_BUCKET_NAME:
        # The EventBridge rule matches detail-type and source, which are
        # account-wide. Another bucket's scan is not ours to act on.
        logger.warning("DocumentScanForeignBucket bucket=%s", event.bucket_name)
        return None
    match = _KEY_PATTERN.match(event.object_key)
    if match is None:
        logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
        return None
    try:
        return UUID(match["tenant_id"])
    except ValueError:
        logger.warning("DocumentScanUnknownKey key=%s", event.object_key)
        return None


def mark_read_failed(event: ScanResultEvent) -> None:
    """The last delivery of a transcript's verdict failed: the resume sweep takes it from here.

    consume_once calls this on the delivery SQS dead-letters next -- whatever escaped
    process_upload (an engine or provider that did not answer, an answer outside its options, a
    file the page renderer crashed on). The upload is left DELAYED, never failed outright: the
    sweep retries it with a backoff and fails it after MAX_ATTEMPTS. A CV, a document with no
    upload, and an upload already refused, failed or assembled are not touched.

    An upload the check never answered for leaves CHECKING for REVIEW_REQUIRED: a person
    looks, nothing was promoted, and so there is nothing for the sweep to read.
    """
    tenant_id = _tenant_of(event)
    if tenant_id is None:
        return
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        unchecked = DocumentVersion.objects.filter(
            object_key=event.object_key, state="CHECKING"
        ).update(state="REVIEW_REQUIRED")
        upload = (
            TranscriptUpload.objects.filter(document__object_key=event.object_key)
            .values_list("id", flat=True)
            .first()
        )
    if unchecked:
        logger.warning("DocumentUploadUnchecked key=%s", event.object_key)
    elif upload is not None:
        delay(tenant_id, upload, reason="last_delivery")


def _ingest_cv(document: DocumentVersion, object_key: str) -> None:
    if VerifiedFact.objects.filter(
        student_id=document.student_id, source_ref=f"upload:{document.id}"
    ).exists():
        # SQS delivery is at-least-once. Re-applying the scan state is
        # harmless (same value), but a second ingestion duplicates every
        # candidate fact and the student confirms the same claim twice.
        logger.info("DocumentScanAlreadyIngested document=%s", document.id)
        return
    try:
        ingest_uploaded_cv(document=document, student=document.student)
    except UnsupportedUpload:
        # A JPEG, a PNG, a .txt CV: the commonest user error there is, and
        # not an error at all from the worker's side. Uncaught it escapes
        # consume_once and run_document_worker's two-exception filter, so
        # the task dies, the traceback trips DocumentWorkerCrashFilter --
        # and the ingestion's transaction rolls back with it. The poll endpoint
        # then answers QUARANTINED forever, which is exactly the
        # indistinguishability upload_status exists to prevent. Terminal,
        # visible, and the message is deleted rather than redelivered.
        # Anything else still raises: a genuine bug must crash loudly.
        logger.warning("DocumentIngestUnsupported document=%s key=%s", document.id, object_key)
        document.state = "REVIEW_REQUIRED"
        document.save(update_fields=["state"])


#: The variants render_draft turns into PDF bytes with nothing else supplied.
#: FUNDER_TEMPLATE needs a funder_template_id no draft carries, and
#: FIELD_MAPPED produces a dict. Both are out of this door's scope.
_LOCAL_PDF_VARIANTS = frozenset({"STANDARD", "EUROPASS", "GERMAN_TABULAR"})


def _object_store() -> S3ObjectStore:
    """Indirection for tests only -- the one seam store_document takes."""
    return S3ObjectStore()


def handle_document_work(message: DocumentWorkMessage) -> None:
    if message.action == "generate":
        _generate(message)
    elif message.action == "capture_requirements":
        _capture(message)
    else:
        _render(message)


def _capture(message: DocumentWorkMessage) -> None:
    """Copy the kit's catalogue parts onto a new Application (dashboard spec §7).

    Here because this worker runs as runtime_engine, which may read the
    catalogue; the web tier that created the Application may not.
    """
    from apps.portals import packets
    from apps.portals.models import Application

    if message.application_id is None:
        raise ValueError("capture message carries no application_id")
    with tenant_scope(message.tenant_id):
        with tenant_transaction(message.tenant_id):
            application = (
                Application.objects.select_related("student")
                .filter(id=message.application_id)
                .first()
            )
        if application is None:
            # Removed before the worker got to it: no later delivery finds it.
            logger.info("capture_requirements: application %s is gone", message.application_id)
            return
        packets.capture_requirements(application)


def _generate(message: DocumentWorkMessage) -> None:
    """Generate a document from the student's confirmed ledger and store the draft.

    The programme is loaded here, not passed on the message, because it is a
    shared-catalog row the web tier cannot read: the queue carries its id, and
    the endpoint (`api._programme_id`) now accepts only a programme in the
    student's current pack or one of their own `portals.Application` rows --
    it no longer merely checks that the value is a UUID. This worker's
    unknown-programme drop stays as defence in depth (e.g. a programme deleted
    between request and job): refused HERE, logged as the requester's error
    and returned from, so the message is deleted rather than crashing the
    task through three redeliveries into the DLQ; no redelivery makes an
    unknown id known.

    It is handed to BOTH calls on purpose -- ``generate_cv`` uses it to tailor
    the skills section, and ``create_draft`` records it so ``resolve_variant``
    can see it at render time. Passing it to only the first silently renders a
    funder-template programme as STANDARD.

    Every predictable failure (identity not confirmed, no application email,
    rate limit) was already checked synchronously by the generate endpoint.
    What reaches here and fails is model refusal, a GenerationFailure, or
    SkillMatchRateLimited -- rare, and the DLQ alarm is the right place for it.
    """
    if message.kind != DocumentDraft.Kind.CV:
        # The letter engine adds its branch here. Until it does, widening
        # api._SUPPORTED_KINDS alone would file a motivation letter as a CV --
        # silently, since create_draft stores whatever kind it is handed.
        raise ValueError(f"no generator for kind {message.kind!r}")
    tenant_id = message.tenant_id
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        student = Membership.objects.get(id=message.student_id)
        programme = None
        if message.programme_id is not None:
            programme = Program.objects.filter(id=message.programme_id).first()
            if programme is None:
                # Silent to the student: the request was accepted at the door
                # (api._programme_id already verified this id names a
                # programme in the student's pack or own applications --
                # this is the defence-in-depth path for a programme deleted
                # between that check and this job running), and this WARNING
                # is the only trace. A metric filter or a student-visible
                # failure on DocumentGenerateUnknownProgramme is not built.
                logger.warning(
                    "DocumentGenerateUnknownProgramme requester sent programme=%s "
                    "student=%s: no such catalogue programme, message dropped",
                    message.programme_id,
                    message.student_id,
                )
                return
            verdict, code = programme_verdict(programme)
            if verdict == Verdict.BLOCKED:
                # Spec §7.5, defence in depth: pack membership is already
                # verdict-filtered, so this fires only for a body blocked after
                # the pack was built. Dropped, not raised, for the same
                # reason as the unknown-programme case above.
                logger.warning(
                    "DocumentGenerateBlockedProgramme programme=%s code=%s student=%s: "
                    "not generated",
                    programme.id, code, message.student_id,
                )
                return
        result = generate_cv(student=student, programme=programme)
        create_draft(
            student=student,
            kind=message.kind,
            content=result.content,
            facts=list(generatable_facts(student)),
            programme=programme,
            actor=student,
        )


def _render(message: DocumentWorkMessage) -> None:
    """Render an approved draft, or hand it to the worker that may call europa.eu.

    The variant is resolved once, here, from the same expression render_draft
    uses -- the queue choice and the render must not be able to disagree.
    """
    if message.draft_id is None:
        # DocumentWorkMessage doesn't tie draft_id to action="render" -- a
        # buggy producer could send one without it. Raise, not assert: this
        # is a real check on externally-produced queue data, not a
        # type-checker appeasement, and it must survive python -O.
        raise ValueError("render message carries no draft_id")
    tenant_id = message.tenant_id
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            draft = DocumentDraft.objects.select_related(
                "programme", "funding_opportunity"
            ).get(id=message.draft_id)
            variant = resolve_variant(draft)

        if variant == "EUROPASS_API":
            # EuropassQueue is single-worker and pinned for the circuit
            # breaker and the europa.eu courtesy rate. Calling render_draft
            # here would bypass both, and nothing would store the result.
            enqueue_europass_render(
                EuropassRenderMessage(tenant_id=tenant_id, draft_id=draft.id),
                queue_url=settings.EUROPASS_QUEUE_URL,
            )
            return
        if variant not in _LOCAL_PDF_VARIANTS:
            raise UnsupportedRenderVariant(f"no worker render path for variant {variant!r}")

        with tenant_transaction(tenant_id):
            artifact = render_draft(draft=draft)
            if artifact.pdf_bytes is None:
                raise UnsupportedRenderVariant(f"variant {variant!r} produced no PDF")
            store_document(
                draft=draft,
                filename=artefact_filename(variant),
                content=artifact.pdf_bytes,
                store=_object_store(),
            )
