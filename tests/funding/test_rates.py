from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from apps.funding.fx import RateTable, convert
from apps.funding.models import ExchangeRate
from apps.funding.rate_sources import parse_cbar_daily
from apps.funding.rates import latest_table, store

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def _table(day: date, eur: str = "0.5") -> RateTable:
    return RateTable(
        base="AZN",
        rates={"AZN": Decimal("1"), "EUR": Decimal(eur)},
        source="CBAR",
        retrieved_on=day,
    )


def test_a_stored_day_reads_back_as_the_same_table() -> None:
    assert store(_table(date(2026, 10, 8))) == 2

    table = latest_table(on=date(2026, 10, 8))

    assert table == _table(date(2026, 10, 8))
    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("200.00")


def test_storing_a_day_twice_keeps_one_row_per_currency_with_the_newer_rate() -> None:
    store(_table(date(2026, 10, 8)))
    store(_table(date(2026, 10, 8), eur="0.4"))

    assert ExchangeRate.objects.filter(day=date(2026, 10, 8)).count() == 2
    assert latest_table(on=date(2026, 10, 8)).rates["EUR"] == Decimal("0.4")


def test_the_newest_day_on_or_before_the_date_is_used() -> None:
    store(_table(date(2026, 10, 6), eur="0.4"))
    store(_table(date(2026, 10, 8)))

    assert latest_table(on=date(2026, 10, 7)).retrieved_on == date(2026, 10, 6)
    assert latest_table(on=date(2026, 10, 9)).retrieved_on == date(2026, 10, 8)


def test_nothing_stored_is_none_not_an_empty_table() -> None:
    """The first day: the spine's "No exchange-rate table is loaded" pack is
    the honest answer, and an empty table would raise inside convert()."""
    assert latest_table() is None


def test_a_real_cbar_quote_survives_storage() -> None:
    store(parse_cbar_daily((FIXTURES / "cbar_daily.xml").read_bytes()))

    table = latest_table(on=date(2026, 8, 14))

    assert table.source == "CBAR"
    assert convert(Decimal("100.00"), "EUR", "AZN", table) == Decimal("196.15")
    assert convert(Decimal("100"), "JPY", "AZN", table) == Decimal("1.07")


def test_the_web_tier_may_read_rates_and_never_write_them(db_cursor) -> None:
    """Not tenant data, so no RLS: the grant is the guard. Default privileges
    gave runtime_web full DML when the table was made; 0060's RunSQL takes the
    writes back. `has_table_privilege` evaluates the NAMED role, so the superuser
    cursor is honest here (tests/tenancy/test_catalog_grants.py does the same)."""
    for privilege, web in (
        ("SELECT", True), ("INSERT", False), ("UPDATE", False), ("DELETE", False),
    ):
        db_cursor.execute(
            "SELECT has_table_privilege('runtime_web', 'public.funding_exchangerate', %s), "
            "has_table_privilege('runtime_engine', 'public.funding_exchangerate', %s)",
            [privilege, privilege],
        )
        assert db_cursor.fetchone() == (web, True), privilege


def _ecb(day: date, **rates: str) -> RateTable:
    return RateTable(
        base="EUR",
        rates={"EUR": Decimal("1"), **{k: Decimal(v) for k, v in rates.items()}},
        source="ECB",
        retrieved_on=day,
    )


def test_a_currency_cbar_lacks_is_crossed_through_the_euro() -> None:
    store(_table(date(2026, 10, 8)))  # 1 AZN = 0.5 EUR
    store(_ecb(date(2026, 10, 8), MYR="5.0"))

    table = latest_table(on=date(2026, 10, 8))

    assert table.rates["MYR"] == Decimal("2.5")
    assert convert(Decimal("100"), "MYR", "AZN", table) == Decimal("40.00")
    assert table.cross == {"MYR"}
    assert table.source == "CBAR"


def test_a_currency_both_quote_keeps_cbars_value() -> None:
    store(_table(date(2026, 10, 8)))
    store(_ecb(date(2026, 10, 8), AZN="9", MYR="5.0"))

    table = latest_table(on=date(2026, 10, 8))

    assert table.rates["AZN"] == Decimal("1")
    assert table.cross == {"MYR"}


def test_without_ecb_rows_the_table_is_unchanged() -> None:
    store(_table(date(2026, 10, 8)))

    assert latest_table(on=date(2026, 10, 8)) == _table(date(2026, 10, 8))
    assert latest_table(on=date(2026, 10, 8)).cross == frozenset()


def test_without_a_cbar_euro_rate_nothing_is_crossed() -> None:
    store(RateTable(base="AZN", rates={"AZN": Decimal("1"), "USD": Decimal("0.6")},
                    source="CBAR", retrieved_on=date(2026, 10, 8)))
    store(_ecb(date(2026, 10, 8), MYR="5.0"))

    table = latest_table(on=date(2026, 10, 8))

    assert "MYR" not in table.rates
    assert table.cross == frozenset()


def test_an_ecb_day_after_the_date_is_ignored_and_an_older_one_used() -> None:
    store(_table(date(2026, 10, 8)))
    store(_ecb(date(2026, 10, 6), MYR="4.0"))
    store(_ecb(date(2026, 10, 9), MYR="9.0"))

    assert latest_table(on=date(2026, 10, 8)).rates["MYR"] == Decimal("2.0")
