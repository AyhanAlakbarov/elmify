"""The extension pairing code and the student's application actions (dashboard spec §7).

Session-authenticated, not part of the extension's HTTP API. The kit page is
not here: it is the assigned counsellor's read-only debugging view
(``apps/dashboard/views.py::application_answers``) and a student is not shown
it. The actions resolve every
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

import logging
from uuid import UUID

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.dashboard.board import overrun_for
from apps.documents.storage import _requesting_membership, admit, read_prepared
from apps.funding.models import AuditEvent
from apps.ratelimit import pack_command_rate_limited, rate_limited
from apps.tenancy.middleware import require_staff_mfa
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from . import credentials
from .applications import (
    REFUSALS,
    ApplicationRefused,
    accept_offer,
    add_application,
    ignore_offer,
    offer_for,
    own_candidate,
    remove_application,
    start_application,
)
from .bench import is_bench_operator
from .fees import mark_fee_paid
from .http import inert_response, inline_response
from .models import Application, ExtensionPairing, PortalAccount, PreparedDocument
from .outcome import correct_outcome
from .pairing import active_pairings, fresh_login, issue_pairing_code, revoke_pairing
from .prepare import current_prepared


@login_required
@require_GET
def prepared_download(request: HttpRequest, prepared_id: UUID, filename: str) -> HttpResponse:
    """A prepared file, to its own student only while the row is current and READY.
    Every refusal is a 404, as `download_document` does."""
    try:
        student = current_membership(request, Membership.Role.STUDENT)
    except PermissionDenied as error:
        raise Http404 from error
    row = _current_ready(prepared_id)
    if row.student_id != student.id or row.filename != filename:
        raise Http404
    return inert_response(_prepared_body(row), row.content_type, row.filename)


def _current_ready(prepared_id: UUID) -> PreparedDocument:
    """A READY prepared file that is still its application's current one; Http404 otherwise."""
    row = (
        PreparedDocument.objects.select_related("application", "student")
        .filter(id=prepared_id, state=PreparedDocument.State.READY)
        .first()
    )
    if row is None:
        raise Http404
    current = current_prepared(row.application).get(row.slot)
    if current is None or current.id != row.id:
        raise Http404
    return row


def _prepared_body(row: PreparedDocument) -> bytes:
    try:
        return read_prepared(row.object_key)
    except KeyError as error:
        raise Http404 from error


@login_required
@require_GET
def prepared_view(request: HttpRequest, prepared_id: UUID) -> HttpResponse:
    """A prepared file shown inline to Elmify staff or the counsellor assigned to its student;
    never to the student (who has the download route). Every refusal is a 404, and a staff
    view is recorded before the file is read (`admit`)."""
    row = _current_ready(prepared_id)
    admit(
        _requesting_membership(request), row.student, kind=f"PREPARED_{row.document}",
        document_id=row.id,
    )
    return inline_response(_prepared_body(row), row.content_type)


@login_required
@require_GET
def staff_prepared_download(request: HttpRequest, prepared_id: UUID) -> HttpResponse:
    """The same prepared file as a download, for Elmify staff only, recorded first."""
    row = _current_ready(prepared_id)
    admit(
        _requesting_membership(request), row.student, kind=f"PREPARED_{row.document}",
        document_id=row.id, download=True,
    )
    return inert_response(_prepared_body(row), row.content_type, row.filename)

logger = logging.getLogger(__name__)


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
        member = current_membership(request, Membership.Role.STUDENT)
    except PermissionDenied:
        # The bench (plan 6): a platform operator pairs from the platform host.
        # TenantMembershipMiddleware already held this session to
        # require_staff_mfa; it is checked again here, as research/views.py's
        # _operator does, so the door does not rest on the middleware's choice
        # of membership. is_bench_operator checks the platform and the role.
        try:
            member = current_membership(request, Membership.Role.PLATFORM_ADMIN)
            require_staff_mfa(request.user, member.role)
        except PermissionDenied:
            return JsonResponse({"error": "student_membership_required"}, status=403)
        if not is_bench_operator(member):
            return JsonResponse({"error": "student_membership_required"}, status=403)
    # Onboarding pairs right after login, and that login is the proof portal
    # passwords need; any later pairing is confirmed once on Portal logins.
    code = issue_pairing_code(member, passwords_allowed=fresh_login(request))
    return JsonResponse({"code": code}, status=201)


def _own_application(request: HttpRequest, application_id: UUID) -> tuple[Membership, Application]:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("portal_form", "candidate"),
        id=application_id,
        student=student,
    )
    return student, application


_OVER_BUDGET_PAGE = "student/over_budget.html"


@login_required
@require_POST
def application_add(request: HttpRequest, candidate_id: UUID) -> HttpResponse:
    """Add to my applications. A programme that doesn't fit the free budget
    renders the over-budget page first, and only its ticked box (``confirm=1``)
    adds it (owner 2026-10-14): enforced here, not by the template."""
    student = current_membership(request, Membership.Role.STUDENT)
    # Before the board is built: an unconfirmed POST costs a board read too.
    # ponytail: a confirmed add is counted twice (here and in add_application).
    if pack_command_rate_limited(student.id):
        messages.error(request, REFUSALS["rate_limited"])
        return redirect("student-recommendation")
    candidate = own_candidate(student, candidate_id)
    already = (
        candidate is not None
        and Application.objects.filter(student=student, candidate=candidate).exists()
    )
    overrun = overrun_for(student, candidate) if candidate is not None else None
    if overrun is not None and request.POST.get("confirm") != "1":
        return render(request, _OVER_BUDGET_PAGE, {
            "overrun": overrun,
            "action": reverse("student-application-add", args=[candidate_id]),
            "hidden": {},
            "refused": request.POST.get("seen") == "1",
        })
    try:
        card = add_application(student=student, candidate_id=candidate_id, actor=student)
    except ApplicationRefused as refused:
        if refused.reason == "not_found":
            raise Http404 from refused
        messages.error(request, REFUSALS[refused.reason])
        return redirect("student-recommendation")
    if already:
        messages.info(request, "This is already in your applications.")
        return redirect("concierge-student-dashboard")
    if overrun is not None:
        AuditEvent.objects.create(
            actor=student, event="application.added_over_budget", object_id=card.id
        )
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
    funding_outcome = (
        request.POST.get("funding_outcome", "") if "funding_outcome" in request.POST else None
    )
    try:
        correct_outcome(
            application,
            request.POST.get("outcome", ""),
            actor=student,
            funding_outcome=funding_outcome,
        )
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


#: Revealing a portal password re-checks the student's own Elmify password; five
#: tries in fifteen minutes is a person mistyping, more is guessing.
_REVEAL_LIMIT = 5
_REVEAL_WINDOW_SECONDS = 900


def _own_account(request: HttpRequest, account_id: UUID) -> tuple[Membership, PortalAccount]:
    student = current_membership(request, Membership.Role.STUDENT)
    return student, get_object_or_404(PortalAccount, id=account_id, student=student)


def _portals_page(
    request: HttpRequest, student: Membership, *, shown: UUID | None = None,
    password: str = "", error: str = "", status: int = 200,
) -> HttpResponse:
    accounts = (
        PortalAccount.objects.filter(student=student).exclude(address="").order_by("portal_host")
    )
    browsers = _unconfirmed_browsers(student).order_by("redeemed_at")
    response = render(
        request,
        "student/settings_portals.html",
        {
            "accounts": accounts, "browsers": browsers, "shown": shown, "password": password,
            "error": error,
        },
        status=status,
    )
    # A revealed password must not sit in a shared cache or the back button's.
    response["Cache-Control"] = "no-store"
    return response


def _unconfirmed_browsers(student: Membership) -> QuerySet[ExtensionPairing]:
    return ExtensionPairing.objects.filter(
        membership=student,
        redeemed_at__isnull=False,
        revoked_at__isnull=True,
        passwords_allowed_at__isnull=True,
    )


@login_required
@require_POST
def portal_browser_allow(request: HttpRequest, pairing_id: UUID) -> HttpResponse:
    """Let a browser paired from an old session receive portal passwords, once
    the student proves it is them -- the same proof the reveal asks for, from
    the same rate-limit bucket, so the two cannot be used to guess in turn."""
    student = current_membership(request, Membership.Role.STUDENT)
    browser = get_object_or_404(_unconfirmed_browsers(student), id=pairing_id)
    if rate_limited(
        "portal-reveal", student.user_id, limit=_REVEAL_LIMIT, window_seconds=_REVEAL_WINDOW_SECONDS
    ):
        return _portals_page(
            request, student, error="Too many tries. Wait a few minutes.", status=429
        )
    if not request.user.check_password(request.POST.get("password", "")):
        return _portals_page(request, student, error="That is not your Elmify password.")
    ExtensionPairing.objects.filter(pk=browser.pk).update(passwords_allowed_at=timezone.now())
    AuditEvent.objects.create(
        tenant_id=browser.tenant_id, actor=student, actor_kind=AuditEvent.ActorKind.HUMAN,
        event="portal.browser_allowed", object_id=browser.id,
    )
    messages.success(request, "This browser can now log in to portals for you.")
    return redirect("student-settings-portals")


def _log_secrets_failure(action: str, host: str, error: ClientError) -> None:
    # Code and host only: the exception's message names the secret, which names the student.
    logger.warning(
        "portal secret %s failed (%s) for %s",
        action,
        credentials.aws_code(error),
        host,
    )


@login_required
@require_GET
def portal_logins(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return _portals_page(request, student)


@login_required
@require_POST
def portal_reveal(request: HttpRequest, account_id: UUID) -> HttpResponse:
    """The password, once, after the student proves it is them (spec §6)."""
    student, account = _own_account(request, account_id)
    if rate_limited(
        "portal-reveal", student.user_id, limit=_REVEAL_LIMIT, window_seconds=_REVEAL_WINDOW_SECONDS
    ):
        return _portals_page(
            request, student, error="Too many tries. Wait a few minutes.", status=429
        )
    if not request.user.check_password(request.POST.get("password", "")):
        return _portals_page(request, student, error="That is not your Elmify password.")
    if account.password_held_at is None or account.student_managed_at is not None:
        return _portals_page(request, student, error="We do not hold a password for this portal.")
    try:
        password = credentials.password_for(
            tenant_id=account.tenant_id, student_id=student.id, portal_host=account.portal_host
        )
    except ClientError as error:
        _log_secrets_failure("read", account.portal_host, error)
        return _portals_page(
            request, student, error="We could not read it just now. Try again.", status=503
        )
    if password is None:
        # Confirmed gone: the marker was a lie (as ext_api.portal_login does).
        PortalAccount.objects.filter(pk=account.pk).update(password_held_at=None)
        return _portals_page(request, student, error="We do not hold a password for this portal.")
    AuditEvent.objects.create(
        tenant_id=account.tenant_id, actor=student, actor_kind=AuditEvent.ActorKind.HUMAN,
        event="portal.password_revealed", object_id=account.id,
    )
    return _portals_page(request, student, shown=account.id, password=password)


@login_required
@require_POST
def portal_takeover(request: HttpRequest, account_id: UUID) -> HttpResponse:
    """"I changed my password": our copy is deleted first, then the account is
    marked, so a failed delete never reads as handed over."""
    student, account = _own_account(request, account_id)
    try:
        deleted = credentials.delete_password(
            tenant_id=account.tenant_id, student_id=student.id, portal_host=account.portal_host
        )
    except ClientError as error:
        _log_secrets_failure("delete", account.portal_host, error)
        return _portals_page(
            request, student, error="We could not remove it just now. Try again.", status=503
        )
    # Handed over once: a second press, or a press on an account we never
    # held a password for, marks nothing -- marking the latter would block the
    # co-pilot's sign-up there over a password that never existed.
    if not deleted and account.password_held_at is None:
        messages.info(request, f"We do not keep a password for {account.portal_host}.")
        return redirect("student-settings-portals")
    handed = PortalAccount.objects.filter(pk=account.pk, student_managed_at__isnull=True).update(
        student_managed_at=timezone.now()
    )
    if handed == 1:
        AuditEvent.objects.create(
            tenant_id=account.tenant_id, actor=student, actor_kind=AuditEvent.ActorKind.HUMAN,
            event="portal.password_handed_over", object_id=account.id,
        )
    messages.success(request, f"We no longer log in to {account.portal_host} for you.")
    return redirect("student-settings-portals")


@login_required
@require_POST
def application_fee_paid(request: HttpRequest, application_id: UUID) -> HttpResponse:
    """"I've paid this fee" (lanes spec §7.4). Only the student: there is no
    counsellor route, because spending is the student's own record."""
    student, application = _own_application(request, application_id)
    if pack_command_rate_limited(student.id):
        messages.error(request, REFUSALS["rate_limited"])
    elif mark_fee_paid(
        application, source=Application.FeePaidSource.STUDENT, at=timezone.now(), actor=student
    ):
        messages.success(request, f"Marked the application fee for {application.title} as paid.")
    else:
        messages.error(request, "This fee is already marked as paid, or has nothing to pay.")
    return redirect("concierge-student-dashboard")
