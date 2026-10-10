"""Programme cards and the awards applied for separately that pay for them
(lanes spec §2, §4). An award the student is confirmed eligible for becomes its
own card, linked to every programme card it funds; one award is one card.

Every query is scoped to ``card.student``: the database guards stop a link
across tenants, not across two students of one tenant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.funding.grouping import funds
from apps.funding.models import RecommendationCandidate
from apps.tenancy.models import Membership

from .models import Application, ApplicationLink

#: The award routes with an application of their own (§5.2's `_Route`).
SEPARATE_ROUTES: frozenset[str] = frozenset(
    {"STUDENT_APPLIES_SEPARATELY", "HOME_GOVERNMENT_NOMINATES"}
)


def _is_award(candidate: RecommendationCandidate) -> bool:
    return candidate.opportunity_id is not None


def _addable(award: RecommendationCandidate) -> bool:
    return (
        award.state == RecommendationCandidate.State.VISIBLE
        and (award.funding_card or {}).get("route") in SEPARATE_ROUTES
        and award.eligibility_status == RecommendationCandidate.EligibilityStatus.ELIGIBLE
    )


def _run_pool(candidate: RecommendationCandidate) -> QuerySet[RecommendationCandidate]:
    """The candidates a programme card's awards are drawn from: its own run, in
    a stable order. One definition for `link_awards` and `award_lines`."""
    return RecommendationCandidate.objects.filter(run_id=candidate.run_id).order_by("id")


def _link(award_card: Application, programme_card: Application) -> None:
    try:
        with transaction.atomic():
            ApplicationLink.objects.get_or_create(
                tenant_id=award_card.tenant_id, from_app=award_card, to_app=programme_card,
                defaults={"order": ApplicationLink.Order.LINKED_ONLY},
            )
    except IntegrityError:
        pass  # a card removed under us: there is nothing left to link


def _board(student: Membership) -> dict[UUID, Application]:
    """The student's cards on the board, by candidate id."""
    return {
        c.candidate_id: c
        for c in Application.objects.filter(student=student).select_related("candidate")
        if c.candidate_id is not None
    }


def link_awards(card: Application, *, actor: Membership) -> None:
    """Add and link the separate awards for a programme card, or link an award
    card to the programme cards already on the board. Idempotent."""
    from .applications import _create, _existing_card, _known_portal  # the one way a card is made

    candidate = card.candidate
    if candidate is None:
        return
    cards = _board(card.student)
    if _is_award(candidate):
        for other in cards.values():
            programme = other.candidate
            if programme and not _is_award(programme) and funds(candidate, programme):
                _link(card, other)
        return
    for award in _run_pool(candidate):
        if not _is_award(award) or not funds(award, candidate):
            continue
        award_card = cards.get(award.id)
        if award_card is None:
            if not _addable(award):  # only the creation is gated; a card on the board links
                continue
            target = award.opportunity_id or award.id
            try:
                with transaction.atomic():  # a double click must not 500
                    # A Remove may have rejected it since we read it. no_key: a plain
                    # FOR UPDATE blocks the FK checks of a Remove's pack copy and deadlocks.
                    if not RecommendationCandidate.objects.select_for_update(
                        no_key=True
                    ).filter(
                        id=award.id, state=RecommendationCandidate.State.VISIBLE
                    ).exists():
                        continue
                    award_card = _create(
                        card.student, program_id=target, candidate=award, name="",
                        portal=_known_portal(target), actor=actor,
                        event="application.award_added", capture=True,
                    )
            except IntegrityError:
                award_card = _existing_card(card.student, award)
                if award_card is None:
                    raise
            cards[award.id] = award_card
        _link(award_card, card)


LineKind = Literal[
    "AUTOMATIC", "SAME_APPLICATION", "NOMINATED", "COMBINED", "SUGGESTED", "NOT_STATED"
]

_NOT_STATED: tuple[LineKind, str] = (
    "NOT_STATED", "How to apply for this is not stated — open its page",
)
_LINE_FOR_ROUTE: dict[str, tuple[LineKind, str]] = {
    "AUTOMATIC_ON_ADMISSION": ("AUTOMATIC", "Considered automatically — nothing to do"),
    "CONSIDERED_WITH_ADMISSION": (
        "SAME_APPLICATION", "Considered with your application — nothing extra to submit",
    ),
    "INSTITUTION_NOMINATES": (
        "NOMINATED", "Nominated by the university — you cannot apply for it",
    ),
    "JOINT_SELECTION": ("COMBINED", "Programme + scholarship, one application"),
}
_SUGGESTED: tuple[LineKind, str] = (
    "SUGGESTED", "Suggested for this programme — check you qualify, then add it",
)


@dataclass(frozen=True)
class AwardLine:
    name: str
    kind: LineKind
    text: str
    candidate_id: UUID


def award_lines(card: Application) -> list[AwardLine]:
    """What the programme card says about each pack award that funds it and is
    not already its own card (lanes spec §2). Plan 2 renders these."""
    candidate = card.candidate
    if candidate is None or _is_award(candidate):
        return []
    on_board = _board(card.student)
    lines: list[AwardLine] = []
    for award in _run_pool(candidate):
        if (
            not _is_award(award) or award.id in on_board
            or award.state != RecommendationCandidate.State.VISIBLE
            or award.eligibility_status == RecommendationCandidate.EligibilityStatus.NOT_ELIGIBLE
            or not funds(award, candidate)
        ):
            continue
        route = (award.funding_card or {}).get("route", "")
        kind, text = (
            _SUGGESTED if route in SEPARATE_ROUTES else _LINE_FOR_ROUTE.get(route, _NOT_STATED)
        )
        lines.append(AwardLine(award.program_name, kind, text, award.id))
    return sorted(lines, key=lambda line: line.name.casefold())
