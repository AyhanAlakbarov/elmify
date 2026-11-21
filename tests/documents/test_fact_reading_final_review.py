"""Plan 2's final whole-branch review: each finding (I1-I3, M1, M3-M6) pinned as a test.
The reviewer's probes (scratchpad final2) are p1-p3 here."""

from html import unescape

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.documents.confirmation import confirm_facts
from apps.documents.fact_readers import CertificateQuotes, DiplomaQuotes
from apps.documents.fact_writer import adopt_document_value, merge_whole_document
from apps.documents.models import VerifiedFact
from apps.documents.text_reading import _iso_date
from apps.portals.profile import verified_values
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.documents import test_documents_page_details
from tests.documents.test_documents_page_adopt import _ADA, _ADA_VALUES, _details, _whole
from tests.documents.test_fact_writer_documents import _cv_degree, _read, _tips, _v

pytestmark = pytest.mark.django_db
page = test_documents_page_details.page


def _degree_count(agency, student):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        values = verified_values(student)
    return len({k.split(".")[1] for k in values
                if k.startswith("education.") and k.split(".")[1].isdigit()})


def _unconfirmed_cv_degree(agency, student, **payload):
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        cv = _cv_degree(student, **payload)
        cv.confirmed_at = None
        cv.confirmed_by = None
        cv.save()
    return cv


_DIPLOMA = [_v("education.institution_original", "ADA University"),
            _v("education.end_date", "2024-06-15"), _v("education.diploma_number", "AB 1")]


# I1: Correct never confirms a whole-document row.


def test_p1_correct_on_a_merged_whole_row_makes_no_second_degree(page, agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="ADA University",
                            degree_as_awarded="Bachelor")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    assert page.post(reverse("student-document-merge", args=[whole.id]),
                     {"into": str(degree.id)}).status_code == 302
    response = page.post(reverse("student-fact-correct", args=[whole.id]),
                         {"key": "institution_original", "value": "ADA University"})
    assert response.status_code == 404
    assert _degree_count(agency_a, membership_a) == 1


def test_p1b_correct_on_an_open_whole_row_is_refused(page, agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _cv_degree(membership_a, institution_original="ADA University",
                   degree_as_awarded="Bachelor")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    response = page.post(reverse("student-fact-correct", args=[whole.id]),
                         {"key": "end_date", "value": "2024-06-15"})
    assert response.status_code == 404
    assert _degree_count(agency_a, membership_a) == 1


# I2: an unconfirmed CV degree the diploma may be.


def test_p2_the_line_waits_while_the_cv_degree_is_unconfirmed(page, agency_a, membership_a):
    """Concern ruling 1: nothing to answer until the CV degree is confirmed, then the
    question with "No — it's my X" onto that confirmed row."""
    cv = _unconfirmed_cv_degree(agency_a, membership_a, institution_original="ADA University",
                                degree_as_awarded="Bachelor", end_date="2024-06-15")
    _read(agency_a, membership_a, "DIPLOMA", _DIPLOMA)
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Yes, add it" not in html and "it's my" not in html
    assert "detail to check" not in html and "AB 1" not in html
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        confirm_facts(student=membership_a, fact_ids=[cv.id], actor=membership_a)
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Is this a new degree?" in html
    assert "No — it's my Bachelor, ADA University" in html


def test_p2b_yes_then_confirming_the_cv_degree_serves_one_degree(agency_a, membership_a):
    cv = _unconfirmed_cv_degree(agency_a, membership_a, institution_original="ADA University",
                                degree_as_awarded="Bachelor", end_date="2024-06-15")
    _read(agency_a, membership_a, "DIPLOMA", _DIPLOMA)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        whole = next(r for r in _tips(membership_a, "EDUCATION")
                     if r.source_ref.startswith("document:"))
        assert confirm_facts(student=membership_a, fact_ids=[whole.id], actor=membership_a) == 0
        confirm_facts(student=membership_a, fact_ids=[cv.id], actor=membership_a)
    assert _degree_count(agency_a, membership_a) == 1


def test_a_merge_onto_an_unconfirmed_cv_degree_is_refused(page, agency_a, membership_a):
    """Attach only to confirmed rows: a merge never confirms a CV degree."""
    cv = _unconfirmed_cv_degree(agency_a, membership_a, institution_original="ADA University",
                                degree_as_awarded="Bachelor")
    _read(agency_a, membership_a, "DIPLOMA", _DIPLOMA)
    with tenant_scope(agency_a.id):
        whole = next(r for r in _tips(membership_a, "EDUCATION")
                     if r.source_ref.startswith("document:"))
    assert page.post(reverse("student-document-merge", args=[whole.id]),
                     {"into": str(cv.id)}).status_code == 404
    with tenant_scope(agency_a.id):
        cv.refresh_from_db()
        assert cv.confirmed_at is None
    assert _degree_count(agency_a, membership_a) == 0


def test_an_unconfirmed_degree_elsewhere_holds_nothing_back(page, agency_a, membership_a):
    _unconfirmed_cv_degree(agency_a, membership_a, institution_original="Khazar University")
    _read(agency_a, membership_a, "DIPLOMA", _DIPLOMA)
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Yes, add it" in html and "it's my" not in html


# I3: dates.


@pytest.mark.parametrize("printed", ["18/JAN/2025", "18-Jan-2025", "18.Jan.2025",
                                     "18 Jan 2025", "Jan 18, 2025"])
def test_a_month_name_date_normalises_with_any_separator(printed):
    assert _iso_date(printed) == "2025-01-18"


def test_a_two_digit_year_with_a_separator_still_does_not_normalise():
    assert _iso_date("18/JAN/25") is None


_TOEFL = [_v("language.test_name", "TOEFL"), _v("language.language", "English"),
          _v("language.test_date", "2023-03-01"), _v("language.test_score", "95")]
_IELTS_UNCLEAR = [_v("language.test_name", "IELTS"), _v("language.language", "English"),
                  _v("language.test_date", "18/JAN/2025", False, "date_unclear"),
                  _v("language.test_score", "7.5")]


def test_p3_use_never_writes_an_unread_date_the_student_types_it(page, agency_a, membership_a):
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", _TOEFL)
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", _IELTS_UNCLEAR)
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert 'type="date" name="value"' in html  # a box to type it in, on the Use line
    url = reverse("student-document-value-adopt", args=[reading.id])
    assert page.post(url, {"key": "language.test_date"}).status_code == 400
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        with pytest.raises(ValueError):
            adopt_document_value(student=membership_a, reading_id=reading.id,
                                 key="language.test_date")
    assert page.post(url, {"key": "language.test_date", "value": "2025-01-18"}).status_code == 302
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        values = verified_values(membership_a)
    assert values["language.test_name"] == "IELTS"
    assert values["language.test_date"] == "2025-01-18"


def test_a_typed_value_is_taken_only_for_an_unread_date(page, agency_a, membership_a):
    """Concern ruling 3: elsewhere a typed value is a correction, which has its own path."""
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", [
        _v("language.test_name", "IELTS"), _v("language.language", "English"),
        _v("language.test_date", "2025-01-18"),
        _v("language.test_score", "7.0", False, "low_confidence")])
    response = page.post(reverse("student-document-value-adopt", args=[reading.id]),
                         {"key": "language.test_score", "value": "9.0"})
    assert response.status_code == 400
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert "language.test_score" not in verified_values(membership_a)


def test_yes_add_it_never_writes_an_unread_date(page, agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", [
        _v("language.test_name", "IELTS", False, "readers_disagree"),
        _v("language.test_date", "18/JAN/2025", False, "date_unclear"),
        _v("language.test_score", "7.5")])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        (whole,) = _tips(membership_a, "LANGUAGE")
        assert "test_date" not in whole.payload
        confirm_facts(student=membership_a, fact_ids=[whole.id], actor=membership_a)
        assert "language.test_date" not in verified_values(membership_a)
    # Once the row is the student's, the date is a value to type.
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "18/JAN/2025" in html and 'type="date" name="value"' in html
    assert page.post(reverse("student-document-value-adopt", args=[reading.id]),
                     {"key": "language.test_date", "value": "2025-01-18"}).status_code == 302


def test_the_latest_sitting_is_ordered_on_iso_dates_only(agency_a, membership_a):
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        for test, when, ref in (("TOEFL", "2023-03-01", "document:a"),
                                ("IELTS", "June 2019", "document:b")):
            VerifiedFact.objects.create(
                student=membership_a, category="LANGUAGE",
                payload={"test_name": test, "test_date": when},
                source_tier="AUTHORITATIVE_DOCUMENT", source_ref=ref,
                confirmed_by=membership_a, confirmed_at=timezone.now(), created_by=membership_a)
        assert verified_values(membership_a)["language.test_name"] == "TOEFL"


# M3 + M4: the answers lock what they rewrite.


def test_an_answer_locks_the_reading_and_a_merge_locks_the_whole_row(agency_a, membership_a):
    reading = _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", _IELTS_UNCLEAR)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        with CaptureQueriesContext(connection) as queries:
            from apps.documents.fact_writer import dismiss_document_value
            dismiss_document_value(student=membership_a, reading_id=reading.id,
                                   key="language.test_date")
        assert any('FROM "documents_documentreading"' in q["sql"] and "FOR UPDATE" in q["sql"]
                   for q in queries.captured_queries)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        degree = _cv_degree(membership_a, institution_original="ADA University")
    whole = _whole(agency_a, membership_a, dict(_ADA), list(_ADA_VALUES))
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        with CaptureQueriesContext(connection) as queries:
            merge_whole_document(student=membership_a, fact_id=whole.id, into_id=degree.id)
        first = next(q["sql"] for q in queries.captured_queries
                     if 'FROM "documents_verifiedfact"' in q["sql"])
        assert "FOR UPDATE" in first


# M5: "Yes, add it" names what it is not sure of.


def test_a_whole_row_names_its_doubtful_values(page, agency_a, membership_a):
    _whole(agency_a, membership_a,
           {"institution_original": "ADA University", "grade_native": "4.0"},
           [{"key": "education.institution_original", "value": "ADA University",
             "snippet": "ADA", "proven": False, "why": "readers_disagree"},
            {"key": "education.grade_native", "value": "4.0", "snippet": "4.0",
             "proven": False, "why": "low_confidence"}])
    html = unescape(_details(page.get(reverse("student-documents")).content.decode()))
    assert "Institution: We read it two ways." in html
    assert "Grade: The text was hard to read." in html


# M6: a YDS result anchors on its test name.


def test_a_yds_result_is_proven_without_a_language(agency_a, membership_a):
    _read(agency_a, membership_a, "LANGUAGE_CERTIFICATE", [
        _v("language.test_name", "YDS"), _v("language.test_date", "2025-04-06"),
        _v("language.test_score", "80")])
    with tenant_scope(agency_a.id):
        (row,) = _tips(membership_a, "LANGUAGE")
        assert row.confirmed_at is not None and row.payload["test_name"] == "YDS"


# M1: the readers see what the labels mean.


def test_the_reader_schema_explains_the_ambiguous_fields():
    diploma = DiplomaQuotes.model_json_schema()["properties"]
    for field in ("document", "grade", "diploma_number"):
        assert diploma[field].get("description"), field
    assert "translation" in diploma["document"]["description"]
    assert CertificateQuotes.model_json_schema()["properties"]["document"]
