"""The counsellor on one student's board (dashboard spec §4a).

Full rights, each write audited with the counsellor as actor. Starting an
application and the fill stay with the student -- their own browser, their own
extension -- so nothing here queues a device action. Staff MFA runs in
TenantMembershipMiddleware before any of this. Anyone but an active assignee of
this student in this agency gets a 404.

The middleware's deletion and processing locks look at the REQUESTER only, so
every route here checks the TARGET student's locks itself (``locks.paused_reason``).
"""

from __future__ import annotations

import json
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.concierge.documents import presigned_upload, register
from apps.concierge.models import UPLOAD_KIND_VALUES, Notification
from apps.concierge.services import (
    MessageBodyError,
    acknowledge_notification,
    clean_message_body,
    send_message,
)
from apps.concierge.views import messages_context
from apps.documents.gap_intake import submit_answers
from apps.documents.gaps import UnanswerableQuestion
from apps.documents.transcript_pages import TranscriptRegistrationRefused, register_transcript
from apps.documents.views import page_context, render_gap_page
from apps.funding.models import (
    AuditEvent,
    PackCandidate,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import current_pack
from apps.portals.applications import (
    REFUSALS,
    ApplicationRefused,
    accept_offer,
    add_application,
    ignore_offer,
    offer_for,
    record_portal,
    remove_application,
)
from apps.portals.models import Application
from apps.portals.outcome import correct_outcome
from apps.ratelimit import rate_limited
from apps.tenancy.middleware import deletion_lock_target
from apps.tenancy.models import CounselorAssignment, Membership
from apps.tenancy.services import current_membership

from .board import board_for
from .locks import paused_reason
from .needs import items_for
from .pack import applied_candidate_ids

_MESSAGE_LIMIT = 20
_MESSAGE_WINDOW_SECONDS = 60
_UPLOAD_LIMIT = 10
_UPLOAD_WINDOW_SECONDS = 3600


def _assigned(request: HttpRequest, student_id: UUID) -> tuple[Membership, Membership]:
    """The caller as an active counsellor, and the student they actively hold.

    Anything else -- a student, an owner, an unassigned or ended assignment --
    is a 404, never a hint the student exists. The counsellor's membership is
    tenant-scoped, so the assignment is in this agency by construction.
    """
    try:
        counselor = current_membership(request, Membership.Role.COUNSELOR)
    except PermissionDenied:
        raise Http404 from None
    assignment = get_object_or_404(
        CounselorAssignment.objects.select_related("student__user"),
        counselor=counselor,
        student_id=student_id,
        active=True,
    )
    return counselor, assignment.student


def _application(student: Membership, application_id: UUID) -> Application:
    return get_object_or_404(
        Application.objects.select_related("portal_form", "candidate"),
        id=application_id,
        student=student,
    )


def _back(student: Membership) -> HttpResponse:
    return redirect("counselor-student-board", student_id=student.id)


def _for_write(
    request: HttpRequest, student_id: UUID
) -> tuple[Membership, Membership, HttpResponse | None]:
    """_assigned, plus the pause: while the student is paused, every write is
    refused 409 and the board comes back read-only. Checked before any object
    lookup, so a refused write learns nothing about the id it named."""
    counselor, student = _assigned(request, student_id)
    refusal = _board_page(request, student, status=409) if paused_reason(student) else None
    return counselor, student, refusal


def _board_page(
    request: HttpRequest,
    student: Membership,
    *,
    status: int = 200,
    error: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    board = board_for(student, counselor_view=True)
    pack = current_pack(student)
    applied = applied_candidate_ids(student)
    addable = (
        [
            member.candidate
            for member in PackCandidate.objects.filter(pack_version=pack)
            .select_related("candidate")
            .order_by("candidate__program_name")
            if member.candidate_id not in applied
            and member.candidate.state == RecommendationCandidate.State.VISIBLE
            and (member.candidate.funding_card or {}).get("route") != "AUTOMATIC_ON_ADMISSION"
        ]
        if pack is not None
        else []
    )
    context: dict[str, object] = {
        **page_context(student, counselor_view=True),
        **messages_context(student),
        "student": student,
        "board": board,
        "needs": items_for(student, board=board, counselor_view=True),
        "outcome_choices": Application.Outcome.choices,
        "addable": addable,
        "error": error,
        "error_form": "message" if error else None,
        "form_values": form_values or {},
        # A sentence when paused; the shared includes hide every form on it.
        "read_only": paused_reason(student),
        # The pack review page (counselor/runs/<id>/approve/) for the newest run.
        "review_run_id": RecommendationRun.objects.filter(profile_version__student=student)
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first(),
    }
    return render(request, "counselor/student_board.html", context, status=status)


@login_required
def student_board(request: HttpRequest, student_id: UUID) -> HttpResponse:
    _counselor, student = _assigned(request, student_id)
    return _board_page(request, student)


@login_required
@require_POST
def add(request: HttpRequest, student_id: UUID, candidate_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        add_application(student=student, candidate_id=candidate_id, actor=counselor)
    except ApplicationRefused as refused:
        if refused.reason == "not_found":
            raise Http404 from refused
        messages.error(request, REFUSALS[refused.reason])
    return _back(student)


@login_required
@require_POST
def record_outcome(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        correct_outcome(
            _application(student, application_id), request.POST.get("outcome", ""), actor=counselor
        )
    except ValueError:
        messages.error(request, "Choose an outcome from the list.")
    return _back(student)


@login_required
@require_POST
def remove(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        remove_application(_application(student, application_id), actor=counselor)
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    return _back(student)


@login_required
@require_POST
def portal(request: HttpRequest, student_id: UUID, application_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    try:
        record_portal(
            _application(student, application_id), request.POST.get("form_url", ""),
            actor=counselor,
        )
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    return _back(student)


@login_required
@require_POST
def acknowledge(request: HttpRequest, student_id: UUID, notification_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    # Unacknowledged only: a repeat POST is a 404, never a second audit row.
    note = get_object_or_404(
        Notification, id=notification_id, recipient=student, acknowledged_at__isnull=True
    )
    acknowledge_notification(note)
    AuditEvent.objects.create(actor=counselor, event="notification.acknowledged", object_id=note.id)
    return _back(student)


@login_required
@require_POST
def message(request: HttpRequest, student_id: UUID) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    raw = request.POST.get("body", "")
    if rate_limited(
        "counselor-message", counselor.id, limit=_MESSAGE_LIMIT,
        window_seconds=_MESSAGE_WINDOW_SECONDS,
    ):
        return _board_page(
            request, student, status=429, error="Too many messages. Try again shortly.",
            form_values={"body": raw.strip()},
        )
    try:
        body = clean_message_body(raw)
    except MessageBodyError as refused:
        return _board_page(
            request, student, status=refused.status, error=str(refused),
            form_values={"body": raw.strip()},
        )
    sent = send_message(student=student, counselor=counselor, sender=counselor, body=body)
    AuditEvent.objects.create(actor=counselor, event="message.sent", object_id=sent.id)
    return _back(student)


@login_required
def gap_interview(request: HttpRequest, student_id: UUID) -> HttpResponse:
    """The student's open questions, answered by the counsellor (spec §4a).
    gap_intake.submit_answers records the counsellor as the actor. Paused, like
    every write, while the student is paused -- the page is a form."""
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    if request.method == "POST":
        try:
            submit_answers(request.POST, student=student, actor=counselor)
        except UnanswerableQuestion:
            return render_gap_page(
                request, student,
                error="The answers were not saved -- the questions below are current. "
                "Answer them again.",
            )
        return redirect("counselor-student-gap-interview", student_id=student.id)
    return render_gap_page(request, student)


@require_POST
def upload(request: HttpRequest, student_id: UUID) -> HttpResponse:
    """A presigned upload for the student's own document row, registered by the
    counsellor. JSON, like the student's door it mirrors (documents/api.py)."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication_required"}, status=401)
    counselor, student = _assigned(request, student_id)
    if paused_reason(student):
        code = "deletion_requested" if deletion_lock_target(student) else "processing_stopped"
        return JsonResponse({"error": code}, status=409)
    if rate_limited(
        "counselor-upload", counselor.id, limit=_UPLOAD_LIMIT, window_seconds=_UPLOAD_WINDOW_SECONDS
    ):
        return JsonResponse({"error": "rate_limited"}, status=429)
    try:
        body = json.loads(request.body or b"{}")
        kind = body.get("kind", "")
    except (ValueError, AttributeError):
        return JsonResponse({"error": "invalid_json"}, status=400)
    if kind not in UPLOAD_KIND_VALUES:
        return JsonResponse({"error": "invalid_kind"}, status=400)
    if kind == "TRANSCRIPT":
        # The student door's rules exactly: paid cycle, REPLACE lock, role/mode/slot/language.
        try:
            document = register_transcript(student, body)
        except TranscriptRegistrationRefused as refused:
            return JsonResponse({"error": refused.code}, status=refused.status)
    else:
        document = register(student.tenant_id, student.id, kind=kind)
    AuditEvent.objects.create(
        actor=counselor, event="document.upload_registered", object_id=document.id
    )
    presigned = presigned_upload(document)
    return JsonResponse(
        {"document_id": str(document.id), "url": presigned["url"], "fields": presigned["fields"]},
        status=201,
    )


def _handle_offer(
    request: HttpRequest, student_id: UUID, signal_id: UUID, *, accept: bool
) -> HttpResponse:
    counselor, student, paused = _for_write(request, student_id)
    if paused is not None:
        return paused
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    try:
        if accept:
            accept_offer(signal, actor=counselor)
        else:
            ignore_offer(signal, actor=counselor)
    except ApplicationRefused as refused:  # a double click: the other request handled it
        raise Http404 from refused
    return _back(student)


@login_required
@require_POST
def offer_accept(request: HttpRequest, student_id: UUID, signal_id: UUID) -> HttpResponse:
    return _handle_offer(request, student_id, signal_id, accept=True)


@login_required
@require_POST
def offer_ignore(request: HttpRequest, student_id: UUID, signal_id: UUID) -> HttpResponse:
    return _handle_offer(request, student_id, signal_id, accept=False)
