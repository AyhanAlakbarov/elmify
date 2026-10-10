"""The three moments a token exists, and what must not happen at any of them."""

from __future__ import annotations

import base64
import json
import logging
from urllib.parse import parse_qs, urlsplit

import botocore.exceptions  # type: ignore[import-untyped]
import pytest
import urllib3.exceptions
from django.test import override_settings

from apps.mailbox.oauth import (
    GrantRefused,
    GrantUnavailable,
    access_token_for,
    authorize_url,
    exchange_code,
)


def _id_token(email: str, *, verified: bool = True) -> str:
    """An unsigned JWT shaped like a provider's, for the fake token endpoint."""
    claims = {"email": email, "email_verified": verified}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeTokenHTTP:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.requests: list[tuple[str, dict[str, list[str]]]] = []

    def request(self, method, url, *, body=None, headers=None, timeout=None, **_):
        self.requests.append((url, parse_qs(body or "")))
        return _TokenResponse(self.status, self.payload)


class _TokenResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.data = json.dumps(payload).encode()


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="client-123",
    MAILBOX_OAUTH_REDIRECT_BASE="https://agency.example.test",
)
def test_the_authorize_url_asks_for_offline_access_and_carries_the_state() -> None:
    url = authorize_url(provider="GOOGLE", tier="CONTENT", state="opaque-state")

    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["state"] == ["opaque-state"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["https://agency.example.test/mailbox/callback/GOOGLE/"]
    assert "gmail.readonly" in query["scope"][0]
    assert "gmail.metadata" not in query["scope"][0]


def test_an_unknown_tier_or_provider_is_refused_before_a_url_exists() -> None:
    with pytest.raises(GrantRefused):
        authorize_url(provider="GOOGLE", tier="EVERYTHING", state="s")
    with pytest.raises(GrantRefused):
        authorize_url(provider="IMAP", tier="CONTENT", state="s")


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="client-123",
    GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
    MAILBOX_OAUTH_REDIRECT_BASE="https://agency.example.test",
)
def test_the_exchange_returns_the_address_and_the_refresh_token() -> None:
    http = FakeTokenHTTP(
        {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": _id_token("student@gmail.test"),
        }
    )

    grant = exchange_code(provider="GOOGLE", code="auth-code", http=http)

    assert grant.address == "student@gmail.test"
    assert grant.refresh_token == "rt"
    url, form = http.requests[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["auth-code"]


@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_an_unverified_google_address_is_refused() -> None:
    """Security review L1: the address becomes application_email, which tagged
    portal addresses are built on. Google says whether it verified it."""
    http = FakeTokenHTTP(
        {
            "access_token": "at",
            "refresh_token": "rt",
            "id_token": _id_token("someone.else@gmail.test", verified=False),
        }
    )

    with pytest.raises(GrantRefused):
        exchange_code(provider="GOOGLE", code="auth-code", http=http)


class _MicrosoftHTTP:
    """The token endpoint, then Graph's /me for the signed-in mailbox."""

    def __init__(self, me: dict[str, object], *, me_status: int = 200) -> None:
        self.me, self.me_status = me, me_status
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, url, *, body=None, headers=None, timeout=None, **_):
        self.calls.append((method, url, dict(headers or {})))
        if url.startswith("https://graph.microsoft.com/"):
            return _TokenResponse(self.me_status, self.me)
        return _TokenResponse(
            200,
            {
                "access_token": "graph-at",
                "refresh_token": "rt",
                # nOAuth: a hostile Entra tenant can make this claim say anything.
                "id_token": _id_token("victim@university.test"),
            },
        )


_MS = {"MICROSOFT_OAUTH_CLIENT_ID": "c", "MICROSOFT_OAUTH_CLIENT_SECRET": "s"}


@override_settings(**_MS)
def test_a_microsoft_address_comes_from_graph_never_the_email_claim() -> None:
    """Security review L1: Microsoft documents `email` as mutable and
    unverified; the mailbox Graph reads for this token is the one we hold."""
    http = _MicrosoftHTTP({"mail": "leyla@outlook.test", "userPrincipalName": "leyla@outlook.test"})

    grant = exchange_code(provider="MICROSOFT", code="auth-code", http=http)

    assert grant.address == "leyla@outlook.test"
    method, url, headers = http.calls[1]
    assert (method, urlsplit(url).netloc, urlsplit(url).path) == (
        "GET",
        "graph.microsoft.com",
        "/v1.0/me",
    )
    assert headers["Authorization"] == "Bearer graph-at"


@override_settings(**_MS)
def test_a_microsoft_mail_attribute_off_the_verified_domain_falls_back_to_the_upn() -> None:
    """`mail` can be set by a tenant's admin; the UPN's domain is one the tenant
    proved it owns. A `mail` on any other domain is not trusted."""
    http = _MicrosoftHTTP(
        {"mail": "victim@university.test", "userPrincipalName": "leyla@evil-tenant.test"}
    )

    grant = exchange_code(provider="MICROSOFT", code="auth-code", http=http)

    assert grant.address == "leyla@evil-tenant.test"


@override_settings(**_MS)
@pytest.mark.parametrize(
    ("me_status", "raised"), [(403, GrantRefused), (503, GrantUnavailable)]
)
def test_a_failed_graph_lookup_stores_nothing(me_status, raised) -> None:
    http = _MicrosoftHTTP({}, me_status=me_status)

    with pytest.raises(raised):
        exchange_code(provider="MICROSOFT", code="auth-code", http=http)


def test_microsoft_scopes_can_read_the_signed_in_user() -> None:
    from apps.mailbox.providers import SCOPES

    assert "User.Read" in SCOPES[("MICROSOFT", "METADATA")]
    assert "User.Read" in SCOPES[("MICROSOFT", "CONTENT")]


@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_grant_with_no_refresh_token_is_refused_rather_than_half_stored() -> None:
    """Google returns no refresh_token when the student has consented before and
    prompt=consent was dropped. A connection whose token cannot be refreshed
    works once and then fails silently at the next sync."""
    http = FakeTokenHTTP({"access_token": "at", "id_token": _id_token("s@gmail.test")})

    with pytest.raises(GrantRefused):
        exchange_code(provider="GOOGLE", code="auth-code", http=http)


@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_refused_exchange_logs_no_code_and_no_token(caplog) -> None:
    http = FakeTokenHTTP({"error": "invalid_grant"}, status=400)

    with caplog.at_level(logging.DEBUG), pytest.raises(GrantRefused) as raised:
        exchange_code(provider="GOOGLE", code="auth-code-secret", http=http)

    assert "auth-code-secret" not in str(raised.value)
    assert "auth-code-secret" not in caplog.text


class _Unreachable:
    """A transport that fails below HTTP: a reset, a timeout, a refused dial."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.requests: list[str] = []

    def request(self, method, url, **_kwargs):
        self.requests.append(url)
        raise self.error


@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_transport_failure_exchanging_a_code_is_not_a_grant_refusal() -> None:
    """A reset while exchanging the code is the provider's passing problem,
    never a reason to tell the student their grant is dead."""
    error = urllib3.exceptions.ProtocolError("connection reset secret-code")

    with pytest.raises(GrantUnavailable) as raised:
        exchange_code(provider="GOOGLE", code="auth-code-secret", http=_Unreachable(error))

    assert raised.value.status is None
    assert "secret-code" not in str(raised.value)
    assert "auth-code-secret" not in str(raised.value)


@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_a_transient_exchange_status_is_not_a_grant_refusal(status) -> None:
    http = FakeTokenHTTP({"error": "server_error"}, status=status)

    with pytest.raises(GrantUnavailable) as raised:
        exchange_code(provider="GOOGLE", code="auth-code", http=http)

    assert raised.value.status == status


class _FakeGrantSecrets:
    """A stored refresh token, for tests that must reach the real token call."""

    def get_secret_value(self, *, SecretId):
        return {"SecretString": json.dumps({"refresh_token": "rt"})}


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_a_transient_refresh_status_is_not_a_grant_refusal(connection, status) -> None:
    """The rule (brief): 408/429/5xx at the token endpoint is not now, never a
    lost grant -- sync.py must not flip the connection or raise a card for it."""
    http = FakeTokenHTTP({"error": "server_error"}, status=status)

    with pytest.raises(GrantUnavailable) as raised:
        access_token_for(connection, http=http, secrets_client=_FakeGrantSecrets())

    assert raised.value.status == status


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_transport_failure_refreshing_a_token_is_not_a_grant_refusal(connection) -> None:
    error = urllib3.exceptions.ReadTimeoutError(None, "/token", "read timed out")

    with pytest.raises(GrantUnavailable) as raised:
        access_token_for(connection, http=_Unreachable(error), secrets_client=_FakeGrantSecrets())

    assert raised.value.status is None


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
@pytest.mark.parametrize("status", [400, 401, 403])
def test_a_real_grant_refusal_status_still_refuses_the_grant(connection, status) -> None:
    """400 (invalid_grant), 401 and 403 are unchanged: a real grant loss."""
    http = FakeTokenHTTP({"error": "invalid_grant"}, status=status)

    with pytest.raises(GrantRefused):
        access_token_for(connection, http=http, secrets_client=_FakeGrantSecrets())


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_an_access_token_is_minted_from_the_stored_refresh_token(connection) -> None:
    class FakeSecrets:
        def get_secret_value(self, *, SecretId):
            return {"SecretString": json.dumps({"refresh_token": "rt"})}

    http = FakeTokenHTTP({"access_token": "fresh-access-token"})

    token = access_token_for(connection, http=http, secrets_client=FakeSecrets())

    assert token == "fresh-access-token"
    _url, form = http.requests[0]
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["rt"]


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_missing_grant_refuses_rather_than_syncing_nothing(connection) -> None:
    class Empty:
        def get_secret_value(self, *, SecretId):
            raise KeyError(SecretId)

    with pytest.raises(GrantRefused):
        access_token_for(connection, http=FakeTokenHTTP({}), secrets_client=Empty())


class _RotatingSecrets:
    def __init__(self, fail: bool = False) -> None:
        self.puts: list[tuple[str, str]] = []
        self.fail = fail

    def get_secret_value(self, *, SecretId):
        return {"SecretString": json.dumps({"refresh_token": "rt"})}

    def put_secret_value(self, *, SecretId, SecretString):
        if self.fail:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "AccessDeniedException"}}, "PutSecretValue"
            )
        self.puts.append((SecretId, json.loads(SecretString)["refresh_token"]))


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_rotated_refresh_token_replaces_the_stored_one(connection) -> None:
    """Microsoft rotates it on every refresh and the held one dies at 90 days."""
    secrets = _RotatingSecrets()
    http = FakeTokenHTTP({"access_token": "at", "refresh_token": "rt-2"})

    access_token_for(connection, http=http, secrets_client=secrets)

    assert [token for _id, token in secrets.puts] == ["rt-2"]


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
@pytest.mark.parametrize(
    "payload", [{"access_token": "at"}, {"access_token": "at", "refresh_token": "rt"}]
)
def test_an_unrotated_refresh_writes_nothing(connection, payload) -> None:
    """Positive control: Google usually returns no new token, or the same one."""
    secrets = _RotatingSecrets()

    access_token_for(connection, http=FakeTokenHTTP(payload), secrets_client=secrets)

    assert secrets.puts == []


@pytest.mark.django_db
@override_settings(GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
def test_a_refused_rotation_write_still_syncs_and_logs_no_secret_name(connection, caplog) -> None:
    """The old token still works until it expires; the secret's name names the student."""
    http = FakeTokenHTTP({"access_token": "at", "refresh_token": "rt-2"})

    with caplog.at_level(logging.WARNING):
        token = access_token_for(connection, http=http, secrets_client=_RotatingSecrets(fail=True))

    assert token == "at"
    assert "rotated refresh token" in caplog.text
    assert "tehsil/mailbox" not in caplog.text
    assert "rt-2" not in caplog.text
