from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.http.request import split_domain_port
from django.utils import timezone

from .context import tenant_scope
from .models import Membership, SupportGrant, TenantDomain


class TenantHostInvalid(ValueError):
    pass


def current_membership(request: HttpRequest, role: str) -> Membership:
    """Look up the caller's active membership for ``role``.

    Raises Django's PermissionDenied (-> a clean 403) rather than letting
    Membership.DoesNotExist escape as an unhandled 500. Every role-gated view
    routes through here, so this is the single place that needs the guard.
    """
    assert request.user.pk is not None
    try:
        return Membership.objects.get(user_id=request.user.pk, role=role, active=True)
    except Membership.DoesNotExist as error:
        raise PermissionDenied("no active membership for this role") from error


def resolve_verified_domain(raw_host: str) -> TenantDomain:
    host, _port = split_domain_port(raw_host.lower())
    if not host:
        raise TenantHostInvalid(raw_host)
    try:
        return TenantDomain.objects.select_related("agency").get(
            host=host, verified_at__isnull=False
        )
    except TenantDomain.DoesNotExist as error:
        raise TenantHostInvalid(raw_host) from error


def require_active_support_grant(administrator: AbstractBaseUser, tenant_id: UUID) -> SupportGrant:
    """Look up an unrevoked, currently-active SupportGrant for administrator/tenant.

    Runs its own tenant_scope so it works whether or not the caller is
    already inside one (e.g. a management command, not a tenant-hosted request).
    """
    now = timezone.now()
    with tenant_scope(tenant_id):
        return SupportGrant.objects.get(
            administrator_id=administrator.pk,
            tenant_id=tenant_id,
            starts_at__lte=now,
            ends_at__gt=now,
            revoked_at=None,
        )


def validate_brand_contrast(foreground_hex: str, background_hex: str) -> bool:
    def luminance(hex_color: str) -> float:
        rgb = [int(hex_color.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

    l1, l2 = luminance(foreground_hex), luminance(background_hex)
    lighter, darker = max(l1, l2), min(l1, l2)
    ratio = (lighter + 0.05) / (darker + 0.05)
    return ratio >= 4.5  # WCAG AA normal-text threshold


# --brand-tint is derived in CSS as
# color-mix(in srgb, var(--brand-primary) 22%, var(--surface-canvas)).
# These constants mirror that derivation so save-time validation sees the
# same color the browser will render.
#
# They used to be the mirror and are now the DEFINITION: the stylesheet and
# the design contract they were kept in sync with were both removed with the
# presentation layer (DESIGN.md, deleted 2026-09-19). Whoever builds the next
# one matches these numbers, not the other way round -- a stylesheet that
# mixes at any other ratio silently invalidates every palette this file
# accepted at save time.
BRAND_TINT_MIX = 0.22
CANVAS_HEX = "#f9f7f0"  # --surface-canvas
TINT_TEXT_HEXES = ("#333333", "#13426f")  # the only text colors permitted on the tint


def derive_brand_tint(primary_hex: str) -> str:
    """Python mirror of the CSS color-mix that produces --brand-tint."""
    primary = [int(primary_hex.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    canvas = [int(CANVAS_HEX.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)]
    mixed = [round(BRAND_TINT_MIX * p + (1 - BRAND_TINT_MIX) * c) for p, c in zip(primary, canvas)]
    return "#" + "".join(f"{value:02x}" for value in mixed)


def validate_brand_palette(primary_hex: str) -> bool:
    """Validate the tenant primary AND the tokens derived from it.

    validate_brand_contrast alone never sees --brand-tint, so a primary could
    pass while a derived surface fails; this closes that gap and keeps the
    guarantee if BRAND_TINT_MIX ever changes.
    """
    tint = derive_brand_tint(primary_hex)
    return validate_brand_contrast(primary_hex, "#ffffff") and all(
        validate_brand_contrast(text_hex, tint) for text_hex in TINT_TEXT_HEXES
    )
