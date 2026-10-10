"""S3-quarantined document upload and scan-state machine.

Uploads land only under ``quarantine/{tenant_id}/{document_id}``. ``register``
*derives* that key from the row it creates rather than accepting one, so a
caller cannot store a key pointing outside its own tenant's prefix (Global
Constraint: tenant context must fail closed in object keys). A view issuing a
presigned POST scopes it to the returned ``object_key``. GuardDuty Malware
Protection scans that prefix and reports back via apply_scan_result.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID, uuid4

import boto3  # type: ignore[import-untyped]
from django.conf import settings

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


def register(tenant_id: UUID, student_id: UUID, kind: str = "CV") -> DocumentVersion:
    document_id = uuid4()
    with tenant_scope(tenant_id):
        return DocumentVersion.objects.create(
            id=document_id,
            tenant_id=tenant_id,
            student_id=student_id,
            object_key=f"quarantine/{tenant_id}/{document_id}",
            kind=kind,
        )


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
