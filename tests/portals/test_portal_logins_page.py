"""The student's own portal logins: shown on request after a password re-check,
and handed over for good with one button."""

from __future__ import annotations

import json
import logging

import botocore.exceptions
import pytest

from apps.funding.models import AuditEvent
from apps.portals import credentials
from apps.portals.credentials import secret_id
from apps.tenancy.context import tenant_scope
from tests.portals.test_credentials import FakeSecrets

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"
PASSWORD = "Gq7-xR2!mN8_vL4.kP9#wT3z"


@pytest.fixture
def fake(monkeypatch):
    store = FakeSecrets()
    monkeypatch.setattr(credentials, "_client", lambda client=None: store)
    return store


@pytest.fixture
def held(agency_a, membership_a, fake):
    from django.utils import timezone

    from apps.portals.models import PortalAccount

    with tenant_scope(agency_a.id):
        account = PortalAccount.objects.create(
            tenant=agency_a, student=membership_a, portal_host=HOST, tag="k3x9",
            address="leyla.apply+k3x9@outlook.com", password_held_at=timezone.now(),
        )
    fake.store[secret_id(agency_a.id, membership_a.id, HOST)] = json.dumps(
        {"username": account.address, "password": PASSWORD}
    )
    return account


def test_the_page_lists_the_login_and_hides_the_password(client, user_a, domain_a, held) -> None:
    client.force_login(user_a)
    page = client.get("/student/settings/portals/", HTTP_HOST=domain_a.host)
    assert page.status_code == 200
    body = page.content.decode()
    assert HOST in body and held.address in body
    assert PASSWORD not in body


def test_the_right_password_reveals_it_once_and_leaves_a_trail(
    client, user_a, domain_a, held, agency_a, user_a_password
) -> None:
    client.force_login(user_a)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert page.status_code == 200
    assert PASSWORD in page.content.decode()
    assert page["Cache-Control"] == "no-store"
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            event="portal.password_revealed", object_id=held.id
        ).count() == 1


def test_a_wrong_password_reveals_nothing(client, user_a, domain_a, held, agency_a) -> None:
    client.force_login(user_a)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/",
        {"password": "nope"},
        HTTP_HOST=domain_a.host,
    )
    assert PASSWORD not in page.content.decode()
    with tenant_scope(agency_a.id):
        assert not AuditEvent.objects.filter(event="portal.password_revealed").exists()


def test_a_secret_that_is_gone_clears_the_marker_instead_of_asking_to_retry(
    client, user_a, domain_a, held, agency_a, fake, user_a_password
) -> None:
    """Retrying cannot bring back a secret Secrets Manager says is gone."""
    fake.store.clear()
    client.force_login(user_a)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert "We do not hold a password for this portal." in page.content.decode()
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
        assert held.password_held_at is None
        assert not AuditEvent.objects.filter(event="portal.password_revealed").exists()


def test_guessing_is_rate_limited(client, user_a, domain_a, held, user_a_password) -> None:
    client.force_login(user_a)
    for _ in range(5):
        client.post(
            f"/student/settings/portals/{held.id}/reveal/",
            {"password": "nope"},
            HTTP_HOST=domain_a.host,
        )
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert page.status_code == 429
    assert PASSWORD not in page.content.decode()


def test_takeover_deletes_our_copy_and_stops_the_co_pilot(
    client, user_a, domain_a, held, agency_a, fake
) -> None:
    client.force_login(user_a)
    url = f"/student/settings/portals/{held.id}/takeover/"
    response = client.post(url, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert fake.store == {}
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
        assert held.student_managed_at is not None
        assert AuditEvent.objects.filter(
            event="portal.password_handed_over", object_id=held.id
        ).exists()


def test_another_student_s_account_is_404(
    client, domain_a, held, django_user_model, agency_a
) -> None:
    from apps.tenancy.models import Membership

    other = django_user_model.objects.create_user(username="other2", password="x")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=other, role=Membership.Role.STUDENT)
    client.force_login(other)
    assert client.post(
        f"/student/settings/portals/{held.id}/reveal/", {"password": "x"}, HTTP_HOST=domain_a.host
    ).status_code == 404
    assert client.post(
        f"/student/settings/portals/{held.id}/takeover/", HTTP_HOST=domain_a.host
    ).status_code == 404


class _Denied(FakeSecrets):
    """Secrets Manager refusing, with a message that names the secret as botocore's does."""

    def _deny(self, op: str, secret: str):
        raise botocore.exceptions.ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": f"not allowed on {secret}"}}, op
        )

    def get_secret_value(self, *, SecretId: str):
        self._deny("GetSecretValue", SecretId)

    def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool):
        self._deny("DeleteSecret", SecretId)


def _everything_logged(caplog) -> str:
    from logging import Formatter

    fmt = Formatter()
    return "\n".join(fmt.format(r) for r in caplog.records)


def test_a_failed_read_shows_nothing_and_logs_no_student_id(
    client, user_a, domain_a, held, agency_a, membership_a, user_a_password, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(credentials, "_client", lambda client=None: _Denied())
    caplog.set_level(logging.DEBUG)
    client.force_login(user_a)
    page = client.post(
        f"/student/settings/portals/{held.id}/reveal/",
        {"password": user_a_password},
        HTTP_HOST=domain_a.host,
    )
    assert page.status_code == 503
    assert "We could not read it just now" in page.content.decode()
    assert PASSWORD not in page.content.decode()
    with tenant_scope(agency_a.id):
        assert not AuditEvent.objects.filter(event="portal.password_revealed").exists()
    assert str(membership_a.id) not in _everything_logged(caplog)


def test_a_failed_delete_does_not_read_as_handed_over(
    client, user_a, domain_a, held, agency_a, membership_a, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(credentials, "_client", lambda client=None: _Denied())
    caplog.set_level(logging.DEBUG)
    client.force_login(user_a)
    url = f"/student/settings/portals/{held.id}/takeover/"
    response = client.post(url, HTTP_HOST=domain_a.host)
    assert response.status_code == 503
    assert "We could not remove it just now" in response.content.decode()
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
        assert held.student_managed_at is None
        assert not AuditEvent.objects.filter(event="portal.password_handed_over").exists()
    assert str(membership_a.id) not in _everything_logged(caplog)


def test_pressing_takeover_twice_hands_over_once(
    client, user_a, domain_a, held, agency_a, fake
) -> None:
    client.force_login(user_a)
    url = f"/student/settings/portals/{held.id}/takeover/"
    client.post(url, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        first = type(held).objects.get(pk=held.pk).student_managed_at

    assert client.post(url, HTTP_HOST=domain_a.host).status_code == 302

    with tenant_scope(agency_a.id):
        assert type(held).objects.get(pk=held.pk).student_managed_at == first
        assert AuditEvent.objects.filter(
            event="portal.password_handed_over", object_id=held.id
        ).count() == 1


def test_takeover_of_an_account_we_hold_nothing_for_changes_nothing(
    client, user_a, domain_a, agency_a, membership_a, fake
) -> None:
    # A hand-made POST: marking it the student's would block the co-pilot's
    # sign-up there for good, over a password we never had.
    from apps.portals.models import PortalAccount

    with tenant_scope(agency_a.id):
        account = PortalAccount.objects.create(
            tenant=agency_a, student=membership_a, portal_host=HOST, tag="k3x9",
            address="leyla.apply+k3x9@outlook.com",
        )
    client.force_login(user_a)

    client.post(f"/student/settings/portals/{account.id}/takeover/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        assert PortalAccount.objects.get(pk=account.pk).student_managed_at is None
        assert not AuditEvent.objects.filter(event="portal.password_handed_over").exists()
