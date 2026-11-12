"""Transcript plan 3b: the transcript check -- doubtful cells asked one by one, answers kept beside
the reader's values, accepting it, and asking for review without ever being blocked."""

import pytest

from apps.audit.redaction import KEEP, REDACT
from apps.concierge.documents import register
from apps.documents.models import TranscriptReading
from apps.documents.transcript_check import (
    REASONS,
    accept,
    answer,
    check_items,
    effective_rows,
    request_review,
)
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _stored(agency, student, **fields):
    document = register(agency.id, student.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        return TranscriptReading.objects.create(
            student=student, document=document, **{"record": {}, **fields}
        )


def test_a_reading_keeps_the_students_answers_and_review_request(agency_a, membership_a):
    reading = _stored(agency_a, membership_a)
    answer = {"choice": "fix", "value": "A", "at": "2026-10-16T09:00:00+00:00"}
    with tenant_scope(agency_a.id):
        reading.answers = {"1:grade": answer}
        reading.review_reason = "my second semester is missing"
        reading.save()
        reading.refresh_from_db()
    assert reading.answers == {"1:grade": answer}
    assert reading.review_requested_at is None and reading.review_reason


def test_the_students_answers_and_reason_are_erased_with_them():
    fields = REDACT["documents.TranscriptReading"].fields
    assert {"answers", "review_reason"} <= set(fields)
    assert "review_requested_at" in KEEP["documents.TranscriptReading"]


def _row(index, title="", kind="course", credits="", grade=""):
    status = "COMPLETED" if kind == "course" else None
    return {"index": index, "kind": kind, "title": title, "credits": credits, "grade": grade,
            "status": status, "origin": None}


def _reading(rows=(), highlights=(), crops=None, record=None, key_numbers=None):
    return TranscriptReading(
        rows=list(rows), highlights=list(highlights), crops=crops or {},
        record={**_RECORD, **(record or {})},  # a complete record: no blank to type
        key_numbers=key_numbers or {},
    )


def test_a_low_confidence_row_asks_about_its_credits_and_grade():
    reading = _reading(rows=[_row(1, "Physics", credits="6", grade="B")],
                       highlights=[{"kind": "low_confidence", "scope": "row", "ref": "1"}],
                       crops={"1:credits": "k1", "1:grade": "k2"})
    items = check_items(reading)
    assert [(i.ref, i.reader_value, i.crop_ref) for i in items] == [
        ("1:credits", "6", "1:credits"), ("1:grade", "B", "1:grade")]
    assert items[0].reason == REASONS["low_confidence"]


def test_a_not_checked_total_is_never_asked():
    reading = _reading(
        highlights=[{"kind": "credit_total_not_checked", "scope": "transcript", "ref": ""}])
    assert check_items(reading) == ()


def test_a_row_without_a_crop_is_still_asked():
    reading = _reading(rows=[_row(1, "Physics")],
                       highlights=[{"kind": "grade_above_scale", "scope": "row", "ref": "1"}],
                       crops={})
    assert check_items(reading)[0].crop_ref is None


def test_no_highlights_means_no_items():
    assert check_items(_reading(highlights=[])) == ()


def test_a_semester_that_does_not_add_up_says_both_numbers():
    reading = _reading(
        rows=[_row(0, kind="semester_heading"), _row(1, "Physics", credits="6"),
              _row(2, "Algebra", credits="7.5"), _row(3, "Semester 1", "semester_total", "30")],
        highlights=[{"kind": "credit_total_mismatch", "scope": "semester", "ref": "3"}],
    )
    (item,) = check_items(reading)
    assert (item.ref, item.cell, item.reader_value) == ("semester:3", "credits", "30")
    assert item.reason == "The credits in this semester add up to 13.5; the transcript prints 30."


def test_a_field_item_reads_the_records_value_and_its_scale():
    reading = _reading(
        highlights=[{"kind": "grade_above_scale", "scope": "field", "ref": "overall_grade"}],
        record={"grade": "105", "grading_scale": "100"},
        key_numbers={"overall_grade": "105", "grading_scale": "100"},
    )
    (item,) = check_items(reading)
    assert (item.ref, item.cell, item.reader_value) == ("field:overall_grade", "field", "105")
    assert item.reason == "This grade is above the scale printed on the transcript (100)."


def test_two_doubts_on_one_cell_ask_once_in_reading_order():
    reading = _reading(
        rows=[_row(1, "Physics", credits="60", grade="B"), _row(2, "Algebra", credits="6")],
        highlights=[{"kind": "credit_out_of_range", "scope": "row", "ref": "2"},
                    {"kind": "credit_out_of_range", "scope": "row", "ref": "1"},
                    {"kind": "low_confidence", "scope": "row", "ref": "1"},
                    {"kind": "unsure", "scope": "field", "ref": "country"}],
        record={"country_code": "AZ"},
    )
    assert [(i.ref, i.reason) for i in check_items(reading)] == [
        ("field:country", REASONS["low_confidence"]),
        ("1:credits", REASONS["credit_out_of_range"]),
        ("1:grade", REASONS["low_confidence"]),
        ("2:credits", REASONS["credit_out_of_range"]),
    ]


def test_a_field_item_reads_the_stored_records_own_keys():
    reading = _reading(
        highlights=[{"kind": "unsure", "scope": "field", "ref": "credit_system"},
                    {"kind": "unsure", "scope": "field", "ref": "completed_on"}],
        record={"completed_on": "2026-06-30"}, key_numbers={"credit_unit": "ECTS"},
    )
    assert [i.reader_value for i in check_items(reading)] == ["ECTS", "2026-06-30"]


_RECORD = {
    "institution": "Baku State University", "country_code": "AZ", "qualification": "BSc",
    "field": "Physics", "grade": "88", "grading_scale": "100", "completed_on": None,
    "expected_completion": "2027-06-30", "courses": [],
}
_KEY_NUMBERS = {
    "overall_grade": "88", "grading_scale": "100", "total_credits": None,
    "total_credits_printed": False, "credit_unit": "ECTS", "graduation_date": "2027-06-30",
}


def _checked(agency, student, rows, highlights):
    return _stored(agency, student, record=_RECORD, key_numbers=_KEY_NUMBERS, rows=rows,
                   highlights=highlights)


def _low_confidence_grade(agency, student, row=1, grade="B"):
    return _checked(agency, student, [_row(row, "Physics", credits="6", grade=grade)],
                    [{"kind": "low_confidence", "scope": "row", "ref": str(row)}])


def _balanced_semester(agency, student, credits="6", printed_total="30"):
    rows = [_row(0, kind="semester_heading"), _row(1, "Physics", credits=credits, grade="B"),
            _row(2, "Thesis", credits="24", grade="A"),
            _row(3, "Semester 1", "semester_total", printed_total)]
    return _checked(agency, student, rows,
                    [{"kind": "low_confidence", "scope": "row", "ref": "1"}])


def test_a_fix_is_stored_beside_the_readers_value(agency_a, membership_a):
    reading = _low_confidence_grade(agency_a, membership_a, row=1, grade="B")
    with tenant_scope(agency_a.id):
        answer(reading, "1:grade", "fix", "A")
        reading.refresh_from_db()
    assert reading.rows[0]["grade"] == "B"
    assert effective_rows(reading)[0].grade == "A"
    assert reading.answers["1:grade"]["value"] == "A"
    assert reading.answers["1:grade"]["choice"] == "fix" and reading.answers["1:grade"]["at"]


def test_a_fix_that_breaks_the_printed_total_is_asked_again(agency_a, membership_a):
    reading = _balanced_semester(agency_a, membership_a, credits="6", printed_total="30")
    with tenant_scope(agency_a.id):
        open_items = answer(reading, "1:credits", "fix", "8")
    assert any(i.ref.startswith("semester:") for i in open_items)
    semester = next(i for i in open_items if i.ref == "semester:3")
    assert semester.reason == "The credits in this semester add up to 32; the transcript prints 30."


def test_a_total_once_matched_is_asked_again_after_a_fix_breaks_it(agency_a, membership_a):
    reading = _balanced_semester(agency_a, membership_a, credits="8", printed_total="30")
    reading.highlights.append({"kind": "credit_total_mismatch", "scope": "semester", "ref": "3"})
    with tenant_scope(agency_a.id):
        answer(reading, "semester:3", "matches")
        answer(reading, "1:credits", "fix", "6")  # now adds up: nothing to ask
        assert [i.ref for i in answer(reading, "1:grade", "matches")] == []
        open_items = answer(reading, "1:credits", "fix", "9")
    assert [i.ref for i in open_items] == ["semester:3"]


def test_answering_closes_the_item(agency_a, membership_a):
    reading = _low_confidence_grade(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        assert [i.ref for i in answer(reading, "1:grade", "matches")] == ["1:credits"]


def test_accept_refuses_while_an_item_is_unanswered(agency_a, membership_a):
    reading = _low_confidence_grade(agency_a, membership_a, row=1, grade="B")
    with tenant_scope(agency_a.id), pytest.raises(ValueError, match="unanswered"):
        accept(reading, student=membership_a)


def test_accept_keeps_the_students_fix_in_the_record(agency_a, membership_a):
    reading = _low_confidence_grade(agency_a, membership_a, row=1, grade="B")
    with tenant_scope(agency_a.id):
        answer(reading, "1:grade", "fix", "A")
        answer(reading, "1:credits", "matches")
        accept(reading, student=membership_a)
        reading.refresh_from_db()
    assert reading.accepted["courses"] == [
        {"title": "Physics", "ects": "6.00", "grade": "A", "in_progress": False}]
    assert reading.accepted["institution"] == "Baku State University"
    assert reading.review_requested_at is None


def test_cant_read_still_accepts_and_marks_for_review(agency_a, membership_a):
    reading = _low_confidence_grade(agency_a, membership_a, row=1, grade="B")
    with tenant_scope(agency_a.id):
        answer(reading, "1:grade", "cant_read")
        answer(reading, "1:credits", "cant_read")
        accept(reading, student=membership_a)
        reading.refresh_from_db()
    assert reading.accepted is not None and reading.review_requested_at is not None
    assert reading.accepted["courses"][0]["grade"] == "B"
    assert "Physics" in reading.review_reason


def test_somethings_wrong_never_blocks_accepting(agency_a, membership_a):
    reading = _checked(agency_a, membership_a, [], [])
    with tenant_scope(agency_a.id):
        request_review(reading, "my second semester is missing")
        accept(reading, student=membership_a)
        reading.refresh_from_db()
    assert reading.accepted is not None and reading.review_reason == "my second semester is missing"
    assert reading.review_requested_at is not None


def test_a_fixed_field_reaches_the_record(agency_a, membership_a):
    reading = _checked(agency_a, membership_a, [], [
        {"kind": "grade_above_scale", "scope": "field", "ref": "overall_grade"}])
    with tenant_scope(agency_a.id):
        answer(reading, "field:overall_grade", "fix", "91")
        accept(reading, student=membership_a)
    assert reading.accepted["grade"] == "91" and reading.record["grade"] == "88"


def test_a_ref_not_on_the_reading_is_refused():
    with pytest.raises(ValueError):
        answer(_reading(highlights=[]), "9:grade", "matches")


@pytest.mark.parametrize(("choice", "value"), [("fix", ""), ("fix", "   "), ("maybe", "A")])
def test_a_fix_needs_a_value_and_a_choice_must_be_known(agency_a, membership_a, choice, value):
    reading = _low_confidence_grade(agency_a, membership_a)
    with tenant_scope(agency_a.id), pytest.raises(ValueError):
        answer(reading, "1:grade", choice, value)


def test_a_fix_the_record_cannot_hold_is_refused(agency_a, membership_a):
    reading = _checked(agency_a, membership_a, [], [
        {"kind": "unsure", "scope": "field", "ref": "completed_on"}])
    with tenant_scope(agency_a.id), pytest.raises(ValueError):
        answer(reading, "field:completed_on", "fix", "last June")


def _finalized(agency, student, history):
    from apps.accounts.consultation import ConsultationDraft, finalize_consultation
    from tests.accounts.test_prefill import _ANSWERS

    draft = ConsultationDraft(agency.id, student.id, {**_ANSWERS, "academic_history": history})
    with tenant_scope(agency.id):
        finalize_consultation(membership=student, draft=draft)


def _profiles(agency, student):
    from apps.accounts.models import StudentProfileVersion

    with tenant_scope(agency.id):
        return list(StudentProfileVersion.objects.filter(student=student).order_by("version")
                    .values_list("snapshot", flat=True))


def _accept_with_fixed_grade(agency, student):
    reading = _low_confidence_grade(agency, student, row=1, grade="B")
    with tenant_scope(agency.id):
        answer(reading, "1:grade", "fix", "A")
        answer(reading, "1:credits", "matches")
        accept(reading, student=student)
    return reading


def test_accepting_after_the_questionnaire_writes_a_new_profile_version(agency_a, membership_a):
    _finalized(agency_a, membership_a, [_RECORD])
    _accept_with_fixed_grade(agency_a, membership_a)
    first, second = _profiles(agency_a, membership_a)
    assert first["academic_history"][0]["courses"] == []
    assert second["academic_history"][0]["courses"][0]["grade"] == "A"
    assert {k: v for k, v in second.items() if k != "academic_history"} == {
        k: v for k, v in first.items() if k != "academic_history"}


def test_accepting_before_the_questionnaire_writes_no_profile(agency_a, membership_a):
    _accept_with_fixed_grade(agency_a, membership_a)
    assert _profiles(agency_a, membership_a) == []


def test_a_profile_holding_another_degree_is_left_alone(agency_a, membership_a):
    _finalized(agency_a, membership_a, [{**_RECORD, "qualification": "MSc"}])
    _accept_with_fixed_grade(agency_a, membership_a)
    assert len(_profiles(agency_a, membership_a)) == 1


def test_the_students_graduation_answer_survives_an_undated_reading(agency_a, membership_a):
    _finalized(agency_a, membership_a, [_RECORD])
    reading = _checked(agency_a, membership_a, [_row(1, "Physics", credits="6", grade="B")], [])
    reading.record = {**_RECORD, "expected_completion": None}
    with tenant_scope(agency_a.id):
        reading.save(update_fields=["record"])
        accept(reading, student=membership_a)
    first, second = _profiles(agency_a, membership_a)
    assert second["academic_history"][0]["courses"][0]["title"] == "Physics"
    assert second["academic_history"][0]["expected_completion"] == "2027-06-30"


def _cv_degree(agency, student, institution, degree, end=None, confirmed=True):
    from django.utils import timezone

    from apps.documents.models import VerifiedFact

    with tenant_scope(agency.id):
        return VerifiedFact.objects.create(
            student=student, category="EDUCATION", source_tier="STUDENT_STATEMENT",
            payload={"institution_original": institution, "degree_as_awarded": degree,
                     "end_date": end, "city": "Baku"},
            source_ref="upload:cv", confirmed_by=student if confirmed else None,
            confirmed_at=timezone.now() if confirmed else None, created_by=student)


def _degrees(agency, student):
    from apps.documents.verification import unsuperseded_facts

    with tenant_scope(agency.id):
        return list(unsuperseded_facts(student).filter(category="EDUCATION"))


def _clean(agency, student):
    """A reading with nothing doubtful: Physics 6 credits, grade B."""
    return _checked(agency, student, [_row(1, "Physics", credits="6", grade="B")], [])


def test_an_unsure_degree_match_is_asked_in_the_check(agency_a, membership_a):
    _cv_degree(agency_a, membership_a, "Bakı Dövlət Universiteti", "Bakalavr", "2027-06-30")
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        (item,) = check_items(reading)
        assert item.ref == "degree:same"
        assert item.row_title == "Bakalavr, Bakı Dövlət Universiteti, 2027"
        with pytest.raises(ValueError, match="unanswered"):
            accept(reading, student=membership_a)
        with pytest.raises(ValueError):
            answer(reading, "degree:same", "matches")


def test_same_degree_puts_the_courses_on_the_cvs_degree(agency_a, membership_a):
    cv = _cv_degree(agency_a, membership_a, "Bakı Dövlət Universiteti", "Bakalavr",
                    "2027-06-30")
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        assert answer(reading, "degree:same", "same") == ()
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert degree.supersedes_id == cv.id and degree.confirmed_by_id == membership_a.id
    assert degree.source_ref == f"transcript:{reading.id}"
    assert degree.payload["institution_original"] == "Bakı Dövlət Universiteti"
    assert degree.payload["degree_as_awarded"] == "Bakalavr" and degree.payload["city"] == "Baku"
    assert degree.payload["aliases"] == ["Baku State University", "BSc"]
    assert degree.payload["courses"] == [
        {"title": "Physics", "ects": "6.00", "grade": "B", "in_progress": False}]
    assert degree.payload["courses_unconfirmed"] == []


def test_different_degree_adds_one_from_the_transcript(agency_a, membership_a):
    _cv_degree(agency_a, membership_a, "Bakı Dövlət Universiteti", "Bakalavr", "2027-06-30")
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        answer(reading, "degree:same", "different")
        accept(reading, student=membership_a)
        accept(reading, student=membership_a)  # twice: still no third
    cv, new = _degrees(agency_a, membership_a)
    assert new.payload["institution_original"] == "Baku State University"
    assert new.payload["degree_as_awarded"] == "BSc" and new.payload["aliases"] == []
    assert new.payload["end_date"] == "2027-06-30" and new.payload["country"] == "AZ"
    assert new.confirmed_by_id == membership_a.id


def test_a_sure_match_is_not_asked(agency_a, membership_a):
    cv = _cv_degree(agency_a, membership_a, "Baku State University", "BSc Chemistry",
                    "2027-06-30")
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        assert check_items(reading) == ()
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert degree.supersedes_id == cv.id and degree.payload["courses"]


def test_the_first_degree_comes_from_the_transcript(agency_a, membership_a):
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert degree.payload["institution_original"] == "Baku State University"
    assert degree.payload["grade_native"] == "88" and degree.payload["grade_scale"] == "100"


def test_an_unconfirmed_cv_claim_is_not_confirmed_by_the_transcript(agency_a, membership_a):
    _cv_degree(agency_a, membership_a, "Baku State University", "BSc", "2027-06-30",
               confirmed=False)
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert degree.payload["courses"] and degree.confirmed_at is None


def test_a_course_the_student_could_not_read_is_kept_apart_and_never_given_to_a_letter(
    agency_a, membership_a
):
    from apps.documents import letters, storyline

    reading = _low_confidence_grade(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        answer(reading, "1:grade", "cant_read")
        answer(reading, "1:credits", "matches")
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert degree.payload["courses"] == []
    assert [c["title"] for c in degree.payload["courses_unconfirmed"]] == ["Physics"]
    for payload in (letters._facts_payload({degree.id: degree}),
                    storyline._facts_payload({degree.id: degree})):
        assert "courses_unconfirmed" not in payload and "Physics" not in payload


def test_the_cv_prompt_waits_for_the_coursework_design(agency_a, membership_a):
    from apps.documents import generation

    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    prompt = generation._facts_payload([degree])
    assert "Physics" not in prompt and "courses" not in prompt
    assert "Baku State University" in prompt


def test_a_blank_record_field_is_asked_to_be_typed(agency_a, membership_a):
    # Final review finding 1: a reading with no field of study could never be accepted.
    reading = _stored(agency_a, membership_a, record={**_RECORD, "field": ""},
                      key_numbers=_KEY_NUMBERS, rows=[], highlights=[])
    with tenant_scope(agency_a.id):
        (item,) = check_items(reading)
        assert item.ref == "field:field" and item.reader_value == ""
        for choice in ("matches", "cant_read"):
            with pytest.raises(ValueError):
                answer(reading, "field:field", choice)
        answer(reading, "field:field", "fix", "Physics")
        accept(reading, student=membership_a)
    assert reading.accepted["field"] == "Physics" and reading.record["field"] == ""


def test_a_field_the_student_could_not_read_is_not_a_confirmed_fact(agency_a, membership_a):
    # Final review finding 2.
    reading = _stored(agency_a, membership_a, record={**_RECORD, "grade": "105"},
                      key_numbers={**_KEY_NUMBERS, "overall_grade": "105"}, rows=[],
                      highlights=[{"kind": "grade_above_scale", "scope": "field",
                                   "ref": "overall_grade"}])
    with tenant_scope(agency_a.id):
        answer(reading, "field:overall_grade", "cant_read")
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert "grade_native" not in degree.payload
    assert reading.review_requested_at is not None


def test_a_fixed_institution_name_still_updates_the_profile(agency_a, membership_a):
    # Final review finding 4: "Bakу" has a Cyrillic у.
    misread = {**_RECORD, "institution": "Bakу State University"}
    _finalized(agency_a, membership_a, [misread])
    reading = _stored(agency_a, membership_a, record=misread, key_numbers=_KEY_NUMBERS,
                      rows=[], highlights=[{"kind": "mixed_script", "scope": "field",
                                            "ref": "institution"}])
    with tenant_scope(agency_a.id):
        answer(reading, "field:institution", "fix", "Baku State University")
        accept(reading, student=membership_a)
    first, second = _profiles(agency_a, membership_a)
    assert second["academic_history"][0]["institution"] == "Baku State University"


def test_a_country_the_record_cannot_hold_is_refused_when_typed(agency_a, membership_a):
    # Spec audit P3: "UK" passed the two-letter pattern, then made accepting impossible.
    reading = _stored(agency_a, membership_a, record={**_RECORD, "country_code": ""},
                      key_numbers=_KEY_NUMBERS, rows=[], highlights=[])
    with tenant_scope(agency_a.id), pytest.raises(ValueError):
        answer(reading, "field:country", "fix", "UK")


def test_the_questionnaire_finished_after_the_check_keeps_the_students_fix(agency_a,
                                                                          membership_a):
    # Spec audit P1: the draft was pre-filled from the reader's record before the check.
    from apps.accounts.consultation import (
        ConsultationDraft,
        finalize_consultation,
        prefill_from_latest_reading,
    )
    from tests.accounts.test_prefill import _ANSWERS

    reading = _low_confidence_grade(agency_a, membership_a, row=1, grade="B")
    reading.record = {**_RECORD, "courses": [
        {"title": "Physics", "ects": "6.00", "grade": "B", "in_progress": False}]}
    with tenant_scope(agency_a.id):
        reading.save(update_fields=["record"])
        draft = prefill_from_latest_reading(
            ConsultationDraft(agency_a.id, membership_a.id, dict(_ANSWERS)),
            membership=membership_a)
        assert draft.reading_id == reading.id
        answer(reading, "1:grade", "fix", "A")
        answer(reading, "1:credits", "matches")
        accept(reading, student=membership_a)
        finalize_consultation(membership=membership_a, draft=draft)
    (profile,) = _profiles(agency_a, membership_a)
    assert profile["academic_history"][0]["courses"][0]["grade"] == "A"


def test_a_degree_typed_in_other_words_is_asked_and_then_followed(agency_a, membership_a):
    # Spec audit P2: the profile says "Baku State University, Bachelor"; the transcript is
    # Azerbaijani. The check asks once, and "Same degree" updates the profile.
    _finalized(agency_a, membership_a, [{**_RECORD, "qualification": "Bachelor"}])
    reading = _clean(agency_a, membership_a)
    reading.record = {**_RECORD, "institution": "Bakı Dövlət Universiteti",
                      "qualification": "Bakalavr",
                      "courses": [{"title": "Physics", "ects": "6.00", "grade": "B",
                                   "in_progress": False}]}
    with tenant_scope(agency_a.id):
        reading.save(update_fields=["record"])
        (item,) = check_items(reading)
        assert item.ref == "degree:same" and "in your profile" in item.reason
        answer(reading, "degree:same", "same")
        accept(reading, student=membership_a)
    first, second = _profiles(agency_a, membership_a)
    assert second["academic_history"][0]["courses"][0]["title"] == "Physics"


def test_two_courses_with_one_title_keep_their_own_can_t_read(agency_a, membership_a):
    reading = _checked(agency_a, membership_a,
                       [_row(1, "Seminar", credits="2", grade="A"),
                        _row(2, "Seminar", credits="2", grade="B")],
                       [{"kind": "low_confidence", "scope": "row", "ref": "2"}])
    with tenant_scope(agency_a.id):
        answer(reading, "2:grade", "cant_read")
        answer(reading, "2:credits", "matches")
        accept(reading, student=membership_a)
    (degree,) = _degrees(agency_a, membership_a)
    assert [c["grade"] for c in degree.payload["courses"]] == ["A"]
    assert [c["grade"] for c in degree.payload["courses_unconfirmed"]] == ["B"]


def test_a_second_review_request_keeps_the_first(agency_a, membership_a):
    reading = _clean(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        request_review(reading, "semester 2 is missing")
        request_review(reading, "and my thesis grade")
    assert reading.review_reason == "semester 2 is missing\nand my thesis grade"


def test_a_fix_no_check_reads_re_runs_nothing(agency_a, membership_a):
    # Walked 2026-10-20: choosing the country re-ran the credit checks and a total card
    # appeared. A country, a date or a credit system decides no check.
    reading = _stored(agency_a, membership_a, record={**_RECORD, "country_code": ""},
                      key_numbers={**_KEY_NUMBERS, "total_credits": "240",
                                   "total_credits_printed": True},
                      rows=[_row(1, "Physics", credits="6", grade="B")], highlights=[])
    with tenant_scope(agency_a.id):
        assert [i.ref for i in check_items(reading)] == ["field:country"]
        assert answer(reading, "field:country", "fix", "Azerbaijan") == ()
        assert reading.answers["field:country"]["value"] == "AZ"


def test_accepting_mid_semester_transcript_with_higher_gpa_enqueues_rebuild_pack(
    agency_a, membership_a, monkeypatch
):
    from apps.accounts.models import StudentProfileVersion
    from apps.funding.models import RecommendationRun

    enqueued = []
    monkeypatch.setattr(
        "apps.documents.profile_bridge.enqueue_research_message",
        lambda msg: enqueued.append(msg) or True,
    )
    _finalized(agency_a, membership_a, [{**_RECORD, "grade": "85"}])
    with tenant_scope(agency_a.id):
        v1 = StudentProfileVersion.objects.filter(student=membership_a).order_by("-version").first()
        run = RecommendationRun.objects.create(
            profile_version=v1, state=RecommendationRun.State.PUBLISHED
        )
    reading = _clean(agency_a, membership_a)
    reading.record = {
        **_RECORD,
        "grade": "92",
        "courses": [
            {"title": "Organic Chemistry", "ects": "6.00", "grade": "A", "in_progress": False}
        ],
    }
    with tenant_scope(agency_a.id):
        reading.save(update_fields=["record"])
        accept(reading, student=membership_a)
    assert len(enqueued) == 1
    assert (enqueued[0].kind, enqueued[0].run_id) == ("rebuild_pack", run.id)
