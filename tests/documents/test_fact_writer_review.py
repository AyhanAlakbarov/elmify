"""Task 5 review round 1: end-to-end probes of the diploma and certificate writers,
each asserting what a portal is served. The controller's rulings are cited per test."""
import pytest
from django.db import IntegrityError, transaction

from apps.documents import fact_writer
from apps.documents.confirmation import FactNotFound
from apps.documents.fact_labels import WHY_TEXT
from apps.documents.fact_writer import (
    adopt_document_value,
    correct_fact,
    dismiss_document_value,
)
from apps.portals.profile import verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.documents.test_fact_writer_documents import CERT, _cv_degree, _entry, _read, _tips, _v

pytestmark = pytest.mark.django_db

BDU_CV = dict(institution_original="Bakı Dövlət Universiteti", degree_as_awarded="Bachelor",
              end_date="2023-06-30")


def _served(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return verified_values(student)


def _degrees(values):
    return sorted({k.split(".")[1] for k in values
                   if k.startswith("education.") and k.split(".")[1].isdigit()})


def _unconfirm(row):
    row.confirmed_at = None
    row.confirmed_by = None
    row.save()
    return row


def _cert(name, date, score, writing="6.0", number=None):
    values = [_v("language.test_name", name), _v("language.language", "English"),
              _v("language.test_date", date), _v("language.test_score", score),
              _v("language.score_writing", writing)]
    return values + ([_v("language.certificate_number", number)] if number else [])


# ---- ruling 1: an unmatched diploma beside an existing degree waits whole --------------


def test_a_translation_of_the_cv_degree_is_not_a_second_degree(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, **BDU_CV)
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_english", "Baku State University"),
        _v("education.degree_english", "Bachelor of Science"),
        _v("education.end_date", "2023-06-30")])
    assert _degrees(_served(agency_a, membership_a)) == ["1"]
    assert {v["why"] for v in reading.values} == {"new_degree"}


def test_an_abbreviation_on_the_cv_is_not_a_second_degree(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="BSU", end_date="2023-06-30")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "Baku State University"),
        _v("education.end_date", "2023-06-30"), _v("education.diploma_number", "AB 1")])
    assert _degrees(_served(agency_a, membership_a)) == ["1"]


def test_a_translation_after_its_original_is_not_a_second_degree(agency_a, membership_a):
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "Bakı Dövlət Universiteti"),
        _v("education.end_date", "2023-06-30")])
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_english", "Baku State University"),
        _v("education.end_date", "2023-06-30")])
    assert _degrees(_served(agency_a, membership_a)) == ["1"]


def test_a_re_upload_after_correcting_the_institution_is_not_a_second_degree(
        agency_a, membership_a):
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA Universitet"),
        _v("education.end_date", "2024-06-15")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        correct_fact(student=membership_a, fact_id=row.id, key="institution_original",
                     value="ADA Universiteti")
    _read(agency_a, membership_a, "DIPLOMA", [  # the same file as a new upload
        _v("education.institution_original", "ADA Universitet"),
        _v("education.end_date", "2024-06-15")])
    values = _served(agency_a, membership_a)
    assert _degrees(values) == ["1"]
    assert values["education.1.institution_original"] == "ADA Universiteti"


def test_a_second_unmatched_degree_waits_for_the_student(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, **BDU_CV)
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.degree_as_awarded", "Master"),
        _v("education.end_date", "2025-06-15")])
    with tenant_scope(agency_a.id):
        new = [r for r in _tips(membership_a, "EDUCATION") if r.source_ref.startswith("document:")]
        assert len(new) == 1 and new[0].confirmed_at is None
    assert not any(v["proven"] for v in reading.values)
    assert WHY_TEXT["new_degree"] == "Is this a new degree?"


def test_correct_then_re_read_keeps_the_students_entry(agency_a, membership_a):
    first = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        correct_fact(student=membership_a, fact_id=row.id, key="end_date", value="2024-06-20")
    again = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15")], document=first.document, version="doc-2")
    values = _served(agency_a, membership_a)
    assert values["education.1.end_date"] == "2024-06-20" and _degrees(values) == ["1"]
    assert _entry(again, "education.end_date")["why"] == "student_entry_differs"


# ---- ruling 3: only a proven year places a diploma ---------------------------------------


def test_a_masters_diploma_fills_the_undated_master_row(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="ADA University",
                   degree_as_awarded="Bachelor", end_date="2023-06-30")
        _cv_degree(membership_a, institution_original="ADA University", degree_as_awarded="Master")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.degree_as_awarded", "Master"),
        _v("education.end_date", "2025-06-15"), _v("education.diploma_number", "M 9")])
    values = _served(agency_a, membership_a)
    assert _degrees(values) == ["1", "2"]
    master = next(k for k, v in values.items() if v == "Master" and k.count(".") == 2)
    assert values[f"education.{master.split('.')[1]}.diploma_number"] == "M 9"


def test_a_misread_year_never_places_a_bachelors_diploma_on_the_master(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="ADA University",
                   degree_as_awarded="Bachelor", end_date="2023-06-30")
        _cv_degree(membership_a, institution_original="ADA University", degree_as_awarded="Master")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.degree_as_awarded", "Bakalavr"),
        _v("education.end_date", "2028-06-30", False, "low_confidence"),  # a misread 2023
        _v("education.diploma_number", "B 1")])
    values = _served(agency_a, membership_a)
    assert not any(k.endswith(".diploma_number") for k in values)


def test_a_misread_year_is_not_a_second_degree(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="ADA University", end_date="2023-06-30")
    _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2028-06-30", False, "low_confidence"),
        _v("education.diploma_number", "B 1")])
    assert _degrees(_served(agency_a, membership_a)) == ["1"]


# ---- ruling 5: only the institution is compared folded ----------------------------------


def test_a_different_number_or_grade_is_a_detail_to_check(agency_a, membership_a):
    first = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15"),
        _v("education.diploma_number", "AB123456"), _v("education.grade_native", "B")])
    again = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.end_date", "2024-06-15"),
        _v("education.diploma_number", "AB654321"), _v("education.grade_native", "B+")],
        document=first.document, version="doc-2")
    values = _served(agency_a, membership_a)
    assert values["education.1.diploma_number"] == "AB123456"
    for key in ("education.diploma_number", "education.grade_native"):
        entry = _entry(again, key)
        assert not entry["proven"] and entry["target"], entry


# ---- ruling 4: only a confirmed degree is filled; no tap serves a CV claim -------------


def test_a_diploma_never_fills_an_unconfirmed_cv_degree(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        cv = _unconfirm(_cv_degree(membership_a, **BDU_CV))
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "Bakı Dövlət Universiteti"),
        _v("education.degree_as_awarded", "Bakalavr"),
        _v("education.end_date", "2023-06-30"), _v("education.diploma_number", "AB 1")])
    with tenant_scope(agency_a.id):
        tips = _tips(membership_a, "EDUCATION")
        assert len(tips) == 2 and not any(r.confirmed_at for r in tips)
        assert any(r.id == cv.id for r in tips)  # the CV row is untouched
    assert _degrees(_served(agency_a, membership_a)) == []
    assert {v["why"] for v in reading.values} == {"new_degree"}
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id), pytest.raises(FactNotFound):
        adopt_document_value(student=membership_a, reading_id=reading.id,
                             key="education.degree_as_awarded")


def test_a_tap_never_serves_an_unconfirmed_cv_claim(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _unconfirm(_cv_degree(membership_a, institution_original="ADA University",
                              degree_as_awarded="Bachelor", end_date="2023-06-30",
                              grade_native="4.0/4.0"))
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.degree_as_awarded", "Bakalavr"), _v("education.end_date", "2023-06-30")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        with pytest.raises(FactNotFound):
            adopt_document_value(student=membership_a, reading_id=reading.id,
                                 key="education.degree_as_awarded")
        assert "education.1.grade_native" not in verified_values(membership_a)


# ---- ruling 6: a filled row carries the diploma's ref -----------------------------------


def test_a_value_a_diploma_filled_into_the_cv_degree_can_be_corrected(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, **BDU_CV)
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "Bakı Dövlət Universiteti"),
        _v("education.end_date", "2023-06-30"), _v("education.diploma_number", "AB 1")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = _tips(membership_a, "EDUCATION")
        assert row.source_ref == f"document:{reading.document_id}"
        correct_fact(student=membership_a, fact_id=row.id, key="diploma_number", value="AB 2")
        (tip,) = _tips(membership_a, "EDUCATION")
    assert tip.payload["diploma_number"] == "AB 2"
    assert tip.payload["degree_as_awarded"] == "Bachelor"


# ---- ruling 2: an answered value is answered -------------------------------------------


def _bdu_diploma():
    return [_v("education.institution_original", "BDU"), _v("education.end_date", "2023-06-30"),
            _v("education.degree_as_awarded", "Bakalavr")]


def test_keep_mine_then_a_re_read_is_not_asked_again(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="BDU", degree_as_awarded="Bachelor",
                   end_date="2023-06-30")
    first = _read(agency_a, membership_a, "DIPLOMA", _bdu_diploma())
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        dismiss_document_value(student=membership_a, reading_id=first.id,
                               key="education.degree_as_awarded")
    again = _read(agency_a, membership_a, "DIPLOMA", _bdu_diploma(),
                  document=first.document, version="doc-2")
    assert _entry(again, "education.degree_as_awarded")["why"] == "kept"
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id), pytest.raises(FactNotFound):
        adopt_document_value(student=membership_a, reading_id=again.id,
                             key="education.degree_as_awarded")


def test_keep_mine_then_a_re_upload_is_not_asked_again(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="BDU", degree_as_awarded="Bachelor",
                   end_date="2023-06-30")
    first = _read(agency_a, membership_a, "DIPLOMA", _bdu_diploma())
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        dismiss_document_value(student=membership_a, reading_id=first.id,
                               key="education.degree_as_awarded")
    again = _read(agency_a, membership_a, "DIPLOMA", _bdu_diploma())
    assert _entry(again, "education.degree_as_awarded")["why"] == "kept"


def test_a_different_value_after_keep_mine_is_asked(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="BDU", degree_as_awarded="Bachelor",
                   end_date="2023-06-30")
    first = _read(agency_a, membership_a, "DIPLOMA", _bdu_diploma())
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        dismiss_document_value(student=membership_a, reading_id=first.id,
                               key="education.degree_as_awarded")
    again = _read(agency_a, membership_a, "DIPLOMA",
                  [*_bdu_diploma()[:2], _v("education.degree_as_awarded", "Magistr")],
                  document=first.document, version="doc-2")
    assert _entry(again, "education.degree_as_awarded")["why"] == "document_differs"


def test_an_adopted_value_cannot_be_adopted_twice(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        adopt_document_value(student=membership_a, reading_id=reading.id,
                             key="language.score_writing")
        with pytest.raises(FactNotFound):
            adopt_document_value(student=membership_a, reading_id=reading.id,
                                 key="language.score_writing")


def test_a_kept_value_cannot_then_be_adopted(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        dismiss_document_value(student=membership_a, reading_id=reading.id,
                               key="language.score_writing")
        with pytest.raises(FactNotFound):
            adopt_document_value(student=membership_a, reading_id=reading.id,
                                 key="language.score_writing")


# ---- certificates -----------------------------------------------------------------------


def test_the_latest_ielts_wins_over_an_older_toefl(agency_a, membership_a):
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", _cert("IELTS", "2025-11-08", "6.5"))
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", _cert("IELTS", "2026-03-01", "7.5"))
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
          _cert("TOEFL", "2024-05-01", "100", "25"))
    values = _served(agency_a, membership_a)
    assert values["language.test_score"] == "7.5" and values["language.test_name"] == "IELTS"
    assert values["language.score_writing"] == "6.0"


def test_the_latest_sitting_across_all_tests_is_served(agency_a, membership_a):
    """Spec as amended (c0013bfc): the latest sitting across all tests."""
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", _cert("IELTS", "2025-11-08", "7.0"))
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
          _cert("TOEFL", "2026-01-01", "100", "25"))
    assert _served(agency_a, membership_a)["language.test_name"] == "TOEFL"


def test_a_newer_certificate_wins_after_a_use_tap(agency_a, membership_a):
    first = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        adopt_document_value(student=membership_a, reading_id=first.id,
                             key="language.score_writing")
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
          _cert("IELTS", "2026-03-01", "7.5", "7.0"))
    values = _served(agency_a, membership_a)
    assert values["language.test_score"] == "7.5" and values["language.score_writing"] == "7.0"


def test_the_same_certificate_twice_with_a_doubtful_second_date_is_one_sitting(
        agency_a, membership_a):
    """Ruling 7: a proven certificate number is the same sitting."""
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
          _cert("IELTS", "2025-11-08", "6.5", number="25GB001234"))
    second = _cert("IELTS", "2025-11-08", "6.5", number="25GB001234")
    second[2] = _v("language.test_date", "2025-11-03", False, "date_unclear")
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", second)
    with tenant_scope(agency_a.id):
        assert len([r for r in _tips(membership_a, "LANGUAGE") if r.confirmed_at]) == 1


def test_a_certificate_with_no_proven_test_waits_as_a_new_result(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
                    [_v("language.test_name", "IELTS", False, "readers_disagree"),
                     *CERT[1:4]])
    whys = {v["key"]: v["why"] for v in reading.values}
    assert whys["language.test_name"] == "readers_disagree"  # the reader's doubt stays
    assert whys["language.test_score"] == "new_result"  # never "readers_agree" unconfirmed
    assert WHY_TEXT["new_result"] == "Is this a new test result?"


# ---- adopt / dismiss edges --------------------------------------------------------------


def test_only_a_waiting_value_can_be_used_or_kept(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id), pytest.raises(FactNotFound):
        adopt_document_value(student=membership_a, reading_id=reading.id,
                             key="language.score_reading")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id), pytest.raises(FactNotFound):
        dismiss_document_value(student=membership_a, reading_id=reading.id,
                               key="language.test_score")


def test_keeping_refuses_another_students_reading(agency_a, membership_a, django_user_model):
    from tests.portals.test_answers import _student

    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id):
        classmate = _student(agency_a, django_user_model, "classmate2")
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id), pytest.raises(FactNotFound):
        dismiss_document_value(student=classmate, reading_id=reading.id,
                               key="language.score_writing")


def test_using_a_value_after_a_correction_builds_on_the_correction(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (row,) = _tips(membership_a, "LANGUAGE")
        correct_fact(student=membership_a, fact_id=row.id, key="test_score", value="7.0")
        new = adopt_document_value(student=membership_a, reading_id=reading.id,
                                   key="language.score_writing")
        assert new.payload["test_score"] == "7.0" and new.payload["score_writing"] == "6.0"
        assert len(_tips(membership_a, "LANGUAGE")) == 1


def test_a_use_racing_a_re_read_fails_and_settles_nothing(agency_a, membership_a, monkeypatch):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", CERT)
    with tenant_scope(agency_a.id):
        (stale,) = _tips(membership_a, "LANGUAGE")
    # Fix round 1: only the latest reading is answerable, so the re-read carries the
    # waiting value too; the Use still holds the tip it saw before the re-read.
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE",
                    [*CERT[:4], _v("language.score_reading", "7.0"), CERT[4]],
                    document=reading.document, version="doc-2")
    monkeypatch.setattr(fact_writer, "tip_of", lambda f: stale)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        with pytest.raises(IntegrityError), transaction.atomic():
            adopt_document_value(student=membership_a, reading_id=reading.id,
                                 key="language.score_writing")
        reading.refresh_from_db()
        assert _entry(reading, "language.score_writing")["why"] != "adopted"


def test_a_diploma_that_could_be_either_of_two_degrees_says_so(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        _cv_degree(membership_a, institution_original="ADA University", degree_as_awarded="BA")
        _cv_degree(membership_a, institution_original="ADA University", degree_as_awarded="MA")
    reading = _read(agency_a, membership_a, "DIPLOMA", [
        _v("education.institution_original", "ADA University"),
        _v("education.diploma_number", "AB 1")])
    assert {v["why"] for v in reading.values} == {"new_degree"}
