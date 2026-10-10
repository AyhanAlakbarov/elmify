"""The student's own erasure flow. Three views, all gated on their own membership.

apps/audit/console.py holds the lifecycle; these are the trust boundary around
it -- they check the role, check that the request belongs to the caller, and
cap the rate.
"""

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.ratelimit import rate_limited
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .console import (
    applications_in_flight,
    cancel_deletion,
    deny_deletion,
    release_deletion,
    request_deletion,
)
from .models import DeletionRequest

#: Requesting an erasure writes a row, an audit event, and starts an
#: irreversible thirty-day clock. Five an hour is generous for a decision
#: nobody makes twice.
_REQUEST_RATE_LIMIT = 5
_REQUEST_RATE_WINDOW_SECONDS = 3600

#: Every state except CANCELLED and EXECUTED. DENIED is open: the agency
#: refused the erasure so nothing was erased, but the student asked to leave
#: and their access stays closed until they restore it themselves. EXECUTED
#: needs no entry -- advance_deletion has set Membership.active = False, so
#: middleware.py finds no membership and never reaches the lock.
OPEN_DELETION_STATES = ("REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED")


@login_required
@require_POST
def request_account_deletion(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    if rate_limited(
        "account-deletion",
        student.id,
        limit=_REQUEST_RATE_LIMIT,
        window_seconds=_REQUEST_RATE_WINDOW_SECONDS,
    ):
        return HttpResponse("Too many requests. Try again shortly.", status=429)

    reason = request.POST.get("reason", "")
    # The view is the trust boundary. DeletionRequest carries a CheckConstraint
    # on this column, so an unvalidated value would reach the database and come
    # back as a 500 -- and choices= alone validates nothing, since .create()
    # never calls full_clean().
    if reason not in DeletionRequest.Reason.values:
        return HttpResponseBadRequest("Choose a reason from the list.")

    # The savepoint matters: HostTenantContextMiddleware wraps every request in
    # transaction.atomic(), so an IntegrityError caught without one leaves the
    # transaction poisoned and the redirect below fails with
    # TransactionManagementError. A double-click is not an error to show the
    # student -- the pending screen is where both POSTs were going anyway.
    try:
        with transaction.atomic():
            request_deletion(student=student, reason=reason)
    except IntegrityError:
        pass
    return redirect("audit-deletion-pending")


@login_required
def deletion_pending(request: HttpRequest) -> HttpResponse:
    """The one screen a student with an open request can reach."""
    student = current_membership(request, Membership.Role.STUDENT)
    record = get_object_or_404(
        DeletionRequest, student=student, state__in=OPEN_DELETION_STATES
    )
    return render(
        request,
        "audit/deletion_pending.html",
        {"request_record": record, "in_flight": applications_in_flight(student)},
    )


@login_required
@require_POST
def restore_account(request: HttpRequest, request_id: str) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    # student=student is the ownership check, and it is the whole security of
    # this endpoint: without it one student could cancel another's erasure.
    # Not destructive, but it silently keeps alive data somebody asked to have
    # deleted.
    record = get_object_or_404(DeletionRequest, id=request_id, student=student)
    cancel_deletion(request=record, student=student)
    return redirect("concierge-student-dashboard")


@login_required
def deletion_console(request: HttpRequest) -> HttpResponse:
    """The owner's three lists. The only exit from RETENTION_REVIEW.

    There is no agency work queue in this codebase and no email anywhere in it,
    so this screen is both the queue and the notification: without it a held
    request is seen by nobody while the student has been told their records are
    being kept, and an agency learns a student is leaving only by looking.
    """
    current_membership(request, Membership.Role.OWNER)
    return render(
        request,
        "audit/deletion_console.html",
        {
            "held": DeletionRequest.objects.filter(state="RETENTION_REVIEW").select_related(
                "student"
            ),
            "counting_down": DeletionRequest.objects.filter(state="APPROVED").order_by(
                "execute_after"
            ),
            # .values() rather than model rows, deliberately. A retained
            # identity is by definition unscrubbed, so a Membership in the
            # template can reach display_name -> auth.User and put an erased
            # person's real name back on the screen of the agency that erased
            # them. The reason is what the agency has to act on; two of the
            # three cases are misconfigurations to fix rather than people to
            # look up, and the audit trail carries the identity for anyone with
            # a lawful need for it.
            "partially_erased": DeletionRequest.objects.filter(
                state="EXECUTED", identity_retained=True
            ).values("id", "student_id", "identity_retained_reason", "created_at"),
        },
    )


@login_required
@require_POST
def release_deletion_request(request: HttpRequest, request_id: str) -> HttpResponse:
    owner = current_membership(request, Membership.Role.OWNER)
    # The manager is tenant-scoped, so this 404s on another agency's request
    # rather than acting on it. state= pins the action to a held request: an
    # APPROVED one is already counting down and advance_deletion would refuse
    # it with a 500 rather than a 404.
    record = get_object_or_404(DeletionRequest, id=request_id, state="RETENTION_REVIEW")
    release_deletion(request=record, owner=owner)
    return redirect("audit-deletion-console")


@login_required
@require_POST
def deny_deletion_request(request: HttpRequest, request_id: str) -> HttpResponse:
    owner = current_membership(request, Membership.Role.OWNER)
    record = get_object_or_404(DeletionRequest, id=request_id, state="RETENTION_REVIEW")
    deny_deletion(request=record, owner=owner)
    return redirect("audit-deletion-console")


@login_required
def account_settings(request: HttpRequest) -> HttpResponse:
    """The deletion request form. An open request never reaches this: the
    deletion lock sends the student to the waiting page first."""
    current_membership(request, Membership.Role.STUDENT)
    return render(
        request, "student/settings_account.html", {"reasons": DeletionRequest.Reason.choices}
    )
