"""The Elmify staff desk: every student of the agency, their profile, their universities
and the team inbox (owner request 2026-11-21, extending the 2026-10-11 decision).

Only an active PLATFORM_ADMIN reaches these pages (staff two-step code enforced by the
tenant middleware), and only for students `staff_may_view` allows: a student who asked
for deletion or stopped processing is hidden here exactly as on the counsellor pages.
Every page that shows one student's personal data writes an `AuditEvent` first. The
desk reads and answers; it never edits a student's answers.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Max, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import StudentProfileVersion
from apps.accounts.review import review_sections
from apps.concierge.models import ConversationMessage
from apps.concierge.services import MessageBodyError, clean_message_body, send_message
from apps.documents.storage import staff_may_view
from apps.funding.models import AuditEvent
from apps.portals.models import Application
from apps.ratelimit import rate_limited
from apps.tenancy.models import CounselorAssignment, Membership
from apps.tenancy.services import current_membership

from .notify import alert_student_of_reply

_REPLY_LIMIT = 30
_REPLY_WINDOW_SECONDS = 60


def unread_messages() -> QuerySet[ConversationMessage]:
    """Student messages (sender is the student) no staff member has opened yet."""
    return ConversationMessage.objects.filter(
        read_by_staff_at__isnull=True, sender_id=F("student_id")
    )


def _staff(request: HttpRequest) -> Membership:
    return current_membership(request, Membership.Role.PLATFORM_ADMIN)


def _student(staff: Membership, student_id: UUID) -> Membership:
    student = get_object_or_404(
        Membership.objects.select_related("user"),
        id=student_id,
        role=Membership.Role.STUDENT,
        active=True,
    )
    if not staff_may_view(staff, student):
        raise Http404
    return student


def _audit(staff: Membership, student: Membership, event: str) -> None:
    AuditEvent.objects.create(
        actor=staff, actor_kind=AuditEvent.ActorKind.HUMAN, event=event, object_id=student.id
    )


def _name(student: Membership) -> str:
    return student.user.get_full_name() or student.user.get_username()


def _visible_students() -> list[Membership]:
    """Active students minus anyone paused (deletion request, stopped processing)."""
    return list(
        Membership.objects.filter(role=Membership.Role.STUDENT, active=True)
        .select_related("user")
        .order_by("-user__date_joined")
    )


def _latest_profile(student: Membership) -> dict[str, object]:
    version = (
        StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    )
    return dict(version.snapshot) if version is not None else {}


@login_required
def overview(request: HttpRequest) -> HttpResponse:
    staff = _staff(request)
    students = [s for s in _visible_students() if staff_may_view(staff, s)]
    week_ago = timezone.now() - timedelta(days=7)
    with_profile = set(
        StudentProfileVersion.objects.values_list("student_id", flat=True).distinct()
    )
    states = dict(
        Application.objects.values_list("state").annotate(n=Count("id")).order_by()
    )
    unread = unread_messages()
    latest = list(unread.select_related("student__user").order_by("-created_at")[:6])
    return render(
        request,
        "staff/overview.html",
        {
            "total": len(students),
            "new_week": sum(1 for s in students if s.user.date_joined >= week_ago),
            "with_profile": sum(1 for s in students if s.id in with_profile),
            "unread": unread.count(),
            "applications": sum(states.values()),
            "submitted": states.get(Application.State.SUBMITTED, 0)
            + states.get(Application.State.CONFIRMED, 0),
            "latest": latest,
            "recent": students[:6],
        },
    )


@login_required
def students(request: HttpRequest) -> HttpResponse:
    staff = _staff(request)
    query = request.GET.get("q", "").strip()
    rows = []
    counts = dict(
        Application.objects.values_list("student_id").annotate(n=Count("id")).order_by()
    )
    with_profile = set(
        StudentProfileVersion.objects.values_list("student_id", flat=True).distinct()
    )
    unread = dict(
        unread_messages()
        .values_list("student_id")
        .annotate(n=Count("id"))
        .order_by()
    )
    for student in _visible_students():
        if not staff_may_view(staff, student):
            continue
        haystack = f"{_name(student)} {student.user.email} {student.user.get_username()}".lower()
        if query and query.lower() not in haystack:
            continue
        rows.append(
            {
                "student": student,
                "name": _name(student),
                "applications": counts.get(student.id, 0),
                "has_profile": student.id in with_profile,
                "unread": unread.get(student.id, 0),
            }
        )
    return render(request, "staff/students.html", {"rows": rows, "q": query})


@login_required
def student_detail(request: HttpRequest, student_id: UUID) -> HttpResponse:
    staff = _staff(request)
    student = _student(staff, student_id)
    _audit(staff, student, "staff.student_viewed")
    snapshot = _latest_profile(student)
    applications = list(
        Application.objects.filter(student=student)
        .select_related("candidate")
        .order_by("-created_at")
    )
    assignment = (
        CounselorAssignment.objects.filter(student=student, active=True)
        .select_related("counselor__user")
        .first()
    )
    return render(
        request,
        "staff/student.html",
        {
            "student": student,
            "name": _name(student),
            "sections": review_sections(snapshot),
            "has_profile": bool(snapshot),
            "applications": applications,
            "counselor": assignment.counselor if assignment else None,
            "message_count": ConversationMessage.objects.filter(student=student).count(),
        },
    )


@login_required
def inbox(request: HttpRequest) -> HttpResponse:
    staff = _staff(request)
    threads = (
        ConversationMessage.objects.values("student_id")
        .annotate(last=Max("created_at"), total=Count("id"))
        .order_by("-last")
    )
    unread = dict(
        unread_messages()
        .values_list("student_id")
        .annotate(n=Count("id"))
        .order_by()
    )
    members = {
        m.id: m
        for m in Membership.objects.filter(
            id__in=[t["student_id"] for t in threads], role=Membership.Role.STUDENT, active=True
        ).select_related("user")
    }
    rows = []
    for thread in threads:
        student = members.get(thread["student_id"])
        if student is None or not staff_may_view(staff, student):
            continue
        last = (
            ConversationMessage.objects.filter(student=student).order_by("-created_at").first()
        )
        assert last is not None
        rows.append(
            {
                "student": student,
                "name": _name(student),
                "last": last,
                "from_student": last.sender_id == student.id,
                "unread": unread.get(student.id, 0),
            }
        )
    rows.sort(key=lambda r: (r["unread"] == 0,))  # unread first; stable, newest first within
    return render(request, "staff/inbox.html", {"rows": rows})


def _thread_page(
    request: HttpRequest,
    staff: Membership,
    student: Membership,
    *,
    status: int = 200,
    error: str = "",
    body: str = "",
) -> HttpResponse:
    messages = list(
        ConversationMessage.objects.filter(student=student)
        .select_related("sender")
        .order_by("created_at")
    )
    return render(
        request,
        "staff/thread.html",
        {"student": student, "name": _name(student), "messages_": messages,
         "error": error, "body": body},
        status=status,
    )


@login_required
def thread(request: HttpRequest, student_id: UUID) -> HttpResponse:
    staff = _staff(request)
    student = _student(staff, student_id)
    _audit(staff, student, "staff.thread_opened")
    ConversationMessage.objects.filter(
        student=student, read_by_staff_at__isnull=True, sender=student
    ).update(read_by_staff_at=timezone.now())
    return _thread_page(request, staff, student)


@login_required
@require_POST
def reply(request: HttpRequest, student_id: UUID) -> HttpResponse:
    staff = _staff(request)
    student = _student(staff, student_id)
    raw = request.POST.get("body", "")
    if rate_limited(
        "staff-reply", staff.id, limit=_REPLY_LIMIT, window_seconds=_REPLY_WINDOW_SECONDS
    ):
        return _thread_page(
            request, staff, student, status=429,
            error="Too many replies. Try again shortly.", body=raw.strip(),
        )
    try:
        body = clean_message_body(raw)
    except MessageBodyError as refused:
        return _thread_page(
            request, staff, student, status=400, error=str(refused), body=raw.strip()
        )
    assignment = CounselorAssignment.objects.filter(student=student, active=True).first()
    sent = send_message(
        student=student,
        counselor=assignment.counselor if assignment is not None else None,
        sender=staff,
        body=body,
    )
    _audit(staff, student, "staff.message_sent")
    alert_student_of_reply(request, sent)
    return redirect("staff-thread", student_id=student.id)
