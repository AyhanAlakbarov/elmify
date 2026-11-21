# tests/dashboard/test_programme_page.py
import re
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from apps.portals.award_links import _NOT_STATED
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.conftest import reads_no_catalogue, verify_mfa_session
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db


def _get(client, url, domain):
    return client.get(url, HTTP_HOST=domain.host)


def test_the_student_sees_their_programme_page(
    client, agency_a, domain_a, membership_a, user_a, pack
):
    programme, award = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme,
                       kit_requirements=["A CV in English"])
    client.force_login(user_a)
    with reads_no_catalogue():
        response = _get(client, f"/student/applications/{app.id}/", domain_a)
    body = response.content.decode()
    assert response.status_code == 200
    assert "TUM — M.Sc. Informatics (Germany)" in body
    assert "A CV in English" in body                    # requirements
    assert "75.00 EUR" in body                          # application fee
    assert "DAAD Study Scholarship" in body             # funding line
    assert "934 EUR a month" in body
    assert "Official source" in body and "last checked" in body
    body = body.replace(_NOT_STATED[1], "")  # the spec's sanctioned line for a route-less award
    body = body.lower()
    for never in ("not stated", "not confirmed", "(unstructured)", "step 1", "how to apply"):
        assert never not in body


def _same_response(a, b) -> None:
    def body(response) -> bytes:  # the per-response CSRF token is the only variance
        return re.sub(rb'csrfmiddlewaretoken" value="[^"]*"', b"", response.content)

    assert (a.status_code, body(a)) == (b.status_code, body(b))


def test_another_students_application_is_the_random_id_404(
    client, agency_a, domain_a, membership_a, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme)
        other = Membership.objects.create(
            tenant=agency_a,
            user=get_user_model().objects.create_user(username="student-a2"),
            role=Membership.Role.STUDENT,
        )
    client.force_login(other.user)
    with reads_no_catalogue():
        real = _get(client, f"/student/applications/{app.id}/", domain_a)
        invented = _get(client, f"/student/applications/{uuid4()}/", domain_a)
    assert real.status_code == 404
    _same_response(real, invented)


def test_a_student_of_another_agency_gets_the_same_403(
    client, agency_a, domain_a, membership_a, user_b, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme)
    client.force_login(user_b)
    with reads_no_catalogue():
        real = _get(client, f"/student/applications/{app.id}/", domain_a)
        invented = _get(client, f"/student/applications/{uuid4()}/", domain_a)
    assert real.status_code == 403
    _same_response(real, invented)


def test_the_assigned_counsellor_sees_it_and_no_one_else(
    client, agency_a, domain_a, membership_a, counselor_user, counselor_membership, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, programme)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    url = f"/counselor/students/{membership_a.id}/applications/{app.id}/"
    assert _get(client, url, domain_a).status_code == 404  # not assigned yet
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    with reads_no_catalogue():
        response = _get(client, url, domain_a)
    assert response.status_code == 200
    assert "Apply to" not in response.content.decode()


def test_a_russian_programme_shows_the_full_notice(
    client, agency_a, domain_a, membership_a, user_a, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        programme.country_code = "RU"
        programme.save(update_fields=["country_code"])
        app = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    with reads_no_catalogue():
        body = _get(client, f"/student/applications/{app.id}/", domain_a).content.decode()
    assert "Before you apply to a programme in Russia" in body
    assert "This is general information as of" in body


def test_a_lone_scholarship_page_shows_its_own_funding(
    client, agency_a, domain_a, membership_a, user_a, pack
):
    _, award = pack
    with tenant_scope(agency_a.id):
        app = add_card(agency_a, membership_a, award)
    client.force_login(user_a)
    with reads_no_catalogue():
        response = _get(client, f"/student/applications/{app.id}/", domain_a)
    body = response.content.decode()
    assert response.status_code == 200
    assert "934 EUR a month" in body and "2026-11-15" in body
    assert "No scholarship found" not in body


def test_an_assigned_counselor_cannot_tell_another_students_application_from_an_invented_id(
    client, agency_a, domain_a, membership_a, counselor_user, counselor_membership, pack
):
    programme, _ = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a,
            user=get_user_model().objects.create_user(username="student-a3"),
            role=Membership.Role.STUDENT,
        )
        theirs = add_card(agency_a, other, programme)
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    base = f"/counselor/students/{membership_a.id}/applications"
    with reads_no_catalogue():
        unassigned = _get(client, f"{base}/{theirs.id}/", domain_a)
        unassigned_invented = _get(client, f"{base}/{uuid4()}/", domain_a)
    assert unassigned.status_code == 404
    _same_response(unassigned, unassigned_invented)
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    with reads_no_catalogue():
        real = _get(client, f"{base}/{theirs.id}/", domain_a)
        invented = _get(client, f"{base}/{uuid4()}/", domain_a)
    assert real.status_code == 404
    _same_response(real, invented)
