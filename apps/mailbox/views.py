"""Connect, come back, revoke, narrow. No screen.

The connect screen is templates/student/settings_mailbox.html.
It shows three things at once, which is the whole privacy argument --
the provider's scope, the live list of domains this student's pack justifies
reading (apps/mailbox/filter.py::allowed_senders), and the choice
between the content tier and the metadata tier. These views are the seam: a
template rendering that screen posts to exactly these routes and needs no
change here.
"""

from __future__ import annotations

import json
import logging
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.mailbox import push
from apps.mailbox.filter import allowed_senders
from apps.mailbox.models import LearnedSender, MailboxConnection
from apps.mailbox.oauth import GrantRefused, GrantUnavailable, authorize_url, exchange_code
from apps.mailbox.secrets import delete_student_mailbox_tokens, store_refresh_token
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from apps.tenancy.services import current_membership

#: Ten minutes between pressing Connect and coming back. Long enough for a
#: consent screen and a password manager, short enough that a state left in a
#: browser history is not a standing invitation.
_STATE_MAX_AGE = 600

logger = logging.getLogger(__name__)

#: Graph batches notifications; more than this in one POST is not a mailbox
#: event, it is something else, and the rest are left to the sweep.
_MAX_NOTIFICATIONS = 100


def _wants_html(request: HttpRequest) -> bool:
    """A browser form post (Accept: text/html) gets a redirect and a message; a
    JSON caller keeps getting JSON. Django's test client sends no Accept header.
    This picks the response shape only: CSRF, login and ownership are decided
    before and apart from it."""
    return "text/html" in request.headers.get("Accept", "")


def _answer(
    request: HttpRequest, payload: dict[str, object], *, status: int = 200, message: str = ""
) -> HttpResponse:
    if not _wants_html(request):
        return JsonResponse(payload, status=status)
    if status == 404:
        # The id of a connection that is not yours is not a fact you get to confirm.
        raise Http404
    if status >= 400:
        messages.error(request, message or "That did not work. Try again.")
    elif message:
        messages.success(request, message)
    return redirect("student-settings-mailbox")


@login_required
def mailbox_settings(request: HttpRequest) -> HttpResponse:
    """Connections, connect (tier and kind), revoke, downgrade, senders to confirm,
    and the live list of domains the pack justifies reading -- the privacy
    argument in one screen."""
    membership = current_membership(request, Membership.Role.STUDENT)
    return render(
        request,
        "student/settings_mailbox.html",
        {
            "connections": MailboxConnection.objects.filter(membership=membership).order_by(
                "-connected_at"
            ),
            "learned": LearnedSender.objects.filter(
                student=membership, confirmed_at__isnull=True
            ).exclude(domain=""),
            "domains": sorted(allowed_senders(membership)),
            "providers": settings.MAILBOX_PROVIDERS,
            "tiers": MailboxConnection.Tier.choices,
            "kinds": MailboxConnection.Kind.choices,
        },
    )


@login_required
def connect(request: HttpRequest, provider: str) -> HttpResponse:
    membership = current_membership(request, Membership.Role.STUDENT)
    # A browser form gets the page back with a message (Task 17 minor).
    if provider not in settings.MAILBOX_PROVIDERS:
        return _answer(request, {"reason": "provider_unavailable"}, status=400,
                       message="That mailbox provider is not offered yet.")
    tier = request.GET.get("tier", MailboxConnection.Tier.CONTENT)
    if tier not in MailboxConnection.Tier.values:
        return _answer(request, {"reason": "unknown_tier"}, status=400)
    kind = request.GET.get("kind", MailboxConnection.Kind.EVERYDAY)
    if kind not in MailboxConnection.Kind.values:
        return _answer(request, {"reason": "unknown_kind"}, status=400)
    state = signing.dumps(
        {"membership": str(membership.id), "provider": provider, "tier": tier, "kind": kind}
    )
    try:
        target = authorize_url(provider=provider, tier=tier, state=state)
    except GrantRefused:
        return _answer(request, {"reason": "unknown_provider"}, status=400)
    return HttpResponseRedirect(target)


@login_required
def callback(request: HttpRequest, provider: str) -> HttpResponse:
    membership = current_membership(request, Membership.Role.STUDENT)
    try:
        state = signing.loads(request.GET.get("state", ""), max_age=_STATE_MAX_AGE)
    except signing.BadSignature:
        return _answer(
            request,
            {"reason": "bad_state"},
            status=400,
            message="The connection link expired or was not yours. Start again.",
        )
    # The signature proves WE issued this state. It does not prove it was
    # issued to the person now logged in -- a student who starts a connection
    # and hands the URL to someone else would otherwise attach that person's
    # mailbox to their own account.
    if state.get("membership") != str(membership.id) or state.get("provider") != provider:
        return _answer(
            request,
            {"reason": "state_mismatch"},
            status=400,
            message="The connection link expired or was not yours. Start again.",
        )

    code = request.GET.get("code", "")
    if not code:
        return _answer(
            request,
            {"reason": "no_code"},
            status=400,
            message="The provider did not send a code. Start again.",
        )
    try:
        grant = exchange_code(provider=provider, code=code)
    except GrantUnavailable:
        # A busy provider, not a refused grant: the student did nothing
        # wrong and no row is stored -- exchange_code raises before any
        # write. Answer retryable, never a 500.
        return _answer(
            request,
            {"reason": "try_again"},
            status=503,
            message="The provider is busy. Try again in a minute.",
        )
    except GrantRefused:
        return _answer(
            request,
            {"reason": "grant_refused"},
            status=400,
            message="The provider refused the connection.",
        )

    # Before the row: a row pointing at a secret that does not exist reads as a
    # working connection and fails at the first sync.
    store_refresh_token(
        tenant_id=membership.tenant_id,
        student_id=membership.id,
        provider=provider,
        refresh_token=grant.refresh_token,
    )
    with tenant_transaction(membership.tenant_id):
        # The partial unique constraint allows one ACTIVE connection per
        # provider, so reconnecting retires the old row rather than colliding
        # with it. The old row stays as history; its signals stay with it.
        MailboxConnection.objects.filter(
            membership=membership,
            provider=provider,
            status=MailboxConnection.Status.ACTIVE,
        ).update(status=MailboxConnection.Status.REVOKED, revoked_at=timezone.now())
        kind = state.get("kind", MailboxConnection.Kind.EVERYDAY)
        if kind not in MailboxConnection.Kind.values:
            kind = MailboxConnection.Kind.EVERYDAY
        connection = MailboxConnection.objects.create(
            tenant_id=membership.tenant_id,
            membership=membership,
            provider=provider,
            address=grant.address,
            tier=state["tier"],
            kind=kind,
        )
        membership.application_email = grant.address
        membership.save(update_fields=["application_email"])
        if (
            provider == MailboxConnection.Provider.MICROSOFT
            and push.push_host(membership.tenant_id) is not None
        ):
            transaction.on_commit(lambda: _subscribe_soon(connection))
    messages.success(request, f"{grant.address} is connected.")
    return redirect("student-settings-mailbox")


def _subscribe_soon(connection: MailboxConnection) -> None:
    """Ask the worker to subscribe now rather than at the next sweep.

    After the commit, so the worker finds the row. A queue failure must not
    turn a successful connect into an error page: the sweep subscribes every
    connection it finds without one.
    """
    try:
        push.enqueue_work("subscribe", connection)
    except Exception as error:
        logger.warning(
            "could not queue a push subscription for connection %s (%s)",
            connection.id,
            type(error).__name__,
        )


@require_POST
@login_required
def revoke(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    membership = current_membership(request, Membership.Role.STUDENT)
    with tenant_transaction(membership.tenant_id):
        # Filtered by membership as well as id: the tenant manager already
        # keeps another agency out, and this keeps another student in the same
        # agency out. A miss is 404, never 403 -- the id of a connection that
        # is not yours is not a fact you get to confirm.
        connection = MailboxConnection.objects.filter(
            id=connection_id, membership=membership
        ).first()
        if connection is None:
            return JsonResponse({"reason": "not_found"}, status=404)

    # provider=connection.provider: a student with two active connections
    # (one GOOGLE, one MICROSOFT) revoking one must not silently take down
    # the other. Without it, delete_student_mailbox_tokens's default walks
    # every provider, and the other connection's next sync fails GrantRefused
    # with no explanation of why.
    delete_student_mailbox_tokens(
        tenant_id=membership.tenant_id, student_id=membership.id, provider=connection.provider
    )
    with tenant_transaction(membership.tenant_id):
        connection.status = MailboxConnection.Status.REVOKED
        connection.revoked_at = timezone.now()
        connection.save(update_fields=["status", "revoked_at"])
    # The signals stay: they are the record that the platform saw something,
    # and erasure -- not revocation -- is what removes them.
    return _answer(request, {"revoked": True}, message="Disconnected.")


@require_POST
@login_required
def tier(request: HttpRequest, connection_id: UUID) -> HttpResponse:
    membership = current_membership(request, Membership.Role.STUDENT)
    if request.content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
        wanted = request.POST.get("tier", "")
    else:
        # JSON, however the caller labelled it (Task 17 minor: a text/plain
        # JSON body 400'd once the form path was added).
        try:
            wanted = json.loads(request.body or b"{}").get("tier", "")
        except (ValueError, AttributeError):
            return _answer(request, {"reason": "bad_request"}, status=400)
    if wanted not in MailboxConnection.Tier.values:
        return _answer(request, {"reason": "unknown_tier"}, status=400)

    with tenant_transaction(membership.tenant_id):
        connection = MailboxConnection.objects.filter(
            id=connection_id, membership=membership
        ).first()
        if connection is None:
            return _answer(request, {"reason": "not_found"}, status=404)
        # Narrowing is ours to do: the grant already covers it, and reading
        # less than we may is always allowed. Widening is a different scope,
        # and a column claiming access the grant does not carry fails at the
        # next body fetch with nothing saying why.
        if (
            connection.tier == MailboxConnection.Tier.METADATA
            and wanted == MailboxConnection.Tier.CONTENT
        ):
            return _answer(
                request,
                {"reason": "reconnect_required"},
                status=409,
                message="Reading more needs a new connection: disconnect and connect again.",
            )
        connection.tier = wanted
        connection.save(update_fields=["tier"])
    return _answer(request, {"tier": wanted}, message="From now on only headers are read.")


@require_POST
@login_required
def confirm_sender(request: HttpRequest, sender_id: UUID) -> HttpResponse:
    membership = current_membership(request, Membership.Role.STUDENT)
    with tenant_transaction(membership.tenant_id):
        updated = LearnedSender.objects.filter(
            id=sender_id, student=membership, confirmed_at__isnull=True
        ).update(confirmed_at=timezone.now())
    if not updated:
        return _answer(request, {"reason": "not_found"}, status=404)
    return _answer(request, {"confirmed": True}, message="Confirmed.")


def _push_values(request: HttpRequest) -> list[dict[str, object]] | None:
    try:
        payload = json.loads(request.body)
    except (ValueError, RecursionError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError; a body
        # nested deep enough overflows the decoder's stack instead.
        return None
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return None
    return [item for item in values[:_MAX_NOTIFICATIONS] if isinstance(item, dict)]


def _validation(request: HttpRequest) -> HttpResponse | None:
    """Graph's handshake: echo the token, as plain text, within ten seconds.

    Sent when a subscription is created and when its URL changes. Plain text
    and nosniff (SecurityMiddleware's default) are what keep an echoed string
    from ever being read as markup.
    """
    token = request.GET.get("validationToken")
    if token is None:
        return None
    return HttpResponse(token, content_type="text/plain; charset=utf-8")


_Work = Literal["sync", "subscribe"]


def _enqueue_verified(request: HttpRequest, kind_for: dict[str, _Work] | None) -> HttpResponse:
    """Verify each notification and queue one piece of work per connection.

    Runs inside HostTenantContextMiddleware's transaction and tenant scope, so
    the lookup below sees this tenant's connections only. Anything that does
    not verify -- an unknown subscription, an inactive connection, a wrong
    clientState -- is acknowledged and dropped: answering it with an error
    would only make Graph retry it and then throttle every notification we do
    want. A queue failure is the one error worth a 5xx, because Graph retries
    those.
    """
    values = _push_values(request)
    if values is None:
        return HttpResponse(status=400)
    # One piece of work per connection, the stronger kind winning: "subscribe"
    # also syncs, so a "missed" and a "subscriptionRemoved" in one POST must not
    # leave the removed subscription unrepaired.
    work: dict[UUID, tuple[MailboxConnection, _Work]] = {}
    for item in values:
        subscription_id = item.get("subscriptionId")
        if not push.valid_subscription_id(subscription_id):
            continue
        if kind_for is None:
            kind: _Work = "sync"
        elif (event := str(item.get("lifecycleEvent", ""))) in kind_for:
            kind = kind_for[event]
        else:
            continue
        connection = MailboxConnection.objects.filter(
            push_subscription_id=subscription_id, status=MailboxConnection.Status.ACTIVE
        ).first()
        if connection is None:
            continue
        if not push.state_matches(connection.id, item.get("clientState")):
            logger.warning("push notification with a wrong clientState for %s", connection.id)
            continue
        if work.get(connection.id, (None, ""))[1] != "subscribe":
            work[connection.id] = (connection, kind)
    for connection, kind in work.values():
        push.enqueue_work(kind, connection)
    return HttpResponse(status=202)


#: Watch spec §3a. Both reauthorization and removal are subscription upkeep;
#: "missed" is only a sync, because the sync's cursor reads everything since
#: the last one whether or not a notification said so.
_LIFECYCLE_WORK: dict[str, _Work] = {
    "reauthorizationRequired": "subscribe",
    "subscriptionRemoved": "subscribe",
    "missed": "sync",
}


@csrf_exempt
@require_POST
def graph_notification(request: HttpRequest) -> HttpResponse:
    """Graph's change notifications: "a message was created", by id only.

    Unauthenticated by session, like every webhook: what authenticates a
    notification is the clientState it echoes (push.client_state).
    """
    return _validation(request) or _enqueue_verified(request, None)


@csrf_exempt
@require_POST
def graph_lifecycle(request: HttpRequest) -> HttpResponse:
    """Graph's lifecycle events for the same subscriptions."""
    return _validation(request) or _enqueue_verified(request, _LIFECYCLE_WORK)
