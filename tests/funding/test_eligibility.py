"""One vocabulary: the keys, the value forms, and what a region expands to."""

import datetime as dt
from dataclasses import dataclass
from dataclasses import field as dc_field

import pytest
from pydantic import ValidationError

from apps.funding.eligibility import (
    DEADLINE_PARTITION_KEYS,
    KEYS,
    ConditionTriple,
    decide,
    expand_countries,
)


def test_the_key_list_is_closed_and_holds_the_specs_twenty():
    assert len(KEYS) == 20
    for key in (
        "CITIZENSHIP", "RESIDENCE", "DESCENT", "FIELD", "PRIOR_DEGREE", "PRIOR_INSTITUTION",
        "GRADE", "TALENT", "WORK_EXPERIENCE", "LANGUAGE", "AGE", "GENDER", "NEED",
        "REFUGEE_OR_DISPLACED", "DISABILITY", "EMPLOYMENT", "AFFINITY", "GUARANTOR",
        "OPEN", "OTHER",
    ):
        assert key in KEYS, key
    # UNSTATED is deliberately absent: a page that states nothing writes no row.
    assert "UNSTATED" not in KEYS
    assert "REGION" not in KEYS and "LEVEL" not in KEYS


def test_a_triple_is_closed_and_carries_its_sentence():
    triple = ConditionTriple(
        key="CITIZENSHIP",
        operator="IN",
        value="AZ,TR",
        quote="Open to citizens of Azerbaijan and Türkiye.",
    )
    assert triple.key == "CITIZENSHIP" and triple.value == "AZ,TR"
    with pytest.raises(ValidationError):
        ConditionTriple(key="NATIONALITY", operator="IN", value="AZ", quote="x")
    with pytest.raises(ValidationError):
        ConditionTriple(key="CITIZENSHIP", operator="CONTAINS", value="AZ", quote="x")
    with pytest.raises(ValidationError):
        ConditionTriple(key="CITIZENSHIP", operator="IN", value="AZ", quote="x", extra="no")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AZ,TR", ("AZ", "TR")),
        ("az, tr", ("AZ", "TR")),
        ("WESTERN_BALKANS", ("AL", "BA", "ME", "MK", "RS", "XK")),
    ],
)
def test_a_country_set_expands_from_codes_or_a_named_region(value, expected):
    assert expand_countries(value) == expected


def test_a_region_the_table_does_not_know_expands_to_nothing():
    """None, never a guess: an unknown region must become UNDECIDABLE upstream."""
    assert expand_countries("GLOBAL_NORTH_ISH") is None
    assert expand_countries("") is None


def test_a_cyrillic_homoglyph_is_not_a_country_code():
    # Non-ASCII letters like Cyrillic АВ must return None, preventing
    # bogus codes from silently failing conditions meant to be undecidable.
    assert expand_countries("АВ") is None


def test_every_region_carries_a_source_url():
    from apps.funding.regions import REGIONS

    assert REGIONS
    for name, region in REGIONS.items():
        assert region.countries, name
        assert region.source.startswith("https://"), name
        assert all(len(code) == 2 and code.isupper() for code in region.countries), name


@dataclass
class _Experience:
    kind: str
    months: int


@dataclass
class _Academic:
    qualification: str = "Bachelor of Science"
    field: str = "robotics"
    institution: str = "Example University"
    country_code: str = "AZ"
    grade: str = "3.6"
    grading_scale: str = "GPA 4.0"


@dataclass
class _Language:
    language: str = "German"
    level: str = "C1"


@dataclass
class _Profile:
    nationality: str = "AZ"
    country_of_residence: str = "AZ"
    target_field: str = "robotics"
    academic_history: tuple = dc_field(default_factory=lambda: (_Academic(),))
    experience: tuple = dc_field(default_factory=tuple)
    language_evidence: tuple = dc_field(default_factory=tuple)
    date_of_birth: dt.date | None = None
    gender: str = ""


def _t(key, operator, value="", unit=None, quote="a published sentence"):
    return ConditionTriple(key=key, operator=operator, value=value, unit=unit, quote=quote)


def test_citizenship_in_a_country_set_is_satisfied_or_failed():
    assert decide(_t("CITIZENSHIP", "IN", "AZ,TR"), _Profile()).outcome == "SATISFIED"
    assert decide(_t("CITIZENSHIP", "IN", "DE,FR"), _Profile()).outcome == "FAILED"
    assert decide(_t("CITIZENSHIP", "NOT_IN", "DE,FR"), _Profile()).outcome == "SATISFIED"
    assert decide(_t("CITIZENSHIP", "IN", "EASTERN_PARTNERSHIP"), _Profile()).outcome == "SATISFIED"


def test_an_unknown_region_is_undecidable_and_names_itself():
    outcome = decide(_t("CITIZENSHIP", "IN", "THE_LEVANT"), _Profile())
    assert outcome.outcome == "UNDECIDABLE" and "THE_LEVANT" in outcome.reason


def test_residence_reads_its_own_field_not_nationality():
    profile = _Profile(nationality="AZ", country_of_residence="DE")
    assert decide(_t("RESIDENCE", "IN", "DE"), profile).outcome == "SATISFIED"
    assert decide(_t("CITIZENSHIP", "IN", "DE"), profile).outcome == "FAILED"


def test_descent_is_undecidable_because_the_profile_does_not_carry_it():
    outcome = decide(_t("DESCENT", "IN", "AM"), _Profile())
    assert outcome.outcome == "UNDECIDABLE" and "descent" in outcome.reason.casefold()


def test_a_field_that_does_not_match_is_undecidable_never_failed():
    """'engineering' does not demonstrably exclude 'robotics'."""
    assert decide(_t("FIELD", "IN", "robotics"), _Profile()).outcome == "SATISFIED"
    assert decide(_t("FIELD", "IN", "medicine"), _Profile()).outcome == "UNDECIDABLE"


def test_work_experience_in_months_is_decided_and_in_hours_is_not():
    profile = _Profile(experience=(_Experience("WORK", 30),))
    assert decide(_t("WORK_EXPERIENCE", "GTE", "24", "MONTHS"), profile).outcome == "SATISFIED"
    assert decide(_t("WORK_EXPERIENCE", "GTE", "36", "MONTHS"), profile).outcome == "FAILED"
    # 2,800 hours read as months would shut every route in the catalog.
    assert decide(_t("WORK_EXPERIENCE", "GTE", "2800", "HOURS"), profile).outcome == "UNDECIDABLE"


def test_only_work_counts_toward_a_professional_experience_bar():
    profile = _Profile(experience=(_Experience("INTERNSHIP", 30),))
    assert decide(_t("WORK_EXPERIENCE", "GTE", "24", "MONTHS"), profile).outcome == "FAILED"


def test_a_grade_decides_only_when_the_scales_are_the_same_string():
    profile = _Profile()  # 3.6 on "GPA 4.0"
    assert decide(_t("GRADE", "GTE", "3.0 GPA 4.0"), profile).outcome == "SATISFIED"
    assert decide(_t("GRADE", "GTE", "3.9 GPA 4.0"), profile).outcome == "FAILED"
    # Grades are never converted between systems (CLAUDE.md).
    assert decide(_t("GRADE", "GTE", "2.0 German 1-5"), profile).outcome == "UNDECIDABLE"


def test_grade_decides_on_an_identical_scale_and_talent_does_not_mean_a_number():
    """Two different conditions were sharing one key. GRADE is a numeric bar on a
    stated scale; TALENT is sports or arts, a label nothing in the profile decides.

    Owner decision 2026-09-22 (master spec section 17 row 25), taken while
    BenefitRule holds zero rows.
    """
    profile = _Profile()  # 3.6 on "GPA 4.0"
    grade = _t("GRADE", "GTE", "3.5 GPA 4.0", quote="A minimum GPA of 3.5 is required.")
    assert decide(grade, profile).outcome == "SATISFIED"

    talent = _t(
        "TALENT",
        "PRESENT",
        "music",
        quote="Open to students with a record of musical achievement.",
    )
    decision = decide(talent, profile)
    assert decision.outcome == "UNDECIDABLE"
    assert "profile does not carry" in decision.reason


def test_talent_never_decides_on_a_grade_whatever_operator_a_page_used():
    """The rename's whole point: the old key answered a GTE bar off
    academic_history. A page writing TALENT GTE must not reach that decider by
    the back door now that the label form owns the name."""
    profile = _Profile()  # 3.6 on "GPA 4.0"
    assert decide(_t("TALENT", "GTE", "3.0 GPA 4.0"), profile).outcome == "UNDECIDABLE"


def test_a_language_is_present_or_compared_only_in_cefr():
    profile = _Profile(language_evidence=(_Language("German", "C1"),))
    assert decide(_t("LANGUAGE", "PRESENT", "German"), profile).outcome == "SATISFIED"
    assert decide(_t("LANGUAGE", "PRESENT", "French"), profile).outcome == "FAILED"
    assert decide(_t("LANGUAGE", "GTE", "German B2"), profile).outcome == "SATISFIED"
    assert decide(_t("LANGUAGE", "GTE", "German C2"), profile).outcome == "FAILED"
    profile_native = _Profile(language_evidence=(_Language("German", "mother tongue"),))
    assert decide(_t("LANGUAGE", "GTE", "German B2"), profile_native).outcome == "UNDECIDABLE"


def test_prior_degree_and_prior_institution():
    profile = _Profile()
    assert decide(_t("PRIOR_DEGREE", "GTE", "BACHELOR"), profile).outcome == "SATISFIED"
    assert decide(_t("PRIOR_DEGREE", "GTE", "MASTER"), profile).outcome == "FAILED"
    assert decide(_t("PRIOR_INSTITUTION", "IN", "AZ"), profile).outcome == "SATISFIED"
    assert decide(_t("PRIOR_INSTITUTION", "IN", "DE"), profile).outcome == "FAILED"


def test_age_is_decided_once_a_birth_date_exists():
    born = _Profile(date_of_birth=dt.date(1996, 5, 1))
    assert decide(_t("AGE", "LTE", "35", "YEARS"), born).outcome == "SATISFIED"
    assert decide(_t("AGE", "LTE", "20", "YEARS"), born).outcome == "FAILED"
    assert decide(_t("AGE", "LTE", "35", "YEARS"), _Profile()).outcome == "UNDECIDABLE"


def test_gender_is_decided_once_asked_and_undecidable_when_declined():
    assert decide(_t("GENDER", "EQ", "female"), _Profile(gender="female")).outcome == "SATISFIED"
    assert decide(_t("GENDER", "EQ", "female"), _Profile(gender="male")).outcome == "FAILED"
    assert decide(_t("GENDER", "EQ", "female"), _Profile(gender="")).outcome == "UNDECIDABLE"


#: A substring unique to each key's curated _UNASKED reason, absent from the
#: generic fallback "{key}: no profile field decides this" -- asserting only
#: that `reason` is truthy would stay green even if _UNASKED were deleted.
_UNASKED_SUBSTRINGS = {
    "NEED": "income",
    "REFUGEE_OR_DISPLACED": "consultation",
    "DISABILITY": "consultation",
    "EMPLOYMENT": "employer",
    "AFFINITY": "membership",
    "GUARANTOR": "produced",
    "OTHER": "sentence",
}


@pytest.mark.parametrize(
    "key",
    ["NEED", "REFUGEE_OR_DISPLACED", "DISABILITY", "EMPLOYMENT", "AFFINITY", "GUARANTOR", "OTHER"],
)
def test_the_keys_no_profile_can_decide_say_which_field_is_missing(key):
    outcome = decide(_t(key, "PRESENT", "x"), _Profile())
    assert outcome.outcome == "UNDECIDABLE"
    assert _UNASKED_SUBSTRINGS[key] in outcome.reason.casefold()


def test_open_is_an_answer_not_an_absence():
    assert decide(_t("OPEN", "PRESENT"), _Profile()).outcome == "SATISFIED"


def test_the_deadline_partition_keys_are_not_eligibility_keys():
    """They say whose deadline a date is, never who may apply."""
    assert DEADLINE_PARTITION_KEYS == ("APPLICANT_CLASS", "FUNDING", "ROUTE", "ROUND")
    for key in DEADLINE_PARTITION_KEYS:
        assert key not in KEYS


# --- Fix round 1: an operator table per key, and five defects the brief's own
# code carried (docs/superpowers/sdd/2026-09-19-eligibility-vocabulary-and-
# register-amendment/task-2-report.md's fix-round-1 section has the findings).


def test_an_operator_outside_the_keys_table_is_undecidable_not_wrongly_decided():
    # Finding 1a. WORK_EXPERIENCE only permits GTE; LTE is the ordinary way a
    # page writes "no more than two years" and must not be silently answered
    # by the >= comparison the branch actually runs -- that read this 30-month
    # applicant as SATISFIED before the operator table existed.
    profile = _Profile(experience=(_Experience("WORK", 30),))
    outcome = decide(_t("WORK_EXPERIENCE", "LTE", "24", "MONTHS"), profile)
    assert outcome.outcome == "UNDECIDABLE"
    assert "WORK_EXPERIENCE" in outcome.reason and "LTE" in outcome.reason


def test_prior_degree_eq_decides_equality_not_at_least():
    # Finding 1b. Before the fix EQ was read as GTE, so a Master's degree
    # wrongly satisfied "exactly BACHELOR".
    profile = _Profile(academic_history=(_Academic(qualification="Master of Science"),))
    assert decide(_t("PRIOR_DEGREE", "EQ", "BACHELOR"), profile).outcome == "FAILED"
    assert decide(_t("PRIOR_DEGREE", "EQ", "MASTER"), profile).outcome == "SATISFIED"


def test_language_with_no_evidence_at_all_is_undecidable_not_failed():
    # Finding 2a. An empty language_evidence tuple is a student who has not
    # entered anything yet, not one who has proven they don't speak the
    # language -- that must not shut a route the page does not shut.
    outcome = decide(_t("LANGUAGE", "PRESENT", "German"), _Profile())
    assert outcome.outcome == "UNDECIDABLE"
    assert "language" in outcome.reason.casefold()


def test_work_experience_with_no_experience_attribute_at_all_is_undecidable():
    # Revised (Task 3): the original Finding 2b read an empty experience tuple as
    # unentered data and abstained. That premise does not hold for
    # StudentProfileSnapshot.experience, a required field the consultation asks
    # unconditionally -- there, an empty tuple is the student's answer of "none",
    # a recorded zero, not a missing source. What genuinely abstains is a caller
    # that carries no `experience` attribute at all, e.g. a profile-like object
    # from a source that never asked the question.
    outcome = decide(_t("WORK_EXPERIENCE", "GTE", "24", "MONTHS"), object())
    assert outcome.outcome == "UNDECIDABLE"
    assert "experience" in outcome.reason.casefold()


def test_work_experience_with_an_empty_answered_history_decides_zero_months():
    # The other half of the above: a profile that HAS an experience field, empty
    # because the student answered "none", is decided (FAILED against a positive
    # bar), not treated as missing data.
    outcome = decide(_t("WORK_EXPERIENCE", "GTE", "24", "MONTHS"), _Profile())
    assert outcome.outcome == "FAILED"
    assert "0 months" in outcome.reason


def test_a_diploma_is_not_promoted_to_a_masters_degree():
    # Finding 3. "Diploma in Nursing" casefold-contains "diplom"; a bare
    # substring check reads this as a Master's and would satisfy a GTE MASTER
    # bar it should not.
    profile = _Profile(academic_history=(_Academic(qualification="Diploma in Nursing"),))
    assert decide(_t("PRIOR_DEGREE", "GTE", "MASTER"), profile).outcome == "UNDECIDABLE"


def test_field_does_not_match_a_bare_substring_inside_an_unrelated_word():
    # Finding 4. "AI" is a substring of "ukrainian studies", glued between two
    # letters; without a word-boundary requirement this wrongly satisfied a
    # field the page never listed instead of reaching a human.
    profile = _Profile(target_field="Ukrainian studies")
    assert decide(_t("FIELD", "IN", "AI"), profile).outcome == "UNDECIDABLE"


def test_non_finite_experience_bars_are_undecidable_never_forced():
    # Finding 5. float() accepts "inf" and "nan" without raising; both must be
    # rejected as non-finite instead of forcing a comparison result.
    profile = _Profile(experience=(_Experience("WORK", 240),))
    assert decide(_t("WORK_EXPERIENCE", "GTE", "inf", "MONTHS"), profile).outcome == "UNDECIDABLE"
    assert decide(_t("WORK_EXPERIENCE", "GTE", "nan", "MONTHS"), profile).outcome == "UNDECIDABLE"


def test_a_negative_infinite_age_bar_is_undecidable_not_a_free_pass():
    # Finding 5. float("-inf") does not raise, so "at least -inf years" would
    # satisfy any age at all -- demonstrated live against a one-year-old.
    born = _Profile(date_of_birth=dt.date(2025, 1, 1))
    assert decide(_t("AGE", "GTE", "-inf", "YEARS"), born).outcome == "UNDECIDABLE"


def test_an_overflowing_grade_bar_is_undecidable_not_a_failed_grade():
    # Finding 5. "1e400" overflows float() to inf without raising, which would
    # fail a perfect 4.0 GPA against an unstatable bar instead of abstaining.
    profile = _Profile()  # 3.6 on "GPA 4.0"
    assert decide(_t("GRADE", "GTE", "1e400 GPA 4.0"), profile).outcome == "UNDECIDABLE"


def test_prior_institution_blank_value_does_not_match_a_blank_institution():
    # Finding 6. An empty condition.value must not match a record whose
    # institution field was left blank -- "" in {""} is a real but spurious set
    # membership.
    profile = _Profile(academic_history=(_Academic(institution=""),))
    assert decide(_t("PRIOR_INSTITUTION", "IN", ""), profile).outcome == "UNDECIDABLE"


# --- Fix round 2.


def test_a_fused_diplom_compound_still_resolves_to_masters():
    # Round 2, finding 1. "Diplomingenieur" is the standard German fused-
    # compound spelling; the bounded fix for "diploma" must not overcorrect
    # and lose the fused form the word was added for in the first place.
    profile = _Profile(academic_history=(_Academic(qualification="Diplomingenieur"),))
    assert decide(_t("PRIOR_DEGREE", "GTE", "MASTER"), profile).outcome == "SATISFIED"


def test_higher_national_diploma_still_resolves_to_no_level():
    # Round 2, finding 1. A different English "Diploma" phrasing than the one
    # already covered -- must still fail the "not followed by 'a'" rule.
    profile = _Profile(academic_history=(_Academic(qualification="Higher National Diploma"),))
    assert decide(_t("PRIOR_DEGREE", "GTE", "MASTER"), profile).outcome == "UNDECIDABLE"


def test_prior_institution_with_no_academic_history_is_undecidable_not_failed():
    # Round 2, finding 2. Empty academic_history makes held_countries an empty
    # set, and an empty intersection is falsy -- that must not read as a
    # proven non-match, the same defect round 1 fixed for LANGUAGE and
    # WORK_EXPERIENCE.
    outcome = decide(_t("PRIOR_INSTITUTION", "IN", "AZ"), _Profile(academic_history=()))
    assert outcome.outcome == "UNDECIDABLE"
    assert "academic history" in outcome.reason.casefold()
