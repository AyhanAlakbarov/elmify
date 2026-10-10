"""The public "Book a demo" page and the owner's action on a request."""

from __future__ import annotations

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.privacy.views import _client_ip, _key
from apps.ratelimit import rate_limited
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .forms import DemoRequestForm
from .models import DemoRequest

TOO_MANY = "Too many requests from your connection. Try again in an hour."
_HOUR = 3600


@require_http_methods(["GET", "POST"])
def book_demo(request: HttpRequest) -> HttpResponse:
    form = DemoRequestForm(request.POST or None)
    if request.method == "POST":
        if rate_limited("demo-request", _key(_client_ip(request)), limit=5, window_seconds=_HOUR):
            return render(
                request, "leads/book_demo.html", {"form": form, "error": TOO_MANY}, status=429
            )
        if form.is_valid():
            form.save()
            return redirect("leads-demo-thanks")
        return render(request, "leads/book_demo.html", {"form": form}, status=400)
    return render(request, "leads/book_demo.html", {"form": form})


def demo_thanks(request: HttpRequest) -> HttpResponse:
    return render(request, "leads/demo_thanks.html")


@login_required
@require_POST
def mark_contacted(request: HttpRequest, request_id: UUID) -> HttpResponse:
    current_membership(request, Membership.Role.OWNER)
    demo = get_object_or_404(DemoRequest, id=request_id)
    demo.state = DemoRequest.State.CONTACTED
    demo.save(update_fields=["state"])
    messages.success(request, f"Marked {demo.full_name} as contacted.")
    return redirect("concierge-owner-dashboard")
