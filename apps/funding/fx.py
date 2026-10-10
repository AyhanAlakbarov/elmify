from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from apps.reference_data import COUNTRY_TO_CURRENCY


class UnconvertibleCurrency(Exception):
    """Raised when a rate table cannot express a requested conversion."""


@dataclass(frozen=True)
class RateTable:
    base: str
    rates: Mapping[str, Decimal]
    source: str
    retrieved_on: date


def round_money(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def convert(
    amount: Decimal, source_currency: str, target_currency: str, table: RateTable
) -> Decimal:
    if source_currency == target_currency:
        return round_money(amount)
    try:
        source_rate = table.rates[source_currency]
        target_rate = table.rates[target_currency]
    except KeyError as exc:
        raise UnconvertibleCurrency(f"{table.source} has no rate for {exc.args[0]}") from exc
    in_base = amount / source_rate
    return round_money(in_base * target_rate)


@dataclass(frozen=True)
class PresentedMoney:
    amount: Decimal
    currency: str
    rate: Decimal
    source: str
    retrieved_on: date


def home_currency_for(country_code: str) -> str | None:
    return COUNTRY_TO_CURRENCY.get(country_code)


def present(
    amount: Decimal, source_currency: str, home_currency: str, table: RateTable
) -> PresentedMoney:
    converted = convert(amount, source_currency, home_currency, table)
    # convert() has already raised UnconvertibleCurrency for anything the table cannot
    # express, so the only case left without a table entry is the identity one.
    rate = (
        Decimal("1")
        if source_currency == home_currency
        else table.rates[home_currency] / table.rates[source_currency]
    )
    return PresentedMoney(
        amount=converted,
        currency=home_currency,
        rate=rate,
        source=table.source,
        retrieved_on=table.retrieved_on,
    )
