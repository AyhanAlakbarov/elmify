from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from apps.accounts.schemas import ExperienceRecord, LanguageEvidence
from apps.funding.eligibility import decide
from apps.funding.evaluation import _as_triple, evaluate
from tests.funding.conftest import (
    EUR_RATES,
    make_applicant_condition,
    make_benefit,
    make_candidate,
    make_constraint,
    make_cost,
    make_profile,
)


def test_teaching_language_hard_gate_blocks_unlisted_language() -> None:
    profile = make_profile(acceptable_teaching_languages=("English",))
    candidate = make_candidate(teaching_languages=("German",))

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert "teaching-language evidence" in " ".join(result.reasons)


def test_teaching_language_evidence_must_be_deliverable_by_deadline() -> None:
    profile = make_profile(acceptable_teaching_languages=("English",), language_evidence=())
    candidate = make_candidate(
        teaching_languages=("English",),
        language_evidence_required=True,
        language_evidence_deadline=date(2026, 12, 1),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert "teaching-language evidence" in " ".join(result.reasons)


def test_confirmed_eligibility_failure_blocks() -> None:
    profile = make_profile()
    candidate = make_candidate(confirmed_eligibility_failure=True)

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("eligibility" in reason for reason in result.reasons)


def test_nonviable_deadline_blocks() -> None:
    profile = make_profile()
    candidate = make_candidate(deadline_is_viable=False)

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("deadline" in reason for reason in result.reasons)


def test_low_evidence_confidence_blocks() -> None:
    profile = make_profile()
    candidate = make_candidate(evidence_confidence="LOW")

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("evidence" in reason for reason in result.reasons)


def test_medium_evidence_confidence_passes_the_gate() -> None:
    profile = make_profile()
    candidate = make_candidate(evidence_confidence="MEDIUM")

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_non_negotiable_location_constraint_blocks() -> None:
    profile = make_profile(non_negotiables=(make_constraint("LOCATION", "Paris"),))
    candidate = make_candidate(city="Berlin", program_country_code="DE")

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("non-negotiable" in reason for reason in result.reasons)


def test_non_negotiable_location_constraint_satisfied() -> None:
    profile = make_profile(non_negotiables=(make_constraint("LOCATION", "Berlin"),))
    candidate = make_candidate(city="Berlin", program_country_code="DE")

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_mandatory_funding_without_viable_route_blocks() -> None:
    profile = make_profile(funding_dependency="MANDATORY")
    candidate = make_candidate(benefits=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("funding route" in reason for reason in result.reasons)


def test_mandatory_funding_with_viable_route_passes_the_gate() -> None:
    profile = make_profile(funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(make_benefit(scope_type="GLOBAL", eligibility_confidence="VERIFIED"),)
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome != "NOT_ELIGIBLE"


def test_uncertain_confidence_benefit_is_not_a_viable_funding_route() -> None:
    profile = make_profile(funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(make_benefit(scope_type="GLOBAL", eligibility_confidence="UNCERTAIN"),)
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"


def test_funding_never_overrides_language_hard_gate() -> None:
    profile = make_profile(acceptable_teaching_languages=("English",), strategy="FUNDING_FIRST")
    candidate = make_candidate(
        teaching_languages=("German",),
        cost_components=(),
        benefits=(make_benefit(amount="100000.00"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert "teaching-language evidence" in " ".join(result.reasons)


def test_balanced_eligible_when_thresholds_met() -> None:
    profile = make_profile(strategy="BALANCED")
    candidate = make_candidate(cost_components=())

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"
    assert result.scores is not None
    assert result.scores.overall >= Decimal("80")


def test_balanced_possibly_eligible_when_overall_below_eighty() -> None:
    profile = make_profile(strategy="BALANCED")
    candidate = make_candidate(
        cost_components=(),
        dimension_scores={
            "ACADEMIC_FIT": Decimal("50"),
            "PROGRAM_FIT": Decimal("50"),
            "CAREER_FIT": Decimal("50"),
            "DURATION": Decimal("50"),
            "MOBILITY_FIT": Decimal("50"),
            "RESEARCH_FIT": Decimal("50"),
        },
    )

    result = evaluate(profile, candidate, EUR_RATES)

    # Changed 2026-09-19: an eligible candidate that merely scores below the
    # balanced bar is not an eligibility question, and saying "possibly
    # eligible, needs review" with no reason told the student nothing.
    assert result.outcome == "ELIGIBLE_BELOW_FIT_BAR"
    assert any("overall fit" in reason and "80" in reason for reason in result.reasons)


def test_balanced_below_the_bar_when_a_critical_dimension_is_below_sixty() -> None:
    profile = make_profile(strategy="BALANCED")
    dimension_scores = {
        "ACADEMIC_FIT": Decimal("30"),
        "PROGRAM_FIT": Decimal("100"),
        "CAREER_FIT": Decimal("100"),
        "DURATION": Decimal("100"),
        "MOBILITY_FIT": Decimal("100"),
        "RESEARCH_FIT": Decimal("100"),
    }
    candidate = make_candidate(cost_components=(), dimension_scores=dimension_scores)

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE_BELOW_FIT_BAR"
    assert result.scores is not None
    assert result.scores.overall >= Decimal("80")
    # The dimension that fell short is named with its number, not just "below".
    assert any("ACADEMIC_FIT" in reason and "60" in reason for reason in result.reasons)


def test_funding_first_eligible_when_affordability_gap_is_closed() -> None:
    profile = make_profile(strategy="FUNDING_FIRST", funding_dependency="MANDATORY")
    candidate = make_candidate(
        cost_components=(),
        benefits=(make_benefit(amount="0.00", currency="EUR"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"


def test_funding_first_is_eligible_even_when_an_affordability_gap_remains() -> None:
    # Funding-first has no universal per-gap minimum beyond hard gates (P1-6); once a
    # verified route exists, a remaining gap only affects ranking order.
    profile = make_profile(strategy="FUNDING_FIRST", funding_dependency="MANDATORY")
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "5000.00"),),
        benefits=(make_benefit(amount="1000.00"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"
    assert result.scores is not None


def test_mandatory_funding_gate_rejects_a_benefit_for_another_nationality() -> None:
    profile = make_profile(nationality="KZ", funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(
            make_benefit(
                scope_type="NATIONALITY",
                nationality_code="AZ",
                accessibility="ORDINARY",
                eligibility_confidence="VERIFIED",
            ),
        ),
    )

    outcome = evaluate(profile, candidate, EUR_RATES)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("funding is mandatory" in reason for reason in outcome.reasons)


def test_a_program_in_an_excluded_country_is_rejected() -> None:
    profile = make_profile(excluded_countries=("RU",))
    candidate = make_candidate(program_country_code="RU")

    outcome = evaluate(profile, candidate, EUR_RATES)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("excluded" in reason for reason in outcome.reasons)


def test_a_program_outside_the_allowed_countries_is_rejected() -> None:
    profile = make_profile(allowed_countries=("DE", "NL"))
    candidate = make_candidate(program_country_code="FR")

    outcome = evaluate(profile, candidate, EUR_RATES)

    assert outcome.outcome == "NOT_ELIGIBLE"


def test_an_empty_allowed_list_means_no_country_restriction() -> None:
    profile = make_profile(allowed_countries=())
    candidate = make_candidate(program_country_code="FR")

    outcome = evaluate(profile, candidate, EUR_RATES)

    assert outcome.outcome == "ELIGIBLE"


def test_a_program_that_does_not_admit_the_students_nationality_is_rejected() -> None:
    profile = make_profile(nationality="AZ")
    candidate = make_candidate(excluded_nationalities=("AZ",))

    outcome = evaluate(profile, candidate, EUR_RATES)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("nationality" in reason for reason in outcome.reasons)


def test_a_nationality_restriction_for_another_country_does_not_apply() -> None:
    profile = make_profile(nationality="KZ")
    candidate = make_candidate(excluded_nationalities=("AZ",))

    outcome = evaluate(profile, candidate, EUR_RATES)

    assert outcome.outcome == "ELIGIBLE"


def test_a_lowercase_excluded_nationality_is_rejected_at_construction_not_silently_admitted() -> (
    None
):
    # Uppercase-vs-lowercase mismatch would defeat the gate silently and admit a student
    # the institution does not accept, so the code has to fail loud at the boundary.
    with pytest.raises(ValidationError):
        make_candidate(excluded_nationalities=("az",))


def test_a_program_country_code_that_is_not_an_active_iso_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_candidate(program_country_code="de")

    with pytest.raises(ValidationError):
        make_candidate(program_country_code="ZZ")


def test_a_nationality_scoped_benefit_without_a_nationality_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_benefit(scope_type="NATIONALITY", nationality_code=None)


def test_unmet_work_experience_condition_closes_that_route_only() -> None:
    """ADB-JSP's two-year bar excludes fresh graduates, who are most of our
    population. It shuts that scheme, not the programme: a student with another
    verified route is still fundable."""
    profile = make_profile(funding_dependency="MANDATORY", experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"), make_benefit(id="open-scheme")),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"


def test_unmet_work_experience_on_the_only_route_fails_the_mandatory_funding_gate() -> None:
    profile = make_profile(funding_dependency="MANDATORY", experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("no viable verified funding route" in reason for reason in result.reasons)


def test_met_work_experience_leaves_the_route_open() -> None:
    profile = make_profile(
        funding_dependency="MANDATORY",
        experience=(ExperienceRecord(kind="WORK", summary="Backend engineer", months=30),),
    )
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"


def test_internships_do_not_count_toward_a_professional_experience_bar() -> None:
    """The published bars say "professional work experience". Counting an internship
    toward one over-qualifies the student and produces exactly the false offer the
    spec calls worse than an omission."""
    profile = make_profile(
        funding_dependency="MANDATORY",
        experience=(ExperienceRecord(kind="INTERNSHIP", summary="Summer intern", months=36),),
    )
    candidate = make_candidate(
        benefits=(make_benefit(id="bonded-scheme"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"


def test_an_excluded_scheme_names_the_condition_that_excluded_it() -> None:
    """A pack that says "no viable funding route" and stops has told the student
    nothing they can act on. The reason has to name the scheme and the bar."""
    profile = make_profile(funding_dependency="MANDATORY", experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"),),
        applicant_conditions=(
            make_applicant_condition(
                benefit_id="adb-jsp",
                rule_text="at least two years of full-time professional work experience",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    named = " ".join(result.reasons)
    assert "adb-jsp" in named
    assert "WORK_EXPERIENCE" in named
    assert "two years of full-time professional work experience" in named


def test_a_closed_route_does_not_count_toward_affordability_coverage() -> None:
    """benefit_applies is the single point both the funding gate and the affordability
    buckets route through, so one guard closes the route in both."""
    from apps.funding.affordability import calculate_affordability

    profile = make_profile(experience=())
    candidate = make_candidate(
        cost_components=(make_cost("TUITION", "10000.00"),),
        benefits=(make_benefit(id="bonded-scheme", kind="TUITION", amount="8000.00"),),
        applicant_conditions=(make_applicant_condition(benefit_id="bonded-scheme"),),
    )

    affordability = calculate_affordability(profile, candidate, EUR_RATES)

    assert affordability.covered == Decimal("0.00")
    assert affordability.gap == Decimal("10000.00")


def test_an_age_cap_is_checked_against_the_date_of_birth() -> None:
    """Profile schema 3 carries a date of birth, so an age cap is decided, not sent
    to review. (A profile without one still routes to review -- that path is pinned
    in test_eligibility.py, which can build a profile with no date of birth.)"""
    candidate = make_candidate(
        benefits=(make_benefit(id="capped-scheme"),),
        applicant_conditions=(
            make_applicant_condition(
                "AGE_CAP",
                benefit_id="capped-scheme",
                comparable_value="35",
                rule_text="not more than 35 years old at the time of application",
            ),
        ),
    )

    # Funding is mandatory, so the capped scheme is the only route: closing it
    # closes the candidate, and the reason names the bar.
    def outcome(born: date):
        profile = make_profile(date_of_birth=born, funding_dependency="MANDATORY")
        return evaluate(profile, candidate, EUR_RATES)

    young, old = outcome(date(2000, 1, 1)), outcome(date(1970, 1, 1))

    assert young.outcome == "ELIGIBLE"
    assert old.outcome == "NOT_ELIGIBLE"
    assert any("35 years old" in reason for reason in old.reasons)


def test_a_means_test_routes_to_review_and_names_the_route() -> None:
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"),),
        applicant_conditions=(
            make_applicant_condition(
                "MEANS_TEST",
                benefit_id="adb-jsp",
                comparable_value="50000",
                rule_text="gross family income not exceeding USD 50,000 per annum",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("adb-jsp" in reason for reason in result.reasons)


def test_an_unevaluable_condition_on_an_inapplicable_route_does_not_force_review() -> None:
    """The route is scoped to a country this programme is not in, so its condition is
    moot. Sending a consultant a task about a scheme that never applied is noise."""
    profile = make_profile()
    candidate = make_candidate(
        program_country_code="DE",
        benefits=(make_benefit(id="fr-only", scope_type="COUNTRY", country_code="FR"),),
        applicant_conditions=(
            make_applicant_condition("TALENT", benefit_id="fr-only", comparable_value=None),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"
    assert result.reasons == ()


def test_a_route_already_closed_on_experience_does_not_also_force_review() -> None:
    """WORK_EXPERIENCE already shut this route in benefit_applies, so its unevaluable
    sibling condition is moot -- no consultant task for a scheme the student is out of."""
    profile = make_profile(experience=())
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"), make_benefit(id="open-scheme")),
        applicant_conditions=(
            make_applicant_condition(benefit_id="adb-jsp"),
            make_applicant_condition("TALENT", benefit_id="adb-jsp", comparable_value=None),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "ELIGIBLE"


def test_a_language_requirement_routes_to_review() -> None:
    """A party foundation funding an English-taught degree can still demand C1 German.
    No profile field decides it, so it is a consultant's task, not a silent pass."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="kas"),),
        applicant_conditions=(
            make_applicant_condition(
                "LANGUAGE",
                benefit_id="kas",
                comparable_value=None,
                rule_text="German at C1 level is required, including for programmes "
                "taught in English",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("kas" in reason for reason in result.reasons)
    assert any("C1" in reason for reason in result.reasons)


def test_a_guarantor_requirement_routes_to_review() -> None:
    """A hard gate that is not a number (design section 12). It closes the route for a
    student who cannot produce a guarantor, and nothing in the profile knows that."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="loan-scheme"),),
        applicant_conditions=(
            make_applicant_condition(
                "GUARANTOR",
                benefit_id="loan-scheme",
                comparable_value=None,
                rule_text="two guarantors resident in the country of study are required",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("guarantors resident" in reason for reason in result.reasons)


def test_an_experience_bar_published_in_hours_is_not_compared_against_months() -> None:
    """Chevening publishes 2,800 hours and the Swedish Institute 3,000; the profile
    holds months. Read as months, 2,800 shuts every route on earth. The bar must
    escalate instead -- an unconvertible unit is a consultant's task, not a filter."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="chevening"),),
        applicant_conditions=(
            make_applicant_condition(
                benefit_id="chevening",
                comparable_value="2800",
                comparable_unit="HOURS",
                rule_text="at least 2,800 hours of work experience",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("2,800 hours" in reason for reason in result.reasons)


def test_no_outcome_ever_excludes_a_candidate_without_telling_it_why() -> None:
    """The rule the module's own docstring states: a reason nobody can act on is
    the same as no reason. Every non-ELIGIBLE outcome must carry one."""
    profile = make_profile(strategy="BALANCED")
    low = {
        "ACADEMIC_FIT": Decimal("50"), "PROGRAM_FIT": Decimal("50"),
        "CAREER_FIT": Decimal("50"), "DURATION": Decimal("50"),
        "MOBILITY_FIT": Decimal("50"), "RESEARCH_FIT": Decimal("50"),
    }
    result = evaluate(
        profile, make_candidate(cost_components=(), dimension_scores=low), EUR_RATES
    )
    assert result.outcome != "ELIGIBLE"
    assert result.reasons, "an excluded candidate with no reason is the bug this pins"


def test_an_undecidable_condition_outranks_a_low_score() -> None:
    """Both are true at once on a weak candidate with an unquantifiable bar. The
    one a human can resolve is the one to report."""
    profile = make_profile(strategy="BALANCED")
    low = {
        "ACADEMIC_FIT": Decimal("50"), "PROGRAM_FIT": Decimal("50"),
        "CAREER_FIT": Decimal("50"), "DURATION": Decimal("50"),
        "MOBILITY_FIT": Decimal("50"), "RESEARCH_FIT": Decimal("50"),
    }
    candidate = make_candidate(
        cost_components=(),
        dimension_scores=low,
        benefits=(make_benefit(id="kas"),),
        applicant_conditions=(
            make_applicant_condition(
                "AFFILIATION", benefit_id="kas", rule_text="endorsement of the foundation's values"
            ),
        ),
    )
    result = evaluate(profile, candidate, EUR_RATES)
    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("kas" in reason for reason in result.reasons)


def test_the_evaluator_decides_a_citizenship_condition_through_the_shared_vocabulary() -> None:
    """Before this, only WORK_EXPERIENCE was decided and everything else escalated.

    Brief bug fixed here, same class as the work-experience test above: without
    funding_dependency="MANDATORY" a FAILED condition on the sole benefit never
    reaches the mandatory-funding hard gate, so the candidate stays ELIGIBLE
    instead of NOT_ELIGIBLE.
    """
    profile = make_profile(nationality="AZ", funding_dependency="MANDATORY")
    candidate = make_candidate(
        benefits=(make_benefit(id="daad"),),
        applicant_conditions=(
            make_applicant_condition(
                "CITIZENSHIP",
                benefit_id="daad",
                value="DE,FR",
                operator="IN",
                rule_text="Open to citizens of Germany and France.",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "NOT_ELIGIBLE"
    assert any("daad" in reason for reason in result.reasons)
    # Finding 2: closed_route_reasons used to always name condition_type, so this
    # printed "closed by its WORK_EXPERIENCE condition" for a citizenship
    # failure -- ApplicantConditionType has no OTHER member, so a new-vocabulary
    # row's condition_type is always some other legacy name here, and any of
    # them is wrong. The key is the true label once one is set.
    named = " ".join(result.reasons)
    assert "CITIZENSHIP condition" in named
    assert "WORK_EXPERIENCE condition" not in named


def test_an_undecidable_key_still_routes_to_review_with_its_reason() -> None:
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="kas"),),
        applicant_conditions=(
            make_applicant_condition(
                "DISABILITY",
                benefit_id="kas",
                comparable_value=None,
                operator="PRESENT",
                rule_text="Reserved for applicants with a recognised disability.",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("kas" in reason for reason in result.reasons)


def test_work_experience_behaviour_is_unchanged_by_the_shared_deciders() -> None:
    """The one key decided before this change must decide identically after it.

    Brief bug fixed here: `experience_months` is not a StudentProfileSnapshot
    field (it has `experience: tuple[ExperienceRecord, ...]`), and without
    `funding_dependency="MANDATORY"` an unmet condition on the sole benefit
    never forces NOT_ELIGIBLE -- see the pre-existing
    test_unmet_work_experience_on_the_only_route_fails_the_mandatory_funding_gate,
    which this mirrors.
    """
    profile = make_profile(
        funding_dependency="MANDATORY",
        experience=(ExperienceRecord(kind="WORK", summary="Backend engineer", months=12),),
    )
    candidate = make_candidate(
        benefits=(make_benefit(id="adb-jsp"),),
        applicant_conditions=(
            make_applicant_condition(
                "WORK_EXPERIENCE",
                benefit_id="adb-jsp",
                comparable_value="24",
                operator="GTE",
                value="24",
                rule_text="Two years of full-time professional experience.",
            ),
        ),
    )

    assert evaluate(profile, candidate, EUR_RATES).outcome == "NOT_ELIGIBLE"


def test_a_malformed_condition_escalates_instead_of_crashing_the_gate() -> None:
    """Finding 3. _as_triple casts an unvalidated key into ConditionTriple's closed
    Literal; pydantic raises ValidationError for one outside the vocabulary. This
    module escalates rather than guesses everywhere else -- one garbled row on one
    benefit must not abort evaluate() (and, upstream, pack.py's per-candidate loop)
    for the whole student."""
    profile = make_profile()
    candidate = make_candidate(
        benefits=(make_benefit(id="daad"),),
        applicant_conditions=(
            make_applicant_condition(
                "NOT_A_REAL_KEY",
                benefit_id="daad",
                value="x",
                rule_text="a garbled row",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("daad" in reason for reason in result.reasons)


def test_a_legacy_age_cap_fact_translates_to_the_lte_operator() -> None:
    """Findings 4/5. Pins the translation, not the decision -- no date of birth
    needed. An age cap is a maximum; read as GTE (a floor) it would decide the
    opposite of what the row says, silently, the moment a later task adds date of
    birth and AGE becomes decidable."""
    condition = make_applicant_condition(
        "AGE_CAP", benefit_id="capped-scheme", comparable_value="35"
    )

    triple = _as_triple(condition)

    assert triple.key == "AGE"
    assert triple.operator == "LTE"


def test_a_new_vocabulary_condition_with_no_value_never_inherits_a_synthesised_number() -> None:
    """Fix round 2's residual: condition_type is required and closed to the six
    legacy names, so every new-vocabulary row (this one, built via
    make_applicant_condition's non-legacy path) carries one as meaningless
    filler -- the shared factory picks WORK_EXPERIENCE, one of the three types
    the comparable_value fallback exists for. Gating that fallback on
    condition_type alone (rather than on the row also carrying no key of its
    own) would still synthesise a fabricated value -- reproduces exactly:
    make_applicant_condition('GENDER', operator='EQ', ...) used to translate to
    value='24' and decide FAILED by direct equality against it. Pinned at
    _as_triple, the translation, not decide()'s GENDER branch."""
    condition = make_applicant_condition(
        "GENDER", operator="EQ", rule_text="Open to women only."
    )

    triple = _as_triple(condition)

    assert triple.value == ""
    assert decide(triple, make_profile()).outcome == "UNDECIDABLE"


def test_a_legacy_language_condition_still_escalates_when_evidence_is_present() -> None:
    """Finding 1. BenefitRule.comparable_value is DB-CHECK-constrained to NULL for
    LANGUAGE, so a real legacy row never carries a number -- but before this fix,
    _as_triple synthesised one from the helper's own comparable_value default
    ("24"), which decide() partitioned into a "language" no student could hold,
    deciding FAILED. Measured: with no evidence at all the route escalated; with
    English C1 evidence present it decided NOT_ELIGIBLE -- a route that may be
    open, silently shut. This is the non-empty-language_evidence case the
    existing suite was missing."""
    profile = make_profile(
        language_evidence=(
            LanguageEvidence(
                language="English",
                level="C1",
                evidence_type="TEST",
                available_by=date(2027, 1, 1),
            ),
        ),
    )
    candidate = make_candidate(
        benefits=(make_benefit(id="kas"),),
        applicant_conditions=(
            make_applicant_condition(
                "LANGUAGE",
                benefit_id="kas",
                comparable_value=None,
                rule_text="German at C1 level is required.",
            ),
        ),
    )

    result = evaluate(profile, candidate, EUR_RATES)

    assert result.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("kas" in reason for reason in result.reasons)
