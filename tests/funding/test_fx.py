from datetime import date
from decimal import Decimal

import pytest

from apps.funding.fx import RateTable, UnconvertibleCurrency, convert


def test_round_money_rounds_half_up_at_the_exact_boundary() -> None:
    from apps.funding.fx import round_money

    assert round_money(Decimal("500.025")) == Decimal("500.03")


TABLE = RateTable(
    base="EUR",
    rates={"EUR": Decimal("1"), "USD": Decimal("1.0850"), "INR": Decimal("94.5000")},
    source="ECB",
    retrieved_on=date(2026, 8, 14),
)

TABLE_WITH_AZN = RateTable(
    base="EUR",
    rates={
        "EUR": Decimal("1"),
        "USD": Decimal("1.0850"),
        "INR": Decimal("94.5000"),
        "AZN": Decimal("1.8450"),
    },
    source="TEST",
    retrieved_on=date(2026, 8, 14),
)


def test_converting_from_the_base_currency_uses_the_rate_directly() -> None:
    assert convert(Decimal("100.00"), "EUR", "USD", TABLE) == Decimal("108.50")


def test_converting_to_the_base_currency_inverts_the_rate() -> None:
    assert convert(Decimal("108.50"), "USD", "EUR", TABLE) == Decimal("100.00")


def test_cross_conversion_goes_through_the_base_currency() -> None:
    assert convert(Decimal("1085.00"), "USD", "INR", TABLE) == Decimal("94500.00")


def test_converting_a_currency_to_itself_is_the_identity() -> None:
    assert convert(Decimal("42.42"), "USD", "USD", TABLE) == Decimal("42.42")


def test_an_unknown_currency_raises_rather_than_guessing() -> None:
    with pytest.raises(UnconvertibleCurrency):
        convert(Decimal("100.00"), "AZN", "EUR", TABLE)


def test_the_result_is_quantized_to_two_places() -> None:
    result = convert(Decimal("33.33"), "EUR", "INR", TABLE)
    assert result == result.quantize(Decimal("0.01"))


def test_presented_money_carries_its_rate_and_provenance() -> None:
    from apps.funding.fx import present

    shown = present(Decimal("1000.00"), "EUR", "AZN", TABLE_WITH_AZN)

    assert shown.currency == "AZN"
    assert shown.rate == Decimal("1.8450")
    assert shown.source == "TEST"
    assert shown.retrieved_on == date(2026, 8, 14)


def test_an_unknown_home_country_has_no_currency_rather_than_a_default() -> None:
    from apps.funding.fx import home_currency_for

    assert home_currency_for("AZ") == "AZN"
    assert home_currency_for("ZZ") is None


def test_the_identity_conversion_is_quantized_like_every_other_path() -> None:
    assert convert(Decimal("75.5555"), "USD", "USD", TABLE) == Decimal("75.56")


def test_presenting_a_currency_as_itself_does_not_require_a_rate_for_it() -> None:
    from apps.funding.fx import present

    shown = present(Decimal("50.00"), "GBP", "GBP", TABLE)

    assert shown.amount == Decimal("50.00")
    assert shown.currency == "GBP"
    assert shown.rate == Decimal("1")
