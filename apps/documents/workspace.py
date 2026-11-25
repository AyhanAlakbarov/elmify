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

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.portals.models import Application, ApplicationLink
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .audit import record_event
from .models import DocumentDraft, NarrativeInput
from .referee_views import referee_context, visible_referee_requests
from .verification import generatable_facts, has_full_name
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

#: Structured prompts that feed the student's confirmed NarrativeInput ledger
#: for motivation letters (mapped 1-to-1 to NarrativeInput.Kind).
LETTER_QUESTIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "research_plan",
        "Which courses, labs, or professors at this university match your research or study plan?",
        (
            "e.g. Prof. Weber's Catalysis Group, the Advanced Synthesis Lab module, "
            "or your proposed MSc thesis topic"
        ),
        NarrativeInput.Kind.RESEARCH_PLAN,
    ),
    (
        "career_goal",
        (
            "What specific career role or research path are you aiming for "
            "after completing this degree?"
        ),
        (
            "e.g. R&D process chemist in sustainable catalysis, or pursuing a PhD "
            "in organometallic chemistry"
        ),
        NarrativeInput.Kind.DEVELOPMENT_IMPACT,
    ),
    (
        "key_project",
        (
            "Which past thesis, research project, or technical achievement best proves "
            "you are ready for this programme?"
        ),
        (
            "e.g. My BSc thesis on selective oxidation of aromatics using FTIR "
            "and GC-MS reaction monitoring"
        ),
        NarrativeInput.Kind.PERSONAL_BACKGROUND,
    ),
    (
        "home_impact",
        "How will you apply what you learn to your field or home country after graduating?",
        "e.g. Modernizing cleaner catalytic and environmental monitoring workflows in Azerbaijan",
        NarrativeInput.Kind.HOME_COUNTRY_CIRCUMSTANCES,
    ),
)

_MAX_NOTE_CHARS = 2000


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

    def _holder_for(target: Application | None) -> str:
        if target is not None and target.candidate is not None:
            return str(
                (target.candidate.funding_card or {}).get("holder")
                or (target.candidate.details or {}).get("holder")
                or ""
            )
        if candidate is not None:
            return str((candidate.details or {}).get("holder") or "")
        return ""

    essay_targets = scholarship_apps if scholarship_apps else [application]
    essay_bundles = [
        {
            "app": target_app if scholarship_apps else None,
            "id": str(target_app.id),
            "row": LetterRow(
                application=target_app,
                drafts=_essay_drafts(student, target_app if scholarship_apps else None),
                note=LETTER_NOTES.get(target_app.letter_note, ""),
                writable=False,
            ),
            "requirements": (
                requirements_for(target_app)
                if scholarship_apps
                else Requirements((), (), (), ())
            ),
            "holder": _holder_for(target_app if scholarship_apps else None),
        }
        for target_app in essay_targets
    ]
    active_bundle = next(
        (b for b in essay_bundles if scholarship_app and b["id"] == str(scholarship_app.id)),
        essay_bundles[0],
    )
    essay_row = active_bundle["row"]
    essay_requirements = active_bundle["requirements"]
    scholarship_holder = active_bundle["holder"]
    existing_inputs: dict[str, str] = {}
    for entry in NarrativeInput.objects.filter(
        student=student,
        kind__in=[kind for _k, _l, _p, kind in LETTER_QUESTIONS],
    ).order_by("created_at"):
        if entry.text and entry.text.strip():
            existing_inputs[entry.kind] = entry.text.strip()
    letter_questions = [
        {
            "key": key,
            "label": label,
            "placeholder": placeholder,
            "value": existing_inputs.get(kind, ""),
        }
        for key, label, placeholder, kind in LETTER_QUESTIONS
    ]
    saved_notes_count = sum(1 for q in letter_questions if q["value"])
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
            "essay_bundles": essay_bundles,
            "questions": [(q["key"], q["label"]) for q in letter_questions],
            "letter_questions": letter_questions,
            "saved_notes_count": saved_notes_count,
            "identity_confirmed": has_full_name(generatable_facts(student)).exists(),
            "referee_requests": [
                q
                for q in visible_referee_requests(student)
                if q.application_id == application.id
            ],
            "here": request.path,
        },
    )


@login_required
@require_POST
def letter_notes_save(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    application = (
        Application.objects.filter(id=application_id, student=student)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .first()
    )
    if application is None:
        raise Http404
    now = timezone.now()
    saved_kinds: list[str] = []
    for key, _label, _placeholder, kind in LETTER_QUESTIONS:
        if key not in request.POST:
            continue
        raw = str(request.POST.get(key) or "").strip()[:_MAX_NOTE_CHARS]
        existing = (
            NarrativeInput.objects.filter(
                student=student,
                kind=kind,
                proposed_by=NarrativeInput.ProposedBy.STUDENT,
            )
            .order_by("-created_at")
            .first()
        )
        if raw:
            if existing is not None:
                existing.text = raw
                existing.confirmed_at = now
                existing.save(update_fields=["text", "confirmed_at"])
            else:
                NarrativeInput.objects.create(
                    student=student,
                    kind=kind,
                    text=raw,
                    proposed_by=NarrativeInput.ProposedBy.STUDENT,
                    confirmed_at=now,
                )
            saved_kinds.append(kind)
        elif existing is not None:
            existing.delete()
    record_event(
        actor=student,
        event="letter.notes_saved",
        object_id=application.id,
    )
    messages.success(
        request,
        "Saved your letter notes. Click 'Write a new version' whenever you want "
        "the letter updated with them.",
    )
    return redirect(f"/student/writing/letters/{application.id}/?doc=letter")


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
