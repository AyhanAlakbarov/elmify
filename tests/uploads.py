"""An upload as the document worker leaves it once the check passed (Task 14)."""

import hashlib

from apps.concierge.models import DocumentVersion
from apps.documents.storage import upload_key
from apps.tenancy.context import tenant_scope


def promoted_upload(document, store, body, *, content_type="application/pdf"):
    """AVAILABLE, scanned clean, its checked copy under the student's prefix: what
    open_document reads. Scanned version test-version-1, the first put of the key."""
    key = upload_key(
        tenant_id=document.tenant_id,
        student_id=document.student_id,
        document_id=document.id,
        version=hashlib.sha256(body).hexdigest()[:16],
    )
    if store is not None:  # None: the test stands its own store in for every key
        store.put(key, body)
    fields = {
        "state": "AVAILABLE",
        "scan_result": "NO_THREATS_FOUND",
        "scanned_version": "test-version-1",
        "promoted_key": key,
        "content_type": content_type,
    }
    with tenant_scope(document.tenant_id):
        DocumentVersion.objects.filter(id=document.id).update(**fields)
    for name, value in fields.items():
        setattr(document, name, value)
    return document
