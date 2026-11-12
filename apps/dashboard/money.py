"""Money on the board (lanes spec §7.1, §7.5, §7.6). Pure: no queries.

Each amount is its original currency first, then "≈ N AZN" at the stored CBAR
rate. A currency the table lacks, or no table at all, shows the original
alone: a guessed figure is worse than an unconverted one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from apps.accounts.schemas import Money
from apps.funding.fx import (
    BANK_MARGIN,
    RateTable,
    UnconvertibleCurrency,
    convert,
    home_currency_for,
)

if TYPE_CHECKING:
    from .board import Card

#: Award lines whose funding comes with the programme's own application (§2):
#: nothing separate to win, so the fee is not at risk on it (§7.1 "Safe").
WITH_APPLICATION: frozenset[str] = frozenset({"AUTOMATIC", "SAME_APPLICATION", "COMBINED"})

Position = Literal["SAFE", "AT_RISK", ""]


def whole(amount: Decimal, *, up: bool = False) -> str:
    """A home-currency figure in whole units: totals and "≈" parts never show cents.

    ``up`` rounds a floor or a shortfall upward, so a refusal never names a
    figure that the student could type and still be refused at (150.40 paid
    reads "151", not "150")."""
    rounding = ROUND_CEILING if up else ROUND_HALF_UP
    return str(amount.quantize(Decimal("1"), rounding=rounding))


def home_currency(country_of_residence: str) -> str:
    """The student's home currency (§7.6: per country; AZN at launch). "" when unknown."""
    return home_currency_for(country_of_residence) or ""


def in_home(amount: Decimal, currency: str, table: RateTable | None, home: str) -> Decimal | None:
    """``amount`` in the home currency, or None when it cannot be converted honestly."""
    if not home:
        return None
    if currency == home:
        return amount
    if table is None:
        return None
    try:
        return convert(amount, currency, home, table)
    except UnconvertibleCurrency:
        return None


def approx(amount: Decimal, currency: str, table: RateTable | None, home: str) -> str:
    original = f"{amount} {currency}"
    if currency == home:
        return original
    converted = in_home(amount, currency, table, home)
    return original if converted is None else f"{original} ≈ {whole(converted)} {home}"


def rate_note(table: RateTable | None) -> str:
    if table is None:
        return ""
    day = table.retrieved_on
    via = (
        ", via the ECB's euro rate for currencies CBAR doesn't publish"
        if table.cross
        else ""
    )
    return (
        f"Converted at the {table.source} rate of {day.day} {day:%b}{via}; "
        "your bank may charge more"
    )


def position(
    *,
    mandatory: bool,
    fee: Decimal | None,
    fee_state: str,
    fee_text: str,
    linked_award_titles: Sequence[str],
    funded_with_application: bool,
) -> tuple[Position, str]:
    """§7.1's positions this plan can tell apart, and the card's sentence.

    "Wait, then pay" needs a result date and a fee deadline nobody writes yet
    (plan 3b), so a fee due on a separate scholarship's result is always "Pay
    first, at risk" here -- the spec's own rule when "the result date isn't
    stated". Only a MANDATORY student gets a position.
    """
    if not mandatory:
        return "", ""
    if funded_with_application or fee == 0:
        return "SAFE", ""
    if fee is None or fee_state != "OPEN" or not linked_award_titles:
        return "", ""
    awards = " or ".join(linked_award_titles)
    return "AT_RISK", f"{fee_text} at risk: if {awards} isn't won, you can't afford this programme."


#: Fees counted as committed while unpaid (§7.5). HELD joins as "on hold" in plan 3b.
COMMITTED = frozenset({"OPEN", "RELEASED"})


def money_from(snapshot: Mapping[str, object] | None, key: str) -> Money | None:
    """A Money answer from a stored profile, or None. A short-form profile's
    budget is a bare number with no currency, so it cannot be shown in AZN."""
    value = (snapshot or {}).get(key)
    if not isinstance(value, dict):
        return None
    try:
        return Money.model_validate(value)
    except ValidationError:
        return None


def _fees(count: int, reason: str) -> str:
    return f"{count} fee{'s' if count != 1 else ''} {reason} — not counted"


@dataclass(frozen=True)
class BudgetLine:
    """The board's money line (§7.5, §7.7), in the home currency. Never stored."""

    currency: str
    plan: Decimal
    extra: Decimal | None
    paid: Decimal
    committed: Decimal
    not_known: int
    no_rate: int
    converted: bool

    @property
    def free(self) -> Decimal:
        return max(Decimal("0"), self.plan - self.paid - self.committed)

    @property
    def used_from_extra(self) -> Decimal:
        return max(Decimal("0"), self.paid + self.committed - self.plan)

    @property
    def text(self) -> str:
        parts = [
            f"Application budget {whole(self.plan)} {self.currency}",
            f"Paid {whole(self.paid)}",
            f"Committed {whole(self.committed)}",
            f"Free {whole(self.free)}" + (" (≈, see note)" if self.converted else ""),
        ]
        if self.not_known:
            parts.append(_fees(self.not_known, "not known"))
        if self.no_rate:
            parts.append(_fees(self.no_rate, "without a rate yet"))
        return " · ".join(parts)

    @property
    def stretch_text(self) -> str:
        if not self.extra:
            return ""
        return (
            f"Plan {whole(self.plan)} {self.currency} · Extra allowed for exceptional cases: "
            f"up to {whole(self.extra)} · Used from extra: {whole(self.used_from_extra)}"
        )


def counts_toward_budget(card: Card) -> bool:
    """A fee that is paid, or committed and still live (§7.5)."""
    live = not card.outcome and not card.closed
    return bool(card.fee) and (card.fee_state == "PAID" or (card.fee_state in COMMITTED and live))


def budget_line(
    *,
    budget: Money | None,
    stretch: Money | None,
    cards: Sequence[Card],
    table: RateTable | None,
    home: str,
) -> BudgetLine | None:
    """None when the budget itself cannot be shown in the home currency:
    nothing is better than a wrong figure."""
    if budget is None:
        return None
    plan = in_home(budget.amount, budget.currency, table, home)
    if plan is None:
        return None
    extra = in_home(stretch.amount, stretch.currency, table, home) if stretch else None
    paid = committed = Decimal("0")
    not_known = no_rate = 0
    converted = budget.currency != home or (
        stretch is not None and extra is not None and stretch.currency != home
    )
    for card in cards:
        live = not card.outcome and not card.closed
        # A programme (or accepted offer) with no stated fee, portal recorded
        # or not; a scholarship copies no fee and is not counted at all.
        if card.fee_state == "UNKNOWN" and not card.fee and not card.is_award and live:
            not_known += 1
            continue
        if not counts_toward_budget(card) or not card.fee:
            continue
        amount = in_home(card.fee, card.fee_currency, table, home)
        if amount is None:
            no_rate += 1
            continue
        converted = converted or card.fee_currency != home
        if card.fee_state == "PAID":
            paid += amount
        else:
            committed += amount
    return BudgetLine(home, plan, extra, paid, committed, not_known, no_rate, converted)


OverKind = Literal["OVER", "STRETCH", "NO_RATE", "UNKNOWN", "BUDGET_NO_RATE"]


@dataclass(frozen=True)
class Overrun:
    """Why adding a programme needs the student's tick (owner 2026-10-14).
    Amounts carry their unit ("40 AZN"); "about" because they include the
    bank margin."""

    kind: OverKind
    fee_text: str = ""
    free: str = ""
    over: str = ""
    extra: str = ""
    #: The student's name when a counsellor is the one adding; "" for the student.
    who: str = ""

    @property
    def title(self) -> str:
        # Only OVER and STRETCH are known to be over; the rest cannot be checked.
        if self.kind not in ("OVER", "STRETCH"):
            return f"We can't check this against {self.who}'s budget" if self.who else (
                "We can't check this against your budget"
            )
        return f"This is over {self.who}'s application budget" if self.who else (
            "This is over your application budget"
        )

    @property
    def body(self) -> str:
        who = self.who
        budget = f"{who}'s budget" if who else "your budget"
        fee = f"The application fee is {self.fee_text}."
        cannot_tell = f"so we can't tell whether it fits {budget}."
        if self.kind == "OVER":
            if who:
                return (
                    f"{fee} {who} has {self.free} left in their budget, so adding it puts "
                    f"them about {self.over} over."
                )
            return (
                f"{fee} You have {self.free} left in your budget, so adding it puts you "
                f"about {self.over} over."
            )
        if self.kind == "STRETCH":
            if who:
                return (
                    f"{fee} It doesn't fit {who}'s plan, but it fits the extra {who} allowed: "
                    f"it uses about {self.over} of their {self.extra} extra."
                )
            return (
                f"{fee} It doesn't fit your plan, but it fits the extra you allowed: it uses "
                f"about {self.over} of your {self.extra} extra."
            )
        if self.kind == "NO_RATE":
            return f"{fee} We can't convert this currency yet, {cannot_tell}"
        if self.kind == "BUDGET_NO_RATE":
            return f"{fee} We can't convert {budget}'s currency yet, {cannot_tell}"
        return f"We don't know this programme's application fee yet, {cannot_tell}"

    @property
    def tick(self) -> str:
        if self.kind == "OVER":
            if self.who:
                return f"I understand this takes {self.who} about {self.over} over their budget"
            return f"I understand this takes me about {self.over} over my budget"
        if self.kind == "STRETCH":
            if self.who:
                return f"Use about {self.over} from {self.who}'s extra"
            return f"Use about {self.over} from my extra"
        return "Add it anyway"


def over_budget(
    *,
    fee: Decimal | None,
    currency: str,
    line: BudgetLine | None,
    budget_set: bool,
    table: RateTable | None,
    home: str,
) -> Overrun | None:
    """None when the fee fits what is free (fee x BANK_MARGIN <= free), else why
    the student must confirm. A stated 0 always fits. With no budget at all
    (``budget_set`` False: a short-form profile) there is nothing to exceed;
    a budget that exists but cannot be compared still asks."""
    if fee == 0 or (line is None and not budget_set):
        return None
    if fee is None:
        return Overrun("UNKNOWN")
    fee_text = approx(fee, currency, table, home)
    if line is None:
        return Overrun("BUDGET_NO_RATE", fee_text)
    amount = in_home(fee, currency, table, home)
    if amount is None:
        return Overrun("NO_RATE", fee_text)
    over = amount * BANK_MARGIN - line.free
    if over <= 0:
        return None
    unit = line.currency
    room = (line.extra - line.used_from_extra) if line.extra else None
    return Overrun(
        "STRETCH" if room is not None and over <= room else "OVER",
        fee_text,
        free=f"{whole(line.free)} {unit}",
        over=f"{whole(over, up=True)} {unit}",
        extra=f"{whole(line.extra)} {unit}" if line.extra else "",
    )
