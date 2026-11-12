"""The board: one card per application, in five columns (dashboard spec §4).

`column_for`, `outcome_line` and `build_card` are pure functions over rows the
caller has read. `board_for` is the one function that queries, and it reads
tenant tables only: the card's programme facts are the copies the worker wrote
onto RecommendationCandidate, and the kit is built from the Application's copy.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import SimpleNamespace
from uuid import UUID

from django.utils import timezone
from pydantic import ValidationError

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import LanguageEvidence, StudentProfileSnapshot
from apps.dashboard.notices import notice_for
from apps.documents.table import Table, table_for
from apps.funding.fx import RateTable
from apps.funding.grouping import funds
from apps.funding.models import RecommendationCandidate
from apps.funding.probability import joint_admission_and_funding_chance_pct
from apps.funding.rates import latest_table
from apps.funding.services import pack_awards
from apps.funding.transcript_eligibility import evaluate_program_statement
from apps.mailbox.models import MailSignal
from apps.portals.award_links import award_lines_for
from apps.portals.fees import PAYABLE
from apps.portals.models import Application, ApplicationLink, zone_named
from apps.portals.outcome import is_funding_application
from apps.portals.packets import ApplicationKit, build_kits_for_board
from apps.tenancy.models import Membership

from .dates import both_zones, counting_deadline, final_passed, pre_checks
from .lanes import Lane, lanes_for
from .money import (
    WITH_APPLICATION,
    BudgetLine,
    Overrun,
    approx,
    budget_line,
    home_currency,
    money_from,
    over_budget,
    position,
    rate_note,
)
from .routes import action_url
from .templatetags.dashboard import https_only

logger = logging.getLogger(__name__)

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
    apply: bool = False


@dataclass(frozen=True)
class FundingLine:
    name: str
    covers: str
    amounts: str
    duration: str = ""
    deadline: str = ""
    source_url: str = ""
    source_domain: str = ""
    last_checked: datetime | None = None


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
    days_left: int | None
    documents: tuple[int, int]
    answers: tuple[int, int]
    funding: tuple[FundingLine, ...]
    funding_outcome_line: str
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
    deadline_text: str = ""
    deadline_wording: str = ""
    closed: bool = False
    pre_checks: tuple[str, ...] = ()
    is_award: bool = False
    notice_line: str = ""
    requirements: tuple[str, ...] = ()
    source_url: str = ""
    source_domain: str = ""
    last_checked: datetime | None = None
    fee_state: str = ""
    fee_paid_url: str = ""
    fee_text: str = ""
    risk_line: str = ""
    chance_line: str = ""
    funding_outcome: str = ""
    has_bundled_funding: bool = False
    deadline_local: datetime | None = None

    @property
    def converted(self) -> bool:
        """An amount on this card was converted, so the board shows the rate note."""
        return "≈" in self.fee_text


@dataclass(frozen=True)
class Board:
    lanes: tuple[Lane, ...]
    done: tuple[Lane, ...]
    rates: RateTable | None = None
    home: str = ""
    #: Shown once on the board and the programme page, never per card (§7.6).
    rate_note: str = ""
    budget: BudgetLine | None = None
    budget_url: str = ""
    #: The profile holds a budget with a currency, convertible or not.
    budget_set: bool = False

    @property
    def open_cards(self) -> tuple[Card, ...]:
        return tuple(card for lane in self.lanes for card in lane.cards)

    @property
    def cards(self) -> tuple[Card, ...]:
        return tuple(card for lane in (*self.lanes, *self.done) for card in lane.cards)

    @property
    def columns(self) -> tuple[tuple[Column, tuple[Card, ...]], ...]:
        all_cards = self.cards
        return tuple(
            (column, tuple(card for card in all_cards if card.column is column))
            for column in Column
        )


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


def _conditions(
    application: Application,
    *,
    profile_snapshot: object | None = None,
    today: date | None = None,
) -> tuple[str, ...]:
    """Spec §4: each condition of a conditional offer is a missing item."""
    signal = application.outcome_evidence
    if application.outcome != Application.Outcome.ADMITTED_CONDITIONAL or signal is None:
        return ()
    raw = signal.outcome_conditions
    if not isinstance(raw, list):  # an erased signal's JSON is {}
        return ()
    out: list[str] = []
    for condition in raw:
        if not isinstance(condition, str):
            continue
        if (
            profile_snapshot is not None
            and evaluate_program_statement(
                condition, profile_snapshot, kind="OTHER", as_of=today
            ).outcome
            == "SATISFIED"
        ):
            out.append(f"Condition: {condition} (met by your updated scores — ready to send)")
        else:
            out.append(f"Condition: {condition}")
    return tuple(out)


def _mail_funding_domain(application: Application, signals: Sequence[MailSignal]) -> str:
    ev = application.outcome_evidence
    if ev is not None and ev.sender_domain:
        return ev.sender_domain
    return next(
        (
            sig.sender_domain
            for sig in signals
            if sig.trusted and sig.sender_authenticated and sig.sender_domain
        ),
        "",
    )


def _funding_outcome_line(
    application: Application,
    signals: Sequence[MailSignal],
    *,
    linked_award_outcomes: Sequence[str] = (),
    funded_with_application: bool = False,
) -> str:
    if application.funding_outcome:
        label = _award_label(application.funding_outcome)
        if label:
            src = (
                application.funding_outcome_source
                or application.outcome_source
                or Application.OutcomeSource.PERSON
            )
            domain = (
                _mail_funding_domain(application, signals)
                if src == Application.OutcomeSource.MAIL
                else ""
            )
            source = _source_text(src, domain)
            return f"{label} — {source}" if source else label
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
    lost_outcomes = (Application.Outcome.REJECTED, Application.Outcome.WITHDRAWN)
    if (
        linked_award_outcomes
        and not funded_with_application
        and all(o in lost_outcomes for o in linked_award_outcomes)
    ):
        if Application.Outcome.REJECTED in linked_award_outcomes:
            return "Scholarship: not awarded"
        return "Scholarship: withdrawn"
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


def _apply(title: str, start_url: str) -> Button | None:
    # Guidance spec D2/§3: the extension opens the portal page with its panel.
    return Button(f"Apply to {title}", start_url, "post", apply=True) if start_url else None


def _button(
    column: Column, *, has_portal: bool, start_url: str, portal_url: str,
    programme_url: str, documents_url: str, missing: tuple[str, ...], title: str,
    closed: bool = False,
) -> Button | None:
    """One main button by column (spec §4)."""
    if column is Column.TO_START:
        if not has_portal:
            return Button("Open programme page", programme_url) if programme_url else None
        return None if closed else _apply(title, start_url)
    if column is Column.IN_PROGRESS:
        if not has_portal:
            return Button("Open programme page", programme_url) if programme_url else None
        return None if closed else _apply(title, start_url)
    if column in (Column.SUBMITTED, Column.CONFIRMED) and missing:
        return Button("Submit document", documents_url)
    return Button("Open portal", portal_url) if portal_url else None


def _read(application: Application, signal: MailSignal) -> str:
    return signal.funding_outcome if is_funding_application(application) else signal.outcome


def _funding_line(award: RecommendationCandidate) -> FundingLine:
    card = award.funding_card or {}
    return FundingLine(
        award.program_name,
        _covers(card),
        "; ".join(str(a) for a in card.get("amounts", [])),
        duration=str(card.get("duration_text") or ""),
        deadline=str(card.get("deadline") or ""),
        source_url=https_only(award.evidence.source_url),
        source_domain=award.evidence.source_domain,
        last_checked=award.evidence.last_checked_at,
    )


def _chance_line(
    application: Application,
    candidate: RecommendationCandidate | None,
    *,
    awards: Sequence[RecommendationCandidate],
    mandatory: bool,
    linked_award_outcomes: Sequence[str] = (),
    funded_with_application: bool = False,
    home_country: str = "",
) -> str:
    if candidate is None or candidate.estimated_chance_pct is None or application.outcome:
        return ""
    if candidate.opportunity_id is not None:
        return candidate.format_chance_line()

    won_outcomes = (Application.Outcome.ADMITTED, Application.Outcome.ADMITTED_CONDITIONAL)
    lost_outcomes = (Application.Outcome.REJECTED, Application.Outcome.WITHDRAWN)
    funding_already_won = application.funding_outcome in won_outcomes or any(
        o in won_outcomes for o in linked_award_outcomes
    )
    funding_all_lost = (
        not funding_already_won
        and (
            (
                application.funding_outcome in lost_outcomes
                and (
                    not linked_award_outcomes
                    or all(o in lost_outcomes for o in linked_award_outcomes)
                )
            )
            or (
                bool(linked_award_outcomes)
                and not funded_with_application
                and all(o in lost_outcomes for o in linked_award_outcomes)
                and not application.funding_outcome
            )
        )
    )
    if funding_already_won:
        funded_pct: int | None = int(candidate.estimated_chance_pct)
    elif funding_all_lost:
        funded_pct = None
    else:
        funded_pct = candidate.estimated_funded_chance_pct
        if funded_pct is None:
            selective_award_pcts = [
                award.estimated_chance_pct
                for award in awards
                if funds(award, candidate, home_country=home_country)
                and (award.funding_card or {}).get("route") != "AUTOMATIC_ON_ADMISSION"
                and award.estimated_chance_pct is not None
            ]
            funded_pct = joint_admission_and_funding_chance_pct(
                candidate.estimated_chance_pct, selective_award_pcts
            )
    cannot_afford = (
        not funding_all_lost
        and (
            candidate.cannot_afford_without_scholarship
            or (
                mandatory
                and not candidate.funding_gap_is_placeholder
                and candidate.funding_gap > (candidate.self_funded or Decimal("0"))
            )
        )
    )
    return candidate.format_chance_line(
        funded_chance_pct=funded_pct,
        cannot_afford=cannot_afford,
    )


def build_card(
    application: Application,
    *,
    kit: ApplicationKit,
    table: Table,
    signals: Sequence[MailSignal],
    awards: Sequence[RecommendationCandidate],
    counselor_view: bool,
    now: datetime,
    mandatory: bool = False,
    student_zone: str = "",
    rates: RateTable | None = None,
    home: str = "",
    linked_award_titles: Sequence[str] = (),
    linked_award_outcomes: Sequence[str] = (),
    funded_with_application: bool = False,
    profile_snapshot: object | None = None,
    home_country: str = "",
) -> Card:
    candidate = application.candidate
    column = column_for(application)
    conditions = _conditions(application, profile_snapshot=profile_snapshot, today=now.date())
    is_programme = candidate is not None and candidate.opportunity_id is None
    eligibility_warnings: tuple[str, ...] = ()
    if (
        is_programme
        and application.state not in (Application.State.SUBMITTED, Application.State.CONFIRMED)
        and not application.outcome
        and candidate is not None
        and candidate.eligibility_status == RecommendationCandidate.EligibilityStatus.NOT_ELIGIBLE
    ):
        eligibility_warnings = (
            "Eligibility warning: your updated profile no longer meets this"
            " programme's requirements",
        )
    missing = (*table.missing_for(application.id), *conditions, *eligibility_warnings)
    form = application.portal_form
    portal_url = https_only(form.form_url) if form is not None else ""
    programme_url = https_only(candidate.evidence.source_url) if candidate is not None else ""
    student_id = application.student_id
    documents_url = (
        f"/counselor/students/{student_id}/#application-{application.id}"
        if counselor_view
        else f"/student/documents/#application-{application.id}"
    )
    closed = final_passed(application, now)
    counted = counting_deadline(application, mandatory=mandatory)
    deadline = counted.at if counted is not None else None
    # Untrusted mail is never presented as established: it contributes only its badge.
    trusted = [signal for signal in signals if signal.trusted]
    evidence = application.outcome_evidence
    fee = candidate.application_fee if candidate is not None else None
    fee_currency = candidate.application_fee_currency if candidate is not None else ""
    fee_text = approx(fee, fee_currency, rates, home) if fee else ""
    # A decided programme's fee is no longer a bet on a result (§7.1).
    _position, risk_line = ("", "") if application.outcome else position(
        mandatory=mandatory,
        fee=fee,
        fee_state=application.fee_state,
        fee_text=fee_text,
        linked_award_titles=linked_award_titles,
        funded_with_application=funded_with_application,
    )
    return Card(
        application_id=application.id,
        title=application.title,
        institution=candidate.institution_name if candidate is not None else "",
        country=candidate.country_code if candidate is not None else "",
        column=column,
        created_at=application.created_at,
        deadline=deadline,
        deadline_local=_local(
            deadline, counted.zone if counted is not None else application.deadline_timezone
        ),
        deadline_text=(
            both_zones(deadline, counted.zone, student_zone)
            if counted is not None and deadline is not None else ""
        ),
        deadline_wording=counted.wording if counted is not None else "",
        closed=closed,
        pre_checks=pre_checks(application, student_zone),
        days_left=(deadline - now).days if deadline is not None else None,
        documents=table.counts_for(application.id),
        answers=(sum(1 for q in kit.questions if not q.missing), len(kit.questions)),
        funding=(
            (_funding_line(candidate),)
            if candidate is not None and candidate.opportunity_id is not None
            else tuple(
                _funding_line(award)
                for award in awards
                if is_programme
                and candidate is not None
                and funds(award, candidate, home_country=home_country)
            )
        ),
        funding_outcome_line=(
            ""
            if is_funding_application(application)
            else _funding_outcome_line(
                application,
                signals,
                linked_award_outcomes=linked_award_outcomes,
                funded_with_application=funded_with_application,
            )
        ),
        gap=(
            f"{candidate.funding_gap} {candidate.currency}"
            if candidate is not None and not candidate.funding_gap_is_placeholder
            else ""
        ),
        fee=fee,
        fee_currency=fee_currency,
        fee_text=fee_text,
        risk_line=risk_line,
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
            title=application.title,
            closed=closed,
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
        is_award=candidate is not None and candidate.opportunity_id is not None,
        notice_line=(
            n.card_line if (n := notice_for(candidate.country_code if candidate else "")) else ""
        ),
        requirements=tuple(str(r) for r in application.kit_requirements or ()),
        source_url=programme_url,
        source_domain=candidate.evidence.source_domain if candidate is not None else "",
        last_checked=candidate.evidence.last_checked_at if candidate is not None else None,
        fee_state=application.fee_state,
        fee_paid_url=(
            action_url(counselor_view, "fee_paid", student_id, application.id)
            # A scholarship card copies no fee, so it is always UNKNOWN; a paid
            # button on every scholarship would be noise (programmes only).
            if application.fee_state in PAYABLE and (candidate is None or is_programme)
            else ""
        ),
        chance_line=_chance_line(
            application,
            candidate,
            awards=awards,
            mandatory=mandatory,
            linked_award_outcomes=linked_award_outcomes,
            funded_with_application=funded_with_application,
            home_country=home_country,
        ),
        funding_outcome=application.funding_outcome,
        has_bundled_funding=bool(
            is_programme
            and (
                funded_with_application
                or application.funding_outcome
                or (candidate is not None and candidate.estimated_funded_chance_pct is not None)
            )
        ),
    )


def _parse_board_snapshot(snapshot: object, *, student_id: UUID) -> object | None:
    if not isinstance(snapshot, dict):
        return None
    snap_copy = dict(snapshot)
    if not snap_copy.get("weights"):
        snap_copy.pop("weights", None)
    try:
        return StudentProfileSnapshot.model_validate(snap_copy)
    except ValidationError as exc:
        logger.warning(
            "dashboard.board._parse_board_snapshot fallback for student %s (%d errors: %s)",
            student_id,
            exc.error_count(),
            [(e.get("loc"), e.get("type")) for e in exc.errors()],
        )
    raw_lang = snapshot.get("language_evidence")
    raw_acad = snapshot.get("academic_history")
    if not isinstance(raw_lang, list) and not isinstance(raw_acad, list):
        return None
    lang_items: list[object] = []
    for item in raw_lang if isinstance(raw_lang, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            lang_items.append(LanguageEvidence.model_validate(item))
        except ValidationError:
            lang_items.append(SimpleNamespace(**item))
    acad_items = [
        SimpleNamespace(**item)
        for item in (raw_acad if isinstance(raw_acad, list) else [])
        if isinstance(item, dict)
    ]
    return SimpleNamespace(
        language_evidence=tuple(lang_items),
        academic_history=tuple(acad_items),
        nationality=str(snapshot.get("nationality") or ""),
        country_of_residence=str(snapshot.get("country_of_residence") or ""),
        funding_dependency=str(snapshot.get("funding_dependency") or ""),
    )


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
    profile = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    # The money below reads `snapshot` too: plan 4's funding_mandatory(student)
    # replaces only the `mandatory =` line, never these two.
    snapshot = profile.snapshot if profile else None
    parsed_snapshot = _parse_board_snapshot(snapshot, student_id=student.id)
    mandatory = (snapshot or {}).get("funding_dependency") == "MANDATORY"
    home_country = str(
        (snapshot or {}).get("nationality")
        or (snapshot or {}).get("country_of_residence")
        or ""
    )
    home = home_currency(str((snapshot or {}).get("country_of_residence") or ""))
    rates = latest_table()
    links = list(
        ApplicationLink.objects.filter(from_app__in=applications).values_list(
            "from_app_id", "to_app_id"
        )
    )
    lines = award_lines_for(applications)
    # Only scholarships whose result is not in yet: one won or refused no
    # longer decides whether the fee is at risk (WAITLISTED is still waiting).
    pending = {
        application.id: application.title
        for application in applications
        if application.outcome in ("", Application.Outcome.WAITLISTED)
    }
    app_outcomes = {application.id: application.outcome for application in applications}
    # (award card, programme card): the scholarships a programme's fee rides on.
    linked_awards: dict[UUID, list[str]] = {}
    linked_award_outcomes: dict[UUID, list[str]] = {}
    for award_id, programme_id in links:
        if award_id in pending:
            linked_awards.setdefault(programme_id, []).append(pending[award_id])
        if award_id in app_outcomes:
            linked_award_outcomes.setdefault(programme_id, []).append(app_outcomes[award_id])
    kits = build_kits_for_board(student, applications)
    cards = [
        build_card(
            application,
            # Only the packet issues an address; reading the board writes nothing.
            kit=kits[application.id],
            table=table,
            signals=by_application.get(application.id, []),
            awards=awards,
            counselor_view=counselor_view,
            now=now,
            mandatory=mandatory,
            student_zone=student.timezone,
            rates=rates,
            home=home,
            linked_award_titles=tuple(linked_awards.get(application.id, ())),
            linked_award_outcomes=tuple(linked_award_outcomes.get(application.id, ())),
            funded_with_application=any(
                line.kind in WITH_APPLICATION for line in lines.get(application.id, ())
            ),
            profile_snapshot=parsed_snapshot,
            home_country=home_country,
        )
        for application in applications
    ]
    open_lanes, done = lanes_for(
        cards,
        links,
        page_url=lambda key: action_url(counselor_view, "programme", student.id, key),
    )
    open_lanes = tuple(
        replace(lane, award_lines=tuple(
            replace(line, add_url=action_url(counselor_view, "add", student.id, line.candidate_id))
            if line.kind == "ASK" else line
            # A closed lane has nothing left to do: no "Yes, add" either.
            for line in lines.get(lane.key, [])
            if not (line.kind == "ASK" and lane.lead.closed)
        ))
        for lane in open_lanes
    )
    budget_money = money_from(snapshot, "application_budget")
    budget = budget_line(
        budget=budget_money,
        stretch=money_from(snapshot, "budget_stretch"),
        cards=cards,
        table=rates,
        home=home,
    )
    converted = any(card.converted for card in cards) or (budget is not None and budget.converted)
    return Board(
        lanes=open_lanes,
        done=done,
        rates=rates,
        home=home,
        rate_note=rate_note(rates) if converted else "",
        budget=budget,
        budget_url=action_url(counselor_view, "budget", student.id),
        budget_set=budget_money is not None,
    )


def overrun_for(
    student: Membership, candidate: RecommendationCandidate, *, for_counselor: bool = False
) -> Overrun | None:
    """The over-budget check every Add and swap-in shares, and the counsellor's
    refusal (owner 2026-10-14). None: go ahead, no page.

    A scholarship copies no fee (owner question 1), so it has nothing to weigh.
    A candidate already on the board is counted there already: checking it
    again would count its fee twice."""
    if candidate.opportunity_id is not None:
        return None
    if Application.objects.filter(student=student, candidate=candidate).exists():
        return None
    board = board_for(student)
    overrun = over_budget(
        fee=candidate.application_fee,
        currency=candidate.application_fee_currency,
        line=board.budget,
        budget_set=board.budget_set,
        table=board.rates,
        home=board.home,
    )
    if overrun is not None and for_counselor:
        overrun = replace(overrun, who=student.display_name)
    return overrun
