"""Country-group phrases, read through the fallback table (verified-catalog §5.2.1).

The funder's own list always comes first: a page that names countries is read as those countries,
and this table is only for a page that names a group and lists nothing. Each list is data with its
source (`docs/research/country-groups.csv`, one row per group and status, codes space-separated);
the rules of what a phrase means are code, here, copied from the owner's table:

- CIS: AZ AM BY KZ KG TJ TM UZ, MD until 2027-04-08; UA held; GE and TR not eligible.
- "developing countries": off the DAC list not eligible, on it held -- unless the page itself says
  DAC or ODA, when the DAC list applies.
- "Global South", "emerging", "newly industrialised", a bare "LMIC": held for everyone.
- "low- and middle-income": World Bank LMY, only when it is the whole criterion; else held.
- LDC: the M49 LDC column. Sub-Saharan Africa: M49 region 202, Sudan and Djibouti held.

A row past its `until` date is held, never dropped: the operator re-checks it (Moldova's exit,
Nauru's graduation). "International" or "foreign" students is not a condition at all (§5.2.1): it
has no expansion, and the caller hunts the funder's list instead.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from apps.funding.regions import REGIONS

GROUPS_FILE = Path(__file__).resolve().parents[3] / "docs" / "research" / "country-groups.csv"

#: Matched against a place candidate's text (who.py finds these as `unknown_group`). First wins.
PHRASES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (group, re.compile(pattern, re.IGNORECASE)) for group, pattern in (
        ("DEVELOPING", r"develop\w* and (?:emerging|newly industriali[sz]ed)|developing countr|"
                       r"развивающ|inkişaf etməkdə olan|gelişmekte olan|Entwicklungsländer"),
        ("DAC", r"(?<!\w)(?-i:DAC|ODA)(?!\w)"),
        ("LDC", r"least developed|en az gelişmiş|наименее развит"),
        ("CIS", r"(?<!\w)(?-i:CIS)(?!\w)|Commonwealth of Independent States|(?-i:СНГ)|"
                r"Müstəqil Dövlətlər Birliyi|Bağımsız Devletler Topluluğu"),
        ("LMY", r"low-?\s*and[- ]middle[- ]income"),
        ("LMIC", r"(?<!\w)(?-i:LMICs?)(?!\w)"),
        ("GLOBAL_SOUTH", r"Global South|Глобальн\w* Юг"),
        ("EMERGING", r"emerging|Schwellenländer"),
        ("NEWLY_INDUSTRIALISED", r"newly industriali[sz]ed"),
        ("SSA", r"sub-Saharan|к югу от Сахары"),
        ("TURKIC_STATES", r"Turkic States|Türk Dövlətləri|Türk Devletleri"),
        ("OIC", r"(?<!\w)(?-i:OIC)(?!\w)|Islamic Cooperation|İslam Əməkdaşlıq|İslam İşbirliği|"
                r"التعاون الإسلامي"),
        ("INTERNATIONAL", r"foreign|international|иностранн|xarici|əcnəbi|yabancı|uluslararası"),
    )
)
#: Groups with no list anywhere: whoever reads them is held, whatever their country.
EVERYONE_HELD = frozenset({"LMIC", "GLOBAL_SOUTH", "EMERGING", "NEWLY_INDUSTRIALISED"})


@dataclass(frozen=True)
class Row:
    group: str
    status: str  # "eligible" | "held"
    until: date | None
    codes: frozenset[str]
    source: str
    as_of: str


@dataclass(frozen=True)
class Expansion:
    """Who a group phrase lets apply. A country in neither set is not eligible."""

    group: str
    eligible: frozenset[str]
    held: frozenset[str]
    everyone_held: bool = False


@cache
def rows() -> tuple[Row, ...]:
    with GROUPS_FILE.open(encoding="utf-8", newline="") as handle:
        return tuple(
            Row(r["group"], r["status"], date.fromisoformat(r["until"]) if r["until"] else None,
                frozenset(r["codes"].split()), r["source"], r["as_of"])
            for r in csv.DictReader(handle)
        )


def group_of(text: str) -> str | None:
    """The group a place candidate's text names, or None."""
    return next((group for group, pattern in PHRASES if pattern.search(text)), None)


def _listed(group: str, on: date) -> Expansion:
    eligible: set[str] = set()
    held: set[str] = set()
    for row in rows():
        if row.group != group:
            continue
        expired = row.until is not None and on >= row.until
        (held if row.status == "held" or expired else eligible).update(row.codes)
    return Expansion(group, frozenset(eligible), frozenset(held - eligible))


def expand(group: str, *, on: date, page_says_dac: bool = False,
           sole_criterion: bool = False) -> Expansion | None:
    """The fallback for `group` (a PHRASES key or a REGIONS key) as read on `on`, the page's
    date. None for a group with no expansion ("INTERNATIONAL"), which is not a condition."""
    if group in REGIONS:
        region = REGIONS[group]
        return Expansion(group, frozenset(region.countries), frozenset())
    if group in EVERYONE_HELD or (group == "LMY" and not sole_criterion):
        return Expansion(group, frozenset(), frozenset(), everyone_held=True)
    if group == "DEVELOPING":
        dac = _listed("DAC", on)
        if page_says_dac:
            return Expansion(group, dac.eligible, dac.held)
        return Expansion(group, frozenset(), dac.eligible | dac.held)
    if group in {"CIS", "DAC", "LDC", "SSA", "LMY"}:
        return _listed(group, on)
    return None
