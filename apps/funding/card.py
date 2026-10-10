"""The award card's own fields -- what the reader owes the pack (spec 10.4).

Two constructors and one judgement. `award_card` reads a catalogue row and its
benefits; `apps.research.funding_reader.card_of` builds the same value from a
decision nothing has written yet, so the 58-host measurement and the pack count
a card the same way. `card_fill` is the judgement, per field:

- FILLED -- the page states it and the readings agreed;
- UNCONFIRMED -- the readings split; shown beside its quote, never filtered on;
- UNSTATED -- read, and the page says nothing;
- NOT_READ -- no reader for that field has run on this row;
- NOT_APPLICABLE -- a contact on an award that comes with the place.

Pure, like facts.py: rows in, a value out, no query. Rendering the card is the
presentation layer's (CLAUDE.md, "Frontend and design"); this is the data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from apps.funding.models import FundingBenefit, FundingOpportunity

FieldState = Literal["FILLED", "UNCONFIRMED", "UNSTATED", "NOT_READ", "NOT_APPLICABLE"]
CARD_FIELDS = ("amount", "duration", "timing", "cycle", "required_documents", "contact")
#: The one route on which nobody is written to: the money comes with the place.
_NO_CONTACT_ROUTE = "AUTOMATIC_ON_ADMISSION"


@dataclass(frozen=True)
class AmountLine:
    kind: str
    amount_text: str
    amount: Decimal | None
    currency: str | None
    period: str
    bound: str
    quote: str


@dataclass(frozen=True)
class AwardCard:
    route: str
    tuition: str
    living: str
    amounts: tuple[AmountLine, ...]
    duration_text: str
    duration_months: int | None
    timing: str
    cycle: str
    unconfirmed: tuple[str, ...]
    quotes: tuple[tuple[str, str], ...] = ()
    #: Part B of the build-item-13 plan fills these; until then NOT_READ.
    required_documents: tuple[str, ...] = ()
    documents_read: bool = False
    contact_email: str = ""
    contact_url: str = ""
    contact_quote: str = ""
    contact_read: bool = False


def _split(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split(";") if part)


def amount_lines(benefits: Sequence[FundingBenefit]) -> tuple[AmountLine, ...]:
    """The benefits a reader wrote a figure for, in a stable order."""
    return tuple(sorted(
        (
            AmountLine(
                kind=benefit.kind, amount_text=benefit.amount_text, amount=benefit.amount,
                currency=benefit.currency, period=benefit.period,
                bound=benefit.amount_bound, quote=benefit.amount_quote,
            )
            for benefit in benefits
            if benefit.amount_text
        ),
        key=lambda line: (line.kind, line.amount_text),
    ))


def award_card(award: FundingOpportunity, benefits: Sequence[FundingBenefit]) -> AwardCard:
    """The card a catalogue row carries. `benefits` are the row's own, fetched by the caller."""
    return AwardCard(
        route=award.route,
        tuition=award.tuition or "UNSTATED",
        living=award.living or "UNSTATED",
        amounts=amount_lines(benefits),
        duration_text=award.duration_text,
        duration_months=award.duration_months,
        timing=award.timing or "UNSTATED",
        cycle=award.cycle or "UNSTATED",
        unconfirmed=_split(award.unconfirmed),
        quotes=tuple(sorted(award.card_quotes.items())),
    )


def _state(name: str, filled: bool, card: AwardCard) -> FieldState:
    """A value written wins over a split elsewhere: a blanked value is never written."""
    if filled:
        return "FILLED"
    return "UNCONFIRMED" if name in card.unconfirmed else "UNSTATED"


def card_fill(card: AwardCard) -> dict[str, FieldState]:
    """What the card says about each of its fields.

    A FULL coverage level is a stated amount -- "full tuition" is what the page
    printed, and it is the amount a student reads -- while PARTIAL with no
    figure is not: "a partial waiver" tells nobody how much.
    """
    contact: FieldState
    if card.route == _NO_CONTACT_ROUTE:
        contact = "NOT_APPLICABLE"
    elif not card.contact_read:
        contact = "NOT_READ"
    else:
        contact = _state("contact", bool(card.contact_email or card.contact_url), card)
    return {
        "amount": _state(
            "amount", bool(card.amounts) or "FULL" in (card.tuition, card.living), card
        ),
        "duration": _state("duration", bool(card.duration_text), card),
        "timing": _state("timing", card.timing != "UNSTATED", card),
        "cycle": _state("cycle", card.cycle != "UNSTATED", card),
        "required_documents": (
            _state("required_documents", bool(card.required_documents), card)
            if card.documents_read
            else "NOT_READ"
        ),
        "contact": contact,
    }


def card_values(card: AwardCard) -> dict[str, str]:
    """Each filled field as one line a person checks against the page (Task 12)."""
    amounts = "; ".join(
        f"{line.amount_text} [{line.kind} {line.period} {line.bound}"
        + (f" = {line.amount} {line.currency}]" if line.amount is not None else ", no number]")
        for line in card.amounts
    )
    if not amounts and "FULL" in (card.tuition, card.living):
        amounts = f"tuition {card.tuition}, living {card.living}"
    return {
        "amount": amounts,
        "duration": card.duration_text
        + (f" = {card.duration_months} months" if card.duration_months else ""),
        "timing": card.timing,
        "cycle": card.cycle,
        "required_documents": " | ".join(card.required_documents),
        "contact": card.contact_email or card.contact_url,
    }
