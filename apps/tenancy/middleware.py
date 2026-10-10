from collections.abc import Callable
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from .context import tenant_scope
from .db import set_local_tenant
from .models import Membership
from .services import TenantHostInvalid, resolve_verified_domain

_STAFF_MFA_ROLES = frozenset(
    {Membership.Role.OWNER, Membership.Role.COUNSELOR, Membership.Role.PLATFORM_ADMIN}
)

# The device-setup flow itself must stay reachable for an unverified staff
# user -- otherwise there is no way for them to ever pass the gate below.
_MFA_SETUP_PATH = "/mfa/setup/"

#: The paths a student with an open deletion request must still reach. Without
#: them the lock is a one-way door and the thirty-day reversal window is
#: decorative -- and without logout a locked student cannot leave a shared
#: machine. Same shape as _MFA_SETUP_PATH above.
_DELETION_EXEMPT_PREFIXES = (
    "/student/account/deletion/",
    "/student/account/restore/",
    "/accounts/logout/",
)

#: Reachable while a student must re-accept or has stopped processing: the pages
#: themselves, the documents they link to, the erasure entry point and deletion
#: pages (refusing new terms must not block erasure), and logout (a locked student
#: must be able to leave).
_ACCEPTANCE_EXEMPT_PREFIXES = (
    "/privacy/accept/",
    "/legal/",
    "/student/account/delete/",
    # Exempt as the erasure entry point. Only erasure may live under this
    # prefix: anything else added here is reachable by a locked student.
    "/student/settings/account/",
    "/api/auth/logout",
    "/accounts/logout/",
    "/privacy/stopped/",
    *_DELETION_EXEMPT_PREFIXES,
)

#: A vendor webhook posts to our platform host, never an agency's verified
#: domain -- there is no tenant to select for a payload that updates
#: `OfficialSourceSnapshot`, a table every tenant reads (see CLAUDE.md,
#: "Row-level security"). Checked before host resolution even runs, so an
#: unrelated host-validation failure can never masquerade as "off" for a
#: route whose own flag (`FETCH_WEBHOOKS_ENABLED`) already governs that.
_TENANT_HOST_EXEMPT_PATHS = ("/webhooks/firecrawl/",)


def deletion_lock_target(membership: Membership) -> str | None:
    """Where to send a student whose account is scheduled for deletion, or None.

    One .exists() per authenticated student request, on the
    (tenant, student, state) index added for it. Deliberately a query rather
    than a denormalised flag on Membership: a flag would be a second source of
    truth for DeletionRequest.state and drifts in both directions -- left set
    after a cancellation it locks a student out permanently, and cleared while
    the request is still APPROVED it lets someone be erased mid-session.

    # ponytail: add the flag only if this is ever measured to matter.
    """
    from apps.audit.models import DeletionRequest
    from apps.audit.views import OPEN_DELETION_STATES

    if membership.role != Membership.Role.STUDENT:
        return None
    if not DeletionRequest.objects.filter(
        student=membership, state__in=OPEN_DELETION_STATES
    ).exists():
        return None
    return reverse("audit-deletion-pending")


def require_staff_mfa(user: AbstractBaseUser, role: str) -> None:
    """Deny staff access without a verified OTP device.

    `user.is_verified()` is installed by django_otp.middleware.OTPMiddleware
    (must run before TenantMembershipMiddleware) and reflects whether the
    current session has a confirmed TOTP device attached. Plain students are
    untouched -- MFA is mandatory for staff only per Section 3.4.

    "Staff" is the membership role *or* Django's own is_staff/is_superuser
    flags: those reach /admin/ (auth user and group management, the most
    privileged surface here), and keying only off the membership role let a
    superuser whose membership happens to be STUDENT walk straight past this.
    """
    is_django_staff = bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    if (role in _STAFF_MFA_ROLES or is_django_staff) and not user.is_verified():  # type: ignore[attr-defined]
        raise PermissionDenied("multi-factor verification required")


class HostTenantContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path in _TENANT_HOST_EXEMPT_PATHS:
            return self.get_response(request)
        try:
            domain = resolve_verified_domain(request.get_host())
        except TenantHostInvalid:
            # SuspiciousOperation -> templates/400.html (see its header
            # comment); nothing to unwind, raised before atomic()/tenant_scope() open.
            raise SuspiciousOperation("unknown tenant host") from None

        request.tenant = domain.agency  # type: ignore[attr-defined]
        with transaction.atomic(), tenant_scope(domain.agency_id):
            set_local_tenant(domain.agency_id)
            return self.get_response(request)


class TenantMembershipMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated:
            membership = Membership.objects.filter(user_id=request.user.id, active=True).first()
            if membership is None:
                # PermissionDenied, not HttpResponseForbidden: Django renders
                # templates/403.html with this message. A bare-text body would
                # swap in as the whole page under hx-boost, since base.html's
                # htmx-config makes 403 swap.
                raise PermissionDenied("tenant membership required")
            request.membership = membership  # type: ignore[attr-defined]
            if request.path != _MFA_SETUP_PATH:
                # require_staff_mfa already raises PermissionDenied; letting it
                # propagate is what reaches templates/403.html.
                require_staff_mfa(request.user, membership.role)
            if not request.path.startswith(_DELETION_EXEMPT_PREFIXES):
                target = deletion_lock_target(membership)
                if target is not None:
                    return redirect(target)
            if not request.path.startswith(_ACCEPTANCE_EXEMPT_PREFIXES):
                # Local import: apps.privacy imports apps.tenancy.models, so a
                # module-level import here would be circular.
                from apps.privacy.acceptance import needs_acceptance
                from apps.privacy.requests import processing_stopped

                if processing_stopped(membership):
                    return redirect("privacy-stopped")
                if needs_acceptance(membership):
                    return redirect("privacy-accept")
        return self.get_response(request)


def content_security_policy(
    get_response: Callable[[HttpRequest], HttpResponse],
) -> Callable[[HttpRequest], HttpResponse]:
    """A strict Content-Security-Policy on every HTML page (security review L4).

    The second line of defence behind autoescaping, for pages that render mail
    text. HTML only, and never over a policy a view set itself (a served
    document's `sandbox`). Django 5.2 has no CSP of its own.
    """
    from apps.mailbox.providers import GOOGLE_AUTH_URL, MICROSOFT_AUTH_URL

    def origin(url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    policy = "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            "style-src 'self'",
            "img-src 'self' data:",
            # documents.js POSTs the file to the URL boto3 presigns
            # (concierge.documents.presign_upload): the bucket's global
            # virtual-hosted endpoint, in every region.
            f"connect-src 'self' https://{settings.EVIDENCE_BUCKET_NAME}.s3.amazonaws.com",
            # The mailbox Connect forms GET our own route, which redirects to
            # the provider; browsers hold that redirect to form-action too.
            f"form-action 'self' {origin(GOOGLE_AUTH_URL)} {origin(MICROSOFT_AUTH_URL)}",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "object-src 'none'",
        )
    )

    def middleware(request: HttpRequest) -> HttpResponse:
        response = get_response(request)
        if (
            response.get("Content-Type", "").startswith("text/html")
            and "Content-Security-Policy" not in response
        ):
            response["Content-Security-Policy"] = policy
        return response

    return middleware
