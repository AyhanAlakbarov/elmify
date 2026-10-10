from apps.funding.models import _HOLDER_VALUES, FundingOpportunity, Institution, Program
from apps.research.cells import (
    ANY,
    LEVEL,
    Area,
    CellKey,
    area_of,
    award_cells,
    program_cells,
    student_areas,
    student_cells,
)
from apps.research.funding_reader import FAMILY_BY_HOLDER


def test_a_student_with_no_destination_gets_the_any_host_and_both_homes(profile_snapshot) -> None:
    profile = profile_snapshot(nationality="AZ", country_of_residence="TR", allowed_countries=())
    cells = student_cells(profile)
    assert {cell.host for cell in cells} == {ANY}
    assert {cell.home for cell in cells} == {"AZ", "TR", ANY}
    assert {cell.level for cell in cells} == {LEVEL} == {"MASTER"}
    # Read from the tuple, not typed: a new holder value moves the count with it.
    assert {cell.holder for cell in cells} == set(_HOLDER_VALUES)


def test_an_excluded_country_is_never_a_host_even_when_also_allowed(profile_snapshot) -> None:
    # The schema refuses an overlap (profile_country_overlap), so the overlap is
    # built past validation: the cell rule must not depend on the schema alone.
    profile = profile_snapshot(allowed_countries=("DE", "FR")).model_copy(
        update={"excluded_countries": ("FR",)}
    )
    assert {cell.host for cell in student_cells(profile)} == {"DE", ANY}


def test_areas_are_where_the_bodies_are_home_and_hosts_times_families(profile_snapshot) -> None:
    profile = profile_snapshot(
        nationality="AZ", country_of_residence="AZ", allowed_countries=("DE",)
    )
    areas = student_areas(profile)
    assert Area("AZ", "PRIVATE_FOUNDATION") in areas
    assert Area("DE", "UNIVERSITY_WIDE") in areas
    assert all(area.country != ANY for area in areas)  # no search can aim at "anywhere"
    assert {area.family for area in areas} == set(FAMILY_BY_HOLDER.values())


# One test per OpportunityScope, matching funding_opportunity_scope_shape_valid:
# only COUNTRY carries country_code; INSTITUTION and PROGRAM carry it through
# their own row; GLOBAL and HOLDER carry none, so they sit in host ANY.


def test_a_global_award_sits_in_any_host() -> None:
    award = FundingOpportunity(holder="INTERGOVERNMENTAL", scope_type="GLOBAL")
    assert {cell.host for cell in award_cells(award, eligible_nationalities=())} == {ANY}


def test_a_country_award_sits_in_its_own_country() -> None:
    award = FundingOpportunity(
        holder="NATIONAL_GOVERNMENT", scope_type="COUNTRY", country_code="DE"
    )
    assert award_cells(award, eligible_nationalities=()) == {
        CellKey("NATIONAL_GOVERNMENT", "DE", ANY, LEVEL)
    }


def test_an_institution_award_sits_in_the_institutions_country() -> None:
    award = FundingOpportunity(
        holder="INSTITUTION", scope_type="INSTITUTION", institution=Institution(country_code="FR")
    )
    assert {cell.host for cell in award_cells(award, eligible_nationalities=())} == {"FR"}


def test_a_programme_award_sits_in_the_programmes_country() -> None:
    award = FundingOpportunity(
        holder="INSTITUTION", scope_type="PROGRAM", program=Program(country_code="NL")
    )
    assert {cell.host for cell in award_cells(award, eligible_nationalities=())} == {"NL"}


def test_a_holder_award_with_no_nationality_list_sits_in_any_home_and_any_host() -> None:
    award = FundingOpportunity(holder="PRIVATE_FOUNDATION", scope_type="HOLDER")
    assert award_cells(award, eligible_nationalities=()) == {
        CellKey("PRIVATE_FOUNDATION", ANY, ANY, LEVEL)
    }


def test_a_scope_row_missing_its_anchor_over_includes_into_any() -> None:
    # The check constraint forbids this shape on a saved row; an unsaved or
    # half-built one must still never be dropped from every cell.
    award = FundingOpportunity(holder="INSTITUTION", scope_type="INSTITUTION")
    assert {cell.host for cell in award_cells(award, eligible_nationalities=())} == {ANY}


def test_a_nationality_list_narrows_home_and_never_drops_the_award() -> None:
    award = FundingOpportunity(holder="NATIONAL_GOVERNMENT", scope_type="HOLDER")
    cells = award_cells(award, eligible_nationalities=("AZ", "GE"))
    assert {cell.home for cell in cells} == {"AZ", "GE"}


def test_an_unlabelled_holder_is_unstated_never_dropped() -> None:
    award = FundingOpportunity(holder="", scope_type="HOLDER")
    assert {cell.holder for cell in award_cells(award, eligible_nationalities=())} == {"UNSTATED"}


def test_a_programme_is_an_institution_cell_in_its_own_country() -> None:
    assert program_cells(Program(country_code="DE")) == {CellKey("INSTITUTION", "DE", ANY, LEVEL)}


def test_a_student_cell_matches_an_any_cell_and_its_own_exact_cell(profile_snapshot) -> None:
    profile = profile_snapshot(
        nationality="AZ", country_of_residence="AZ", allowed_countries=("DE",)
    )
    mine = student_cells(profile)
    assert CellKey("INSTITUTION", "DE", ANY, LEVEL) in mine
    assert CellKey("PRIVATE_FOUNDATION", ANY, ANY, LEVEL) in mine


def test_an_area_is_where_the_body_is_not_the_host() -> None:
    cell = CellKey("PRIVATE_FOUNDATION", "DE", "TR", LEVEL)
    assert area_of(cell, organisation_country="TR") == Area("TR", "PRIVATE_FOUNDATION")
    assert area_of(cell, organisation_country="") == Area("DE", "PRIVATE_FOUNDATION")
