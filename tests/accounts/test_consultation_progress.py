"""Wizard progress indicator. Db-free."""

from uuid import uuid4

from apps.accounts.consultation import ConsultationDraft, consultation_progress


def _draft(answers: dict) -> ConsultationDraft:
    return ConsultationDraft(tenant_id=uuid4(), membership_id=uuid4(), answers=answers)


def test_progress_counts_only_applicable_questions():
    answered, total = consultation_progress(_draft({}))
    assert answered == 0
    # language_evidence is conditional on acceptable_teaching_languages being
    # answered, so it is not applicable yet.
    baseline_total = total

    answered, grown_total = consultation_progress(
        _draft({"acceptable_teaching_languages": ["EN"]})
    )
    assert answered == 1
    # The conditional question entered the denominator (documented dynamic
    # behavior).
    assert grown_total == baseline_total + 1


def test_progress_reaches_total_when_all_applicable_answered():
    from apps.accounts.consultation import QUESTIONS

    answers = {}
    for question in QUESTIONS:
        if question.asked_when(_draft(answers)):
            answers[question.key] = "x"
    # One more sweep for conditionals unlocked by the first pass.
    for question in QUESTIONS:
        if question.asked_when(_draft(answers)) and question.key not in answers:
            answers[question.key] = "x"
    answered, total = consultation_progress(_draft(answers))
    assert answered == total


_RECORD = {
    "institution": "Baku State University",
    "country_code": "AZ",
    "qualification": "BSc",
    "field": "Chemistry",
    "grade": "90",
    "grading_scale": "100",
    "completed_on": "2026-06-30",
}


def test_the_short_set_totals_fourteen_or_fifteen_with_self_funding():
    base = {"academic_history": [_RECORD], "acceptable_teaching_languages": ["English"]}
    assert consultation_progress(_draft({**base, "funding_dependency": "MANDATORY"}))[1] == 14
    assert consultation_progress(_draft({**base, "funding_dependency": "OPTIONAL"}))[1] == 15
    undated = {**_RECORD, "completed_on": None}
    asked = {**base, "academic_history": [undated], "funding_dependency": "OPTIONAL"}
    assert consultation_progress(_draft(asked))[1] == 16
