"""Graph push for Microsoft mailboxes: the trigger, never the only path.

Watch spec §3a. A Graph change notification says only that a message was
created in a mailbox we hold a subscription on. It carries an id, never
content, and it is read here as one instruction: sync this connection now. The
sync's own timestamp cursor does the rest, so a notification that was dropped,
delayed or duplicated changes nothing but when the sync runs -- and the
six-hourly sweep (sync_mailboxes) is the backstop for the dropped ones, as both
vendors say it must be.

Three rules hold the shape together:

- The webhook only enqueues. Graph wants a 202 within three seconds and drops
  notifications to a slow endpoint for good; a sync takes seconds to tens of
  seconds. So views.py verifies and enqueues, and the mailbox worker
  (run_mailbox_worker) calls handle_work.
- clientState is derived, never stored: an HMAC of the connection id under the
  Django secret key, compared in constant time. A notification that does not
  carry it is not ours to act on.
- Upkeep never raises for Graph or for a grant. A subscription that could not
  be created or renewed leaves the connection on the sweep, which is where
  every connection was before push existed; the sync that follows reports a
  lost grant itself. Infrastructure failures (no AWS endpoint, a database
  error) still raise, exactly as they do from sync_connection.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import urllib3
from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from apps.queue import SQSClient, enqueue
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import TenantDomain

from .models import MailboxConnection
from .oauth import GrantRefused, access_token_for
from .providers import _GRAPH_HEADERS, MICROSOFT_API_ORIGIN, ProviderError, _json
from .sync import PUSH_SYNC_BUCKET, PUSH_SYNC_LIMIT, SyncRefused, sync_connection

logger = logging.getLogger(__name__)

#: Where Graph posts, on the tenant's own verified host, so
#: HostTenantContextMiddleware selects the tenant and RLS applies as it does to
#: any request. urls.py routes these exact paths.
NOTIFICATION_PATH = "/mailbox/push/graph/"
LIFECYCLE_PATH = "/mailbox/push/graph/lifecycle/"

#: Graph's ceiling for an Outlook message subscription is 10,080 minutes. A
#: little under it, so a clock a few minutes fast on either side is not a 400.
SUBSCRIPTION_MINUTES = 10_000
#: Renewed once fewer than this remain. With the sweep every six hours, a
#: renewal that keeps failing still has eight more chances before it lapses.
RENEW_WITHIN = timedelta(days=2)
#: Everything in me/messages: Inbox and Junk alike, which sync reads apart.
RESOURCE = "me/messages"

#: What a Graph subscription id may look like before it touches a query or a
#: column: Graph issues GUIDs. Checked on what Graph sends us AND on what a
#: webhook caller claims, so neither a NUL byte (Postgres refuses it, a 500) nor
#: an over-long value (the column is 200) ever reaches the database.
_SUBSCRIPTION_ID = re.compile(r"[A-Za-z0-9-]{1,200}")


def valid_subscription_id(value: object) -> bool:
    return isinstance(value, str) and _SUBSCRIPTION_ID.fullmatch(value) is not None


class MailboxWork(BaseModel):
    """Identifiers only, like every message on every queue here: a queue is a
    durable store with its own retention, and a student's mail does not go
    into it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    #: "sync": a notification arrived. "subscribe": the subscription needs
    #: creating, renewing or recreating first (a new connection, or a lifecycle
    #: event), then a sync.
    kind: Literal["sync", "subscribe"]
    tenant_id: UUID
    connection_id: UUID


def client_state(connection_id: UUID) -> str:
    """The secret Graph echoes back on every notification for this connection.

    64 hex characters against Graph's 128 limit. Rotating SECRET_KEY changes
    every one of them, and a renewal PATCH cannot resend it (Graph updates only
    the expiry and the URL), so after a rotation push fails CLOSED -- every
    notification is ignored -- until each subscription is recreated. Clearing
    push_subscription_id on the Microsoft rows makes the next sweep recreate
    them; until then the sweep's own sync is what reads the mail.
    """
    return hmac.new(
        settings.SECRET_KEY.encode(), f"graph-push:{connection_id}".encode(), hashlib.sha256
    ).hexdigest()


def state_matches(connection_id: UUID, presented: object) -> bool:
    # Bytes, not str: compare_digest raises TypeError on a non-ASCII str, which
    # any caller could turn into a 500 by sending "é".
    return isinstance(presented, str) and hmac.compare_digest(
        client_state(connection_id).encode(), presented.encode()
    )


def push_host(tenant_id: UUID) -> str | None:
    """The tenant's verified host Graph can post to, or None for no push.

    TenantDomain is not tenant-scoped, so this reads outside a tenant
    transaction. The first verified host by name: any of an agency's verified
    hosts resolves to it, and a stable choice means a renewal re-points the
    URL only when the hosts themselves changed.
    """
    if not settings.MAILBOX_PUSH_ENABLED:
        return None
    host: str | None = (
        TenantDomain.objects.filter(agency_id=tenant_id, verified_at__isnull=False)
        .order_by("host")
        .values_list("host", flat=True)
        .first()
    )
    return host


def enqueue_work(
    kind: Literal["sync", "subscribe"],
    connection: MailboxConnection,
    *,
    client: SQSClient | None = None,
) -> None:
    enqueue(
        MailboxWork(kind=kind, tenant_id=connection.tenant_id, connection_id=connection.id),
        client=client,
        queue_url=settings.MAILBOX_QUEUE_URL,
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save(connection: MailboxConnection, subscription_id: str, expires: datetime | None) -> None:
    connection.push_subscription_id = subscription_id
    connection.push_expires_at = expires
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        MailboxConnection.objects.filter(id=connection.id).update(
            push_subscription_id=subscription_id, push_expires_at=expires
        )


def _renew(
    http: Any, token: str, subscription_id: str, expires: datetime, notification_url: str
) -> None:
    """Extend, reauthorize and re-point in one PATCH.

    The URL goes every time: an agency whose verified host changed would
    otherwise keep renewing a subscription that posts to a host which no longer
    resolves to it, push dead and nothing saying so. Graph validates a changed
    URL with the same handshake as a create. The lifecycle URL cannot be
    updated, so lifecycle events keep the old host until the next recreate;
    the sweep covers what they would have said.
    """
    _json(
        http,
        "PATCH",
        f"{MICROSOFT_API_ORIGIN}/v1.0/subscriptions/{subscription_id}",
        access_token=token,
        provider="MICROSOFT",
        body={"expirationDateTime": _iso(expires), "notificationUrl": notification_url},
    )


def _create(http: Any, token: str, body: dict[str, object]) -> dict[str, object]:
    return _json(
        http,
        "POST",
        f"{MICROSOFT_API_ORIGIN}/v1.0/subscriptions",
        access_token=token,
        provider="MICROSOFT",
        headers=_GRAPH_HEADERS,
        ok=(201,),
        body=body,
    )


def _delete(http: Any, token: str, subscription_id: str) -> None:
    _json(
        http,
        "DELETE",
        f"{MICROSOFT_API_ORIGIN}/v1.0/subscriptions/{subscription_id}",
        access_token=token,
        provider="MICROSOFT",
        ok=(204, 404),
    )


def _existing_id(http: Any, token: str) -> str:
    """The id of the subscription a 409 says is in the way, or "".

    Matched on the resource alone: a delegated listing holds "Subscriptions
    created by this app for the signed-in user only" (Graph's list-subscriptions
    reference), so any me/messages row in it is ours -- even one made when the
    agency's host was a different one.
    """
    listing = _json(
        http,
        "GET",
        f"{MICROSOFT_API_ORIGIN}/v1.0/subscriptions",
        access_token=token,
        provider="MICROSOFT",
    )
    rows = listing.get("value", [])
    for row in rows if isinstance(rows, list) else []:
        if (
            isinstance(row, dict)
            and str(row.get("resource", "")).casefold() == RESOURCE
            and valid_subscription_id(row.get("id"))
        ):
            return str(row["id"])
    return ""


def ensure_subscription(
    connection: MailboxConnection,
    *,
    force: bool = False,
    now: datetime | None = None,
    http: object | None = None,
    secrets_client: object | None = None,
) -> bool:
    """Keep this connection's Graph subscription alive. True when it is.

    Creates one when there is none, renews one with under RENEW_WITHIN left
    (or any one, under ``force``), and recreates one Graph no longer has.
    Raises for neither Graph nor a grant: see the module docstring.
    """
    if (
        connection.provider != MailboxConnection.Provider.MICROSOFT
        or connection.status != MailboxConnection.Status.ACTIVE
    ):
        return False
    host = push_host(connection.tenant_id)
    if host is None:
        return False
    moment = now or timezone.now()
    if (
        not force
        and connection.push_subscription_id
        and connection.push_expires_at is not None
        and connection.push_expires_at - moment > RENEW_WITHIN
    ):
        return True
    pool: Any = http if http is not None else urllib3.PoolManager()
    expires = moment + timedelta(minutes=SUBSCRIPTION_MINUTES)
    notification_url = f"https://{host}{NOTIFICATION_PATH}"
    try:
        token = access_token_for(connection, http=pool, secrets_client=secrets_client)
        if connection.push_subscription_id:
            try:
                _renew(pool, token, connection.push_subscription_id, expires, notification_url)
                _save(connection, connection.push_subscription_id, expires)
                return True
            except ProviderError as error:
                if error.status != 404:
                    raise
                # Graph removed it (expired, or a subscriptionRemoved event):
                # make a new one below.
        body: dict[str, object] = {
            "changeType": "created",
            "notificationUrl": notification_url,
            "lifecycleNotificationUrl": f"https://{host}{LIFECYCLE_PATH}",
            "resource": RESOURCE,
            "expirationDateTime": _iso(expires),
            "clientState": client_state(connection.id),
            "latestSupportedTlsVersion": "v1_2",
        }
        try:
            created = _create(pool, token, body)
        except ProviderError as error:
            if error.status != 409:
                raise
            # One subscription per app, user, resource and change type. The
            # one in the way belongs to an earlier connection of this student
            # (a reconnect) or to a create whose row write was lost -- either
            # way its clientState is not this connection's, so adopting it
            # would leave every notification failing the check. Replace it.
            stale = _existing_id(pool, token)
            if not stale:
                raise
            _delete(pool, token, stale)
            created = _create(pool, token, body)
        subscription_id = created.get("id")
        if not valid_subscription_id(subscription_id):
            raise ProviderError("MICROSOFT returned no usable subscription id")
        _save(connection, str(subscription_id), expires)
        return True
    except (GrantRefused, ProviderError) as error:
        # The connection id and the error's own text, which providers.py and
        # oauth.py keep to a status and a host by design -- never a token, an
        # address or a URL.
        logger.warning("push upkeep failed for connection %s: %s", connection.id, error)
        if connection.push_expires_at is not None:
            # Forget the expiry, keep the id: the row no longer looks fresh, so
            # the next sweep tries again instead of trusting a subscription
            # that a lifecycle event or a failed renewal says is in doubt.
            _save(connection, connection.push_subscription_id, None)
        return False


def handle_work(
    message: MailboxWork,
    *,
    http: object | None = None,
    secrets_client: object | None = None,
) -> None:
    """One queued instruction: keep the subscription alive if asked, then sync.

    Never raises for a provider or a limit. A refused or failed sync is
    acknowledged and left to the next sweep: redelivering it would only spend
    the queue's three receives on a Graph outage and page someone from the
    dead-letter queue for nothing.
    """
    with tenant_scope(message.tenant_id):
        with tenant_transaction(message.tenant_id):
            connection = (
                MailboxConnection.objects.select_related("membership")
                .filter(id=message.connection_id)
                .first()
            )
        if connection is None or connection.status != MailboxConnection.Status.ACTIVE:
            return
        if message.kind == "subscribe":
            ensure_subscription(connection, force=True, http=http, secrets_client=secrets_client)
        try:
            sync_connection(
                connection,
                http=http,
                secrets_client=secrets_client,
                rate_bucket=PUSH_SYNC_BUCKET,
                limit=PUSH_SYNC_LIMIT,
            )
        except (SyncRefused, ProviderError) as error:
            logger.info("push sync skipped for connection %s: %s", connection.id, error)
