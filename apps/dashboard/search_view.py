"""`GET /student/search/?q=` -- the search box in the app shell (see search.py)."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .search import MIN_QUERY, search, terms


@login_required
@require_GET
def student_search(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    query = request.GET.get("q", "").strip()
    groups = search(student, query)
    return render(
        request,
        "student/search.html",
        {
            "search_query": query,
            "searched": bool(terms(query)),
            "groups": groups,
            "total": sum(len(group.results) for group in groups),
            "min_query": MIN_QUERY,
        },
    )
