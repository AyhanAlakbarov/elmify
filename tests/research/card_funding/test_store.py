"""Tests for Gen-2 funding `Card` persistence (`apps.research.card_funding.store`)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.funding.models import (
    BenefitRule,
    CostComponent,
    FundingBenefit,
    FundingCycleVerification,
    Institution,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
)
from apps.research.candidates import Amount, Date, Duration, Intake, Requirement
from apps.research.card_engine import Quote
from apps.research.card_funding.card import AwardCard, Card, Field, Hold, Track
from apps.research.card_funding.parse import AwardDate, Benefit, Condition, Nationality, Value
from apps.research.card_funding.store import is_servable_award, write_card
from apps.research.register import record_organisation
from apps.research.spine import build_student_pack
from tests.funding.conftest import EUR_RATES, make_profile


def _val(value: object, quote_text: str) -> Value:
    return Value(
        value=value,
        quote=Quote(quote_text, "L1.text"),
        source="https://university.example.org/funding",
        decisions=(),
    )


def _shown(name: str, *items: tuple[object, str]) -> Field:
    return Field(
        name=name,
        state="shown",
        values=tuple(_val(val, q) for val, q in items),
    )


def _fixtures() -> tuple[Institution, Program, OfficialSource, OfficialSourceSnapshot]:
    inst = Institution.objects.create(
        canonical_key=f"inst:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.org",
    )
    prog = Program.objects.create(
        canonical_key=f"prog:{uuid4()}",
        institution=inst,
        name="MSc Computer Science",
        campus_name="Main",
        city="Berlin",
        country_code="DE",
        location_key="DE-BERLIN",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=12,
    )
    src = OfficialSource.objects.create(
        canonical_url=f"https://university.example.org/funding/{uuid4()}",
        publisher="university.example.org",
        source_type=OfficialSource.Type.UNIVERSITY,
    )
    snap = OfficialSourceSnapshot.objects.create(
        source=src,
        s3_key="official-sources/card-test",
        s3_version_id="1",
        sha256="a" * 64,
        final_url=src.canonical_url,
        redirect_chain=[],
        retrieved_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        admissions_cycle="2027",
        content_type="text/html",
        byte_size=512,
        discovery_technique="seed",
    )
    return inst, prog, src, snap


@pytest.mark.django_db(transaction=True)
def test_write_card_persists_servable_award_and_flows_into_student_pack() -> None:
    _inst, prog, src, snap = _fixtures()
    CostComponent.objects.create(
        program=prog, kind="TUITION", amount=Decimal("12000"), currency="EUR", period="ANNUAL"
    )
    org = record_organisation(
        domain="excellence-foundation.de",
        name="Excellence Foundation",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )

    stipend_benefit = Benefit(
        amount=Amount(
            text="EUR 1,200",
            start=0,
            end=9,
            low=Decimal("1200"),
            high=Decimal("1200"),
            currency="EUR",
            bound="exact",
        ),
        conversion=None,
        pays="paid_to_student",
        bound="exact",
        covers=frozenset({"living"}),
        frequency="monthly",
        duration="whole_programme",
        for_whom=frozenset({"student"}),
        for_all=True,
        places=(),
        level="master",
        intake=None,
    )
    deadline_date = AwardDate(
        role="application_deadline",
        date=Date(text="15 December 2026", start=0, end=16, year=2026, month=12, day=15),
        for_all=True,
        places=(),
        cycle=2027,
    )
    nationality = Nationality(
        eligible=frozenset({"AZ", "TR", "GE"}),
        excluded=frozenset(),
        held=frozenset(),
        basis="citizenship",
        groups=(),
    )
    age_cond = Condition(
        kind="age",
        requirement=Requirement(
            text="under 35 years of age",
            start=0,
            end=21,
            kind="age",
            age_max=34,
        ),
    )

    holder_award = AwardCard(
        name="Excellence Scholarship & Opportunity Programme",
        name_quote=Quote("Excellence Scholarship & Opportunity Programme", "L1.text"),
        fields={
            "target_level": _shown("target_level", ("master", "for Master's students")),
            "money_form": _shown("money_form", ("grant", "scholarship grant")),
            "route": _shown("route", ("separate_application", "separate application required")),
            "route_order": _shown("route_order", ("before_admission", "apply before admission")),
            "tuition_level": _shown("tuition_level", ("full", "full tuition fee waiver")),
            "living_level": _shown("living_level", ("full", "EUR 1,200 per month")),
            "benefits": _shown("benefits", (stipend_benefit, "EUR 1,200 per month living stipend")),
            "dates": _shown("dates", (deadline_date, "Application deadline: 15 December 2026")),
            "nationality": _shown("nationality", (nationality, "Open to citizens of AZ, TR, GE")),
            "requirements": _shown(
                "requirements", (age_cond, "Applicants must be under 35 years of age")
            ),
            "funding_duration": _shown(
                "funding_duration",
                (
                    Duration(
                        text="4 semesters", start=0, end=11, count=24, unit="months", months=24
                    ),
                    "for the regular duration of 4 semesters (24 months)",
                ),
            ),
            "funding_period": _shown(
                "funding_period",
                (
                    Intake(
                        text="2027/28",
                        start=0,
                        end=7,
                        start_year=2027,
                        end_year=2028,
                        season=None,
                    ),
                    "for the 2027/28 intake",
                ),
            ),
            "obligations": _shown(
                "obligations", (frozenset({"maintain_progress"}), "maintain good standing")
            ),
        },
        holds=(),
        cycle=2027,
    )
    holder_card = Card(
        program_id=None,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="main", awards=(holder_award,)),),
    )

    assert is_servable_award(holder_card, holder_award) is True
    written = write_card(
        holder_card,
        organisation=org,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert len(written) == 1
    opp = written[0]
    assert opp.served is True
    assert opp.name == "Excellence Scholarship & Opportunity Programme"
    assert opp.money_form == "GRANT"
    assert opp.route == "STUDENT_APPLIES_SEPARATELY"
    assert opp.timing == "PRE_ARRIVAL"
    assert opp.tuition == "FULL"
    assert opp.living == "FULL"
    assert opp.duration_months == 24

    benefits = list(FundingBenefit.objects.filter(opportunity=opp))
    assert {b.kind for b in benefits} == {"STIPEND", "TUITION"}
    stipend_row = next(b for b in benefits if b.kind == "STIPEND")
    assert stipend_row.amount == Decimal("1200.00")
    assert stipend_row.currency == "EUR"

    rules = list(BenefitRule.objects.filter(benefit__opportunity=opp))
    assert any(r.key == "CITIZENSHIP" and r.operator == "IN" and "AZ" in r.value for r in rules)
    assert any(r.key == "AGE" and r.operator == "LTE" and r.value == "34" for r in rules)

    cycle_row = FundingCycleVerification.objects.get(opportunity=opp, intake_start_year=2027)
    assert cycle_row.state == "OPEN"

    # Also write a programme-attached automatic tuition waiver card
    waiver_benefit = Benefit(
        amount=Amount(
            text="EUR 12,000",
            start=0,
            end=10,
            low=Decimal("12000"),
            high=Decimal("12000"),
            currency="EUR",
            bound="exact",
        ),
        conversion=None,
        pays="fee_reduction",
        bound="exact",
        covers=frozenset({"tuition"}),
        frequency="annual",
        duration="whole_programme",
        for_whom=frozenset({"student"}),
        for_all=True,
        places=(),
        level="master",
        intake=None,
    )
    prog_award = AwardCard(
        name="Automatic Merit Waiver",
        name_quote=Quote("Automatic Merit Waiver", "L2.text"),
        fields={
            "target_level": _shown("target_level", ("master", "for Master's students")),
            "money_form": _shown("money_form", ("fee_waiver", "tuition fee waiver")),
            "route": _shown("route", ("automatic_on_admission", "automatic on admission")),
            "tuition_level": _shown("tuition_level", ("full", "full tuition fee waiver")),
            "benefits": _shown("benefits", (waiver_benefit, "EUR 12,000 annual tuition waiver")),
        },
        holds=(),
        cycle=2027,
    )
    prog_card = Card(
        program_id=prog.id,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="main", awards=(prog_award,)),),
    )
    prog_written = write_card(
        prog_card,
        program=prog,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert len(prog_written) == 1
    assert prog_written[0].served is True

    # Real caller verification: build_student_pack serves both to an AZ student
    res = build_student_pack(
        make_profile(nationality="AZ", country_of_residence="AZ"),
        rates=EUR_RATES,
        today=date(2026, 10, 15),
    )
    packed_award = next(a for a in res.pack.awards if a.award_id == str(opp.id))
    assert packed_award.deadline == date(2026, 12, 15)
    packed_prog = next(
        p
        for p in (*res.pack.fee_free, *res.pack.paid, *res.pack.fee_not_known)
        if p.program_id == str(prog.id)
    )
    assert packed_prog.gap == Decimal("0.00")


@pytest.mark.django_db(transaction=True)
def test_country_specific_hold_fails_closed_only_for_held_countries() -> None:
    _inst, _prog, src, snap = _fixtures()
    org = record_organisation(
        domain="regional-foundation.org",
        name="Regional Foundation",
        kind="PRIVATE_FOUNDATION",
        country_code="DE",
        found_via="REGISTER",
    )

    nationality = Nationality(
        eligible=frozenset({"AZ", "GE", "UA"}),
        excluded=frozenset(),
        held=frozenset({"UA"}),
        basis="citizenship",
        groups=("CIS",),
    )
    award = AwardCard(
        name="Regional Fellowship",
        name_quote=Quote("Regional Fellowship", "L1.text"),
        fields={
            "target_level": _shown("target_level", ("master", "Master's track")),
            "money_form": _shown("money_form", ("grant", "grant")),
            "tuition_level": _shown("tuition_level", ("full", "full tuition covered")),
            "nationality": _shown("nationality", (nationality, "Open to CIS citizens")),
        },
        holds=(
            Hold(
                reason="held_country_group",
                field="nationality",
                detail="CIS",
                countries=frozenset({"UA"}),
            ),
        ),
        cycle=2027,
    )
    card = Card(
        program_id=None,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="", awards=(award,)),),
    )

    written = write_card(
        card,
        organisation=org,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert len(written) == 1
    opp = written[0]
    assert opp.served is True

    # Student from AZ (certain eligible) receives the award in pack.awards
    res_az = build_student_pack(
        make_profile(nationality="AZ", country_of_residence="AZ"),
        rates=EUR_RATES,
        today=date(2026, 10, 15),
    )
    assert any(a.award_id == str(opp.id) for a in res_az.pack.awards)

    # Student from UA (held country) fails closed and is excluded from pack.awards
    res_ua = build_student_pack(
        make_profile(nationality="UA", country_of_residence="UA"),
        rates=EUR_RATES,
        today=date(2026, 10, 15),
    )
    assert not any(a.award_id == str(opp.id) for a in res_ua.pack.awards)
    assert any(e.program_id == str(opp.id) for e in res_ua.pack.excluded)


@pytest.mark.django_db(transaction=True)
def test_unconditional_holds_discontinued_loans_and_non_master_tracks_gate_correctly() -> None:
    _inst, _prog, src, snap = _fixtures()
    org = record_organisation(
        domain="external-foundation.ch",
        name="External Foundation",
        kind="PRIVATE_FOUNDATION",
        country_code="CH",
        found_via="REGISTER",
    )

    held_award = AwardCard(
        name="Unresolved Split Award",
        name_quote=Quote("Unresolved Split Award", "L1.text"),
        fields={
            "target_level": _shown("target_level", ("master", "Master's")),
            "money_form": _shown("money_form", ("grant", "grant")),
            "tuition_level": _shown("tuition_level", ("full", "full waiver")),
        },
        holds=(Hold(reason="unresolved_split", field="benefits", detail="pays_m1"),),
    )
    discontinued_award = AwardCard(
        name="Suspended Award",
        name_quote=Quote("Suspended Award", "L2.text"),
        fields={
            "target_level": _shown("target_level", ("master", "Master's")),
            "money_form": _shown("money_form", ("grant", "grant")),
            "tuition_level": _shown("tuition_level", ("full", "full waiver")),
            "discontinued": _shown("discontinued", ("yes", "Not offered for 2027/28")),
        },
        holds=(),
    )
    loan_award = AwardCard(
        name="Pure Bank Loan",
        name_quote=Quote("Pure Bank Loan", "L3.text"),
        fields={
            "target_level": _shown("target_level", ("master", "Master's")),
            "money_form": _shown("money_form", ("loan", "repayable student loan")),
        },
        holds=(),
    )
    bachelor_award = AwardCard(
        name="Undergraduate Bursary",
        name_quote=Quote("Undergraduate Bursary", "L4.text"),
        fields={
            "target_level": _shown("target_level", ("bachelor", "Bachelor's students only")),
            "money_form": _shown("money_form", ("grant", "grant")),
            "tuition_level": _shown("tuition_level", ("full", "full waiver")),
        },
        holds=(),
    )

    card = Card(
        program_id=None,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(
            Track(
                name="",
                awards=(held_award, discontinued_award, loan_award, bachelor_award),
            ),
        ),
    )

    written = write_card(
        card,
        organisation=org,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    # Pure loan and Bachelor-only awards are never written; held and discontinued are
    # written with served=False.
    assert {o.name for o in written} == {"Unresolved Split Award", "Suspended Award"}
    for opp in written:
        assert opp.served is False
        assert opp.scope_type == "HOLDER"
        assert opp.organisation_id == org.pk
    suspended_row = next(o for o in written if o.name == "Suspended Award")
    assert suspended_row.suspension_quote == "Not offered for 2027/28"
    held_row = next(o for o in written if o.name == "Unresolved Split Award")
    assert held_row.agreement == "UNAGREED"
    assert held_row.disputed == "benefits"


@pytest.mark.django_db(transaction=True)
def test_secondary_detail_holds_keep_award_servable_with_unconfirmed_fields() -> None:
    _inst, prog, src, snap = _fixtures()
    award = AwardCard(
        name="Padua Digital Chemistry Fee Waiver & Scholarship",
        name_quote=Quote("Padua Digital Chemistry Fee Waiver & Scholarship", "L1.text"),
        fields={
            "target_level": _shown("target_level", ("master", "for Master's students")),
            "money_form": _shown("money_form", ("grant", "scholarship and fee waiver")),
            "tuition_level": _shown("tuition_level", ("full", "full tuition fee waiver")),
            "living_level": _shown("living_level", ("partial", "EUR 8,000 annual grant")),
        },
        holds=(
            Hold(reason="unresolved_split", field="dates", detail="deadline_split"),
            Hold(reason="unresolved_split", field="funding_duration", detail="duration_split"),
            Hold(reason="unresolved_split", field="route_order", detail="timing_split"),
        ),
        cycle=2027,
    )
    card = Card(
        program_id=prog.id,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="main", awards=(award,)),),
    )

    assert is_servable_award(card, award) is True
    written = write_card(
        card,
        program=prog,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert len(written) == 1
    opp = written[0]
    assert opp.served is True
    assert opp.agreement == "AGREED"
    assert opp.unconfirmed == "dates;duration;timing"
    assert opp.disputed == "dates;funding_duration;route_order"
    assert opp.scope_type == "PROGRAM"
    assert opp.program_id == prog.id


@pytest.mark.django_db(transaction=True)
def test_write_card_institution_scope_and_multi_benefit_rule_attachment() -> None:
    inst, prog, src, snap = _fixtures()
    CostComponent.objects.create(
        program=prog, kind="TUITION", amount=Decimal("10000"), currency="EUR", period="ANNUAL"
    )
    nationality = Nationality(
        eligible=frozenset({"AZ", "TR"}),
        excluded=frozenset(),
        held=frozenset(),
        basis="citizenship",
        groups=(),
    )
    age_range_cond = Condition(
        kind="age",
        requirement=Requirement(
            text="between 18 and 35 years of age",
            start=0,
            end=30,
            kind="age",
            age_min=18,
            age_max=35,
        ),
    )
    grade_cond = Condition(
        kind="grade",
        requirement=Requirement(
            text="minimum GPA 3.0/4.0",
            start=0,
            end=19,
            kind="grade",
            score=Decimal("3.0"),
            scale=Decimal("4.0"),
        ),
    )
    lang_cond = Condition(
        kind="language_test",
        requirement=Requirement(
            text="IELTS 6.5",
            start=0,
            end=9,
            kind="language_test",
            test="IELTS",
            score=Decimal("6.5"),
        ),
    )
    award = AwardCard(
        name="University-Wide International Excellence Award",
        name_quote=Quote("University-Wide International Excellence Award", "L1.text"),
        fields={
            "target_level": _shown("target_level", ("master", "for Master's students")),
            "money_form": _shown("money_form", ("grant", "grant")),
            "route": _shown("route", ("automatic_on_admission", "automatic")),
            "tuition_level": _shown("tuition_level", ("full", "full tuition waiver")),
            "living_level": _shown("living_level", ("full", "living stipend")),
            "nationality": _shown("nationality", (nationality, "Open to AZ and TR citizens")),
            "requirements": _shown(
                "requirements",
                (age_range_cond, "between 18 and 35 years of age"),
                (grade_cond, "minimum GPA 3.0/4.0"),
                (lang_cond, "IELTS 6.5"),
            ),
        },
        holds=(),
        cycle=2027,
    )
    card = Card(
        program_id=None,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="main", awards=(award,)),),
    )

    written = write_card(
        card,
        institution=inst,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert len(written) == 1
    opp = written[0]
    assert opp.scope_type == "INSTITUTION"
    assert opp.institution_id == inst.id
    assert opp.family == "UNIVERSITY_WIDE"

    # Both TUITION and STIPEND benefits receive all eligibility rules
    benefits = list(FundingBenefit.objects.filter(opportunity=opp))
    assert len(benefits) == 2
    for benefit in benefits:
        b_rules = list(BenefitRule.objects.filter(benefit=benefit))
        keys_ops = {(r.key, r.operator, r.value) for r in b_rules}
        assert ("CITIZENSHIP", "IN", "AZ,TR") in keys_ops
        assert ("AGE", "LTE", "35") in keys_ops
        assert ("AGE", "GTE", "18") in keys_ops
        assert ("GRADE", "GTE", "3.0 4.0") in keys_ops
        assert ("LANGUAGE", "PRESENT", "English IELTS 6.5") in keys_ops


@pytest.mark.django_db(transaction=True)
def test_write_card_on_joint_programme_coerces_institution_wide_to_program_scope() -> None:
    from apps.funding.models import FundingOpportunityProgram

    _inst, _prog, src, snap = _fixtures()
    joint_prog = Program.objects.create(
        institution=None,
        canonical_key=f"prog:joint:{uuid4()}",
        name="Erasmus Mundus Joint Master in Chemical Nanoengineering",
        campus_name="Consortium",
        city="Marseille",
        country_code="FR",
        location_key="FR-MARSEILLE",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
        provision_type=Program.ProvisionType.JOINT,
    )
    award = AwardCard(
        name="EMJM Consortium Scholarship",
        name_quote=Quote("EMJM Consortium Scholarship", "L1.text"),
        fields={
            "target_level": _shown("target_level", ("master", "for Master's students")),
            "money_form": _shown("money_form", ("grant", "monthly grant")),
            "tuition_level": _shown("tuition_level", ("full", "full participation cost waiver")),
            "living_level": _shown("living_level", ("full", "EUR 1,400/month living allowance")),
            "institution_wide": _shown("institution_wide", ("yes", "consortium-wide scholarship")),
        },
        holds=(),
        cycle=2027,
    )
    card = Card(
        program_id=joint_prog.id,
        source_url=src.canonical_url,
        lang="en",
        outcome="read",
        tracks=(Track(name="emjm", awards=(award,)),),
    )

    written = write_card(
        card,
        program=joint_prog,
        source=src,
        snapshot=snap,
        now=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )
    assert len(written) == 1
    opp = written[0]
    assert opp.served is True
    assert opp.scope_type == "PROGRAM"
    assert opp.program_id == joint_prog.id
    assert opp.institution_id is None
    assert FundingOpportunityProgram.objects.filter(opportunity=opp, program=joint_prog).exists()


