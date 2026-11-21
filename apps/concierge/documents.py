"""S3-quarantined document upload and scan-state machine.

Uploads land only under ``quarantine/{tenant_id}/{document_id}``. ``register``
*derives* that key from the row it creates rather than accepting one, so a
caller cannot store a key pointing outside its own tenant's prefix (Global
Constraint: tenant context must fail closed in object keys). A view issuing a
presigned POST scopes it to the returned ``object_key``. GuardDuty Malware
Protection scans that prefix and reports back via apply_scan_result.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol
from uuid import UUID, uuid4

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope

from .models import DocumentVersion


class ReadableObjectStore(Protocol):
    def get(self, key: str) -> bytes: ...


class PresignClient(Protocol):
    def generate_presigned_post(self, **kwargs: object) -> dict[str, object]: ...


SCAN_STATES = {
    "NO_THREATS_FOUND": "AVAILABLE",
    "THREATS_FOUND": "BLOCKED",
    "UNSUPPORTED": "REVIEW_REQUIRED",
    "ACCESS_DENIED": "REVIEW_REQUIRED",
    "FAILED": "REVIEW_REQUIRED",
}

#: A CV, not a corpus. Big enough for a scanned multi-page PDF, small enough
#: that a signed form is not an open upload slot into the evidence bucket.
#: Equal to ocr/read_pages.py's MAX_BYTES (pinned by test): the upload check
#: runs there, and a file above its cap would pass S3 and the scan only to end
#: REVIEW_REQUIRED.
_MAX_UPLOAD_BYTES = 10_000_000
#: Long enough to start an upload on a bad connection, short enough that a
#: leaked form is not a standing grant.
_PRESIGN_EXPIRY_SECONDS = 900


class DocumentUnavailable(RuntimeError):
    pass


class UploadModeRefused(ValueError):
    """A Replace / Add another request refused before any row is written: an HTTP status
    and a stable code."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


#: Kinds where a second upload is usually another document, not a better copy: a letter
#: from another referee (fix I1), or a project report beside a thesis. With no mode, these add.
ADD_BY_DEFAULT = frozenset({"REFERENCE_LETTER", "THESIS_OR_REPORT"})
#: The presigned form lives 900 s, plus scan time: a replacement registered and never sent
#: stops holding its target after this (register_transcript's _PENDING_WINDOW).
_PENDING_WINDOW = timedelta(minutes=20)


def register(
    tenant_id: UUID,
    student_id: UUID,
    kind: str = "CV",
    *,
    mode: object = None,
    replaces: object = None,
) -> DocumentVersion:
    """`mode` REPLACE (today's behaviour, the default) or ADD (a second degree, say). With
    no mode, a kind in ADD_BY_DEFAULT adds and every other kind replaces.

    A REPLACE names the held upload it replaces: `replaces`, or the one AVAILABLE upload of
    this kind when there is exactly one. With several held it must name one ("replace_which"),
    so replacing the master's diploma never retires the bachelor's. Retirement itself waits
    for promotion (document_worker). A transcript ignores both: register_transcript's own
    ADD / REPLACE / RETAKE retire through its reading (transcript_pages._write).
    """
    if mode is None:
        mode = "ADD" if kind in ADD_BY_DEFAULT else "REPLACE"
    if mode not in ("REPLACE", "ADD"):
        raise UploadModeRefused("invalid_mode")
    document_id = uuid4()
    with tenant_scope(tenant_id), transaction.atomic():
        target = None if kind == "TRANSCRIPT" else _replaced(student_id, kind, mode, replaces)
        return DocumentVersion.objects.create(
            id=document_id,
            tenant_id=tenant_id,
            student_id=student_id,
            object_key=f"quarantine/{tenant_id}/{document_id}",
            kind=kind,
            replaces=target,
        )


def _replaced(student_id: UUID, kind: str, mode: object, replaces: object) -> UUID | None:
    if mode == "ADD":
        if replaces is not None:
            raise UploadModeRefused("invalid_replaces")
        return None
    held = DocumentVersion.objects.filter(
        student_id=student_id, kind=kind, state="AVAILABLE", retired_at__isnull=True
    ).values_list("id", flat=True)
    if replaces is None:
        ids = list(held[:2])
        if len(ids) > 1:
            raise UploadModeRefused("replace_which")
        return _unclaimed(ids[0] if ids else None)
    try:
        target = UUID(str(replaces))
    except ValueError:
        raise UploadModeRefused("invalid_replaces") from None
    if not held.filter(id=target).exists():
        raise UploadModeRefused("invalid_replaces")
    return _unclaimed(target)


def _unclaimed(target: UUID | None) -> UUID | None:
    """Refuse a second replacement of an upload another is still replacing (fix M2): the
    target row is locked, so two requests cannot both pass. A replacement still being
    checked holds it; one registered and never sent stops holding it after the window, and
    a rejected one at once."""
    if target is None:
        return None
    DocumentVersion.objects.select_for_update().filter(id=target).first()
    pending = DocumentVersion.objects.filter(replaces=target, retired_at__isnull=True).filter(
        Q(state="CHECKING")
        | Q(state="QUARANTINED", created_at__gt=timezone.now() - _PENDING_WINDOW)
    )
    if pending.exists():
        raise UploadModeRefused("replace_pending", status=409)
    return target


def retire_replaced(document: DocumentVersion) -> None:
    """Retire what an AVAILABLE upload replaces. Called inside the promotion's transaction,
    so the new copy and the retirement land together."""
    if document.replaces is None or document.state != "AVAILABLE":
        return
    DocumentVersion.objects.filter(
        id=document.replaces, student_id=document.student_id, kind=document.kind,
        retired_at__isnull=True,
    ).update(retired_at=timezone.now())


def presigned_upload(
    document: DocumentVersion, *, client: PresignClient | None = None
) -> dict[str, object]:
    """A browser-postable form scoped to exactly this document's own key.

    The key is not a parameter -- it comes off the row ``register`` derived it
    on -- and the POST conditions pin it by EQUALITY. ``starts-with`` on the
    tenant prefix would turn one student's signed form into a write capability
    over every document in the agency, including one already scanned clean.

    The size ceiling is a condition rather than a check after the fact: S3
    rejects the upload itself, so an oversized file never reaches the bucket
    and never costs a scan.
    """
    s3 = client or boto3.client("s3")
    result = s3.generate_presigned_post(
        Bucket=settings.EVIDENCE_BUCKET_NAME,
        Key=document.object_key,
        Fields={"key": document.object_key},
        Conditions=[
            {"key": document.object_key},
            ["content-length-range", 1, _MAX_UPLOAD_BYTES],
        ],
        ExpiresIn=_PRESIGN_EXPIRY_SECONDS,
    )
    return dict(result)


def apply_scan_result(document: DocumentVersion, result: str) -> DocumentVersion:
    """Record GuardDuty's verdict on one quarantined object.

    An unrecognised status is REVIEW_REQUIRED rather than a KeyError. AWS
    publishes five scanResultStatus values today and may add a sixth; a
    KeyError here kills whatever is draining the scan queue, the message
    redelivers, and every other student's upload waits behind it until the
    DLQ catches it. The raw value is still recorded (capped to the column
    width) so an unknown status is visible on the row rather than smoothed
    away.
    """
    with tenant_scope(document.tenant_id):
        document.state = SCAN_STATES.get(result, "REVIEW_REQUIRED")
        document.scan_result = result[:20]
        document.save(update_fields=["state", "scan_result"])
    return document


def upload_prefix(*, tenant_id: UUID, student_id: UUID, document_id: UUID) -> str:
    """Where a scanned-clean, checked upload's copy lives: under the student's own
    prefix, so the web tier (tenants/* read) can serve it and erasure's prefix
    purge removes it. storage.upload_key writes under it; open_document refuses
    anything outside it -- one definition, so the two cannot drift."""
    return f"tenants/{tenant_id}/students/{student_id}/uploads/{document_id}/"


def open_document(document: DocumentVersion, *, store: ReadableObjectStore | None = None) -> bytes:
    """Read an upload's checked copy: AVAILABLE, and promoted (Task 14).

    Never the quarantine key. The upload form stays valid for 900 s, so that key's latest
    version can be bytes nobody scanned or checked; the promoted copy is the version
    GuardDuty scanned, copied only when its digest matched the upload check's. Every reader
    -- CV ingestion, the transcript read, evidence intake, the extension route -- reads
    this, and only under the document's own uploads/ prefix, so no row can point it
    elsewhere.
    """
    if document.state != "AVAILABLE":
        raise DocumentUnavailable(f"document is {document.state}")
    own = upload_prefix(
        tenant_id=document.tenant_id, student_id=document.student_id, document_id=document.id
    )
    if not document.promoted_key.startswith(own) or ".." in document.promoted_key:
        raise DocumentUnavailable("document has no checked copy")
    return (store or S3ObjectStore()).get(document.promoted_key)
