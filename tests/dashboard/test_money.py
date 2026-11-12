from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.schemas import Money
from apps.dashboard.board import Card, Column
from apps.dashboard.money import (
    approx,
    budget_line,
    home_currency,
    money_from,
    position,
    rate_note,
    whole,
)
from apps.funding.fx import RateTable

RATES = RateTable(
    base="AZN",
    rates={"AZN": Decimal("1"), "EUR": Decimal("0.5"), "USD": Decimal("0.625")},
    source="CBAR",
    retrieved_on=date(2026, 10, 8),
)


def test_the_home_currency_follows_the_country_of_residence() -> None:
    assert home_currency("AZ") == "AZN"
    assert home_currency("") == ""


@pytest.mark.parametrize(
    ("amount", "currency", "table", "expected"),
    [
        (Decimal("100.00"), "EUR", RATES, "100.00 EUR ≈ 200 AZN"),
        (Decimal("85.00"), "USD", RATES, "85.00 USD ≈ 136 AZN"),
        (Decimal("50.00"), "AZN", RATES, "50.00 AZN"),
        # Review Focus 1: a currency the table lacks is never guessed at.
        (Decimal("120.00"), "ISK", RATES, "120.00 ISK"),
        # Review Focus 2: the first day, before any rate is stored.
        (Decimal("100.00"), "EUR", None, "100.00 EUR"),
    ],
)
def test_each_amount_is_the_original_then_about_so_much_in_azn(
    amount, currency, table, expected
) -> None:
    assert approx(amount, currency, table, "AZN") == expected


def test_a_floor_rounds_up_and_a_total_rounds_to_nearest() -> None:
    assert (whole(Decimal("150.40")), whole(Decimal("150.40"), up=True)) == ("150", "151")
    assert (whole(Decimal("150.50")), whole(Decimal("150.00"), up=True)) == ("151", "150")


def test_no_home_currency_shows_the_original_alone() -> None:
    assert approx(Decimal("100.00"), "EUR", RATES, "") == "100.00 EUR"


def test_the_rate_is_a_note_with_its_day() -> None:
    assert rate_note(RATES) == "Converted at the CBAR rate of 8 Oct; your bank may charge more"
    assert rate_note(None) == ""


_FEE = "85.00 EUR ≈ 170 AZN"


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        # Pay first, at risk: mandatory, a fee to pay, a separate scholarship card.
        (
            {},
            (
                "AT_RISK",
                f"{_FEE} at risk: if SI Scholarship isn't won, you can't afford this programme.",
            ),
        ),
        (
            {"linked_award_titles": ("SI Scholarship", "KTH Tuition waiver")},
            (
                "AT_RISK",
                f"{_FEE} at risk: if SI Scholarship or KTH Tuition waiver isn't won, "
                "you can't afford this programme.",
            ),
        ),
        # Safe: funding comes with the application, or there is no fee.
        ({"funded_with_application": True}, ("SAFE", "")),
        ({"fee": Decimal("0")}, ("SAFE", "")),
        # Not at risk: paid already, not known, or no separate scholarship to wait on.
        ({"fee_state": "PAID"}, ("", "")),
        ({"fee_state": "UNKNOWN", "fee": None}, ("", "")),
        ({"linked_award_titles": ()}, ("", "")),
        # IMPORTANT and OPTIONAL students see fees, never positions (§7.1).
        ({"mandatory": False}, ("", "")),
    ],
)
def test_the_position_line(fields, expected) -> None:
    arguments = {
        "mandatory": True,
        "fee": Decimal("85.00"),
        "fee_state": "OPEN",
        "fee_text": _FEE,
        "linked_award_titles": ("SI Scholarship",),
        "funded_with_application": False,
        **fields,
    }
    assert position(**arguments) == expected


NOW = datetime(2026, 10, 13, tzinfo=UTC)


def _card(fee=None, currency="EUR", state="OPEN", **overrides) -> Card:
    fields = dict(
        application_id=uuid4(), title="TUM M.Sc.", institution="TUM", country="DE",
        column=Column.TO_START, created_at=NOW, deadline=None, days_left=None,
        documents=(0, 0), answers=(0, 0), funding=(), funding_outcome_line="", gap="",
        fee=Decimal(fee) if fee is not None else None, fee_currency=currency, badges=(),
        missing=(), outcome_line="", offer=None, button=None, has_portal=True, portal_url="",
        kit_url="", documents_url="", outcome_url="", remove_url="", portal_record_url="",
        outcome="", conditions=(), fee_state=state,
    )
    fields.update(overrides)
    return Card(**fields)


def _azn(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="AZN")


def test_the_budget_line_reads_like_the_spec() -> None:
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN",
        cards=[_card("95.00", state="PAID"), _card("70.00"), _card(None, state="UNKNOWN")],
    )
    assert line.text == (
        "Application budget 500 AZN · Paid 190 · Committed 140 · Free 170 (≈, see note)"
        " · 1 fee not known — not counted"
    )
    assert line.stretch_text == ""


def test_with_a_stretch_the_line_shows_the_extra_and_what_is_used() -> None:
    line = budget_line(
        budget=_azn("400"), stretch=_azn("150"), table=RATES, home="AZN",
        cards=[_card("95.00", state="PAID"), _card("142.50")],
    )
    assert line.free == 0
    assert line.stretch_text == (
        "Plan 400 AZN · Extra allowed for exceptional cases: up to 150 · Used from extra: 75"
    )


def test_a_budget_in_eur_is_shown_in_azn() -> None:
    """Review Focus 3."""
    line = budget_line(
        budget=Money(amount=Decimal("250.00"), currency="EUR"), stretch=None, cards=[],
        table=RATES, home="AZN",
    )
    assert line.text == "Application budget 500 AZN · Paid 0 · Committed 0 · Free 500 (≈, see note)"


def test_a_budget_that_cannot_be_converted_shows_nothing() -> None:
    eur = Money(amount=Decimal("250.00"), currency="EUR")
    assert budget_line(budget=eur, stretch=None, cards=[], table=None, home="AZN") is None
    assert budget_line(budget=None, stretch=None, cards=[], table=RATES, home="AZN") is None


def test_a_fee_without_a_rate_is_not_counted_and_says_so() -> None:
    """Review Focus 1 and 2: an ISK fee, and a EUR fee before any rate is stored."""
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN", cards=[_card("90", "ISK")],
    )
    assert line.text.endswith("Free 500 · 1 fee without a rate yet — not counted")
    first_day = budget_line(
        budget=_azn("500"), stretch=None, table=None, home="AZN", cards=[_card("70.00")],
    )
    assert first_day.text == (
        "Application budget 500 AZN · Paid 0 · Committed 0 · Free 500"
        " · 1 fee without a rate yet — not counted"
    )


def test_an_unknown_programme_fee_is_not_known_with_or_without_a_portal() -> None:
    """Most programme cards have no portal yet (_ask_for_portal); a
    scholarship card copies no fee and is never a fee "not known"."""
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN",
        cards=[
            _card(None, state="UNKNOWN", has_portal=False),
            _card(None, state="UNKNOWN", is_award=True),
        ],
    )
    assert line.not_known == 1


def test_a_decided_or_closed_card_commits_nothing() -> None:
    line = budget_line(
        budget=_azn("500"), stretch=None, table=RATES, home="AZN",
        cards=[_card("70.00", outcome="WITHDRAWN"), _card("70.00", closed=True)],
    )
    assert (line.paid, line.committed) == (0, 0)


def test_a_short_form_budget_has_no_currency_so_no_money() -> None:
    assert money_from({"application_budget": "150"}, "application_budget") is None
    assert money_from(None, "application_budget") is None
    assert money_from(
        {"application_budget": {"amount": "150.00", "currency": "EUR"}}, "application_budget"
    ) == Money(amount=Decimal("150.00"), currency="EUR")


def test_the_rate_note_names_the_ecb_only_when_a_currency_was_crossed() -> None:
    from datetime import date
    from decimal import Decimal

    from apps.funding.fx import RateTable

    plain = RateTable(base="AZN", rates={"AZN": Decimal("1")}, source="CBAR",
                      retrieved_on=date(2026, 10, 8))
    crossed = RateTable(base="AZN", rates={"AZN": Decimal("1")}, source="CBAR",
                        retrieved_on=date(2026, 10, 8), cross=frozenset({"MYR"}))

    assert rate_note(plain) == "Converted at the CBAR rate of 8 Oct; your bank may charge more"
    assert rate_note(crossed) == (
        "Converted at the CBAR rate of 8 Oct, via the ECB's euro rate for currencies "
        "CBAR doesn't publish; your bank may charge more"
    )
