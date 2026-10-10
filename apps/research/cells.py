"""Profile -> cells, catalog row -> cells, cells -> areas (spec 5, 10.1, 10.6).

A CELL is `holder x host country x home country x level`, the accounting unit.
An AREA is `(organisation country, family)`, the grain a sweep pass can act on
(spec 5's correction: the pass is keyed by country and family, and one pass
serves several cells). The coverage line reports areas; CellCoverage stores cells.

**Over-include, never under-include.** An award whose destination nothing reads
sits in host ANY; one with no nationality list sits in home ANY. The gates
decide eligibility. A cell rule that dropped an award would hide it from every
pack with no reason attached anywhere -- the failure P1-7 exists to prevent.

**The host rule follows `funding_opportunity_scope_shape_valid` exactly.** Only
a COUNTRY row carries `country_code`; an INSTITUTION or PROGRAM row carries it
through its institution or programme (its own `country_code` is NULL by that
constraint), and GLOBAL and HOLDER rows carry none. A caller walking many
awards should `select_related("institution", "program")`, or each INSTITUTION
and PROGRAM row costs one query here.

Nothing here names a country: every country comes from the profile or the row.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.models import _HOLDER_VALUES, FundingOpportunity, OpportunityScope, Program

from .funding_reader import FAMILY_BY_HOLDER

ANY = "ANY"
LEVEL = "MASTER"
UNSTATED = "UNSTATED"


@dataclass(frozen=True, order=True)
class CellKey:
    holder: str
    host: str
    home: str
    level: str


@dataclass(frozen=True, order=True)
class Area:
    country: str
    family: str


def _hosts(profile: StudentProfileSnapshot) -> set[str]:
    excluded = set(profile.excluded_countries)
    return {code for code in profile.allowed_countries if code not in excluded} | {ANY}


def _homes(profile: StudentProfileSnapshot) -> set[str]:
    return {profile.nationality, profile.country_of_residence, ANY}


def student_cells(profile: StudentProfileSnapshot) -> frozenset[CellKey]:
    return frozenset(
        CellKey(holder, host, home, LEVEL)
        for holder in _HOLDER_VALUES
        for host in _hosts(profile)
        for home in _homes(profile)
    )


def student_areas(profile: StudentProfileSnapshot) -> frozenset[Area]:
    countries = (_hosts(profile) | _homes(profile)) - {ANY}
    families = set(FAMILY_BY_HOLDER.values())
    return frozenset(Area(country, family) for country in countries for family in families)


def _award_host(award: FundingOpportunity) -> str:
    scope = award.scope_type
    if scope == OpportunityScope.COUNTRY:
        return award.country_code or ANY
    if scope == OpportunityScope.INSTITUTION:
        institution = award.institution
        return institution.country_code if institution is not None else ANY
    if scope == OpportunityScope.PROGRAM:
        program = award.program
        return program.country_code if program is not None else ANY
    # GLOBAL, HOLDER: no destination on the row (a holder's direction is owed, spec 19).
    return ANY


def award_cells(
    award: FundingOpportunity,
    *,
    eligible_nationalities: Iterable[str],
    host: str | None = None,
) -> frozenset[CellKey]:
    """`host`, when given, is the award's host already read in bulk (a caller
    walking the whole served catalogue); otherwise it is read off the row."""
    holder = award.holder or UNSTATED
    host = host if host is not None else _award_host(award)
    homes = set(eligible_nationalities) or {ANY}
    return frozenset(CellKey(holder, host, home, LEVEL) for home in homes)


def program_cells(program: Program) -> frozenset[CellKey]:
    return frozenset({CellKey("INSTITUTION", program.country_code, ANY, LEVEL)})


def area_of(cell: CellKey, *, organisation_country: str) -> Area:
    """The area a catalog row belongs to: where its body is, and its family."""
    return Area(
        organisation_country or cell.host,
        FAMILY_BY_HOLDER.get(cell.holder, FAMILY_BY_HOLDER[UNSTATED]),
    )
