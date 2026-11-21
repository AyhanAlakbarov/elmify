"""One document list per student (lanes spec §10): every card's needs merged into one
entry per document, with the applications that need it, when it is first needed, and
whether what is held is still valid then.

`merge` is pure. `document_list` is the one function that reads, and it reads tenant
rows only: the requirement sentences are the cards' own copies (`kit_requirements`),
the referee facts the candidate's copy (`referee_requirements`). Never stored (spec §3.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from apps.dashboard.dates import counting_deadline, funding_mandatory
from apps.portals.models import Application, zone_named
from apps.portals.route_snapshot import read_snapshot

from .referee_needs import needs_for
from .table import EXPIRING, ROWS, SENDABLE, ApplicationNeeds, Held, needed_kinds, vouched

if TYPE_CHECKING:
    from apps.mailbox.models import MailSignal
    from apps.tenancy.models import Membership

_REFERENCE = "REFERENCE_LETTER"


@dataclass(frozen=True)
class CardNeeds:
    application_id: UUID
    title: str
    #: Kit requirements, vouched mail requests and offer conditions, in their own words.
    sentences: tuple[str, ...]
    #: How many reference letters the card's referee facts ask for; None when unstated.
    letters: int | None = None
    #: The card's counting deadline (dashboard/dates.counting_deadline) and its zone.
    deadline: datetime | None = None
    zone: str = ""


@dataclass(frozen=True)
class DocumentEntry:
    kind: str
    label: str
    #: The applications that need it, earliest deadline first.
    titles: tuple[str, ...]
    #: The ones that ask for a certified copy.
    certified: tuple[str, ...] = ()
    #: REFERENCE_LETTER only: the most letters any one application asks for.
    letters: int | None = None
    needed_by: str = ""
    held: bool = False
    validity: str = ""

    @property
    def headline(self) -> str:
        count = len(self.titles)
        return f"{self.label} — needed by {count} application{'s' if count != 1 else ''}"


def _day(at: datetime, zone: str) -> datetime:
    return at.astimezone(zone_named(zone) or UTC)


def _text(at: datetime, zone: str) -> str:
    local = _day(at, zone)
    return f"{local.day} {local:%b}"


def _by_deadline(card: CardNeeds) -> tuple[bool, datetime]:
    return (card.deadline is None, card.deadline or datetime.max.replace(tzinfo=UTC))


def merge(cards: Sequence[CardNeeds], held: Sequence[Held]) -> tuple[DocumentEntry, ...]:
    first = min((c.deadline for c in cards if c.deadline is not None), default=None)
    entries = []
    for kind, label in ROWS:
        needing: list[tuple[CardNeeds, bool]] = []
        for card in sorted(cards, key=_by_deadline):
            wanted = needed_kinds(ApplicationNeeds(card.application_id, card.title, card.sentences))
            if kind in wanted or (kind == _REFERENCE and card.letters):
                needing.append((card, wanted.get(kind, False)))
        if not needing:
            continue
        lead = needing[0][0]
        needed_by = ""
        if lead.deadline is not None:
            needed_by = f"needed by {_text(lead.deadline, lead.zone)} for {lead.title}"
            if lead.deadline == first:
                needed_by += " (your first deadline)"
        mine = [h for h in held if h.kind == kind and h.state in SENDABLE]
        entries.append(DocumentEntry(
            kind=kind,
            label=label,
            titles=tuple(card.title for card, _c in needing),
            certified=tuple(card.title for card, certified in needing if certified),
            letters=max((c.letters for c, _ in needing if c.letters), default=None)
            if kind == _REFERENCE else None,
            needed_by=needed_by,
            held=bool(mine),
            validity=_validity(label, mine, [card for card, _c in needing]),
        ))
    return tuple(entries)


def _validity(label: str, held: Sequence[Held], cards: Sequence[CardNeeds]) -> str:
    """The first card a held document's expiry falls before, in the spec's sentence.
    A document with no expiry date typed is never flagged: nothing is guessed."""
    expiring = [h for h in held if h.kind in EXPIRING and h.expires_on is not None]
    if not expiring:
        return ""
    expires = max(h.expires_on for h in expiring if h.expires_on is not None)
    for card in cards:
        if card.deadline is not None and _day(card.deadline, card.zone).date() > expires:
            return (
                f"Your {label.lower()} expires {expires.day} {expires:%b}; "
                f"{card.title} needs it valid on {_text(card.deadline, card.zone)}"
            )
    return ""


def _offer_conditions(application: Application) -> tuple[str, ...]:
    """A conditional offer's conditions (spec §10's "offer conditions"): recorded on the
    card only from trusted mail (portals/outcome.py), so each one is a need."""
    signal = application.outcome_evidence
    if application.outcome != Application.Outcome.ADMITTED_CONDITIONAL or signal is None:
        return ()
    raw = signal.outcome_conditions
    if not isinstance(raw, list):  # an erased signal's JSON is {}
        return ()
    return tuple(condition for condition in raw if isinstance(condition, str))


def document_list(
    student: Membership,
    applications: Sequence[Application],
    signals: Sequence[MailSignal],
    held: Sequence[Held],
) -> tuple[DocumentEntry, ...]:
    """The list from the student's own rows: the same applications, mail and held
    documents the by-application table is built from (views.page_context)."""
    asked: dict[UUID, list[str]] = {}
    for signal in signals:
        if signal.application_id is None:
            continue
        if signal.label == "DOCUMENT_REQUEST" and signal.document_name and vouched(signal):
            asked.setdefault(signal.application_id, []).append(signal.document_name)
    mandatory = funding_mandatory(student)
    cards = []
    for application in applications:
        if application.outcome == Application.Outcome.ADMITTED_CONDITIONAL:
            # A conditional offer needs its conditions and nothing else: no kit
            # requirement, no letter, no needed-by from a deadline already past.
            cards.append(CardNeeds(application.id, application.title,
                                   _offer_conditions(application)))
            continue
        if application.outcome:
            # Decided: nothing is needed for it any more (final review I2).
            continue
        candidate = application.candidate
        records = candidate.referee_requirements if candidate is not None else []
        snapshot = read_snapshot(application)
        need = needs_for(
            records if isinstance(records, list) else [],
            route_kind=snapshot.kind if snapshot is not None else "",
            award=candidate is not None and candidate.opportunity_id is not None,
        )
        counted = counting_deadline(application, mandatory=mandatory)
        cards.append(CardNeeds(
            application_id=application.id,
            title=application.title,
            sentences=(
                *(text for text in application.kit_requirements if isinstance(text, str)),
                *asked.get(application.id, []),
            ),
            letters=need.letters,
            deadline=counted.at if counted is not None else None,
            zone=counted.zone if counted is not None else "",
        ))
    return merge(cards, held)
