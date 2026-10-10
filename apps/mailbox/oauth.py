"""Authorize, exchange, refresh. The three moments a token exists here.

An access token is never stored -- it is minted from the refresh token at the
start of each sync and dropped when the sync ends. There is therefore nothing to
expire, nothing to cache and nothing to invalidate; the only durable credential
is the refresh token, and it lives in Secrets Manager (secrets.py).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import botocore.exceptions  # type: ignore[import-untyped]
import urllib3
from django.conf import settings

from apps.mailbox.models import MailboxConnection
from apps.mailbox.providers import (
    GOOGLE_AUTH_URL,
    GOOGLE_TOKEN_URL,
    MICROSOFT_API_ORIGIN,
    MICROSOFT_AUTH_URL,
    MICROSOFT_TOKEN_URL,
    SCOPES,
    ProviderError,
    _json,
)
from apps.mailbox.secrets import refresh_token_for, replace_refresh_token

logger = logging.getLogger(__name__)

_TIMEOUT = urllib3.Timeout(connect=5.0, read=15.0)

_AUTH_URLS = {"GOOGLE": GOOGLE_AUTH_URL, "MICROSOFT": MICROSOFT_AUTH_URL}
_TOKEN_URLS = {"GOOGLE": GOOGLE_TOKEN_URL, "MICROSOFT": MICROSOFT_TOKEN_URL}

#: The token endpoint's own transient statuses -- a busy provider, not a dead
#: grant. sync.py's existing `error.status in (401, 403)` check already treats
#: anything else as "not lost", which is why this is a ProviderError subclass
#: rather than a second exception shape: the transient path providers._json
#: already built for listing handles this one for free.
_TRANSIENT_STATUSES = {408, 429}


class GrantRefused(Exception):
    """The grant cannot be completed. Never carries a code, a token or an address."""


class GrantUnavailable(ProviderError):
    """The token endpoint has a passing problem: retry later, do not ask to
    reconnect. Never carries a code, a token or an address -- same rule as
    GrantRefused."""


@dataclass(frozen=True)
class Grant:
    address: str
    refresh_token: str


def _credentials(provider: str) -> tuple[str, str]:
    if provider == "GOOGLE":
        return settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET
    if provider == "MICROSOFT":
        return settings.MICROSOFT_OAUTH_CLIENT_ID, settings.MICROSOFT_OAUTH_CLIENT_SECRET
    raise GrantRefused(f"no such provider: {provider}")


def redirect_uri(provider: str) -> str:
    return f"{settings.MAILBOX_OAUTH_REDIRECT_BASE.rstrip('/')}/mailbox/callback/{provider}/"


def authorize_url(*, provider: str, tier: str, state: str) -> str:
    """Where to send the student's browser.

    `access_type=offline` and `prompt=consent` are Google's way of saying "issue
    a refresh token"; without the second, a student who has consented before
    gets an access token only, and the connection dies at the next sync.
    """
    scopes = SCOPES.get((provider, tier))
    if scopes is None:
        raise GrantRefused(f"no scope for {provider}/{tier}")
    client_id, _secret = _credentials(provider)
    query = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(provider),
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_AUTH_URLS[provider]}?{urlencode(query)}"


def _post_form(url: str, form: dict[str, str], http: object | None) -> dict[str, object]:
    pool: Any = http if http is not None else urllib3.PoolManager()
    try:
        response = pool.request(
            "POST",
            url,
            body=urlencode(form),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            timeout=_TIMEOUT,
            preload_content=True,
        )
    except urllib3.exceptions.HTTPError as error:
        # A reset, a timeout, a refused dial -- not now, never a lost grant.
        # Host and class only, and not chained: urllib3's own message can
        # quote the URL (matches providers._json's I1 fix).
        host = urlsplit(url).hostname
        raise GrantUnavailable(
            f"token endpoint could not reach {host} ({type(error).__name__})"
        ) from None
    if response.status in _TRANSIENT_STATUSES or 500 <= response.status < 600:
        # Not a lost grant: sync.py must leave the connection ACTIVE and raise
        # no reconnect card for this. Only the status is safe to repeat.
        raise GrantUnavailable(
            f"token endpoint answered {response.status}", status=response.status
        )
    if response.status != 200:
        # 400 (invalid_grant), 401, 403 and anything else unlisted above: a
        # real grant loss. Only the status is safe to repeat.
        raise GrantRefused(f"token endpoint answered {response.status}")
    try:
        payload = json.loads(response.data)
    except json.JSONDecodeError as error:
        raise GrantRefused("token endpoint answered with malformed JSON") from error
    if not isinstance(payload, dict):
        raise GrantRefused("token endpoint answered with an unexpected shape")
    return payload


def _address_from_id_token(id_token: str) -> str:
    """Google's `email` claim, and only when Google says it verified it.

    Read without verifying the signature. That is sound here and only here:
    the token came back on our own direct, TLS-authenticated POST to the
    provider's token endpoint, which OpenID Connect Core §3.1.3.7 lists as the
    case where signature validation may be skipped. It would NOT be sound for
    a token arriving through the browser.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        return ""
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "==="))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(claims, dict) or claims.get("email_verified") is not True:
        return ""
    return str(claims.get("email", ""))


def _graph_address(access_token: str, http: object | None) -> str:
    """The signed-in Microsoft mailbox's address, from Graph, never the id_token.

    Microsoft documents the `email` claim as mutable and unverified -- the
    nOAuth class (security review L1). The UPN's domain is one the tenant
    proved it owns (for a personal account, the account's own sign-in
    address); `mail` is taken only on that same domain, because a tenant's
    admin can set it to anything. A guest's `#EXT#` UPN names no mailbox.
    """
    pool: Any = http if http is not None else urllib3.PoolManager()
    try:
        me = _json(
            pool,
            "GET",
            f"{MICROSOFT_API_ORIGIN}/v1.0/me?$select=mail,userPrincipalName",
            access_token=access_token,
            provider="MICROSOFT",
        )
    except ProviderError as error:
        if error.status in (401, 403):
            raise GrantRefused(f"Graph answered {error.status}") from None
        raise GrantUnavailable(str(error), status=error.status) from None
    upn, mail = me.get("userPrincipalName"), me.get("mail")
    if not isinstance(upn, str) or "@" not in upn or "#EXT#" in upn.upper():
        return ""
    domain = upn.rpartition("@")[2].casefold()
    if isinstance(mail, str) and mail.rpartition("@")[2].casefold() == domain:
        return mail.strip()
    return upn.strip()


def exchange_code(*, provider: str, code: str, http: object | None = None) -> Grant:
    client_id, client_secret = _credentials(provider)
    payload = _post_form(
        _TOKEN_URLS[provider],
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(provider),
        },
        http,
    )
    refresh = str(payload.get("refresh_token", ""))
    if not refresh:
        # Half a grant is worse than none: it syncs once and then fails
        # silently, and the student is told they are connected.
        raise GrantRefused("provider issued no refresh token")
    if provider == "MICROSOFT":
        address = _graph_address(str(payload.get("access_token", "")), http)
    else:
        address = _address_from_id_token(str(payload.get("id_token", "")))
    if not address:
        raise GrantRefused("provider issued no verified address")
    return Grant(address=address, refresh_token=refresh)


def access_token_for(
    connection: MailboxConnection,
    *,
    http: object | None = None,
    secrets_client: object | None = None,
) -> str:
    """Mint a short-lived access token. Never stored, never logged."""
    refresh = refresh_token_for(
        tenant_id=connection.tenant_id,
        student_id=connection.membership_id,
        provider=connection.provider,
        client=secrets_client,
    )
    if not refresh:
        raise GrantRefused(f"no stored grant for provider {connection.provider}")
    client_id, client_secret = _credentials(connection.provider)
    payload = _post_form(
        _TOKEN_URLS[connection.provider],
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        },
        http,
    )
    token = str(payload.get("access_token", ""))
    if not token:
        raise GrantRefused("token endpoint issued no access token")
    # Microsoft rotates the refresh token on every refresh, and the one we hold
    # stops working 90 days after it was issued however often it is used. Drop
    # the new one and every Outlook connection dies at three months.
    rotated = str(payload.get("refresh_token", ""))
    if rotated and rotated != refresh:
        try:
            replace_refresh_token(
                tenant_id=connection.tenant_id,
                student_id=connection.membership_id,
                provider=connection.provider,
                refresh_token=rotated,
                client=secrets_client,
            )
        except botocore.exceptions.ClientError:
            # The old token still works until it expires, so this sync goes on.
            # Logged without the error: botocore's message names the secret,
            # and the secret's name names the student.
            logger.warning(
                "could not store a rotated refresh token for connection %s", connection.id
            )
    return token
