"""One application's requirement-list inputs and builder (CV build step 4.2).

Worker-only (`runtime_engine`): loads the catalogue rows (`Program`,
`FundingOpportunity`, `CatalogRule`, `ApplicationPrompt`, `ProgramStatement`)
that the web tier (`runtime_web`) holds no grant to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q

from apps.funding.models import (
    ApplicationPrompt,
    CatalogRule,
    FundingOpportunity,
    Program,
    ProgramStatement,
)
from apps.portals.models import Application, ApplicationLink
from apps.tenancy.models import Membership

from . import render
from .letter_shape import shape_from_prompt
from .models import VerifiedFact
from .requirement_list import RequirementList, build_requirements
from .verification import generatable_facts

if TYPE_CHECKING:
    pass

#: Award routes applied for inside the programme's own application (§6.3).
TOGETHER_ROUTES: frozenset[str] = frozenset(
    {"CONSIDERED_WITH_ADMISSION", "JOINT_SELECTION"}
)


@dataclass(frozen=True)
class ListInputs:
    programme: Program | None
    opportunity: FundingOpportunity | None
    together: tuple[FundingOpportunity, ...]
    destination_label: str


def _linked_opportunity(application: Application) -> FundingOpportunity | None:
    linked_ids = list(
        ApplicationLink.objects.filter(
            to_app=application,
            from_app__student_id=application.student_id,
            from_app__candidate__opportunity__isnull=False,
        )
        .values_list("from_app__candidate__opportunity_id", flat=True)
        .distinct()
    )
    if len(linked_ids) != 1:
        return None
    return FundingOpportunity.objects.filter(id=linked_ids[0]).first()


def _programme_label(programme: Program) -> str:
    if programme.institution_id is not None and programme.institution is not None:
        inst_name = programme.institution.name
        if inst_name:
            return f"{programme.name}, {inst_name}"
    return programme.name


def inputs_for(
    application: Application | None, programme_id: UUID | None
) -> ListInputs | None:
    """Resolve the catalogue rows and destination label for one CV generation.

    Returns `None` when a non-null id names neither a `Program` nor a
    `FundingOpportunity` (the unknown-programme drop).
    """
    if (
        application is not None
        and application.candidate_id is not None
        and application.candidate is not None
        and application.candidate.opportunity_id is not None
    ):
        opportunity = application.candidate.opportunity
        if opportunity is None:
            return None
        return ListInputs(
            programme=None,
            opportunity=opportunity,
            together=(),
            destination_label=opportunity.name,
        )

    target_id = application.program_id if application is not None else programme_id
    if target_id is None:
        return ListInputs(
            programme=None, opportunity=None, together=(), destination_label=""
        )

    programme = (
        Program.objects.select_related("institution").filter(id=target_id).first()
    )
    if programme is None:
        opportunity = FundingOpportunity.objects.filter(id=target_id).first()
        if opportunity is None:
            return None
        return ListInputs(
            programme=None,
            opportunity=opportunity,
            together=(),
            destination_label=opportunity.name,
        )

    opportunity = (
        _linked_opportunity(application) if application is not None else None
    )
    together = tuple(
        FundingOpportunity.objects.filter(
            Q(program=programme) | Q(programs=programme),
            route__in=TOGETHER_ROUTES,
        )
        .distinct()
        .order_by("id")
    )
    return ListInputs(
        programme=programme,
        opportunity=opportunity,
        together=together,
        destination_label=_programme_label(programme),
    )


def track_for(programme: Program | None, student: Membership) -> str:
    if programme is not None and programme.academic_track:
        return programme.academic_track
    if generatable_facts(student).filter(category=VerifiedFact.Category.RESEARCH).exists():
        return "research"
    return "taught"


def build_for(
    inputs: ListInputs, student: Membership, application: Application | None
) -> RequirementList:
    letter_shape = None
    document_language = "en"
    if (
        inputs.programme is not None
        and application is not None
        and application.kit_letter_cycle
    ):
        prompt = ApplicationPrompt.objects.filter(
            programme=inputs.programme, cycle=application.kit_letter_cycle
        ).first()
        if prompt is not None:
            letter_shape = shape_from_prompt(prompt)
            document_language = prompt.document_language or "en"

    competencies: tuple[str, ...] = ()
    if inputs.programme is not None:
        competencies = tuple(
            ProgramStatement.objects.filter(
                program=inputs.programme, kind=ProgramStatement.Kind.COMPETENCY
            ).values_list("text", flat=True)
        )

    return build_requirements(
        inputs.programme,
        inputs.opportunity,
        together=inputs.together,
        catalog=CatalogRule.objects.order_by("rule_id"),
        track=track_for(inputs.programme, student),
        style_rules=render._UNIVERSAL_RULES,
        letter_shape=letter_shape,
        document_language=document_language,
        competencies=competencies,
    )
