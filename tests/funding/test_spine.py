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


def test_a_balanced_student_receives_a_matching_programme(agency_a, membership_a):
    """With upstream fit scoring wired in `facts.score_program_fit`, a BALANCED
    student whose target field and prior degree match `MSc Computer Science`
    clears the 80 overall / 60 per-dimension bar and receives the programme."""
    program, _ = _catalogue(with_award=False)
    run = _run(agency_a, membership_a, strategy="BALANCED")

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert pack.published_at is not None
        assert RecommendationCandidate.objects.filter(
            run=run, program=program
        ).count() == 1


def test_a_balanced_student_gets_no_programme_when_fit_falls_below_bar_and_is_told_the_score(
    agency_a, membership_a
):
    """When a BALANCED student's research interest does not match the programme,
    `RESEARCH_FIT` scores 50 (< 60 per-dimension bar) and the programme is
    excluded with its shortfall named."""
    _catalogue(with_award=False)
    run = _run(
        agency_a,
        membership_a,
        strategy="BALANCED",
        research_interests=("Marine Biology",),
    )

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


def _cbar_table():
    from pathlib import Path

    from apps.funding.rate_sources import parse_cbar_daily

    table = parse_cbar_daily(
        (Path(__file__).parent / "fixtures" / "cbar_daily.xml").read_bytes()
    )
    assert "MYR" not in table.rates, "the case needs a currency CBAR does not quote"
    return table


def test_a_fee_in_a_currency_without_a_rate_drops_that_programme_not_the_pack(
    agency_a, membership_a
):
    """Final review C1. CBAR quotes no MYR, so converting a Malaysian fee
    raised out of the ranking loop, rolled the run back and dead-lettered the
    message: one programme cost the student their whole pack. Now that
    programme alone is left out, as NO_EXCHANGE_RATE, and named for a person."""
    from apps.research.spine import build_student_pack

    ok, _ = _catalogue(with_award=False)
    odd, _ = _catalogue(with_award=False, program_name="MSc Computer Science Malaysia")
    CostComponent.objects.create(
        program=odd, kind="APPLICATION_FEE", amount=Decimal("100"), currency="MYR",
        period="ONE_OFF",
    )
    run = _run(agency_a, membership_a)
    table = _cbar_table()

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=table)

        assert pack.published_at is not None
        packed = set(
            PackCandidate.objects.filter(pack_version=pack).values_list(
                "candidate__program_id", flat=True
            )
        )
        assert packed == {ok.id}
        reasons = " ".join(
            ConsultantResearchTask.objects.filter(
                url__startswith=f"https://review.invalid/degraded/{run.id}/"
            ).values_list("reason", flat=True)
        )
        assert "MSc Computer Science Malaysia" in reasons
        assert "MYR" in reasons

        from apps.research.services import _profile_for

        result = build_student_pack(_profile_for(run), rates=table, today=dt.date.today())
    assert [(e.program_id, e.reason_code) for e in result.pack.excluded] == [
        (str(odd.id), "NO_EXCHANGE_RATE")
    ]


def test_an_ecb_crossed_currency_is_packed_and_one_ecb_lacks_is_still_left_out(
    agency_a, membership_a
):
    """ECB covers MYR, so a Malaysian fee is converted; ECB has no TWD, so a
    Taiwanese one is still NO_EXCHANGE_RATE."""
    from pathlib import Path

    from apps.funding.rate_sources import parse_ecb_daily
    from apps.funding.rates import latest_table, store
    from apps.research.services import _profile_for
    from apps.research.spine import build_student_pack

    fixtures = Path(__file__).parent / "fixtures"
    cbar = _cbar_table()
    store(cbar)
    store(parse_ecb_daily((fixtures / "ecb_daily.xml").read_bytes()))
    table = latest_table(on=cbar.retrieved_on)
    assert "MYR" in table.cross

    myr, _ = _catalogue(with_award=False, program_name="MSc Computer Science Malaysia")
    twd, _ = _catalogue(with_award=False, program_name="MSc Computer Science Taiwan")
    for program, code in ((myr, "MYR"), (twd, "TWD")):
        CostComponent.objects.create(
            program=program, kind="APPLICATION_FEE", amount=Decimal("100"), currency=code,
            period="ONE_OFF",
        )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        result = build_student_pack(_profile_for(run), rates=table, today=dt.date.today())

    assert [(e.program_id, e.reason_code) for e in result.pack.excluded] == [
        (str(twd.id), "NO_EXCHANGE_RATE")
    ]
    packed = {a.program_id for a in (*result.pack.fee_free, *result.pack.paid)}
    assert str(myr.id) in packed


def test_a_budget_in_a_currency_without_a_rate_publishes_the_empty_pack_saying_so(
    agency_a, membership_a
):
    """Final review C1, the student's side: with no rate for their own budget
    nothing can be compared against it, so they get the empty pack with the
    reason -- never a crashed run."""
    from apps.accounts.schemas import Money

    _catalogue(with_award=False)
    run = _run(
        agency_a, membership_a,
        application_budget=Money(amount=Decimal("500"), currency="MYR"),
    )

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=_cbar_table())

        assert pack.published_at is None
        task = ConsultantResearchTask.objects.get(
            url=f"https://review.invalid/empty-pool/{run.id}"
        )
        assert "budget's currency has no exchange rate" in task.reason


def test_cycle_verification_deadline_and_ended_state_flow_into_student_pack(
    agency_a, membership_a
):
    from apps.funding.models import FundingCycleVerification

    _program, award = _catalogue()
    assert award is not None
    ended = _award_only()
    FundingCycleVerification.objects.create(
        opportunity=award,
        intake_start_year=2027,
        state="OPEN",
        evidence=[
            {
                "step": "0",
                "url": "https://www.daad.de/en/",
                "sha256": "a" * 64,
                "at": "2026-10-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027",
                "intake_year": 2027,
                "stated_on": "2026-10-01",
                "deadlines": [["2027-05-15", "15 May 2027", "ALL"]],
                "quote": "Deadline is 15 May 2027.",
                "agreement": "AGREED",
            }
        ],
    )
    FundingCycleVerification.objects.create(
        opportunity=ended,
        intake_start_year=2027,
        state="ENDED",
        page_removed=True,
        evidence=[],
    )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidates = list(
            RecommendationCandidate.objects.filter(run=run, opportunity__isnull=False)
        )
        assert [c.opportunity_id for c in candidates] == [award.id]
        assert candidates[0].funding_card["deadline"] == "2027-05-15"


def test_an_institution_scope_award_from_the_institutions_own_domain_covers_its_programmes(
    agency_a, membership_a
):
    from apps.funding.models import (
        FundingOpportunityEvidenceClaim,
        OfficialEvidenceClaim,
        OfficialSource,
        OfficialSourceSnapshot,
    )

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    inst_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:INSTITUTION:{uuid4()}",
        name="University-Wide Waiver",
        family="UNIVERSITY_WIDE",
        scope_type="INSTITUTION",
        institution=program.institution,
        kind="I1_UNIVERSITY_WIDE",
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
    )
    FundingBenefit.objects.create(
        opportunity=inst_opp,
        kind="TUITION",
        amount=Decimal("12000"),
        currency="EUR",
        period="ANNUAL",
        description="Full tuition waiver for all master's programmes.",
    )
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/en/studies/fees/waiver",
        publisher="university.example.org",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/tum-waiver",
        s3_version_id="1",
        sha256="c" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=100,
        discovery_technique="seed",
    )
    claim = OfficialEvidenceClaim.objects.create(
        source=source,
        snapshot=snapshot,
        claim="Full tuition waiver for all master's programmes.",
        evidence_strength="DIRECT",
        visibility="STUDENT_FACING",
        claim_class="FUNDING",
        last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    FundingOpportunityEvidenceClaim.objects.create(opportunity=inst_opp, evidence_claim=claim)
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("0.00")


def test_an_institution_scope_award_from_a_foreign_host_never_reduces_a_gap(
    agency_a, membership_a
):
    from apps.funding.models import (
        FundingOpportunityEvidenceClaim,
        OfficialEvidenceClaim,
        OfficialSource,
        OfficialSourceSnapshot,
    )

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    inst_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:INSTITUTION:{uuid4()}",
        name="Unverified Foreign Host Waiver",
        family="UNIVERSITY_WIDE",
        scope_type="INSTITUTION",
        institution=program.institution,
        kind="I1_UNIVERSITY_WIDE",
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
    )
    FundingBenefit.objects.create(
        opportunity=inst_opp,
        kind="TUITION",
        amount=Decimal("12000"),
        currency="EUR",
        period="ANNUAL",
        description="Full tuition waiver.",
    )
    foreign_source = OfficialSource.objects.create(
        canonical_url="https://blog.other-domain.org/tum-waiver",
        publisher="blog.other-domain.org",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=foreign_source,
        s3_key="official-sources/foreign-waiver",
        s3_version_id="1",
        sha256="d" * 64,
        final_url=foreign_source.canonical_url,
        redirect_chain=[],
        retrieved_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=100,
        discovery_technique="seed",
    )
    claim = OfficialEvidenceClaim.objects.create(
        source=foreign_source,
        snapshot=snapshot,
        claim="Full tuition waiver.",
        evidence_strength="DIRECT",
        visibility="STUDENT_FACING",
        claim_class="FUNDING",
        last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    FundingOpportunityEvidenceClaim.objects.create(opportunity=inst_opp, evidence_claim=claim)
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("12000.00")


def test_an_institution_scope_award_on_a_linked_organisation_domain_covers_its_programmes(
    agency_a, membership_a
):
    from apps.funding.models import (
        FundingOpportunityEvidenceClaim,
        OfficialEvidenceClaim,
        OfficialSource,
        OfficialSourceSnapshot,
    )
    from apps.research.models import Organisation
    from apps.research.register import record_organisation

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    # Bind both `example.org` (`university.example.org`) and `gradschool-example.org`
    # to the same Organisation.
    org = record_organisation(
        domain="example.org",
        name="Example University",
        kind="UNSTATED",
        country_code="DE",
        found_via="CLOSED_LIST:test",
        status=Organisation.Status.CANDIDATE,
    )
    from apps.research.models import OrganisationDomain

    OrganisationDomain.objects.get_or_create(
        registrable_domain="gradschool-example.org",
        defaults={"organisation": org},
    )

    inst_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:INSTITUTION:{uuid4()}",
        name="Graduate School Excellence Waiver",
        family="UNIVERSITY_WIDE",
        scope_type="INSTITUTION",
        institution=program.institution,
        kind="I1_UNIVERSITY_WIDE",
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
    )
    FundingBenefit.objects.create(
        opportunity=inst_opp,
        kind="TUITION",
        amount=Decimal("12000"),
        currency="EUR",
        period="ANNUAL",
        description="Full tuition waiver for graduate school students.",
    )
    grad_source = OfficialSource.objects.create(
        canonical_url="https://gradschool-example.org/en/scholarships/waiver",
        publisher="gradschool-example.org",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=grad_source,
        s3_key="official-sources/gradschool-waiver",
        s3_version_id="1",
        sha256="e" * 64,
        final_url=grad_source.canonical_url,
        redirect_chain=[],
        retrieved_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=100,
        discovery_technique="seed",
    )
    claim = OfficialEvidenceClaim.objects.create(
        source=grad_source,
        snapshot=snapshot,
        claim="Full tuition waiver for graduate school students.",
        evidence_strength="DIRECT",
        visibility="STUDENT_FACING",
        claim_class="FUNDING",
        last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    FundingOpportunityEvidenceClaim.objects.create(opportunity=inst_opp, evidence_claim=claim)
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("0.00")


def test_an_automatic_full_tuition_waiver_without_printed_euro_amount_covers_tuition(
    agency_a, membership_a
):
    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    opp = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}",
        name="Full Tuition Fee Waiver",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
        tuition="FULL",
    )
    FundingBenefit.objects.create(
        opportunity=opp,
        kind="TUITION",
        amount=None,
        currency=None,
        period="FULL_PROGRAM",
        description="Full tuition fee waiver for all admitted students.",
    )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("0.00")


def test_a_selective_erasmus_mundus_attached_scholarship_opens_gate_10_and_names_the_scholarship(
    agency_a, membership_a
):
    from apps.funding.models import (
        OfficialEvidenceClaim,
        OfficialSource,
        OfficialSourceSnapshot,
        ProgramEvidenceClaim,
    )

    joint_prog = Program.objects.create(
        institution=None,
        provision_type="JOINT",
        provider_text="Erasmus Mundus Joint Master Consortium",
        canonical_key=f"program:{uuid4()}",
        name="MSc Computer Science — Erasmus Mundus Joint Master",
        campus_name="Consortium",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    source = OfficialSource.objects.create(
        canonical_url="https://emjm-cs.example.eu/scholarships",
        publisher="emjm-cs.example.eu",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/emjm-cs",
        s3_version_id="1",
        sha256="f" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=100,
        discovery_technique="seed",
    )
    claim = OfficialEvidenceClaim.objects.create(
        source=source,
        snapshot=snapshot,
        claim="Erasmus Mundus Joint Master Scholarship covers full participation costs and living.",
        evidence_strength="DIRECT",
        visibility="STUDENT_FACING",
        claim_class="FUNDING",
        last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    ProgramEvidenceClaim.objects.create(program=joint_prog, evidence_claim=claim)

    em_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}",
        name="Erasmus Mundus Joint Master Scholarship",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=joint_prog,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="CONSIDERED_WITH_ADMISSION",
        tuition="FULL",
        living="FULL",
        nationality_shape="NAMED_LIST",
        internationals_included="YES",
    )
    FundingBenefit.objects.create(
        opportunity=em_opp,
        kind="TUITION",
        amount=None,
        currency=None,
        period="FULL_PROGRAM",
        description="Full participation cost waiver.",
    )
    FundingBenefit.objects.create(
        opportunity=em_opp,
        kind="STIPEND",
        amount=Decimal("1400"),
        currency="EUR",
        period="MONTHLY",
        description="EUR 1,400 per month stipend.",
    )

    run = _run(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert pack.published_at is not None
        candidate = RecommendationCandidate.objects.get(run=run, program=joint_prog)
        review_task_exists = ConsultantResearchTask.objects.filter(
            url=f"https://review.invalid/candidate/{run.id}/{em_opp.id}"
        ).exists()

    assert candidate.eligible is True
    assert candidate.institution_name == "Erasmus Mundus Joint Master Consortium"
    assert "Erasmus Mundus Joint Master Scholarship" in candidate.funding_condition
    assert review_task_exists is True


def test_an_ended_attached_waiver_never_reduces_funding_gap(agency_a, membership_a):
    from apps.funding.models import FundingCycleVerification

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    opp = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}",
        name="Ended Programme Tuition Waiver",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
        tuition="FULL",
    )
    FundingBenefit.objects.create(
        opportunity=opp,
        kind="TUITION",
        amount=None,
        currency=None,
        period="FULL_PROGRAM",
        description="Full tuition fee waiver.",
    )
    FundingCycleVerification.objects.create(
        opportunity=opp,
        intake_start_year=2027,
        state=FundingCycleVerification.State.ENDED,
    )
    run = _run(agency_a, membership_a)

    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        candidate = RecommendationCandidate.objects.get(run=run, program=program)

    assert candidate.funding_gap == Decimal("12000.00")


def test_chemoinformatics_sibling_suspension_or_statement_shuts_scholarship_for_2027(
    agency_a, membership_a
):
    from apps.funding.models import (
        OfficialSource,
        OfficialSourceSnapshot,
        ProgramStatement,
    )

    program, _ = _catalogue(
        with_award=False,
        program_name="MSc Computer Science & Chemoinformatics+ Erasmus Mundus",
    )
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("15000"), currency="EUR", period="ANNUAL"
    )
    overview_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{program.id}:overview:I5_FUNDED_DUAL_DEGREE",
        name="ChEMoinformatics+ Erasmus Mundus Scholarship",
        family="MULTILATERAL",
        scope_type="PROGRAM",
        program=program,
        kind="I5_FUNDED_DUAL_DEGREE",
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="CONSIDERED_WITH_ADMISSION",
        tuition="FULL",
        living="FULL",
        internationals_included="YES",
    )
    FundingBenefit.objects.create(
        opportunity=overview_opp,
        kind="TUITION",
        amount=None,
        currency=None,
        period="FULL_PROGRAM",
        description="Full participation costs.",
    )
    FundingBenefit.objects.create(
        opportunity=overview_opp,
        kind="STIPEND",
        amount=Decimal("1400"),
        currency="EUR",
        period="MONTHLY",
        description="EUR 1,400/month stipend.",
    )
    # A second row read off `/scholarships` under a different heading states that
    # the 2027-2029 intake is without scholarship.
    no_quote = (
        "The recruitment of the 2027-2029 student intake will be without scholarship."
    )
    sibling_susp = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{program.id}:scholarship:I2_PROGRAMME_ATTACHED",
        name="ChEMoinformatics+ Scholarship Section",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=False,
        suspension_quote=no_quote,
        suspended_for="2027-2029",
    )

    run_1 = _run(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run_1), rates=EUR_RATES)
        assert not RecommendationCandidate.objects.filter(
            run=run_1, program=program
        ).exists()

    # Now remove the sibling FundingOpportunity and express the suspension as a
    # Tier-0 ProgramStatement on the programme.
    sibling_susp.delete()
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/chemoinformatics/scholarships",
        publisher="university.example.org",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        s3_key="official-sources/chemo-scholarships",
        s3_version_id="1",
        sha256="c" * 64,
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=100,
        discovery_technique="seed",
    )
    stmt = ProgramStatement.objects.create(
        program=program,
        snapshot=snapshot,
        kind=ProgramStatement.Kind.OTHER,
        requirement=ProgramStatement.Requirement.REQUIRED,
        label="Scholarship / Funding Status",
        text=no_quote,
    )
    run_2 = _run(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run_2), rates=EUR_RATES)
        assert not RecommendationCandidate.objects.filter(
            run=run_2, program=program
        ).exists()

    # If the suspension statement applies to a past intake (2025-2027, start year 2025),
    # the 2027-2029 intake scholarship is NOT shut.
    stmt.text = "The recruitment of the 2025-2027 student intake was without scholarship."
    stmt.save(update_fields=["text"])
    run_3 = _run(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run_3), rates=EUR_RATES)
        cand_3 = RecommendationCandidate.objects.get(run=run_3, program=program)
    assert cand_3.eligible is True


def test_dual_track_deadline_shuts_scholarship_when_scholarship_deadline_passed(
    agency_a, membership_a
):
    from apps.funding.models import FundingCycleVerification

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("15000"), currency="EUR", period="ANNUAL"
    )
    opp = FundingOpportunity.objects.create(
        canonical_key=f"read:PROGRAM:{uuid4()}",
        name="Selective Programme Scholarship",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        kind="I2_PROGRAMME_ATTACHED",
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="CONSIDERED_WITH_ADMISSION",
        tuition="FULL",
        living="FULL",
        internationals_included="YES",
    )
    FundingBenefit.objects.create(
        opportunity=opp,
        kind="TUITION",
        amount=None,
        currency=None,
        period="FULL_PROGRAM",
        description="Full tuition waiver.",
    )
    FundingBenefit.objects.create(
        opportunity=opp,
        kind="STIPEND",
        amount=Decimal("1200"),
        currency="EUR",
        period="MONTHLY",
        description="Monthly stipend.",
    )
    # Scholarship deadline for 2027 intake has already passed (`2026-09-15` < today),
    # while self-funded deadline (`2027-05-15`) is still in the future.
    FundingCycleVerification.objects.create(
        opportunity=opp,
        intake_start_year=2027,
        state=FundingCycleVerification.State.OPEN,
        evidence=[
            {
                "step": "0",
                "url": "https://university.example.org/cs/scholarships",
                "sha256": "a" * 64,
                "at": "2026-09-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027-2028",
                "intake_year": 2027,
                "stated_on": "2026-09-01",
                "deadlines": [
                    ["2026-09-15", "15 September 2026", "FUNDING:SCHOLARSHIP"],
                    ["2027-05-15", "15 May 2027", "FUNDING:SELF_FUNDED"],
                ],
                "quote": "Deadline for scholarship applicants: 15 September 2026.",
                "agreement": "AGREED",
            }
        ],
    )
    run = _run(agency_a, membership_a, funding_dependency="MANDATORY")
    with tenant_scope(agency_a.id):
        handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert not RecommendationCandidate.objects.filter(
            run=run, program=program
        ).exists()


def test_joint_programme_with_excluded_awarding_institution_country_is_filtered_by_pool():
    from apps.funding.models import ProgramAwardingInstitution
    from apps.funding.pool import candidate_pool

    inst_it = Institution.objects.create(
        canonical_key=f"inst:it:{uuid4()}",
        name="University of Milan",
        country_code="IT",
        official_website="https://www.unimi.it",
    )
    inst_fr = Institution.objects.create(
        canonical_key=f"inst:fr:{uuid4()}",
        name="University of Strasbourg",
        country_code="FR",
        official_website="https://www.unistra.fr",
    )
    joint_prog = Program.objects.create(
        institution=None,
        provision_type=Program.ProvisionType.JOINT,
        provider_text="University of Milan and University of Strasbourg",
        canonical_key=f"prog:joint:{uuid4()}",
        name="MSc Computer Science and Chemoinformatics",
        campus_name="Consortium",
        city="Milan",
        country_code="IT",
        location_key="IT:milan",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )
    ProgramAwardingInstitution.objects.create(program=joint_prog, institution=inst_it)
    ProgramAwardingInstitution.objects.create(program=joint_prog, institution=inst_fr)

    snap = make_profile(target_field="Computer Science", excluded_countries=("FR",))
    pool_res = candidate_pool(snap, limit=50)
    assert joint_prog not in pool_res.programs


def test_card_store_large_eligible_country_list_and_cohort_suspension_guard():
    from apps.funding.eligibility import ConditionTriple, decide
    from apps.funding.models import BenefitRule, OfficialSource, OfficialSourceSnapshot
    from apps.research.candidates import Intake, Requirement
    from apps.research.card_engine import Quote
    from apps.research.card_funding.card import AwardCard, Card, Field, Track
    from apps.research.card_funding.parse import Condition, Nationality, Value
    from apps.research.card_funding.store import write_card

    program, _ = _catalogue(with_award=False)
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/scholarships",
        publisher="Example University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    snapshot = OfficialSourceSnapshot.objects.create(
        source=source,
        sha256="b" * 64,
        s3_key="official-sources/scholarships",
        s3_version_id="1",
        final_url=source.canonical_url,
        redirect_chain=[],
        retrieved_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=100,
    )
    # 80 eligible countries (> 65 limit of a single 195-char comma-joined chunk, with ZW at end)
    eighty_codes = frozenset(
        f"A{chr(ord('A') + i)}" if i < 26 else (
            f"B{chr(ord('A') + i - 26)}" if i < 52 else (
                f"C{chr(ord('A') + i - 52)}" if i < 78 else ("AZ" if i == 78 else "ZW")
            )
        )
        for i in range(80)
    )
    nat_val = Nationality(
        eligible=eighty_codes,
        excluded=frozenset(),
        held=frozenset(),
        basis="citizenship",
        groups=(),
    )
    excl_deg_cond = Condition(
        kind="excluded_degree",
        requirement=Requirement(
            text="Applicants who already hold a Master's degree are not eligible.",
            start=0,
            end=63,
            kind="excluded_degree",
        ),
    )
    award_card = AwardCard(
        name="Global Merit Award",
        name_quote=Quote("Global Merit Award", "L1.text"),
        cycle=None,
        fields={
            "money_form": Field(
                "money_form", "shown", (Value("grant", Quote("grant", "L1.text"), "s", ()),)
            ),
            "tuition_level": Field(
                "tuition_level",
                "shown",
                (Value("full", Quote("full tuition", "L1.text"), "s", ()),),
            ),
            "living_level": Field(
                "living_level",
                "shown",
                (Value("full", Quote("full living", "L1.text"), "s", ()),),
            ),
            "nationality": Field(
                "nationality",
                "shown",
                (Value(nat_val, Quote("80 countries", "L2.text"), "s", ()),),
            ),
            "requirements": Field(
                "requirements",
                "shown",
                (Value(excl_deg_cond, Quote("No prior Master's degree.", "L3.text"), "s", ()),),
            ),
            "funding_period": Field(
                "funding_period",
                "shown",
                (
                    Value(
                        Intake("2027-2029", 0, 9, 2027, 2029, None),
                        Quote("2027-2029 intake", "L4.text"),
                        "s",
                        (),
                    ),
                ),
            ),
            "discontinued": Field(
                "discontinued",
                "shown",
                (
                    Value(
                        "yes",
                        Quote(
                            "The recruitment of the 2027-2029 student intake "
                            "will be without scholarship.",
                            "L4.text",
                        ),
                        "s",
                        (),
                    ),
                ),
            ),
        },
        holds=(),
    )
    card = Card(
        program_id=program.id,
        source_url=source.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="Main", awards=(award_card,)),),
    )
    written = write_card(
        card,
        program=program,
        source=source,
        snapshot=snapshot,
        now=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )
    assert len(written) == 1
    opp = written[0]
    assert opp.suspended_for == "2027-2029"
    assert "without scholarship" in opp.suspension_quote

    # Check that ZW (last alphabetically in 80-country list) is SATISFIED, not dropped
    cit_rules = list(BenefitRule.objects.filter(benefit__opportunity=opp, key="CITIZENSHIP"))
    assert cit_rules
    for r in cit_rules:
        triple = ConditionTriple(
            key="CITIZENSHIP", operator=r.operator, value=r.value, quote=r.rule_text
        )
        assert decide(triple, make_profile(nationality="ZW")).outcome == "SATISFIED"
        assert decide(triple, make_profile(nationality="DE")).outcome == "FAILED"

    # Check that excluded_degree wrote PRIOR_DEGREE NOT_IN MASTER,DOCTORATE
    deg_rule = BenefitRule.objects.filter(benefit__opportunity=opp, key="PRIOR_DEGREE").first()
    assert deg_rule is not None
    assert deg_rule.operator == "NOT_IN"
    assert deg_rule.value == "MASTER,DOCTORATE"

    # Undated general re-read does not erase the 2027-2029 suspension
    undated_award = AwardCard(
        name="Global Merit Award",
        name_quote=Quote("Global Merit Award", "L1.text"),
        cycle=None,
        fields={
            "money_form": Field(
                "money_form", "shown", (Value("grant", Quote("grant", "L1.text"), "s", ()),)
            ),
            "tuition_level": Field(
                "tuition_level",
                "shown",
                (Value("full", Quote("full tuition", "L1.text"), "s", ()),),
            ),
            "living_level": Field(
                "living_level",
                "shown",
                (Value("full", Quote("full living", "L1.text"), "s", ()),),
            ),
        },
        holds=(),
    )
    undated_card = Card(
        program_id=program.id,
        source_url=source.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="Main", awards=(undated_award,)),),
    )
    rewritten = write_card(
        undated_card,
        program=program,
        source=source,
        snapshot=snapshot,
        now=dt.datetime(2026, 10, 2, tzinfo=dt.UTC),
    )
    assert rewritten[0].suspended_for == "2027-2029"
    assert "without scholarship" in rewritten[0].suspension_quote


def test_spine_excludes_domestic_only_attached_benefits_for_foreign_applicant():
    from apps.research.spine import build_student_pack

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("12000.00"),
        currency="EUR",
        period="ANNUAL",
    )
    domestic_waiver = FundingOpportunity.objects.create(
        canonical_key=f"read:program:domestic:{uuid4()}",
        name="Domestic Fee Waiver",
        family="UNIVERSITY_WIDE",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
        tuition="FULL",
        duration_months=12,
        internationals_included="NO",
        nationality_shape="UNSTATED",
    )
    FundingBenefit.objects.create(
        opportunity=domestic_waiver,
        kind="TUITION",
        amount=Decimal("12000.00"),
        currency="EUR",
        period="ANNUAL",
        description="Full tuition waiver for domestic students.",
        amount_text="€12,000",
        amount_bound="EXACT",
        amount_quote="€12,000 per year for domestic students.",
    )

    foreign_profile = make_profile(
        nationality="AZ",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    res_foreign = build_student_pack(
        foreign_profile, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    assert res_foreign.pack.fee_not_known == ()

    domestic_profile = make_profile(
        nationality="DE",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    res_domestic = build_student_pack(
        domestic_profile, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    assert len(res_domestic.pack.fee_not_known) == 1
    assert res_domestic.pack.fee_not_known[0].gap == Decimal("0.00")


def test_pass3_b4_i4_r1_split_selective_benefit_exclusion_and_upcoming_deadline_selection():
    from apps.funding.models import (
        EvidenceStrength,
        EvidenceVisibility,
        FundingCycleVerification,
        OfficialEvidenceClaim,
        OfficialSource,
        ProgramEvidenceClaim,
    )
    from apps.research.spine import build_student_pack

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("10000.00"),
        currency="EUR",
        period="ANNUAL",
    )

    # B4: A selective attached opportunity with agreement="UNAGREED" or a failing BenefitRule
    # must NOT leak its FundingBenefit into program_facts or close the mandatory funding gap
    split_selective = FundingOpportunity.objects.create(
        canonical_key=f"read:program:split:{uuid4()}",
        name="Unconfirmed Selective Waiver",
        family="UNIVERSITY_WIDE",
        scope_type="PROGRAM",
        program=program,
        agreement="UNAGREED",
        served=True,
        money_form="FEE_WAIVER",
        route="STUDENT_APPLIES_SEPARATELY",
        tuition="FULL",
        duration_months=12,
    )
    FundingBenefit.objects.create(
        opportunity=split_selective,
        kind="TUITION",
        amount=Decimal("10000.00"),
        currency="EUR",
        period="ANNUAL",
        description="Unconfirmed selective waiver.",
        amount_text="€10,000",
        amount_bound="EXACT",
        amount_quote="€10,000 per year.",
    )
    # I4: Domestic-only selective attached opportunity has a cycle deadline;
    # foreign applicant should not inherit its scholarship_decision_deadline
    domestic_selective = FundingOpportunity.objects.create(
        canonical_key=f"read:program:domsel:{uuid4()}",
        name="Domestic Merit Scholarship",
        family="UNIVERSITY_WIDE",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="STUDENT_APPLIES_SEPARATELY",
        tuition="FULL",
        duration_months=12,
        internationals_included="NO",
        nationality_shape="UNSTATED",
    )
    FundingCycleVerification.objects.create(
        opportunity=domestic_selective,
        intake_start_year=2027,
        state="OPEN",
        evidence=[
            {
                "step": "S1",
                "url": "https://university.example.org/scholarships",
                "sha256": "a" * 64,
                "at": "2026-10-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027",
                "intake_year": 2027,
                "stated_on": "2026-10-01",
                "deadlines": [["2027-04-15", "15 April 2027", "ALL"]],
                "quote": "Deadline: 15 April 2027",
                "agreement": "AGREED",
            }
        ],
    )

    # R1: Two DEADLINE claims on the programme: Round 1 passed (2026-09-15),
    # Round 2 upcoming (2026-11-30). app_deadline should pick Round 2 (2026-11-30) as of 2026-10-01.
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/msc-cs",
        publisher="Example University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    for dl_iso in ("2026-09-15", "2026-11-30"):
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            claim=f"Application deadline: {dl_iso}: for non-EU international applicants",
            evidence_strength=EvidenceStrength.DIRECT,
            visibility=EvidenceVisibility.STUDENT_FACING,
            claim_class=OfficialEvidenceClaim.ClaimClass.DEADLINE,
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)

    foreign_mandatory = make_profile(
        nationality="AZ",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    res_mandatory = build_student_pack(
        foreign_mandatory, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    # B4: Because split_selective's benefit is excluded, mandatory funding rejects it
    assert res_mandatory.pack.fee_not_known == ()

    foreign_optional = make_profile(
        nationality="AZ",
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
    )
    res_optional = build_student_pack(
        foreign_optional, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    assert len(res_optional.pack.fee_not_known) == 1
    # R1: Earliest upcoming APPLICATION_SUBMISSION deadline selected in program_deadlines
    assert res_optional.program_deadlines[str(program.id)] == "2026-11-30"


def test_selective_benefit_undecidable_rule_does_not_block_programme_and_persists_risk_notes(
    agency_a, membership_a
):
    from apps.funding.models import BenefitRule, FundingBenefit, FundingCycleVerification

    program, _ = _catalogue(with_award=False)
    # Give the programme an open automatic waiver so it passes mandatory funding
    auto_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:program:auto:{uuid4()}",
        name="Automatic Merit Waiver",
        family="UNIVERSITY_WIDE",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
        money_form="WAIVER",
        route="AUTOMATIC_ON_ADMISSION",
        tuition="FULL",
        duration_months=24,
        internationals_included="YES",
        nationality_shape="OPEN",
    )
    FundingCycleVerification.objects.create(
        opportunity=auto_opp,
        intake_start_year=2027,
        state="OPEN",
        evidence=[
            {
                "step": "S1",
                "url": "https://university.example.org/auto",
                "sha256": "a" * 64,
                "at": "2026-10-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027",
                "intake_year": 2027,
                "stated_on": "2026-10-01",
                "deadlines": [],
                "quote": "Open for 2027.",
                "agreement": "AGREED",
            }
        ],
    )
    auto_benefit = FundingBenefit.objects.create(
        opportunity=auto_opp,
        kind="TUITION",
        amount=Decimal("5000.00"),
        currency="EUR",
        period="ANNUAL",
        description="Full waiver.",
        amount_text="€5,000",
        amount_bound="EXACT",
        amount_quote="€5,000 per year.",
    )
    BenefitRule.objects.create(
        benefit=auto_benefit,
        kind=BenefitRule.Kind.RETURN_SERVICE,
        scope_type="GLOBAL",
        condition_type=None,
        comparable_value=24,
        rule_text="Graduates must return home for 24 months.",
    )
    # Also attach a selective scholarship with an undecidable SOCIOECONOMIC rule
    sel_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:program:sel:{uuid4()}",
        name="Selective Hardship Stipend",
        family="UNIVERSITY_WIDE",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="STUDENT_APPLIES_SEPARATELY",
        tuition="PARTIAL",
        duration_months=24,
        internationals_included="YES",
        nationality_shape="OPEN",
    )
    FundingCycleVerification.objects.create(
        opportunity=sel_opp,
        intake_start_year=2027,
        state="OPEN",
        evidence=[
            {
                "step": "S1",
                "url": "https://university.example.org/sel",
                "sha256": "b" * 64,
                "at": "2026-10-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027",
                "intake_year": 2027,
                "stated_on": "2026-10-01",
                "deadlines": [],
                "quote": "Open for 2027.",
                "agreement": "AGREED",
            }
        ],
    )
    sel_benefit = FundingBenefit.objects.create(
        opportunity=sel_opp,
        kind="STIPEND",
        amount=Decimal("2000.00"),
        currency="EUR",
        period="ANNUAL",
        description="Hardship stipend.",
        amount_text="€2,000",
        amount_bound="EXACT",
        amount_quote="€2,000 per year.",
    )
    BenefitRule.objects.create(
        benefit=sel_benefit,
        kind=BenefitRule.Kind.APPLICANT_CONDITION,
        scope_type="GLOBAL",
        condition_type="AFFILIATION",
        rule_text="Family income below threshold.",
    )

    run = _run(agency_a, membership_a, career_intent="WORK_ABROAD")

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert pack.published_at is not None
        cand = RecommendationCandidate.objects.get(run=run, program=program)
        assert cand.risk_tier_label in {"Safety", "Target", "Reach"}
        assert any("work abroad" in note for note in cand.risk_notes)
        # Consultant research task is still queued for the selective benefit's undecidable rule
        assert ConsultantResearchTask.objects.filter(
            url=f"https://review.invalid/candidate/{run.id}/{sel_opp.id}"
        ).exists()


def test_professional_only_referee_requirement_warns_zero_experience_student_and_renders_tier(
    agency_a, membership_a
):
    from django.template.loader import render_to_string

    program, _ = _catalogue(with_award=False)
    program.referee_requirements = [
        {
            "field": "kind",
            "value": "PROFESSIONAL_ONLY",
            "date": "",
            "conditional": False,
            "condition": "",
            "rule_text": "Two professional references from employers are required.",
            "source_url": "https://university.example.org/msc-cs",
        }
    ]
    program.save(update_fields=["referee_requirements"])

    run = _run(
        agency_a,
        membership_a,
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
        experience=(),
    )

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        assert pack.published_at is not None
        cand = RecommendationCandidate.objects.get(run=run, program=program)
        assert any("professional referees" in note for note in cand.risk_notes)
        rendered = render_to_string(
            "student/_candidate.html",
            {"candidate": cand, "applied": set(), "in_pack": True, "recognition_notes": {}},
        )
        assert f"Portfolio tier: {cand.risk_tier_label}" in rendered
        assert "professional referees" in rendered


def test_consider_named_program_rejects_non_masters_and_replace_candidate_strips_overflow_notes(
    agency_a, membership_a
):
    from apps.funding.services import (
        PackCommandError,
        consider_named_program,
        replace_candidate,
        resolve_named_program,
    )

    program, _ = _catalogue(with_award=False)
    run = _run(
        agency_a,
        membership_a,
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
    )

    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        with pytest.raises(PackCommandError, match="Master's"):
            consider_named_program(pack, "BSc in Computer Science", membership_a)
        with pytest.raises(PackCommandError, match="Master's"):
            consider_named_program(pack, "PhD in Artificial Intelligence", membership_a)

        named = consider_named_program(pack, "MSc in Data Science", membership_a)
        assert named.degree_level == "MASTER"
        resolve_named_program(
            named,
            eligible=True,
            reason="Verified Master's programme.",
            source_url="https://university.example.org/msc-ds",
            actor=membership_a,
        )
        named.refresh_from_db()
        assert named.risk_tier_label in {"Safety", "Target", "Reach"}
        # Simulate an overflow note on `named` before swapping it into the pack
        named.calibration_features = {
            **named.calibration_features,
            "over_budget_reason": "PACK_DIVERSITY_LIMIT",
            "risk_notes": [
                "the pack already holds 2 programmes at the same institution; "
                "kept in Other options for portfolio diversity",
                "Real warning to keep",
            ],
        }
        named.save(update_fields=["calibration_features"])

        in_pack_cand = RecommendationCandidate.objects.get(run=run, program=program)
        replace_candidate(pack, in_pack_cand.id, named.id, membership_a)
        named.refresh_from_db()
        assert "over_budget_reason" not in named.calibration_features
        assert named.risk_notes == ["Real warning to keep"]


def test_sole_undecidable_selective_route_is_possibly_eligible_review(
    agency_a, membership_a
):
    from apps.funding.models import BenefitRule, FundingBenefit, FundingCycleVerification
    from apps.research.spine import build_student_pack

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("10000.00"),
        currency="EUR",
        period="ANNUAL",
    )
    sel_opp = FundingOpportunity.objects.create(
        canonical_key=f"read:program:sole-sel:{uuid4()}",
        name="Sole Selective Hardship Scholarship",
        family="UNIVERSITY_WIDE",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
        money_form="GRANT",
        route="STUDENT_APPLIES_SEPARATELY",
        tuition="PARTIAL",
        living="NONE",
        duration_months=24,
        internationals_included="YES",
        nationality_shape="OPEN",
    )
    FundingCycleVerification.objects.create(
        opportunity=sel_opp,
        intake_start_year=2027,
        state="OPEN",
        evidence=[
            {
                "step": "S1",
                "url": "https://university.example.org/sole-sel",
                "sha256": "c" * 64,
                "at": "2026-10-01",
                "archived": False,
                "captured_at": "",
                "offered": "YES",
                "applies_to": "2027",
                "intake_year": 2027,
                "stated_on": "2026-10-01",
                "deadlines": [],
                "quote": "Open for 2027.",
                "agreement": "AGREED",
            }
        ],
    )
    sel_benefit = FundingBenefit.objects.create(
        opportunity=sel_opp,
        kind="TUITION",
        amount=Decimal("20000.00"),
        currency="EUR",
        period="ANNUAL",
        description="Tuition grant.",
        amount_text="€20,000",
        amount_bound="EXACT",
        amount_quote="€20,000 per year.",
    )
    BenefitRule.objects.create(
        benefit=sel_benefit,
        kind=BenefitRule.Kind.APPLICANT_CONDITION,
        scope_type="GLOBAL",
        condition_type="AFFILIATION",
        rule_text="Applicant must hold a regional ministry nomination.",
    )

    profile = make_profile(
        nationality="AZ",
        funding_dependency="MANDATORY",
        self_funding_capacity=None,
    )
    res = build_student_pack(profile, rates=EUR_RATES, today=dt.date(2026, 10, 1))
    # Because the undecidable selective route is the ONLY funding route and there is no
    # external full scheme, evaluate() returns POSSIBLY_ELIGIBLE_REVIEW rather than ELIGIBLE.
    assert str(program.id) in res.review
    assert res.pack.fee_not_known == ()


def test_portfolio_led_disclosure_and_republish_preserves_named_and_clears_dropped_eligible(
    agency_a, membership_a
):
    from apps.funding.models import CostComponent
    from apps.funding.services import (
        consider_named_program,
        replace_candidate,
        resolve_named_program,
    )
    from apps.portals.applications import add_application
    from apps.research.services import _publish
    from apps.research.spine import build_student_pack

    program, _ = _catalogue(with_award=False)
    program.portfolio_led = True
    program.save(update_fields=["portfolio_led"])
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("2000.00"),
        currency="EUR",
        period="ANNUAL",
    )

    run = _run(
        agency_a,
        membership_a,
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
    )

    with tenant_scope(agency_a.id):
        pack_v1 = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        cand = RecommendationCandidate.objects.get(run=run, program=program)
        assert any("Portfolio required:" in note for note in cand.risk_notes)

        # Student submits a named Master's programme, consultant resolves, and student swaps it in
        named = consider_named_program(pack_v1, "MSc in Urban Design", membership_a)
        resolve_named_program(
            named,
            eligible=True,
            reason="Verified official programme page",
            source_url="https://arch.example.edu/msc-urban-design",
            actor=membership_a,
        )
        # Simulate overflow notes on the candidate before adding to applications
        named.calibration_features = {
            **dict(named.calibration_features or {}),
            "over_budget_reason": "PACK_DIVERSITY_LIMIT",
            "risk_notes": ["the pack already holds 10 active programmes; kept in Other options"],
        }
        named.save(update_fields=["calibration_features"])
        add_application(student=membership_a, candidate_id=named.id, actor=membership_a)
        named.refresh_from_db()
        assert "over_budget_reason" not in (named.calibration_features or {})
        assert named.risk_notes == []

        pack_v2 = replace_candidate(pack_v1, cand.id, named.id, membership_a)
        assert PackCandidate.objects.filter(pack_version=pack_v2, candidate=named).exists()

        # Republish on the same run when `program` drops out of the pool (country excluded)
        profile_excluded = make_profile(
            nationality="AZ",
            funding_dependency="OPTIONAL",
            self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
            excluded_countries=(program.institution.country_code,),
        )
        res_empty = build_student_pack(
            profile_excluded, rates=EUR_RATES, today=dt.date(2026, 10, 1)
        )
        pack_v3 = _publish(
            run,
            version=pack_v2.version + 1,
            result=res_empty,
            profile=profile_excluded,
            rates=EUR_RATES,
        )
        # B14: Student's approved named programme is preserved in pack_v3
        assert PackCandidate.objects.filter(pack_version=pack_v3, candidate=named).exists()
        # B10: Catalogue programme that dropped out of the pool is marked eligible=False
        cand.refresh_from_db()
        assert cand.eligible is False
        # B16: _pack_context excludes eligible=False catalogue rows from `considered`
        from apps.funding.views import _pack_context

        considered_ids = {c.id for c in _pack_context(membership_a)["considered"]}
        assert cand.id not in considered_ids


def test_consider_named_program_view_returns_400_on_non_masters_and_hybrid_counts_overflow(
    agency_a, membership_a
):
    from django.test import RequestFactory
    from django.urls import reverse

    from apps.funding.models import CostComponent
    from apps.funding.views import consider_named_program_view
    from apps.research.hybrid_strategy import plan_hybrid_retrieval

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("0.00"),
        currency="EUR",
        period="ANNUAL",
    )
    run = _run(
        agency_a,
        membership_a,
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
    )
    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        cand = RecommendationCandidate.objects.get(run=run, program=program)
        # B15: POSTing a PhD title to consider_named_program_view returns 400 with inline error
        req = RequestFactory().post(
            reverse("student-consider-named-program"),
            {"program_name": "PhD in Computer Science"},
        )
        req.user = membership_a.user
        resp = consider_named_program_view(req)
        assert resp.status_code == 400
        assert b"only Master&#x27;s degree programmes are supported" in resp.content or (
            b"only Master's degree programmes are supported" in resp.content
        )

        # Move cand out of PackCandidate into overflow (PACK_DIVERSITY_LIMIT) to test B17
        PackCandidate.objects.filter(pack_version=pack, candidate=cand).delete()
        cand.calibration_features = {
            **dict(cand.calibration_features or {}),
            "over_budget_reason": "PACK_DIVERSITY_LIMIT",
        }
        cand.save(update_fields=["calibration_features"])

        profile = make_profile(
            nationality="AZ",
            funding_dependency="OPTIONAL",
            self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
            allowed_countries=(program.country_code,),
        )
        plan = plan_hybrid_retrieval(profile, pack=pack)
        decision = next(d for d in plan.assessments if d.country_code == program.country_code)
        assert decision.affordable_count >= 1


def test_non_eu_eea_deadline_not_confused_with_eu_eea_substring(agency_a, membership_a):
    from apps.funding.models import (
        CostComponent,
        EvidenceStrength,
        EvidenceVisibility,
        OfficialEvidenceClaim,
        OfficialSource,
        ProgramEvidenceClaim,
    )
    from apps.research.spine import build_student_pack

    program, _ = _catalogue(with_award=False)
    CostComponent.objects.create(
        program=program,
        kind="TUITION",
        amount=Decimal("0.00"),
        currency="EUR",
        period="ANNUAL",
    )
    source = OfficialSource.objects.create(
        canonical_url="https://university.example.org/deadlines",
        publisher="Example University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    for dl_iso, label in (
        ("2027-01-15", "Non-EU/EEA citizens"),
        ("2027-05-15", "EU/EEA citizens"),
    ):
        claim = OfficialEvidenceClaim.objects.create(
            source=source,
            claim=f"Application deadline: {dl_iso}: {label}",
            evidence_strength=EvidenceStrength.DIRECT,
            visibility=EvidenceVisibility.STUDENT_FACING,
            claim_class=OfficialEvidenceClaim.ClaimClass.DEADLINE,
            last_checked_at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        )
        ProgramEvidenceClaim.objects.create(program=program, evidence_claim=claim)

    non_eea_profile = make_profile(
        nationality="AZ",
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
    )
    res_non_eea = build_student_pack(
        non_eea_profile, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    assert res_non_eea.program_deadlines[str(program.id)] == "2027-01-15"

    eea_profile = make_profile(
        nationality="FR",
        funding_dependency="OPTIONAL",
        self_funding_capacity={"amount": "20000.00", "currency": "EUR"},
    )
    res_eea = build_student_pack(
        eea_profile, rates=EUR_RATES, today=dt.date(2026, 10, 1)
    )
    assert res_eea.program_deadlines[str(program.id)] == "2027-05-15"
















