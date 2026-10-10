from django.http import HttpRequest

from .services import validate_brand_palette

PLATFORM_DEFAULT_PRIMARY = "#0254a5"  # must pass validate_brand_palette


def viewer_role(request: HttpRequest) -> dict[str, str | None]:
    """The current user's active-membership role, for role-gating nav links.

    Set by TenantMembershipMiddleware (request.membership) so this doesn't
    re-query -- None for anonymous users or requests that middleware didn't
    attach a membership to (e.g. it 403'd before reaching the view).
    """
    membership = getattr(request, "membership", None)
    return {"viewer_role": getattr(membership, "role", None)}


def brand_colors(request: HttpRequest) -> dict[str, str]:
    """Validated brand primary color, falling back to the platform default.

    Python (not CSS) owns the WCAG contrast check, since CSS cannot call
    validate_brand_palette — see apps/tenancy/services.py. The palette check
    covers the derived --brand-tint as well as the primary.
    """
    agency = getattr(request, "tenant", None)
    primary = getattr(agency, "brand_primary_color", None) or PLATFORM_DEFAULT_PRIMARY
    if not validate_brand_palette(primary):
        primary = PLATFORM_DEFAULT_PRIMARY
    return {"brand_primary_color": primary}


#: Pages a signed-in user is held on until they act -- new terms, a paused or
#: closing account, staff two-step setup. They render without the app menu,
#: because every menu link would only bounce back here (TenantMembershipMiddleware).
_GATE_PREFIXES = (
    "/privacy/",
    "/legal/",
    "/student/account/",
    "/mfa/setup/",
    "/signup/",
)


def app_shell(request: HttpRequest) -> dict[str, bool]:
    """Whether base.html draws the sidebar and top bar (presentation only)."""
    membership = getattr(request, "membership", None)
    return {
        "app_shell": membership is not None
        and request.user.is_authenticated
        and not request.path.startswith(_GATE_PREFIXES)
    }
