from decimal import Decimal
from pathlib import Path

import pytest

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

    assert table.rates["JPY"] == Decimal("0.010668")


def test_an_empty_body_is_rejected_rather_than_yielding_an_empty_table() -> None:
    with pytest.raises(ValueError):
        parse_ecb_daily(b"")
