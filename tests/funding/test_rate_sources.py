from decimal import Decimal
from pathlib import Path

import pytest

from apps.funding.fx import convert
from apps.funding.rate_sources import parse_cbar_daily, parse_ecb_daily

FIXTURES = Path(__file__).parent / "fixtures"


def test_ecb_parses_into_a_eur_based_table() -> None:
    table = parse_ecb_daily((FIXTURES / "ecb_daily.xml").read_bytes())

    assert table.base == "EUR"
    assert table.source == "ECB"
    assert table.rates["EUR"] == Decimal("1")
    assert table.rates["USD"] > Decimal("0")


def test_ecb_does_not_cover_origin_currencies() -> None:
    table = parse_ecb_daily((FIXTURES / "ecb_daily.xml").read_bytes())

    assert "AZN" not in table.rates
    assert "KZT" not in table.rates


def test_cbar_parses_into_an_azn_based_table() -> None:
    table = parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes())

    assert table.base == "AZN"
    assert table.source == "CBAR"
    assert table.rates["AZN"] == Decimal("1")
    assert table.rates["EUR"] > Decimal("0")


def test_cbar_divides_by_nominal_for_rates_quoted_per_multiple_units() -> None:
    table = parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes())

    # The fixture quotes 100 JPY = 1.0668 AZN.
    assert convert(Decimal("100"), "JPY", "AZN", table) == Decimal("1.07")


def test_a_cbar_table_converts_the_right_way_round() -> None:
    """CBAR quotes 1 EUR = 1.9615 AZN. Stored as quoted, fx.convert read
    100 EUR as 50.98 AZN -- inverted, off by a factor of almost four."""
    table = parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes())

    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("196.15")
    assert convert(Decimal("196.15"), "AZN", "EUR", table) == Decimal("100.00")


def test_an_empty_body_is_rejected_rather_than_yielding_an_empty_table() -> None:
    with pytest.raises(ValueError):
        parse_ecb_daily(b"")
