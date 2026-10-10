"""Every student page is behind the deletion lock, and the acceptance lock once f7 lands."""

import pytest

from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db

#: Each page task appends its URL (Tasks 12-19).
STUDENT_PAGES = [
    "/student/",
    "/student/recommendation/",
    "/student/documents/",
    "/student/messages/",
    "/student/settings/",
    "/student/settings/mailbox/",
    "/student/settings/extension/",
    "/student/settings/account/",
    "/student/profile/",
    "/student/gap-interview/",
]
#: Erasure must stay reachable under the acceptance lock (GDPR).
ACCEPTANCE_EXEMPT_PAGES = {"/student/settings/account/"}


@pytest.fixture
def locked(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
        )


@pytest.mark.parametrize("path", STUDENT_PAGES)
def test_every_student_page_is_behind_the_deletion_lock(
    client, domain_a, user_a, membership_a, locked, path
) -> None:
    client.force_login(user_a)
    response = client.get(path, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/student/account/deletion/"


@pytest.mark.parametrize(
    "path", [p for p in STUDENT_PAGES if p not in ACCEPTANCE_EXEMPT_PAGES]
)
def test_every_student_page_is_behind_the_acceptance_lock(
    client, domain_a, user_a, membership_a, monkeypatch, path
) -> None:
    from apps.privacy import acceptance

    monkeypatch.setattr(acceptance, "needs_acceptance", lambda _membership: True)
    client.force_login(user_a)
    response = client.get(path, HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/privacy/accept/"


@pytest.mark.parametrize("path", STUDENT_PAGES)
def test_every_student_page_exists_for_an_unlocked_student(
    client, domain_a, user_a, membership_a, path
) -> None:
    """Without this, a renamed page leaves both lock tests passing against a dead path:
    the middleware redirects before the URL is ever resolved."""
    client.force_login(user_a)
    assert client.get(path, HTTP_HOST=domain_a.host).status_code == 200
