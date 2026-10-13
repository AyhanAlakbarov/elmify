"""The "CV & letters" page: the document engine, where a student can reach it.

The CV half drives the JSON endpoints in ``api.py`` (confirm facts, write,
approve) and adds what they never had a page for: the draft itself, read back
with the ledger's verdict on every claim, so a student approves something they
have seen.

The letter half is the motivation-letter engine's web door. It reads only
tenant rows -- the student's applications, their letter drafts, the ledger --
and writes only ``Application.letter_state``; everything that needs the shared
catalogue (the programme, its ``ApplicationPrompt``) happens in the worker
(``letter_worker``), because ``runtime_web`` holds no grant on those tables.
Approval is queued too: ``mark_letter_ready`` needs the prompt, and must be
handed the gate violations the GENERATOR recorded, never any a request sends.

``api._SUPPORTED_KINDS`` stays CV-only on purpose; letters never reach the
generic draft endpoints, whose approve path would skip every letter gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.concierge.cycles import paid_cycle
from apps.dashboard.templatetags.dashboard import month_year
from apps.portals.models import Application
from apps.ratelimit import rate_limited
from apps.tenancy.context import current_tenant_id
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

from .approval import ApprovalBlocked, verdicts_for
from .document_queue import DocumentWorkMessage, enqueue_document_work
from .models import DocumentDraft, TranscriptPage, VerifiedFact
from .templatetags.cv_countries import country_name
from .verification import fact_label, generatable_facts, unsuperseded_facts

logger = logging.getLogger(__name__)

#: Why a letter is not there, in the student's words. Keyed by the codes the
#: worker writes to ``Application.letter_note``; an unknown code shows nothing.
LETTER_NOTES = {
    "programme_unknown": "We could not find this programme in our catalogue any more.",
    "programme_blocked": (
        "We could not confirm this university is officially recognised, "
        "so we did not write a letter for it."
    ),
    "needs_research_fit": (
        "This programme asks you to name a professor or research group you have "
        "contacted. Tell your counsellor who it is, then try again."
    ),
    "not_a_letter": (
        "This programme asks for a video or a consortium form instead of a letter. "
        "Your counsellor can help with it."
    ),
    "shape_unsatisfiable": (
        "This programme's rules for the letter contradict each other. "
        "Your counsellor will check them."
    ),
    "not_generatable": "The AI could not write a letter for this programme.",
    "engine_refused": (
        "The AI could not write a letter that passed its own checks. Try again later."
    ),
    "rate_limited": "You asked for many letters in the last hour. Try again later.",
    "blocked": (
        "This letter says something we could not match to your confirmed details, "
        "so it cannot be approved. Write a new version."
    ),
    "flagged": "Your counsellor needs to read this letter before it can be approved.",
}

#: A door-side brake on queued letter work, on top of generate_letter's own
#: 20/hour model limit: every request is a queue message and a worker turn.
_LETTER_REQUESTS_PER_HOUR = 10

_QUEUE_DOWN = "The writing service is not reachable right now. Try again in a few minutes."


@dataclass(frozen=True)
class LetterRow:
    application: Application
    drafts: list[DocumentDraft]
    note: str
    #: A catalogue programme. A scholarship card, or a programme the student
    #: named that nobody resolved, has no ApplicationPrompt to write to.
    writable: bool

    @property
    def latest(self) -> DocumentDraft | None:
        return self.drafts[0] if self.drafts else None

    @property
    def paragraphs(self) -> list[str]:
        latest = self.latest
        if latest is None:
            return []
        units = latest.content.get("units") if isinstance(latest.content, dict) else None
        return [str(unit.get("text", "")) for unit in units or [] if isinstance(unit, dict)]

    @property
    def header(self) -> str:
        latest = self.latest
        if latest is None or not isinstance(latest.content, dict):
            return ""
        return str(latest.content.get("header_block") or "")


@dataclass(frozen=True)
class FactView:
    """One unconfirmed detail, worded for the student to check."""

    category: str
    label: str
    detail: str
    bullets: tuple[str, ...]


def _fact_view(fact: VerifiedFact) -> FactView:
    payload = fact.payload if isinstance(fact.payload, dict) else {}
    category = fact.category
    detail: list[str] = []
    start, end = month_year(payload.get("start_date")), month_year(payload.get("end_date"))
    if start or end:
        detail.append(f"{start} to {end}" if start and end else start or f"until {end}")
    place = ", ".join(
        part
        for part in (
            str(payload.get("city") or ""),
            country_name(str(payload.get("country") or "")),
        )
        if part
    )
    if place:
        detail.append(place)
    if payload.get("grade_native"):
        scale = f" ({payload['grade_scale']})" if payload.get("grade_scale") else ""
        detail.append(f"grade {payload['grade_native']}{scale}")
    if category == VerifiedFact.Category.LANGUAGE:
        if payload.get("mother_tongue"):
            detail.append("mother tongue")
        if payload.get("cefr_level"):
            detail.append(str(payload["cefr_level"]))
        if payload.get("test_name"):
            score = f" {payload['test_score']}" if payload.get("test_score") else ""
            detail.append(f"{payload['test_name']}{score}")
    if category == VerifiedFact.Category.LANGUAGE:
        label = str(payload.get("language") or "")
    elif category == VerifiedFact.Category.EDUCATION:
        degree = payload.get("degree_english") or payload.get("degree_as_awarded")
        school = payload.get("institution_english") or payload.get("institution_original")
        label = ", ".join(str(part) for part in (degree, school) if part)
    elif category == VerifiedFact.Category.EXPERIENCE:
        label = ", ".join(str(payload[k]) for k in ("title", "employer") if payload.get(k))
    else:
        label = fact_label(fact)
    label = label or category.lower().capitalize()
    raw_bullets = payload.get("bullets")
    bullets = tuple(str(b) for b in raw_bullets) if isinstance(raw_bullets, list) else ()
    return FactView(category, label, ", ".join(detail), bullets)


def _cv_verdicts(draft: DocumentDraft | None) -> list[dict[str, str]]:
    if draft is None:
        return []
    try:
        verdicts = verdicts_for(draft)
    except ApprovalBlocked:
        return []
    return [
        {"text": verdict.claim_text, "verdict": str(verdict.verdict)}
        for verdict in verdicts
        if str(verdict.verdict) != "SUPPORTED"
    ]


def _transcript(student: Membership) -> dict[str, object] | None:
    cycle = paid_cycle(student.id)
    if cycle is None:
        return None
    pages = list(
        TranscriptPage.objects.filter(cycle=cycle, superseded_at__isnull=True).order_by("slot")
    )
    return {
        "pages": pages,
        "pages_left": max(0, settings.TRANSCRIPT_PAGES_PER_CYCLE - cycle.pages_used),
    }


def _writable(application: Application) -> bool:
    candidate = application.candidate
    return candidate is not None and candidate.program_id == application.program_id


def page_context(student: Membership) -> dict[str, object]:
    facts = list(unsuperseded_facts(student).filter(confirmed_by__isnull=True))
    confirmed = generatable_facts(student)
    cv_drafts = list(
        DocumentDraft.objects.filter(student=student, kind=DocumentDraft.Kind.CV).order_by(
            "-version"
        )
    )
    latest_cv = cv_drafts[0] if cv_drafts else None

    applications = list(
        Application.objects.filter(student=student)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .select_related("candidate", "portal_form")
        .order_by("created_at")
    )
    letters: dict[UUID, list[DocumentDraft]] = {}
    for draft in DocumentDraft.objects.filter(
        student=student, kind=DocumentDraft.Kind.MOTIVATION_LETTER
    ).order_by("-version"):
        if draft.programme_id is not None:
            letters.setdefault(draft.programme_id, []).append(draft)
    rows = [
        LetterRow(
            application=application,
            drafts=letters.get(application.program_id, []),
            note=LETTER_NOTES.get(application.letter_note, ""),
            writable=_writable(application),
        )
        for application in applications
    ]
    return {
        "facts": facts,
        "fact_views": [_fact_view(fact) for fact in facts],
        "confirm_body": json.dumps({"fact_ids": [str(fact.id) for fact in facts]}),
        "confirmed_count": confirmed.count(),
        "identity_confirmed": confirmed.filter(
            category=VerifiedFact.Category.IDENTITY
        ).exists(),
        "has_email": bool(student.application_email),
        "cv_drafts": cv_drafts,
        "latest_cv": latest_cv,
        "cv": latest_cv.content if latest_cv is not None else None,
        "cv_checks": _cv_verdicts(latest_cv),
        "letter_rows": rows,
        "transcript": _transcript(student),
    }


@login_required
def writing_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    return render(request, "student/writing.html", page_context(student))


def _enqueue(message: DocumentWorkMessage) -> bool:
    try:
        enqueue_document_work(message, queue_url=settings.DOCUMENT_QUEUE_URL)
    except (BotoCoreError, ClientError):
        logger.warning("document queue unreachable for %s", message.action)
        return False
    return True


@login_required
@require_POST
def letter_write(request: HttpRequest, application_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    application = get_object_or_404(
        Application.objects.select_related("candidate"), id=application_id, student=student
    )
    if not _writable(application):
        messages.error(request, "Letters are written for programmes, not for scholarships.")
        return redirect("student-writing")
    if not generatable_facts(student).filter(category=VerifiedFact.Category.IDENTITY).exists():
        messages.error(
            request, "Confirm your name and contact details first, at the top of this page."
        )
        return redirect("student-writing")
    if application.letter_state in ("QUEUED", "CHECKING"):
        return redirect("student-writing")
    if rate_limited(
        "letter-request", student.id, limit=_LETTER_REQUESTS_PER_HOUR, window_seconds=3600
    ):
        messages.error(request, LETTER_NOTES["rate_limited"])
        return redirect("student-writing")
    if not _enqueue(
        DocumentWorkMessage(
            action="generate",
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            tenant_id=current_tenant_id(),
            student_id=student.id,
            programme_id=application.program_id,
            application_id=application.id,
        )
    ):
        messages.error(request, _QUEUE_DOWN)
        return redirect("student-writing")
    application.letter_state = "QUEUED"
    application.letter_note = ""
    application.save(update_fields=["letter_state", "letter_note"])
    messages.success(request, f"The AI is writing your letter for {application.title}.")
    return redirect("student-writing")


@login_required
@require_POST
def letter_approve(request: HttpRequest, draft_id: UUID) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    draft = get_object_or_404(
        DocumentDraft,
        id=draft_id,
        student=student,
        kind=DocumentDraft.Kind.MOTIVATION_LETTER,
        status=DocumentDraft.Status.DRAFT,
    )
    application = (
        Application.objects.filter(student=student, program_id=draft.programme_id)
        .exclude(outcome=Application.Outcome.WITHDRAWN)
        .first()
        if draft.programme_id is not None
        else None
    )
    if application is None:
        messages.error(request, "This letter's application was removed.")
        return redirect("student-writing")
    if not _enqueue(
        DocumentWorkMessage(
            action="approve_letter",
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            tenant_id=current_tenant_id(),
            student_id=student.id,
            draft_id=draft.id,
            application_id=application.id,
        )
    ):
        messages.error(request, _QUEUE_DOWN)
        return redirect("student-writing")
    application.letter_state = "CHECKING"
    application.letter_note = ""
    application.save(update_fields=["letter_state", "letter_note"])
    messages.success(request, "Checking your letter. It will be ready to download in a minute.")
    return redirect("student-writing")
