import pytest
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.fact_writer import (
    adopt_document_value,
    correct_fact,
    dismiss_document_value,
    write_facts,
)
from apps.documents.id_reading import ReadValue
from apps.documents.models import DocumentReading, VerifiedFact
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _v(key, value, proven=True, why="readers_agree"):
    return ReadValue(key, value, value, proven, why)


def _read(agency, student, kind, values, *, document=None, version="doc-1"):
    document = document or register(agency.id, student.id, kind=kind)
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        reading = DocumentReading.objects.create(
            student=student, document=document, kind=kind, reader_version=version,
            state="READ", values=[v.as_dict() for v in values])
        write_facts(reading)
        reading.refresh_from_db()
    return reading


def _cv_degree(student, **payload):
    return VerifiedFact.objects.create(
        student=student, category="EDUCATION", payload=payload, source_tier="STUDENT_STATEMENT",
        source_ref="upload:cv", confirmed_by=student, confirmed_at=timezone.now(),
        created_by=student)


def _tips(student, category):
    return list(VerifiedFact.objects.filter(student=student, category=category,
                                            superseded_by__isnull=True))


def _entry(reading, key):
    return next(v for v in reading.values if v["key"] == key)


CERT = [_v("language.test_name", "IELTS"), _v("language.language", "English"),
        _v("language.test_date", "2025-11-08"), _v("language.test_score", "6.5"),
        _v("language.score_writing", "6.0", False, "low_confidence")]


def test_a_certificate_is_one_row_and_its_doubtful_key_waits_on_the_reading(agency_a,
                                                                            membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "LANGUAGE")
        assert row.confirmed_at and row.payload["test_score"] == "6.5"
        assert "score_writing" not in row.payload
    waiting = [v for v in reading.values if not v["proven"]]
    assert waiting[0]["target"] == str(row.id)


def test_a_passport_read_writes_no_language_or_education_row(agency_a, membership_a):
    """write_facts runs every writer on every reading: an empty group writes nothing."""
    _read(agency_a, membership_a, "PASSPORT", [_v("identity.date_of_birth", "1998-03-14",
                                                  why="check_digit")], version="id-1")
    with tenant_scope(agency_a.id):
        assert _tips(membership_a, "LANGUAGE") == [] and _tips(membership_a, "EDUCATION") == []


def test_adopting_the_doubtful_key_changes_that_row(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        new = adopt_document_value(student=membership_a, reading_id=reading.id,
                                   key="language.score_writing")
        (row,) = _tips(membership_a, "LANGUAGE")
        assert row.id == new.id and row.payload["score_writing"] == "6.0"
        assert row.source_tier == "STUDENT_STATEMENT" and row.supersedes_id
        reading.refresh_from_db()
    adopted = _entry(reading, "language.score_writing")
    # A tap is the student's choice, never a proof (plan 1: reading values carry the truth).
    assert (adopted["why"], adopted["proven"]) == ("adopted", False)


def test_a_re_read_never_carries_back_a_key_the_student_adopted(agency_a, membership_a):
    first = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        adopt_document_value(student=membership_a, reading_id=first.id,
                             key="language.score_writing")
    again = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
                  [*CERT[:4], _v("language.score_writing", "5.5")],
                  document=first.document, version="doc-2")
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "LANGUAGE")
        assert row.payload["score_writing"] == "6.0" and row.payload["test_score"] == "6.5"
    differs = _entry(again, "language.score_writing")
    assert (differs["proven"], differs["why"], differs["target"]) == (
        False, "student_entry_differs", str(row.id))


def test_a_diploma_fills_only_what_the_cv_degree_lacks(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="Bakı Dövlət Universiteti",
                            degree_as_awarded="Bachelor", end_date="2023-06-30")
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "BAKI DÖVLƏT UNİVERSİTETİ"),
        _v("education.degree_as_awarded", "Bakalavr"),
        _v("education.end_date", "2023-06-30"),
        _v("education.diploma_number", "AB 123456"),
    ])
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")  # one degree, never two
        assert row.supersedes_id == degree.id
        assert row.payload["degree_as_awarded"] == "Bachelor"  # the CV's value stands
        assert row.payload["diploma_number"] == "AB 123456"  # the gap is filled
    differs = _entry(reading, "education.degree_as_awarded")
    assert (differs["proven"], differs["why"], differs["target"]) == (False, "document_differs",
                                                                      str(row.id))


def test_two_cyrillic_institutions_are_not_one_degree(agency_a, membership_a):
    """mrz.fold_tokens, as built, drops every non-Latin letter: two Cyrillic names
    both fold to nothing, which must never read as "the same institution"."""
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="Московский университет",
                   end_date="2023-06-30")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "Бакинский университет"),
        _v("education.end_date", "2023-06-30")])
    with tenant_scope(agency_a.id):
        assert len(_tips(membership_a, "EDUCATION")) == 2


def test_keeping_mine_leaves_the_row_alone(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="BDU", degree_as_awarded="Bachelor",
                   end_date="2023-06-30")
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "BDU"), _v("education.end_date", "2023-06-30"),
        _v("education.degree_as_awarded", "Bakalavr")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        dismiss_document_value(student=membership_a, reading_id=reading.id,
                               key="education.degree_as_awarded")
        reading.refresh_from_db()
        assert _tips(membership_a, "EDUCATION")[0].payload["degree_as_awarded"] == "Bachelor"
    assert _entry(reading, "education.degree_as_awarded")["why"] == "kept"


def test_a_diploma_with_no_matching_degree_is_a_new_degree(agency_a, membership_a):
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")])
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        assert row.confirmed_at and row.source_ref.startswith("document:")


def test_a_document_with_no_proven_anchor_is_one_row_the_student_confirms_whole(
        agency_a, membership_a):
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University", False, "readers_disagree"),
        _v("education.end_date", "2024-06-15")])
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        assert row.confirmed_at is None
        assert row.payload == {"institution_original": "ADA University", "end_date": "2024-06-15"}
    # Plan 1: reading.values carry the final proven/why; nothing of it is confirmed.
    assert not any(v["proven"] for v in reading.values)


def test_a_proof_after_a_whole_row_writes_its_own_confirmed_row(agency_a, membership_a):
    first = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University", False, "readers_disagree"),
        _v("education.end_date", "2024-06-15")])
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")], document=first.document, version="doc-2")
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")  # still one degree
        assert row.confirmed_at is not None and row.supersedes_id is not None
        assert row.supersedes.confirmed_at is None  # the waiting row, never confirmed in place


def test_correcting_one_key_of_a_degree_keeps_one_degree(agency_a, membership_a):
    """Plan 1's correct_fact writes a one-key row beside a multi-key one (ruling NB4).
    A degree counts once per row, so for EDUCATION and LANGUAGE it supersedes instead."""
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        correct_fact(student=membership_a, fact_id=row.id, key="end_date", value="2024-06-20")
        (tip,) = _tips(membership_a, "EDUCATION")
    assert tip.payload == {"institution_original": "ADA University", "end_date": "2024-06-20"}
    assert tip.source_tier == "STUDENT_STATEMENT" and tip.supersedes_id == row.id


def test_adopting_refuses_another_students_reading(agency_a, membership_a, django_user_model):
    """Same tenant on purpose: RLS already hides another agency's rows, so only a
    classmate's reading tests the student filter."""
    from apps.documents.confirmation import FactNotFound
    from tests.portals.test_answers import _student

    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id):
        classmate = _student(agency_a, django_user_model, "classmate")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id), pytest.raises(FactNotFound):
        adopt_document_value(student=classmate, reading_id=reading.id,
                             key="language.score_writing")


# Review hardening: the four ways plan 1 let a wrong value reach a portal.


def test_a_shared_latin_word_does_not_make_two_mixed_script_names_one(agency_a, membership_a):
    """fold_tokens drops the Cyrillic words, leaving {"UNIVERSITY"} on both sides."""
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="Московский University",
                   end_date="2023-06-30")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "Бакинский University"),
        _v("education.end_date", "2023-06-30")])
    with tenant_scope(agency_a.id):
        assert len(_tips(membership_a, "EDUCATION")) == 2


def test_a_re_read_that_spells_the_institution_differently_is_still_that_degree(
        agency_a, membership_a):
    first = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")])
    again = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA Univ."),
        _v("education.end_date", "2024-06-15")], document=first.document, version="doc-2")
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        assert row.payload["institution_original"] == "ADA University"
    assert _entry(again, "education.institution_original")["target"] == str(row.id)


def test_a_re_read_after_the_student_corrected_the_institution_stays_one_degree(
        agency_a, membership_a):
    first = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        correct_fact(student=membership_a, fact_id=row.id, key="institution_original",
                     value="ADA Universiteti")
    again = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")], document=first.document, version="doc-2")
    with tenant_scope(agency_a.id):
        (tip,) = _tips(membership_a, "EDUCATION")
        assert tip.payload["institution_original"] == "ADA Universiteti"
    differs = _entry(again, "education.institution_original")
    assert (differs["proven"], differs["why"]) == (False, "student_entry_differs")


def test_a_bachelor_diploma_fills_the_bachelor_not_the_master_in_progress(
        agency_a, membership_a):
    with tenant_scope(agency_a.id):
        bachelor = _cv_degree(membership_a, institution_original="ADA University",
                              degree_as_awarded="Bachelor", end_date="2023-06-30")
        master = _cv_degree(membership_a, institution_original="ADA University",
                            degree_as_awarded="Master")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2023-06-30"), _v("education.diploma_number", "AB 1")])
    with tenant_scope(agency_a.id):
        tips = {r.supersedes_id or r.id: r for r in _tips(membership_a, "EDUCATION")}
        assert len(tips) == 2
        assert tips[bachelor.id].payload["diploma_number"] == "AB 1"
        assert "diploma_number" not in tips[master.id].payload


def test_a_diploma_that_could_be_either_of_two_degrees_fills_neither(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="ADA University", degree_as_awarded="BA")
        _cv_degree(membership_a, institution_original="ADA University", degree_as_awarded="MA")
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.diploma_number", "AB 1")])
    with tenant_scope(agency_a.id):
        confirmed = [r for r in _tips(membership_a, "EDUCATION") if r.confirmed_at]
        assert len(confirmed) == 2
        assert not any("diploma_number" in r.payload for r in confirmed)
    assert not any(v["proven"] for v in reading.values)


def test_the_same_sitting_uploaded_twice_is_one_sitting(agency_a, membership_a):
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT, version="doc-2")
    with tenant_scope(agency_a.id):
        assert len(_tips(membership_a, "LANGUAGE")) == 1
