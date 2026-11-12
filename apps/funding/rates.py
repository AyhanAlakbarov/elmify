"""The daily official rates, stored and read back (lanes spec §7.6)."""

from __future__ import annotations

from datetime import date
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
    # CBAR does not quote MYR, ZAR, THB...: cross them through EUR (X per EUR x EUR per AZN).
    if base == "AZN" and "EUR" in rates:
        ecb_day = (
            ExchangeRate.objects.filter(base="EUR", day__lte=on)
            .order_by("-day")
            .values_list("day", flat=True)
            .first()
        )
        if ecb_day is not None:
            for currency, rate in ExchangeRate.objects.filter(
                base="EUR", day=ecb_day
            ).values_list("currency", "rate"):
                if currency not in rates:
                    rates[currency] = rate * rates["EUR"]
                    cross.add(currency)
    return RateTable(
        base=base,
        rates=rates,
        source=rows[0][2],
        retrieved_on=day,
        cross=frozenset(cross),
    )
