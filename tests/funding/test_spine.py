"""One student, one programme, one award, one pack.

The deliverable of slice 1. Every one of these failed before 2026-09-23 for the
reasons the spine spec's section 1 lists: the evaluator had no production
caller, the live path was a fixture skeleton, and nothing student-facing read
the reader's catalogue.
"""

import datetime as dt
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.accounts.profile_versions import create_profile_version
from apps.funding.models import (
    BenefitRule,
    CostComponent,
    FundingBenefit,
    FundingOpportunity,
    FundingOpportunityProgram,
    Institution,
    PackCandidate,
    PackVersion,
    Program,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.research.models import ConsultantResearchTask
from apps.research.register import record_organisation
from apps.research.schemas import ResearchMessage
from apps.research.services import handle_research_message
from apps.tenancy.context import tenant_scope
from tests.funding.conftest import EUR_RATES, make_profile

pytestmark = pytest.mark.django_db(transaction=True)


def _catalogue(*, with_award=True, program_name="MSc Computer Science"):
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.org",
    )
    program = Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name=program_name,
        campus_name="Main",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
    )
    award = None
    if with_award:
        organisation = record_organisation(
            domain="example-foundation.org",
            name="Example Foundation",
            kind="PRIVATE_FOUNDATION",
            country_code="DE",
            found_via="REGISTER",
        )
        award = FundingOpportunity.objects.create(
            canonical_key=f"read:holder:{uuid4()}",
            name="Foundation Stipend",
            family="PRIVATE_FOUNDATION",
            scope_type="HOLDER",
            holder="PRIVATE_FOUNDATION",
            holder_domain="example-foundation.org",
            holder_name="Example Foundation",
            organisation=organisation,
            agreement="AGREED",
            served=True,
            money_form="GRANT",
        )
    return program, award


def _award_only():
    organisation = record_organisation(
        domain="example-foundation.org",
        name="Example Foundation",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    return FundingOpportunity.objects.create(
        canonical_key=f"read:holder:{uuid4()}",
        name="Foundation Stipend",
        family="PRIVATE_FOUNDATION",
        scope_type="HOLDER",
        holder="PRIVATE_FOUNDATION",
        holder_domain="example-foundation.org",
        holder_name="Example Foundation",
        organisation=organisation,
        agreement="AGREED",
        served=True,
        money_form="GRANT",
    )


def _run(agency, membership, **profile_overrides):
    # FUNDING_FIRST by default, as the real consultation produces (tests/
    # acceptance/helpers.py). BALANCED is pinned separately below: it cannot
    # recommend a programme at all until upstream fit scoring exists.
    fields = {
        "target_field": "Computer Science",
        "intended_intake": dt.date(2027, 9, 1),
        "allowed_countries": (),
        "excluded_countries": (),
        "strategy": "FUNDING_FIRST",
    }
    fields.update(profile_overrides)
    snapshot = make_profile(**fields)
    with tenant_scope(agency.id):
        version = create_profile_version(student=membership, snapshot=snapshot)
        return RecommendationRun.objects.create(profile_version=version)


def _message(agency, run):
    return ResearchMessage(kind="run_research", tenant_id=agency.id, run_id=run.id)


def test_one_student_one_programme_one_award_becomes_a_pack(agency_a, membership_a):
    program, award = _catalogue()
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)

        assert pack.published_at is not None
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.PUBLISHED

        candidates = RecommendationCandidate.objects.filter(run=run)
        assert candidates.count() == 2
        # Each candidate points back at the catalogue row it came from.
        assert {c.program_id for c in candidates} == {program.id, None}
        assert {c.opportunity_id for c in candidates} == {award.id, None}
        assert PackCandidate.objects.filter(pack_version=pack).count() == 2


def test_the_award_is_its_own_application_not_a_discount(agency_a, membership_a):
    """Owner decision 2026-09-19. The programme candidate's gap must be the
    same whether or not an award exists -- counting money not yet won
    understates it by exactly the amount at risk."""
    program, _ = _catalogue(with_award=False)
    run = _run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        without = RecommendationCandidate.objects.get(run=run, program=program).funding_gap

    # The SAME programme, with an award now in the catalogue beside it.
    _award_only()
    second = _run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, second), rates=EUR_RATES)
        programme = RecommendationCandidate.objects.get(run=second, program=program)
        assert RecommendationCandidate.objects.filter(
            run=second, opportunity__isnull=False
        ).exists(), "the award must be in this pack for the comparison to mean anything"

    assert programme.funding_gap == without


def test_an_empty_pool_publishes_an_empty_pack_carrying_the_sentence(agency_a, membership_a):
    """P1-7: never a silently short pack. The reason names the field and the
    intake, so "we found nothing" is distinguishable from "we did not look"."""
    _catalogue(program_name="MA Art History", with_award=False)
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)

        assert pack.published_at is None
        run.refresh_from_db()
        assert run.state == RecommendationRun.State.DRAFT_READY
        task = ConsultantResearchTask.objects.get(
            url=f"https://review.invalid/empty-pool/{run.id}"
        )
        assert "Computer Science" in task.reason


def test_a_missing_rate_table_says_so_rather_than_inventing_one(agency_a, membership_a):
    """`parse_ecb_daily` and `parse_cbar_daily` have no production caller, so
    None is what a deployed worker passes today. Comparing currencies with a
    made-up table would produce a confident wrong gap."""
    _catalogue()
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=None)

        assert pack.published_at is None
        task = ConsultantResearchTask.objects.get(
            url=f"https://review.invalid/empty-pool/{run.id}"
        )
        assert "exchange-rate" in task.reason


def test_a_short_form_profile_names_the_consultation_it_needs(agency_a, membership_a):
    """A MinimalProfile carries a field, an intake and a budget. Widening it
    into a full snapshot would mean inventing the nationality and history the
    gates are about to reason from."""
    from apps.accounts.schemas import MinimalProfile

    _catalogue()
    with tenant_scope(agency_a.id):
        version = create_profile_version(
            student=membership_a,
            snapshot=MinimalProfile.model_validate(
                {
                    "target_field": "Computer Science",
                    "intended_intake": "2027-09-01",
                    "funding_dependency": "MANDATORY",
                    "strategy": "FUNDING_FIRST",
                    "application_budget": "150",
                }
            ),
        )
        run = RecommendationRun.objects.create(profile_version=version)
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)

        assert pack.published_at is None
        task = ConsultantResearchTask.objects.get(
            url=f"https://review.invalid/empty-pool/{run.id}"
        )
        assert "short form" in task.reason


def test_an_unserved_award_never_reaches_the_pack(agency_a, membership_a):
    """The serve gate is the catalog's promise and the spine does not
    second-guess it."""
    _, award = _catalogue()
    award.served = False
    award.save(update_fields=["served"])
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert not RecommendationCandidate.objects.filter(
            run=run, opportunity__isnull=False
        ).exists()


def test_a_second_message_for_one_run_returns_the_same_pack(agency_a, membership_a):
    """The run is taken with select_for_update and an existing pack short-
    circuits: a redelivered message must not publish a second pack."""
    _catalogue()
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        first = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        second = handle_research_message(_message(agency_a, run), rates=EUR_RATES)

    assert first.id == second.id
    with tenant_scope(agency_a.id):
        assert PackVersion.objects.filter(run=run).count() == 1


def test_a_balanced_student_gets_no_programme_and_is_told_the_score(agency_a, membership_a):
    """Measured, and left standing on purpose. `facts._NEUTRAL` is 50 across
    four dimensions because nothing scores qualitative fit yet; BALANCED needs
    80 overall and 60 per dimension, and 50 reaches 64. So every programme is
    excluded with its shortfall named -- visible rather than silent, and the
    reason is honest about the SCORE while misleading about the programme.

    Raising the constant to clear the bar would be manufacturing a pass. The
    fix is upstream fit scoring. This test is here so that fix has something
    that fails when it lands, rather than a silent behaviour change.
    """
    _catalogue(with_award=False)
    run = _run(agency_a, membership_a, strategy="BALANCED")

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert pack.published_at is None
        assert not RecommendationCandidate.objects.filter(run=run).exists()


def test_a_balanced_student_still_receives_awards(agency_a, membership_a):
    """The award gates carry no fit bar, so the half of the engine this slice
    exists to connect works for a BALANCED student even while the programme
    half cannot."""
    _catalogue()
    run = _run(agency_a, membership_a, strategy="BALANCED")

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert pack.published_at is not None
        assert RecommendationCandidate.objects.filter(
            run=run, opportunity__isnull=False
        ).count() == 1


# --- security audit 2026-09-23 ------------------------------------------------


def test_two_students_with_empty_pools_get_two_reasons_not_one(agency_a, membership_a):
    """Finding 2. `record_blocked_source` is `get_or_create` against a
    (tenant, url) unique constraint, and the reason is a `defaults` value -- so
    one constant URL per tenant meant the SECOND student's reason was silently
    dropped and they got no recorded reason at all. That is exactly the P1-7
    guarantee this slice claims to honour."""
    _catalogue(program_name="MA Art History", with_award=False)
    first = _run(agency_a, membership_a)
    second = _run(agency_a, membership_a, target_field="Marine Biology")

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, first), rates=EUR_RATES)
        handle_research_message(_message(agency_a, second), rates=EUR_RATES)

        tasks = ConsultantResearchTask.objects.filter(url__contains="empty-pool")
        assert tasks.count() == 2, "each student's run needs its own reason"
        reasons = {task.reason for task in tasks}
        assert any("Computer Science" in reason for reason in reasons)
        assert any("Marine Biology" in reason for reason in reasons)


def test_a_candidates_evidence_url_is_an_origin_never_a_synthesised_one(
    agency_a, membership_a
):
    """Finding 3. `_evidence_for` prefixed a canonical_key with https://, so a
    programme's evidence became `https://program:<uuid>` -- a fabricated string
    the UI captions as "program" and the report prints in full, under the label
    "Official source". Provenance comes from the origin or it is not
    provenance."""
    program, award = _catalogue()
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        for candidate in RecommendationCandidate.objects.filter(run=run):
            url = candidate.evidence.source_url
            assert not url.startswith("https://program:"), url
            assert not url.startswith("https://read:"), url
            host = candidate.evidence.source_domain
            assert "." in host, f"{host!r} is not a hostname a student can read ({url})"


def test_an_award_condition_no_profile_field_decides_opens_a_review_task(
    agency_a, membership_a
):
    """Characterisation before a refactor: the review list is what turns an
    UNDECIDABLE condition into work for a human, and publication is NOT held
    for it (phased requirements section 38). Nothing covered this path, so the
    third evaluate() pass it was computed by could have been cut blind."""
    from apps.funding.models import BenefitRule, FundingBenefit

    _, award = _catalogue()
    benefit = FundingBenefit.objects.create(
        opportunity=award, kind="STIPEND", period="MONTHLY", description="1,200 EUR monthly."
    )
    BenefitRule.objects.create(
        benefit=benefit,
        kind=BenefitRule.Kind.APPLICANT_CONDITION,
        scope_type="GLOBAL",
        condition_type="AFFILIATION",
        key="AFFINITY",
        operator="PRESENT",
        value="alumni association",
        rule_text="Open to members of the foundation's alumni association.",
    )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)

        assert pack.published_at is not None, "a review task must not hold the pack"
        assert ConsultantResearchTask.objects.filter(
            url__startswith=f"https://review.invalid/candidate/{run.id}/"
        ).exists()


def test_a_programme_candidates_funding_gap_is_a_real_figure(agency_a, membership_a):
    """The other half of the refactor's safety net: `funding_gap` must be the
    evaluator's own number. Asserting only that two runs agree would still pass
    if both became zero."""
    from decimal import Decimal

    from apps.funding.models import CostComponent

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap > 0, "a costed programme has a gap the student can read"
    assert candidate.currency == "EUR"
    assert candidate.funding_gap_is_placeholder is False


def test_every_skipped_row_in_one_run_records_its_own_reason(agency_a, membership_a):
    """PR #124 review, and the same defect class as finding 2 of that PR --
    which this function only half fixed.

    `record_blocked_source` is `get_or_create` against a (tenant, url) unique
    constraint with `reason` in `defaults`, so any URL constant across a run
    keeps the FIRST reason and drops the rest. Two origin-less rows in one run
    therefore recorded one of them, and a programme and an award without an
    origin collided with each other on the identical URL.
    """
    # Two JOINTLY-provided programmes: `Program.institution` is nullable for
    # those (the consortium's members live in awarding_institutions instead),
    # and an institution always HAS a website -- `institution_official_website_https`
    # requires one -- so a null institution is the reachable no-origin case.
    for name in ("MSc Computer Science A", "MSc Computer Science B"):
        Program.objects.create(
            institution=None,
            provision_type="JOINT",
            canonical_key=f"program:{uuid4()}",
            name=name,
            campus_name="Main",
            city="Berlin",
            country_code="DE",
            location_key="DE-BERLIN",
            degree_level="MASTER",
            teaching_languages=["English"],
            duration_months=12,
        )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        tasks = ConsultantResearchTask.objects.filter(url__contains="no-origin")
        assert tasks.count() == 2, "each skipped row needs its own reason"
        reasons = " ".join(task.reason for task in tasks)
        assert "MSc Computer Science A" in reasons
        assert "MSc Computer Science B" in reasons


def _programme_award(program, *, route, served=True):
    """One award a programme's OWN page states, as `write_funding_decision`
    writes it: PROGRAM scope, anchored to the programme both ways."""
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}",
        name="Departmental Tuition Waiver",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=served,
        money_form="FEE_WAIVER",
        route=route,
    )
    FundingOpportunityProgram.objects.create(opportunity=opportunity, program=program)
    return opportunity


def _costed_programme_with(route, *, served=True):
    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    opportunity = _programme_award(program, route=route, served=served)
    FundingBenefit.objects.create(
        opportunity=opportunity,
        kind="TUITION",
        amount=Decimal("12000"),
        currency="EUR",
        period="ANNUAL",
        description="Tuition is waived in full.",
    )
    return program, opportunity


def test_a_programmes_own_automatic_award_covers_its_cost(agency_a, membership_a):
    """The money attached to a programme IS `CandidateFacts.benefits` (spec
    10.2, 10.4). The spine passed `benefits=()` for every programme, so a
    waiver the programme's own page states never reduced anything and every
    costed programme looked unfunded."""
    program, _ = _costed_programme_with("AUTOMATIC_ON_ADMISSION")
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("0.00")


def test_a_competitive_programme_award_is_never_counted_as_coverage(agency_a, membership_a):
    """Same waiver, awarded by selection rather than on admission. Subtracting
    it would show every applicant a gap only the winners will have -- the same
    mistake as counting a HOLDER award as a discount, one scope down."""
    program, _ = _costed_programme_with("STUDENT_APPLIES_SEPARATELY")
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("12000.00")


def test_an_unserved_programme_award_never_reduces_a_gap(agency_a, membership_a):
    """The serve gate is the catalog's promise on every scope, not just HOLDER."""
    program, _ = _costed_programme_with("AUTOMATIC_ON_ADMISSION", served=False)
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("12000.00")


def test_a_programme_condition_no_profile_field_decides_opens_a_review_task(
    agency_a, membership_a
):
    """The other half of `rules=()`: a programme carried no applicant condition,
    so a bar its own page publishes reached neither the student nor a human.

    This programme is the run's only candidate and a review outcome excludes
    it, so there is nothing left to publish -- unlike the award case above,
    where the programme beside it carries the pack. What is asserted here is
    the task, which is the thing `rules=()` made unreachable.
    """
    program, opportunity = _costed_programme_with("AUTOMATIC_ON_ADMISSION")
    benefit = FundingBenefit.objects.get(opportunity=opportunity)
    BenefitRule.objects.create(
        benefit=benefit,
        kind=BenefitRule.Kind.APPLICANT_CONDITION,
        scope_type="GLOBAL",
        condition_type="AFFILIATION",
        key="AFFINITY",
        operator="PRESENT",
        value="departmental alumni",
        rule_text="The waiver is open to graduates of the department's own bachelor.",
    )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)

        assert ConsultantResearchTask.objects.filter(
            url=f"https://review.invalid/candidate/{run.id}/{program.id}"
        ).exists()
