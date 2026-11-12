import pytest
from django.core.cache import cache

from apps.dashboard.board import board_for
from apps.dashboard.new_for_you import offers_for
from apps.funding.models import RecommendationCandidate
from apps.funding.rates import store
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.funding.conftest import make_db_candidate

from .conftest import AZN_RATES, set_profile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _pool_item(agency, run, name, *, rank, gap="500.00", fee="120.00"):
    """A ranked programme in the run's pool, not in the pack: 120 EUR is 240 AZN,
    247.20 with the bank margin."""
    candidate = make_db_candidate(agency, run, program_name=name, funding_gap=gap)
    with tenant_scope(agency.id):
        RecommendationCandidate.objects.filter(id=candidate.id).update(
            application_fee=fee, application_fee_currency="EUR", rank=rank
        )
    return candidate


@pytest.fixture
def pool(agency_a, membership_a, pack):
    """The pack's programme is the last paid item, at rank 3. It is not a card,
    so its 75 EUR = 150 AZN fee, 154.50 with the margin, is held back from what
    New for you may offer (§7.9): each budget below is that much above the room
    it means to leave."""
    programme, _award = pack
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(rank=3)
    return {
        "above": _pool_item(agency_a, programme.run, "MSc Above", rank=2),
        "funded": _pool_item(agency_a, programme.run, "MSc Funded", rank=9, gap="0.00"),
        "ordinary": _pool_item(agency_a, programme.run, "MSc Ordinary", rank=8),
    }


def _offers(agency, student):
    with tenant_scope(agency.id), reads_no_catalogue():
        board = board_for(student)
        return {o.title: o for o in offers_for(student, board=board, table=board.rates,
                                               home=board.home)}


def _budget(agency, student, amount, stretch=None):
    snapshot = {
        "country_of_residence": "AZ",
        "application_budget": {"amount": amount, "currency": "AZN"},
    }
    if stretch:
        snapshot["budget_stretch"] = {"amount": stretch, "currency": "AZN"}
    set_profile(agency, student, **snapshot)


def test_a_raised_budget_offers_the_over_budget_programmes_that_now_fit(
    agency_a, membership_a, pool
):
    _budget(agency_a, membership_a, "454.50")
    offers = _offers(agency_a, membership_a)
    assert {title: o.kind for title, o in offers.items()} == {
        "MSc Above": "FITS", "MSc Funded": "FITS", "MSc Ordinary": "FITS",
    }
    assert offers["MSc Above"].text == "MSc Above — fee 120.00 EUR ≈ 240 AZN, fits your plan"
    assert offers["MSc Above"].add_url == f"/student/applications/add/{pool['above'].id}/"
    assert list(offers) == ["MSc Above", "MSc Ordinary", "MSc Funded"]  # rank order


@pytest.mark.parametrize("name", ["MSc Above", "MSc Funded"])
def test_each_exceptional_reason_is_worth_stretching_for_with_a_stretch(
    agency_a, membership_a, pool, name
):
    _budget(agency_a, membership_a, "354.50", stretch="100.00")
    offer = _offers(agency_a, membership_a)[name]
    assert offer.kind == "STRETCH"
    assert offer.text == (
        f"Worth stretching for: {name} — fee 120.00 EUR ≈ 240 AZN, 48 AZN over your plan "
        "(within the extra you allowed)"
    )
    # The same Add as every other row: it renders the over-budget page.
    assert offer.add_url == f"/student/applications/add/{offer.candidate_id}/"


@pytest.mark.parametrize("name", ["MSc Above", "MSc Funded"])
def test_without_a_stretch_an_exceptional_item_is_over_your_plan(
    agency_a, membership_a, pool, name
):
    _budget(agency_a, membership_a, "354.50")
    offer = _offers(agency_a, membership_a)[name]
    assert offer.kind == "OVER"
    assert offer.add_url == f"/student/applications/add/{offer.candidate_id}/"
    assert offer.text == f"{name} — fee 120.00 EUR ≈ 240 AZN. Over your plan by 48 AZN"


def test_an_ordinary_item_that_does_not_fit_is_not_shown(agency_a, membership_a, pool):
    _budget(agency_a, membership_a, "354.50", stretch="100.00")
    assert "MSc Ordinary" not in _offers(agency_a, membership_a)


def test_an_item_already_a_card_or_in_the_pack_is_not_offered(agency_a, membership_a, pool):
    from apps.portals.applications import add_application

    _budget(agency_a, membership_a, "454.50")
    with tenant_scope(agency_a.id):
        # A pool item names no catalogue row, so the card takes its own id.
        add_application(student=membership_a, candidate_id=pool["above"].id, actor=membership_a)
    offers = _offers(agency_a, membership_a)
    assert "MSc Above" not in offers
    assert "M.Sc. Informatics" not in offers


def test_a_programme_already_a_card_from_an_earlier_run_is_not_offered(
    agency_a, membership_a, pool, program_factory
):
    """A newer run copies the programme as a new candidate row; the card made
    from the older row (here an accepted offer naming it) is still that programme."""
    _budget(agency_a, membership_a, "454.50")
    row = program_factory(name="MSc Above")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=pool["above"].id).update(program_id=row.id)
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=row.id, name="MSc Above"
        )
    offers = _offers(agency_a, membership_a)
    assert "MSc Above" not in offers
    assert "MSc Ordinary" in offers  # the rest of the pool is still offered


def test_new_for_you_is_on_the_student_home_and_never_on_the_counsellor_board(
    client, agency_a, domain_a, user_a, membership_a, counselor_user, counselor_membership, pool
):
    _budget(agency_a, membership_a, "300.00")
    client.force_login(user_a)
    assert "New for you" in client.get("/student/", HTTP_HOST=domain_a.host).content.decode()

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    body = client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    # The counsellor's page does render this student's money (the budget
    # line), so the absence below is about the offers, not an empty page.
    assert "Application budget 300 AZN" in body
    assert "New for you" not in body


def test_an_item_tied_with_the_last_paid_rank_is_not_exceptional(
    agency_a, membership_a, pool, pack
):
    programme, _award = pack  # the last paid item, rank 3
    _pool_item(agency_a, programme.run, "MSc Tied", rank=3)
    _budget(agency_a, membership_a, "354.50", stretch="100.00")
    offers = _offers(agency_a, membership_a)
    assert "MSc Tied" not in offers
    assert "MSc Above" in offers  # rank 2 still is


def test_day_one_offers_nothing_the_packs_own_paid_picks_need(
    agency_a, membership_a, pack, client, user_a, domain_a
):
    """Final review I1 (spec §7.9: New for you appears only when the budget
    gains room). The pack's own pick, 75 EUR = 150 AZN, is not a card yet; a
    lower-ranked 50 EUR pool item was offered as fitting with that same money,
    and adding the pack's pick afterwards hit the over-budget page."""
    programme, _award = pack
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(rank=1)
    _pool_item(agency_a, programme.run, "MSc Pool", rank=2, fee="50.00")
    _budget(agency_a, membership_a, "200.00")

    assert "MSc Pool" not in _offers(agency_a, membership_a)
    client.force_login(user_a)
    response = client.post(
        f"/student/applications/add/{programme.id}/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302  # the pack's pick still fits: no over-budget page

    # Room the budget gained is offered: 150 + 100 AZN, each with the 3% margin.
    _budget(agency_a, membership_a, "300.00")
    assert _offers(agency_a, membership_a)["MSc Pool"].kind == "FITS"


def test_a_raised_budget_offers_only_beyond_the_packs_unadded_picks(
    agency_a, membership_a, pack
):
    """I1, without adding anything: the room offered is free minus the pack's
    paid picks that are not cards yet (154.50 AZN with the margin)."""
    programme, _award = pack
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(rank=1)
    _pool_item(agency_a, programme.run, "MSc Pool", rank=2, fee="50.00")  # 103 AZN

    _budget(agency_a, membership_a, "257.00")  # 257 - 154.50 = 102.50 < 103
    assert "MSc Pool" not in _offers(agency_a, membership_a)
    _budget(agency_a, membership_a, "257.50")
    assert _offers(agency_a, membership_a)["MSc Pool"].kind == "FITS"


def test_a_pack_pick_already_a_card_from_an_earlier_run_is_not_held_back_twice(
    agency_a, membership_a, pack
):
    """I1: a pick that is already a card (made from an older run's row of the
    same programme) is the board's to count, so nothing is reserved for it."""
    programme, _award = pack
    store(AZN_RATES)
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=programme.id).update(rank=1)
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=programme.program_id,
            name="M.Sc. Informatics",
        )
    _pool_item(agency_a, programme.run, "MSc Pool", rank=2, fee="50.00")  # 103 AZN
    _budget(agency_a, membership_a, "103.00")
    assert _offers(agency_a, membership_a)["MSc Pool"].kind == "FITS"


def _section(client, host) -> str:
    body = client.get("/student/", HTTP_HOST=host).content.decode()
    start = body.index('<section aria-labelledby="new-heading">')
    return body[start : body.index("</section>", start)]


def test_an_over_row_has_change_my_budget_beside_it_and_a_fitting_row_does_not(
    client, agency_a, domain_a, user_a, membership_a, pool
):
    """Final review M2 (spec §7.7: "with 'Change my budget' beside it")."""
    client.force_login(user_a)
    _budget(agency_a, membership_a, "354.50")  # MSc Above and MSc Funded are OVER
    section = _section(client, domain_a.host)
    assert section.count('<a href="/student/settings/budget/">Change my budget</a>') == 2

    _budget(agency_a, membership_a, "454.50")  # all three fit
    section = _section(client, domain_a.host)
    assert "fits your plan" in section
    assert "Change my budget" not in section


def test_score_unlocked_and_boosted_programmes_and_scholarships_appear_in_new_for_you(
    agency_a, membership_a, pack
):
    from decimal import Decimal
    from uuid import uuid4

    from django.utils import timezone

    from apps.funding.models import FundingOpportunity, PackCandidate, PackVersion

    programme, award = pack
    store(AZN_RATES)
    _budget(agency_a, membership_a, "300.00")
    new_award = FundingOpportunity.objects.create(
        canonical_key=f"award:{uuid4()}",
        name="DAAD Merit Scholarship",
        family="UNIVERSITY_WIDE",
        scope_type="GLOBAL",
    )
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(country_code="DE")
        v2 = PackVersion.objects.create(
            run=programme.run, version=2, published_at=timezone.now()
        )
        PackCandidate.objects.create(pack_version=v2, candidate=programme)
        PackCandidate.objects.create(pack_version=v2, candidate=award)

        unlocked_free = make_db_candidate(
            agency_a,
            programme.run,
            program_name="MSc Unlocked Free",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=unlocked_free.id).update(
            country_code="DE",
            application_fee=Decimal("0.00"),
            application_fee_currency="EUR",
            rank=1,
            calibration_features={"score_unlocked": True},
        )
        PackCandidate.objects.create(pack_version=v2, candidate=unlocked_free)

        unlocked_award = make_db_candidate(
            agency_a,
            programme.run,
            program_name="DAAD Merit Scholarship",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=unlocked_award.id).update(
            opportunity_id=new_award.id,
            program_id=None,
            application_fee=None,
            rank=None,
            estimated_chance_pct=Decimal("64.00"),
            funding_card={
                "scope": "GLOBAL",
                "route": "STUDENT_APPLIES_SEPARATELY",
                "deadline": "2026-12-15",
            },
            calibration_features={"score_boosted": True, "previous_chance_pct": "42.00"},
        )
        PackCandidate.objects.create(pack_version=v2, candidate=unlocked_award)

    offers = _offers(agency_a, membership_a)
    assert "MSc Unlocked Free" in offers
    assert offers["MSc Unlocked Free"].kind == "UNLOCKED"
    assert "unlocked by your updated scores" in offers["MSc Unlocked Free"].text
    assert "DAAD Study Scholarship" in offers["MSc Unlocked Free"].text
    assert "DAAD Merit Scholarship" in offers
    assert offers["DAAD Merit Scholarship"].kind == "UNLOCKED"
    assert "updated scores" in offers["DAAD Merit Scholarship"].text


def test_score_unlocked_programme_requires_viable_related_pack_scholarship_and_open_deadlines(
    agency_a, membership_a, pack
):
    from decimal import Decimal

    from django.utils import timezone

    from apps.funding.models import PackCandidate, PackVersion

    programme, award = pack
    store(AZN_RATES)
    _budget(agency_a, membership_a, "300.00")

    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            country_code="DE",
            funding_card={
                "scope": "HOLDER",
                "holder": "DAAD",
                "route": "STUDENT_APPLIES_SEPARATELY",
                "tuition": "FULL",
                "living": "FULL",
                "amounts": ["934 EUR a month"],
                "deadline": "2026-11-15",
            },
        )
        v2 = PackVersion.objects.create(
            run=programme.run, version=2, published_at=timezone.now()
        )
        PackCandidate.objects.create(pack_version=v2, candidate=programme)
        PackCandidate.objects.create(pack_version=v2, candidate=award)

        # 1. Unrelated programme in FR (not funded by DAAD DE scholarship) -> NOT offered
        unrelated_fr = make_db_candidate(
            agency_a,
            programme.run,
            program_name="MSc Unrelated France",
            funding_gap="5000.00",
        )
        RecommendationCandidate.objects.filter(id=unrelated_fr.id).update(
            country_code="FR",
            application_fee=Decimal("0.00"),
            application_fee_currency="EUR",
            rank=1,
            calibration_features={"score_unlocked": True},
        )
        PackCandidate.objects.create(pack_version=v2, candidate=unrelated_fr)

        # 2. Programme in DE related to DAAD Study Scholarship, but with its OWN expired deadline
        expired_prog = make_db_candidate(
            agency_a,
            programme.run,
            program_name="MSc Expired University Deadline",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=expired_prog.id).update(
            country_code="DE",
            application_fee=Decimal("0.00"),
            application_fee_currency="EUR",
            rank=2,
            calibration_features={
                "score_unlocked": True,
                "application_deadline": "2026-10-01",
            },
        )
        PackCandidate.objects.create(pack_version=v2, candidate=expired_prog)

        # 3. Programme in DE related to DAAD Study Scholarship with open deadline -> OFFERED
        viable_de = make_db_candidate(
            agency_a,
            programme.run,
            program_name="MSc Viable Germany",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=viable_de.id).update(
            country_code="DE",
            application_fee=Decimal("0.00"),
            application_fee_currency="EUR",
            rank=3,
            calibration_features={
                "score_unlocked": True,
                "application_deadline": "2027-01-15",
            },
        )
        PackCandidate.objects.create(pack_version=v2, candidate=viable_de)

    offers = _offers(agency_a, membership_a)
    assert "MSc Unrelated France" not in offers
    assert "MSc Expired University Deadline" not in offers
    assert "MSc Viable Germany" in offers
    assert "DAAD Study Scholarship" in offers["MSc Viable Germany"].text

    # 4. Now if DAAD Study Scholarship's deadline has passed (2026-10-15) and the student
    # has NOT submitted an application for it -> MSc Viable Germany is NOT offered
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=award.id).update(
            funding_card={
                "scope": "HOLDER",
                "holder": "DAAD",
                "route": "STUDENT_APPLIES_SEPARATELY",
                "tuition": "FULL",
                "living": "FULL",
                "amounts": ["934 EUR a month"],
                "deadline": "2026-10-15",
            }
        )
    assert "MSc Viable Germany" not in _offers(agency_a, membership_a)

    # 5. Subcase C3-b: Student ALREADY submitted the external HOLDER scholarship before its deadline
    # -> MSc Viable Germany IS offered even after the scholarship's deadline!
    with tenant_scope(agency_a.id):
        award_app = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=award.opportunity_id,
            candidate=award,
            state=Application.State.SUBMITTED,
        )
    offers_after_submit = _offers(agency_a, membership_a)
    assert "MSc Viable Germany" in offers_after_submit

    # 6. If the student is subsequently REJECTED from that scholarship -> not offered
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=award_app.id).update(
            outcome=Application.Outcome.REJECTED
        )
    assert "MSc Viable Germany" not in _offers(agency_a, membership_a)

    # 7. R3: If the submitted scholarship is WAITLISTED -> offered with "— waitlisted" note
    with tenant_scope(agency_a.id):
        Application.objects.filter(id=award_app.id).update(
            outcome=Application.Outcome.WAITLISTED
        )
    offers_waitlisted = _offers(agency_a, membership_a)
    assert "MSc Viable Germany" in offers_waitlisted
    assert "DAAD Study Scholarship — waitlisted" in offers_waitlisted["MSc Viable Germany"].text


def test_pass3_b1_b2_b3_b6_paid_score_offers_reserved_budget_and_award_viability(
    agency_a, membership_a, pack
):
    from decimal import Decimal
    from uuid import uuid4

    from django.utils import timezone

    from apps.funding.models import FundingOpportunity, PackCandidate, PackVersion

    programme, award = pack
    store(AZN_RATES)
    # Budget 200 AZN: programme (75 EUR = 150 AZN * 1.03 = 154.50 AZN reserved) -> 45.50 AZN room
    _budget(agency_a, membership_a, "200.00")

    se_award_opp = FundingOpportunity.objects.create(
        canonical_key=f"award:se:{uuid4()}",
        name="Swedish Institute Scholarship",
        family="UNIVERSITY_WIDE",
        scope_type="COUNTRY",
        country_code="SE",
    )
    fr_award_opp = FundingOpportunity.objects.create(
        canonical_key=f"award:fr:{uuid4()}",
        name="Eiffel Excellence Scholarship",
        family="UNIVERSITY_WIDE",
        scope_type="COUNTRY",
        country_code="FR",
    )

    with tenant_scope(agency_a.id):
        # B1: Existing paid v1 pack member gets score_boosted=True in v2 -> must stay in taken
        # AND keep its 75 EUR fee reserved!
        RecommendationCandidate.objects.filter(id=programme.id).update(
            country_code="DE",
            application_fee=Decimal("75.00"),
            application_fee_currency="EUR",
            rank=1,
            estimated_chance_pct=Decimal("72.00"),
            calibration_features={"score_boosted": True, "previous_chance_pct": "55.00"},
        )
        RecommendationCandidate.objects.filter(id=award.id).update(
            country_code="DE",
            funding_card={
                "scope": "HOLDER",
                "holder": "DAAD",
                "route": "STUDENT_APPLIES_SEPARATELY",
                "tuition": "FULL",
                "living": "FULL",
                "amounts": ["934 EUR a month"],
                "deadline": "2026-12-15",
            },
        )
        v2 = PackVersion.objects.create(
            run=programme.run, version=2, published_at=timezone.now()
        )
        PackCandidate.objects.create(pack_version=v2, candidate=programme)
        PackCandidate.objects.create(pack_version=v2, candidate=award)

        # B2: Paid newly score-unlocked programme (20 EUR = 40 AZN * 1.03 = 41.20 AZN <= 45.50 AZN)
        # retains score_note and scholarship attribution in Offer.text
        paid_unlocked_de = make_db_candidate(
            agency_a,
            programme.run,
            program_name="MSc Paid Unlocked Germany",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=paid_unlocked_de.id).update(
            country_code="DE",
            application_fee=Decimal("20.00"),
            application_fee_currency="EUR",
            rank=2,
            calibration_features={
                "score_unlocked": True,
                "application_deadline": "2027-01-15",
            },
        )
        PackCandidate.objects.create(pack_version=v2, candidate=paid_unlocked_de)

        # Ordinary pool item with 50 EUR fee (103 AZN): only fits if `programme`'s 75 EUR fee
        # were wrongly un-reserved!
        ordinary_pool = make_db_candidate(
            agency_a,
            programme.run,
            program_name="MSc Ordinary Pool Item",
            funding_gap="5000.00",
        )
        RecommendationCandidate.objects.filter(id=ordinary_pool.id).update(
            country_code="DE",
            application_fee=Decimal("50.00"),
            application_fee_currency="EUR",
            rank=5,
        )

        # B3: Newly score-unlocked scholarship in v2 (Swedish Institute) + newly score-unlocked
        # programme in SE covered by it in the same v2 pack
        se_award_cand = make_db_candidate(
            agency_a,
            programme.run,
            program_name="Swedish Institute Scholarship",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=se_award_cand.id).update(
            opportunity_id=se_award_opp.id,
            program_id=None,
            country_code="SE",
            application_fee=None,
            rank=None,
            funding_card={
                "scope": "COUNTRY",
                "route": "STUDENT_APPLIES_SEPARATELY",
                "deadline": "2027-02-15",
            },
            calibration_features={"score_unlocked": True},
        )
        PackCandidate.objects.create(pack_version=v2, candidate=se_award_cand)

        se_prog = make_db_candidate(
            agency_a,
            programme.run,
            program_name="KTH MSc Machine Learning",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=se_prog.id).update(
            country_code="SE",
            application_fee=Decimal("0.00"),
            application_fee_currency="EUR",
            rank=3,
            calibration_features={
                "score_unlocked": True,
                "application_deadline": "2027-01-15",
            },
        )
        PackCandidate.objects.create(pack_version=v2, candidate=se_prog)

        # B6: Standalone score-unlocked scholarship in FR where the only FR programme in the run
        # has an expired deadline -> scholarship must NOT be offered
        fr_award_cand = make_db_candidate(
            agency_a,
            programme.run,
            program_name="Eiffel Excellence Scholarship",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=fr_award_cand.id).update(
            opportunity_id=fr_award_opp.id,
            program_id=None,
            country_code="FR",
            application_fee=None,
            rank=None,
            funding_card={
                "scope": "COUNTRY",
                "route": "STUDENT_APPLIES_SEPARATELY",
                "deadline": "2027-01-10",
            },
            calibration_features={"score_unlocked": True},
        )
        PackCandidate.objects.create(pack_version=v2, candidate=fr_award_cand)

        fr_dead_prog = make_db_candidate(
            agency_a,
            programme.run,
            program_name="Sorbonne MSc AI",
            funding_gap="0.00",
        )
        RecommendationCandidate.objects.filter(id=fr_dead_prog.id).update(
            country_code="FR",
            application_fee=Decimal("0.00"),
            application_fee_currency="EUR",
            rank=4,
            calibration_features={"application_deadline": "2026-10-01"},
        )

    offers = _offers(agency_a, membership_a)
    # B1: Existing paid v1 pack member is NOT duplicated in New for you, and its 75 EUR fee stays
    # reserved so the 50 EUR ordinary pool item is NOT falsely offered as FITS
    assert programme.program_name not in offers
    assert "MSc Ordinary Pool Item" not in offers

    # B2: Paid score-unlocked programme carries score_note and scholarship name
    assert "MSc Paid Unlocked Germany" in offers
    assert offers["MSc Paid Unlocked Germany"].kind == "FITS"
    assert "unlocked by your updated scores (under DAAD Study Scholarship)" in (
        offers["MSc Paid Unlocked Germany"].text
    )

    # B3: Newly score-unlocked scholarship in v2 sponsors its covered SE programme
    assert "Swedish Institute Scholarship" in offers
    assert "KTH MSc Machine Learning" in offers
    assert "Swedish Institute Scholarship" in offers["KTH MSc Machine Learning"].text

    # B6: Standalone FR scholarship with zero viable FR programmes in the run is NOT offered
    assert "Eiffel Excellence Scholarship" not in offers


@pytest.mark.parametrize(
    "reason",
    [
        "ELIGIBLE_BELOW_FIT_BAR",
        "PACK_DIVERSITY_LIMIT",
        "FEE_NOT_KNOWN_LIMIT",
        "ANCHOR_BUDGET_RESERVED",
    ],
)
def test_non_budget_over_budget_reasons_are_not_offered_as_new_for_you_unless_score_unlocked(
    agency_a, membership_a, pack, reason
):
    programme, _award = pack
    store(AZN_RATES)
    _budget(agency_a, membership_a, "1000.00")
    item = _pool_item(agency_a, programme.run, f"MSc {reason}", rank=1, fee="0.00")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=item.id).update(
            calibration_features={"over_budget_reason": reason}
        )

    assert f"MSc {reason}" not in _offers(agency_a, membership_a)

    # Genuine budget-exceeded pool item IS offered when budget has room
    budget_item = _pool_item(agency_a, programme.run, "MSc Budget Exceeded", rank=2, fee="50.00")
    with tenant_scope(agency_a.id):
        RecommendationCandidate.objects.filter(id=budget_item.id).update(
            calibration_features={"over_budget_reason": "APPLICATION_BUDGET_EXCEEDED"}
        )
    assert _offers(agency_a, membership_a)["MSc Budget Exceeded"].kind == "FITS"

