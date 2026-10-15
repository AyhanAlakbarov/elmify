from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import StudentProfileVersion
from apps.dashboard.board import board_for
from apps.dashboard.locks import paused_reason
from apps.dashboard.mylist import country_groups, missing_links, option_page
from apps.dashboard.needs import items_for
from apps.dashboard.overview import build_overview
from apps.funding.models import AuditEvent
from apps.mailbox.models import MAX_CLASSIFY_ATTEMPTS, MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.ratelimit import rate_limited
from apps.tenancy.models import CounselorAssignment, Membership, SupportGrant
from apps.tenancy.services import current_membership, require_active_support_grant

from .models import ConversationMessage, Notification, RoadmapItem
from .services import (
    MessageBodyError,
    acknowledge_notification,
    clean_message_body,
    record_manual_operation,
    send_message,
)

#: Student-writable free text reaching a counselor's inbox: cap the rate and
#: the size (services.clean_message_body); same treatment as the pack
#: commands in apps.funding.views.
_MESSAGE_RATE_LIMIT = 20
_MESSAGE_RATE_WINDOW_SECONDS = 60


def _counselor_dashboard_page(
    request: HttpRequest,
    counselor: Membership,
    *,
    status: int = 200,
    error: str | None = None,
    error_form: str | None = None,
) -> HttpResponse:
    assignments = CounselorAssignment.objects.filter(
        counselor=counselor, active=True
    ).select_related("student__user")
    student_ids = [assignment.student_id for assignment in assignments]
    items = RoadmapItem.objects.filter(student_id__in=student_ids).select_related("student__user")
    return render(
        request,
        "counselor/dashboard.html",
        # error_form carries the failing roadmap item's id so the alert
        # renders inside that item's form, not at the top of the page.
        {"assignments": assignments, "items": items, "error": error, "error_form": error_form},
        status=status,
    )


@login_required
def counselor_dashboard(request: HttpRequest) -> HttpResponse:
    counselor = current_membership(request, Membership.Role.COUNSELOR)
    return _counselor_dashboard_page(request, counselor)


@login_required
@require_POST
def mark_roadmap_item_done(request: HttpRequest, item_id: str) -> HttpResponse:
    counselor = current_membership(request, Membership.Role.COUNSELOR)
    item = get_object_or_404(
        RoadmapItem.objects.select_related("student"), id=item_id, owner=counselor
    )
    paused = paused_reason(item.student)
    if paused is not None:
        return _counselor_dashboard_page(request, counselor, status=409, error=paused)
    try:
        record_manual_operation(item, counselor, request.POST.get("description", ""))
    except ValueError as error:
        # Same 403 contract as before, but the counselor gets the dashboard
        # back with an inline alert instead of a bare text page
        # (design-lint-baseline defect 5). The dashboard lists items by active
        # assignment while this action is owner-scoped, so the failing item is
        # not always on the page — error_form pins the alert to the item only
        # when it renders there; otherwise it falls back to the page level.
        item_is_listed = CounselorAssignment.objects.filter(
            counselor=counselor, student_id=item.student_id, active=True
        ).exists()
        return _counselor_dashboard_page(
            request,
            counselor,
            status=403,
            error=str(error),
            error_form=str(item.id) if item_is_listed else None,
        )
    return redirect("concierge-counselor-dashboard")


@login_required
def owner_dashboard(request: HttpRequest) -> HttpResponse:
    current_membership(request, Membership.Role.OWNER)
    from apps.leads.models import DemoRequest

    items = RoadmapItem.objects.select_related("student__user", "owner__user").all()
    demo_requests = DemoRequest.objects.all()[:50]
    counselors = list(
        Membership.objects.filter(role=Membership.Role.COUNSELOR, active=True)
        .select_related("user")
        .order_by("user__username")
    )
    assigned = dict(
        CounselorAssignment.objects.filter(active=True).values_list("student_id", "counselor_id")
    )
    students = [
        (student, assigned.get(student.id))
        for student in Membership.objects.filter(role=Membership.Role.STUDENT, active=True)
        .select_related("user")
        .order_by("-user__date_joined")[:200]
    ]
    return render(
        request,
        "owner/dashboard.html",
        {
            "items": items,
            "demo_requests": demo_requests,
            "students": students,
            "counselors": counselors,
        },
    )


@login_required
@require_POST
def owner_assign_counselor(request: HttpRequest, student_id: UUID) -> HttpResponse:
    """Give a student a counsellor, or take theirs away (empty choice).

    One active assignment per student (the table's own constraint), so the old
    one is closed first. Recorded as an AuditEvent: who a student's counsellor
    is decides who reads their documents and messages.
    """
    owner = current_membership(request, Membership.Role.OWNER)
    student = get_object_or_404(
        Membership, id=student_id, role=Membership.Role.STUDENT, active=True
    )
    choice = request.POST.get("counselor", "")
    counselor = None
    if choice:
        try:
            counselor = Membership.objects.get(
                id=UUID(choice), role=Membership.Role.COUNSELOR, active=True
            )
        except (ValueError, Membership.DoesNotExist):
            messages.error(request, "Choose one of your counsellors.")
            return redirect("concierge-owner-dashboard")
    CounselorAssignment.objects.filter(student=student, active=True).update(active=False)
    if counselor is not None:
        CounselorAssignment.objects.create(counselor=counselor, student=student)
    AuditEvent.objects.create(
        actor=owner,
        actor_kind=AuditEvent.ActorKind.HUMAN,
        event="counselor_assignment.changed",
        object_id=student.id,
    )
    who = student.user.get_full_name() or student.user.get_username()
    if counselor is None:
        messages.success(request, f"{who} no longer has a counsellor.")
    else:
        name = counselor.user.get_full_name() or counselor.user.get_username()
        messages.success(request, f"{who} is now with {name}.")
    return redirect("concierge-owner-dashboard")


def _student_dashboard_page(request: HttpRequest, student: Membership) -> HttpResponse:
    board = board_for(student)
    needs = items_for(student, board=board)
    return render(
        request,
        "student/dashboard.html",
        {"needs": needs, "overview": build_overview(student, board, needs)},
    )


@login_required
def student_dashboard(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return _student_dashboard_page(request, student)


@login_required
def student_applications(request: HttpRequest) -> HttpResponse:
    """My list: grouped by country (default) or by stage (the board).

    The home page keeps only the milestones and what needs doing next."""
    student = current_membership(request, Membership.Role.STUDENT)
    board = board_for(student)
    by_stage = request.GET.get("view") == "stage"
    return render(
        request,
        "student/applications.html",
        {
            "board": board,
            "by_stage": by_stage,
            "groups": () if by_stage else country_groups(student.id, board),
            "outcome_choices": Application.Outcome.choices,
        },
    )


@login_required
def student_option(request: HttpRequest, application_id: UUID) -> HttpResponse:
    """One option on the list: everything about it, why the student fits, and
    where their application stands. Tenant copies only (dashboard.mylist)."""
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("candidate__evidence"),
        id=application_id,
        student=student,
    )
    if application.candidate is None:
        raise Http404
    card = next(
        (c for c in board_for(student).cards if c.application_id == application.id), None
    )
    if card is None:
        raise Http404
    return render(
        request,
        "student/option.html",
        {
            "card": card,
            "page": option_page(application.candidate),
            "missing": missing_links(card),
            "outcome_choices": Application.Outcome.choices,
        },
    )


@login_required
@require_POST
def acknowledge_notification_view(request: HttpRequest, notification_id: str) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    notification = get_object_or_404(Notification, id=notification_id, recipient=student)
    acknowledge_notification(notification)
    return redirect("concierge-student-dashboard")


@dataclass(frozen=True)
class MailRow:
    """One recognised mail and what an unlabelled one means: "" (labelled),
    "failed" (classification gave up), "metadata" (that tier reads nothing),
    "pending" (still being read)."""

    signal: MailSignal
    reading: Literal["", "failed", "metadata", "pending"]


def _reading(signal: MailSignal) -> Literal["", "failed", "metadata", "pending"]:
    if signal.label:
        return ""
    if signal.classify_attempts >= MAX_CLASSIFY_ATTEMPTS:
        return "failed"
    if signal.connection.tier == "METADATA":
        return "metadata"
    return "pending"


def messages_context(student: Membership) -> dict[str, object]:
    """Recognised mail per application, and the counsellor conversation.

    Keys: ``mail_groups`` (list of (title, list[MailRow]), one group per
    application id, unlinked mail last in its own group), ``conversation``,
    ``has_counselor``, ``has_mailbox`` (an active mailbox connection exists) and
    ``outcome_labels``. Reads only this student's rows; exposes no
    student-only action, so the counsellor's view can reuse it.
    """
    groups: dict[object, tuple[str, list[MailRow]]] = {}
    for signal in (
        MailSignal.objects.filter(connection__membership=student)
        .select_related("connection", "application__candidate", "application__portal_form")
        .order_by("-received_at")
    ):
        application = signal.application
        key = application.id if application is not None else None
        title = application.title if application is not None else "Not about one application"
        groups.setdefault(key, (title, []))[1].append(MailRow(signal, _reading(signal)))
    return {
        "mail_groups": list(groups.values()),
        "conversation": ConversationMessage.objects.filter(student=student).order_by("created_at"),
        "has_counselor": CounselorAssignment.objects.filter(student=student, active=True).exists(),
        "has_mailbox": MailboxConnection.objects.filter(
            membership=student, status=MailboxConnection.Status.ACTIVE
        ).exists(),
        "outcome_labels": dict(Application.Outcome.choices),
    }


def _messages_page(
    request: HttpRequest,
    student: Membership,
    *,
    status: int = 200,
    error: str | None = None,
    form_values: dict[str, str] | None = None,
) -> HttpResponse:
    context = messages_context(student)
    context.update(
        {
            "error": error,
            "error_form": "message" if error else None,
            "form_values": form_values or {},
        }
    )
    return render(request, "student/messages.html", context, status=status)


@login_required
def messages_page(request: HttpRequest) -> HttpResponse:
    return _messages_page(request, current_membership(request, Membership.Role.STUDENT))


@login_required
@require_POST
def send_student_message(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    raw = request.POST.get("body", "")
    # The composer lives on the Messages page only, so errors re-render there.

    def _message_error(message: str, *, status: int) -> HttpResponse:
        # Same inline-error contract as the counselor dashboard (design-lint
        # baseline defect 5, student side): keep the status code, re-render
        # the page with the alert, and preserve the typed message.
        return _messages_page(
            request, student, status=status, error=message, form_values={"body": raw.strip()}
        )

    if rate_limited(
        "student-message",
        student.id,
        limit=_MESSAGE_RATE_LIMIT,
        window_seconds=_MESSAGE_RATE_WINDOW_SECONDS,
    ):
        return _message_error("Too many messages. Try again shortly.", status=429)
    assignment = get_object_or_404(CounselorAssignment, student=student, active=True)
    try:
        body = clean_message_body(raw)
    except MessageBodyError as error:
        return _message_error(str(error), status=error.status)
    send_message(student=student, counselor=assignment.counselor, sender=student, body=body)
    return redirect("student-messages")


@login_required
def admin_support_grant(request: HttpRequest) -> HttpResponse:
    tenant = request.tenant  # type: ignore[attr-defined]
    assert request.user.pk is not None
    try:
        active_grant = require_active_support_grant(request.user, tenant.id)
    except SupportGrant.DoesNotExist:
        # The page needs an active grant to render, so there is nothing to
        # re-render with an inline error -- templates/403.html carries it.
        raise PermissionDenied("an active support grant is required") from None
    grants = SupportGrant.objects.filter(tenant_id=tenant.id).order_by("-starts_at")
    return render(
        request, "admin/support_grant.html", {"active_grant": active_grant, "grants": grants}
    )


@login_required
def settings_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    profile_done = StudentProfileVersion.objects.filter(student=student).exists()
    return render(request, "student/settings.html", {"profile_done": profile_done})
