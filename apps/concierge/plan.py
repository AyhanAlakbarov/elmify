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

from .cycles import current_academic_year, cycle_consumption_status, paid_cycle

PLANS = (
    {
        "key": "explore",
        "name": "Explore",
        "price": "0 AZN",
        "period": "€0 / $0 · free forever",
        "features": (
            (
                "Eligibility check across flagship scholarships "
                "(Dövlət Proqramı, HTP, DAAD, Chevening, Erasmus Mundus, SISGP)"
            ),
            (
                "First 3 hidden & niche funding matches unlocked "
                "(regional, foundation & automatic waivers)"
            ),
            "City living-cost & uncovered gap calculator + deadline calendar",
            "1 base academic CV draft",
        ),
    },
    {
        "key": "apply",
        "name": "Apply Cycle Pass",
        "price": "299 AZN",
        "period": "€159 / $175 for the full academic year (or 3 × 109 AZN)",
        "features": (
            (
                "All matched hidden & niche scholarships unlocked across 53 countries "
                "(DSU, IdEx, Visegrad, Stiftungen, automatic waivers)"
            ),
            "Verified Bachelor's transcript PDF upload & ECTS credit check",
            (
                "Up to 10 fact-locked programme & scholarship kits "
                "(CV, motivation letter, scholarship essay, referee brief)"
            ),
            (
                "Elmify glass-box browser extension for 1-click portal autofill "
                "& PDF staging (you press Submit)"
            ),
            (
                "Pre-purchase match count preview + 7-day unconsumed refund "
                "if < 5 verified matches (before kit export or extension use)"
            ),
        ),
    },
    {
        "key": "concierge",
        "name": "Cycle Pass + Counsellor Review",
        "price": "499 AZN",
        "period": "€269 / $295 for the full academic year (or 3 × 179 AZN)",
        "features": (
            "Everything in Apply Cycle Pass with unlimited programme kits for the academic year",
            "Human counsellor line-by-line review & sign-off on up to 5 priority applications",
            (
                "Direct counsellor workspace chat (/student/messages/) "
                "+ 2 live 30-minute video walkthroughs"
            ),
            "Pre-submission portal audit before you click Submit in your browser",
        ),
    },
)


@login_required
def plan_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    cycle = paid_cycle(student.id)
    consumption = cycle_consumption_status(student.id, cycle)
    return render(
        request,
        "student/settings_plan.html",
        {
            "cycle": cycle,
            "consumption": consumption,
            "academic_year": current_academic_year(),
            "plans": PLANS,
            "current_plan": "apply" if cycle is not None else "explore",
        },
    )
