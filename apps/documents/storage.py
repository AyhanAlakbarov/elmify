from __future__ import annotations

import hashlib
import re
from typing import Any
from uuid import UUID

import boto3  # type: ignore[import-untyped]
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse

from apps.concierge.documents import open_document, upload_prefix
from apps.concierge.models import DocumentVersion
from apps.reports.models import ConsultationReport
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import current_tenant_id, tenant_scope
from apps.tenancy.db import set_local_tenant, tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership

from .models import DocumentDraft

#: Objects live in EvidenceBucket beside the research snapshots, under the
#: tenants/ prefix WebTaskRole and WorkerTaskRole are already scoped to.
#: Tenant first, so one prefix delete or one IAM condition covers a tenant.
_KEY_TEMPLATE = "tenants/{tenant_id}/students/{student_id}/documents/{draft_id}/{filename}"
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_COUNSELOR_ROLES = frozenset(
    {Membership.Role.COUNSELOR, Membership.Role.OWNER, Membership.Role.PLATFORM_ADMIN}
)


class InvalidFilename(ValueError):
    pass


class DocumentStoreRefused(ValueError):
    pass


def _object_store() -> S3ObjectStore:
    return S3ObjectStore()


def document_key(*, tenant_id: UUID, student_id: UUID, draft_id: UUID, filename: str) -> str:
    if not _SAFE_FILENAME.match(filename) or ".." in filename:
        raise InvalidFilename(f"unsafe document filename {filename!r}")
    return _KEY_TEMPLATE.format(
        tenant_id=tenant_id, student_id=student_id, draft_id=draft_id, filename=filename
    )


def artefact_filename(variant: str) -> str:
    """The filename a rendered draft is stored under, for one variant.

    Names the variant, so two variants of one draft cannot overwrite each other
    under the same key. Matches _SAFE_FILENAME above.

    The web tier never calls this: it links to `DocumentDraft.rendered_filename`,
    which `store_document` records from the name actually written.
    """
    return f"cv-{variant.lower().replace('_', '-')}.pdf"


def store_document(
    *,
    draft: DocumentDraft,
    filename: str,
    content: bytes,
    store: S3ObjectStore | None = None,
) -> str:
    """Persist a rendered artefact. Only an APPROVED draft gets stored.

    The key is derived from the *active tenant context*, never from the draft's
    own tenant_id -- a row that disagrees with the context is the case this
    refuses, rather than the case it writes under the row's preferred prefix.
    """
    tenant_id = current_tenant_id()
    if draft.tenant_id != tenant_id:
        raise DocumentStoreRefused("draft belongs to a different tenant than the active scope")
    if draft.status != DocumentDraft.Status.APPROVED:
        raise DocumentStoreRefused(f"draft is {draft.status}, not APPROVED")
    key = document_key(
        tenant_id=tenant_id, student_id=draft.student_id, draft_id=draft.id, filename=filename
    )
    (store or _object_store()).put(key, content)
    # Recorded here, not by each caller, because this is the only place an
    # artefact is written: the name the web tier links to is exactly the one
    # just put. Its own transaction because the Europass cross-draft re-store
    # calls this outside any.
    with tenant_transaction(tenant_id):
        DocumentDraft.objects.filter(id=draft.id).update(rendered_filename=filename)
    draft.rendered_filename = filename
    return key


def _requesting_membership(request: HttpRequest) -> Membership | None:
    """The caller's active membership in the *current* tenant, whatever its role.

    apps.tenancy.services.current_membership takes a fixed role, so it cannot
    answer this question. Membership.objects is the tenant-scoped manager, and
    RLS backs it, so the tenant filter is not being skipped here.
    """
    if request.user.pk is None:
        return None
    return Membership.objects.filter(user_id=request.user.pk, active=True).first()


def _may_read(membership: Membership, draft: DocumentDraft) -> bool:
    if draft.student_id == membership.id:
        return True
    if membership.role not in _COUNSELOR_ROLES:
        return False
    # Same gate as apps/funding/views.py::review -- a counselor sees the
    # students assigned to them, not every student in the tenant.
    return CounselorAssignment.objects.filter(
        counselor=membership, student_id=draft.student_id, active=True
    ).exists()


@login_required
def download_document(request: HttpRequest, draft_id: UUID, filename: str) -> HttpResponse:
    """Stream a stored artefact. Never a public or presigned URL.

    Every refusal is a 404: a 403 would confirm the document exists.
    """
    membership = _requesting_membership(request)
    if membership is None:
        raise Http404
    try:
        draft = DocumentDraft.objects.get(id=draft_id, status=DocumentDraft.Status.APPROVED)
    except DocumentDraft.DoesNotExist as error:
        raise Http404 from error
    if not _may_read(membership, draft):
        raise Http404
    try:
        body = read_draft(draft, filename)
    except (InvalidFilename, KeyError) as error:
        raise Http404 from error
    response = HttpResponse(body, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _purge_prefix(s3: Any, bucket: str, prefix: str) -> int:
    """Erase every stored version under one prefix.

    EvidenceBucket has versioning enabled, so DeleteObject alone would only add
    a delete marker and leave the prior versions readable. This enumerates
    list_object_versions and deletes each VersionId, delete markers included.
    """
    markers: dict[str, str] = {}
    deleted = 0
    while True:
        page = s3.list_object_versions(Bucket=bucket, Prefix=prefix, **markers)
        entries = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for group in ("Versions", "DeleteMarkers")
            for item in page.get(group, [])
        ]
        if entries:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": entries})
            deleted += len(entries)
        if not page.get("IsTruncated"):
            return deleted
        markers = {
            "KeyMarker": page["NextKeyMarker"],
            "VersionIdMarker": page["NextVersionIdMarker"],
        }


def delete_student_documents(
    *, tenant_id: UUID, student_id: UUID, client: object | None = None
) -> int:
    """Erase every object holding one student's documents, from THREE sources.

    Scoped to the student, not the tenant: a DeletionRequest is one person
    exercising erasure, and a tenant-wide prefix delete would take every other
    student in the agency with it.

    Two prefixes, because the student's own uploaded CV -- the most personal
    artefact in the system -- is not under theirs. Released artefacts sit at
    tenants/{tenant}/students/{student}/, but an upload lands at
    quarantine/{tenant}/{document_id}: apps/concierge/documents.py::register
    puts the tenant first and has no student segment at all, so a scan of the
    student prefix misses it entirely. Before the HTTP door, register() had no
    caller and nothing was ever written there; every uploaded CV lands there
    now, and an erasure that skipped it recorded EXECUTED over a CV nothing
    could subsequently remove -- no code enumerated it and no role held delete
    on that prefix. A false compliance record is worse than an incomplete one.

    A third source, ConsultationReport, because its object at
    tenants/{tenant}/reports/{pack_id}/{digest}.html sits under NEITHER
    prefix above. Redacting object_key alone (apps/audit/redaction.py) hides
    nothing: sha256, s3_version_id and the pack_version FK are all KEEP and
    survive erasure, and the key is exactly {tenant_id} + {pack.id} + digest,
    all reconstructible from those survivors. Emptying the column removes our
    ability to find and delete the object, not anyone's ability to read it --
    so it is purged here, by exact key, same as the quarantine uploads below.

    All three sources in ONE function rather than a sibling advance_deletion
    also calls: this is the single call the erasure path makes, so an erasure
    that covers some and not others cannot be written by accident, and a test
    that stubs erasure out cannot stub out part of it.

    The quarantine and report keys come from the student's own DocumentVersion
    and ConsultationReport rows, so finding them needs no bucket-wide listing;
    each is then erased by exact key, versions included, exactly as the prefix
    above is.

    That read runs with the tenant GUC set, not merely under tenant_scope:
    concierge_documentversion and reports_consultationreport are both FORCE
    ROW LEVEL SECURITY keyed on app.tenant_id, tenant_scope is only a
    contextvar and never touches Postgres, and the production runtime role is
    NOBYPASSRLS. Without set_local_tenant the query is legal SQL that silently
    returns zero rows -- the erasure runs, advance_deletion records EXECUTED,
    and the student's uploaded CV or consultation report is never touched.
    set_local_tenant requires an open transaction (TransactionManagementError
    otherwise), hence the atomic() wrapped around this one read -- both models
    are read inside it, so there is still only one transaction here.
    """
    s3: Any = client if client is not None else boto3.client("s3")
    bucket = settings.EVIDENCE_BUCKET_NAME
    deleted = _purge_prefix(s3, bucket, f"tenants/{tenant_id}/students/{student_id}/")
    with tenant_scope(tenant_id), transaction.atomic():
        set_local_tenant(tenant_id)
        uploads = list(
            DocumentVersion.objects.filter(student_id=student_id).values_list(
                "object_key", flat=True
            )
        )
        report_keys = list(
            ConsultationReport.objects.filter(
                pack_version__run__profile_version__student_id=student_id
            ).values_list("object_key", flat=True)
        )
    for key in [*uploads, *report_keys]:
        # An empty key is a prefix that matches the whole bucket -- every
        # tenant's objects, deleted by a routine asked to erase one student.
        # register() always sets object_key (and so does generate_report), so
        # this guards a row that should not exist; the cost of being wrong
        # about that is unrecoverable.
        if not key:
            continue
        # An object_key used as a prefix: it is exact and ends in a UUID or a
        # digest, so it matches that one object and nothing else.
        deleted += _purge_prefix(s3, bucket, key)
    return deleted


#: Confirmation screenshots sit under the student's own prefix, so
#: _purge_prefix(tenants/<t>/students/<s>/) erases them with everything else. A
#: separate top-level prefix would be a second thing to remember at erasure,
#: and the one this codebase already forgot (EuropassRenderCache) is exactly
#: that shape.
_SUBMISSION_TEMPLATE = "tenants/{tenant_id}/students/{student_id}/submissions/{step_id}.png"


def store_submission_image(
    *, tenant_id: UUID, student_id: UUID, step_id: UUID, image: bytes
) -> str:
    """Store one submission confirmation image and return its key.

    PNG, because the extension captures the visible tab and Chrome's
    captureVisibleTab returns PNG unless asked otherwise. The key says so; a
    content script that switched format would have to change this too.
    """
    key = _SUBMISSION_TEMPLATE.format(
        tenant_id=tenant_id, student_id=student_id, step_id=step_id
    )
    _object_store().put(key, image)
    return key


def upload_key(*, tenant_id: UUID, student_id: UUID, document_id: UUID, version: str) -> str:
    """A checked upload's copy: concierge.documents.upload_prefix plus the version."""
    prefix = upload_prefix(tenant_id=tenant_id, student_id=student_id, document_id=document_id)
    return prefix + version


def promote_upload(
    document: DocumentVersion, body: bytes, *, content_type: str, store: S3ObjectStore
) -> str:
    """Copy a checked upload, byte for byte, under the student's prefix. Worker side only:
    the caller read `body` from quarantine/ (DocumentWorkerTaskRole's grant, never the web
    tier's) and `content_type` is the upload check's. Nothing here rewrites the file.

    The version segment is the content's own digest, so a redelivered verdict writes the
    same key. This is the one write that makes an upload AVAILABLE: the key, the type and
    the state land together, so AVAILABLE always means checked and promoted.

    The state is claimed first, and only from CHECKING for the version that was checked: a
    verdict written while the check ran (a re-upload BLOCKED, a newer version now being
    checked) is never overwritten, and a refused claim writes no object. The put runs inside
    the caller's transaction, so a failed put leaves the row CHECKING.
    """
    key = upload_key(
        tenant_id=document.tenant_id, student_id=document.student_id, document_id=document.id,
        version=hashlib.sha256(body).hexdigest()[:16],
    )
    claimed = DocumentVersion.objects.filter(
        id=document.id, state="CHECKING", scanned_version=document.scanned_version
    ).update(state="AVAILABLE", promoted_key=key, content_type=content_type)
    if not claimed:
        raise DocumentStoreRefused("document is no longer CHECKING this version")
    store.put(key, body)
    document.state, document.promoted_key, document.content_type = "AVAILABLE", key, content_type
    return key


def read_draft(draft: DocumentDraft, filename: str) -> bytes:
    """A stored artefact's bytes: InvalidFilename for a name that is not one,
    KeyError when nothing is stored under it."""
    return _object_store().get(
        document_key(
            tenant_id=draft.tenant_id,
            student_id=draft.student_id,
            draft_id=draft.id,
            filename=filename,
        )
    )


def read_upload(document: DocumentVersion) -> bytes:
    """The promoted copy's bytes, for the extension route: open_document's read, so only
    an AVAILABLE upload's copy under its own uploads/ prefix (DocumentUnavailable else)."""
    return open_document(document, store=_object_store())
