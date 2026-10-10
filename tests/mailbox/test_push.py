"""Graph push: subscription upkeep, the webhook, and the worker (watch spec §3a).

Every Graph call goes to a scripted fake; no test here reaches Microsoft.
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.mailbox import push
from apps.mailbox.models import MailboxConnection
from apps.mailbox.oauth import GrantRefused
from apps.mailbox.providers import ProviderError
from apps.mailbox.sync import PUSH_SYNC_BUCKET, PUSH_SYNC_LIMIT, SyncRefused
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


class _Graph:
    """Answers each (method, path) from a script; records every request."""

    def __init__(self, script: dict[tuple[str, str], list[tuple[int, object]]]) -> None:
        self.script = {key: list(answers) for key, answers in script.items()}
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method, url, *, body=None, headers=None, **_kwargs):
        path = url.removeprefix("https://graph.microsoft.com/v1.0")
        self.calls.append((method, path, json.loads(body) if body else None))
        status, payload = self.script[(method, path)].pop(0)
        data = b"" if payload is None else json.dumps(payload).encode()
        return SimpleNamespace(status=status, data=data)


@pytest.fixture(autouse=True)
def _push_on(settings, monkeypatch):
    settings.MAILBOX_PUSH_ENABLED = True
    monkeypatch.setattr(push, "access_token_for", lambda *a, **k: "access-token")


@pytest.fixture
def outlook(agency_a, membership_a, domain_a):
    with tenant_scope(agency_a.id):
        return MailboxConnection.objects.create(
            tenant=agency_a,
            membership=membership_a,
            provider=MailboxConnection.Provider.MICROSOFT,
            tier=MailboxConnection.Tier.METADATA,
            status=MailboxConnection.Status.ACTIVE,
            address="student@outlook.test",
        )


def _reload(connection):
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        return MailboxConnection.objects.get(id=connection.id)


# --- clientState -------------------------------------------------------------


def test_client_state_is_per_connection_and_checked_in_constant_time() -> None:
    one, two = uuid4(), uuid4()
    assert push.client_state(one) == push.client_state(one)
    assert push.client_state(one) != push.client_state(two)
    assert len(push.client_state(one)) <= 128  # Graph's limit
    assert push.state_matches(one, push.client_state(one))
    assert not push.state_matches(one, push.client_state(two))
    assert not push.state_matches(one, None)
    assert not push.state_matches(one, 12345)


# --- the host Graph posts to -------------------------------------------------


@pytest.mark.django_db
def test_no_push_without_the_switch(settings, agency_a, domain_a) -> None:
    settings.MAILBOX_PUSH_ENABLED = False
    assert push.push_host(agency_a.id) is None


@pytest.mark.django_db
def test_only_a_verified_host_receives_push(agency_a, unverified_domain) -> None:
    assert push.push_host(agency_a.id) is None


@pytest.mark.django_db
def test_the_tenant_s_own_verified_host_receives_push(agency_a, domain_a, domain_b) -> None:
    assert push.push_host(agency_a.id) == domain_a.host


# --- subscription upkeep -----------------------------------------------------


@pytest.mark.django_db
def test_a_new_connection_is_subscribed_on_its_tenant_host(outlook, domain_a) -> None:
    now = timezone.now()
    graph = _Graph({("POST", "/subscriptions"): [(201, {"id": "sub-1"})]})

    assert push.ensure_subscription(outlook, now=now, http=graph)

    (method, path, body), = graph.calls
    assert body["resource"] == "me/messages"
    assert body["changeType"] == "created"
    assert body["notificationUrl"] == f"https://{domain_a.host}/mailbox/push/graph/"
    assert body["lifecycleNotificationUrl"] == f"https://{domain_a.host}/mailbox/push/graph/lifecycle/"
    assert body["clientState"] == push.client_state(outlook.id)
    saved = _reload(outlook)
    assert saved.push_subscription_id == "sub-1"
    assert saved.push_expires_at - now == timedelta(minutes=push.SUBSCRIPTION_MINUTES)
    assert saved.push_expires_at - now < timedelta(minutes=10_080)


@pytest.mark.django_db
def test_the_routes_are_the_paths_subscriptions_are_made_with() -> None:
    assert reverse("mailbox-push-graph") == push.NOTIFICATION_PATH
    assert reverse("mailbox-push-graph-lifecycle") == push.LIFECYCLE_PATH


@pytest.mark.django_db
def test_a_fresh_subscription_is_left_alone(outlook) -> None:
    now = timezone.now()
    outlook.push_subscription_id = "sub-1"
    outlook.push_expires_at = now + timedelta(days=5)
    graph = _Graph({})

    assert push.ensure_subscription(outlook, now=now, http=graph)
    assert graph.calls == []


@pytest.mark.django_db
def test_a_subscription_near_expiry_is_renewed(outlook) -> None:
    now = timezone.now()
    outlook.push_subscription_id = "sub-1"
    outlook.push_expires_at = now + timedelta(days=1)
    graph = _Graph({("PATCH", "/subscriptions/sub-1"): [(200, {"id": "sub-1"})]})

    assert push.ensure_subscription(outlook, now=now, http=graph)

    assert [call[:2] for call in graph.calls] == [("PATCH", "/subscriptions/sub-1")]
    assert _reload(outlook).push_expires_at > now + timedelta(days=6)


@pytest.mark.django_db
def test_a_subscription_graph_no_longer_has_is_recreated(outlook) -> None:
    outlook.push_subscription_id = "gone"
    graph = _Graph(
        {
            ("PATCH", "/subscriptions/gone"): [(404, {"error": "not found"})],
            ("POST", "/subscriptions"): [(201, {"id": "sub-2"})],
        }
    )

    assert push.ensure_subscription(outlook, force=True, http=graph)
    assert _reload(outlook).push_subscription_id == "sub-2"


@pytest.mark.django_db
def test_a_reconnect_replaces_the_old_connection_s_subscription(outlook) -> None:
    """Graph allows one subscription per app, user, resource and change type.
    The one in the way carries the OLD connection's clientState, so adopting it
    would fail every notification's check; it is deleted and remade."""
    graph = _Graph(
        {
            ("POST", "/subscriptions"): [(409, {"error": "exists"}), (201, {"id": "sub-new"})],
            ("GET", "/subscriptions"): [
                (200, {"value": [{"id": "sub-old", "resource": "me/messages"}]})
            ],
            ("DELETE", "/subscriptions/sub-old"): [(204, None)],
        }
    )

    assert push.ensure_subscription(outlook, http=graph)

    assert [call[:2] for call in graph.calls] == [
        ("POST", "/subscriptions"),
        ("GET", "/subscriptions"),
        ("DELETE", "/subscriptions/sub-old"),
        ("POST", "/subscriptions"),
    ]
    assert _reload(outlook).push_subscription_id == "sub-new"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure", [ProviderError("MICROSOFT answered 503", status=503), GrantRefused("gone")]
)
def test_upkeep_never_raises(outlook, monkeypatch, failure) -> None:
    """A connection push cannot cover stays on the sweep; the sync that
    follows reports a lost grant itself."""

    def boom(*_a, **_k):
        raise failure

    monkeypatch.setattr(push, "access_token_for", boom)
    assert push.ensure_subscription(outlook, http=_Graph({})) is False
    assert _reload(outlook).push_subscription_id == ""


@pytest.mark.django_db
def test_gmail_and_switched_off_connections_are_not_subscribed(
    settings, connection, outlook
) -> None:
    graph = _Graph({})
    assert push.ensure_subscription(connection, http=graph) is False  # GOOGLE
    settings.MAILBOX_PUSH_ENABLED = False
    assert push.ensure_subscription(outlook, http=graph) is False
    assert graph.calls == []


# --- the webhook -------------------------------------------------------------


@pytest.fixture
def queued(monkeypatch):
    sent: list[tuple[str, object]] = []
    monkeypatch.setattr(push, "enqueue_work", lambda kind, conn, **_k: sent.append((kind, conn.id)))
    return sent


@pytest.fixture
def subscribed(outlook):
    with tenant_scope(outlook.tenant_id), tenant_transaction(outlook.tenant_id):
        MailboxConnection.objects.filter(id=outlook.id).update(push_subscription_id="sub-1")
    outlook.push_subscription_id = "sub-1"
    return outlook


def _post(client, host, path, values):
    return client.post(
        path, data=json.dumps({"value": values}), content_type="application/json", HTTP_HOST=host
    )


@pytest.mark.django_db
@pytest.mark.parametrize("path", [push.NOTIFICATION_PATH, push.LIFECYCLE_PATH])
def test_the_validation_handshake_echoes_the_token_as_plain_text(client, domain_a, path) -> None:
    response = client.post(
        f"{path}?validationToken=Validation%3A%20Testing%20client%20application%20reachability",
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response.content == b"Validation: Testing client application reachability"


@pytest.mark.django_db
def test_a_genuine_notification_queues_one_sync(client, domain_a, subscribed, queued) -> None:
    item = {"subscriptionId": "sub-1", "clientState": push.client_state(subscribed.id)}

    response = _post(client, domain_a.host, push.NOTIFICATION_PATH, [item, item])

    assert response.status_code == 202
    assert queued == [("sync", subscribed.id)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "item",
    [
        {"subscriptionId": "sub-1", "clientState": "forged"},
        {"subscriptionId": "sub-1"},
        {"subscriptionId": "unknown", "clientState": "x"},
        {"clientState": "x"},
    ],
)
def test_anything_unverified_is_acknowledged_and_dropped(
    client, domain_a, subscribed, queued, item
) -> None:
    response = _post(client, domain_a.host, push.NOTIFICATION_PATH, [item])
    assert response.status_code == 202
    assert queued == []


@pytest.mark.django_db
def test_a_revoked_connection_s_notifications_are_ignored(
    client, domain_a, subscribed, queued
) -> None:
    with tenant_scope(subscribed.tenant_id), tenant_transaction(subscribed.tenant_id):
        MailboxConnection.objects.filter(id=subscribed.id).update(
            status=MailboxConnection.Status.REVOKED
        )
    item = {"subscriptionId": "sub-1", "clientState": push.client_state(subscribed.id)}
    assert _post(client, domain_a.host, push.NOTIFICATION_PATH, [item]).status_code == 202
    assert queued == []


@pytest.mark.django_db
def test_another_tenant_s_host_cannot_reach_this_connection(
    client, domain_a, domain_b, subscribed, queued
) -> None:
    """The tenant comes from the host, and the lookup runs under its scope."""
    item = {"subscriptionId": "sub-1", "clientState": push.client_state(subscribed.id)}
    assert _post(client, domain_b.host, push.NOTIFICATION_PATH, [item]).status_code == 202
    assert queued == []


@pytest.mark.django_db
@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"value": "nope"}'])
def test_a_malformed_body_is_a_400(client, domain_a, queued, body) -> None:
    response = client.post(
        push.NOTIFICATION_PATH, data=body, content_type="application/json", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_the_webhook_takes_only_post(client, domain_a) -> None:
    assert client.get(push.NOTIFICATION_PATH, HTTP_HOST=domain_a.host).status_code == 405


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("reauthorizationRequired", [("subscribe",)]),
        ("subscriptionRemoved", [("subscribe",)]),
        ("missed", [("sync",)]),
        ("somethingNew", []),
    ],
)
def test_lifecycle_events_become_upkeep_or_a_sync(
    client, domain_a, subscribed, queued, event, expected
) -> None:
    item = {
        "subscriptionId": "sub-1",
        "clientState": push.client_state(subscribed.id),
        "lifecycleEvent": event,
    }
    assert _post(client, domain_a.host, push.LIFECYCLE_PATH, [item]).status_code == 202
    assert [(kind,) for kind, _id in queued] == expected


# --- the worker ----------------------------------------------------------------


@pytest.fixture
def sync_calls(monkeypatch):
    calls: list[dict] = []

    def fake_sync(connection, **kwargs):
        calls.append({"connection": connection.id, **kwargs})
        return []

    monkeypatch.setattr(push, "sync_connection", fake_sync)
    return calls


def _work(kind, connection):
    return push.MailboxWork(kind=kind, tenant_id=connection.tenant_id, connection_id=connection.id)


@pytest.mark.django_db
def test_a_push_sync_spends_its_own_budget(outlook, sync_calls) -> None:
    push.handle_work(_work("sync", outlook))
    (call,) = sync_calls
    assert call["rate_bucket"] == PUSH_SYNC_BUCKET
    assert call["limit"] == PUSH_SYNC_LIMIT


@pytest.mark.django_db
def test_subscribe_work_forces_upkeep_then_syncs(outlook, sync_calls, monkeypatch) -> None:
    upkeep: list[bool] = []
    monkeypatch.setattr(push, "ensure_subscription", lambda c, **k: upkeep.append(k["force"]))
    push.handle_work(_work("subscribe", outlook))
    assert upkeep == [True]
    assert len(sync_calls) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [SyncRefused("limit"), ProviderError("MICROSOFT answered 503")])
def test_the_worker_never_raises_for_a_provider_or_a_limit(outlook, monkeypatch, failure) -> None:
    def boom(*_a, **_k):
        raise failure

    monkeypatch.setattr(push, "sync_connection", boom)
    push.handle_work(_work("sync", outlook))  # no exception: the sweep catches up


@pytest.mark.django_db
def test_the_worker_skips_a_connection_that_is_gone_or_inactive(outlook, sync_calls) -> None:
    with tenant_scope(outlook.tenant_id), tenant_transaction(outlook.tenant_id):
        MailboxConnection.objects.filter(id=outlook.id).update(
            status=MailboxConnection.Status.REVOKED
        )
    push.handle_work(_work("sync", outlook))
    push.handle_work(
        push.MailboxWork(kind="sync", tenant_id=outlook.tenant_id, connection_id=uuid4())
    )
    assert sync_calls == []


# --- the views that start and end a subscription --------------------------------


@pytest.mark.django_db
def test_the_sweep_keeps_subscriptions_alive_before_syncing(outlook, monkeypatch) -> None:
    from django.core.management import call_command

    order: list[str] = []
    monkeypatch.setattr(
        "apps.mailbox.management.commands.sync_mailboxes.ensure_subscription",
        lambda c, **k: order.append("upkeep") or True,
    )
    monkeypatch.setattr(
        "apps.mailbox.management.commands.sync_mailboxes.sync_connection",
        lambda c, **k: order.append("sync") or [],
    )
    call_command("sync_mailboxes")
    assert order == ["upkeep", "sync"]


def _connect(client, student, provider):
    from django.core import signing

    state = signing.dumps({"membership": str(student.id), "provider": provider, "tier": "METADATA"})
    return client.get(reverse("mailbox-callback", args=[provider]) + f"?code=c&state={state}")


@pytest.mark.django_db
def test_connecting_outlook_asks_the_worker_to_subscribe_after_the_commit(
    settings, student_client, fake_exchange, queued, django_capture_on_commit_callbacks
) -> None:
    settings.MAILBOX_PROVIDERS = ("MICROSOFT",)
    client, student = student_client
    with django_capture_on_commit_callbacks(execute=True):
        response = _connect(client, student, "MICROSOFT")
    assert response.status_code == 302
    with tenant_scope(student.tenant_id):
        connection = MailboxConnection.objects.get()
    assert queued == [("subscribe", connection.id)]


@pytest.mark.django_db
def test_connecting_gmail_queues_nothing(
    student_client, fake_exchange, queued, django_capture_on_commit_callbacks
) -> None:
    client, student = student_client
    with django_capture_on_commit_callbacks(execute=True):
        assert _connect(client, student, "GOOGLE").status_code == 302
    assert queued == []


@pytest.mark.django_db
def test_a_queue_failure_does_not_break_the_connect(
    settings, student_client, fake_exchange, monkeypatch, django_capture_on_commit_callbacks
) -> None:
    """The sweep subscribes any connection it finds without a subscription."""
    settings.MAILBOX_PROVIDERS = ("MICROSOFT",)

    def down(*_a, **_k):
        raise RuntimeError("SQS is down")

    monkeypatch.setattr(push, "enqueue_work", down)
    client, student = student_client
    with django_capture_on_commit_callbacks(execute=True):
        assert _connect(client, student, "MICROSOFT").status_code == 302


# --- regressions from the probing review ----------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "item",
    [
        {"subscriptionId": "sub-1", "clientState": "é"},  # compare_digest on non-ASCII str
        {"subscriptionId": "a\u0000b", "clientState": "x"},  # Postgres refuses NUL
        {"subscriptionId": "x" * 300, "clientState": "x"},  # longer than the column
    ],
)
def test_hostile_identifiers_are_dropped_not_500s(client, domain_a, subscribed, queued, item):
    assert _post(client, domain_a.host, push.NOTIFICATION_PATH, [item]).status_code == 202
    assert queued == []


@pytest.mark.django_db
def test_deeply_nested_json_is_a_400_not_a_500(client, domain_a, queued) -> None:
    body = b"[" * 200_000 + b"]" * 200_000
    response = client.post(
        push.NOTIFICATION_PATH, data=body, content_type="application/json", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_a_removal_beside_a_miss_in_one_post_still_repairs_the_subscription(
    client, domain_a, subscribed, queued
) -> None:
    state = push.client_state(subscribed.id)
    items = [
        {"subscriptionId": "sub-1", "clientState": state, "lifecycleEvent": "missed"},
        {"subscriptionId": "sub-1", "clientState": state, "lifecycleEvent": "subscriptionRemoved"},
    ]
    assert _post(client, domain_a.host, push.LIFECYCLE_PATH, items).status_code == 202
    assert queued == [("subscribe", subscribed.id)]


@pytest.mark.django_db
def test_a_failed_forced_upkeep_makes_the_next_sweep_retry(outlook) -> None:
    """A subscription a lifecycle event put in doubt must not keep looking
    fresh for days because the repair hit a Graph outage."""
    now = timezone.now()
    with tenant_scope(outlook.tenant_id), tenant_transaction(outlook.tenant_id):
        MailboxConnection.objects.filter(id=outlook.id).update(
            push_subscription_id="sub-1", push_expires_at=now + timedelta(days=6)
        )
    outlook = _reload(outlook)
    graph = _Graph({("PATCH", "/subscriptions/sub-1"): [(503, {"error": "busy"})]})

    assert push.ensure_subscription(outlook, force=True, now=now, http=graph) is False

    saved = _reload(outlook)
    assert (saved.push_subscription_id, saved.push_expires_at) == ("sub-1", None)
    renewed = _Graph({("PATCH", "/subscriptions/sub-1"): [(200, {"id": "sub-1"})]})
    assert push.ensure_subscription(saved, now=now, http=renewed)  # not forced
    assert len(renewed.calls) == 1


@pytest.mark.django_db
def test_a_renewal_re_points_the_subscription_at_the_current_host(
    outlook, domain_a, agency_a
) -> None:
    from apps.tenancy.models import TenantDomain

    now = timezone.now()
    outlook.push_subscription_id = "sub-1"
    outlook.push_expires_at = now + timedelta(days=1)
    domain_a.delete()
    TenantDomain.objects.create(agency=agency_a, host="new.example.test", verified_at=now)
    graph = _Graph({("PATCH", "/subscriptions/sub-1"): [(200, {"id": "sub-1"})]})

    assert push.ensure_subscription(outlook, now=now, http=graph)

    (_method, _path, body), = graph.calls
    assert body["notificationUrl"] == "https://new.example.test/mailbox/push/graph/"


@pytest.mark.django_db
@pytest.mark.parametrize("bad_id", [None, 123, ["a"], "x" * 300, "a\u0000b"])
def test_an_off_spec_subscription_id_is_never_saved(outlook, bad_id) -> None:
    graph = _Graph({("POST", "/subscriptions"): [(201, {"id": bad_id})]})
    assert push.ensure_subscription(outlook, http=graph) is False
    assert _reload(outlook).push_subscription_id == ""


@pytest.mark.django_db
def test_the_webhook_lookup_column_is_indexed() -> None:
    """Security review L2: every unauthenticated Graph POST looks connections
    up by subscription id, up to 100 times, before clientState is checked."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'mailbox_mailboxconnection'"
        )
        definitions = [row[0] for row in cursor.fetchall()]

    assert any("(push_subscription_id)" in definition for definition in definitions)
