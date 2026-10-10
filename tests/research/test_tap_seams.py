"""The seams item 14 consumes (tap_seams.py) and their two real bindings.

The bindings read real ClosedList / RegisterEntry / SweepRun / SweepQuery /
SweepDiscovery rows, built the way test_harness.py and test_tally.py build them.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.research.models import (
    ClosedList,
    Organisation,
    RegisterEntry,
    SweepAngle,
    SweepDiscovery,
    SweepQuery,
    SweepRun,
)
from apps.research.register import record_organisation
from apps.research.seam_bindings import ClosedListRungSource, SweepRunPassStates
from apps.research.tap_seams import (
    AngleSource,
    CellSweeper,
    HostReader,
    NullSeams,
    PassState,
    PassStates,
    RungSource,
    bound_angles,
    bound_host_reader,
    bound_pass_states,
    bound_rungs,
    bound_sweeper,
)

NOW = datetime(2026, 9, 25, tzinfo=UTC)


def test_null_seams_and_the_bindings_satisfy_every_protocol() -> None:
    # Annotated assignments: mypy checks each against its Protocol.
    null = NullSeams()
    angles: AngleSource = null
    passes: PassStates = null
    reader: HostReader = null
    sweeper: CellSweeper = null
    rungs: RungSource = null
    real_rungs: RungSource = ClosedListRungSource()
    real_passes: PassStates = SweepRunPassStates()
    assert all(seam is not None for seam in (angles, passes, reader, sweeper, rungs))
    assert real_rungs is not None and real_passes is not None
    assert PassState.never().swept is False
    assert PassState.never() == PassState(False, False, 0, "")


def test_what_is_bound_today() -> None:
    assert isinstance(bound_rungs(), ClosedListRungSource)
    assert isinstance(bound_pass_states(), SweepRunPassStates)
    # Not bindable on master (see their docstrings), and the sweeper is next.
    assert isinstance(bound_angles(), NullSeams)
    assert isinstance(bound_host_reader(), NullSeams)
    assert isinstance(bound_sweeper(), NullSeams)


# --- ClosedListRungSource ----------------------------------------------------


def _list(slug: str, kinds: list[str], rung: int, *, country: str = "TR", **extra: object) -> None:
    ClosedList.objects.create(
        slug=slug, title=slug, country_code=country, holder_kinds=kinds, rung=rung,
        source_url=f"https://example.org/{slug}", maintainer="own", carries_purpose=True,
        carries_website=True, reuse_terms="OWN_COMPILATION", is_denominator=True,
        read_policy="SIGNAL_ONLY", verified_on=date(2026, 9, 25), **extra,
    )


def _entry(register: str, key: str, *, org: Organisation | None = None) -> None:
    if org is None:
        RegisterEntry.objects.create(
            register=register, external_key=key, name=key, resolution="UNRESOLVED",
            last_seen=NOW,
        )
    else:
        RegisterEntry.objects.create(
            register=register, external_key=key, name=key, resolution="RESOLVED",
            resolved_via="EMAIL", organisation=org, last_seen=NOW,
        )


def _org(domain: str, *, funds: bool) -> Organisation:
    org = record_organisation(domain=domain, name=domain, kind="UNSTATED", country_code="TR",
                              found_via="R0_EMAIL")
    Organisation.objects.filter(pk=org.pk).update(funds_students=funds, classified_at=NOW)
    return Organisation.objects.get(pk=org.pk)


@pytest.mark.django_db
def test_a_read_register_reports_listed_known_and_read() -> None:
    _list("vgm_tr", ["PRIVATE_FOUNDATION"], 1)
    funds, other = _org("a-vakfi.org.tr", funds=True), _org("b-vakfi.org.tr", funds=False)
    _entry("vgm_tr", "1", org=funds)
    _entry("vgm_tr", "2", org=funds)  # a second entry of the same body counts once
    _entry("vgm_tr", "3", org=other)
    _entry("vgm_tr", "4")
    (row,) = ClosedListRungSource().rungs("TR")
    assert (row.family, row.rung, row.register) == ("PRIVATE_FOUNDATION", 1, "vgm_tr")
    assert (row.listed, row.known, row.read, row.surveyed) == (4, 2, 1, True)


@pytest.mark.django_db
def test_the_printed_size_is_the_denominator_when_the_publisher_prints_one() -> None:
    _list("vgm_tr", ["PRIVATE_FOUNDATION"], 1, printed_size=4028)
    _entry("vgm_tr", "1")
    (row,) = ClosedListRungSource().rungs("TR")
    assert row.listed == 4028


@pytest.mark.django_db
def test_the_lowest_rung_wins_and_ties_go_by_slug() -> None:
    _list("z_hubs", ["PRIVATE_FOUNDATION"], 3)
    _list("b_register", ["RELIGIOUS"], 2)
    _list("a_register", ["POLITICAL_FOUNDATION"], 2)
    (row,) = ClosedListRungSource().rungs("TR")
    assert (row.rung, row.register) == (2, "a_register")


@pytest.mark.django_db
def test_each_family_gets_its_own_rung() -> None:
    _list("tr_foundations", ["PRIVATE_FOUNDATION"], 1)
    _list("tr_employers", ["EMPLOYER"], 2)
    rows = {row.family: row.rung for row in ClosedListRungSource().rungs("TR")}
    assert rows == {"PRIVATE_FOUNDATION": 1, "INDUSTRIAL_SPONSORSHIP": 2}


@pytest.mark.django_db
def test_rung_zero_rung_four_other_countries_and_unstated_are_no_rung() -> None:
    _list("enumerator", ["PRIVATE_FOUNDATION"], 0)
    _list("search_only", ["PRIVATE_FOUNDATION"], 4)
    _list("unplaced", ["UNSTATED"], 1)
    _list("az_foundations", ["PRIVATE_FOUNDATION"], 1, country="AZ")
    assert ClosedListRungSource().rungs("TR") == ()


@pytest.mark.django_db
def test_an_unread_list_is_listed_but_not_yet_read_never_zero_known() -> None:
    _list("tr_banks", ["BANK_OR_LENDER"], 2, printed_size=52)
    (row,) = ClosedListRungSource().rungs("TR")
    assert (row.family, row.surveyed, row.listed) == ("PRIVATE_FOUNDATION", False, 52)


# --- SweepRunPassStates ------------------------------------------------------


def _angle() -> SweepAngle:
    return SweepAngle.objects.create(
        country_code="TR", family="PRIVATE_FOUNDATION", language="tr", angle="APPLICATION",
        sample=0, version=1, cycle="2026-2027", query="burs başvurusu", written_by="t",
    )


def _run(*, started: datetime, finished: bool = True, stop: str = "PLATEAU",
         batches: int = 0, family: str = "PRIVATE_FOUNDATION") -> SweepRun:
    return SweepRun.objects.create(
        country_code="TR", family=family, languages=["tr", "en"], rung=4, cycle="2026-2027",
        started_at=started, finished_at=started + timedelta(hours=1) if finished else None,
        stop_reason=stop if finished else "", batches=batches,
    )


def _found(run: SweepRun, angle: SweepAngle, batch: int, domain: str, *, verified: bool) -> None:
    query = SweepQuery.objects.create(run=run, batch_number=batch, angle=angle, provider="exa")
    org = record_organisation(domain=domain, name=domain, kind="UNSTATED", country_code="",
                              found_via="R4_SEARCH:exa")
    SweepDiscovery.objects.create(run=run, query=query, organisation=org,
                                  verified_in_pass=verified)


@pytest.mark.django_db
def test_an_area_never_swept_reads_never() -> None:
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION") == PassState.never()


@pytest.mark.django_db
def test_an_unfinished_run_is_not_a_state() -> None:
    _run(started=NOW, finished=False)
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION") == PassState.never()


@pytest.mark.django_db
def test_the_latest_finished_run_is_the_state() -> None:
    _run(started=NOW - timedelta(days=10), stop="ECONOMIC")
    _run(started=NOW, stop="PLATEAU", batches=3)
    _run(started=NOW + timedelta(days=1), finished=False)  # still running: ignored
    _run(started=NOW + timedelta(days=2), family="GOVERNMENT_SCHOLARSHIP", stop="BUDGET")
    state = SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION")
    assert state.swept and state.stop_reason == "PLATEAU"
    assert state.past_economic_stop is False


@pytest.mark.django_db
def test_an_economic_stop_is_past_the_economic_stop() -> None:
    _run(started=NOW, stop="ECONOMIC", batches=2)
    state = SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION")
    assert state.past_economic_stop and state.stop_reason == "ECONOMIC"


@pytest.mark.django_db
def test_trailing_batches_count_back_to_the_last_verified_discovery() -> None:
    run, angle = _run(started=NOW, batches=5), _angle()
    _found(run, angle, 1, "a.org.tr", verified=True)
    _found(run, angle, 2, "b.org.tr", verified=True)
    _found(run, angle, 3, "c.org.tr", verified=False)  # found, not verified: no credit
    # batches 4 and 5 found nothing at all
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION").batches_without_new == 3


@pytest.mark.django_db
def test_a_run_that_never_verified_anything_is_empty_in_every_batch() -> None:
    _run(started=NOW, batches=3)
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION").batches_without_new == 3


@pytest.mark.django_db
def test_a_last_batch_that_verified_leaves_no_trailing_batches() -> None:
    run, angle = _run(started=NOW, stop="EXHAUSTED", batches=2), _angle()
    _found(run, angle, 2, "a.org.tr", verified=True)
    assert SweepRunPassStates().state("TR", "PRIVATE_FOUNDATION").batches_without_new == 0
