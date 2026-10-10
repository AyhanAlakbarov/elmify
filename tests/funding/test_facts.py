"""The two translators, and what each does when the catalogue is silent.

Every test here is a "when absent" row: the reader records what a page said,
and a translator that filled a gap with a plausible value would be inventing
eligibility, a cost or a deadline. The honest output is always the undecidable
one, carrying the award's own sentence as the reason.

Spec section 10.2.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from apps.funding.conditions import undecidable_conditions
from apps.funding.facts import award_facts, program_facts
from apps.funding.models import (
    BenefitRule,
    FundingBenefit,
    FundingOpportunity,
    Institution,
    Program,
)
from apps.research.register import record_organisation

pytestmark = pytest.mark.django_db


@pytest.fixture
def award():
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
        nationality_shape="COUNTRY_LIST",
    )


@pytest.fixture
def program():
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://university.example.org",
    )
    return Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )


def test_a_country_list_shape_with_no_list_becomes_an_undecidable_condition(award, profile):
    """The reader records `nationality_shape` but not WHICH countries (spine
    section 3.2). A translator that guessed the list would be inventing
    eligibility; the honest output is undecidable, carrying the award's own
    sentence as the reason."""
    facts = award_facts(award, benefits=(), rules=())

    (condition,) = facts.applicant_conditions
    assert condition.key == "CITIZENSHIP"
    assert condition.value == "", "no country list was read, so none may be asserted"

    reasons = undecidable_conditions(profile, facts.applicant_conditions)
    assert reasons, "an unreadable country list must reach a human, not filter silently"
    assert any("CITIZENSHIP" in reason for reason in reasons)


def test_no_benefit_means_no_coverage_never_a_zero_cost_assumption(award, profile):
    """An award with no FundingBenefit row states no amount. Translating that
    into a zero-cost or a full-coverage figure would put a number in front of a
    student that no page printed."""
    facts = award_facts(award, benefits=(), rules=())
    assert facts.benefits == ()
    assert facts.coverage_is_unstated is True


def test_no_deadline_leaves_the_intake_gate_to_decide_never_a_fabricated_date(award, profile):
    """A missing deadline is not an expired one and not an open one. It stays
    None, and the deadline gate abstains rather than inventing a date to
    compare against."""
    facts = award_facts(award, benefits=(), rules=())
    assert facts.evidence.deadline is None
    assert facts.evidence.deadlines == ()


def test_an_unagreed_row_translates_to_low_evidence_confidence(award):
    """A row the readings could not agree on is not evidence a student acts on.
    LOW is what the pack's own P1-6 gate excludes."""
    award.agreement = "UNAGREED"
    award.served = False
    facts = award_facts(award, benefits=(), rules=())
    assert facts.evidence_confidence == "LOW"


def test_an_agreed_row_with_an_unconfirmed_detail_is_not_low_confidence(award):
    """Tiered agreement's whole point: a detail split does not sink the award,
    so it must not sink its confidence either."""
    award.unconfirmed = "route"
    facts = award_facts(award, benefits=(), rules=())
    assert facts.evidence_confidence != "LOW"


def test_an_unconfirmed_field_does_not_become_a_condition(award, profile):
    """`nationality_shape` is blanked to UNSTATED when the readings split on it.
    Translating a blanked field into a condition would turn a disagreement into
    an eligibility bar -- the exact silent exclusion tiered agreement exists to
    prevent."""
    award.nationality_shape = "UNSTATED"
    award.unconfirmed = "nationality_shape"
    facts = award_facts(award, benefits=(), rules=())
    assert facts.applicant_conditions == ()


def test_a_published_condition_survives_the_translation(award, profile):
    benefit = FundingBenefit.objects.create(
        opportunity=award, kind="STIPEND", period="MONTHLY", description="1,200 EUR monthly."
    )
    BenefitRule.objects.create(
        benefit=benefit,
        kind=BenefitRule.Kind.APPLICANT_CONDITION,
        scope_type="GLOBAL",
        condition_type="WORK_EXPERIENCE",
        key="WORK_EXPERIENCE",
        operator="GTE",
        value="24",
        comparable_value=Decimal("24"),
        comparable_unit="MONTHS",
        rule_text="Applicants need two years of professional experience.",
    )
    facts = award_facts(award, benefits=(benefit,), rules=tuple(BenefitRule.objects.all()))

    assert len(facts.benefits) == 1
    keys = {condition.key for condition in facts.applicant_conditions}
    assert "WORK_EXPERIENCE" in keys


def test_program_facts_carry_the_programme_and_no_fabricated_deadline(program, profile):
    facts = program_facts(program, costs=(), benefits=(), rules=())

    assert facts.program_id == str(program.id)
    assert facts.program_country_code == "DE"
    assert facts.teaching_languages == ("English",)
    assert facts.duration_months == 24
    # The catalog holds no deadline columns for a programme (CLAUDE.md), so
    # there is nothing honest to put here.
    assert facts.application_deadline is None
    assert facts.deadline_is_viable is True, "an unknown deadline does not rule the programme out"


def test_program_facts_never_claim_a_confirmed_eligibility_failure(program, profile):
    """`confirmed_eligibility_failure` means a human or a page said no. Nothing
    in the catalogue says that yet, so asserting it would exclude a candidate on
    evidence that does not exist."""
    facts = program_facts(program, costs=(), benefits=(), rules=())
    assert facts.confirmed_eligibility_failure is False


def test_program_facts_are_pure_and_do_no_queries(program, profile, django_assert_num_queries):
    """Pure by test, not only by intent: `read_and_derive`'s idle-in-transaction
    cost is the standing warning about I/O hidden inside a translation."""
    with django_assert_num_queries(0):
        program_facts(program, costs=(), benefits=(), rules=())


def test_the_translator_refuses_a_row_the_database_would_not_have_allowed(program):
    """Defence in depth, and the measurement that says so.

    `spine.build_student_pack` catches a translation failure, counts it and
    names it in an operator's queue, because one bad catalogue row must never
    fail a whole pack. Reaching that branch from the pool turns out to be
    impossible today: `program_country_iso3166_alpha2` and
    `program_duration_months_range` refuse both candidate cases at the
    DATABASE, so a row that survives INSERT also survives translation. Both
    were tried, and both raised IntegrityError before the translator was
    reached.

    So the guard is written against an UNSAVED instance, which is the only way
    to state what it is for: the catalogue's constraints are the first line and
    the translator is the second, and the day a column is added without a
    matching check, the second line is what stops one row emptying a pack.
    """
    program.duration_months = 600  # allowed by the field, refused by the check
    with pytest.raises(Exception):
        program_facts(program, costs=(), benefits=(), rules=())


from apps.funding.card import card_fill  # noqa: E402


def _programme_award(program, *, duration_months=None):
    return FundingOpportunity.objects.create(
        canonical_key=f"read:program:{uuid4()}", name="Programme stipend",
        family="DEPARTMENT_OR_PROGRAM", scope_type="PROGRAM", program=program,
        agreement="AGREED", served=True, route="AUTOMATIC_ON_ADMISSION",
        duration_months=duration_months,
    )


def _read_benefit(opportunity, **fields):
    values = dict(
        kind="STIPEND", amount=Decimal("1000"), currency="EUR", period="MONTHLY",
        description="x", amount_text="€1,000", amount_bound="EXACT",
        amount_quote="€1,000 a month.",
    )
    values.update(fields)
    return FundingBenefit.objects.create(opportunity=opportunity, **values)


def _one_benefit(program, profile, benefit, durations):
    facts = program_facts(
        program, costs=(), benefits=(benefit,), rules=(),
        routes={benefit.opportunity_id: "AUTOMATIC_ON_ADMISSION"}, durations=durations,
    )
    (fact,) = facts.benefits
    return fact


def test_a_monthly_figure_counts_only_for_the_months_the_page_states(program, profile):
    award = _programme_award(program, duration_months=12)
    fact = _one_benefit(program, profile, _read_benefit(award), {award.id: 12})
    assert (fact.amount, fact.currency, fact.period) == (Decimal("12000.00"), "EUR", "FULL_PROGRAM")


def test_an_award_longer_than_the_programme_counts_for_the_programme(program, profile):
    award = _programme_award(program, duration_months=36)
    fact = _one_benefit(program, profile, _read_benefit(award), {award.id: 36})
    assert fact.amount == Decimal("24000.00")   # the programme runs 24 months


def test_a_monthly_figure_with_no_stated_duration_is_no_coverage(program, profile):
    """Not the programme's length: that would count a one-year stipend twice
    on a two-year degree, which is exactly the overstatement this closes."""
    award = _programme_award(program)
    fact = _one_benefit(program, profile, _read_benefit(award), {award.id: None})
    assert (fact.amount, fact.currency) == (None, None)


def test_an_up_to_figure_is_shown_but_never_counted(program, profile):
    award = _programme_award(program)
    benefit = _read_benefit(award, period="ONE_OFF", amount_bound="UP_TO")
    assert _one_benefit(program, profile, benefit, {}).amount is None


def test_a_row_no_reader_wrote_passes_through_unchanged(program, profile):
    award = _programme_award(program)
    benefit = _read_benefit(award, amount_text="", amount_bound="", amount_quote="")
    fact = _one_benefit(program, profile, benefit, {})
    assert (fact.amount, fact.period) == (Decimal("1000"), "MONTHLY")


def test_an_award_fact_carries_its_card(award):
    award.duration_text, award.duration_months, award.timing = "12 months", 12, "PRE_ARRIVAL"
    benefit = _read_benefit(award, period="ONE_OFF", amount_text="€5,000", amount=Decimal("5000"))
    facts = award_facts(award, benefits=(benefit,), rules=())
    assert facts.card is not None and facts.card.duration_months == 12
    assert card_fill(facts.card)["amount"] == "FILLED"
