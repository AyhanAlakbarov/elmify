"""Programme cards and the awards applied for separately that pay for them
(lanes spec §2, §4). An award the student is confirmed eligible for becomes its
own card, linked to every programme card it funds; one award is one card.

Every query is scoped to ``card.student``: the database guards stop a link
across tenants, not across two students of one tenant."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import StudentProfileVersion
from apps.dashboard.dates import final_passed
from apps.funding.grouping import funds
from apps.funding.models import RecommendationCandidate
from apps.tenancy.models import Membership

from .models import Application, ApplicationLink


def _student_home_country(student_id: UUID) -> str:
    profile = (
        StudentProfileVersion.objects.filter(student_id=student_id).order_by("-version").first()
    )
    return str((profile.snapshot or {}).get("nationality") or "") if profile else ""

#: The award routes with an application of their own (§5.2's `_Route`).
SEPARATE_ROUTES: frozenset[str] = frozenset(
    {"STUDENT_APPLIES_SEPARATELY", "HOME_GOVERNMENT_NOMINATES"}
)


def _is_award(candidate: RecommendationCandidate) -> bool:
    return candidate.opportunity_id is not None


def _deadline_passed(award: RecommendationCandidate, *, today: date) -> bool:
    raw = (award.funding_card or {}).get("deadline")
    if not isinstance(raw, str) or not raw:
        return False
    try:
        return date.fromisoformat(raw[:10]) < today
    except ValueError:
        return False


def _award_card_viable(
    award_card: Application,
    award: RecommendationCandidate,
    *,
    today: date,
    now: datetime,
) -> bool:
    if award_card.outcome in (Application.Outcome.REJECTED, Application.Outcome.WITHDRAWN):
        return False
    fcard = award.funding_card or {}
    is_external_sep = (
        fcard.get("scope") in ("HOLDER", "COUNTRY", "GLOBAL")
        and fcard.get("route") == "STUDENT_APPLIES_SEPARATELY"
    )
    unsubmitted_state = award_card.state in (
        Application.State.PREPARING,
        Application.State.READY_TO_SUBMIT,
    ) or award_card.state.startswith("BLOCKED_")
    is_sent_or_won = not unsubmitted_state or award_card.outcome in (
        Application.Outcome.ADMITTED,
        Application.Outcome.ADMITTED_CONDITIONAL,
    )
    if is_external_sep and is_sent_or_won:
        return True
    if _deadline_passed(award, today=today):
        return False
    return not final_passed(award_card, now)


def _addable(award: RecommendationCandidate, *, today: date | None = None) -> bool:
    return (
        award.state == RecommendationCandidate.State.VISIBLE
        and (award.funding_card or {}).get("route") in SEPARATE_ROUTES
        and award.eligibility_status == RecommendationCandidate.EligibilityStatus.ELIGIBLE
        and not _deadline_passed(award, today=today or timezone.now().date())
    )


def _run_pool(candidate: RecommendationCandidate) -> QuerySet[RecommendationCandidate]:
    """The candidates a programme card's awards are drawn from: its own run, in
    a stable order. One definition for `link_awards` and `award_lines_for`."""
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
    now = timezone.now()
    today = now.date()
    home_country = _student_home_country(card.student_id)
    dead_outcomes = (Application.Outcome.REJECTED, Application.Outcome.WITHDRAWN)
    cards = _board(card.student)
    if _is_award(candidate):
        if not _award_card_viable(card, candidate, today=today, now=now):
            return
        for other in cards.values():
            programme = other.candidate
            if (
                programme
                and not _is_award(programme)
                and other.outcome not in dead_outcomes
                and other.funding_outcome not in dead_outcomes
                and not final_passed(other, now)
                and funds(candidate, programme, home_country=home_country)
            ):
                _link(card, other)
        return
    for award in _run_pool(candidate):
        if not _is_award(award) or not funds(award, candidate, home_country=home_country):
            continue
        award_card = cards.get(award.id)
        if award_card is None:
            # only the creation is gated; a card on the board links
            if not _addable(award, today=today):
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
        elif not _award_card_viable(award_card, award, today=today, now=now):
            continue
        _link(award_card, card)


LineKind = Literal["AUTOMATIC", "SAME_APPLICATION", "NOMINATED", "COMBINED", "ASK", "NOT_STATED"]

_NOT_STATED: tuple[LineKind, str] = (
    "NOT_STATED", "How to apply for this is not stated — see its official page",
)
_LINE_FOR_ROUTE: dict[str, tuple[LineKind, str]] = {
    "AUTOMATIC_ON_ADMISSION": ("AUTOMATIC", "Considered automatically — nothing to do"),
    "CONSIDERED_WITH_ADMISSION": (
        "SAME_APPLICATION", "Considered with your application — nothing extra to submit",
    ),
    "INSTITUTION_NOMINATES": ("NOMINATED", "Nominated by the university"),
    "JOINT_SELECTION": ("COMBINED", "Programme + scholarship, one application"),
}
#: Spec §4.3 (amended 2026-10-10): the one-tap question, with the funder's sentence.
_ASK: tuple[LineKind, str] = ("ASK", "Does this apply to you?")


@dataclass(frozen=True)
class AwardLine:
    name: str
    kind: LineKind
    text: str
    candidate_id: UUID
    claim: str = ""
    source_url: str = ""
    add_url: str = ""


def award_lines_for(applications: Sequence[Application]) -> dict[UUID, list[AwardLine]]:
    """Each programme card's lines (lanes spec §2). `applications` is the
    student's whole board, so "already its own card" is read from it."""
    on_board = {a.candidate_id for a in applications if a.candidate_id is not None}
    today = timezone.now().date()
    pools: dict[UUID, list[RecommendationCandidate]] = {}
    home_countries: dict[UUID, str] = {}
    out: dict[UUID, list[AwardLine]] = {}
    for card in applications:
        candidate = card.candidate
        out[card.id] = []
        if candidate is None or _is_award(candidate):
            continue
        if card.student_id not in home_countries:
            home_countries[card.student_id] = _student_home_country(card.student_id)
        home_country = home_countries[card.student_id]
        if candidate.run_id not in pools:
            pools[candidate.run_id] = list(
                _run_pool(candidate).select_related("evidence")
            )
        for award in pools[candidate.run_id]:
            if (
                not _is_award(award) or award.id in on_board
                or award.state != RecommendationCandidate.State.VISIBLE
                or award.eligibility_status
                == RecommendationCandidate.EligibilityStatus.NOT_ELIGIBLE
                or _deadline_passed(award, today=today)
                or not funds(award, candidate, home_country=home_country)
            ):
                continue
            route = (award.funding_card or {}).get("route", "")
            kind, text = (
                _ASK if route in SEPARATE_ROUTES else _LINE_FOR_ROUTE.get(route, _NOT_STATED)
            )
            out[card.id].append(AwardLine(
                award.program_name, kind, text, award.id,
                claim=award.evidence.claim if kind == "ASK" else "",
                source_url=award.evidence.source_url if kind == "NOT_STATED" else "",
            ))
        out[card.id].sort(key=lambda line: line.name.casefold())
    return out

