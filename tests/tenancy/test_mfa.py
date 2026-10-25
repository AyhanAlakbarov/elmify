"""Mandatory TOTP MFA enforcement for staff roles (owner/counselor/platform admin).

Closes the P1-mfa acceptance gate documented BLOCKED in
docs/validation/phase1-scorecard.md and docs/runbooks/shadow-pilot.md.
"""

import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership, SupportGrant
from tests.conftest import verify_mfa_session as _verify_session


@pytest.fixture
def owner_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="owner-a")


@pytest.fixture
def owner_membership(agency_a, owner_user):
    with tenant_scope(agency_a.id):
        return Membership.objects.create(
            tenant=agency_a, user=owner_user, role=Membership.Role.OWNER
        )


@pytest.fixture
def platform_admin_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="admin-a")


@pytest.fixture
def platform_admin_membership(agency_a, platform_admin_user):
    with tenant_scope(agency_a.id):
        return Membership.objects.create(
            tenant=agency_a, user=platform_admin_user, role=Membership.Role.PLATFORM_ADMIN
        )


@pytest.mark.django_db
def test_counselor_without_verified_device_is_denied(
    client, domain_a, counselor_user, counselor_membership
):
    client.force_login(counselor_user)
    response = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


@pytest.mark.django_db
def test_counselor_with_verified_device_is_allowed(
    client, domain_a, counselor_user, counselor_membership
):
    client.force_login(counselor_user)
    _verify_session(client, counselor_user)
    response = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200


@pytest.mark.django_db
def test_owner_without_verified_device_is_denied(client, domain_a, owner_user, owner_membership):
    client.force_login(owner_user)
    response = client.get("/owner/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


@pytest.mark.django_db
def test_owner_with_verified_device_is_allowed(client, domain_a, owner_user, owner_membership):
    client.force_login(owner_user)
    _verify_session(client, owner_user)
    response = client.get("/owner/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200


@pytest.mark.django_db
def test_platform_admin_without_verified_device_is_denied(
    client, domain_a, platform_admin_user, platform_admin_membership
):
    client.force_login(platform_admin_user)
    response = client.get("/admin/support-grant/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


@pytest.mark.django_db
def test_platform_admin_with_verified_device_is_allowed(
    client, domain_a, agency_a, platform_admin_user, platform_admin_membership
):
    from datetime import timedelta

    from django.utils import timezone

    with tenant_scope(agency_a.id):
        SupportGrant.objects.create(
            tenant=agency_a,
            administrator=platform_admin_user,
            reason="billing investigation",
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
    client.force_login(platform_admin_user)
    _verify_session(client, platform_admin_user)
    response = client.get("/admin/support-grant/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200


@pytest.mark.django_db
def test_student_is_unaffected_by_mfa_gate(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200


@pytest.mark.django_db
def test_django_superuser_is_gated_even_with_a_student_membership(
    client, domain_a, user_a, membership_a
):
    """The gate keys off Django's staff flags too, not only the membership role.

    /admin/ exposes auth user and group management -- the most privileged
    surface in the app -- and STUDENT is not in _STAFF_MFA_ROLES, so a
    superuser holding a student membership would otherwise skip MFA entirely.
    """
    user_a.is_staff = True
    user_a.is_superuser = True
    user_a.save(update_fields=["is_staff", "is_superuser"])
    client.force_login(user_a)

    assert client.get("/student/", HTTP_HOST=domain_a.host).status_code == 403

    _verify_session(client, user_a)
    assert client.get("/student/", HTTP_HOST=domain_a.host).status_code == 200


@pytest.mark.django_db
def test_unverified_staff_can_reach_setup_page(
    client, domain_a, counselor_user, counselor_membership
):
    """The setup flow itself must not be caught by its own gate."""
    client.force_login(counselor_user)
    response = client.get("/mfa/setup/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200


@pytest.mark.django_db
def test_staff_can_self_enroll_a_device_and_then_pass_the_gate(
    client, domain_a, counselor_user, counselor_membership
):
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client.force_login(counselor_user)
    response = client.get("/mfa/setup/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200

    device = TOTPDevice.objects.get(user=counselor_user, confirmed=False)
    code = f"{totp(device.bin_key):06d}"
    response = client.post("/mfa/setup/", {"token": code}, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    device.refresh_from_db()
    assert device.confirmed is True

    dashboard = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert dashboard.status_code == 200


@pytest.mark.frontend
@pytest.mark.django_db
def test_staff_with_preexisting_confirmed_device_can_reverify_in_a_new_session(
    client, domain_a, counselor_user, counselor_membership
):
    """A confirmed TOTPDevice from a prior session must not lock a staff user
    out of every subsequent session (or of /mfa/setup/ itself): the setup page
    must always offer a token-entry form and accept a code to re-verify.
    """
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    device = TOTPDevice.objects.create(user=counselor_user, name="default", confirmed=True)

    client.force_login(counselor_user)

    # This session has never called otp_login -- the gated dashboard must
    # still be denied even though the device is confirmed.
    denied = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert denied.status_code == 403

    # The confirmed-device page must render a real token form, not a dead end.
    setup_page = client.get("/mfa/setup/", HTTP_HOST=domain_a.host)
    assert setup_page.status_code == 200
    assert b'name="token"' in setup_page.content

    code = f"{totp(device.bin_key):06d}"
    response = client.post("/mfa/setup/", {"token": code}, HTTP_HOST=domain_a.host)
    assert response.status_code == 302

    dashboard = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert dashboard.status_code == 200


@pytest.mark.django_db(transaction=True)
def test_mfa_verify_attempts_are_rate_limited(
    client, domain_a, counselor_user, counselor_membership
):
    """A 6-digit TOTP POST is a brute-force target; same limiter pattern as
    apps.ratelimit.pack_command_rate_limited
    (tests/funding/test_student_controls.py::test_pack_commands_are_rate_limited_per_student).
    """
    from django.core.cache import cache

    cache.clear()
    client.force_login(counselor_user)
    client.get("/mfa/setup/", HTTP_HOST=domain_a.host)  # creates the unconfirmed device

    for _ in range(10):
        response = client.post("/mfa/setup/", {"token": "000000"}, HTTP_HOST=domain_a.host)
        assert response.status_code == 200

    blocked = client.post("/mfa/setup/", {"token": "000000"}, HTTP_HOST=domain_a.host)
    assert blocked.status_code == 429


@pytest.mark.django_db
def test_a_staff_login_lands_on_the_code_screen_not_a_denied_page(
    client, domain_a, counselor_user, counselor_membership
):
    """LOGIN_REDIRECT_URL is "/": an unverified counsellor sent there got a bare
    403 with no way forward (found by the 2026-10-25 crawl). The bare host now
    sends them to the code screen; every other staff path still denies."""
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice

    device = TOTPDevice.objects.create(user=counselor_user, name="default", confirmed=True)
    client.force_login(counselor_user)

    landing = client.get("/", HTTP_HOST=domain_a.host)
    assert landing.status_code == 302
    assert landing["Location"] == "/mfa/setup/"
    assert client.get("/counselor/", HTTP_HOST=domain_a.host).status_code == 403

    verified = client.post(
        "/mfa/setup/", {"token": f"{totp(device.bin_key):06d}"}, HTTP_HOST=domain_a.host
    )
    assert verified["Location"] == "/"
    assert client.get("/", HTTP_HOST=domain_a.host)["Location"] == "/counselor/"


@pytest.mark.django_db
def test_the_denied_page_links_to_the_code_screen(
    client, domain_a, counselor_user, counselor_membership
):
    client.force_login(counselor_user)
    body = client.get("/counselor/", HTTP_HOST=domain_a.host).content.decode()
    assert 'href="/mfa/setup/"' in body
