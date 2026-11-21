from django.conf import settings
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import include, path

from apps.tenancy.models import Membership


def index(request: HttpRequest) -> HttpResponse:
    """Send a student to the board, a counsellor or owner to their list, a visitor to the website.

    The Outlook callback ends on the mailbox page now, but any other link to the
    bare host lands somewhere useful instead of on the word "Elmify".
    """
    role = getattr(getattr(request, "membership", None), "role", None)
    if role == Membership.Role.STUDENT:
        return redirect("concierge-student-dashboard")
    if role == Membership.Role.COUNSELOR:
        return redirect("concierge-counselor-dashboard")
    if role == Membership.Role.OWNER:
        return redirect("concierge-owner-dashboard")
    if role == Membership.Role.PLATFORM_ADMIN:
        return redirect("staff-overview")
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        return redirect("accounts-login")
    # Nobody signed in: the first thing a new visitor sees is the website, not a login box.
    return redirect(settings.MARKETING_SITE_URL)


urlpatterns = [
    path("", index),
    path("", include("apps.accounts.urls")),
    path("", include("apps.tenancy.urls")),
    path("", include("apps.funding.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.concierge.urls")),
    path("", include("apps.dashboard.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.documents.urls")),
    path("", include("apps.portals.urls")),
    path("", include("apps.mailbox.urls")),
    path("", include("apps.privacy.urls")),
    path("", include("apps.leads.urls")),
    path("", include("apps.staffdesk.urls")),
    path("", include("apps.research.urls")),
    path("admin/", admin.site.urls),
]
