import pytest


@pytest.mark.django_db
def test_unknown_host_fails_before_tenant_access(client) -> None:
    response = client.get("/", HTTP_HOST="unknown.example.test")
    assert response.status_code == 400


@pytest.mark.django_db
def test_unverified_host_fails_closed(client, unverified_domain) -> None:
    response = client.get("/", HTTP_HOST=unverified_domain.host)
    assert response.status_code == 400


@pytest.mark.django_db
def test_verified_host_allows_anonymous_page(client, domain_a) -> None:
    response = client.get("/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/"


@pytest.mark.django_db
def test_matching_membership_is_allowed(client, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    response = client.get("/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/student/"


@pytest.mark.django_db
def test_host_membership_mismatch_is_forbidden(client, domain_b, user_a, membership_a) -> None:
    client.force_login(user_a)
    response = client.get("/", HTTP_HOST=domain_b.host)
    assert response.status_code == 403
