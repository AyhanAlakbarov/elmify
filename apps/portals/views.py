"""The kit page, and the student's application actions (dashboard spec §7).

Session-authenticated, not part of the extension's HTTP API. The kit is the
layer that works with no extension and on any device. The actions resolve every
client-supplied id to the signed-in student's own rows (``_own_application``,
``offer_for``, ``add_application``'s candidate filter); the tenancy middleware
has already turned away a deletion-locked or processing-stopped student.

The id-addressed refusal is 404, never 403: a 403 there would confirm the
application exists. A caller with no active STUDENT membership in this tenant
never reaches that check -- current_membership raises PermissionDenied first,
which Django renders as a plain 403. That refusal is object-independent (it
fires the same way for any application_id, real or invented), so it leaks
nothing about a particular application, and it is the same shape
apps/documents/api.py's _student_endpoint uses for "not a student here".
"""

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .applications import (
    REFUSALS,
    ApplicationRefused,
    accept_offer,
    add_application,
    ignore_offer,
    is_startable,
    offer_for,
    remove_application,
    start_application,
)
from .models import Application, ExtensionPairing
from .outcome import correct_outcome
from .packets import build_kit
from .pairing import active_pairings, issue_pairing_code, revoke_pairing

_NOT_FILLABLE = {
    "no_portal": (
        "This programme's application portal is not known yet; your counsellor is "
        "finding it. Apply with this kit by hand meanwhile."
    ),
    "automation_prohibited": (
        "This portal does not allow filling tools. Apply with this kit by hand."
    ),
    "no_field_map": (
        "The extension has not seen this portal's form yet. It learns it the first "
        "time you start; this kit lists every answer we hold."
    ),
}


@login_required
@require_GET
def application_kit(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(Application, id=application_id, student=student)
    kit = build_kit(application)
    return render(
        request,
        "portals/kit.html",
        {
            "kit": kit,
            "not_fillable_text": _NOT_FILLABLE.get(kit.not_fillable_reason, ""),
            "start_url": (
                reverse("student-application-start", args=[application.id])
                if kit.not_fillable_reason in ("", "no_field_map") and is_startable(application)
                else ""
            ),
        },
    )


@require_POST
def pairing_code(request: HttpRequest) -> HttpResponse:
    """The dashboard hands its own session a one-time pairing code.

    Session-authenticated and POST-only: it mints a credential, so a GET that
    any page could make the browser issue is not available. This is the one
    route in the pairing flow that is NOT an extension route -- the extension
    has no token yet, which is the whole point of it.

    Not @login_required, which answers 302 to a login page. A JSON client
    cannot act on a redirect, so this refuses the way documents/api.py does.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "authentication_required"}, status=401)
    try:
        student = current_membership(request, Membership.Role.STUDENT)
    except PermissionDenied:
        return JsonResponse({"error": "student_membership_required"}, status=403)
    return JsonResponse({"code": issue_pairing_code(student)}, status=201)


def _own_application(request: HttpRequest, application_id: UUID) -> tuple[Membership, Application]:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("portal_form", "candidate"),
        id=application_id,
        student=student,
    )
    return student, application


@login_required
@require_POST
def application_add(request: HttpRequest, candidate_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    try:
        add_application(student=student, candidate_id=candidate_id, actor=student)
    except ApplicationRefused as refused:
        if refused.reason == "not_found":
            raise Http404 from refused
        messages.error(request, REFUSALS[refused.reason])
        return redirect("student-recommendation")
    messages.success(request, "Added to your applications.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def application_start(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student, application = _own_application(request, application_id)
    try:
        start_application(application, actor=student)
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    else:
        messages.success(request, f"Your browser extension is opening {application.where}.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def application_outcome(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student, application = _own_application(request, application_id)
    try:
        correct_outcome(application, request.POST.get("outcome", ""), actor=student)
    except ValueError:
        messages.error(request, "Choose an outcome from the list.")
    else:
        messages.success(request, "Saved.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def application_remove(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student, application = _own_application(request, application_id)
    try:
        remove_application(application, actor=student)
    except ApplicationRefused as refused:
        messages.error(request, REFUSALS[refused.reason])
    else:
        messages.success(request, "Removed from your applications.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def offer_accept(request: HttpRequest, signal_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    try:
        application = accept_offer(signal, actor=student)
    except ApplicationRefused as refused:  # a double click: the other request handled it
        raise Http404 from refused
    messages.success(request, f"{application.title} is on your board.")
    return redirect("concierge-student-dashboard")


@login_required
@require_POST
def offer_ignore(request: HttpRequest, signal_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    signal = offer_for(student, signal_id)
    if signal is None:
        raise Http404
    try:
        ignore_offer(signal, actor=student)
    except ApplicationRefused as refused:
        raise Http404 from refused
    return redirect("concierge-student-dashboard")


@login_required
def extension_settings(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    pairings = active_pairings(student).order_by("-last_seen_at")
    return render(request, "student/settings_extension.html", {"pairings": pairings})


@login_required
@require_POST
def extension_disconnect(request: HttpRequest, pairing_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    pairing = get_object_or_404(
        ExtensionPairing, id=pairing_id, membership=student, revoked_at__isnull=True
    )
    revoke_pairing(pairing)
    messages.success(request, "That browser is disconnected.")
    return redirect("student-settings-extension")
