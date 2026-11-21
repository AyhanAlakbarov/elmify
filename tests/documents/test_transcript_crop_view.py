"""Transcript plan 3a, task 5: a doubtful cell's picture, for the student and the people who may
read their files -- every one else, an unknown ref, or another agency's reading is a 404."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.audit.models import StaffFileAccess
from apps.concierge.documents import register
from apps.documents import storage
from apps.documents.models import TranscriptReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.conftest import reads_no_catalogue, verify_mfa_session

pytestmark = pytest.mark.django_db
CROP = b"\x89PNG a cell"


@pytest.fixture
def reading(agency_a, membership_a, fake_store, monkeypatch):
    monkeypatch.setattr(storage, "_object_store", lambda: fake_store)
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with tenant_scope(agency_a.id):
        reading = TranscriptReading.objects.create(
            student=membership_a, document=document, record={}
        )
        key = storage.crop_key(tenant_id=agency_a.id, student_id=membership_a.id,
                               reading_id=reading.id, ref="1:grade")
        storage.store_crop(key, CROP)
        reading.crops = {"1:grade": key}
        reading.save(update_fields=["crops"])
    return reading


def _get(client, user, host, reading_id, ref="1:grade"):
    client.force_login(user)
    verify_mfa_session(client, user)
    url = reverse("api-documents-transcript-crop", args=[reading_id, ref])
    return client.get(url, HTTP_HOST=host)


def _member(agency, username, role):
    user = get_user_model().objects.create_user(username=username)
    with tenant_scope(agency.id):
        return user, Membership.objects.create(tenant=agency, user=user, role=role)


def test_a_student_sees_their_own_crop(client, domain_a, user_a, reading):
    response = _get(client, user_a, domain_a.host, reading.id)
    assert response.status_code == 200 and response.content == CROP
    assert response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "no-store"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_another_student_gets_404(client, agency_a, domain_a, reading):
    user, _ = _member(agency_a, "student-a2", Membership.Role.STUDENT)
    assert _get(client, user, domain_a.host, reading.id).status_code == 404


def test_a_student_of_another_agency_gets_404(
    client, domain_b, user_b, membership_b, reading
):
    assert _get(client, user_b, domain_b.host, reading.id).status_code == 404


@pytest.mark.parametrize("ref", ["9:grade", "1:title", "x", "1:grade:x"])
def test_an_unknown_ref_gets_404(client, domain_a, user_a, reading, ref):
    assert _get(client, user_a, domain_a.host, reading.id, ref).status_code == 404


def test_the_assigned_counsellor_sees_it_and_an_unassigned_one_does_not(
    client, agency_a, domain_a, membership_a, counselor_user, counselor_membership, reading
):
    assert _get(client, counselor_user, domain_a.host, reading.id).status_code == 404
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a, active=True
        )
    assert _get(client, counselor_user, domain_a.host, reading.id).status_code == 200


def test_staff_see_it_and_the_view_is_recorded(client, agency_a, domain_a, membership_a, reading):
    user, staff = _member(agency_a, "elmify-staff", Membership.Role.PLATFORM_ADMIN)
    assert _get(client, user, domain_a.host, reading.id).status_code == 200
    row = StaffFileAccess._base_manager.get(document_id=reading.document_id)
    assert (row.staff_id, row.student_id, row.document_kind, row.action) == (
        staff.id, membership_a.id, "TRANSCRIPT_CROP", "VIEW"
    )


def test_the_view_reads_no_catalogue_table(client, agency_a, domain_a, reading):
    """It is a web route, and the web role holds no grant on the catalogue."""
    user, _ = _member(agency_a, "elmify-staff", Membership.Role.PLATFORM_ADMIN)
    with reads_no_catalogue():
        assert _get(client, user, domain_a.host, reading.id).status_code == 200
