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
import re
from dataclasses import dataclass
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
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
from .audit import record_event
from .document_queue import DocumentWorkMessage, enqueue_document_work
from .drafts import attach_source_facts
from .gaps import gap_notes, gap_questions
from .models import DocumentDraft, TranscriptPage, VerifiedFact
from .templatetags.cv_countries import country_name
from .verification import fact_label, generatable_facts, has_full_name
from .views import summarize_gap_questions

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

    @property
    def letter_requirements(self) -> tuple[str, ...]:
        from .workspace import requirements_for

        reqs = requirements_for(self.application)
        return reqs.letter or reqs.other


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


CV_VARIANT_LABELS = {
    "GERMAN_TABULAR": "German Tabular CV",
    "EUROPASS": "Europass CV",
    "EUROPASS_API": "Europass CV",
    "FUNDER_TEMPLATE": "Funder Template CV",
    "FIELD_MAPPED": "Portal Field-Mapped CV",
    "STANDARD": "Standard Academic CV",
}


def _writable(application: Application) -> bool:
    candidate = application.candidate
    return candidate is not None and candidate.program_id == application.program_id


def page_context(student: Membership, selected_cv_id: str = "") -> dict[str, object]:
    from . import reupload
    from .gaps.models import preload_gap_facts
    from .verification import confirm_candidates, disowned_refs

    with preload_gap_facts(student) as cached_facts:
        pending_ids = {c.fact.id for c in reupload.pending_changes(student)}
        facts = [
            fact
            for fact in confirm_candidates(student)
            if not fact.source_ref.startswith("document:") and fact.id not in pending_ids
        ]
        disowned = disowned_refs(student)
        confirmed_list = [
            f
            for f in cached_facts
            if f.confirmed_by_id is not None
            and f.category != VerifiedFact.Category.ID_DOCUMENT
            and f.source_ref not in disowned
        ]
        cv_drafts = list(
            DocumentDraft.objects.filter(student=student, kind=DocumentDraft.Kind.CV).order_by(
                "-version"
            )
        )
        for d in cv_drafts:
            d.variant_label = CV_VARIANT_LABELS.get(  # type: ignore[attr-defined]
                d.render_variant or "STANDARD", "Standard Academic CV"
            )
            fallback_title = (
                "General Master CV"
                if d.is_general or not d.programme_id
                else "Tailored Programme CV"
            )
            d.target_title = (  # type: ignore[attr-defined]
                d.destination_label.strip() if d.destination_label else fallback_title
            )
            d.cv_checks = _cv_verdicts(d)  # type: ignore[attr-defined]
        latest_cv = (
            next((d for d in cv_drafts if str(d.id) == selected_cv_id), None)
            or (cv_drafts[0] if cv_drafts else None)
        )

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
            target_id = draft.programme_id or draft.funding_opportunity_id
            if target_id is not None:
                letters.setdefault(target_id, []).append(draft)
        rows = [
            LetterRow(
                application=application,
                drafts=letters.get(
                    application.program_id
                    or (application.candidate.opportunity_id if application.candidate else None),  # type: ignore[arg-type]
                    [],
                ),
                note=LETTER_NOTES.get(application.letter_note, ""),
                writable=_writable(application),
            )
            for application in applications
        ]
        rows.sort(key=lambda r: (0 if r.writable else 1))
        gap_summary = summarize_gap_questions(gap_questions(student))
        notes = gap_notes(student)
        cv_checks = getattr(latest_cv, "cv_checks", []) if latest_cv is not None else []
    return {
        "facts": facts,
        "fact_views": [_fact_view(fact) for fact in facts],
        "confirm_body": json.dumps({"fact_ids": [str(fact.id) for fact in facts]}),
        "confirmed_count": len(confirmed_list),
        "identity_confirmed": any(
            f.category == VerifiedFact.Category.IDENTITY
            and isinstance(f.payload, dict)
            and bool(str(f.payload.get("full_name") or "").strip())
            for f in confirmed_list
        ),
        "has_email": bool(student.application_email),
        "cv_drafts": cv_drafts,
        "latest_cv": latest_cv,
        "cv": latest_cv.content if latest_cv is not None else None,
        "cv_checks": cv_checks,
        "letter_rows": rows,
        "transcript": _transcript(student),
        **gap_summary,
        "gap_notes": notes,
    }


@login_required
def writing_page(request: HttpRequest) -> HttpResponse:
    student = current_membership(request, Membership.Role.STUDENT)
    selected_cv_id = request.GET.get("cv", "")
    return render(request, "student/writing.html", page_context(student, selected_cv_id))


#: Where a letter action may send the student back to: the letter workspace
#: (documents.workspace). Anything else in `next` is ignored.
_BACK_TO = re.compile(r"^/student/writing/letters/[0-9a-f-]{36}/(\?doc=[a-z]+)?$")


def _back(request: HttpRequest) -> HttpResponse:
    """Back to the page the action was pressed on: the workspace, else CV & letters."""
    target = str(request.POST.get("next", ""))
    if _BACK_TO.match(target):
        return redirect(target)
    return redirect("student-writing")


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
        return _back(request)
    if not has_full_name(generatable_facts(student)).exists():
        messages.error(
            request, "Confirm your name and contact details first, at the top of this page."
        )
        return _back(request)
    if application.letter_state in ("QUEUED", "CHECKING"):
        return _back(request)
    if rate_limited(
        "letter-request", student.id, limit=_LETTER_REQUESTS_PER_HOUR, window_seconds=3600
    ):
        messages.error(request, LETTER_NOTES["rate_limited"])
        return _back(request)
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
        return _back(request)
    application.letter_state = "QUEUED"
    application.letter_note = ""
    application.save(update_fields=["letter_state", "letter_note"])
    messages.success(request, f"The AI is writing your letter for {application.title}.")
    return _back(request)


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
        return _back(request)
    if application.letter_state in ("QUEUED", "CHECKING"):
        return _back(request)
    if rate_limited(
        "letter-approve", student.id, limit=_LETTER_REQUESTS_PER_HOUR, window_seconds=3600
    ):
        messages.error(request, LETTER_NOTES["rate_limited"])
        return _back(request)
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
        return _back(request)
    application.letter_state = "CHECKING"
    application.letter_note = ""
    application.save(update_fields=["letter_state", "letter_note"])
    messages.success(request, "Checking your letter. It will be ready to download in a minute.")
    return _back(request)


@login_required
@require_POST
def letter_refine(request: HttpRequest, draft_id: UUID) -> HttpResponse:
    """Save the student's edited paragraphs as a new numbered DocumentDraft version."""
    student = current_membership(request, Membership.Role.STUDENT)
    draft = get_object_or_404(
        DocumentDraft,
        id=draft_id,
        student=student,
        kind=DocumentDraft.Kind.MOTIVATION_LETTER,
    )
    if rate_limited(
        "letter-refine", student.id, limit=_LETTER_REQUESTS_PER_HOUR, window_seconds=3600
    ):
        messages.error(request, LETTER_NOTES["rate_limited"])
        return _back(request)
    raw_text = (request.POST.get("refined_text") or "").strip()
    paragraphs = [p.strip() for p in raw_text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs or len(raw_text) > 12000:
        messages.error(request, "Write at least one paragraph (up to 12,000 characters).")
        return _back(request)
    old_content = draft.content if isinstance(draft.content, dict) else {}
    raw_units = old_content.get("units")
    old_units: list[object] = list(raw_units) if isinstance(raw_units, list) else []
    default_archetypes = (
        "OPENING",
        "ACADEMIC_PREPARATION",
        "EXPERIENCE",
        "WHY_PROGRAMME",
        "CLOSING",
    )
    new_units = []
    for idx, text in enumerate(paragraphs):
        old_unit = old_units[idx] if idx < len(old_units) else None
        if isinstance(old_unit, dict) and old_unit.get("archetype"):
            archetype = str(old_unit["archetype"])
        elif idx == len(paragraphs) - 1 and len(paragraphs) > 1:
            archetype = "CLOSING"
        else:
            archetype = default_archetypes[min(idx, len(default_archetypes) - 1)]
        unit_dict: dict[str, object] = {"archetype": archetype, "text": text}
        if isinstance(old_unit, dict) and old_unit.get("answers_question") is not None:
            unit_dict["answers_question"] = old_unit["answers_question"]
        if isinstance(old_unit, dict) and isinstance(old_unit.get("claims"), list):
            preserved_claims: list[dict[str, object]] = []
            for raw_claim in old_unit["claims"]:
                if not isinstance(raw_claim, dict):
                    continue
                claim_txt = str(raw_claim.get("text") or "")
                if not claim_txt:
                    continue
                pos = text.find(claim_txt)
                if pos >= 0:
                    updated_claim = dict(raw_claim)
                    updated_claim["span_start"] = pos
                    updated_claim["span_end"] = pos + len(claim_txt)
                    preserved_claims.append(updated_claim)
            if preserved_claims:
                unit_dict["claims"] = preserved_claims
        new_units.append(unit_dict)
    new_content_dict: dict[str, object] = {
        "language": str(old_content.get("language") or "en"),
        "units": new_units,
    }
    if old_content.get("header_block") is not None:
        new_content_dict["header_block"] = old_content["header_block"]
    if old_content.get("storyline") is not None:
        new_content_dict["storyline"] = old_content["storyline"]
    with transaction.atomic():
        Membership.objects.select_for_update().get(id=student.id)
        top = (
            DocumentDraft.objects.filter(
                student=student,
                kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            )
            .order_by("-version")
            .first()
        )
        next_version = (top.version if top is not None else draft.version) + 1
        new_draft = DocumentDraft.objects.create(
            student=student,
            kind=DocumentDraft.Kind.MOTIVATION_LETTER,
            programme_id=draft.programme_id,
            funding_opportunity_id=draft.funding_opportunity_id,
            application_id=draft.application_id,
            destination_label=draft.destination_label,
            letter_cycle=draft.letter_cycle,
            version=next_version,
            status=DocumentDraft.Status.DRAFT,
            content=new_content_dict,
        )
        attach_source_facts(document=new_draft, facts=draft.source_facts.all())
        record_event(
            actor=student, event="document.letter_refined", object_id=new_draft.id
        )
    messages.success(
        request,
        f"Saved your refined letter as version {new_draft.version}. "
        "Review and approve it when ready.",
    )
    return _back(request)
