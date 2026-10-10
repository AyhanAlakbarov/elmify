from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from defusedxml import ElementTree

from apps.funding.fx import RateTable
from apps.reference_data import ISO_4217_CODES


def _require_rates(rates: dict[str, Decimal], source: str) -> None:
    if len(rates) < 2:
        raise ValueError(f"{source} returned no usable rates")


def parse_ecb_daily(payload: bytes) -> RateTable:
    if not payload.strip():
        raise ValueError("ECB returned an empty body")
    root = ElementTree.fromstring(payload)
    namespace = {"ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
    day = root.find(".//ecb:Cube[@time]", namespace)
    if day is None:
        raise ValueError("ECB payload has no dated cube")
    rates: dict[str, Decimal] = {"EUR": Decimal("1")}
    for entry in day.findall("ecb:Cube", namespace):
        code = entry.get("currency")
        value = entry.get("rate")
        if code is None or value is None or code not in ISO_4217_CODES:
            continue
        rates[code] = Decimal(value)
    _require_rates(rates, "ECB")
    return RateTable(
        base="EUR",
        rates=rates,
        source="ECB",
        retrieved_on=date.fromisoformat(str(day.get("time"))),
    )


def parse_cbar_daily(payload: bytes) -> RateTable:
    if not payload.strip():
        raise ValueError("CBAR returned an empty body")
    root = ElementTree.fromstring(payload)
    rates: dict[str, Decimal] = {"AZN": Decimal("1")}
    for entry in root.iter("Valute"):
        code = entry.get("Code")
        nominal = entry.findtext("Nominal")
        value = entry.findtext("Value")
        if code is None or value is None or code not in ISO_4217_CODES:
            continue
        divisor = Decimal(nominal) if nominal and nominal.strip().isdigit() else Decimal("1")
        rates[code] = Decimal(value) / divisor
    _require_rates(rates, "CBAR")
    stamp = root.get("Date")
    if stamp is None:
        raise ValueError("CBAR payload has no date")
    return RateTable(
        base="AZN",
        rates=rates,
        source="CBAR",
        retrieved_on=datetime.strptime(stamp, "%d.%m.%Y").date(),
    )
