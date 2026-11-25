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

from django.db import transaction
from django.db.models import Max

from apps.funding.models import ApplicationPrompt, Program, RecommendationCandidate
from apps.portals.models import Application
from apps.research.provenance import Verdict, programme_verdict
from apps.research.storage import S3ObjectStore
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .approval import ApprovalBlocked
from .document_queue import DocumentWorkMessage
from .evidence.readings import UsableReading, usable_readings
from .letter_approval import mark_letter_ready
from .letter_defaults import defaults_for
from .letter_gates import GateCode, LetterGateViolation, check_claim_coverage
from .letter_render import render_letter
from .letter_schemas import LetterContent, Storyline
from .letter_shape import NotGeneratable, constraints_from_shape, shape_from_prompt
from .letters import (
    LetterGenerationError,
    LetterGenerationRateLimited,
    generate_letter,
    ground_and_align_letter_claims,
    inputs_for_programme,
)
from .models import DocumentDraft, NarrativeInput, VerifiedFact
from .prompt_resolution import resolve_application_prompt
from .render import PreflightBlocked
from .research_fit.home_context import propose_home_country_context
from .research_fit.service import propose_research_fit
from .storage import store_document
from .storyline import (
    StorylineProposalFailure,
    StorylineRateLimited,
    choose_storyline,
    propose_storylines,
    recent_programme_sentences,
    recent_theme_texts,
    theme_kind_for,
)
from .verification import generatable_facts

logger = logging.getLogger(__name__)

LETTER_FILENAME = "motivation-letter.pdf"
_GENERATABLE_STRUCTURES = frozenset(
    {
        ApplicationPrompt.Structure.SHORT_ANSWER_SET,
        ApplicationPrompt.Structure.CONTINUOUS_LETTER,
        ApplicationPrompt.Structure.TWO_STATEMENTS,
        ApplicationPrompt.Structure.PRESCRIBED_RESEARCH_FORM,
    }
)


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
            if name := str(payload.get("full_name") or "").strip():
                return name
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


def _storyline_for(
    student: object,
    prompt: ApplicationPrompt,
    facts: dict[UUID, VerifiedFact],
    inputs: dict[UUID, NarrativeInput],
    *,
    readings: tuple[UsableReading, ...] = (),
) -> Storyline | None:
    non_identity = [
        fact for fact in facts.values() if fact.category != VerifiedFact.Category.IDENTITY
    ]
    has_enough_facts = (
        len(non_identity) >= 3 and len({fact.category for fact in non_identity}) >= 2
    ) or (len(non_identity) >= 2 and bool(readings))
    if not has_enough_facts:
        return None
    row = defaults_for(
        country_code=prompt.programme.country_code,
        track=prompt.programme.academic_track,
        portfolio_led=prompt.programme.portfolio_led,
        funder_kind=prompt.funder_kind,
    )
    archetypes = tuple(prompt.archetypes) or row.archetypes
    theme_kind = theme_kind_for(prompt.funder_kind, archetypes)
    if theme_kind is None:
        return None
    try:
        candidates = propose_storylines(
            student=student,  # type: ignore[arg-type]
            facts=facts,
            inputs=inputs,
            theme_kind=theme_kind,
            readings=readings,
            programme_name=prompt.programme.name,
        )
    except (StorylineProposalFailure, StorylineRateLimited) as error:
        logger.warning(
            "storyline proposal degraded for student %s (%s): %s",
            getattr(student, "id", None),
            type(error).__name__,
            error,
        )
        return None
    return choose_storyline(
        candidates,
        facts=facts,
        recent_themes=recent_theme_texts(
            student=student,  # type: ignore[arg-type]
            programme_id=prompt.programme_id,
        ),
    )


def _ensure_research_fit(
    student: object,
    prompt: ApplicationPrompt,
    facts: dict[UUID, VerifiedFact],
    inputs: dict[UUID, NarrativeInput],
    storyline: Storyline | None,
    *,
    readings: tuple[UsableReading, ...] = (),
) -> None:
    if any(
        entry.kind == NarrativeInput.Kind.RESEARCH_FIT
        and isinstance(entry.provenance, dict)
        and str(entry.provenance.get("program_id")) == str(prompt.programme_id)
        for entry in inputs.values()
    ):
        return
    try:
        outcome = propose_research_fit(
            student=student,  # type: ignore[arg-type]
            program=prompt.programme,
            prompt=prompt,
            facts=facts,
            storyline=storyline,
            readings=readings,
        )
    except Exception as error:
        logger.warning(
            "research fit lookup degraded for student %s programme %s (%s): %s",
            getattr(student, "id", None),
            prompt.programme_id,
            type(error).__name__,
            error,
        )
        return
    if outcome.narrative_input is not None:
        inputs[outcome.narrative_input.id] = outcome.narrative_input


def _ensure_home_country_context(
    student: object,
    prompt: ApplicationPrompt,
    facts: dict[UUID, VerifiedFact],
    inputs: dict[UUID, NarrativeInput],
    storyline: Storyline | None,
) -> None:
    if prompt.immigration:
        return
    row = defaults_for(
        country_code=prompt.programme.country_code,
        track=prompt.programme.academic_track,
        portfolio_led=prompt.programme.portfolio_led,
        funder_kind=prompt.funder_kind,
    )
    archetypes = tuple(prompt.archetypes) or row.archetypes
    if "HOME_COUNTRY_CONTRIBUTION" not in archetypes and prompt.funder_kind not in (
        ApplicationPrompt.FunderKind.GOVERNMENT_SCHOLARSHIP,
        ApplicationPrompt.FunderKind.DEVELOPMENT_FOUNDATION,
    ):
        return
    try:
        entry = propose_home_country_context(
            student=student,  # type: ignore[arg-type]
            facts=facts,
            target_country_code=prompt.programme.country_code,
            programme_name=prompt.programme.name,
            storyline_theme=storyline.theme if storyline is not None else "",
        )
    except Exception as error:
        logger.warning(
            "home country context lookup degraded for student %s (%s): %s",
            getattr(student, "id", None),
            type(error).__name__,
            error,
        )
        return
    if entry is not None:
        inputs[entry.id] = entry


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
            inputs = inputs_for_programme(
                {entry.id: entry for entry in NarrativeInput.objects.filter(student=student)},
                prompt.programme_id,
            )
            readings = usable_readings(student)
            storyline: Storyline | None = None
            if (
                prompt.structure in _GENERATABLE_STRUCTURES
                and prompt.programme.letter_required != "not_requested"
                and not prompt.letter_handwritten
            ):
                storyline = _storyline_for(student, prompt, facts, inputs, readings=readings)
                _ensure_research_fit(
                    student, prompt, facts, inputs, storyline, readings=readings
                )
                _ensure_home_country_context(student, prompt, facts, inputs, storyline)
            cohort_sentences = recent_programme_sentences(
                programme_id=prompt.programme_id, student=student
            )
            try:
                result = generate_letter(
                    student=student,
                    prompt=prompt,
                    facts=facts,
                    inputs=inputs,
                    forbidden_institution_names=_forbidden_names(application, own),
                    storyline=storyline,
                    readings=readings,
                    cohort_sentences=cohort_sentences,
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
                application=application,
                destination_label=", ".join(p for p in (programme.name, own) if p),
                status=DocumentDraft.Status.DRAFT,
                letter_gates=[
                    {
                        "code": str(v.code),
                        "unit_archetype": v.unit_archetype,
                        "blocking": v.blocking,
                    }
                    for v in result.gate_violations
                ],
                letter_retried=result.binding_violation_after_retry,
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
            if application is not None:
                with tenant_transaction(message.tenant_id):
                    _settle(application, "", "")
            logger.info("approve_letter: draft %s or its application is gone", message.draft_id)
            return
        programme = (
            Program.objects.select_related("institution").filter(id=draft.programme_id).first()
        )
        if programme is None:
            with tenant_transaction(message.tenant_id):
                _settle(application, "", "")
            logger.info("approve_letter: programme %s is gone", draft.programme_id)
            return
        prompt = _prompt_for(programme, draft.letter_cycle)
        content = LetterContent.model_validate(draft.content)
        gates = tuple(
            LetterGateViolation(
                code=GateCode(entry["code"]),
                detail="",
                unit_archetype=entry.get("unit_archetype"),
                blocking=bool(entry.get("blocking", True)),
            )
            for entry in draft.letter_gates
        )

        with tenant_transaction(message.tenant_id):
            student = draft.student
            facts = {fact.id: fact for fact in generatable_facts(student)}
            inputs = {entry.id: entry for entry in NarrativeInput.objects.filter(student=student)}
            own_inst = programme.institution.name if programme.institution is not None else ""
            forbidden = _forbidden_names(application, own_inst)
            if facts and any(not u.claims for u in content.units):
                content = ground_and_align_letter_claims(
                    content,
                    facts=facts,
                    inputs=inputs,
                    document_language=prompt.document_language,
                )
                gates = (
                    *gates,
                    *(
                        v
                        for unit in content.units
                        for v in check_claim_coverage(
                            unit, document_language=prompt.document_language
                        )
                    ),
                )
            try:
                with transaction.atomic():
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
                        forbidden_institution_names=forbidden,
                    )
                    if approved.status != DocumentDraft.Status.APPROVED:
                        # A counsellor flag: the draft stays a draft, and says why.
                        _settle(application, "", "flagged")
                        return
                    shape = shape_from_prompt(prompt)
                    artifact = render_letter(
                        content,
                        structure=prompt.structure,
                        constraints=constraints_from_shape(
                            shape, document_language=prompt.document_language
                        ),
                        questions=prompt.questions,
                        shape=shape,
                        funder_kind=prompt.funder_kind,
                        addressee=_addressee(programme),
                        applicant_name=_applicant_name(facts),
                    )
            except (ApprovalBlocked, PreflightBlocked):
                _settle(application, "", "blocked")
                return
            _settle(application, "", "")

        if artifact is None or artifact.pdf_bytes is None:
            # A short-answer set: typed into the portal's own boxes, no file.
            return
        with tenant_transaction(message.tenant_id):
            store_document(
                draft=approved,
                filename=LETTER_FILENAME,
                content=artifact.pdf_bytes,
                store=S3ObjectStore(),
            )
