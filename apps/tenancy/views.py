"""Minimal TOTP device-setup flow.

Staff roles (owner/counselor/platform admin) are denied by
TenantMembershipMiddleware's require_staff_mfa() until they have a confirmed
TOTPDevice and a session verified against it. This view is the only way to
get one: it is deliberately not gated by require_staff_mfa itself (a staff
user with no device yet must be able to reach it), just @login_required.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from segno import make as make_qr

from apps.ratelimit import rate_limited

#: A 6-digit TOTP POST is a textbook brute-force target.
_MFA_VERIFY_RATE_LIMIT = 10
_MFA_VERIFY_RATE_WINDOW_SECONDS = 60


def _mfa_verify_rate_limited(user_id: int) -> bool:
    return rate_limited(
        "mfa-verify",
        user_id,
        limit=_MFA_VERIFY_RATE_LIMIT,
        window_seconds=_MFA_VERIFY_RATE_WINDOW_SECONDS,
    )


@login_required
def mfa_setup(request: HttpRequest) -> HttpResponse:
    """Enroll a device if the user has none, and always accept a token to
    (re-)verify the current session -- a confirmed device only proves
    enrollment happened once; each session still needs its own otp_login()
    call, so this view must keep offering a token form after enrollment too.
    """
    assert request.user.pk is not None
    device = TOTPDevice.objects.filter(user_id=request.user.pk, confirmed=True).first()
    confirmed = device is not None
    if device is None:
        device, _created = TOTPDevice.objects.get_or_create(
            user_id=request.user.pk, confirmed=False, defaults={"name": "default"}
        )

    error = None
    status = 200
    if request.method == "POST":
        if _mfa_verify_rate_limited(request.user.pk):
            # Inline re-render, same 429 contract — a bare text body would
            # replace the whole page under hx-boost (design-lint-baseline
            # defect 5 family). The token is deliberately NOT verified on a
            # rate-limited request.
            error = "Too many attempts. Try again shortly."
            status = 429
        elif device.verify_token(request.POST.get("token", "")):
            if not device.confirmed:
                device.confirmed = True
                device.save(update_fields=["confirmed"])
            otp_login(request, device)
            return redirect("tenancy-mfa-setup")
        else:
            error = "Invalid code. Try again."

    context: dict[str, object] = {"confirmed": confirmed, "error": error}
    if not confirmed:
        context["qr_data_uri"] = make_qr(device.config_url).svg_data_uri(scale=4)
        context["secret"] = device.key
    return render(request, "tenancy/mfa_setup.html", context, status=status)
