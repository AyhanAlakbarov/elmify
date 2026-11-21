"""Credits on a transcript, converted to ECTS.

A full-time year is 60 ECTS (ECTS Users' Guide). Any other system converts by
its own full-time year: 30 US semester hours, or whatever a local system's
year holds. No year load means no conversion -- an unknown figure is reported
as unknown, never guessed, because a guessed credit total decides whether a
programme's "20 ECTS of computing" gate passes.

# ponytail: two named systems plus a per-transcript year load; the spec's
# section 4.4 research adds named systems (AZ, TR local credits) as rows here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

CreditUnit = Literal[
    "ECTS",
    "US_SEMESTER_HOUR",
    "US_QUARTER_HOUR",
    "UK_CATS",
    "RU_ZET",
    "JP_CREDIT",
    "KR_CREDIT",
    "IN_CBCS",
    "CN_CREDIT",
    "AU_EFTSL",
    "LOCAL",
    "UNKNOWN",
]

_ECTS_PER_YEAR = Decimal("60")
_YEAR_LOAD: dict[str, Decimal] = {
    "ECTS": Decimal("60"),
    "US_SEMESTER_HOUR": Decimal("30"),
    "US_QUARTER_HOUR": Decimal("45"),
    "UK_CATS": Decimal("120"),
    "RU_ZET": Decimal("60"),
    "JP_CREDIT": Decimal("31"),
    "KR_CREDIT": Decimal("33"),
    "IN_CBCS": Decimal("40"),
    "CN_CREDIT": Decimal("40"),
    "AU_EFTSL": Decimal("1"),
}
_CENT = Decimal("0.01")


def to_ects(
    credits: Decimal, unit: CreditUnit, *, local_credits_per_year: Decimal | None = None
) -> Decimal | None:
    if unit == "LOCAL":
        year_load = local_credits_per_year
    else:
        year_load = _YEAR_LOAD.get(unit)
    if year_load is None or year_load <= 0:
        return None
    return (credits * _ECTS_PER_YEAR / year_load).quantize(_CENT, rounding=ROUND_HALF_UP)
