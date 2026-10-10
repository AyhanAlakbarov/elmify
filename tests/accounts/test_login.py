"""The HTML login and logout: the JSON door's limiter, one refusal sentence."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from apps.audit.models import DeletionRequest
from apps.portals.pairing import issue_pairing_code, redeem_pairing_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from config.urls import index

pytestmark = pytest.mark.django_db

LOGIN = "/accounts/login/"
LOGOUT = "/accounts/logout/"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def student(agency_a):
    user = get_user_model().objects.create_user(username="amina", password="correct-horse-battery")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.STUDENT)
    return user


def test_the_login_page_labels_both_fields(client, domain_a) -> None:
    response = client.get(LOGIN, HTTP_HOST=domain_a.host)
    body = response.content.decode()
    assert response.status_code == 200
    assert '<label for="id_username">' in body
    assert '<label for="id_password">' in body
    assert "Skip to content" in body


def test_a_right_password_signs_in_and_lands_on_the_board(client, domain_a, student) -> None:
    response = client.post(
        LOGIN, {"username": "amina", "password": "correct-horse-battery"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    assert response["Location"] == "/"
    assert client.get("/", HTTP_HOST=domain_a.host)["Location"] == "/student/"


def test_a_wrong_password_says_one_sentence(client, domain_a, student) -> None:
    response = client.post(
        LOGIN, {"username": "amina", "password": "wrong"}, HTTP_HOST=domain_a.host
    )
    body = response.content.decode()
    assert response.status_code == 200
    assert 'role="alert"' in body
    assert "Wrong username or password." in body
    assert "_auth_user_id" not in client.session


def test_an_unknown_username_gets_the_same_sentence(client, domain_a) -> None:
    response = client.post(
        LOGIN, {"username": "nobody", "password": "wrong"}, HTTP_HOST=domain_a.host
    )
    assert "Wrong username or password." in response.content.decode()


def test_the_html_door_shares_the_json_door_s_limit(client, domain_a, student) -> None:
    for _ in range(10):
        client.post(
            "/api/auth/login",
            json.dumps({"username": "amina", "password": "wrong"}),
            content_type="application/json",
            HTTP_HOST=domain_a.host,
        )
    response = client.post(
        LOGIN, {"username": "amina", "password": "correct-horse-battery"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 429
    assert "Too many attempts" in response.content.decode()
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize("retry", [" amina", "ＡMINA"])
def test_spellings_of_one_account_share_one_bucket(client, domain_a, student, retry) -> None:
    for _ in range(10):
        client.post(LOGIN, {"username": "amina", "password": "wrong"}, HTTP_HOST=domain_a.host)
    response = client.post(
        LOGIN, {"username": retry, "password": "correct-horse-battery"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 429
    assert response["Retry-After"] == "900"
    assert "_auth_user_id" not in client.session


def test_a_successful_login_never_redirects_off_site(client, domain_a, student) -> None:
    response = client.post(
        LOGIN,
        {"username": "amina", "password": "correct-horse-battery", "next": "https://evil.example"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302
    assert response["Location"] == "/"


def test_an_anonymous_visitor_at_the_root_goes_to_login(client, domain_a) -> None:
    assert client.get("/", HTTP_HOST=domain_a.host)["Location"] == "/accounts/login/"


def test_a_counselor_at_the_root_goes_to_their_list(rf, agency_a) -> None:
    # Called directly: a real counsellor request first needs a verified MFA device,
    # which is the middleware's business, not the router's.
    user = get_user_model().objects.create_user(username="sam", password="pw-not-used-here")
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.COUNSELOR
        )
    request = rf.get("/")
    request.membership = membership  # type: ignore[attr-defined]
    assert index(request)["Location"] == "/counselor/"


def test_an_owner_at_the_root_goes_to_their_dashboard(rf, agency_a) -> None:
    user = get_user_model().objects.create_user(username="olu", password="pw-not-used-here")
    with tenant_scope(agency_a.id):
        membership = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.OWNER
        )
    request = rf.get("/")
    request.membership = membership  # type: ignore[attr-defined]
    assert index(request)["Location"] == "/owner/"


def test_a_protected_page_sends_an_anonymous_visitor_to_login(client, domain_a) -> None:
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/?next=/student/"


def test_logout_refuses_get(client, domain_a, student) -> None:
    client.force_login(student)
    assert client.get(LOGOUT, HTTP_HOST=domain_a.host).status_code == 405


def test_logout_ends_the_session_and_keeps_the_extension_paired(
    client, agency_a, domain_a, student
) -> None:
    with tenant_scope(agency_a.id):
        membership = Membership.objects.get(user=student)
        pairing, _token = redeem_pairing_code(issue_pairing_code(membership), "install-1")
    client.force_login(student)

    response = client.post(LOGOUT, HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    assert response["Location"] == "/accounts/login/"
    assert "_auth_user_id" not in client.session
    pairing.refresh_from_db()
    # Owner, 2026-10-04: logout keeps the extension paired; Settings disconnects.
    assert pairing.revoked_at is None
    assert pairing.token_hash != ""


def test_a_deletion_locked_student_can_still_log_out(client, agency_a, domain_a, student) -> None:
    with tenant_scope(agency_a.id):
        membership = Membership.objects.get(user=student)
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership, state="REQUESTED", reason="OTHER"
        )
    client.force_login(student)
    response = client.post(LOGOUT, HTTP_HOST=domain_a.host)
    assert response["Location"] == "/accounts/login/"
