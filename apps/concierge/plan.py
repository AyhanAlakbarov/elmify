"""`/student/settings/plan/`: what the student pays for, and whether this year is paid.

**The cycle status is real** (`StudentCycle`, `cycles.paid_cycle`); **paying is
not built**. Today a cycle is marked paid by `manage.py mark_cycle_paid` (or early
access); the card checkout is the backend still owed. The Pay button says so and
is disabled, so nothing here can look like a charge that did not happen.

Prices are the proposed ones from the pitch, shown as such until the pilot
settles them.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .cycles import current_academic_year, paid_cycle

PLANS = (
    {
        "key": "explore",
        "name": "Explore",
        "price": "$0",
        "period": "free",
        "features": ("Programme and funding matches", "One CV", "Deadline calendar"),
    },
    {
        "key": "apply",
        "name": "Apply",
        "price": "$19",
        "period": "a month, cancel any time",
        "features": (
            "Unlimited CVs and letters",
            "An application kit for each programme",
            "The autofill browser extension",
        ),
    },
)


@login_required
def plan_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    cycle = paid_cycle(student.id)
    return render(
        request,
        "student/settings_plan.html",
        {
            "cycle": cycle,
            "academic_year": current_academic_year(),
            "plans": PLANS,
            "current_plan": "apply" if cycle is not None else "explore",
        },
    )
