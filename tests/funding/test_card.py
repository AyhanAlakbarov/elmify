"""What a card says about each of its fields. Pure; no database."""

from decimal import Decimal

from apps.funding.card import AmountLine, AwardCard, card_fill, card_values


def _card(**overrides):
    fields = dict(
        route="STUDENT_APPLIES_SEPARATELY", tuition="UNSTATED", living="UNSTATED", amounts=(),
        duration_text="", duration_months=None, timing="UNSTATED", cycle="UNSTATED",
        unconfirmed=(),
    )
    fields.update(overrides)
    return AwardCard(**fields)  # type: ignore[arg-type]


STIPEND = AmountLine(
    kind="STIPEND", amount_text="€1,200", amount=Decimal("1200"), currency="EUR",
    period="MONTHLY", bound="EXACT", quote="Scholars receive €1,200 per month.",
)


def test_an_empty_card_is_unstated_and_not_read_never_filled():
    assert card_fill(_card()) == {
        "amount": "UNSTATED", "duration": "UNSTATED", "timing": "UNSTATED",
        "cycle": "UNSTATED", "required_documents": "NOT_READ", "contact": "NOT_READ",
    }


def test_full_coverage_is_a_stated_amount_and_partial_is_not():
    assert card_fill(_card(tuition="FULL"))["amount"] == "FILLED"
    assert card_fill(_card(tuition="PARTIAL"))["amount"] == "UNSTATED"


def test_a_split_field_is_unconfirmed_not_unstated():
    assert card_fill(_card(unconfirmed=("timing",)))["timing"] == "UNCONFIRMED"


def test_a_written_amount_is_filled_even_beside_an_unconfirmed_one():
    assert card_fill(_card(amounts=(STIPEND,), unconfirmed=("amount",)))["amount"] == "FILLED"


def test_an_award_that_comes_with_the_place_needs_no_contact():
    assert card_fill(_card(route="AUTOMATIC_ON_ADMISSION"))["contact"] == "NOT_APPLICABLE"


def test_a_value_shows_the_printed_words_beside_the_number():
    values = card_values(_card(amounts=(STIPEND,), duration_text="24 months", duration_months=24))
    assert values["amount"] == "€1,200 [STIPEND MONTHLY EXACT = 1200 EUR]"
    assert values["duration"] == "24 months = 24 months"
