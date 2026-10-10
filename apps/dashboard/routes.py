"""Which URL each card and item action has, for the viewer (spec §4a)."""

from __future__ import annotations

from uuid import UUID

from django.urls import reverse

_STUDENT = {
    "start": "student-application-start",
    "outcome": "student-application-outcome",
    "remove": "student-application-remove",
    "kit": "portals-application-kit",
    "acknowledge": "concierge-acknowledge-notification",
    "accept_offer": "student-offer-accept",
    "ignore_offer": "student-offer-ignore",
}
#: No "start" and no "kit": the fill runs in the student's own browser through
#: the student's own extension (spec §4a), and the kit page is the student's.
_COUNSELOR = {
    "outcome": "counselor-student-outcome",
    "remove": "counselor-student-application-remove",
    "acknowledge": "counselor-student-acknowledge",
    "portal": "counselor-student-application-portal",
    "accept_offer": "counselor-student-offer-accept",
    "ignore_offer": "counselor-student-offer-ignore",
}


def action_url(counselor_view: bool, action: str, student_id: UUID, *args: UUID) -> str:
    """The URL for ``action``, or "" when this viewer does not get that action."""
    if counselor_view:
        name = _COUNSELOR.get(action)
        return reverse(name, args=[student_id, *args]) if name else ""
    name = _STUDENT.get(action)
    return reverse(name, args=list(args)) if name else ""
