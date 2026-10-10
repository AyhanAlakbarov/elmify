from decimal import Decimal
from uuid import uuid4

import pytest

from apps.funding.card import AmountLine, AwardCard
from apps.funding.models import (
    FundingBenefit,
    FundingOpportunity,
    FundingOpportunityProgram,
    Program,
    RecommendationCandidate,
)
from apps.funding.pack import PackedAward
from apps.research.services import _award_copy
from apps.tenancy.context import tenant_scope


def _fund_the_programme() -> None:
    """The seeded programme is NOT_ELIGIBLE for this student (funding is
    mandatory and nothing funds it), so `_publish` never sees it. Attach a
    served programme-scope award with a stated stipend; the shared seed is
    left alone because other tests rely on its shape."""
    program = Program.objects.get(name="MSc Chemistry")
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"read:program:{uuid4()}",
        name="Chemistry stipend",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
        route="AUTOMATIC_ON_ADMISSION",
    )
    FundingOpportunityProgram.objects.create(opportunity=opportunity, program=program)
    FundingBenefit.objects.create(
        opportunity=opportunity,
        kind="STIPEND",
        amount=Decimal("1000"),
        currency="EUR",
        period="MONTHLY",
        description="x",
        amount_text="EUR 1,000",
        amount_bound="EXACT",
        amount_quote="EUR 1,000 a month.",
    )


@pytest.mark.django_db(transaction=True)
def test_the_worker_copies_what_the_board_shows_onto_each_candidate(slice_driver) -> None:
    run = slice_driver.student_submits_profile_and_starts_research()
    _fund_the_programme()
    slice_driver.worker_processes(slice_driver.receive_message())

    with tenant_scope(run.tenant_id):
        programme = RecommendationCandidate.objects.get(run=run, program__isnull=False)
        award = RecommendationCandidate.objects.get(
            run=run, opportunity__isnull=False, opportunity__scope_type="HOLDER"
        )

    assert programme.institution_name == "Example University"
    assert programme.country_code == "DE"
    assert programme.degree_level == "MASTER"
    assert programme.institution_id is not None
    assert programme.application_fee is not None
    assert programme.funding_card == {}
    assert award.funding_card["holder"] == "Example Foundation"
    assert award.funding_card["scope"] == "HOLDER"
    assert award.funding_card["deadline"] == ""
    assert award.funding_card["degree_levels"] == []
    assert award.funds_program_ids == []
    # HOLDER scope carries no country of its own; the holder's is the proxy.
    assert award.opportunity.organisation.country_code == "DE"
    assert award.country_code == "DE"


@pytest.mark.django_db
def test_an_award_copy_lists_the_programmes_it_funds_and_its_amounts(program_factory) -> None:
    # A PROGRAM-scope award is a benefit on its programme, never its own
    # candidate in the slice, so the copy is checked on the function.
    program = program_factory()
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"read:program:{uuid4()}",
        name="Programme stipend",
        family="DEPARTMENT_OR_PROGRAM",
        scope_type="PROGRAM",
        program=program,
        agreement="AGREED",
        served=True,
    )
    FundingOpportunityProgram.objects.create(opportunity=opportunity, program=program)
    packed = PackedAward(
        award_id=str(opportunity.id),
        name=opportunity.name,
        holder_name="Holder",
        deadline=None,
        ordering="FEE_FREE",  # type: ignore[arg-type]
        ordering_reason="",
        unconfirmed=(),
        card=AwardCard(
            route="",
            tuition="",
            living="",
            amounts=(
                AmountLine("STIPEND", "EUR 1,000", Decimal("1000"), "EUR", "MONTHLY", "EXACT", ""),
            ),
            duration_text="",
            duration_months=None,
            timing="",
            cycle="",
            unconfirmed=(),
        ),
    )

    copy = _award_copy(opportunity, packed)

    assert copy["funds_program_ids"] == [program.id]
    assert copy["funding_card"]["amounts"] == ["EUR 1,000"]  # type: ignore[index]


@pytest.mark.django_db
def test_only_a_holder_award_borrows_its_organisations_country() -> None:
    from apps.research.register import record_organisation

    organisation = record_organisation(
        domain="global-fund.example.org",
        name="Global Fund",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )
    opportunity = FundingOpportunity.objects.create(
        canonical_key=f"read:global:{uuid4()}",
        name="Global award",
        family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL",
        organisation=organisation,
        agreement="AGREED",
        served=True,
    )
    packed = PackedAward(
        award_id=str(opportunity.id),
        name=opportunity.name,
        holder_name="Global Fund",
        deadline=None,
        ordering="FEE_FREE",  # type: ignore[arg-type]
        ordering_reason="",
        unconfirmed=(),
    )

    assert _award_copy(opportunity, packed)["country_code"] == ""


def _global_award(**fields) -> FundingOpportunity:
    return FundingOpportunity.objects.create(
        canonical_key=f"read:global:{uuid4()}",
        name="Global award",
        family="PRIVATE_FOUNDATION",
        scope_type="GLOBAL",
        agreement="AGREED",
        served=True,
        **fields,
    )


def _packed(opportunity: FundingOpportunity) -> PackedAward:
    return PackedAward(
        award_id=str(opportunity.id),
        name=opportunity.name,
        holder_name="Global Fund",
        deadline=None,
        ordering="FEE_FREE",  # type: ignore[arg-type]
        ordering_reason="",
        unconfirmed=(),
    )


@pytest.mark.django_db
def test_the_award_copy_carries_its_duration() -> None:
    opportunity = _global_award(duration_months=12, duration_text="one year")
    card = _award_copy(opportunity, _packed(opportunity))["funding_card"]
    assert card["duration_months"] == 12  # type: ignore[index]
    assert card["duration_text"] == "one year"  # type: ignore[index]


@pytest.mark.django_db
def test_an_award_without_a_stated_duration_copies_none() -> None:
    opportunity = _global_award()
    card = _award_copy(opportunity, _packed(opportunity))["funding_card"]
    assert card["duration_months"] is None  # type: ignore[index]
    assert card["duration_text"] == ""  # type: ignore[index]
