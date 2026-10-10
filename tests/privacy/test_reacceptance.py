import pytest
from django.urls import reverse

from apps.privacy import acceptance, documents
from apps.privacy.forms import CONSENT_TEXT
from apps.privacy.models import Acceptance
from apps.tenancy.context import tenant_scope


@pytest.fixture
def accepted(membership_a):
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)
    with tenant_scope(membership_a.tenant_id):
        acceptance.record(
            membership_a,
            acceptance.documents_to_accept(membership_a.tenant_id, "en"),
            surface="signup",
            language="en",
        )
    return membership_a


def _consent(tenant_id, language="en"):
    """What the accept page POSTs: the tick and the ids of the documents it showed."""
    docs = acceptance.documents_to_accept(tenant_id, language)
    return {"consent": "on", "documents": [str(doc.id) for doc in docs]}


@pytest.mark.django_db
def test_a_material_change_redirects_every_page_to_reacceptance(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302 and response["Location"] == reverse("privacy-accept")


@pytest.mark.django_db
def test_legal_pages_and_deletion_pages_stay_reachable(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    legal = client.get(reverse("privacy-legal", args=["terms"]), HTTP_HOST=domain_a.host)
    assert legal.status_code == 200
    response = client.get(reverse("privacy-accept"), HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert CONSENT_TEXT in response.content.decode()


@pytest.mark.django_db
def test_reaccepting_lifts_the_lock(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    response = client.post(
        reverse("privacy-accept"), _consent(accepted.tenant_id), HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(accepted.tenant_id):
        assert not acceptance.needs_acceptance(accepted)


@pytest.mark.django_db
def test_reaccept_without_the_tick_keeps_the_lock(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    assert client.post(reverse("privacy-accept"), {}, HTTP_HOST=domain_a.host).status_code == 400
    with tenant_scope(accepted.tenant_id):
        assert acceptance.needs_acceptance(accepted)


@pytest.mark.django_db
def test_erasure_and_logout_are_never_locked(client, user_a, domain_a, accepted):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    accept_url = reverse("privacy-accept")
    paths = [
        "/student/account/delete/",
        "/student/account/deletion/",
        "/student/account/restore/00000000-0000-0000-0000-000000000000/",
        "/api/auth/logout",
    ]
    for path in paths:
        for method in (client.get, client.post):
            response = method(path, HTTP_HOST=domain_a.host)
            assert not (response.status_code == 302 and response["Location"] == accept_url), path


@pytest.mark.django_db
def test_reaccepting_a_fallback_document_records_its_own_language(
    client, user_a, domain_a, membership_a
):
    # Terms exist only in English, the notice also in Azerbaijani: a student who
    # signed up in "az" is shown the English terms as the fallback.
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)
    documents.publish("privacy_notice_agency", "az", "notice az v1", material=True)
    with tenant_scope(membership_a.tenant_id):
        acceptance.record(
            membership_a,
            acceptance.documents_to_accept(membership_a.tenant_id, "az"),
            surface="signup",
            language="az",
        )
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    client.post(
        reverse("privacy-accept"), _consent(membership_a.tenant_id, "az"), HTTP_HOST=domain_a.host
    )
    with tenant_scope(membership_a.tenant_id):
        row = Acceptance.objects.select_related("document").get(
            student=membership_a, surface="reacceptance", document__kind="terms"
        )
    assert row.language == row.document.language == "en"


@pytest.mark.django_db
def test_reaccepting_a_version_that_was_replaced_meanwhile_is_refused(
    client, user_a, domain_a, accepted
):
    documents.publish("terms", "en", "terms v2", material=True)
    client.force_login(user_a)
    shown = _consent(accepted.tenant_id)
    documents.publish("terms", "en", "terms v3", material=True)
    response = client.post(reverse("privacy-accept"), shown, HTTP_HOST=domain_a.host)
    assert response.status_code == 400
    assert not Acceptance._base_manager.filter(surface="reacceptance").exists()
    with tenant_scope(accepted.tenant_id):
        assert acceptance.needs_acceptance(accepted)
