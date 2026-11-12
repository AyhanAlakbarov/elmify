"""Owner decisions of 2026-10-24 on what a pack shows about money
(docs/superpowers/2026-10-24-external-audit-answer.md, section 11.3):

- a programme with no cost rows is "not yet costed", never a 0.00 gap;
- the student's own money is shown as what is left to find after it;
- at most three programmes whose application fee is not known, never as free;
- a mandatory-funding student sees a programme that selective funding, if won,
  would pay for -- labelled as conditional and ordered scholarship-first.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.schemas import Money
from apps.funding.evaluation import evaluate
from apps.funding.pack import MAX_FEE_NOT_KNOWN, build_pack
from tests.funding.conftest import (
    EUR_RATES,
    make_benefit,
    make_candidate,
    make_cost,
    make_profile,
)

# --- uncosted programmes --------------------------------------------------------


def test_a_programme_with_no_cost_rows_is_not_costed() -> None:
    profile = make_profile(strategy="FUNDING_FIRST")
    uncosted = make_candidate(program_id="uncosted", cost_components=(), benefits=())
    costed = make_candidate(
        program_id="costed", cost_components=(make_cost("TUITION", "3000.00"),), benefits=()
    )

    pack = build_pack(profile, [uncosted, costed], EUR_RATES)

    packed = {item.program_id: item for item in (*pack.fee_free, *pack.paid, *pack.fee_not_known)}
    assert packed["uncosted"].costed is False
    assert packed["costed"].costed is True


def test_an_application_fee_alone_is_not_a_costed_programme() -> None:
    profile = make_profile(
        strategy="FUNDING_FIRST", application_budget=Money(amount=Decimal("500"), currency="EUR")
    )
    fee_only = make_candidate(
        program_id="fee-only",
        cost_components=(make_cost("APPLICATION_FEE", "75.00", period="ONE_OFF"),),
        benefits=(),
    )

    pack = build_pack(profile, [fee_only], EUR_RATES)

    assert pack.paid[0].costed is False


# --- the student's own money ------------------------------------------------------


def test_the_packed_programme_carries_what_the_student_pays_themselves() -> None:
    profile = make_profile(
        strategy="FUNDING_FIRST",
        self_funding_capacity=Money(amount=Decimal("2000"), currency="EUR"),
    )
    candidate = make_candidate(
        program_id="p",
        duration_months=12,
        cost_components=(make_cost("TUITION", "5000.00"),),
        benefits=(),
    )

    pack = build_pack(profile, [candidate], EUR_RATES)

    packed = (*pack.fee_free, *pack.fee_not_known)[0]
    assert packed.gap == Decimal("5000.00")
    assert packed.self_funded == Decimal("2000.00")


# --- unknown application fees -----------------------------------------------------


def test_unknown_fee_programmes_are_their_own_group_capped_and_never_free() -> None:
    profile = make_profile(strategy="FUNDING_FIRST")
    unknown = [
        make_candidate(program_id=f"unknown-{n}", cost_components=(), benefits=())
        for n in range(MAX_FEE_NOT_KNOWN + 2)
    ]
    free = make_candidate(
        program_id="free",
        cost_components=(make_cost("APPLICATION_FEE", "0.00", period="ONE_OFF"),),
        benefits=(),
    )

    pack = build_pack(profile, [*unknown, free], EUR_RATES)

    assert MAX_FEE_NOT_KNOWN == 3
    assert [item.program_id for item in pack.fee_free] == ["free"]
    assert len(pack.fee_not_known) == MAX_FEE_NOT_KNOWN
    assert all(not item.fee_known for item in pack.fee_not_known)
    over = {item.program_id for item in pack.over_budget}
    assert len(over) == 2 and over <= {c.program_id for c in unknown}
    assert {e.reason_code for e in pack.excluded if e.program_id in over} == {
        "FEE_NOT_KNOWN_LIMIT"
    }


# --- gate 10: a winnable scholarship ------------------------------------------------


def _mandatory():
    return make_profile(
        strategy="FUNDING_FIRST", funding_dependency="MANDATORY", self_funding_capacity=None
    )


def _selective(amount: str) -> object:
    return make_benefit(
        accessibility="CAPACITY_LIMITED", amount=amount, eligibility_confidence="LIKELY"
    )


def test_selective_funding_that_would_pay_for_it_opens_the_programme() -> None:
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "6000.00"),), benefits=(_selective("6000.00"),)
    )

    assert evaluate(_mandatory(), candidate, EUR_RATES).outcome == "ELIGIBLE"


def test_selective_funding_that_falls_short_keeps_it_closed() -> None:
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "6000.00"),), benefits=(_selective("2000.00"),)
    )

    outcome = evaluate(_mandatory(), candidate, EUR_RATES)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("funding is mandatory" in reason for reason in outcome.reasons)


def test_an_uncosted_programme_is_never_winnable() -> None:
    """With no cost rows the gap is an unknown, not a zero: no scholarship can
    be shown to close it."""
    candidate = make_candidate(cost_components=(), benefits=(_selective("6000.00"),))

    assert evaluate(_mandatory(), candidate, EUR_RATES).outcome == "NOT_ELIGIBLE"


def test_a_winnable_programme_is_labelled_and_ordered_scholarship_first() -> None:
    candidate = make_candidate(
        program_id="winnable",
        cost_components=(make_cost("TUITION", "6000.00"),),
        benefits=(_selective("6000.00"),),
    )

    pack = build_pack(_mandatory(), [candidate], EUR_RATES)

    packed = (*pack.fee_free, *pack.fee_not_known)[0]
    assert packed.needs_selective_funding is True
    assert packed.ordering == "SCHOLARSHIP_FIRST"


def test_guaranteed_funding_needs_no_label() -> None:
    candidate = make_candidate(
        program_id="guaranteed",
        cost_components=(make_cost("TUITION", "6000.00"),),
        benefits=(make_benefit(accessibility="ORDINARY", amount="6000.00"),),
    )

    pack = build_pack(_mandatory(), [candidate], EUR_RATES)

    packed = (*pack.fee_free, *pack.fee_not_known)[0]
    assert packed.needs_selective_funding is False


# --- gate 10: big schemes (Hungaricum, Turkiye Burslari, the State Programme) -----------

TODAY = date(2026, 10, 24)


def _scheme(*, name="Stipendium Hungaricum", tuition="FULL", living="FULL", **link):
    from apps.funding.card import AwardCard
    from tests.funding.test_award_gates import _award

    card = AwardCard(
        route="STUDENT_APPLIES_SEPARATELY", tuition=tuition, living=living, amounts=(),
        duration_text="", duration_months=None, timing="UNSTATED", cycle="UNSTATED",
        unconfirmed=(),
    )
    return _award(award_id=name, name=name, card=card, **link)


def _hungarian_programme():
    return make_candidate(
        program_id="elte-msc",
        program_country_code="HU",
        location_key="HU-BUDAPEST",
        cost_components=(make_cost("TUITION", "6000.00"),),
        benefits=(),
    )


def test_a_full_cover_scheme_in_the_programme_s_country_opens_it() -> None:
    pack = build_pack(
        _mandatory(), [_hungarian_programme()], EUR_RATES,
        awards=[_scheme(scope="HOLDER", country_code="HU")], today=TODAY,
    )

    packed = (*pack.fee_free, *pack.fee_not_known)[0]
    assert packed.needs_selective_funding is True
    assert packed.winnable_with == ("Stipendium Hungaricum",)
    assert packed.ordering == "SCHOLARSHIP_FIRST"


def test_a_scheme_not_stating_full_tuition_and_living_does_not() -> None:
    pack = build_pack(
        _mandatory(), [_hungarian_programme()], EUR_RATES,
        awards=[_scheme(scope="HOLDER", country_code="HU", living="PARTIAL")], today=TODAY,
    )

    assert not (*pack.fee_free, *pack.fee_not_known, *pack.paid)


def test_a_home_country_scheme_is_never_linked_by_country() -> None:
    """The State Programme's country is Azerbaijan, the holder's; it pays for
    study abroad, so "same country" would pin it to Azerbaijani programmes."""
    baku = make_candidate(
        program_id="baku-msc", program_country_code="AZ", location_key="AZ-BAKU",
        cost_components=(make_cost("TUITION", "6000.00"),), benefits=(),
    )

    pack = build_pack(
        _mandatory(), [baku], EUR_RATES,
        awards=[_scheme(name="State Programme", scope="HOLDER", country_code="AZ")], today=TODAY,
    )

    assert _mandatory().nationality == "AZ"
    assert not (*pack.fee_free, *pack.fee_not_known, *pack.paid)


def test_a_home_country_scheme_listing_the_programme_does_open_it() -> None:
    """Once the State Programme carries its university list, the list links it."""
    pack = build_pack(
        _mandatory(), [_hungarian_programme()], EUR_RATES,
        awards=[
            _scheme(
                name="State Programme", scope="HOLDER", country_code="AZ",
                pays_for_program_ids=frozenset({"elte-msc"}),
            )
        ],
        today=TODAY,
    )

    packed = (*pack.fee_free, *pack.fee_not_known)[0]
    assert packed.winnable_with == ("State Programme",)


def test_a_review_outcome_holder_scheme_also_opens_gate_10() -> None:
    """B1: a HOLDER award with an undecidable country list (`POSSIBLY_ELIGIBLE_REVIEW`)
    is packed into `pack.awards` for consultant review and opens Gate 10 for the
    programme it pays for, matching attached awards in `spine.py`."""
    from tests.funding.conftest import make_applicant_condition

    undecidable_cit = make_applicant_condition(
        "CITIZENSHIP",
        benefit_id="Stipendium Hungaricum",
        operator="IN",
        value="",
        rule_text="Open to partner countries; list not read.",
    )
    pack = build_pack(
        _mandatory(),
        [_hungarian_programme()],
        EUR_RATES,
        awards=[
            _scheme(
                scope="HOLDER",
                country_code="HU",
                applicant_conditions=(undecidable_cit,),
            )
        ],
        today=TODAY,
    )

    packed = (*pack.fee_free, *pack.fee_not_known)[0]
    assert packed.needs_selective_funding is True
    assert packed.winnable_with == ("Stipendium Hungaricum",)
    assert len(pack.awards) == 1


# --- what the publish step copies for the page ---------------------------------------


@pytest.mark.django_db(transaction=True)
def test_published_copies_carry_not_costed_and_self_funding(agency_a, membership_a) -> None:
    """Through the real spine and publish: an uncosted catalogue programme is a
    placeholder gap ("not yet costed"), never a 0.00 added into the total."""
    from apps.funding.models import PackCandidate, RecommendationCandidate
    from apps.research.services import handle_research_message
    from apps.tenancy.context import tenant_scope
    from tests.funding.test_spine import _catalogue, _message, _run

    _catalogue()
    run = _run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        programme = RecommendationCandidate.objects.get(
            id__in=PackCandidate.objects.filter(pack_version=pack).values("candidate_id"),
            opportunity__isnull=True,
        )
    assert programme.funding_gap_is_placeholder is True
    assert programme.self_funded is None
    assert programme.funding_condition == ""


@pytest.mark.django_db(transaction=True)
def test_a_costed_programme_publishes_what_the_student_pays_themselves(
    agency_a, membership_a
) -> None:
    from apps.funding.models import CostComponent, PackCandidate, RecommendationCandidate
    from apps.research.services import handle_research_message
    from apps.tenancy.context import tenant_scope
    from tests.funding.test_spine import _catalogue, _message, _run

    program, _award = _catalogue()
    CostComponent.objects.create(
        program=program, kind="TUITION", amount=Decimal("5000.00"), currency="EUR",
        period="ANNUAL",
    )
    run = _run(
        agency_a, membership_a,
        self_funding_capacity=Money(amount=Decimal("2000"), currency="EUR"),
    )
    with tenant_scope(agency_a.id):
        pack = handle_research_message(_message(agency_a, run), rates=EUR_RATES)
        programme = RecommendationCandidate.objects.get(
            id__in=PackCandidate.objects.filter(pack_version=pack).values("candidate_id"),
            opportunity__isnull=True,
        )
    assert programme.funding_gap_is_placeholder is False
    assert programme.funding_gap == Decimal("5000.00")
    assert programme.self_funded == Decimal("2000.00")
    assert programme.left_to_find == Decimal("3000.00")


@pytest.mark.django_db
def test_the_page_shows_the_money_lines(client, agency_a, domain_a, user_a, membership_a) -> None:
    from apps.funding.models import RecommendationCandidate
    from apps.tenancy.context import tenant_scope
    from tests.funding.conftest import make_db_candidate, make_published_pack, make_run

    run = make_run(agency_a, membership_a)
    programme = make_db_candidate(
        agency_a, run, program_name="MSc Chemistry", funding_gap="5000.00"
    )
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(
            self_funded=Decimal("2000.00"),
            funding_condition="Affordable only if you win Stipendium Hungaricum. "
            "Apply for it before paying this programme's fees.",
            application_fee=None,
        )
    make_published_pack(agency_a, run, (programme,))
    client.force_login(user_a)
    body = client.get("/student/recommendation/", HTTP_HOST=domain_a.host).content.decode()

    assert "After the 2000.00 EUR you said you can cover yourself: 3000.00 EUR left to find" in body
    assert "Affordable only if you win Stipendium Hungaricum." in body
    assert "Application fee: not known" in body
