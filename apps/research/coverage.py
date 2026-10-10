"""CellCoverage and the coverage line (spec 10.6, 6.2's "the line names the rung").

Recomputed from source on every call -- never incremented. Reads: this tenant's
active students, each one's latest published pack, their profile version and its
discipline bucket; and the served catalogue rows (shared) for `found_served`
and `verified_for_intake`. Worker-side only: the catalogue reads here are
runtime_engine's, and the web tier reads the copy on `PackVersion.coverage`.

A student's cells come from `cells.student_cells`; a served award's from
`cells.award_cells`, with its home cells read off its CITIZENSHIP IN rules --
the one place master stores a nationality list. Over-include, never under-
include (cells.py): an award whose list is missing, negated or unreadable sits
in home ANY.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.utils import timezone
from pydantic import ValidationError

from apps.accounts.models import StudentProfileVersion
from apps.accounts.schemas import StudentProfileSnapshot
from apps.funding.eligibility import expand_countries
from apps.funding.fx import RateTable, UnconvertibleCurrency, convert
from apps.funding.models import (
    BenefitRule,
    CostComponent,
    CycleState,
    FundingCycleVerification,
    FundingOpportunity,
    Institution,
    OpportunityScope,
    PackCandidate,
    PackVersion,
    Program,
)
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from .cells import ANY, Area, CellKey, area_of, award_cells, student_areas, student_cells
from .disciplines import UNCLASSIFIABLE
from .models import SWEEP_FAMILIES, CellCoverage, ProfileCellSelection, SweepRun
from .tap_seams import PassState, PassStates, RungRow, RungSource

#: `validity.cycle_validity`'s "only OPEN and UPCOMING are ever shown": a
#: stored FundingCycleVerification in one of these states is an award verified
#: for that intake. The row is the function's output; it is never re-derived here.
VERIFIED_STATES = (CycleState.OPEN, CycleState.UPCOMING)


def _eligible_nationalities(rules: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    """The union of an award's CITIZENSHIP IN lists; () means home ANY.

    A NOT_IN list, or an IN list this build cannot expand (an unknown region),
    widens the award to every home rather than narrowing it: a list read wrong
    would hide the award from exactly the students it is for.
    """
    homes: set[str] = set()
    for operator, value in rules:
        countries = expand_countries(value) if operator == "IN" else None
        if countries is None:
            return ()
        homes.update(countries)
    return tuple(sorted(homes))


def served_cells() -> dict[CellKey, set[UUID]]:
    """Every served catalogue award, by the cells it sits in. Shared-catalogue read."""
    rules: dict[UUID, list[tuple[str, str]]] = defaultdict(list)
    for opportunity_id, operator, value in BenefitRule.objects.filter(
        key="CITIZENSHIP", benefit__opportunity__served=True
    ).values_list("benefit__opportunity_id", "operator", "value"):
        rules[opportunity_id].append((operator, value))
    out: dict[CellKey, set[UUID]] = defaultdict(set)
    awards = list(FundingOpportunity.objects.filter(served=True, suspension_quote=""))
    # Hosts in bulk, by id: one query per side instead of one per INSTITUTION
    # or PROGRAM row, and no forward-FK traversal off the award.
    institutions = dict(
        Institution.objects.filter(
            id__in={a.institution_id for a in awards if a.institution_id}
        ).values_list("id", "country_code")
    )
    programs = dict(
        Program.objects.filter(
            id__in={a.program_id for a in awards if a.program_id}
        ).values_list("id", "country_code")
    )
    for award in awards:
        host = _host(award, institutions, programs)
        homes = _eligible_nationalities(rules.get(award.id, ()))
        for cell in award_cells(award, eligible_nationalities=homes, host=host):
            out[cell].add(award.id)
    return out


def _host(
    award: FundingOpportunity,
    institutions: dict[UUID, str],
    programs: dict[UUID, str],
) -> str:
    """cells._award_host over prefetched countries (the same scope rule)."""
    if award.scope_type == OpportunityScope.COUNTRY:
        return award.country_code or ANY
    if award.scope_type == OpportunityScope.INSTITUTION and award.institution_id:
        return institutions.get(award.institution_id, ANY)
    if award.scope_type == OpportunityScope.PROGRAM and award.program_id:
        return programs.get(award.program_id, ANY)
    return ANY


def _matches(student_cell: CellKey, catalog_cell: CellKey) -> bool:
    return (
        student_cell.holder == catalog_cell.holder
        and student_cell.level == catalog_cell.level
        and catalog_cell.host in {student_cell.host, ANY}
        and catalog_cell.home in {student_cell.home, ANY}
    )


def in_cell(cell: CellKey, catalog: dict[CellKey, set[UUID]]) -> frozenset[UUID]:
    """The served awards a student cell reaches (its own cell and every ANY widening)."""
    ids: set[UUID] = set()
    for catalog_cell, award_ids in catalog.items():
        if _matches(cell, catalog_cell):
            ids |= award_ids
    return frozenset(ids)


def verified_for_intake(award_ids: Iterable[UUID], intake_year: int) -> frozenset[UUID]:
    """The awards whose stored cycle verification for `intake_year` is OPEN or UPCOMING."""
    return frozenset(
        FundingCycleVerification.objects.filter(
            opportunity_id__in=list(award_ids),
            intake_start_year=intake_year,
            state__in=VERIFIED_STATES,
        ).values_list("opportunity_id", flat=True)
    )


def verification_running(intake_year: int) -> bool:
    """Whether the cycle-verification ladder has written ANY row for this intake.

    Only when it has not does the coverage line say "verification not yet
    running": once rows exist, an award with none is simply unverified, and 0
    verified is a real count.
    """
    return FundingCycleVerification.objects.filter(intake_start_year=intake_year).exists()


def budget_unspent(
    pack: PackVersion, profile: StudentProfileSnapshot, *, rates: RateTable | None
) -> bool:
    """The pack's summed application fees sit below the student's application budget.

    Plan decision 5's stand-in for the optimizer's "budget unspent" outcome.
    With no rate table -- which is what a deployed worker has today
    (`handle_research_message` runs with rates=None) -- this is False and
    counts nothing, rather than comparing currencies at a rate somebody made
    up. A fee in a currency the table lacks is the same answer, for the same
    reason.
    """
    if rates is None:
        return False
    budget = profile.application_budget
    fees = CostComponent.objects.filter(
        kind=CostComponent.Kind.APPLICATION_FEE,
        program__recommendation_candidates__packcandidate__pack_version=pack,
    ).values_list("amount", "currency")
    try:
        total = sum(
            (convert(amount, currency, budget.currency, rates) for amount, currency in fees),
            start=Decimal("0"),
        )
    except UnconvertibleCurrency:
        return False
    return total < budget.amount


def _latest_published(student: Membership) -> PackVersion | None:
    return (
        PackVersion.objects.filter(
            run__profile_version__student=student, published_at__isnull=False
        )
        .order_by("-published_at")
        .first()
    )


def _profile(version: StudentProfileVersion) -> StudentProfileSnapshot | None:
    if version.schema_version != 3:
        return None
    try:
        return StudentProfileSnapshot.model_validate(version.snapshot)
    except ValidationError:
        return None


def refresh_cell_coverage(tenant_id: UUID, *, rates: RateTable | None = None) -> int:
    """Rebuild this tenant's CellCoverage from source. Returns the rows written.

    Counts ACTIVE students with a PUBLISHED pack only: an unpublished (empty)
    pack is no evidence about the student's cells either way. Every row is
    deleted and rewritten, so an erased or deactivated student is forgotten
    by the next call -- the table never holds a count nobody can recompute.
    """
    catalog = served_cells()
    cell_ids: dict[CellKey, frozenset[UUID]] = {}
    verified_by_year: dict[int, frozenset[UUID]] = {}
    all_served = frozenset(award_id for ids in catalog.values() for award_id in ids)
    # (cell, bucket) -> [active, no floor, budget unspent] and the verified ids.
    counts: dict[tuple[CellKey, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    verified: dict[tuple[CellKey, str], set[UUID]] = defaultdict(set)
    now = timezone.now()
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        students = Membership.objects.filter(
            tenant_id=tenant_id, role=Membership.Role.STUDENT, active=True
        )
        for student in students:
            pack = _latest_published(student)
            if pack is None:
                continue
            version = StudentProfileVersion.objects.get(id=pack.run.profile_version_id)
            profile = _profile(version)
            if profile is None:
                continue
            selection = ProfileCellSelection.objects.filter(profile_version=version).first()
            bucket = selection.discipline_bucket if selection else UNCLASSIFIABLE
            packed = set(
                PackCandidate.objects.filter(
                    pack_version=pack, candidate__opportunity__isnull=False
                ).values_list("candidate__opportunity_id", flat=True)
            )
            year = profile.intended_intake.year
            if year not in verified_by_year:
                verified_by_year[year] = verified_for_intake(all_served, year)
            mine = student_cells(profile)
            for cell in mine:
                if cell not in cell_ids:
                    cell_ids[cell] = in_cell(cell, catalog)
            thin = any(not (cell_ids[cell] & packed) for cell in mine)
            unspent = thin and budget_unspent(pack, profile, rates=rates)
            for cell in mine:
                key = (cell, bucket)
                row = counts[key]
                row[0] += 1
                row[1] += 0 if cell_ids[cell] & packed else 1
                row[2] += 1 if unspent else 0
                verified[key] |= cell_ids[cell] & verified_by_year[year]
        CellCoverage.objects.all().delete()
        CellCoverage.objects.bulk_create(
            CellCoverage(
                tenant_id=tenant_id,
                holder=cell.holder,
                host_country=cell.host,
                home_country=cell.home,
                level=cell.level,
                discipline_bucket=bucket,
                active_students=active,
                students_no_floor=no_floor,
                students_budget_unspent=unspent_count,
                found_served=len(cell_ids[cell]),
                verified_for_intake=len(verified[(cell, bucket)]),
                refreshed_at=now,
            )
            for (cell, bucket), (active, no_floor, unspent_count) in counts.items()
        )
    return len(counts)


# --- The coverage line (spec 10.6; 6.2's "the line names the rung") ---------


@dataclass(frozen=True)
class AreaLine:
    country: str
    family: str
    #: Packed awards from this area -- 0 is a thin area.
    eligible: int
    rung: RungRow | None
    passes: PassState


#: Stop reasons that mean the pass is FINISHED with the area: it hit a stop
#: rule or ran out of angles. BUDGET and CLASSIFIER_LIMIT are pauses -- the
#: pass could not go on, not a finding that there is nothing more -- so they do
#: not exclude the area from the sweep trigger and read as "researching".
EXHAUSTED_STOPS: frozenset[str] = frozenset({
    SweepRun.StopReason.PLATEAU, SweepRun.StopReason.ECONOMIC, SweepRun.StopReason.EXHAUSTED,
})

_STOP_CLAUSES: dict[str, str] = {
    SweepRun.StopReason.PLATEAU: "search only — stopped when three batches found nothing new",
    SweepRun.StopReason.ECONOMIC: (
        "search only — stopped where more searching cost more than it found"
    ),
    SweepRun.StopReason.EXHAUSTED: "search only — every stored angle asked",
    SweepRun.StopReason.BUDGET: "search only — paused (budget) — researching",
    SweepRun.StopReason.CLASSIFIER_LIMIT: "search only — paused (classifier limit) — researching",
}

_RUNG_KINDS = {1: "a purpose-filtered register", 2: "a register without purpose"}


def area_exhausted(passes: PassState) -> bool:
    return passes.stop_reason in EXHAUSTED_STOPS


def _researching(area: AreaLine) -> bool:
    """A thin area a sweep can still act on: its family has a pass, and that
    pass has not finished with it."""
    return area.family in SWEEP_FAMILIES and not area_exhausted(area.passes)


def _area_clause(area: AreaLine) -> str:
    where = f"{area.country} {area.family.replace('_', ' ').lower()}"
    rung = area.rung
    if rung is not None and rung.rung in _RUNG_KINDS:
        kind = _RUNG_KINDS[rung.rung]
        if not rung.surveyed:
            return f"{where}: {rung.listed:,} listed on {kind}, not yet read"
        return f"{where}: {rung.known:,} of {rung.listed:,} on {kind}, {rung.read:,} read"
    if rung is not None and rung.rung == 3:
        if not rung.surveyed:
            return f"{where}: umbrella and hub lists, not yet read"
        return f"{where}: umbrella and hub lists, {rung.known:,} bodies known"
    if area.family not in SWEEP_FAMILIES:
        return f"{where}: no register and no search pass for this family"
    if not area.passes.swept:
        return f"{where}: not yet searched"
    return f"{where}: " + _STOP_CLAUSES.get(
        area.passes.stop_reason, "search only — researching"
    )


def coverage_sentence(
    *, found: int, verified: int, verification_running: bool, areas: tuple[AreaLine, ...]
) -> str:
    """"N found in your cells; M verified for your intake; K areas still thin".

    Never "no funding": a thin area is a coverage fact about the catalogue, not
    a finding about the student. Six area clauses at most; the counts stay
    whole and the `areas` JSON beside the sentence carries every one.
    """
    thin = [a for a in areas if a.eligible == 0]
    head = f"{found} found in your cells; "
    head += (
        f"{verified} verified for your intake; "
        if verification_running
        else "verification not yet running; "
    )
    head += f"{len(thin)} areas still thin"
    head += " — researching." if any(_researching(a) for a in thin) else "."
    detail = "; ".join(
        _area_clause(a) for a in sorted(thin, key=lambda a: (a.country, a.family))[:6]
    )
    return head + (f" {detail}." if detail else "")


def eligible_by_area(awards: Iterable[FundingOpportunity]) -> dict[Area, int]:
    """Packed awards per area: where the body is (else the award's host), and
    its family. Every cell an award sits in maps to one area; an award counts
    once per area however many of its cells land there."""
    out: dict[Area, int] = defaultdict(int)
    for award in awards:
        organisation = award.organisation
        country = organisation.country_code if organisation is not None else ""
        areas = {
            area_of(cell, organisation_country=country)
            for cell in award_cells(award, eligible_nationalities=())
        }
        for area in areas:
            out[area] += 1
    return dict(out)


def student_coverage(
    profile: StudentProfileSnapshot,
    *,
    eligible: dict[Area, int],
    found: int,
    verified: int,
    verification_running: bool,
    rungs: RungSource,
    passes: PassStates,
) -> dict[str, object]:
    by_country: dict[str, tuple[RungRow, ...]] = {}
    lines: list[AreaLine] = []
    for area in sorted(student_areas(profile)):
        if area.country not in by_country:
            by_country[area.country] = rungs.rungs(area.country)
        rung = next((r for r in by_country[area.country] if r.family == area.family), None)
        lines.append(
            AreaLine(
                area.country, area.family, eligible.get(area, 0), rung,
                passes.state(area.country, area.family),
            )
        )
    return {
        "found": found,
        "verified": verified,
        "verification_running": verification_running,
        "areas": [
            {
                "country": line.country,
                "family": line.family,
                "eligible": line.eligible,
                "rung": line.rung.rung if line.rung else 4,
                "register": line.rung.register if line.rung else "",
                "stop_reason": line.passes.stop_reason,
                "clause": _area_clause(line),
            }
            for line in lines
        ],
        "sentence": coverage_sentence(
            found=found, verified=verified, verification_running=verification_running,
            areas=tuple(lines),
        ),
    }


#: What a pack says when there is no full profile to derive cells from.
NO_PROFILE_COVERAGE: dict[str, object] = {
    "found": 0,
    "verified": 0,
    "verification_running": False,
    "areas": [],
    "sentence": (
        "0 found in your cells: your cells come from the full consultation "
        "(where you are from and where you would study), which is not complete yet."
    ),
}


def pack_coverage(
    profile: StudentProfileSnapshot | None,
    packed_awards: Iterable[FundingOpportunity],
    *,
    rungs: RungSource,
    passes: PassStates,
) -> dict[str, object]:
    """The coverage JSON a pack carries, computed in the worker at build time.

    Copied onto `PackVersion.coverage` so the web tier (runtime_web, no
    catalogue grant) renders it without reading a catalogue table.
    """
    if profile is None:
        return dict(NO_PROFILE_COVERAGE)
    catalog = served_cells()
    found_ids: set[UUID] = set()
    for cell in student_cells(profile):
        found_ids |= in_cell(cell, catalog)
    year = profile.intended_intake.year
    return student_coverage(
        profile,
        eligible=eligible_by_area(packed_awards),
        found=len(found_ids),
        verified=len(verified_for_intake(found_ids, year)),
        verification_running=verification_running(year),
        rungs=rungs,
        passes=passes,
    )
