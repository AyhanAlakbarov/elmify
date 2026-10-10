from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from apps.accounts.schemas import DEFAULT_WEIGHTS, AcademicRecord, StudentProfileSnapshot
from apps.documents.transcript import TranscriptContent, academic_record


def _answers(**overrides):
    values = {
        "nationality": "AZ",
        "country_of_residence": "AZ",
        "date_of_birth": "2002-05-01",
        "academic_history": [
            {
                "institution": "Baku State University",
                "country_code": "AZ",
                "qualification": "BSc",
                "field": "Chemistry",
                "grade": "88",
                "grading_scale": "0-100",
                "completed_on": None,
                "expected_completion": "2027-06-30",
                "courses": [
                    {
                        "title": "Organic Chemistry I",
                        "ects": "6.00",
                        "grade": "91",
                        "in_progress": False,
                    }
                ],
            }
        ],
        "target_field": "Chemistry, maybe synthesis",
        "intended_intake": "2027-09-01",
        "acceptable_teaching_languages": ["English"],
        "language_evidence": [],
        "career_intent": "PHD",
        "application_budget": {"amount": "300", "currency": "EUR"},
        "funding_dependency": "MANDATORY",
    }
    return {**values, **overrides}


def test_the_short_onboarding_answers_make_a_valid_profile():
    profile = StudentProfileSnapshot.model_validate(_answers())
    assert profile.schema_version == 3
    assert profile.strategy == "FUNDING_FIRST"
    assert profile.duration_preference == "NONE"
    assert profile.weights == DEFAULT_WEIGHTS
    assert profile.academic_history[0].courses[0].ects == Decimal("6.00")


def test_not_mandatory_funding_needs_a_self_funding_capacity():
    with pytest.raises(ValidationError) as error:
        StudentProfileSnapshot.model_validate(_answers(funding_dependency="IMPORTANT"))
    assert error.value.errors()[0]["ctx"]["target"] == "self_funding_capacity"


def test_a_self_funded_student_defaults_to_balanced():
    profile = StudentProfileSnapshot.model_validate(
        _answers(
            funding_dependency="OPTIONAL",
            self_funding_capacity={"amount": "15000", "currency": "EUR"},
        )
    )
    assert profile.strategy == "BALANCED"


def test_the_old_career_intent_values_are_gone():
    with pytest.raises(ValidationError):
        StudentProfileSnapshot.model_validate(_answers(career_intent="RESEARCH_OR_PHD"))


def test_a_birth_date_in_the_future_is_refused():
    with pytest.raises(ValidationError):
        StudentProfileSnapshot.model_validate(
            _answers(date_of_birth="2999-01-01")
        )


def test_default_weights_sum_to_one():
    assert sum(DEFAULT_WEIGHTS.values(), Decimal("0")) == Decimal("1")


def test_a_transcript_reading_becomes_an_academic_record():
    content = TranscriptContent.model_validate(
        {
            "institution": "Baku State University",
            "country_code": "AZ",
            "qualification": "BSc",
            "field": "Chemistry",
            "overall_grade": None,
            "grading_scale": None,
            "credit_unit": "ECTS",
            "courses": [
                {
                    "title": "Organic Chemistry I",
                    "credits": 6,
                    "grade": "91",
                    "status": "COMPLETED",
                },
                {"title": "Thesis", "credits": None, "grade": None, "status": "IN_PROGRESS"},
            ],
            "expected_completion": "2027-06-30",
        }
    )
    record = AcademicRecord.model_validate(academic_record(content))
    assert record.expected_completion == date(2027, 6, 30)
    assert record.courses[0].ects == Decimal("6.00")
    assert record.courses[1].in_progress is True
    assert record.courses[1].ects is None
