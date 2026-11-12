# ruff: noqa: F811 -- fixtures imported by name and requested as arguments
"""Transcript plan 3b Task 6: the dashboard asks the student to check their transcript, and a
review request reaches a person -- the assigned counsellor, or Elmify staff for a student with
none (spec §6.5's split; onboarding friction variant 7)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from tests.conftest import reads_no_catalogue
from tests.dashboard.test_counselor_board import counselor_client  # noqa: F401
from tests.dashboard.test_staff_board import staff_client  # noqa: F401
from tests.documents.test_transcript_check import _KEY_NUMBERS, _RECORD, _stored

pytestmark = pytest.mark.django_db

CHECK = reverse("student-transcript-check")


def _reading(agency, student, **fields):
    return _stored(agency, student, record=_RECORD, key_numbers=_KEY_NUMBERS, **fields)


def _home(client, user, host):
    client.force_login(user)
    with reads_no_catalogue():
        return client.get("/student/", HTTP_HOST=host).content.decode()


def test_the_dashboard_asks_to_check_an_unaccepted_transcript(client, agency_a, domain_a,
                                                             user_a, membership_a):
    _reading(agency_a, membership_a)
    body = _home(client, user_a, domain_a.host)
    assert f'href="{CHECK}"' in body and "Check your transcript" in body


def test_an_accepted_transcript_is_not_asked_about(client, agency_a, domain_a, user_a,
                                                   membership_a):
    _reading(agency_a, membership_a, accepted=_RECORD)
    body = _home(client, user_a, domain_a.host)
    assert CHECK not in body and "Check your transcript" not in body


def _review(agency, student, reason="my second semester is missing"):
    return _reading(agency, student, review_requested_at=timezone.now(), review_reason=reason)


def _page(client, host, student):
    response = client.get(f"/counselor/students/{student.id}/", HTTP_HOST=host)
    assert response.status_code == 200
    return response.content.decode()


def test_the_assigned_counsellor_sees_the_review_reason(counselor_client, agency_a, domain_a,
                                                        membership_a):
    _review(agency_a, membership_a)
    body = _page(counselor_client, domain_a.host, membership_a)
    assert "Transcript: the student asked for a review — my second semester is missing" in body


def test_a_direct_students_review_shows_on_the_staff_page(staff_client, agency_a, domain_a,
                                                          membership_a):
    _review(agency_a, membership_a)
    body = _page(staff_client, domain_a.host, membership_a)
    assert "Transcript: the student asked for a review — my second semester is missing" in body


def test_an_agency_students_review_is_their_counsellors_not_staffs(
    counselor_client, client, agency_a, domain_a, membership_a
):
    from tests.portals.test_staff_file_access import _login, _staff

    _review(agency_a, membership_a)
    user, _membership = _staff(agency_a)
    client.logout()
    _login(client, user)
    body = _page(client, domain_a.host, membership_a)
    assert "asked for a review" not in body


def test_no_review_no_line(counselor_client, agency_a, domain_a, membership_a):
    _reading(agency_a, membership_a)
    assert "asked for a review" not in _page(counselor_client, domain_a.host, membership_a)


def test_the_transcript_check_is_a_need_not_a_loose_link(client, agency_a, domain_a, user_a,
                                                         membership_a):
    _reading(agency_a, membership_a)
    body = _home(client, user_a, domain_a.host)
    needs = body.split('id="needs-heading"')[1].split("</section>")[0]
    assert f'href="{CHECK}"' in needs and "Nothing needs you right now" not in needs
