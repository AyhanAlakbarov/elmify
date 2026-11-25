import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.accounts.consultation import (
    ConsultationDraft,
    _apply_duration_preference_from_notes,
    _profile_payload,
)
from apps.accounts.schemas import (
    DEFAULT_WEIGHTS,
    EVALUATION_DIMENSIONS,
    AcademicRecord,
    EvaluationDimension,
    ProfileConstraint,
    compute_weak_order_roc_weights,
    infer_simplex_weights_from_profile,
)
from apps.funding.affordability import calculate_affordability
from apps.funding.evaluation import (
    DimensionScore,
    compute_weighted_power_mean,
    duration_band,
    duration_category,
    score_dimensions,
)
from apps.funding.facts import score_program_fit
from apps.funding.models import Institution, Program, ProgramStatement
from tests.funding.conftest import EUR_RATES, make_candidate, make_profile

# ---------------------------------------------------------------------------
# 1. Preference Polytope Barycenter (Weak-Order ROC(epsilon))
# ---------------------------------------------------------------------------


def test_compute_weak_order_roc_weights_strict_order_matches_analytic_barycenter() -> None:
    """Under a strict ranking s_1 > s_2 > ... > s_7, ROC(epsilon) equals
    epsilon + (1 - 7*epsilon)/7 * sum_{j=k}^7 (1/j)."""
    salience: dict[EvaluationDimension, Decimal] = {
        "AFFORDABILITY": Decimal("70"),
        "ACADEMIC_FIT": Decimal("60"),
        "PROGRAM_FIT": Decimal("50"),
        "CAREER_FIT": Decimal("40"),
        "MOBILITY_FIT": Decimal("30"),
        "RESEARCH_FIT": Decimal("20"),
        "DURATION": Decimal("10"),
    }
    weights = compute_weak_order_roc_weights(salience, epsilon=Decimal("0.03"))

    assert set(weights.keys()) == set(EVALUATION_DIMENSIONS)
    assert abs(sum(weights.values(), Decimal("0")) - Decimal("1")) < Decimal("1e-20")
    assert all(w >= Decimal("0.03") for w in weights.values())

    ordered_dims: list[EvaluationDimension] = [
        "AFFORDABILITY",
        "ACADEMIC_FIT",
        "PROGRAM_FIT",
        "CAREER_FIT",
        "MOBILITY_FIT",
        "RESEARCH_FIT",
        "DURATION",
    ]
    for hi, lo in zip(ordered_dims, ordered_dims[1:], strict=False):
        assert weights[hi] > weights[lo]

    # Exact closed-form verification for top and bottom ranks (D=7, eps=0.03 -> 0.79/7 * H_7)
    assert weights["AFFORDABILITY"].quantize(Decimal("0.01")) == Decimal("0.32")
    assert weights["DURATION"].quantize(Decimal("0.01")) == Decimal("0.05")


def test_compute_weak_order_roc_weights_all_tied_is_uniform() -> None:
    salience = {dim: Decimal("1.0") for dim in EVALUATION_DIMENSIONS}
    weights = compute_weak_order_roc_weights(salience, epsilon=Decimal("0.03"))
    assert abs(sum(weights.values(), Decimal("0")) - Decimal("1")) < Decimal("1e-20")
    for w in weights.values():
        assert Decimal("0.14") <= w <= Decimal("0.15")


def test_infer_simplex_weights_neutral_profile_returns_default_weights() -> None:
    profile = make_profile(
        funding_dependency="IMPORTANT",
        strategy="BALANCED",
        duration_preference="NONE",
        duration_flexibility="NOT_APPLICABLE",
        career_intent="UNDECIDED",
        mobility_priorities=(),
        research_interests=(),
        non_negotiables=(),
        negotiable_preferences=(),
    )
    inferred = infer_simplex_weights_from_profile(profile)
    assert inferred == DEFAULT_WEIGHTS
    assert sum(inferred.values(), Decimal("0")) == Decimal("1.00")


def test_infer_simplex_weights_funding_first_mandatory_boosts_affordability() -> None:
    profile = make_profile(
        funding_dependency="MANDATORY",
        strategy="FUNDING_FIRST",
        career_intent="UNDECIDED",
    )
    weights = infer_simplex_weights_from_profile(profile)
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00")
    assert weights["AFFORDABILITY"] > DEFAULT_WEIGHTS["AFFORDABILITY"]
    assert weights["AFFORDABILITY"] == max(weights.values())


def test_infer_simplex_weights_self_funded_reduces_affordability_below_career_fit() -> None:
    profile = make_profile(
        funding_dependency="OPTIONAL",
        strategy="BALANCED",
        career_intent="WORK_ABROAD",
        negotiable_preferences=(
            ProfileConstraint(kind="OTHER", value="NO_FUNDING_NEEDED"),
        ),
    )
    weights = infer_simplex_weights_from_profile(profile)
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00")
    assert weights["AFFORDABILITY"] < DEFAULT_WEIGHTS["AFFORDABILITY"]
    assert weights["CAREER_FIT"] > weights["AFFORDABILITY"]


def test_infer_simplex_weights_research_boosts_research_and_academic_fit() -> None:
    profile = make_profile(
        funding_dependency="IMPORTANT",
        strategy="BALANCED",
        career_intent="PHD",
        research_interests=("computational neuroscience", "bayesian inference"),
    )
    weights = infer_simplex_weights_from_profile(profile)
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00")
    assert weights["RESEARCH_FIT"] > DEFAULT_WEIGHTS["RESEARCH_FIT"]
    assert weights["ACADEMIC_FIT"] >= DEFAULT_WEIGHTS["ACADEMIC_FIT"]


def test_infer_simplex_weights_work_abroad_boosts_mobility_and_career_fit() -> None:
    profile = make_profile(
        funding_dependency="IMPORTANT",
        strategy="BALANCED",
        career_intent="WORK_ABROAD",
        mobility_priorities=("POST_STUDY_WORK",),
    )
    weights = infer_simplex_weights_from_profile(profile)
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00")
    assert weights["MOBILITY_FIT"] > DEFAULT_WEIGHTS["MOBILITY_FIT"]
    assert weights["CAREER_FIT"] >= DEFAULT_WEIGHTS["CAREER_FIT"]


def test_infer_simplex_weights_duration_non_negotiable_boosts_duration() -> None:
    profile = make_profile(
        funding_dependency="IMPORTANT",
        strategy="BALANCED",
        duration_preference="ONE_AND_HALF_YEAR",
        duration_flexibility="NON_NEGOTIABLE",
    )
    weights = infer_simplex_weights_from_profile(profile)
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00")
    assert weights["DURATION"] > DEFAULT_WEIGHTS["DURATION"]


# ---------------------------------------------------------------------------
# 2. 1.5-Year (15-18 Month) Duration Band & Consultation Notes Extraction
# ---------------------------------------------------------------------------


def test_duration_band_partitions_1_year_1_5_year_and_2_year() -> None:
    assert duration_band(12) == "ONE_YEAR"
    assert duration_band(14) == "ONE_YEAR"
    assert duration_band(15) == "ONE_AND_HALF_YEAR"
    assert duration_band(16) == "ONE_AND_HALF_YEAR"
    assert duration_band(18) == "ONE_AND_HALF_YEAR"
    assert duration_band(19) == "TWO_YEAR"
    assert duration_band(24) == "TWO_YEAR"
    assert duration_category(12) == "ONE_YEAR"
    assert duration_category(24) == "TWO_YEAR"


def test_consultation_notes_extract_1_5_year_and_18_month_duration_preferences() -> None:
    for note in (
        "Prefer a 1.5-year (18-month) master's program.",
        "Student wants an 18-month master's program in data science.",
        "Looking for a 3-semester programme in Germany.",
    ):
        payload: dict[str, object] = {}
        _apply_duration_preference_from_notes(note, payload)
        assert payload["duration_preference"] == "ONE_AND_HALF_YEAR"
        assert payload["duration_flexibility"] == "WEIGHTED"

    strict_payload: dict[str, object] = {}
    _apply_duration_preference_from_notes(
        "Must be a 1.5-year master's program only.",
        strict_payload,
    )
    assert strict_payload["duration_preference"] == "ONE_AND_HALF_YEAR"
    assert strict_payload["duration_flexibility"] == "NON_NEGOTIABLE"


def test_consultation_profile_payload_infers_weights_automatically() -> None:
    draft = ConsultationDraft(
        tenant_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        answers={
            "target_field": "Computer Science",
            "funding_dependency": "MANDATORY",
            "strategy": "FUNDING_FIRST",
            "career_intent": "PHD",
            "research_interests": ["quantum computing"],
        },
    )
    payload = _profile_payload(draft)
    assert "weights" in payload
    weights = payload["weights"]
    assert isinstance(weights, dict)
    assert sum(weights.values(), Decimal("0")) == Decimal("1.00")
    assert weights["AFFORDABILITY"] > DEFAULT_WEIGHTS["AFFORDABILITY"]


# ---------------------------------------------------------------------------
# 3. GPA-Aware ACADEMIC_FIT & 3-Band DURATION Scoring in score_program_fit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_score_program_fit_reflects_gpa_standing_and_gpa_statements() -> None:
    inst = Institution.objects.create(
        canonical_key=f"institution:{uuid.uuid4()}",
        name="Test Technical University",
        country_code="DE",
        official_website="https://tu.example.org",
    )
    prog = Program.objects.create(
        institution=inst,
        canonical_key=f"program:{uuid.uuid4()}",
        name="MSc Computer Science",
        campus_name="Main",
        city="Munich",
        country_code="DE",
        location_key="DE:munich",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=18,
    )

    # 1. Summa-cum-laude student (3.98 / 4.0 -> Bavarian ~1.03 <= 1.15) gets +5 bonus
    high_gpa_profile = make_profile(
        target_field="Computer Science",
        academic_history=(
            AcademicRecord(
                institution="ADA University",
                country_code="AZ",
                qualification="Bachelor of Science",
                field="Computer Science",
                grade="3.98",
                grading_scale="4.0 GPA",
                completed_on=date(2024, 6, 1),
            ),
        ),
    )
    scores_high = score_program_fit(prog, high_gpa_profile, statements=())
    assert scores_high["ACADEMIC_FIT"] == Decimal("95")

    # 2. Low-GPA student (2.3 / 4.0 -> Bavarian ~3.55 > 2.50) gets penalized below 85
    low_gpa_profile = make_profile(
        target_field="Computer Science",
        academic_history=(
            AcademicRecord(
                institution="ADA University",
                country_code="AZ",
                qualification="Bachelor of Science",
                field="Computer Science",
                grade="2.3",
                grading_scale="4.0 GPA",
                completed_on=date(2024, 6, 1),
            ),
        ),
    )
    scores_low = score_program_fit(prog, low_gpa_profile, statements=())
    assert scores_low["ACADEMIC_FIT"] < Decimal("85")

    # 3. Explicit GPA requirement statement satisfied vs failed
    gpa_stmt = ProgramStatement(
        program=prog,
        kind="COMPETENCY",
        requirement="REQUIRED",
        text="Minimum GPA of 3.5 on a 4.0 scale is required.",
    )
    normal_profile = make_profile(target_field="Computer Science")
    scores_stmt_pass = score_program_fit(prog, normal_profile, statements=(gpa_stmt,))
    scores_stmt_fail = score_program_fit(prog, low_gpa_profile, statements=(gpa_stmt,))
    assert scores_stmt_pass["ACADEMIC_FIT"] == Decimal("95")
    assert scores_stmt_fail["ACADEMIC_FIT"] < scores_low["ACADEMIC_FIT"]


@pytest.mark.django_db
def test_score_program_fit_scores_three_duration_bands_smoothly() -> None:
    inst = Institution.objects.create(
        canonical_key=f"institution:{uuid.uuid4()}",
        name="Duration Test University",
        country_code="NL",
        official_website="https://dtu.example.org",
    )
    prog_18 = Program.objects.create(
        institution=inst,
        canonical_key=f"program:{uuid.uuid4()}",
        name="MSc Applied Mathematics",
        campus_name="Main",
        city="Delft",
        country_code="NL",
        location_key="NL:delft",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=18,
    )
    prog_24 = Program.objects.create(
        institution=inst,
        canonical_key=f"program:{uuid.uuid4()}",
        name="MSc Pure Mathematics",
        campus_name="Main",
        city="Delft",
        country_code="NL",
        location_key="NL:delft",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )

    pref_1_5 = make_profile(
        duration_preference="ONE_AND_HALF_YEAR",
        duration_flexibility="WEIGHTED",
    )
    assert score_program_fit(prog_18, pref_1_5)["DURATION"] == Decimal("90")
    assert score_program_fit(prog_24, pref_1_5)["DURATION"] == Decimal("78")

    pref_1yr_just = make_profile(
        duration_preference="ONE_YEAR",
        duration_flexibility="WEIGHTED",
        longer_program_justifications=("FUNDING",),
    )
    assert score_program_fit(prog_18, pref_1yr_just)["DURATION"] == Decimal("78")
    assert score_program_fit(prog_24, pref_1yr_just)["DURATION"] == Decimal("65")

    pref_1yr_internship = make_profile(
        duration_preference="ONE_YEAR",
        duration_flexibility="WEIGHTED",
        longer_program_justifications=("INTERNSHIP",),
    )
    assert score_program_fit(prog_18, pref_1yr_internship)["DURATION"] == Decimal("88")


# ---------------------------------------------------------------------------
# 4. Conjunctive-Compensatory Weighted Generalized Power Mean (Proposition 2)
# ---------------------------------------------------------------------------


def test_weighted_power_mean_special_cases_and_monotonicity() -> None:
    dims = (
        DimensionScore("ACADEMIC_FIT", Decimal("60"), Decimal("0.50")),
        DimensionScore("AFFORDABILITY", Decimal("100"), Decimal("0.50")),
    )
    m_arith = compute_weighted_power_mean(dims, p=1.0)
    m_geom = compute_weighted_power_mean(dims, p=0.0)
    m_half = compute_weighted_power_mean(dims, p=-0.5)
    m_harm = compute_weighted_power_mean(dims, p=-1.0)

    assert m_arith == Decimal("80.00")
    assert m_geom == Decimal("77.46")
    assert m_half == Decimal("76.21")
    assert m_harm == Decimal("75.00")
    assert m_arith > m_geom > m_half > m_harm


def test_weighted_power_mean_strict_schur_concavity_penalizes_bottlenecks() -> None:
    balanced = (
        DimensionScore("ACADEMIC_FIT", Decimal("80"), Decimal("0.25")),
        DimensionScore("AFFORDABILITY", Decimal("80"), Decimal("0.25")),
        DimensionScore("PROGRAM_FIT", Decimal("80"), Decimal("0.25")),
        DimensionScore("CAREER_FIT", Decimal("80"), Decimal("0.25")),
    )
    lopsided = (
        DimensionScore("ACADEMIC_FIT", Decimal("52"), Decimal("0.25")),
        DimensionScore("AFFORDABILITY", Decimal("88"), Decimal("0.25")),
        DimensionScore("PROGRAM_FIT", Decimal("90"), Decimal("0.25")),
        DimensionScore("CAREER_FIT", Decimal("90"), Decimal("0.25")),
    )

    assert compute_weighted_power_mean(balanced, p=1.0) == Decimal("80.00")
    assert compute_weighted_power_mean(lopsided, p=1.0) == Decimal("80.00")

    conj_balanced = compute_weighted_power_mean(balanced, p=-0.5)
    conj_lopsided = compute_weighted_power_mean(lopsided, p=-0.5)

    assert conj_balanced == Decimal("80.00")
    assert conj_lopsided < Decimal("78.00")


def test_score_dimensions_populates_conjunctive_overall() -> None:
    profile = make_profile()
    candidate = make_candidate(
        cost_components=(),
        dimension_scores={
            "ACADEMIC_FIT": Decimal("90"),
            "RESEARCH_FIT": Decimal("50"),
            "PROGRAM_FIT": Decimal("85"),
            "CAREER_FIT": Decimal("80"),
            "MOBILITY_FIT": Decimal("75"),
            "DURATION": Decimal("90"),
        },
    )
    affordability = calculate_affordability(profile, candidate, EUR_RATES)
    scores = score_dimensions(profile, candidate, affordability)

    assert scores.conjunctive_overall > Decimal("0")
    assert scores.conjunctive_overall <= scores.overall
    assert scores.conjunctive_overall == compute_weighted_power_mean(scores.dimensions, p=-0.5)
