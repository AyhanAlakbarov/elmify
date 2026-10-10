"""The board: one card per application, in five columns (dashboard spec §4).

`column_for`, `outcome_line` and `build_card` are pure functions over rows the
caller has read. `board_for` is the one function that queries, and it reads
tenant tables only: the card's programme facts are the copies the worker wrote
onto RecommendationCandidate, and the kit is built from the Application's copy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from django.utils import timezone

from apps.documents.table import Table, table_for
from apps.funding.grouping import funds
from apps.funding.models import RecommendationCandidate
from apps.funding.services import pack_awards
from apps.mailbox.models import MailSignal
from apps.portals.models import Application, zone_named
from apps.portals.outcome import is_funding_application
from apps.portals.packets import ApplicationKit, build_kit
from apps.tenancy.models import Membership

from .routes import action_url
from .templatetags.dashboard import https_only

# ponytail: a fixed window, not "unread" -- nothing records that the student
# opened a message. Add a seen-at on the signal if badges must clear on reading.
BADGE_WINDOW = timedelta(days=14)
_RECOGNISED = frozenset(MailSignal.Label.values)


class Column(StrEnum):
    TO_START = "To start"
    IN_PROGRESS = "In progress"
    SUBMITTED = "Submitted"
    CONFIRMED = "Confirmed"
    DECISION = "Decision"

    @property
    def key(self) -> str:
        """The stable name templates compare; the value is only the heading."""
        return self.name.lower()


def column_for(application: Application) -> Column:
    """Spec §4's table: state plus decision_available_at and outcome."""
    if application.decision_available_at is not None or application.outcome:
        return Column.DECISION
    if application.state == Application.State.CONFIRMED:
        return Column.CONFIRMED
    if application.state == Application.State.SUBMITTED:
        return Column.SUBMITTED
    if application.state == Application.State.PREPARING and application.started_at is None:
        return Column.TO_START
    return Column.IN_PROGRESS


@dataclass(frozen=True)
class Button:
    label: str
    url: str
    method: str = "get"


@dataclass(frozen=True)
class FundingLine:
    name: str
    covers: str
    amounts: str


@dataclass(frozen=True)
class Offer:
    """A letter's offer of a place on another programme (owner, 2026-10-04)."""

    signal_id: UUID
    institution: str
    programme: str
    accept_url: str
    ignore_url: str
    #: The provider authenticated the sender. Otherwise the offer is read to the
    #: person, never stated (the Messages page's wording; final review M1).
    authenticated: bool = False

    @property
    def line(self) -> str:
        if self.authenticated:
            return f"{self.institution} offers you a place in {self.programme}"
        return (
            f"{self.institution} — the email reads: offers a place in {self.programme}"
            " (unverified)"
        )


@dataclass(frozen=True)
class Card:
    application_id: UUID
    title: str
    institution: str
    country: str
    column: Column
    created_at: datetime
    deadline: datetime | None
    deadline_local: datetime | None
    days_left: int | None
    documents: tuple[int, int]
    answers: tuple[int, int]
    funding: tuple[FundingLine, ...]
    funding_outcome_line: str
    funds: tuple[str, ...]
    needs: tuple[str, ...]
    gap: str
    fee: Decimal | None
    fee_currency: str
    badges: tuple[str, ...]
    missing: tuple[str, ...]
    outcome_line: str
    offer: Offer | None
    button: Button | None
    has_portal: bool
    portal_url: str
    kit_url: str
    documents_url: str
    outcome_url: str
    remove_url: str
    portal_record_url: str
    #: The recorded outcome ("" while undecided). A decided card asks for no
    #: documents or answers; only a conditional offer's conditions stay (I2).
    outcome: str
    conditions: tuple[str, ...]


@dataclass(frozen=True)
class Board:
    columns: tuple[tuple[Column, tuple[Card, ...]], ...]

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for _column, cards in self.columns for card in cards)


def _local(deadline: datetime | None, zone: str) -> datetime | None:
    """The deadline in the portal's own zone (spec §4), or as stored."""
    where = zone_named(zone)
    return deadline.astimezone(where) if deadline is not None and where else deadline


def _covers(card: dict[str, object]) -> str:
    return ", ".join(
        f"{name}: {str(card.get(name)).lower()}"
        for name in ("tuition", "living")
        if card.get(name) in ("FULL", "PARTIAL")
    )


#: A scholarship is awarded or not, never "admitted" (controller ruling F18).
_AWARD_LABELS = {
    "ADMITTED": "awarded",
    "ADMITTED_CONDITIONAL": "awarded with conditions",
    "WAITLISTED": "waitlisted",
    "REJECTED": "not awarded",
    "WITHDRAWN": "withdrawn",
}


def _award_label(value: str) -> str:
    return f"Scholarship: {_AWARD_LABELS[value]}" if value in _AWARD_LABELS else ""


def _label(application: Application, value: str) -> str:
    """The outcome's label for this card, or "" for a value this code does not know."""
    if is_funding_application(application):
        return _award_label(value)
    return str(Application.Outcome(value).label) if value in Application.Outcome.values else ""


def _source_text(source: str, domain: str) -> str:
    if source == Application.OutcomeSource.MAIL:
        return f"from {domain}'s email" if domain else "from an email"
    if source == Application.OutcomeSource.PORTAL:
        return "from your portal"
    if source == Application.OutcomeSource.PERSON:
        return "recorded by hand"
    return ""


def outcome_line(
    application: Application, evidence_domain: str, *, read: str = "", unconfirmed: bool = False
) -> str:
    """"Admitted — from tum.de's email, 3 Oct", or one of the "Decision available" lines.

    ``read`` (a funding value on a scholarship card) is what Jev read the email
    as when it was not recorded (bars not yet learned): the person is asked to
    confirm it. ``unconfirmed`` is a DECISION mail Jev abstained on or could not
    read: the card asks too (spec §4).
    """
    if application.outcome:
        label = _label(application, application.outcome)
        if not label:
            return ""
        source = _source_text(application.outcome_source, evidence_domain)
        when = application.outcome_recorded_at
        day = f", {when.day} {when:%b}" if when is not None else ""
        return f"{label} — {source}{day}" if source else label
    if application.decision_available_at is not None and _label(application, read):
        return (
            f"Decision available — the email reads: {_label(application, read)}."
            " Confirm it below."
        )
    if application.decision_available_at is not None:
        return "Decision available — open the email or your portal to read it"
    if unconfirmed:
        return "Decision available — confirm: open the email or your portal, then record it below."
    return ""


def _conditions(application: Application) -> tuple[str, ...]:
    """Spec §4: each condition of a conditional offer is a missing item."""
    signal = application.outcome_evidence
    if application.outcome != Application.Outcome.ADMITTED_CONDITIONAL or signal is None:
        return ()
    raw = signal.outcome_conditions
    if not isinstance(raw, list):  # an erased signal's JSON is {}
        return ()
    return tuple(f"Condition: {condition}" for condition in raw if isinstance(condition, str))


def _funding_outcome_line(signals: Sequence[MailSignal]) -> str:
    for signal in signals:
        if not signal.trusted:
            continue
        value = signal.funding_outcome
        if value:
            label = _award_label(value)
            if not label:
                continue
            if not signal.sender_authenticated:
                # Tag-only mail may be read to the person, never stated as fact.
                return f"Scholarship: the email reads {_AWARD_LABELS[value]} — confirm it below."
            return f"{label} — from {signal.sender_domain}'s email"
    return ""


def _offer(
    application: Application, signals: Sequence[MailSignal], *, counselor_view: bool
) -> Offer | None:
    """The newest offer of another programme still waiting for Accept or Ignore."""
    signal = next(
        (
            s for s in signals if s.trusted and s.offered_programme and not s.offer_handled_at
        ), None
    )
    if signal is None:
        return None
    candidate = application.candidate
    institution = (
        candidate.institution_name
        if candidate is not None and candidate.institution_name
        else signal.sender_domain
    )
    return Offer(
        signal_id=signal.id,
        institution=institution,
        programme=signal.offered_programme,
        accept_url=action_url(counselor_view, "accept_offer", application.student_id, signal.id),
        ignore_url=action_url(counselor_view, "ignore_offer", application.student_id, signal.id),
        authenticated=signal.sender_authenticated,
    )


def _button(
    column: Column, *, has_portal: bool, start_url: str, portal_url: str,
    programme_url: str, documents_url: str, missing: tuple[str, ...],
) -> Button | None:
    """One main button by column (spec §4)."""
    if column is Column.TO_START:
        if has_portal:
            return Button("Start application", start_url, "post") if start_url else None
        return Button("Open programme page", programme_url) if programme_url else None
    if column is Column.IN_PROGRESS:
        if not has_portal:
            return Button("Open programme page", programme_url) if programme_url else None
        return Button("Continue filling", start_url, "post") if start_url else None
    if column in (Column.SUBMITTED, Column.CONFIRMED) and missing:
        return Button("Submit document", documents_url)
    return Button("Open portal", portal_url) if portal_url else None


def _read(application: Application, signal: MailSignal) -> str:
    return signal.funding_outcome if is_funding_application(application) else signal.outcome


def build_card(
    application: Application,
    *,
    kit: ApplicationKit,
    table: Table,
    signals: Sequence[MailSignal],
    awards: Sequence[RecommendationCandidate],
    linked: tuple[tuple[str, ...], tuple[str, ...]],
    counselor_view: bool,
    now: datetime,
) -> Card:
    candidate = application.candidate
    column = column_for(application)
    conditions = _conditions(application)
    missing = (*table.missing_for(application.id), *conditions)
    form = application.portal_form
    portal_url = https_only(form.form_url) if form is not None else ""
    programme_url = https_only(candidate.evidence.source_url) if candidate is not None else ""
    student_id = application.student_id
    documents_url = (
        f"/counselor/students/{student_id}/#application-{application.id}"
        if counselor_view
        else f"/student/documents/#application-{application.id}"
    )
    is_programme = candidate is not None and candidate.opportunity_id is None
    deadline = application.deadline
    # Untrusted mail is never presented as established: it contributes only its badge.
    trusted = [signal for signal in signals if signal.trusted]
    evidence = application.outcome_evidence
    return Card(
        application_id=application.id,
        title=application.title,
        institution=candidate.institution_name if candidate is not None else "",
        country=candidate.country_code if candidate is not None else "",
        column=column,
        created_at=application.created_at,
        deadline=deadline,
        deadline_local=_local(deadline, application.deadline_timezone),
        days_left=(deadline - now).days if deadline is not None else None,
        documents=table.counts_for(application.id),
        answers=(sum(1 for q in kit.questions if not q.missing), len(kit.questions)),
        funding=tuple(
            FundingLine(
                award.program_name,
                _covers(award.funding_card or {}),
                "; ".join(str(a) for a in (award.funding_card or {}).get("amounts", [])),
            )
            for award in awards
            if is_programme and candidate is not None and funds(award, candidate)
        ),
        funding_outcome_line=(
            "" if is_funding_application(application) else _funding_outcome_line(signals)
        ),
        funds=linked[0],
        needs=linked[1],
        gap=(
            f"{candidate.funding_gap} {candidate.currency}"
            if candidate is not None and not candidate.funding_gap_is_placeholder
            else ""
        ),
        fee=candidate.application_fee if candidate is not None else None,
        fee_currency=candidate.application_fee_currency if candidate is not None else "",
        badges=tuple(
            MailSignal.Label(signal.label).label + ("" if signal.trusted else " (unverified)")
            for signal in signals
            if signal.label in _RECOGNISED and signal.received_at >= now - BADGE_WINDOW
        ),
        missing=missing,
        outcome_line=outcome_line(
            application,
            evidence.sender_domain if evidence else "",
            read=next((_read(application, s) for s in trusted if _read(application, s)), ""),
            # Abstained or unavailable, not a confident "not a decision".
            unconfirmed=any(
                s.label == "DECISION"
                and (
                    (s.decision_reading or {}).get("is_decision") is None
                    or (s.decision_reading or {}).get("unavailable") is True
                )
                for s in trusted
            ),
        ),
        offer=_offer(application, signals, counselor_view=counselor_view),
        button=_button(
            column,
            has_portal=form is not None,
            start_url=action_url(counselor_view, "start", student_id, application.id),
            portal_url=portal_url,
            programme_url=programme_url,
            documents_url=documents_url,
            missing=missing,
        ),
        has_portal=form is not None,
        portal_url=portal_url,
        kit_url=action_url(counselor_view, "kit", student_id, application.id),
        documents_url=documents_url,
        outcome_url=action_url(counselor_view, "outcome", student_id, application.id),
        remove_url=action_url(counselor_view, "remove", student_id, application.id),
        portal_record_url=(
            action_url(counselor_view, "portal", student_id, application.id)
            if form is None
            else ""
        ),
        outcome=application.outcome,
        conditions=conditions,
    )


def _links(applications: Sequence[Application]) -> dict[UUID, tuple[list[str], list[str]]]:
    """"funds: TUM M.Sc." on the award's card, "needs: DAAD" on the programme's."""
    links: dict[UUID, tuple[list[str], list[str]]] = {a.id: ([], []) for a in applications}
    for award_app in applications:
        award = award_app.candidate
        if award is None or award.opportunity_id is None:
            continue
        for programme_app in applications:
            programme = programme_app.candidate
            if programme is None or programme.opportunity_id is not None:
                continue
            if funds(award, programme):
                links[award_app.id][0].append(programme_app.title)
                links[programme_app.id][1].append(award_app.title)
    return links


def board_for(
    student: Membership, *, counselor_view: bool = False, now: datetime | None = None
) -> Board:
    now = now or timezone.now()
    applications = list(
        Application.objects.filter(student=student)
        .select_related("portal_form", "candidate__evidence", "outcome_evidence")
        .order_by("created_at")
    )
    signals = list(
        MailSignal.objects.filter(application__in=applications)
        .select_related("connection")
        .order_by("-received_at")
    )
    by_application: dict[UUID, list[MailSignal]] = {}
    for signal in signals:
        if signal.application_id is not None:
            by_application.setdefault(signal.application_id, []).append(signal)
    # The Documents page's own set (apps/documents/views.py): a withdrawn card
    # has no column there, so nothing on it can be sent and nothing is missing.
    table = table_for(
        student,
        [a for a in applications if a.outcome != Application.Outcome.WITHDRAWN],
        signals,
    )
    awards = pack_awards(student)
    links = _links(applications)
    cards = [
        build_card(
            application,
            kit=build_kit(application),
            table=table,
            signals=by_application.get(application.id, []),
            awards=awards,
            linked=(tuple(links[application.id][0]), tuple(links[application.id][1])),
            counselor_view=counselor_view,
            now=now,
        )
        for application in applications
    ]
    far = now + timedelta(days=36500)
    return Board(
        columns=tuple(
            (
                column,
                tuple(
                    sorted(
                        (card for card in cards if card.column is column),
                        key=lambda card: (card.deadline or far, card.created_at),
                    )
                ),
            )
            for column in Column
        )
    )
