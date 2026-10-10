"""Four routes. The interesting assertions are about the ones that refuse."""

from __future__ import annotations

import json

import pytest
from django.core import signing
from django.urls import reverse

from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db
def test_connect_redirects_to_the_provider_with_a_signed_state(student_client) -> None:
    client, _student = student_client
    response = client.get(reverse("mailbox-connect", args=["GOOGLE"]) + "?tier=CONTENT")

    assert response.status_code == 302
    assert response["Location"].startswith("https://accounts.google.com/")
    assert "state=" in response["Location"]


@pytest.mark.django_db
def test_an_anonymous_visitor_cannot_start_a_connection(client, domain_a) -> None:
    client.defaults["HTTP_HOST"] = domain_a.host
    response = client.get(reverse("mailbox-connect", args=["GOOGLE"]))
    assert response.status_code in (302, 403)
    assert "accounts.google.com" not in response.get("Location", "")


@pytest.mark.django_db
def test_the_callback_refuses_a_state_it_did_not_sign(student_client) -> None:
    client, _student = student_client
    response = client.get(
        reverse("mailbox-callback", args=["GOOGLE"]) + "?code=c&state=forged"
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_the_callback_refuses_another_student_s_state(student_client, second_student) -> None:
    """The state is signed by this server, so a forged one is caught by the
    signature. A REPLAYED one is not: a student who starts a connection and
    hands the URL to someone else must not connect that person's mailbox to
    their own account."""
    client, _student = student_client
    state = signing.dumps(
        {"membership": str(second_student.id), "provider": "GOOGLE", "tier": "CONTENT"}
    )

    response = client.get(reverse("mailbox-callback", args=["GOOGLE"]) + f"?code=c&state={state}")

    assert response.status_code == 400
    with tenant_scope(second_student.tenant_id):
        assert MailboxConnection.objects.count() == 0


@pytest.mark.django_db
def test_a_transient_exchange_failure_answers_retryable_and_stores_no_connection(
    student_client, monkeypatch
) -> None:
    """A 429/5xx or a transport error exchanging the code is the provider's
    passing problem, not the student's -- the callback must answer something
    the student can retry, never a 500 and never a stored connection row."""
    from apps.mailbox.oauth import GrantUnavailable

    def _flaky(*, provider, code):
        raise GrantUnavailable("token endpoint answered 503", status=503)

    monkeypatch.setattr("apps.mailbox.views.exchange_code", _flaky)

    client, student = student_client
    state = signing.dumps(
        {"membership": str(student.id), "provider": "GOOGLE", "tier": "CONTENT"}
    )

    response = client.get(reverse("mailbox-callback", args=["GOOGLE"]) + f"?code=c&state={state}")

    assert response.status_code == 503
    assert response.json()["reason"] != "grant_refused"
    with tenant_scope(student.tenant_id):
        assert MailboxConnection.objects.count() == 0


@pytest.mark.django_db
def test_a_successful_callback_stores_the_grant_and_the_address(
    student_client, fake_exchange
) -> None:
    client, student = student_client
    state = signing.dumps(
        {"membership": str(student.id), "provider": "GOOGLE", "tier": "CONTENT"}
    )

    response = client.get(reverse("mailbox-callback", args=["GOOGLE"]) + f"?code=c&state={state}")

    assert response.status_code == 302
    with tenant_scope(student.tenant_id):
        connection = MailboxConnection.objects.get()
        assert connection.address == "student@gmail.test"
        assert connection.tier == MailboxConnection.Tier.CONTENT
    student.refresh_from_db()
    assert student.application_email == "student@gmail.test"


@pytest.mark.django_db
def test_revoking_destroys_the_grant_and_keeps_the_signals(
    student_client, connection_with_pack, fake_secrets
) -> None:
    client, _student = student_client
    response = client.post(reverse("mailbox-revoke", args=[connection_with_pack.id]))

    assert response.status_code == 200
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.status == MailboxConnection.Status.REVOKED
    assert connection_with_pack.revoked_at is not None
    assert fake_secrets.store == {}


@pytest.mark.django_db
def test_revoking_one_provider_does_not_touch_the_other(
    student_client, two_connections_with_pack, fake_secrets
) -> None:
    """A student with a GOOGLE and a MICROSOFT connection revoking one must
    not silently lose the other's grant too -- delete_student_mailbox_tokens's
    default (no provider) walks every provider, which is correct for
    advance_deletion's erasure sweep but wrong for revoking a single
    connection."""
    from apps.mailbox.secrets import secret_id, store_refresh_token

    client, student = student_client
    google, microsoft = two_connections_with_pack
    store_refresh_token(
        tenant_id=student.tenant_id,
        student_id=student.id,
        provider="GOOGLE",
        refresh_token="rt-google",
        client=fake_secrets,
    )
    store_refresh_token(
        tenant_id=student.tenant_id,
        student_id=student.id,
        provider="MICROSOFT",
        refresh_token="rt-microsoft",
        client=fake_secrets,
    )

    response = client.post(reverse("mailbox-revoke", args=[google.id]))

    assert response.status_code == 200
    assert secret_id(student.tenant_id, student.id, "GOOGLE") not in fake_secrets.store
    assert secret_id(student.tenant_id, student.id, "MICROSOFT") in fake_secrets.store
    microsoft.refresh_from_db()
    assert microsoft.status == MailboxConnection.Status.ACTIVE


@pytest.mark.django_db
def test_a_student_cannot_revoke_someone_else_s_connection(
    second_student_client, connection_with_pack
) -> None:
    client = second_student_client
    response = client.post(reverse("mailbox-revoke", args=[connection_with_pack.id]))

    assert response.status_code == 404
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.status == MailboxConnection.Status.ACTIVE


@pytest.mark.django_db
def test_narrowing_the_tier_needs_no_new_grant(student_client, connection_with_pack) -> None:
    client, _student = student_client
    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]),
        data=json.dumps({"tier": "METADATA"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.tier == MailboxConnection.Tier.METADATA


@pytest.mark.django_db
def test_widening_the_tier_sends_the_student_back_to_the_provider(
    student_client, connection_with_pack
) -> None:
    """METADATA -> CONTENT is a different scope. Flipping the column would
    leave a row claiming access the grant does not carry, and the next body
    fetch would 403 with nothing saying why."""
    client, _student = student_client
    connection_with_pack.tier = MailboxConnection.Tier.METADATA
    connection_with_pack.save(update_fields=["tier"])

    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]),
        data=json.dumps({"tier": "CONTENT"}),
        content_type="application/json",
    )

    assert response.status_code == 409
    assert json.loads(response.content)["reason"] == "reconnect_required"
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.tier == MailboxConnection.Tier.METADATA


def test_a_provider_not_offered_in_the_pilot_is_refused(settings, student_client) -> None:
    settings.MAILBOX_PROVIDERS = ("MICROSOFT",)
    client, _student = student_client

    response = client.get(reverse("mailbox-connect", args=["GOOGLE"]))

    assert response.status_code == 400
    assert response.json() == {"reason": "provider_unavailable"}


def test_an_unknown_inbox_kind_is_refused(settings, student_client) -> None:
    settings.MAILBOX_PROVIDERS = ("MICROSOFT",)
    client, _student = student_client

    response = client.get(reverse("mailbox-connect", args=["MICROSOFT"]) + "?kind=OTHER")

    assert response.status_code == 400
    assert response.json() == {"reason": "unknown_kind"}


def test_connect_without_an_oauth_client_says_so_instead_of_redirecting(
    student_client, settings
) -> None:
    settings.GOOGLE_OAUTH_CLIENT_ID = ""
    client, _student = student_client
    response = client.get(
        reverse("mailbox-connect", args=["GOOGLE"]) + "?tier=CONTENT",
        HTTP_ACCEPT="text/html",
    )
    assert response.status_code in {302, 400}
    assert "accounts.google.com" not in response.get("Location", "")
