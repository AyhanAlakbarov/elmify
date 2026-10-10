"""The pack's second list: awards as applications of their own.

Spec section 10.3, owner decision 2026-09-19.
"""

import datetime as dt

from apps.funding.pack import build_pack
from apps.funding.validity import Evidence
from tests.funding.conftest import EUR_RATES, make_benefit, make_candidate, make_cost
from tests.funding.test_award_gates import _award

TODAY = dt.date(2026, 9, 23)


def _candidate(**overrides):
    return make_candidate(
        cost_components=(make_cost("TUITION", "12000", "EUR", "ANNUAL"),),
        benefits=(make_benefit("TUITION", id="benefit-1", amount="6000"),),
        **overrides,
    )


def test_an_awards_money_is_not_counted_against_a_programmes_cost(profile):
    """Owner decision 2026-09-19: an award is an application, not a discount.
    Counting money not yet won understates the gap by exactly the amount at
    risk -- the amount that decides whether the student can go at all."""
    candidate = _candidate()

    without = build_pack(profile, [candidate], EUR_RATES, today=TODAY)
    with_award = build_pack(
        profile, [candidate], EUR_RATES, awards=[_award()], today=TODAY
    )

    assert with_award.fee_free == without.fee_free
    assert with_award.paid == without.paid
    assert len(with_award.awards) == 1


def test_an_award_application_carries_its_own_deadline_and_holder(profile):
    award = _award(evidence=Evidence(deadline=dt.date(2027, 1, 15)))

    pack = build_pack(profile, [_candidate()], EUR_RATES, awards=[award], today=TODAY)

    (packed,) = pack.awards
    assert packed.deadline == dt.date(2027, 1, 15)
    assert packed.holder_name == "Example Foundation"
    assert packed.name == "Foundation Stipend"


def test_an_award_deciding_before_a_fee_deadline_orders_scholarship_first(profile):
    candidate = _candidate(application_deadline=dt.date(2027, 3, 1))
    award = _award(evidence=Evidence(deadline=dt.date(2027, 1, 15)))

    pack = build_pack(profile, [candidate], EUR_RATES, awards=[award], today=TODAY)

    (packed,) = pack.awards
    assert packed.ordering == "SCHOLARSHIP_FIRST"
    assert "deferred" in packed.ordering_reason


def test_an_award_deciding_after_the_fee_deadline_does_not(profile):
    candidate = _candidate(application_deadline=dt.date(2027, 1, 1))
    award = _award(evidence=Evidence(deadline=dt.date(2027, 3, 15)))

    pack = build_pack(profile, [candidate], EUR_RATES, awards=[award], today=TODAY)
    assert pack.awards[0].ordering == "PARALLEL_OR_UNIVERSITY_FIRST"


def test_every_excluded_award_is_published_with_its_reason(profile):
    """P1-7: visible with the reason, never a silently short pack."""
    shut = _award(evidence_confidence="LOW")

    pack = build_pack(profile, [_candidate()], EUR_RATES, awards=[shut], today=TODAY)

    assert pack.awards == ()
    excluded = [item for item in pack.excluded if item.program_id == "award-1"]
    assert len(excluded) == 1
    assert excluded[0].reasons


def test_an_awards_caveat_reaches_the_pack(profile):
    award = _award(unconfirmed=("route", "money_form"))
    pack = build_pack(profile, [_candidate()], EUR_RATES, awards=[award], today=TODAY)
    assert pack.awards[0].unconfirmed == ("route", "money_form")


# `build_pack(empty_reason=…)` was deleted 2026-09-23: its only caller returns
# early on an empty pool, so the argument was always "" and this test was the
# entire reason the parameter existed. The real path -- the spine's own
# `_empty()` -- is covered by
# tests/funding/test_spine.py::test_an_empty_pool_publishes_an_empty_pack_carrying_the_sentence.


from decimal import Decimal  # noqa: E402

from apps.funding.card import AmountLine, AwardCard  # noqa: E402


def test_a_packed_award_carries_its_card(profile):
    card = AwardCard(
        route="STUDENT_APPLIES_SEPARATELY", tuition="UNSTATED", living="FULL",
        amounts=(AmountLine("STIPEND", "€1,200", Decimal("1200"), "EUR", "MONTHLY", "EXACT", "q"),),
        duration_text="24 months", duration_months=24, timing="PRE_ARRIVAL",
        cycle="ANNUAL_FIXED", unconfirmed=(),
    )
    pack = build_pack(profile, [_candidate()], EUR_RATES, awards=[_award(card=card)], today=TODAY)
    (packed,) = pack.awards
    assert packed.card == card
