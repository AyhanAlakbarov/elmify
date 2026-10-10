"""CellCoverage, recomputed (spec 10.6), and the coverage line (Task 9)."""

from datetime import date
from decimal import Decimal

import pytest

from apps.funding.models import CostComponent, FundingCycleVerification
from apps.research.cells import Area
from apps.research.coverage import (
    AreaLine,
    budget_unspent,
    coverage_sentence,
    eligible_by_area,
    refresh_cell_coverage,
    served_cells,
    student_coverage,
)
from apps.research.models import CellCoverage
from apps.research.tap_seams import NullSeams, PassState, RungRow
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import EUR_RATES

pytestmark = pytest.mark.django_db

BUCKET = "physical_sciences"


def _row(tenant_id, **cell):
    fields = dict(holder="PRIVATE_FOUNDATION", host_country="ANY", home_country="AZ",
                  discipline_bucket=BUCKET)
    fields.update(cell)
    with tenant_scope(tenant_id):
        return CellCoverage.objects.get(**fields)


def test_a_student_with_no_eligible_option_in_a_cell_counts_as_no_floor(published_student):
    student = published_student(nationality="AZ", allowed=("DE",), eligible_awards=())
    refresh_cell_coverage(student.tenant_id)
    row = _row(student.tenant_id)
    assert (row.active_students, row.students_no_floor) == (1, 1)
    assert row.thinness == 1.0


def test_an_eligible_award_in_the_cell_is_a_floor(published_student, served_award):
    award = served_award(holder="PRIVATE_FOUNDATION", nationalities=("AZ",))
    student = published_student(nationality="AZ", allowed=("DE",), eligible_awards=(award,))
    refresh_cell_coverage(student.tenant_id)
    row = _row(student.tenant_id)
    assert row.students_no_floor == 0 and row.found_served == 1
    # A cell the award does not reach stays thin.
    other = _row(student.tenant_id, holder="EMPLOYER")
    assert (other.students_no_floor, other.found_served) == (1, 0)


def test_a_nationality_list_keeps_an_award_out_of_other_homes(published_student, served_award):
    served_award(nationalities=("GE",))
    student = published_student(nationality="AZ", eligible_awards=())
    refresh_cell_coverage(student.tenant_id)
    assert _row(student.tenant_id).found_served == 0


def test_an_award_with_no_readable_list_sits_in_every_home(served_award) -> None:
    listed = served_award(nationalities=("AZ", "GE"))
    unlisted = served_award()
    homes = {cell.home for cell, ids in served_cells().items() if listed.id in ids}
    assert homes == {"AZ", "GE"}
    assert {cell.home for cell, ids in served_cells().items() if unlisted.id in ids} == {"ANY"}


def test_refresh_forgets_an_inactive_student(published_student):
    student = published_student(nationality="AZ", eligible_awards=())
    refresh_cell_coverage(student.tenant_id)
    with tenant_scope(student.tenant_id):
        student.active = False
        student.save(update_fields=["active"])
    refresh_cell_coverage(student.tenant_id)
    with tenant_scope(student.tenant_id):
        assert not CellCoverage.objects.filter(active_students__gt=0).exists()


def test_an_unpublished_pack_is_not_counted(published_student):
    student = published_student(nationality="AZ", published=False)
    assert refresh_cell_coverage(student.tenant_id) == 0


def test_refresh_is_tenant_local(published_student, agency_b):
    student = published_student(nationality="AZ", eligible_awards=())
    refresh_cell_coverage(agency_b.id)
    with tenant_scope(agency_b.id):
        assert CellCoverage.objects.count() == 0
    refresh_cell_coverage(student.tenant_id)
    with tenant_scope(student.tenant_id):
        assert CellCoverage.objects.count() > 0
    refresh_cell_coverage(agency_b.id)  # agency B's rebuild never touches agency A's rows
    with tenant_scope(student.tenant_id):
        assert CellCoverage.objects.count() > 0


def test_verified_for_intake_reads_the_stored_cycle_verification(
    published_student, served_award
):
    open_award = served_award(nationalities=("AZ",))
    closed_award = served_award(nationalities=("AZ",))
    other_year = served_award(nationalities=("AZ",))
    FundingCycleVerification.objects.create(
        opportunity=open_award, intake_start_year=2027, state="UPCOMING"
    )
    FundingCycleVerification.objects.create(
        opportunity=closed_award, intake_start_year=2027, state="CLOSED_FOR_INTAKE"
    )
    FundingCycleVerification.objects.create(
        opportunity=other_year, intake_start_year=2028, state="OPEN"
    )
    student = published_student(nationality="AZ", intake=date(2027, 9, 1))
    refresh_cell_coverage(student.tenant_id)
    row = _row(student.tenant_id)
    assert (row.found_served, row.verified_for_intake) == (3, 1)


def _program_with_fee(amount: str, currency: str = "EUR"):
    from tests.funding.test_spine import _catalogue

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="APPLICATION_FEE", amount=Decimal(amount), currency=currency,
        period="ONE_OFF",
    )
    return program


def test_budget_unspent_is_false_with_no_rate_table(published_student):
    student = published_student(nationality="AZ", programs=(_program_with_fee("50"),))
    refresh_cell_coverage(student.tenant_id)  # production: rates=None
    assert _row(student.tenant_id).students_budget_unspent == 0


def test_budget_unspent_counts_a_thin_student_under_budget_with_rates(published_student):
    # make_profile's application budget is 500 USD; one 50 EUR fee is well under.
    student = published_student(nationality="AZ", programs=(_program_with_fee("50"),))
    refresh_cell_coverage(student.tenant_id, rates=EUR_RATES)
    assert _row(student.tenant_id).students_budget_unspent == 1


def test_fees_at_or_over_budget_are_not_unspent(published_student):
    from apps.funding.models import PackVersion

    student = published_student(nationality="AZ", programs=(_program_with_fee("700"),))
    with tenant_scope(student.tenant_id):
        pack = PackVersion.objects.get(run__profile_version__student=student)
        from apps.research.coverage import _profile

        profile = _profile(pack.run.profile_version)
        assert profile is not None
        assert budget_unspent(pack, profile, rates=EUR_RATES) is False
        assert budget_unspent(pack, profile, rates=None) is False


# --- The coverage line (Task 9) ----------------------------------------------

def _swept(stop: str, *, batches: int = 3) -> PassState:
    return PassState(swept=True, past_economic_stop=stop == "ECONOMIC",
                     batches_without_new=batches, stop_reason=stop)


def _line(country="DE", family="INDUSTRIAL_SPONSORSHIP", *, eligible=0, rung=None,
          passes=None) -> AreaLine:
    return AreaLine(country, family, eligible, rung, passes or PassState.never())


def _say(*areas, found=0, verified=0, running=True) -> str:
    return coverage_sentence(found=found, verified=verified, verification_running=running,
                             areas=tuple(areas))


def test_the_line_never_says_no_funding() -> None:
    sentence = _say(_line(), found=0)
    assert "no funding" not in sentence.lower()
    assert sentence.startswith("0 found in your cells; 0 verified for your intake; 1 areas")


def test_zero_verified_is_a_count_once_verification_runs() -> None:
    assert "0 verified for your intake" in _say(found=4, verified=0, running=True)
    assert "verification not yet running" in _say(found=4, verified=0, running=False)
    assert "3 verified for your intake" in _say(found=4, verified=3, running=True)


def test_a_thin_register_area_names_its_rung_and_its_denominator() -> None:
    rung = RungRow("TR", "PRIVATE_FOUNDATION", 1, "vgm_tr", listed=4028, known=1417, read=49)
    text = _say(_line("TR", "PRIVATE_FOUNDATION", rung=rung), found=3)
    assert "1,417 of 4,028 on a purpose-filtered register, 49 read" in text


def test_a_register_nobody_has_read_says_so_never_zero_known() -> None:
    rung = RungRow("AZ", "PRIVATE_FOUNDATION", 2, "az_banks", listed=52, known=0, read=0,
                   surveyed=False)
    text = _say(_line("AZ", "PRIVATE_FOUNDATION", rung=rung))
    assert "52 listed on a register without purpose, not yet read" in text
    assert "0 of 52" not in text


@pytest.mark.parametrize(
    ("stop", "words"),
    [
        ("PLATEAU", "stopped when three batches found nothing new"),
        ("ECONOMIC", "stopped where more searching cost more than it found"),
        ("EXHAUSTED", "every stored angle asked"),
        ("BUDGET", "paused (budget) — researching"),
        ("CLASSIFIER_LIMIT", "paused (classifier limit) — researching"),
    ],
)
def test_a_search_only_area_reports_its_stop_never_a_total(stop, words) -> None:
    text = _say(_line(passes=_swept(stop)))
    assert "search only" in text and words in text
    assert "%" not in text  # a search-only area never reads as a share of a whole


def test_a_pause_is_still_researching_and_a_stop_rule_is_not() -> None:
    assert _say(_line(passes=_swept("BUDGET"))).split(".")[0].endswith("— researching")
    assert "researching" not in _say(_line(passes=_swept("PLATEAU"))).split(";")[2]


def test_an_unswept_area_says_not_yet_searched_never_empty() -> None:
    text = _say(_line("AZ", "PRIVATE_FOUNDATION"))
    assert "AZ private foundation: not yet searched" in text


def test_a_family_with_no_pass_is_not_called_researching() -> None:
    text = _say(_line("DE", "UNIVERSITY_WIDE"))
    assert "no register and no search pass" in text
    assert "researching" not in text


def test_an_area_with_an_eligible_award_is_not_thin() -> None:
    assert "0 areas still thin." in _say(_line(eligible=1))


def test_the_line_names_at_most_six_areas_and_counts_all() -> None:
    areas = [_line(country=c) for c in ("AT", "BE", "CH", "DE", "ES", "FR", "IT", "NL")]
    text = _say(*areas)
    assert "8 areas still thin" in text and text.count("not yet searched") == 6


def test_student_coverage_reads_both_seams(profile_snapshot) -> None:
    class Rungs:
        def rungs(self, country: str) -> tuple[RungRow, ...]:
            return (RungRow(country, "PRIVATE_FOUNDATION", 1, "vgm_tr", 10, 4, 2),) \
                if country == "TR" else ()

    class Passes(NullSeams):
        def state(self, country: str, family: str) -> PassState:
            return _swept("PLATEAU") if family == "INDUSTRIAL_SPONSORSHIP" else PassState.never()

    profile = profile_snapshot(nationality="TR", country_of_residence="TR")
    coverage = student_coverage(profile, eligible={}, found=2, verified=1,
                                verification_running=True, rungs=Rungs(), passes=Passes())
    areas = {(a["country"], a["family"]): a for a in coverage["areas"]}
    assert areas[("TR", "PRIVATE_FOUNDATION")]["rung"] == 1
    assert areas[("TR", "INDUSTRIAL_SPONSORSHIP")]["stop_reason"] == "PLATEAU"
    assert areas[("TR", "GOVERNMENT_SCHOLARSHIP")]["rung"] == 4
    assert coverage["sentence"].startswith("2 found in your cells; 1 verified")


def test_an_award_counts_in_its_bodys_country(served_award) -> None:
    award = served_award(holder="PRIVATE_FOUNDATION", organisation_country="TR")
    assert eligible_by_area([award]) == {Area("TR", "PRIVATE_FOUNDATION"): 1}
