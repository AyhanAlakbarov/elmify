import pytest

from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db
PAGE = "/student/settings/extension/"


def _paired(agency, membership, installation="laptop-1"):
    with tenant_scope(agency.id):
        pairing, _token = redeem_pairing_code(issue_pairing_code(membership), installation)
    return pairing


def test_the_page_lists_paired_browsers_and_how_to_pair(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    pairing = _paired(agency_a, membership_a)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "laptop-1" in body
    assert f'action="/student/settings/extension/{pairing.id}/disconnect/"' in body
    assert "How to pair" in body


def test_disconnect_revokes_the_pairing(client, agency_a, domain_a, user_a, membership_a) -> None:
    pairing = _paired(agency_a, membership_a)
    client.force_login(user_a)
    response = client.post(
        f"/student/settings/extension/{pairing.id}/disconnect/", HTTP_HOST=domain_a.host
    )
    assert response["Location"] == PAGE
    pairing.refresh_from_db()
    assert pairing.revoked_at is not None
    assert pairing.token_hash == ""


def test_another_students_pairing_is_404(
    client, agency_a, domain_a, user_a, membership_a, user_b
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
    pairing = _paired(agency_a, other)
    client.force_login(user_a)
    response = client.post(
        f"/student/settings/extension/{pairing.id}/disconnect/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404
    pairing.refresh_from_db()
    assert pairing.revoked_at is None


def test_disconnect_is_post_only(client, agency_a, domain_a, user_a, membership_a) -> None:
    pairing = _paired(agency_a, membership_a)
    client.force_login(user_a)
    response = client.get(
        f"/student/settings/extension/{pairing.id}/disconnect/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 405
