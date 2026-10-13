"""The motivation letter's worker branch: write a letter, and approve one. Worker-side only.

The letter engine's second caller, after ``manage.py draft_letter``, and the
first one a student can reach: the web tier records the request on the
student's own ``Application`` row (``letter_state``) and queues a
``DocumentWorkMessage``; everything that reads the shared catalogue -- the
programme, its ``ApplicationPrompt`` -- happens here, because this worker runs
as ``runtime_engine`` and the web role holds no grant on those tables.

What this adds over the command, and why:

* **The cycle** is the kit's (``Application.kit_letter_cycle``), else the
  newest prompt the catalogue holds for the programme, else a prompt resolved
  for next year's cycle -- ``resolve_application_prompt`` never returns None,
  and an UNRESOLVED prompt is a counsellor flag at approval, not a refusal.
* **The forbidden names** are the institutions of the student's OTHER
  applications and pack candidates (tenant copies), so the wrong-institution
  gate checks something without anyone typing ``--forbid``.
* **Approval runs here too.** ``mark_letter_ready`` needs the prompt (a
  catalogue row) and trusts its caller for the gate violations, so the web tier
  can do neither. The gate violations it is handed are the ones this module
  stored on the draft when it generated the letter (``letter_gates``) -- the
  generator's own record, never a request's.

Refusals are the engine working, not the worker failing: each is written to
``Application.letter_note`` as a code (``LETTER_NOTES`` in ``writing.py``) and
the message is acknowledged. Anything else raises, so the queue's dead-letter
alarm sees it, exactly like the CV path.
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from django.db.models import Max

from apps.funding.models import ApplicationPrompt, Program, RecommendationCandidate
from apps.portals.models import Application
from apps.research.provenance import Verdict, programme_verdict
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .approval import ApprovalBlocked
from .document_queue import DocumentWorkMessage
from .letter_approval import mark_letter_ready
from .letter_gates import GateCode, LetterGateViolation
from .letter_render import render_letter
from .letter_schemas import LetterContent
from .letter_shape import NotGeneratable, constraints_from_shape, shape_from_prompt
from .letters import LetterGenerationError, LetterGenerationRateLimited, generate_letter
from .models import DocumentDraft, NarrativeInput, VerifiedFact
from .prompt_resolution import resolve_application_prompt
from .storage import store_document
from .verification import generatable_facts

logger = logging.getLogger(__name__)

LETTER_FILENAME = "motivation-letter.pdf"


def _default_cycle() -> str:
    """Next year's intake: what a student preparing a letter now applies for."""
    return str(date.today().year + 1)


def _prompt_for(programme: Program, cycle: str) -> ApplicationPrompt:
    if cycle:
        found = ApplicationPrompt.objects.filter(programme=programme, cycle=cycle).first()
        if found is not None:
            return found
    newest = ApplicationPrompt.objects.filter(programme=programme).order_by("-cycle").first()
    if newest is not None:
        return newest
    return resolve_application_prompt(program=programme, cycle=cycle or _default_cycle())


def _refusal_code(error: Exception) -> str:
    text = str(error)
    if isinstance(error, LetterGenerationRateLimited):
        return "rate_limited"
    if isinstance(error, NotGeneratable):
        if "naming required" in text:
            return "needs_research_fit"
        if "outside the engine" in text:
            return "not_a_letter"
        if "unsatisfiable" in text:
            return "shape_unsatisfiable"
        return "not_generatable"
    return "engine_refused"


def _forbidden_names(application: Application, own_institution: str) -> frozenset[str]:
    """Institutions the letter must not name: every other one the student is
    looking at. Tenant rows only (candidate copies), and never this
    programme's own institution."""
    names = set(
        RecommendationCandidate.objects.filter(
            run__profile_version__student_id=application.student_id
        )
        .exclude(institution_name="")
        .values_list("institution_name", flat=True)
    )
    own = own_institution.strip().casefold()
    return frozenset(name for name in names if name.strip().casefold() != own)


def _applicant_name(facts: dict[UUID, VerifiedFact]) -> str:
    for fact in reversed(list(facts.values())):
        if fact.category == VerifiedFact.Category.IDENTITY:
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            return str(payload.get("full_name") or "")
    return ""


def _addressee(programme: Program) -> str:
    institution = programme.institution
    where = ", ".join(part for part in (programme.city, programme.country_code) if part)
    return "\n".join(part for part in (institution.name if institution else "", where) if part)


def _settle(application: Application, state: str, note: str) -> None:
    application.letter_state = state
    application.letter_note = note
    application.save(update_fields=["letter_state", "letter_note"])


def _load_application(message: DocumentWorkMessage) -> Application | None:
    if message.application_id is None:
        raise ValueError("letter message carries no application_id")
    with tenant_transaction(message.tenant_id):
        return (
            Application.objects.select_related("student")
            .filter(id=message.application_id, student_id=message.student_id)
            .first()
        )


def generate_letter_for(message: DocumentWorkMessage) -> None:
    with tenant_scope(message.tenant_id):
        application = _load_application(message)
        if application is None:
            logger.info("letter: application %s is gone", message.application_id)
            return
        programme = (
            Program.objects.select_related("institution")
            .filter(id=application.program_id)
            .first()
        )
        if programme is None:
            with tenant_transaction(message.tenant_id):
                _settle(application, "REFUSED", "programme_unknown")
            return
        verdict, _code = programme_verdict(programme)
        if verdict == Verdict.BLOCKED:
            with tenant_transaction(message.tenant_id):
                _settle(application, "REFUSED", "programme_blocked")
            return
        prompt = _prompt_for(programme, application.kit_letter_cycle)
        own = programme.institution.name if programme.institution else ""

        with tenant_transaction(message.tenant_id):
            student = application.student
            facts = {fact.id: fact for fact in generatable_facts(student)}
            inputs = {entry.id: entry for entry in NarrativeInput.objects.filter(student=student)}
            try:
                result = generate_letter(
                    student=student,
                    prompt=prompt,
                    facts=facts,
                    inputs=inputs,
                    forbidden_institution_names=_forbidden_names(application, own),
                )
            except (NotGeneratable, LetterGenerationError) as error:
                logger.info("letter refused for application %s: %s", application.id, error)
                _settle(application, "REFUSED", _refusal_code(error))
                return
            # Version is unique per (student, kind) across every programme.
            last = DocumentDraft.objects.filter(
                student=student, kind=DocumentDraft.Kind.MOTIVATION_LETTER
            ).aggregate(top=Max("version"))["top"]
            DocumentDraft.objects.create(
                tenant_id=message.tenant_id,
                student=student,
                kind=DocumentDraft.Kind.MOTIVATION_LETTER,
                version=(last or 0) + 1,
                content=result.content.model_dump(mode="json"),
                programme=programme,
                status=DocumentDraft.Status.DRAFT,
                letter_gates=[
                    {"code": str(v.code), "unit_archetype": v.unit_archetype}
                    for v in result.gate_violations
                ],
                letter_retried=result.retried,
                letter_cycle=prompt.cycle,
            )
            _settle(application, "", "")


def approve_letter_for(message: DocumentWorkMessage) -> None:
    if message.draft_id is None:
        raise ValueError("approve_letter message carries no draft_id")
    with tenant_scope(message.tenant_id):
        application = _load_application(message)
        with tenant_transaction(message.tenant_id):
            draft = (
                DocumentDraft.objects.select_related("student")
                .filter(
                    id=message.draft_id,
                    student_id=message.student_id,
                    kind=DocumentDraft.Kind.MOTIVATION_LETTER,
                )
                .first()
            )
        if draft is None or draft.programme_id is None or application is None:
            logger.info("approve_letter: draft %s or its application is gone", message.draft_id)
            return
        programme = Program.objects.select_related("institution").get(id=draft.programme_id)
        prompt = _prompt_for(programme, draft.letter_cycle)
        content = LetterContent.model_validate(draft.content)
        gates = tuple(
            LetterGateViolation(
                code=GateCode(entry["code"]), detail="", unit_archetype=entry.get("unit_archetype")
            )
            for entry in draft.letter_gates
        )

        with tenant_transaction(message.tenant_id):
            student = draft.student
            facts = {fact.id: fact for fact in generatable_facts(student)}
            inputs = {entry.id: entry for entry in NarrativeInput.objects.filter(student=student)}
            try:
                approved = mark_letter_ready(
                    document=draft,
                    content=content,
                    gate_violations=gates,
                    prompt=prompt,
                    letter_required=programme.letter_required,
                    facts=facts,
                    inputs=inputs,
                    binding_violation_after_retry=draft.letter_retried,
                    accepted_by=student,
                )
            except ApprovalBlocked:
                _settle(application, "", "blocked")
                return
            if approved.status != DocumentDraft.Status.APPROVED:
                # A counsellor flag: the draft stays a draft, and says why.
                _settle(application, "", "flagged")
                return
            _settle(application, "", "")

        shape = shape_from_prompt(prompt)
        artifact = render_letter(
            content,
            structure=prompt.structure,
            constraints=constraints_from_shape(shape, document_language=prompt.document_language),
            questions=prompt.questions,
            shape=shape,
            funder_kind=prompt.funder_kind,
            addressee=_addressee(programme),
            applicant_name=_applicant_name(facts),
        )
        if artifact.pdf_bytes is None:
            # A short-answer set: typed into the portal's own boxes, no file.
            return
        with tenant_transaction(message.tenant_id):
            store_document(
                draft=approved,
                filename=LETTER_FILENAME,
                content=artifact.pdf_bytes,
                store=S3ObjectStore(),
            )
