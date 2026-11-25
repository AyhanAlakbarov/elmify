"""The daily official rates, stored and read back (lanes spec §7.6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from .fx import RateTable
from .models import ExchangeRate

#: CBAR publishes one table per Baku calendar day.
BAKU = ZoneInfo("Asia/Baku")


def store(table: RateTable) -> int:
    """Write one day's table. A second run for the same day overwrites it."""
    rows = [
        ExchangeRate(
            day=table.retrieved_on, base=table.base, currency=code, rate=rate, source=table.source
        )
        for code, rate in table.rates.items()
    ]
    ExchangeRate.objects.bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["day", "base", "currency"],
        update_fields=["rate", "source"],
    )
    return len(rows)


def latest_table(*, on: date | None = None, base: str = "AZN") -> RateTable | None:
    """The newest stored day on or before ``on`` (today in Baku), or None."""
    on = on or timezone.localdate(timezone=BAKU)
    day = (
        ExchangeRate.objects.filter(base=base, day__lte=on)
        .order_by("-day")
        .values_list("day", flat=True)
        .first()
    )
    if day is None:
        return None
    rows = list(
        ExchangeRate.objects.filter(base=base, day=day).values_list("currency", "rate", "source")
    )
    rates = {currency: rate for currency, rate, _source in rows}
    cross: set[str] = set()
    # Cross missing currencies through stored pivot tables (EUR, USD, AZN)
    # whenever a direct rate is missing, regardless of whether base == "AZN".
    for pivot in ("EUR", "USD", "AZN"):
        if pivot == base:
            continue
        pivot_day = (
            ExchangeRate.objects.filter(base=pivot, day__lte=on)
            .order_by("-day")
            .values_list("day", flat=True)
            .first()
        )
        if pivot_day is None:
            continue
        pivot_rows = dict(
            ExchangeRate.objects.filter(base=pivot, day=pivot_day).values_list(
                "currency", "rate"
            )
        )
        pivot_per_base = rates.get(pivot)
        if pivot_per_base is None and base in pivot_rows and pivot_rows[base] != 0:
            pivot_per_base = Decimal("1") / pivot_rows[base]
        if pivot_per_base is None:
            continue
        for currency, rate in pivot_rows.items():
            if currency not in rates:
                rates[currency] = rate * pivot_per_base
                cross.add(currency)
    return RateTable(
        base=base,
        rates=rates,
        source=rows[0][2],
        retrieved_on=day,
        cross=frozenset(cross),
    )
