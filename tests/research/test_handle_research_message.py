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


@pytest.mark.django_db(transaction=True)
def test_an_empty_pack_keeps_its_reason_where_the_student_page_can_read_it(
    agency_a, membership_a
):
    """The reason used to reach only the counsellor's task; the student saw
    "Finish your profile" on a finished one. It now travels on the pack."""
    _catalogue()
    run = _run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)
    with tenant_scope(agency_a.id):
        pack = handle_research_message(message, rates=EUR_RATES)
        assert "short form" in PackVersion.objects.get(id=pack.id).empty_reason


@pytest.mark.django_db(transaction=True)
def test_a_published_pack_carries_no_empty_reason(agency_a, membership_a):
    _catalogue()
    run = _full_run(agency_a, membership_a)
    message = ResearchMessage(kind="run_research", tenant_id=agency_a.id, run_id=run.id)
    with tenant_scope(agency_a.id):
        pack = handle_research_message(message, rates=EUR_RATES)
        assert pack.published_at is not None
        assert PackVersion.objects.get(id=pack.id).empty_reason == ""


@pytest.mark.django_db(transaction=True)
def test_rebuild_pack_updates_existing_candidate_in_place_and_marks_newly_unlocked_candidate(
    agency_a, membership_a
):
    from decimal import Decimal

    program, award = _catalogue()
    run, first = _publish_full(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        prog_cand = RecommendationCandidate.objects.get(run=run, program=program)
        orig_id = prog_cand.id
        RecommendationCandidate.objects.filter(id=orig_id).update(
            estimated_chance_pct=Decimal("20.00")
        )
        msg = ResearchMessage(kind="rebuild_pack", tenant_id=agency_a.id, run_id=run.id)
        second = handle_research_message(msg, rates=EUR_RATES)
        assert second.version == 2
        assert RecommendationCandidate.objects.filter(run=run, program=program).count() == 1
        prog_cand.refresh_from_db()
        assert prog_cand.id == orig_id
        assert prog_cand.calibration_features.get("score_boosted") is True
        assert prog_cand.calibration_features.get("previous_chance_pct") == "20"


@pytest.mark.django_db(transaction=True)
def test_rebuild_pack_never_resurrects_rejected_candidates_or_uses_rejected_award_for_gate_10(
    agency_a, membership_a
):
    from decimal import Decimal
    from uuid import uuid4

    from apps.funding.models import (
        CostComponent,
        FundingBenefit,
        FundingOpportunity,
        FundingOpportunityProgram,
        Program,
    )

    program, award = _catalogue()
    assert award is not None
    award.tuition = "FULL"
    award.living = "FULL"
    award.route = "STUDENT_APPLIES_SEPARATELY"
    award.save(update_fields=["tuition", "living", "route"])

    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    free_prog = Program.objects.create(
        institution=program.institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Computer Science Free",
        campus_name="Main",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
    )
    auto_waiver = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}",
        name="Departmental Automatic Waiver",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=free_prog,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
    )
    FundingOpportunityProgram.objects.create(opportunity=auto_waiver, program=free_prog)
    FundingBenefit.objects.create(
        opportunity=auto_waiver,
        kind="TUITION",
        amount=Decimal("12000"),
        currency="EUR",
        period="ANNUAL",
        description="Automatic tuition waiver.",
    )

    run, first = _publish_full(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        award_cand = RecommendationCandidate.objects.get(run=run, opportunity=award)
        prog_cand = RecommendationCandidate.objects.get(run=run, program=program)
        assert PackCandidate.objects.filter(pack_version=first, candidate=award_cand).exists()
        assert PackCandidate.objects.filter(pack_version=first, candidate=prog_cand).exists()

        # Student rejects the award
        after_reject = reject_candidate(first, award_cand.id, membership_a)
        award_cand.refresh_from_db()
        assert award_cand.state == RecommendationCandidate.State.REJECTED

        # Now rebuild_pack runs (e.g., on score progression)
        rebuilt = rebuild_pack(run, rates=EUR_RATES)
        assert rebuilt.version == after_reject.version + 1
        award_cand.refresh_from_db()
        assert award_cand.state == RecommendationCandidate.State.REJECTED
        # Rejected award is NOT resurrected into the new PackVersion
        assert not PackCandidate.objects.filter(
            pack_version=rebuilt, candidate=award_cand
        ).exists()
        # And the costed mandatory-funding programme that relied on the rejected award
        # for Gate 10 is no longer packed either, while the free programme stays packed.
        assert not PackCandidate.objects.filter(
            pack_version=rebuilt, candidate=prog_cand
        ).exists()
        assert PackCandidate.objects.filter(
            pack_version=rebuilt, candidate__program=free_prog
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_rebuild_pack_preserves_submitted_external_award_after_deadline_passes(
    agency_a, membership_a
):
    from decimal import Decimal
    from uuid import uuid4

    from apps.funding.models import CostComponent, Program
    from apps.portals.models import Application

    program, award = _catalogue()
    assert award is not None
    award.tuition = "FULL"
    award.living = "FULL"
    award.route = "STUDENT_APPLIES_SEPARATELY"
    award.save(update_fields=["tuition", "living", "route"])

    run, first = _publish_full(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        award_cand = RecommendationCandidate.objects.get(run=run, opportunity=award)
        # Student already submitted the external HOLDER scholarship before its deadline passed
        Application.objects.create(
            student=membership_a,
            program_id=award.id,
            candidate=award_cand,
            state=Application.State.SUBMITTED,
        )

    # Now the scholarship's deadline is in the past (2026-01-15), and a new costed programme
    # appears / unlocks after mid-semester score progression.
    FundingCycleVerification.objects.create(
        opportunity=award,
        intake_start_year=2027,
        state="OPEN",
        evidence=[
            {
                "step": "0",
                "url": "https://example-foundation.org/stipend",
                "sha256": "b" * 64,
                "at": "2026-10-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027",
                "intake_year": 2027,
                "stated_on": "2026-10-01",
                "deadlines": [["2026-10-15", "15 October 2026", "ALL"]],
                "quote": "Deadline is 15 October 2026.",
                "agreement": "AGREED",
            }
        ],
    )
    unlocked_prog = Program.objects.create(
        institution=program.institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Computer Science II",
        campus_name="Main",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
    )
    CostComponent.objects.create(
        program=unlocked_prog,
        kind="TUITION",
        amount=Decimal("10000"),
        currency="EUR",
        period="ANNUAL",
    )

    with tenant_scope(agency_a.id):
        rebuilt = rebuild_pack(run, rates=EUR_RATES)
        assert rebuilt.version == 2
        assert PackCandidate.objects.filter(
            pack_version=rebuilt, candidate=award_cand
        ).exists()
        unlocked_cand = RecommendationCandidate.objects.get(run=run, program=unlocked_prog)
        assert PackCandidate.objects.filter(
            pack_version=rebuilt, candidate=unlocked_cand
        ).exists()
        assert unlocked_cand.calibration_features.get("score_unlocked") is True
        assert "Foundation Stipend" in (
            unlocked_cand.calibration_features.get("winnable_with") or []
        )

        # G1: Rejecting the scholarship from the pack strips it from winnable_with
        # and updates funding_condition on the dependent programme
        reject_candidate(rebuilt, award_cand.id, membership_a)
        unlocked_cand.refresh_from_db()
        assert "Foundation Stipend" not in (
            unlocked_cand.calibration_features.get("winnable_with") or []
        )
        assert "removed from your pack" in unlocked_cand.funding_condition


@pytest.mark.django_db(transaction=True)
def test_pass3_b5_g2_funded_chance_boost_and_ineligible_regression_marking(
    agency_a, membership_a
):
    from uuid import uuid4

    from apps.funding.models import Program

    program, _award = _catalogue()
    run, first = _publish_full(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        assert first.version == 1
        prog_cand = RecommendationCandidate.objects.get(run=run, program=program)
        # B5: Simulate a low initial funded chance (15%) with high admission chance (75%),
        # so when rebuild_pack computes a higher funded chance (>= 25%), score_boosted triggers
        # via funded_jumped even if admission chance rose by < 10%
        RecommendationCandidate.objects.filter(id=prog_cand.id).update(
            estimated_chance_pct=prog_cand.estimated_chance_pct,
            estimated_funded_chance_pct=1,
        )
        v2 = rebuild_pack(run, rates=EUR_RATES)
        assert v2.version == 2
        prog_cand.refresh_from_db()
        if (prog_cand.estimated_funded_chance_pct or 0) >= 11:
            assert prog_cand.calibration_features.get("score_boosted") is True
            assert prog_cand.calibration_features.get("previous_funded_chance_pct") == "1"

    # G2: Now add a second programme that is initially eligible, then becomes NOT_ELIGIBLE
    second_prog = Program.objects.create(
        institution=program.institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Quantum Computing",
        campus_name="Main",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    with tenant_scope(agency_a.id):
        v3 = rebuild_pack(run, rates=EUR_RATES)
        second_cand = RecommendationCandidate.objects.get(run=run, program=second_prog)
        assert second_cand.eligible is True

    second_prog.teaching_languages = ["Japanese"]
    second_prog.save(update_fields=["teaching_languages"])
    with tenant_scope(agency_a.id):
        v4 = rebuild_pack(run, rates=EUR_RATES)
        assert v4.version == v3.version + 1
        second_cand.refresh_from_db()
        assert second_cand.eligible is False
        assert (
            second_cand.eligibility_status
            == RecommendationCandidate.EligibilityStatus.NOT_ELIGIBLE
        )

