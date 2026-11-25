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

import re
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

CreditUnit = Literal[
    "ECTS",
    "CFU",
    "AKTS",
    "EC",
    "SE_HP",
    "EE_EAP",
    "DE_LP",
    "DE_SWS",
    "LV_KP",
    "US_SEMESTER_HOUR",
    "US_QUARTER_HOUR",
    "CA_FCE",
    "UK_CATS",
    "RU_ZET",
    "TR_LOCAL_KREDI",
    "ACADEMIC_HOUR",
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
    "CFU": Decimal("60"),
    "AKTS": Decimal("60"),
    "EC": Decimal("60"),
    "SE_HP": Decimal("60"),
    "EE_EAP": Decimal("60"),
    "DE_LP": Decimal("60"),
    "DE_SWS": Decimal("40"),
    "LV_KP": Decimal("40"),
    "US_SEMESTER_HOUR": Decimal("30"),
    "US_QUARTER_HOUR": Decimal("45"),
    "CA_FCE": Decimal("5"),
    "UK_CATS": Decimal("120"),
    "RU_ZET": Decimal("60"),
    "TR_LOCAL_KREDI": Decimal("35"),
    "ACADEMIC_HOUR": Decimal("2160"),
    "JP_CREDIT": Decimal("31"),
    "KR_CREDIT": Decimal("33"),
    "IN_CBCS": Decimal("40"),
    "CN_CREDIT": Decimal("40"),
    "AU_EFTSL": Decimal("1"),
}
_CENT = Decimal("0.01")

_MASTER_QUAL_RE = re.compile(
    r"(?:\b(?:master(?:'s)?|m[áa]ster|m\.?sc\.?|m\.?a\.?|m\.?eng\.?|m\.?b\.?a\.?|ll\.?m\.?|"
    r"m\.?tech\.?|m\.?e\.?|magistr\w*|magister|магистр\w*|yüksek\s+lisans|"
    r"laurea\s+magistrale|dipl[ôo]me\s+d['\u2019]ing[ée]nieur)\b|硕士|修士|석사)",
    re.IGNORECASE,
)
_FOUR_YEAR_BACHELOR_COUNTRIES = frozenset(
    {"TR", "US", "CA", "AZ", "RU", "UA", "KZ", "UZ", "BY", "GE", "JP", "KR", "CN", "ES"}
)
_THREE_YEAR_BOLOGNA_COUNTRIES = frozenset(
    {
        "GB",
        "DE",
        "FR",
        "IT",
        "NL",
        "BE",
        "AT",
        "CH",
        "SE",
        "NO",
        "DK",
        "FI",
        "EE",
        "PL",
        "CZ",
        "HU",
    }
)


def _is_master_qualification(qualification: str) -> bool:
    if not qualification:
        return False
    if _MASTER_QUAL_RE.search(qualification):
        return True
    from .degree_match import degree_level

    return degree_level(qualification) == "master"


def infer_local_credits_per_year(
    completed_credits: Sequence[Decimal],
    *,
    total_credits: Decimal | None = None,
    qualification: str = "",
    country_code: str = "",
) -> Decimal | None:
    """Infer the full-time annual credit load for a `LOCAL` transcript only when the
    transcript provides sufficient full-degree context (Tier-2 proportional normalization).

    Returns `None` on partial/short transcripts without a clear statutory or degree-total
    signature so individual isolated courses are never guessed.
    """
    positive = [c for c in completed_credits if c > Decimal("0")]
    if not positive:
        return None

    cc = country_code.strip().upper()
    sorted_vals = sorted(positive)
    median_val = sorted_vals[len(sorted_vals) // 2]

    # Post-Soviet / curriculum contact-hour transcripts where individual courses carry
    # 36–250 academic hours (36 academic hours = 1 ZET / ECTS, 2160 hours/year).
    if median_val >= Decimal("36") and max(positive) <= Decimal("600"):
        return _YEAR_LOAD["ACADEMIC_HOUR"]

    # Full-degree proportional normalization when >= 24 completed courses (or completed
    # Master's with >= 12 courses) are present on the transcript.
    is_master = _is_master_qualification(qualification or "")
    min_courses_for_degree = 12 if is_master else 24
    if len(positive) < min_courses_for_degree:
        return None

    sum_credits = sum(positive, Decimal("0"))
    degree_total = (
        total_credits
        if total_credits is not None
        and total_credits > Decimal("0")
        and Decimal("0.85") <= (sum_credits / total_credits) <= Decimal("1.15")
        else sum_credits
    )
    if is_master:
        nominal_years = Decimal("2")
    elif cc in _FOUR_YEAR_BACHELOR_COUNTRIES or len(positive) >= 32:
        nominal_years = Decimal("4")
    elif cc in _THREE_YEAR_BOLOGNA_COUNTRIES and len(positive) < 32:
        nominal_years = Decimal("3")
    else:
        nominal_years = Decimal("4") if len(positive) >= 30 else Decimal("3")

    year_load = degree_total / nominal_years
    return year_load if year_load > Decimal("0") else None


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
