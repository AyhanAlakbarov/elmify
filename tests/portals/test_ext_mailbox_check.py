"""A portal says "check your email": the extension asks, and the mailbox worker checks.

The web tier queues the sync and never runs it (security review M1): reading a
stored grant needs secretsmanager:GetSecretValue, which WebTaskRole does not
hold, and a sync run here would read AccessDenied as a lost grant and flip the
student's connection to ERROR.
"""

import pytest
from django.core.cache import cache

from apps.mailbox import push
from apps.mailbox import secrets as mailbox_secrets
from apps.mailbox import sync as sync_module
from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db

CHECK = "/ext/mailbox/check"


@pytest.fixture(autouse=True)
def _clear_limits():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def queued(monkeypatch):
    sent: list[tuple[str, object]] = []
    monkeypatch.setattr(
        push, "enqueue_work", lambda kind, connection, **_: sent.append((kind, connection.id))
    )

    def _never(*_args, **_kwargs):
        raise AssertionError("the web tier must never sync or read a stored grant")

    monkeypatch.setattr(sync_module, "sync_connection", _never)
    monkeypatch.setattr(mailbox_secrets, "refresh_token_for", _never)
    return sent


def _connection(agency, membership, **fields):
    with tenant_scope(agency.id):
        return MailboxConnection.objects.create(
            tenant=agency,
            membership=membership,
            provider=fields.pop("provider", MailboxConnection.Provider.MICROSOFT),
            address=fields.pop("address", "leyla@outlook.test"),
            **fields,
        )


def _check(client, domain, token):
    return client.post(CHECK, HTTP_HOST=domain.host, HTTP_AUTHORIZATION=f"Bearer {token}")


def test_a_paired_extension_queues_a_sync_of_its_own_student_and_never_syncs_here(
    client, agency_a, membership_a, domain_a, queued
):
    connection = _connection(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _check(client, domain_a, token)

    assert response.status_code == 202
    assert response.json() == {"queued": 1}
    assert queued == [("sync", connection.id)]


def test_no_token_is_refused(client, domain_a):
    assert client.post(CHECK, HTTP_HOST=domain_a.host).status_code == 401


def test_another_students_token_does_not_queue_this_students_sync(
    client, agency_a, membership_a, agency_b, membership_b, domain_b, queued
):
    """A device token authenticates one membership only; it must not reach a
    MailboxConnection belonging to a different student (or a different tenant)."""
    _connection(agency_a, membership_a)
    other_token = _pair(client, agency_b, membership_b, domain_b)

    response = _check(client, domain_b, other_token)

    assert response.status_code == 202
    assert response.json() == {"queued": 0}
    assert queued == []


def test_a_revoked_connection_is_not_queued(client, agency_a, membership_a, domain_a, queued):
    _connection(agency_a, membership_a, status=MailboxConnection.Status.REVOKED)
    token = _pair(client, agency_a, membership_a, domain_a, installation="install-2")

    response = _check(client, domain_a, token)

    assert response.status_code == 202
    assert response.json() == {"queued": 0}
    assert queued == []


def test_a_connection_already_disconnected_says_reconnect(
    client, agency_a, membership_a, domain_a, queued
):
    """A membership whose only connection is ERROR is told to reconnect, not to
    wait: nothing was queued, and nothing will arrive."""
    _connection(agency_a, membership_a, status=MailboxConnection.Status.ERROR)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _check(client, domain_a, token)

    assert response.status_code == 409
    assert response.json() == {"error": "mailbox_disconnected"}
    assert queued == []


def test_the_check_is_rate_limited_per_student_before_anything_is_queued(
    client, agency_a, membership_a, domain_a, queued
):
    connection = _connection(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    answers = [_check(client, domain_a, token).status_code for _ in range(sync_module.SYNC_LIMIT)]
    refused = _check(client, domain_a, token)

    assert answers == [202] * sync_module.SYNC_LIMIT
    assert refused.status_code == 429
    assert refused.json() == {"error": "rate_limited"}
    assert queued == [("sync", connection.id)] * sync_module.SYNC_LIMIT
