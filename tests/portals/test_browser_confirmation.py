"""A browser gets portal passwords only once the student has proved it is them:
a pairing made within minutes of typing their Elmify password, or a one-time
confirmation on Settings > Portal logins. A session alone is not that proof --
whoever holds a left-open dashboard could otherwise pair their own client and
read every portal password the reveal page guards with a password check."""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.funding.models import AuditEvent
from apps.portals import credentials
from apps.portals.models import ExtensionPairing
from apps.tenancy.context import tenant_scope
from tests.portals.test_credentials import FakeSecrets

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"


def _code_from_dashboard(client, domain) -> str:
    response = client.post("/api/extension/pairing-code", HTTP_HOST=domain.host)
    assert response.status_code == 201, response.content
    return response.json()["code"]


def _redeem(client, domain, code) -> str:
    response = client.post(
        "/ext/pair",
        data=json.dumps({"code": code, "installation_id": "install-1"}),
        content_type="application/json",
        HTTP_HOST=domain.host,
    )
    assert response.status_code == 201, response.content
    return response.json()["token"]


def _logged_in_ago(client, user, minutes: int) -> None:
    client.force_login(user)
    session = client.session
    session["authenticated_at"] = (timezone.now() - timedelta(minutes=minutes)).timestamp()
    session.save()


def _pairing(agency, membership) -> ExtensionPairing:
    with tenant_scope(agency.id):
        return ExtensionPairing.objects.get(membership=membership, redeemed_at__isnull=False)


def test_a_browser_paired_right_after_login_may_receive_passwords(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    client.force_login(user_a)  # the login itself is the proof
    _redeem(client, domain_a, _code_from_dashboard(client, domain_a))
    assert _pairing(agency_a, membership_a).passwords_allowed_at is not None


def test_a_browser_paired_from_an_old_session_may_not(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    _logged_in_ago(client, user_a, minutes=60)
    _redeem(client, domain_a, _code_from_dashboard(client, domain_a))
    assert _pairing(agency_a, membership_a).passwords_allowed_at is None


def test_a_session_that_never_recorded_its_login_may_not(
    client, agency_a, domain_a, membership_a, user_a
) -> None:
    client.force_login(user_a)
    session = client.session
    del session["authenticated_at"]
    session.save()
    _redeem(client, domain_a, _code_from_dashboard(client, domain_a))
    assert _pairing(agency_a, membership_a).passwords_allowed_at is None


def test_an_unconfirmed_browser_gets_no_password_and_none_is_made(
    client, agency_a, domain_a, membership_a, user_a, monkeypatch, settings
) -> None:
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address

    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    store = FakeSecrets()
    monkeypatch.setattr(credentials, "_client", lambda client=None: store)
    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        form = PortalForm.objects.create(
            portal_host=HOST, form_key=f"ext-{uuid4()}", form_url=f"https://{HOST}/personal"
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        portal_address(application)
    _logged_in_ago(client, user_a, minutes=60)
    token = _redeem(client, domain_a, _code_from_dashboard(client, domain_a))
    client.logout()

    response = client.post(
        f"/ext/applications/{application.id}/portal-login",
        data=json.dumps({"page": "signup", "host": HOST}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_HOST=domain_a.host,
    )

    assert response.status_code == 409
    assert response.json() == {"error": "browser_unconfirmed"}
    assert store.store == {}


@pytest.fixture
def unconfirmed(client, agency_a, domain_a, membership_a, user_a, user_a_password):
    # user_a_password first: setting a password ends every session made before it.
    _logged_in_ago(client, user_a, minutes=60)
    _redeem(client, domain_a, _code_from_dashboard(client, domain_a))
    return _pairing(agency_a, membership_a)


def test_the_page_names_a_browser_waiting_for_confirmation(client, domain_a, unconfirmed) -> None:
    body = client.get("/student/settings/portals/", HTTP_HOST=domain_a.host).content.decode()
    assert f"/student/settings/portals/browsers/{unconfirmed.id}/allow/" in body


def test_the_right_password_allows_the_browser_and_leaves_a_trail(
    client, agency_a, domain_a, unconfirmed, user_a_password
) -> None:
    response = client.post(
        f"/student/settings/portals/browsers/{unconfirmed.id}/allow/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        unconfirmed.refresh_from_db()
        assert unconfirmed.passwords_allowed_at is not None
        assert AuditEvent.objects.filter(
            event="portal.browser_allowed", object_id=unconfirmed.id
        ).exists()


def test_a_wrong_password_allows_nothing(client, agency_a, domain_a, unconfirmed) -> None:
    response = client.post(
        f"/student/settings/portals/browsers/{unconfirmed.id}/allow/",
        {"password": "not it"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 200
    assert "That is not your Elmify password." in response.content.decode()
    with tenant_scope(agency_a.id):
        unconfirmed.refresh_from_db()
        assert unconfirmed.passwords_allowed_at is None


def test_another_student_s_browser_is_404(
    client, agency_a, domain_a, unconfirmed, django_user_model
) -> None:
    from apps.tenancy.models import Membership

    other = django_user_model.objects.create_user(username="other3", password="x")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=other, role=Membership.Role.STUDENT)
    client.force_login(other)
    response = client.post(
        f"/student/settings/portals/browsers/{unconfirmed.id}/allow/",
        {"password": "x"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 404


def test_a_revoked_browser_cannot_be_allowed(
    client, agency_a, domain_a, unconfirmed, user_a_password
) -> None:
    with tenant_scope(agency_a.id):
        ExtensionPairing.objects.filter(pk=unconfirmed.pk).update(revoked_at=timezone.now())
    response = client.post(
        f"/student/settings/portals/browsers/{unconfirmed.id}/allow/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 404
