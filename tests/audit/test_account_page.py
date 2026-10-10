import pytest
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_the_account_page_asks_for_a_reason_from_the_list(client, domain_a, user_a, membership_a):
    client.force_login(user_a)
    body = client.get("/student/settings/account/", HTTP_HOST=domain_a.host).content.decode()
    assert 'action="/student/account/delete/"' in body
    assert '<label for="deletion-reason">' in body
    for value, _label in DeletionRequest.Reason.choices:
        assert f'value="{value}"' in body


def test_the_waiting_page_offers_restore(client, agency_a, domain_a, user_a, membership_a):
    with tenant_scope(agency_a.id):
        record = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="APPROVED", reason="OTHER",
            execute_after=timezone.now(),
        )
    client.force_login(user_a)
    body = client.get("/student/account/deletion/", HTTP_HOST=domain_a.host).content.decode()
    assert "Skip to content" in body
    assert f'action="/student/account/restore/{record.id}/"' in body
    assert 'action="/accounts/logout/"' in body


def test_an_acceptance_locked_student_can_still_start_erasure(
    client, agency_a, domain_a, user_a, membership_a, monkeypatch
):
    from apps.privacy import acceptance

    monkeypatch.setattr(acceptance, "needs_acceptance", lambda _membership: True)
    client.force_login(user_a)
    page = client.get("/student/settings/account/", HTTP_HOST=domain_a.host)
    assert page.status_code == 200
    response = client.post(
        "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.filter(student=membership_a).exists()


def test_other_settings_pages_stay_behind_the_acceptance_lock(
    client, domain_a, user_a, membership_a, monkeypatch
):
    from apps.privacy import acceptance

    monkeypatch.setattr(acceptance, "needs_acceptance", lambda _membership: True)
    client.force_login(user_a)
    for path in (
        "/student/settings/",
        "/student/settings/mailbox/",
        "/student/settings/extension/",
    ):
        assert client.get(path, HTTP_HOST=domain_a.host)["Location"] == "/privacy/accept/"
