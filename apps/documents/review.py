"""Letters waiting for a counsellor: `/counselor/letters/`.

A letter the engine flagged (an UNRESOLVED prompt, a gate it could not settle)
stays a DRAFT with `Application.letter_note == "flagged"`, and the student is
told "Your counsellor needs to read this letter before it can be approved."
Until this page, no counsellor screen showed them (CLAUDE.md: "no counsellor
approval surface exists yet").

**The list and the letter are real; Approve and Send back are not built yet.**
Approving a flagged letter has to run `mark_letter_ready` in the worker with the
counsellor as `accepted_by`, which is the backend still owed; the buttons say so
and are disabled. Scoped to the counsellor's own active assignments, from tenant
rows only.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.portals.models import Application
from apps.tenancy.models import CounselorAssignment, Membership
from apps.tenancy.services import current_membership

from .models import DocumentDraft


@dataclass(frozen=True)
class WaitingLetter:
    application: Application
    draft: DocumentDraft | None

    @property
    def paragraphs(self) -> list[str]:
        content = self.draft.content if self.draft is not None else None
        units = content.get("units") if isinstance(content, dict) else None
        return [str(unit.get("text", "")) for unit in units or [] if isinstance(unit, dict)]


def waiting_letters(counselor: Membership) -> list[WaitingLetter]:
    students = CounselorAssignment.objects.filter(counselor=counselor, active=True).values(
        "student_id"
    )
    applications = list(
        Application.objects.filter(student_id__in=students, letter_note="flagged")
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .select_related("candidate", "student")
        .order_by("created_at")
    )
    rows = []
    for application in applications:
        draft = (
            DocumentDraft.objects.filter(
                student_id=application.student_id,
                kind=DocumentDraft.Kind.MOTIVATION_LETTER,
                programme_id=application.program_id,
                status=DocumentDraft.Status.DRAFT,
            )
            .order_by("-version")
            .first()
            if application.program_id is not None
            else None
        )
        rows.append(WaitingLetter(application, draft))
    return rows


@login_required
def letter_review_queue(request: HttpRequest) -> HttpResponse:
    counselor = current_membership(request, Membership.Role.COUNSELOR)
    return render(
        request, "counselor/letter_review.html", {"letters": waiting_letters(counselor)}
    )
