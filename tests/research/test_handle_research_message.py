from datetime import date

import pytest
from django.utils import timezone

from apps.accounts.profile_versions import create_profile_version
from apps.accounts.schemas import MinimalProfile
from apps.funding.models import (
    FundingCycleVerification,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import reject_candidate
from apps.research.coverage import NO_PROFILE_COVERAGE
from apps.research.models import CellCoverage, ClosedList, ConsultantResearchTask, RegisterEntry
from apps.research.schemas import ResearchMessage
from apps.research.services import (
    _is_publishable_confidence,
    handle_research_message,
    rebuild_pack,
)
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import EUR_RATES
from tests.funding.test_spine import _catalogue
from tests.funding.test_spine import _run as _full_run


def _run(agency, membership) -> RecommendationRun:
    """A SHORT-FORM profile, deliberately. The full-profile path lives in
    tests/funding/test_spine.py; this module keeps the minimal one, because it
    is the case that used to be indistinguishable from a working pack."""
    with tenant_scope(agency.id):
        profile = create_profile_version(
            student=membership,
            snapshot=MinimalProfile.model_validate(
                {
                    "target_field": "Chemistry",
                    "intended_intake": "2027-09-01",
                    "funding_dependency": "MANDATORY",
                    "strategy": "FUNDING_FIRST",
                    "application_budget": "150",
                }
            ),
        )
        return RecommendationRun.objects.create(profile_version=profile)


def test_is_publishable_confidence_excludes_only_low():
    assert _is_publishable_confidence("HIGH") is True
    assert _is_publishable_confidence("MEDIUM") is True
    assert _is_publishable_confidence("LOW") is False


@pytest.mark.django_db(transaction=True)
def test_handle_research_message_auto_publishes_the_pack(agency_a, membership_a):
    """Rewritten 2026-09-23. It used to pass a JSON fixture whose `eligible`
    field the handler hard-coded to True, so it proved the plumbing and never
    the engine. It now goes through the catalogue the reader writes."""
    _catalogue()
    run = _full_run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)

    with tenant_scope(agency_a.id):
        pack = handle_research_message(message, rates=EUR_RATES)
        assert pack.published_at is not None
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.PUBLISHED
        assert PackCandidate.objects.filter(pack_version=pack).count() == 2


@pytest.mark.django_db(transaction=True)
def test_a_short_form_profile_publishes_nothing_and_says_which_consultation_is_missing(
    agency_a, membership_a
):
    """The replacement for the old low-confidence test, which drove its path by
    monkeypatching `RecommendationCandidate.objects.create`. This is the same
    guarantee -- P1-11, a blocked run leaves an operator-visible record -- on a
    condition the code actually reaches: a MinimalProfile cannot be widened
    into the snapshot the gates need without inventing a nationality and an
    academic history.
    """
    _catalogue()
    run = _run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)

    with tenant_scope(agency_a.id):
        pack = handle_research_message(message, rates=EUR_RATES)
        assert PackCandidate.objects.filter(pack_version=pack).count() == 0
        assert pack.published_at is None
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.DRAFT_READY
        task = ConsultantResearchTask.objects.get(
            url=f"https://review.invalid/empty-pool/{run.id}",
            state=ConsultantResearchTask.State.OPEN,
        )
        assert "short form" in task.reason


# --- The coverage line on every pack (demand cells, Task 9) ------------------

def _publish_full(agency, membership, *, rates=EUR_RATES, **profile):
    run = _full_run(agency, membership, **profile)
    message = ResearchMessage(kind="run_research", tenant_id=agency.id, run_id=run.id)
    with tenant_scope(agency.id):
        return run, handle_research_message(message, rates=rates)


@pytest.mark.django_db(transaction=True)
def test_the_published_pack_carries_its_coverage(agency_a, membership_a):
    _catalogue()
    _, pack = _publish_full(agency_a, membership_a)
    assert pack.published_at is not None
    assert set(pack.coverage) >= {"found", "verified", "verification_running", "areas",
                                  "sentence"}
    # The catalogue's one served award is a HOLDER row with no nationality
    # list: host ANY, home ANY, so it is in this student's cells.
    assert pack.coverage["found"] == 1
    assert pack.coverage["sentence"].startswith(
        "1 found in your cells; verification not yet running;"
    )
    # Its body is German, so the DE private-foundation area is not thin.
    areas = {(a["country"], a["family"]): a for a in pack.coverage["areas"]}
    assert areas[("AZ", "PRIVATE_FOUNDATION")]["eligible"] == 0
    with tenant_scope(agency_a.id):
        assert PackVersion.objects.get(id=pack.id).coverage == pack.coverage


@pytest.mark.django_db(transaction=True)
def test_the_coverage_names_the_real_closed_list_rung(agency_a, membership_a):
    _catalogue()
    ClosedList.objects.create(
        slug="vgm_tr", title="VGM", country_code="TR", holder_kinds=["PRIVATE_FOUNDATION"],
        rung=1, source_url="https://example.org/vgm", maintainer="VGM", carries_purpose=True,
        carries_website=True, reuse_terms="UNREAD", is_denominator=True,
        read_policy="FUNDING_READ", printed_size=4028, verified_on=date(2026, 9, 25),
    )
    RegisterEntry.objects.create(
        register="vgm_tr", external_key="1", name="TEV", resolution="UNRESOLVED",
        last_seen=timezone.now(),
    )
    _, pack = _publish_full(agency_a, membership_a, nationality="TR", country_of_residence="TR")
    areas = {(a["country"], a["family"]): a for a in pack.coverage["areas"]}
    tr = areas[("TR", "PRIVATE_FOUNDATION")]
    assert (tr["rung"], tr["register"]) == (1, "vgm_tr")
    assert "0 of 4,028 on a purpose-filtered register" in tr["clause"]
    assert areas[("TR", "INDUSTRIAL_SPONSORSHIP")]["clause"].endswith("not yet searched")


@pytest.mark.django_db(transaction=True)
def test_verified_is_a_real_count_once_verification_runs(agency_a, membership_a):
    _, award = _catalogue()
    FundingCycleVerification.objects.create(
        opportunity=award, intake_start_year=2027, state="OPEN"
    )
    _, pack = _publish_full(agency_a, membership_a)
    assert pack.coverage["verified"] == 1 and pack.coverage["verification_running"]
    assert "1 verified for your intake" in pack.coverage["sentence"]


@pytest.mark.django_db(transaction=True)
def test_publishing_rebuilds_the_tenants_cell_coverage(agency_a, membership_a):
    _catalogue()
    _publish_full(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        row = CellCoverage.objects.get(
            holder="PRIVATE_FOUNDATION", host_country="ANY", home_country="AZ",
            discipline_bucket="unclassifiable",
        )
    # The packed award sits in this cell, so the student has a floor there.
    assert (row.active_students, row.students_no_floor, row.found_served) == (1, 0, 1)


@pytest.mark.django_db(transaction=True)
def test_an_empty_pack_still_carries_coverage_and_counts_nowhere(agency_a, membership_a):
    """rates=None is what a deployed worker has: the spine publishes nothing
    and the run goes DRAFT_READY -- the coverage line is still computed."""
    _catalogue()
    run, pack = _publish_full(agency_a, membership_a, rates=None)
    assert pack.published_at is None
    with tenant_scope(agency_a.id):
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.DRAFT_READY
        assert CellCoverage.objects.count() == 0  # only published packs are counted
    assert pack.coverage["found"] == 1
    assert pack.coverage["sentence"].startswith("1 found in your cells")


@pytest.mark.django_db(transaction=True)
def test_a_short_form_pack_says_its_cells_need_the_consultation(agency_a, membership_a):
    _catalogue()
    run = _run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)
    with tenant_scope(agency_a.id):
        pack = handle_research_message(message, rates=EUR_RATES)
    assert pack.coverage == NO_PROFILE_COVERAGE
    assert "no funding" not in pack.coverage["sentence"].lower()


@pytest.mark.django_db(transaction=True)
def test_the_handler_stays_idempotent(agency_a, membership_a):
    _catalogue()
    run, first = _publish_full(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)
    with tenant_scope(agency_a.id):
        again = handle_research_message(message, rates=EUR_RATES)
        assert again.id == first.id
        assert PackVersion.objects.filter(run=run).count() == 1


@pytest.mark.django_db(transaction=True)
def test_rebuild_writes_the_next_published_version_with_coverage(agency_a, membership_a):
    _catalogue()
    run, first = _publish_full(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        second = rebuild_pack(run, rates=EUR_RATES)
        first.refresh_from_db()
        assert (second.version, second.published_at is not None) == (2, True)
        assert first.superseded_at is not None
        assert second.coverage["found"] == 1


@pytest.mark.django_db(transaction=True)
def test_an_empty_rebuild_never_replaces_a_published_pack(agency_a, membership_a):
    _catalogue()
    run, first = _publish_full(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        same = rebuild_pack(run, rates=None)  # no rates: the spine packs nothing
        assert same.id == first.id
        assert PackVersion.objects.filter(run=run).count() == 1
        assert ConsultantResearchTask.objects.filter(
            url=f"https://review.invalid/empty-rebuild/{run.id}"
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_a_student_command_carries_the_coverage_line_to_the_new_version(
    agency_a, membership_a
):
    """reject/replace run in the web tier, which cannot read the catalogue:
    the line is copied, never recomputed there."""
    _catalogue()
    _, pack = _publish_full(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        award_candidate = RecommendationCandidate.objects.get(
            run=pack.run, opportunity__isnull=False
        )
        newer = reject_candidate(pack, award_candidate.id, membership_a)
        assert newer.coverage == pack.coverage
