
from datetime import timedelta
from uuid import uuid4

import pytest

from apps.accounts.consultation import (
    ConsultationDraft,
    finalize_consultation,
    next_profile_question,
    prefill_from_latest_reading,
)
from apps.concierge.documents import register
from apps.documents.models import TranscriptReading
from apps.documents.transcript import Highlight
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db

_RECORD = {
    "institution": "Baku State University",
    "country_code": "AZ",
    "qualification": "BSc",
    "field": "Chemistry",
    "grade": "88",
    "grading_scale": "0-100",
    "completed_on": None,
    "expected_completion": "2027-06-30",
    "courses": [
        {"title": "Organic Chemistry I", "ects": "6.00", "grade": "91", "in_progress": False}
    ],
}


def _student(agency, django_user_model, name):
    user = django_user_model.objects.create(username=name)
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


_GRADE_UNSURE = Highlight(kind="unsure", scope="field", ref="grading_scale")


def _reading(agency, student, highlights=()):
    document = register(agency.id, student.id, kind="TRANSCRIPT")
    return TranscriptReading.objects.create(
        student=student,
        document=document,
        record=_RECORD,
        highlights=[highlight.model_dump() for highlight in highlights],
    )


def test_a_reading_prefills_the_academic_record_and_skips_its_question(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p1")
        reading = _reading(agency_a, student, highlights=(_GRADE_UNSURE,))
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id == reading.id
    assert draft.highlights == (_GRADE_UNSURE,)
    assert draft.answer("academic_history")[0]["courses"][0]["title"] == "Organic Chemistry I"
    asked = []
    while (question := next_profile_question(draft)) is not None:
        asked.append(question.key)
        draft = draft.with_answer(question.key, _ANSWERS[question.key])
    assert "academic_history" not in asked


def test_without_a_reading_the_academic_record_is_asked(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p2")
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None
    keys = []
    while (question := next_profile_question(draft)) is not None:
        keys.append(question.key)
        draft = draft.with_answer(question.key, _ANSWERS.get(question.key, [_RECORD]))
    assert "academic_history" in keys


def test_mandatory_funding_skips_self_funding_and_changing_it_clears_the_answer():
    draft = ConsultationDraft(uuid4(), uuid4(), {})
    draft = draft.with_answer("funding_dependency", "OPTIONAL")
    draft = draft.with_answer("self_funding_capacity", {"amount": "10000.00", "currency": "EUR"})
    draft = draft.with_answer("funding_dependency", "MANDATORY")
    assert draft.answer("self_funding_capacity") is None


def test_finalize_records_what_the_student_kept(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p3")
        reading = _reading(agency_a, student)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
        while (question := next_profile_question(draft)) is not None:
            draft = draft.with_answer(question.key, _ANSWERS[question.key])
        finalize_consultation(membership=student, draft=draft)
        reading.refresh_from_db()
        assert reading.accepted == draft.answer("academic_history")[0]


def test_an_accepted_reading_is_not_prefilled_again(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p4")
        reading = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=reading.id).update(accepted=_RECORD)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None


def _undated_record():
    return [{**_RECORD, "expected_completion": None, "courses": []}]


def test_a_record_with_no_dates_asks_when_the_student_graduates():
    draft = ConsultationDraft(uuid4(), uuid4(), {})
    keys = []
    while (question := next_profile_question(draft)) is not None:
        keys.append(question.key)
        value = _undated_record() if question.key == "academic_history" else None
        draft = draft.with_answer(question.key, value or _ANSWERS.get(question.key, "2027-06-30"))
    assert keys[keys.index("academic_history") + 1] == "expected_completion"


def test_a_prefilled_graduation_date_skips_the_question(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p5")
        _reading(agency_a, student)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    keys = []
    while (question := next_profile_question(draft)) is not None:
        keys.append(question.key)
        draft = draft.with_answer(question.key, _ANSWERS[question.key])
    assert "expected_completion" not in keys


def test_the_graduation_answer_lands_in_the_finalized_record(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p6")
        draft = ConsultationDraft(agency_a.id, student.id, {})
        while (question := next_profile_question(draft)) is not None:
            value = {
                "academic_history": _undated_record(),
                "expected_completion": "2027-07-15",
            }.get(question.key, _ANSWERS.get(question.key))
            draft = draft.with_answer(question.key, value)
        snapshot, _run = finalize_consultation(membership=student, draft=draft)
    assert snapshot.academic_history[0].expected_completion.isoformat() == "2027-07-15"


def test_an_unreadable_reading_is_not_prefilled(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p7")
        reading = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=reading.id).update(
            record={**_RECORD, "country_code": "not a country"}
        )
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None
    assert "academic_history" not in draft.answers


def test_retyping_the_record_clears_its_highlights_but_keeps_the_reading(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p8")
        reading = _reading(agency_a, student, highlights=(_GRADE_UNSURE,))
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    draft = draft.with_answer("academic_history", [{**_RECORD, "grade": "90"}])
    assert draft.highlights == ()
    assert draft.reading_id == reading.id


def test_a_reading_with_malformed_highlights_is_not_prefilled(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p9")
        reading = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=reading.id).update(highlights=[{"kind": "spelling"}])
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None
    assert "academic_history" not in draft.answers


def test_an_older_unaccepted_reading_is_not_offered_once_the_newest_is_accepted(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p10")
        older = _reading(agency_a, student)
        newer = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=older.id).update(
            created_at=newer.created_at - timedelta(days=1)
        )
        TranscriptReading.objects.filter(id=newer.id).update(accepted=_RECORD)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id is None
    assert "academic_history" not in draft.answers


_ANSWERS = {
    "nationality": "AZ",
    "country_of_residence": "AZ",
    "date_of_birth": "2002-05-01",
    "target_field": "Chemistry, maybe synthesis",
    "allowed_countries": [],
    "excluded_countries": [],
    "intended_intake": "2027-09-01",
    "funding_dependency": "MANDATORY",
    "application_budget": {"amount": "300.00", "currency": "EUR"},
    "career_intent": "PHD",
    "acceptable_teaching_languages": ["English"],
    "language_evidence": [],
    "additional_notes": "",
}
