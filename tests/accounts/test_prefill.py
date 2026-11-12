
from datetime import timedelta
from uuid import uuid4

import pytest

from apps.accounts.consultation import (
    ConsultationDraft,
    _canonical_answer,
    finalize_consultation,
    late_reading,
    next_profile_question,
    prefill_from_latest_reading,
    use_reading,
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


def test_finalizing_leaves_the_reading_for_the_check_to_accept(agency_a, django_user_model):
    # Plan 3b Task 5: the transcript check accepts a reading, never the questionnaire.
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
    assert reading.accepted is None
    assert draft.reading_id == reading.id


def test_an_accepted_reading_prefills_what_the_student_checked(agency_a, django_user_model):
    checked = {**_RECORD, "grade": "90"}
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p4")
        reading = _reading(agency_a, student, highlights=(_GRADE_UNSURE,))
        TranscriptReading.objects.filter(id=reading.id).update(accepted=checked)
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.reading_id == reading.id
    assert draft.answer("academic_history") == _canonical_answer("academic_history", [checked])
    assert draft.highlights == ()  # the check settled every doubt


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
    assert draft.reading_id == newer.id  # the accepted newest, never the older one


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
    "budget_stretch": None,
    "career_intent": "PHD",
    "acceptable_teaching_languages": ["English"],
    "language_evidence": [],
    "additional_notes": "",
}


def test_finalize_calls_the_search_hook_after_commit_with_the_previous_snapshot(
    agency_a, django_user_model, monkeypatch, django_capture_on_commit_callbacks, settings
):
    import apps.research.tap as tap_module

    settings.TAP_AUTOMATIC = True
    calls = []
    monkeypatch.setattr(
        tap_module, "on_profile_saved", lambda previous, current, student: calls.append(previous)
    )
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p4")
        draft = ConsultationDraft(agency_a.id, student.id, {})
        while (question := next_profile_question(draft)) is not None:
            draft = draft.with_answer(question.key, _ANSWERS.get(question.key, [_RECORD]))
        with django_capture_on_commit_callbacks(execute=True):
            finalize_consultation(membership=student, draft=draft)
            assert calls == []  # not before commit
        with django_capture_on_commit_callbacks(execute=True):
            finalize_consultation(membership=student, draft=draft)
    assert calls[0] is None and calls[1] is not None


def test_an_unreadable_previous_snapshot_neither_blocks_the_intake_nor_starts_a_first_search(
    agency_a, django_user_model, monkeypatch, django_capture_on_commit_callbacks, settings
):
    import apps.research.tap as tap_module
    from apps.accounts.models import StudentProfileVersion

    settings.TAP_AUTOMATIC = True
    searched = []
    monkeypatch.setattr(tap_module, "request_tap", lambda *a, **k: searched.append(k))
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "p5")
        draft = ConsultationDraft(agency_a.id, student.id, {})
        while (question := next_profile_question(draft)) is not None:
            draft = draft.with_answer(question.key, _ANSWERS.get(question.key, [_RECORD]))
        with django_capture_on_commit_callbacks(execute=True):
            finalize_consultation(membership=student, draft=draft)
        searched.clear()
        # Stored versions are immutable, so "a row that no longer validates" is
        # simulated at the tap side's validation.
        class _Stale:
            @staticmethod
            def model_validate(_value):
                raise ValueError("schema moved on")

        monkeypatch.setattr(tap_module, "StudentProfileSnapshot", _Stale)
        with django_capture_on_commit_callbacks(execute=True):
            finalize_consultation(membership=student, draft=draft)
        assert StudentProfileVersion.objects.filter(student=student).count() == 2
    assert searched == []


# --- Onboarding plan, task 3: a reading that finishes after the student typed ---

_TYPED = [{**_RECORD, "institution": "BSU", "courses": []}]


def _typed_draft(agency, student):
    return ConsultationDraft(
        agency.id, student.id, {"target_field": "Chemistry", "academic_history": _TYPED}
    )


def test_a_reading_that_finishes_after_typing_is_offered(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "late1")
        draft = _typed_draft(agency_a, student)
        reading = _reading(agency_a, student, highlights=(_GRADE_UNSURE,))
        assert late_reading(draft, membership=student) == reading


def test_using_a_late_reading_replaces_only_the_degree(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "late2")
        draft = _typed_draft(agency_a, student)
        reading = _reading(agency_a, student, highlights=(_GRADE_UNSURE,))
        used = use_reading(draft, reading)
    assert used.answers["academic_history"] == _canonical_answer("academic_history", [_RECORD])
    assert used.answers["target_field"] == "Chemistry"
    assert used.reading_id == reading.id
    assert used.highlights == (_GRADE_UNSURE,)


def test_a_prefilled_draft_is_not_offered_its_own_reading_again(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "late3")
        _reading(agency_a, student)
        prefilled = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
        assert late_reading(prefilled, membership=student) is None


def test_an_accepted_reading_is_never_offered_late(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "late4")
        reading = _reading(agency_a, student)
        TranscriptReading.objects.filter(id=reading.id).update(accepted=_RECORD)
        assert late_reading(_typed_draft(agency_a, student), membership=student) is None


def test_confirmed_verified_facts_prefill_identity_language_and_experience(
    agency_a, django_user_model
):
    from django.utils import timezone

    from apps.documents.models import VerifiedFact

    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v6_prefill")
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.IDENTITY,
            payload={"citizenship": "Azerbaijan", "date_of_birth": "2001-04-15"},
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:11111111-1111-1111-1111-111111111111",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "7.5",
                "cefr_level": "C1",
                "test_date": "2026-03-10",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:22222222-2222-2222-2222-222222222222",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_original": "ADA University",
                "country": "Azerbaijan",
                "degree_as_awarded": "BSc",
                "field": "Computer Science",
                "grade_native": "3.7",
                "grade_scale": "4.0",
                "end_date": "2025-06-15",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:33333333-3333-3333-3333-333333333333",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EXPERIENCE,
            payload={
                "title": "Software Engineer",
                "employer": "PASHA Bank",
                "start_date": "2024-01-01",
                "end_date": "2026-01-01",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:1",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
        assert draft.answer("nationality") == "AZ"
        assert draft.answer("date_of_birth") == "2001-04-15"
        assert draft.answer("acceptable_teaching_languages") == ["English"]
        assert draft.answer("language_evidence") == [
            {
                "language": "English",
                "level": "C1",
                "evidence_type": "TEST",
                "available_by": "2026-03-10",
            }
        ]
        assert draft.answer("academic_history")[0]["institution"] == "ADA University"

        while (question := next_profile_question(draft)) is not None:
            draft = draft.with_answer(question.key, _ANSWERS[question.key])
        snapshot, _run = finalize_consultation(membership=student, draft=draft)

    assert snapshot.experience is not None
    assert len(snapshot.experience) == 1
    assert snapshot.experience[0].kind == "WORK"
    assert snapshot.experience[0].months == 24


def test_additional_notes_parses_explicit_work_and_zero_experience(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "notes_exp")
        draft = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "academic_history": [_RECORD],
                "additional_notes": (
                    "I have 3 years of full-time work experience and "
                    "6 months of research experience."
                ),
            },
        )
        snapshot, _ = finalize_consultation(membership=student, draft=draft)
        assert snapshot.experience is not None
        assert [(r.kind, r.months) for r in snapshot.experience] == [
            ("WORK", 36),
            ("RESEARCH", 6),
        ]

        draft_zero = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "academic_history": [_RECORD],
                "additional_notes": "Fresh graduate, no work experience yet.",
            },
        )
        snapshot_zero, _ = finalize_consultation(membership=student, draft=draft_zero)
        assert snapshot_zero.experience == ()


def test_negated_or_requirement_notes_do_not_extract_false_work_experience(
    agency_a, django_user_model
):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "notes_neg")
        for note in (
            "I do not have 2 years of work experience.",
            "Please exclude programmes requiring 2 years of work experience.",
        ):
            draft = ConsultationDraft(
                agency_a.id,
                student.id,
                {**_ANSWERS, "academic_history": [_RECORD], "additional_notes": note},
            )
            snapshot, _ = finalize_consultation(membership=student, draft=draft)
            assert snapshot.experience is None

        draft_no_any = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "academic_history": [_RECORD],
                "additional_notes": "I do not have any work experience.",
            },
        )
        snapshot_no_any, _ = finalize_consultation(membership=student, draft=draft_no_any)
        assert snapshot_no_any.experience == ()


def test_conditional_answers_are_cleaned_up_on_edit_and_use_reading(
    agency_a, django_user_model
):
    draft = ConsultationDraft(uuid4(), uuid4(), {})
    draft = draft.with_answer("academic_history", _undated_record())
    draft = draft.with_answer("expected_completion", "2027-06-30")
    assert "expected_completion" in draft.answers

    # Updating academic_history with a dated record pops the orphaned expected_completion
    draft = draft.with_answer("academic_history", [_RECORD])
    assert "expected_completion" not in draft.answers

    # Switching between two ambiguous target_field values clears stale research_interests
    draft = draft.with_answer("target_field", "Engineering")
    draft = draft.with_answer("research_interests", ["Civil Engineering"])
    draft = draft.with_answer("target_field", "Data Science")
    assert "research_interests" not in draft.answers

    # Removing a teaching language prunes its language_evidence entry
    draft = draft.with_answer("acceptable_teaching_languages", ["English", "German"])
    draft = draft.with_answer(
        "language_evidence",
        [
            {
                "language": "English",
                "level": "C1",
                "evidence_type": "TEST",
                "available_by": "2026-01-10",
            },
            {
                "language": "German",
                "level": "B2",
                "evidence_type": "TEST",
                "available_by": "2026-01-10",
            },
        ],
    )
    draft = draft.with_answer("acceptable_teaching_languages", ["English"])
    assert draft.answer("language_evidence") == [
        {
            "language": "English",
            "level": "C1",
            "evidence_type": "TEST",
            "available_by": "2026-01-10",
        }
    ]

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "cond_reading")
        reading = _reading(agency_a, student)
        undated_draft = ConsultationDraft(
            agency_a.id,
            student.id,
            {"academic_history": _undated_record(), "expected_completion": "2027-09-01"},
        )
        used = use_reading(undated_draft, reading)
    assert "expected_completion" not in used.answers


def test_prefill_preserves_stronger_language_level_and_allows_ungraded_diploma(
    agency_a, django_user_model
):
    from django.utils import timezone

    from apps.documents.models import VerifiedFact

    now = timezone.now()
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "v6_nondowngrade")
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "test_name": "IELTS Academic",
                "language": "English",
                "test_score": "7.5",
                "cefr_level": "C1",
                "test_date": "2026-02-01",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.LANGUAGE,
            payload={
                "language": "English",
                "cefr_level": "B2",
                "evidence_type": "ATTESTED",
            },
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="cv:lang1",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        VerifiedFact.objects.create(
            student=student,
            category=VerifiedFact.Category.EDUCATION,
            payload={
                "institution_original": "ADA University",
                "country": "Azerbaijan",
                "degree_as_awarded": "BSc",
                "field": "not stated",
                "grade_native": "not stated",
                "grade_scale": "not stated",
                "end_date": "2025-06-15",
            },
            source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
            source_ref="document:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            confirmed_by=student,
            confirmed_at=now,
            created_by=student,
        )
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
    assert draft.answer("language_evidence") == [
        {
            "language": "English",
            "level": "C1",
            "evidence_type": "TEST",
            "available_by": "2026-02-01",
        }
    ]
    assert draft.answer("academic_history")[0]["institution"] == "ADA University"
    assert draft.answer("academic_history")[0]["grade"] == "not stated"


def test_mid_onboarding_transcript_check_refreshes_prefilled_draft_before_review(
    agency_a, django_user_model
):
    checked = {**_RECORD, "grade": "93"}
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "mid_check")
        reading = _reading(agency_a, student, highlights=(_GRADE_UNSURE,))
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, student.id, {}), membership=student
        )
        assert draft.highlights == (_GRADE_UNSURE,)
        assert draft.answer("academic_history")[0]["grade"] == "88"

        TranscriptReading.objects.filter(id=reading.id).update(accepted=checked)
        refreshed = prefill_from_latest_reading(draft, membership=student)
    assert refreshed.highlights == ()
    assert refreshed.answer("academic_history")[0]["grade"] == "93"


def test_onboarding_captures_unconstrained_self_funded_and_priority_notes(
    agency_a, django_user_model
):
    from apps.accounts.forms import ConsultationQuestionForm, question_field

    # 1. Blank or 0 self_funding_capacity compresses to None on the form
    form_blank = ConsultationQuestionForm(
        key="self_funding_capacity",
        field=question_field("self_funding_capacity"),
        data={"value_0": "", "value_1": "EUR"},
    )
    assert form_blank.is_valid(), form_blank.errors
    assert form_blank.cleaned_data["value"] is None

    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model, "priority_notes")

        # 2. OPTIONAL funding + blank self_funding_capacity + "don't care about funding options"
        draft_self_funded = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "funding_dependency": "OPTIONAL",
                "self_funding_capacity": None,
                "academic_history": [_RECORD],
                "additional_notes": (
                    "I only want top universities and I don't care about any funding options. "
                    "Strictly 1-year master's only."
                ),
            },
        )
        snap_self, _ = finalize_consultation(membership=student, draft=draft_self_funded)
        assert snap_self.funding_dependency == "OPTIONAL"
        assert snap_self.self_funding_capacity is None
        assert snap_self.duration_preference == "ONE_YEAR"
        assert snap_self.duration_flexibility == "NON_NEGOTIABLE"
        assert snap_self.longer_program_justifications == ()
        assert any(
            c.kind == "OTHER" and c.value == "TOP_UNIVERSITIES_ONLY"
            for c in snap_self.non_negotiables
        )
        assert any(
            c.kind == "OTHER" and c.value == "NO_FUNDING_NEEDED"
            for c in snap_self.negotiable_preferences
        )

        # 3. MANDATORY funding + "prestigious scholarships and top universities" -> BALANCED
        draft_prestigious = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "funding_dependency": "MANDATORY",
                "academic_history": [_RECORD],
                "additional_notes": (
                    "Looking for prestigious scholarships and top universities. "
                    "Prefer a 1-year program unless there is research or funding, "
                    "and no return bond."
                ),
            },
        )
        snap_prest, _ = finalize_consultation(membership=student, draft=draft_prestigious)
        assert snap_prest.strategy == "BALANCED"
        assert snap_prest.duration_preference == "ONE_YEAR"
        assert snap_prest.duration_flexibility == "WEIGHTED"
        assert set(snap_prest.longer_program_justifications) == {"FUNDING", "RESEARCH"}
        assert any(
            c.kind == "OTHER" and c.value == "TOP_UNIVERSITIES_ONLY"
            for c in snap_prest.negotiable_preferences
        )
        assert any(
            c.kind == "OTHER" and c.value == "NO_RETURN_BOND"
            for c in snap_prest.negotiable_preferences
        )

        # 4. OB8: Re-finalizing preserves mobility_priorities & weights from previous version,
        # OB9: Ticking "fully self-funded" overrides MANDATORY to OPTIONAL,
        # OB10: Negated strict modifier ("not strictly 1-year") stays WEIGHTED.
        from decimal import Decimal

        from apps.accounts.profile_versions import create_profile_version
        from apps.accounts.schemas import StudentProfileSnapshot

        seeded_with_mobility = snap_prest.model_copy(
            update={
                "mobility_priorities": ("POST_STUDY_WORK",),
                "weights": {
                    **snap_prest.weights,
                    "ACADEMIC_FIT": Decimal("0.25"),
                    "AFFORDABILITY": Decimal("0.15"),
                },
            }
        )
        create_profile_version(student=student, snapshot=seeded_with_mobility)

        draft_override = ConsultationDraft(
            agency_a.id,
            student.id,
            {
                **_ANSWERS,
                "funding_dependency": "MANDATORY",
                "academic_history": [_RECORD],
                "additional_notes": (
                    "I don't care about any funding options (fully self-funded). "
                    "Prefer a 1-year master's, not strictly 1-year."
                ),
            },
        )
        snap_override, _ = finalize_consultation(membership=student, draft=draft_override)
        assert snap_override.funding_dependency == "OPTIONAL"
        assert snap_override.self_funding_capacity is None
        assert snap_override.duration_preference == "ONE_YEAR"
        assert snap_override.duration_flexibility == "WEIGHTED"
        assert snap_override.mobility_priorities == ("POST_STUDY_WORK",)
        assert snap_override.weights["ACADEMIC_FIT"] == Decimal("0.25")
        assert isinstance(snap_override, StudentProfileSnapshot)

