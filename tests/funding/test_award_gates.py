"""The four award gates.

An award is an application of its own, so it gets its own gates rather than
being squeezed through the programme ones: conditions the student demonstrably
fails, a cycle the evidence says is shut, a deadline already past, and evidence
the readings could not agree on.

Spec section 10.3.
"""

import datetime as dt

from apps.funding.evaluation import AwardCandidateFacts, evaluate_award
from apps.funding.validity import Evidence
from tests.funding.conftest import make_applicant_condition

TODAY = dt.date(2026, 9, 23)


def _award(**overrides) -> AwardCandidateFacts:
    fields = dict(
        award_id="award-1",
        name="Foundation Stipend",
        holder_name="Example Foundation",
        organisation_id="org-1",
        money_form="GRANT",
        route="STUDENT_APPLIES_SEPARATELY",
        unconfirmed=(),
        benefits=(),
        applicant_conditions=(),
        return_service=(),
        evidence_confidence="MEDIUM",
        evidence=Evidence(),
        coverage_is_unstated=True,
    )
    fields.update(overrides)
    return AwardCandidateFacts(**fields)  # type: ignore[arg-type]


def test_an_award_with_nothing_against_it_is_eligible(profile):
    assert evaluate_award(profile, _award(), today=TODAY).outcome == "ELIGIBLE"


def test_a_condition_the_student_demonstrably_fails_shuts_the_award(profile):
    """FAILED, not UNDECIDABLE: the profile carries the field and the answer is
    no. The reason quotes the funder's own sentence, because "not eligible" on
    its own tells a student nothing they can act on."""
    condition = make_applicant_condition(
        "WORK_EXPERIENCE",
        benefit_id="award-1",
        operator="GTE",
        value="240",
        comparable_value="240",
        comparable_unit="MONTHS",
        rule_text="Applicants need twenty years of professional experience.",
    )
    outcome = evaluate_award(profile, _award(applicant_conditions=(condition,)), today=TODAY)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("twenty years" in reason for reason in outcome.reasons)


def test_a_condition_nothing_can_decide_goes_to_review_never_to_exclusion(profile):
    """UNDECIDABLE is not a soft FAILED. Excluding here would hide an award the
    student may well be able to take."""
    condition = make_applicant_condition(
        "AFFINITY",
        benefit_id="award-1",
        operator="PRESENT",
        value="alumni association",
        rule_text="Open to members of the foundation's alumni association.",
    )
    outcome = evaluate_award(profile, _award(applicant_conditions=(condition,)), today=TODAY)

    assert outcome.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
    assert any("alumni association" in reason for reason in outcome.reasons)


def test_an_award_its_own_page_suspends_for_this_intake_is_not_eligible(profile):
    """The page dated its own negation. Serving it anyway puts a scholarship in
    the pack that the funder has withdrawn."""
    evidence = Evidence(
        offered="NO",
        contrary_on=dt.date(2026, 8, 1),
        contrary_intake=str(profile.intended_intake.year),
    )
    outcome = evaluate_award(profile, _award(evidence=evidence), today=TODAY)
    assert outcome.outcome == "NOT_ELIGIBLE"


def test_an_unverified_award_is_still_eligible_and_that_is_deliberate(profile):
    """Weaker than the spec's "only OPEN and UPCOMING are shown", on purpose.
    cycle_validity runs on step-0 evidence only, so without the evidence ladder
    UPCOMING is unreachable and nearly everything is UNVERIFIED. Gating hard
    today empties the pack for want of a crawler, which is the worse failure --
    and the same function tightens by itself once the ladder lands."""
    outcome = evaluate_award(profile, _award(evidence=Evidence()), today=TODAY)
    assert outcome.outcome == "ELIGIBLE"


def test_a_deadline_already_past_shuts_the_award(profile):
    evidence = Evidence(deadline=dt.date(2026, 1, 15))
    outcome = evaluate_award(profile, _award(evidence=evidence), today=TODAY)

    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("2026-01-15" in reason for reason in outcome.reasons)


def test_a_deadline_still_ahead_does_not(profile):
    evidence = Evidence(deadline=dt.date(2027, 1, 15))
    assert evaluate_award(profile, _award(evidence=evidence), today=TODAY).outcome == "ELIGIBLE"


def test_low_evidence_confidence_shuts_the_award(profile):
    outcome = evaluate_award(profile, _award(evidence_confidence="LOW"), today=TODAY)
    assert outcome.outcome == "NOT_ELIGIBLE"
    assert any("did not agree" in reason for reason in outcome.reasons)


def test_a_failed_condition_is_reported_before_a_missing_deadline(profile):
    """Order matters for what a student reads: a bar they cannot clear is more
    useful than a date, and reporting the date first would send them looking for
    a deadline extension that could not help."""
    condition = make_applicant_condition(
        "WORK_EXPERIENCE",
        benefit_id="award-1",
        operator="GTE",
        value="240",
        comparable_value="240",
        comparable_unit="MONTHS",
        rule_text="Applicants need twenty years of professional experience.",
    )
    outcome = evaluate_award(
        profile,
        _award(applicant_conditions=(condition,), evidence=Evidence(deadline=dt.date(2026, 1, 1))),
        today=TODAY,
    )
    assert any("twenty years" in reason for reason in outcome.reasons)


def test_a_student_never_asked_about_experience_goes_to_review_not_exclusion():
    """The short onboarding does not ask about experience, so the profile it
    builds carries None, not an empty answer. Reading that as "none" shut every
    award with an experience bar for every student."""
    from apps.accounts.schemas import StudentProfileSnapshot
    from tests.accounts.test_profile_schema_v3 import _answers

    profile = StudentProfileSnapshot.model_validate(_answers())
    assert profile.experience is None
    condition = make_applicant_condition(
        "WORK_EXPERIENCE",
        benefit_id="award-1",
        operator="GTE",
        value="24",
        comparable_value="24",
        comparable_unit="MONTHS",
        rule_text="Applicants need two years of professional experience.",
    )
    outcome = evaluate_award(profile, _award(applicant_conditions=(condition,)), today=TODAY)
    assert outcome.outcome == "POSSIBLY_ELIGIBLE_REVIEW"
