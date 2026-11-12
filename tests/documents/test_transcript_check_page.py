"""Transcript plan 3b Task 4: the check page -- one tap when nothing is doubtful, one card per
doubtful cell otherwise, a read-only summary, and "something's wrong" that never blocks."""

import re
from html import unescape

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.documents.models import TranscriptReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.documents import test_documents_page_details
from tests.documents.test_transcript_check import _KEY_NUMBERS, _RECORD, _row, _stored

pytestmark = pytest.mark.django_db
page = test_documents_page_details.page  # the student's own browser, as a fixture

URL = "/student/transcript/"


def _reading(agency, student, rows=(), highlights=(), crops=None):
    return _stored(agency, student, record=_RECORD, key_numbers=_KEY_NUMBERS, rows=list(rows),
                   highlights=list(highlights), crops=crops or {})


def _low_confidence(agency, student):
    return _reading(
        agency, student,
        rows=[_row(1, "Physics", credits="6", grade="B"), _row(2, "Algebra", credits="5",
                                                              grade="A")],
        highlights=[{"kind": "low_confidence", "scope": "row", "ref": "1"}],
        crops={"1:credits": "k1", "1:grade": "k2"},
    )


def _two_doubtful_rows(agency, student):
    return _reading(
        agency, student,
        rows=[_row(1, "Physics", credits="6", grade="B"), _row(2, "Algebra", credits="60",
                                                              grade="A")],
        highlights=[{"kind": "credit_out_of_range", "scope": "row", "ref": "1"},
                    {"kind": "credit_out_of_range", "scope": "row", "ref": "2"}])


def _html(response):
    return unescape(response.content.decode())


def _accepted(agency, reading):
    with tenant_scope(agency.id):
        reading.refresh_from_db()
    return reading.accepted


def test_the_url_is_named():
    assert reverse("student-transcript-check") == URL


def test_nothing_to_check_without_an_unaccepted_reading(page):
    html = _html(page.get(URL))
    assert "Nothing to check" in html and reverse("student-documents") in html


def test_a_clean_reading_is_one_tap(page, agency_a, membership_a):
    reading = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    html = _html(page.get(URL))
    assert "We read 1 course" in html and "overall 88 on a 100 scale" in html
    assert "Looks right?" in html and "Something's wrong" in html
    response = page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert response.status_code == 302
    assert _accepted(agency_a, reading) is not None


def test_somethings_wrong_on_the_one_tap_card_thanks_then_continues(page, agency_a,
                                                                     membership_a):
    reading = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    page.post(URL, {"reading_id": reading.id, "action": "review",
                    "reason": "my second semester is missing"})
    html = _html(page.get(URL))
    assert "Thanks — someone will look at it" in html and "Continue" in html
    page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert _accepted(agency_a, reading) is not None
    assert reading.review_reason == "my second semester is missing"


def test_a_doubtful_row_shows_its_first_card_with_the_picture_and_nothing_chosen(
    page, agency_a, membership_a
):
    reading = _low_confidence(agency_a, membership_a)
    html = _html(page.get(URL))
    for cell in ("1:credits", "1:grade"):  # one card for the row: both its doubtful cells
        crop = reverse("api-documents-transcript-crop", args=[reading.id, cell])
        assert f'<img src="{crop}"' in html
    assert 'alt="' in html
    assert "1 of 1" in html and "Physics" in html
    assert "Credits we read: <strong>6</strong>" in html
    assert "Grade we read: <strong>B</strong>" in html
    assert "We weren't sure we read this correctly." in html
    assert "Matches" in html and "Fix" in html and "Can't read" in html
    assert not re.search(r"\b(checked|selected)\b", html)


def test_a_cell_without_a_picture_says_so(page, agency_a, membership_a):
    _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="60")],
             highlights=[{"kind": "credit_out_of_range", "scope": "row", "ref": "1"}])
    assert "No picture for this one" in _html(page.get(URL))


def test_one_fix_answers_the_rows_cells_and_an_unchanged_one_matches(page, agency_a,
                                                                     membership_a):
    reading = _low_confidence(agency_a, membership_a)
    response = page.post(URL, {"reading_id": reading.id, "action": "answer",
                               "ref": ["1:credits", "1:grade"], "choice": "fix",
                               "value:1:credits": "7", "value:1:grade": "B"})
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        reading.refresh_from_db()
    assert reading.answers["1:credits"]["choice"] == "fix"
    assert reading.answers["1:grade"]["choice"] == "matches"
    assert "Your transcript" in _html(page.get(URL))


def test_a_refused_fix_says_why_and_stays_on_the_card(page, agency_a, membership_a):
    reading = _low_confidence(agency_a, membership_a)
    page.post(URL, {"reading_id": reading.id, "action": "answer",
                    "ref": ["1:credits", "1:grade"], "choice": "fix",
                    "value:1:credits": "six", "value:1:grade": "B"})
    html = _html(page.get(URL))
    assert "1 of 1" in html and "credits must be a number" not in html
    assert "That value can't be saved" in html


def test_the_summary_lists_every_course_and_never_says_verified(page, agency_a, membership_a):
    reading = _low_confidence(agency_a, membership_a)
    page.post(URL, {"reading_id": reading.id, "action": "answer",
                    "ref": ["1:credits", "1:grade"], "choice": "fix",
                    "value:1:credits": "7", "value:1:grade": "B"})
    html = _html(page.get(URL))
    assert "Physics" in html and "Algebra" in html and "you changed this" in html
    assert "Only the cells we asked about were checked with you" in html
    assert "verified" not in html.lower()
    page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert _accepted(agency_a, reading)["courses"][0]["ects"] == "7.00"


def test_accepting_with_a_card_still_open_is_refused(page, agency_a, membership_a):
    reading = _low_confidence(agency_a, membership_a)
    page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert _accepted(agency_a, reading) is None


def test_another_students_reading_is_404(page, agency_a, membership_a):
    other_user = get_user_model().objects.create_user(username="student-a2")
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(tenant=agency_a, user=other_user,
                                          role=Membership.Role.STUDENT)
    theirs = _reading(agency_a, other)
    response = page.post(URL, {"reading_id": theirs.id, "action": "accept"})
    assert response.status_code == 404
    with tenant_scope(agency_a.id):
        assert TranscriptReading.objects.get(id=theirs.id).accepted is None


def test_the_newest_unaccepted_reading_is_the_one_checked(page, agency_a, membership_a):
    first = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    page.post(URL, {"reading_id": first.id, "action": "accept"})
    _reading(agency_a, membership_a, rows=[_row(1, "Chemistry", credits="6")])
    html = _html(page.get(URL))
    assert "We read 1 course" in html and "Looks right?" in html


def test_the_same_degree_question_is_two_buttons(page, agency_a, membership_a):
    from tests.documents.test_transcript_check import _cv_degree

    _cv_degree(agency_a, membership_a, "Bakı Dövlət Universiteti", "Bakalavr", "2027-06-30")
    reading = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    html = _html(page.get(URL))
    assert "Is this the same degree as Bakalavr, Bakı Dövlət Universiteti, 2027 on your CV?" in html
    assert "Same degree" in html and "Different degree" in html and "Can't read" not in html
    assert "No picture for this one" not in html
    page.post(URL, {"reading_id": reading.id, "action": "answer", "ref": "degree:same",
                    "choice": "same"})
    page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert _accepted(agency_a, reading) is not None


def test_an_older_reading_cannot_be_accepted_over_the_newer_one(page, agency_a, membership_a):
    # Final review finding 3: a stale tab.
    from datetime import timedelta

    older = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    newer = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    with tenant_scope(agency_a.id):
        TranscriptReading.objects.filter(id=older.id).update(
            created_at=newer.created_at - timedelta(days=1))
    page.post(URL, {"reading_id": older.id, "action": "accept"})
    assert _accepted(agency_a, older) is None


def test_a_blank_field_card_only_asks_for_the_value(page, agency_a, membership_a):
    _stored(agency_a, membership_a, record={**_RECORD, "field": ""}, key_numbers=_KEY_NUMBERS,
            rows=[], highlights=[])
    html = _html(page.get(URL))
    assert "We couldn't read your field of study from the transcript. Type it here." in html
    assert "Matches" not in html and "Can't read" not in html and 'id="fix-value"' in html


# --- Friction pass (walked as a student, 2026-10-20) ---------------------------------------


def test_a_card_names_the_cell_it_asks_about(page, agency_a, membership_a):
    _low_confidence(agency_a, membership_a)
    html = _html(page.get(URL))
    assert "Credits we read: <strong>6</strong>" in html
    assert "We weren't sure about 1 thing on your transcript" in html


def test_a_blank_field_card_is_just_the_box_named_for_the_field(page, agency_a, membership_a):
    _stored(agency_a, membership_a, record={**_RECORD, "field": ""}, key_numbers=_KEY_NUMBERS,
            rows=[], highlights=[])
    html = _html(page.get(URL))
    assert "<h2 id=\"card\">Field of study</h2>" in html
    assert "No picture for this one" not in html and "(blank)" not in html
    assert '<label for="fix-value">Field of study</label>' in html


def test_a_fix_that_adds_a_question_says_why(page, agency_a, membership_a):
    reading = _reading(
        agency_a, membership_a,
        rows=[_row(0, kind="semester_heading"), _row(1, "Physics", credits="6", grade="B"),
              _row(2, "Thesis", credits="24", grade="A"),
              _row(3, "Semester 1", "semester_total", "30")],
        highlights=[{"kind": "low_confidence", "scope": "row", "ref": "1"}])
    page.post(URL, {"reading_id": reading.id, "action": "answer",
                    "ref": ["1:credits", "1:grade"], "choice": "fix",
                    "value:1:credits": "8", "value:1:grade": "B"})
    html = _html(page.get(URL))
    assert "Your change affects a total, so we added a question about it." in html
    assert "2 of 2" in html


def test_an_answer_can_be_changed_before_accepting(page, agency_a, membership_a):
    reading = _two_doubtful_rows(agency_a, membership_a)
    page.post(URL, {"reading_id": reading.id, "action": "answer", "ref": "1:credits",
                    "choice": "fix", "value": "7"})
    assert "Back" in _html(page.get(URL))
    page.post(URL, {"reading_id": reading.id, "action": "answer", "ref": "2:credits",
                    "choice": "matches"})
    summary = _html(page.get(URL))
    assert "Change" in summary
    page.post(URL, {"reading_id": reading.id, "action": "reopen", "ref": "1:credits"})
    html = _html(page.get(URL))
    assert "Credits we read: <strong>6</strong>" in html
    with tenant_scope(agency_a.id):
        reading.refresh_from_db()
    assert "1:credits" not in reading.answers and "2:credits" in reading.answers


def test_the_summary_and_the_clean_card_name_the_degree_and_show_the_courses(
    page, agency_a, membership_a
):
    reading = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6",
                                                          grade="B")])
    html = _html(page.get(URL))
    assert "BSc in Physics — Baku State University" in html
    assert "See the 1 course" in html and "<td>Physics</td>" in html
    low = _low_confidence(agency_a, membership_a)  # newer: now the one checked
    page.post(URL, {"reading_id": low.id, "action": "answer", "ref": ["1:credits", "1:grade"],
                    "choice": "cant_read"})
    summary = _html(page.get(URL))
    assert "BSc in Physics — Baku State University" in summary
    assert "you couldn't read this; someone will check it" in summary
    assert reading.id != low.id


def test_a_student_without_a_profile_goes_on_to_the_questions(page, agency_a, membership_a):
    reading = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    response = page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert response.status_code == 302 and response["Location"] == reverse("student-profile")


def test_a_checked_transcript_stays_visible_and_can_still_be_reported(
    page, agency_a, membership_a
):
    reading = _reading(agency_a, membership_a, rows=[_row(1, "Physics", credits="6")])
    page.post(URL, {"reading_id": reading.id, "action": "accept"})
    docs = _html(page.get(reverse("student-documents")))
    assert "Your transcript: checked" in docs and "BSc in Physics — Baku State University" in docs
    page.post(URL, {"reading_id": reading.id, "action": "review", "reason": "a course is missing"})
    with tenant_scope(agency_a.id):
        reading.refresh_from_db()
    assert reading.review_reason == "a course is missing" and reading.accepted is not None


def test_the_documents_page_shows_no_template_notes(page):
    assert "SHOULD BE DONE BY AYKHAN" not in _html(page.get(reverse("student-documents")))


def test_the_country_is_chosen_from_a_list(page, agency_a, membership_a):
    reading = _stored(agency_a, membership_a, record={**_RECORD, "country_code": ""},
                      key_numbers=_KEY_NUMBERS, rows=[], highlights=[])
    html = _html(page.get(URL))
    assert '<select id="fix-value" name="value"' in html
    assert '<option value="AZ">Azerbaijan</option>' in html
    page.post(URL, {"reading_id": reading.id, "action": "answer", "ref": "field:country",
                    "choice": "fix", "value": "AZ"})
    page.post(URL, {"reading_id": reading.id, "action": "accept"})
    assert _accepted(agency_a, reading)["country_code"] == "AZ"
