"""One application's documents, side by side: what is asked on the left, the document on the right.

`/student/writing/letters/<application_id>/` is where a "Motivation letter"
link under "Still missing" lands (dashboard.mylist.missing_links). Each document
an application needs has its own tab -- motivation letter, recommendation
letters, scholarship essay -- because each has its own rules and its own text.

What is real and what is a front end waiting for its backend, stated here once:

* **Real:** the letter itself (the student's `DocumentDraft` rows), its state on
  `Application.letter_state`, and Write / Approve / Download, which post to the
  existing `letter_write` / `letter_approve` doors. The requirements on the left
  are the worker's tenant copy of the programme's page (`kit_requirements`,
  `kit_your_actions`, written by `portals.packets.capture_requirements`).
* **Front end only:** the "Tell us more for this letter" answers, recommendation
  requests and the scholarship essay. Each says so on the page, its controls are
  disabled, and nothing posts. No form here pretends to save.

Reads tenant rows only, so the web role's missing catalogue grant is never hit
(CLAUDE.md, "the catalogue boundary is a GRANT"); pinned by
`tests/documents/test_workspace.py` with `reads_no_catalogue`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render

from apps.portals.models import Application, ApplicationLink
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .models import DocumentDraft, RefereeRequest, VerifiedFact
from .referee_views import referee_context
from .verification import generatable_facts
from .writing import LETTER_NOTES, LetterRow, _writable

#: Requirement sentences about the letter itself, shown first. English only, and
#: only an ordering: every sentence is still shown below, never dropped.
_LETTER_EXPLICIT = re.compile(
    r"motivation|statement of purpose|personal statement|essay|cover letter|"
    r"letter of intent|study plan|research proposal|research interest",
    re.IGNORECASE,
)
_LETTER_LENGTH_ONLY = re.compile(r"\bletter\b|\bwords?\b|\bpages?\b|characters", re.IGNORECASE)
_NON_LETTER_DOC = re.compile(
    r"\bcv\b|curriculum vitae|resum[eé]|passport|transcript|diploma|"
    r"degree certificate|language certificate|ielts|toefl|testdaf|dsh\b|\baps\b",
    re.IGNORECASE,
)
_REFERENCE_WORDS = re.compile(r"recommendation|reference|referee", re.IGNORECASE)
_LETTER_ACTION_WORDS = re.compile(
    r"motivation|letter|statement|essay|supervisor|professor|advisor|research|topic|proposal|contact",
    re.IGNORECASE,
)

#: The tabs, in order. A key is also the `?doc=` value.
TABS = (
    ("letter", "Motivation letter"),
    ("references", "Recommendation letters"),
    ("essay", "Scholarship essay"),
)

#: The questions a good letter needs that the ledger does not hold. Shown now
#: so the page has its final shape; saving answers is the backend still owed.
LETTER_QUESTIONS = (
    ("why_programme", "Why this programme, and not a similar one elsewhere?"),
    ("goal", "What do you want to do in the five years after it?"),
    ("story", "One moment that made you choose this field."),
    ("avoid", "Anything the letter must not mention?"),
)


@dataclass(frozen=True)
class Requirements:
    letter: tuple[str, ...]
    references: tuple[str, ...]
    other: tuple[str, ...]
    your_actions: tuple[str, ...]

    @property
    def captured(self) -> bool:
        return bool(self.letter or self.references or self.other or self.your_actions)

    @property
    def letter_actions(self) -> tuple[str, ...]:
        return tuple(a for a in self.your_actions if _LETTER_ACTION_WORDS.search(a))

    @property
    def other_actions(self) -> tuple[str, ...]:
        return tuple(a for a in self.your_actions if not _LETTER_ACTION_WORDS.search(a))


def requirements_for(application: Application) -> Requirements:
    letter: list[str] = []
    references: list[str] = []
    other: list[str] = []
    for raw in application.kit_requirements or []:
        text = str(raw).strip()
        if not text:
            continue
        if _REFERENCE_WORDS.search(text):
            references.append(text)
        elif _LETTER_EXPLICIT.search(text) or (
            _LETTER_LENGTH_ONLY.search(text) and not _NON_LETTER_DOC.search(text)
        ):
            letter.append(text)
        else:
            other.append(text)
    actions = tuple(
        str(item.get("text", "")).strip()
        for item in application.kit_your_actions or []
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    )
    return Requirements(tuple(letter), tuple(references), tuple(other), actions)


def _drafts(student: Membership, application: Application) -> list[DocumentDraft]:
    if application.program_id is None:
        return []
    return list(
        DocumentDraft.objects.filter(
            student=student,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            programme_id=application.program_id,
        ).order_by("-version")
    )


def _scholarship_apps(
    student: Membership, application: Application, *, is_award: bool
) -> list[Application]:
    if is_award:
        return [application]
    links = (
        ApplicationLink.objects.filter(to_app=application, from_app__student=student)
        .exclude(from_app__outcome=Application.Outcome.WITHDRAWN)
        .select_related("from_app__candidate")
        .order_by("created_at")
    )
    prog_country = application.candidate.country_code if application.candidate else ""
    apps = [link.from_app for link in links]
    apps.sort(
        key=lambda a: (
            0
            if (a.candidate and prog_country and a.candidate.country_code == prog_country)
            or (
                a.candidate
                and (a.candidate.funding_card or {}).get("family") == "PRIVATE_FOUNDATION"
            )
            else 1
        )
    )
    return apps


def _essay_drafts(
    student: Membership, scholarship_app: Application | None
) -> list[DocumentDraft]:
    if scholarship_app is None or scholarship_app.candidate is None:
        return []
    opp_id = scholarship_app.candidate.opportunity_id
    if opp_id is None:
        return []
    return list(
        DocumentDraft.objects.filter(
            student=student,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            funding_opportunity_id=opp_id,
        ).order_by("-version")
    )


@login_required
def letter_workspace(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    application = (
        Application.objects.filter(id=application_id, student=student)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .select_related("candidate")
        .first()
    )
    if application is None:
        raise Http404
    candidate = application.candidate
    is_award = candidate is not None and candidate.opportunity_id is not None
    default_tab = "essay" if is_award else "letter"
    tab = request.GET.get("doc", default_tab)
    if tab not in dict(TABS):
        tab = default_tab
    row = LetterRow(
        application=application,
        drafts=_drafts(student, application),
        note=LETTER_NOTES.get(application.letter_note, ""),
        writable=_writable(application),
    )
    scholarship_apps = _scholarship_apps(student, application, is_award=is_award)
    selected_award_id = request.GET.get("award", "")
    scholarship_app = next(
        (a for a in scholarship_apps if str(a.id) == selected_award_id),
        scholarship_apps[0] if scholarship_apps else None,
    )
    essay_drafts = _essay_drafts(student, scholarship_app)
    essay_target = scholarship_app or application
    essay_row = LetterRow(
        application=essay_target,
        drafts=essay_drafts,
        note=LETTER_NOTES.get(essay_target.letter_note, ""),
        writable=False,
    )
    essay_requirements = (
        requirements_for(scholarship_app)
        if scholarship_app is not None
        else Requirements((), (), (), ())
    )
    scholarship_holder = ""
    if scholarship_app is not None and scholarship_app.candidate is not None:
        scholarship_holder = str(
            (scholarship_app.candidate.funding_card or {}).get("holder")
            or (scholarship_app.candidate.details or {}).get("holder")
            or ""
        )
    elif candidate is not None:
        scholarship_holder = str((candidate.details or {}).get("holder") or "")
    return render(
        request,
        "student/letter_workspace.html",
        {
            "application": application,
            "candidate": candidate,
            "is_award": is_award,
            "tabs": TABS,
            "tab": tab,
            "row": row,
            "requirements": requirements_for(application),
            "scholarship_apps": scholarship_apps,
            "scholarship_app": scholarship_app,
            "scholarship_holder": scholarship_holder,
            "essay_row": essay_row,
            "essay_requirements": essay_requirements,
            "questions": LETTER_QUESTIONS,
            "identity_confirmed": generatable_facts(student)
            .filter(category=VerifiedFact.Category.IDENTITY)
            .exists(),
            "referee_requests": list(
                RefereeRequest.objects.filter(
                    referee__student=student, application=application
                )
                .exclude(state=RefereeRequest.State.DECLINED)
                .select_related("referee")
                .order_by("created_at")
            ),
            "here": request.path,
        },
    )


@login_required
def references_page(request: HttpRequest) -> HttpResponse:
    """Ask a referee for a recommendation letter. Front end only, for now."""
    student = current_membership(request, Membership.Role.STUDENT)
    applications = list(
        Application.objects.filter(student=student)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .select_related("candidate")
        .order_by("created_at")
    )
    return render(
        request,
        "student/references.html",
        {
            **referee_context(student, counselor_view=False),
            "applications": applications,
            "asks": [
                (app, refs)
                for app in applications
                if (refs := requirements_for(app).references)
            ],
        },
    )
