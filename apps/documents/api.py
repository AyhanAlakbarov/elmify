"""The document engine's door: JSON over HTTP, no presentation layer.

Deliberately not DRF and deliberately not a template. The engine behind this
was complete and unreachable; what it needed was a caller, not a framework.
The presentation layer that eventually consumes these endpoints is still
undecided, and nothing here settles it.

Every document endpoint resolves ``current_membership(request, STUDENT)``
through ``_student_endpoint`` and receives that membership as an argument, so
the authorisation check and the ledger being written are the same object --
there is no way to pass the check and then act for a different student. A
counselor session gets 403 here: there is no staff surface behind this door
(staff login additionally needs an OTP-verify endpoint, which is separate
work).

Refusals on id-addressed endpoints are 404, never 403, matching
storage.download_document: a 403 would confirm the object exists.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import wraps
from typing import cast
from uuid import UUID

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.concierge.cycles import paid_cycle
from apps.concierge.documents import presigned_upload, register
from apps.concierge.models import UPLOAD_KIND_VALUES, DocumentVersion
from apps.funding.models import PackCandidate
from apps.funding.services import current_pack
from apps.portals.models import Application
from apps.ratelimit import login_rate_limited, rate_limited
from apps.tenancy.context import current_tenant_id
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .approval import ApprovalBlocked, mark_ready, verdicts_for
from .confirmation import FactNotFound, confirm_facts
from .document_queue import DocumentWorkMessage, enqueue_document_work
from .generation import generation_rate_limited
from .models import (
    DocumentDraft,
    TranscriptPage,
    TranscriptReading,
    TranscriptUpload,
    VerifiedFact,
)
from .transcript_pages import (
    TranscriptRegistrationRefused,
    register_transcript,
    replace_pending,
)
from .verification import ClaimVerdict, generatable_facts, unsuperseded_facts

#: The one place a document kind is validated, and it stays CV-only.
#:
#: **Do not widen this to add MOTIVATION_LETTER or CORE_NARRATIVE.** The
#: letter engine deliberately does NOT reach these endpoints: it adds no
#: route, no queue and no task definition, and `draft_detail`/`approve` both
#: filter on `kind__in=_SUPPORTED_KINDS` precisely so a letter draft cannot
#: arrive at them. A letter approved through `approve` would call
#: `approval.mark_ready` directly, skipping every letter gate and the
#: immigration-UNCERTAIN block that only
#: `letter_approval.mark_letter_ready` applies; a letter rendered through
#: `draft_detail` would be serialized with a CV-shaped verdict reader.
#: Adding a member here silently reopens both. Letters get their own
#: endpoints when they get any.
_SUPPORTED_KINDS = frozenset({DocumentDraft.Kind.CV})

#: A signed form is a write capability into the evidence bucket, so issuing
#: them is limited the same way any other write is.
_UPLOAD_RATE_LIMIT = 10
_UPLOAD_RATE_WINDOW_SECONDS = 3600

#: Confirmation is a write per fact plus an audit row per fact. The cap is on
#: the request, so an absurd batch is refused before it becomes a query.
_CONFIRM_RATE_LIMIT = 60
_CONFIRM_RATE_WINDOW_SECONDS = 3600
_MAX_CONFIRM_BATCH = 200

_View = Callable[..., HttpResponse]


class _ApiError(Exception):
    """A refusal with a status and a stable machine-readable code.

    The code is the contract with whatever renders this: it is matched on, so
    it must not be a sentence anyone will later reword.
    """

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _json_errors(view: _View) -> _View:
    @wraps(view)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        try:
            return view(request, *args, **kwargs)
        except _ApiError as error:
            return JsonResponse({"error": error.code}, status=error.status)

    return _wrapped


def _student_endpoint(view: _View) -> _View:
    """Authenticated + STUDENT in this tenant, resolved once, passed in.

    401 for "not signed in" and 403 for "not a student here" are both
    object-independent, so neither reveals anything: the id-addressed
    refusals inside the views are 404.

    Not django.contrib.auth.decorators.login_required, which redirects: a 302
    to a login page is not an answer a JSON client can act on.
    """

    @wraps(view)
    def _wrapped(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        if not request.user.is_authenticated:
            return JsonResponse({"error": "authentication_required"}, status=401)
        try:
            student = current_membership(request, Membership.Role.STUDENT)
        except PermissionDenied:
            return JsonResponse({"error": "student_membership_required"}, status=403)
        return view(request, student, *args, **kwargs)

    return _json_errors(_wrapped)


def _json_body(request: HttpRequest) -> dict[str, object]:
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        raise _ApiError(400, "invalid_json") from None
    if not isinstance(body, dict):
        raise _ApiError(400, "invalid_json")
    return body


def _programme_id(body: dict[str, object], student: Membership) -> UUID | None:
    """Parse the optional programme id and require it to be in the student's pack.

    "In the pack" means either (a) a candidate in the student's CURRENT pack
    (`current_pack` -- the latest version of their latest published run, i.e.
    what the student sees; a candidate they rejected or replaced is no longer
    in it), or (b) one of the student's own `portals.Application` rows. Both
    are tenant-scoped rows matched on their `program_id` column value alone:
    nothing here joins or traverses into `funding_program`, which the web
    role (`runtime_web`) holds no grant on.

    This replaces the shape-only check that followed the catalog read split
    (2026-09-25), and with it the corpus-existence oracle: the answer depends
    only on rows the student already holds, so it says nothing about which
    catalogue ids exist. A malformed id stays `unknown_programme`; a
    well-formed one outside the pack is `programme_not_in_pack`. The worker
    still drops an id that names no programme (`document_worker._generate`),
    as defence in depth.
    """
    raw = body.get("programme_id")
    if raw in (None, ""):
        return None
    try:
        programme_id = UUID(str(raw))
    except ValueError:
        raise _ApiError(400, "unknown_programme") from None
    pack = current_pack(student)
    in_pack = pack is not None and PackCandidate.objects.filter(
        pack_version=pack, candidate__program_id=programme_id
    ).exists()
    if not in_pack and not Application.objects.filter(
        student=student, program_id=programme_id
    ).exists():
        raise _ApiError(400, "programme_not_in_pack")
    return programme_id


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
@_json_errors
def auth_login(request: HttpRequest) -> HttpResponse:
    """GET issues the CSRF cookie; POST signs in.

    GET is not a spare endpoint. CsrfViewMiddleware rejects a POST with no
    token, and a client that has never made a request has no cookie to build
    one from -- so a POST-only login route cannot be used from a browser at
    all. One route with two methods beats a second endpoint nobody remembers
    to call first.

    The rate limiter keys on a stable integer derived from the (resolved)
    username, because there is no actor id before authentication and
    rate_limited takes UUID | int. Keying on the client address would limit a
    whole university's NAT together; keying on the username limits the
    account actually under attack -- but only if that key can't be forged.
    The hash must be cryptographic: CRC32 is linear over GF(2), so an
    attacker who knows a victim's username could construct a different
    username whose CRC32 collides with it, spend their ten attempts under
    that crafted name, and trip the victim's real key -- a targeted lockout
    of a chosen account, with no brute force required. SHA-256 closes that.

    A wrong password and an unknown username give the identical response. A
    different one is a username oracle.
    """
    if request.method == "GET":
        return JsonResponse({"authenticated": request.user.is_authenticated})
    body = _json_body(request)
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    # Signup stores the address lowercased and the student types it as they wrote
    # it. Resolved here, not in the backend: existing staff usernames are mixed-case,
    # and two accounts differing only in case keep their exact-match login.
    matches = list(
        get_user_model()
        .objects.filter(username__iexact=username)
        .values_list("username", flat=True)[:2]
    )
    if len(matches) == 1:
        username = matches[0]
    # Keyed on the RESOLVED username once one account matches: Postgres UPPER folds
    # 'ı' to 'I' and 'ſ' to 'S' where Python's .lower() does not, so a key built from
    # the typed string gave every such variant of one account its own ten attempts.
    if login_rate_limited(username):
        raise _ApiError(429, "rate_limited")
    user = authenticate(request, username=username, password=password)
    if user is None:
        raise _ApiError(401, "invalid_credentials")
    login(request, user)
    return JsonResponse({"authenticated": True})


@require_POST
def auth_logout(request: HttpRequest) -> HttpResponse:
    """POST only. A GET that ends a session is a CSRF hole dressed as a
    convenience -- any page can make the browser issue one."""
    logout(request)
    return JsonResponse({"authenticated": False})


@require_POST
@_student_endpoint
def uploads(request: HttpRequest, student: Membership) -> HttpResponse:
    """Register a document row, and sign a form that can only fill that row.

    The key is never accepted from the caller: register() derives it from the
    row it creates, and the presigned conditions pin that exact key. A caller
    therefore cannot aim an upload outside its own tenant's prefix even by
    lying about every field it does control.
    """
    if rate_limited(
        "api-upload",
        student.id,
        limit=_UPLOAD_RATE_LIMIT,
        window_seconds=_UPLOAD_RATE_WINDOW_SECONDS,
    ):
        raise _ApiError(429, "rate_limited")
    body = _json_body(request)
    kind = body.get("kind", "CV")
    if not isinstance(kind, str) or kind not in UPLOAD_KIND_VALUES:
        raise _ApiError(400, "invalid_kind")
    if kind == "TRANSCRIPT":
        try:
            document = register_transcript(student, body)
        except TranscriptRegistrationRefused as refused:
            raise _ApiError(refused.status, refused.code) from refused
    else:
        document = register(current_tenant_id(), student.id, kind=kind)
    presigned = presigned_upload(document)
    return JsonResponse(
        {
            "document_id": str(document.id),
            "url": presigned["url"],
            "fields": presigned["fields"],
        },
        status=201,
    )


@require_GET
@_student_endpoint
def upload_status(request: HttpRequest, student: Membership, document_id: UUID) -> HttpResponse:
    """The poll target, and the only place BLOCKED is visible.

    Without this endpoint a student whose file carried malware sees exactly
    what a student whose file yielded no facts sees -- ingest_uploaded_cv
    returns () for both. The candidates list cannot stand in for it.
    """
    document = DocumentVersion.objects.filter(id=document_id, student=student).first()
    if document is None:
        raise _ApiError(404, "not_found")
    body: dict[str, object] = {"state": document.state, "scan_result": document.scan_result}
    if document.rejection_message:
        body["message"] = document.rejection_message
    if document.kind == "TRANSCRIPT":
        upload = TranscriptUpload.objects.filter(document=document).first()
        body["reading"] = None if upload is None else {
            "state": upload.state, "refusal": upload.refusal, "refusal_page": upload.refusal_page,
        }
    return JsonResponse(body)


@require_GET
@_student_endpoint
def transcript(request: HttpRequest, student: Membership) -> HttpResponse:
    """The student's transcript as the reader holds it: its live pages and what is left to read."""
    cycle = paid_cycle(student.id)
    if cycle is None:
        raise _ApiError(402, "cycle_unpaid")
    pages = TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True).order_by("slot")
    uploads = TranscriptUpload.objects.filter(cycle=cycle)
    reading = TranscriptReading.objects.filter(cycle=cycle).order_by("-created_at").first()
    return JsonResponse({
        "pages_left": max(0, settings.TRANSCRIPT_PAGES_PER_CYCLE - cycle.pages_used),
        # Pages written but the reading not yet rebuilt is still waiting; delayed when that
        # rebuild is itself waiting on Jev (next_attempt_at set by delay).
        "waiting": uploads.filter(
            Q(state__in=("READING", "DELAYED")) | Q(state="READ", assembled=False)
        ).exists(),
        "delayed": uploads.filter(
            Q(state="DELAYED") | Q(state="READ", assembled=False, next_attempt_at__isnull=False)
        ).exists(),
        "replace_pending": replace_pending(cycle),
        "reading_id": str(reading.id) if reading else None,
        "pages": [
            {
                "slot": page.slot, "state": page.state, "refusal": page.refusal,
                "skipped_because": page.skipped_because,
                "retakes_left": max(0, settings.TRANSCRIPT_MAX_RETAKES - page.retakes),
            }
            for page in pages
        ],
    })


@require_GET
@_student_endpoint
def fact_candidates(request: HttpRequest, student: Membership) -> HttpResponse:
    """What the student is being asked to stand behind.

    Unsuperseded and unconfirmed, in the ledger's own order (oldest first),
    which is the order the uploaded CV listed things in.
    """
    facts = unsuperseded_facts(student).filter(confirmed_by__isnull=True)
    return JsonResponse(
        {
            "facts": [
                {"id": str(fact.id), "category": fact.category, "payload": fact.payload}
                for fact in facts
            ]
        }
    )


@require_POST
@_student_endpoint
def confirm(request: HttpRequest, student: Membership) -> HttpResponse:
    """The click. Everything downstream of it treats these as the student's own.

    ``actor`` is the student: approval_mode defaults to PER_DOCUMENT, so the
    student confirms their own ledger and this door adds no staff path.
    """
    if rate_limited(
        "api-confirm",
        student.id,
        limit=_CONFIRM_RATE_LIMIT,
        window_seconds=_CONFIRM_RATE_WINDOW_SECONDS,
    ):
        raise _ApiError(429, "rate_limited")
    raw = _json_body(request).get("fact_ids")
    if not isinstance(raw, list) or not raw:
        raise _ApiError(400, "fact_ids_required")
    if len(raw) > _MAX_CONFIRM_BATCH:
        raise _ApiError(400, "too_many_fact_ids")
    try:
        fact_ids = [UUID(str(value)) for value in raw]
    except ValueError:
        raise _ApiError(400, "fact_ids_invalid") from None
    try:
        confirmed = confirm_facts(student=student, fact_ids=fact_ids, actor=student)
    except FactNotFound:
        raise _ApiError(404, "not_found") from None
    return JsonResponse({"confirmed": confirmed})


@require_POST
@_student_endpoint
def generate(request: HttpRequest, student: Membership) -> HttpResponse:
    """Queue a generation, after running generate_cv's own preconditions here.

    This is what replaces a job-state table. Every check is cheap -- indexed
    reads, a field read, a cache read -- so every *predictable* failure
    is answered at request time and the client needs no polling to learn about
    it, including whether a programme id is in the student's own pack (see
    `_programme_id`). What stays asynchronous is model refusal and
    GenerationFailure, which are rare and land in the dead-letter queue the
    existing alarm pattern already covers.

    Nothing is enqueued when a check fails: a queued message that is certain
    to fail is a dead-letter entry someone has to read.
    """
    body = _json_body(request)
    kind = str(body.get("kind") or DocumentDraft.Kind.CV)
    if kind not in _SUPPORTED_KINDS:
        raise _ApiError(400, "unsupported_kind")
    programme_id = _programme_id(body, student)
    if not generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists():
        raise _ApiError(409, "identity_not_confirmed")
    if not student.application_email:
        raise _ApiError(409, "application_email_missing")
    if generation_rate_limited(student.id):
        raise _ApiError(429, "rate_limited")
    enqueue_document_work(
        DocumentWorkMessage(
            action="generate",
            kind=kind,
            tenant_id=current_tenant_id(),
            student_id=student.id,
            programme_id=programme_id,
        ),
        queue_url=settings.DOCUMENT_QUEUE_URL,
    )
    return JsonResponse({"status": "queued"}, status=202)


@require_GET
@_student_endpoint
def drafts(request: HttpRequest, student: Membership) -> HttpResponse:
    """Newest first. This is how the client learns a generation finished.

    There is no job row: a generation that succeeded is a draft, and one that
    failed is a dead-letter message with an alarm on it.
    """
    kind = request.GET.get("kind") or DocumentDraft.Kind.CV
    if kind not in _SUPPORTED_KINDS:
        raise _ApiError(400, "unsupported_kind")
    rows = (
        DocumentDraft.objects.filter(student=student, kind=kind)
        .order_by("-version")
        .values("id", "version", "status")
    )
    return JsonResponse(
        {
            "drafts": [
                {"id": str(row["id"]), "version": row["version"], "status": row["status"]}
                for row in rows
            ]
        }
    )


def _download_path(draft: DocumentDraft) -> str | None:
    """Where this draft's artefact is, or None until one has been stored.

    Built from `draft.rendered_filename`, which `storage.store_document` writes
    at the moment it puts the object, so the link names exactly the object that
    exists. A client polls this until it turns non-null. This never resolves a
    variant: the stored name is fixed at render time, so resolving it live from
    the programme or funder was wrong whenever either changed after rendering
    -- the link named an object that does not exist -- and it read catalogue
    tables the web role holds no grant on.
    """
    if draft.status != DocumentDraft.Status.APPROVED or not draft.rendered_filename:
        return None
    return reverse("documents-download", args=[draft.id, draft.rendered_filename])


@require_GET
@_student_endpoint
def draft_detail(request: HttpRequest, student: Membership, draft_id: UUID) -> HttpResponse:
    """The document, plus what the ledger currently says about each claim.

    claim_text is included: this is a response to the student's own browser,
    not a log line, and the review it drives is unusable without the text of
    the claim being judged. The rule it must not break is the other one --
    document text never reaches an exception message or a log.
    """
    # kind__in=_SUPPORTED_KINDS: this endpoint's response shape (claim_path,
    # fact_id) is CVContent-verdict-shaped. approval.verdicts_for became
    # kind-aware for MOTIVATION_LETTER/CORE_NARRATIVE drafts (Task 14), which
    # return LetterClaimVerdict instead -- a different shape this view never
    # learned to render. Excluding those kinds here keeps this generic
    # endpoint CV-only, matching _SUPPORTED_KINDS' documented scope, rather
    # than silently mis-serializing or auto-approving a letter draft without
    # ever running its own is_letter_blocked gates.
    draft = DocumentDraft.objects.filter(
        id=draft_id, student=student, kind__in=_SUPPORTED_KINDS
    ).first()
    if draft is None:
        raise _ApiError(404, "not_found")
    try:
        # cast: the kind__in=_SUPPORTED_KINDS filter above guarantees a CV
        # draft here, so verdicts_for's kind-aware dispatch (Task 14) always
        # returns ClaimVerdict, never LetterClaimVerdict, on this path.
        verdicts = cast("tuple[ClaimVerdict, ...]", verdicts_for(draft))
    except ApprovalBlocked:
        raise _ApiError(409, "malformed_content") from None
    return JsonResponse(
        {
            "id": str(draft.id),
            "version": draft.version,
            "status": draft.status,
            "download_path": _download_path(draft),
            "content": draft.content,
            "verdicts": [
                {
                    "claim_path": verdict.claim_path,
                    "claim_text": verdict.claim_text,
                    "verdict": str(verdict.verdict),
                    "fact_id": str(verdict.fact_id) if verdict.fact_id else None,
                }
                for verdict in verdicts
            ],
        }
    )


@require_POST
@_student_endpoint
def approve(request: HttpRequest, student: Membership, draft_id: UUID) -> HttpResponse:
    """Consent, then a render.

    mark_ready recomputes verdicts under lock from the draft's own content --
    nothing the caller sends can assert a draft is clean, and this endpoint
    deliberately offers no field that could. The render is enqueued only
    after approval succeeds: the worker's render path refuses a draft that is
    not APPROVED anyway, so a message sent before that is a guaranteed
    dead letter.
    """
    # kind__in=_SUPPORTED_KINDS: MOTIVATION_LETTER/CORE_NARRATIVE drafts must
    # be approved through letter_approval.mark_letter_ready (Task 14), which
    # runs is_letter_blocked's gates before ever reaching mark_ready here.
    # This endpoint calling mark_ready directly on a letter draft would skip
    # those gates entirely, so it never sees one.
    draft = DocumentDraft.objects.filter(
        id=draft_id, student=student, kind__in=_SUPPORTED_KINDS
    ).first()
    if draft is None:
        raise _ApiError(404, "not_found")
    # mark_ready is deliberately idempotent: an already-APPROVED draft comes
    # back unchanged rather than raising, so the view can't tell "just
    # approved" from "already approved" from its return value alone. Read
    # the pre-call status instead, and enqueue only on the DRAFT->APPROVED
    # transition -- a retry or double-click of an already-approved draft
    # still answers 202 (a slow first response shouldn't read as failure)
    # but queues no second render for it.
    # ponytail: two truly concurrent approves can both read DRAFT before
    # either writes APPROVED, so both would enqueue -- accepted, not fixed
    # here. The expensive half is already absorbed downstream:
    # EuropassRenderCache keys on the payload hash and its own docstring
    # names at-least-once delivery as the reason it doubles as the
    # idempotency key.
    was_approved = draft.status == DocumentDraft.Status.APPROVED
    try:
        approved = mark_ready(document=draft, accepted_by=student)
    except ApprovalBlocked as error:
        # cast: kind__in=_SUPPORTED_KINDS above guarantees a CV draft, so
        # error.verdicts is always ClaimVerdict here too (see draft_detail).
        blocking_verdicts = cast("tuple[ClaimVerdict, ...]", error.verdicts)
        return JsonResponse(
            {
                "error": "approval_blocked",
                "verdicts": [
                    {
                        "claim_path": verdict.claim_path,
                        "claim_text": verdict.claim_text,
                        "verdict": str(verdict.verdict),
                    }
                    for verdict in blocking_verdicts
                ],
            },
            status=409,
        )
    if not was_approved:
        enqueue_document_work(
            DocumentWorkMessage(
                action="render",
                kind=approved.kind,
                tenant_id=current_tenant_id(),
                student_id=student.id,
                draft_id=approved.id,
            ),
            queue_url=settings.DOCUMENT_QUEUE_URL,
        )
    return JsonResponse({"status": "queued"}, status=202)
