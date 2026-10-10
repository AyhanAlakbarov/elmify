import pytest
from django.core import signing
from django.urls import reverse

from apps.mailbox.models import MailboxConnection
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db
PAGE = "/student/settings/mailbox/"


def test_the_page_lists_connections_and_offers_connect(
    student_client, connection_with_pack
) -> None:
    client, _student = student_client
    body = client.get(PAGE).content.decode()
    assert connection_with_pack.address in body
    assert f'action="{reverse("mailbox-revoke", args=[connection_with_pack.id])}"' in body
    assert 'name="tier"' in body and 'name="kind"' in body
    assert '<label for="tier-' in body


def test_a_browser_revoke_comes_back_to_the_page(
    student_client, connection_with_pack, fake_secrets
) -> None:
    client, _student = student_client
    response = client.post(
        reverse("mailbox-revoke", args=[connection_with_pack.id]), HTTP_ACCEPT="text/html"
    )
    assert response.status_code == 302
    assert response["Location"] == PAGE
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.status == MailboxConnection.Status.REVOKED


def test_a_browser_downgrade_reads_the_form(student_client, connection_with_pack) -> None:
    client, _student = student_client
    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]), {"tier": "METADATA"},
        HTTP_ACCEPT="text/html",
    )
    assert response["Location"] == PAGE
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.tier == MailboxConnection.Tier.METADATA


def test_a_browser_revoke_of_someone_else_s_connection_is_404(
    second_student_client, connection_with_pack
) -> None:
    response = second_student_client.post(
        reverse("mailbox-revoke", args=[connection_with_pack.id]), HTTP_ACCEPT="text/html"
    )
    assert response.status_code == 404


def test_the_callback_lands_on_the_mailbox_page(student_client, fake_exchange) -> None:
    client, student = student_client
    state = signing.dumps({"membership": str(student.id), "provider": "GOOGLE", "tier": "CONTENT"})
    response = client.get(reverse("mailbox-callback", args=["GOOGLE"]) + f"?code=c&state={state}")
    assert response["Location"] == PAGE
    with tenant_scope(student.tenant_id):
        assert MailboxConnection.objects.filter(membership=student).exists()


def test_the_callback_ignores_a_next_in_the_request(student_client, fake_exchange) -> None:
    client, student = student_client
    state = signing.dumps({"membership": str(student.id), "provider": "GOOGLE", "tier": "CONTENT"})
    response = client.get(
        reverse("mailbox-callback", args=["GOOGLE"])
        + f"?code=c&state={state}&next=https://evil.example/",
        HTTP_REFERER="https://evil.example/",
    )
    assert response["Location"] == PAGE


def test_a_browser_post_still_needs_the_csrf_token(
    student_client, connection_with_pack
) -> None:
    from django.test import Client

    client, student = student_client
    strict = Client(enforce_csrf_checks=True)
    strict.cookies = client.cookies
    response = strict.post(
        reverse("mailbox-revoke", args=[connection_with_pack.id]),
        HTTP_ACCEPT="text/html",
        HTTP_HOST=client.defaults.get("HTTP_HOST", "testserver"),
    )
    assert response.status_code == 403
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.status == MailboxConnection.Status.ACTIVE


def _errors(response) -> list[str]:
    from django.contrib.messages import get_messages

    return [str(m) for m in get_messages(response.wsgi_request) if m.level_tag == "error"]


def test_a_browser_widening_comes_back_with_the_reason(
    student_client, connection_with_pack
) -> None:
    """Task 17 minor: the HTML path of the 409, never raw JSON."""
    client, _student = student_client
    connection_with_pack.tier = MailboxConnection.Tier.METADATA
    connection_with_pack.save(update_fields=["tier"])
    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]), {"tier": "CONTENT"},
        HTTP_ACCEPT="text/html",
    )
    assert response["Location"] == PAGE
    assert _errors(response) == [
        "Reading more needs a new connection: disconnect and connect again."
    ]
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.tier == MailboxConnection.Tier.METADATA


def test_a_browser_unknown_tier_comes_back_with_an_error(
    student_client, connection_with_pack
) -> None:
    client, _student = student_client
    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]), {"tier": "EVERYTHING"},
        HTTP_ACCEPT="text/html",
    )
    assert response["Location"] == PAGE
    assert len(_errors(response)) == 1


def test_a_json_caller_labelled_text_plain_still_sets_the_tier(
    student_client, connection_with_pack
) -> None:
    import json

    client, _student = student_client
    response = client.post(
        reverse("mailbox-tier", args=[connection_with_pack.id]),
        data=json.dumps({"tier": "METADATA"}), content_type="text/plain",
    )
    assert response.status_code == 200
    connection_with_pack.refresh_from_db()
    assert connection_with_pack.tier == MailboxConnection.Tier.METADATA


@pytest.mark.parametrize("query", ["?tier=EVERYTHING", "?kind=EVERYTHING"])
def test_a_browser_connect_refusal_comes_back_to_the_page(student_client, query) -> None:
    client, _student = student_client
    response = client.get(
        reverse("mailbox-connect", args=["GOOGLE"]) + query, HTTP_ACCEPT="text/html"
    )
    assert response["Location"] == PAGE
    assert len(_errors(response)) == 1
