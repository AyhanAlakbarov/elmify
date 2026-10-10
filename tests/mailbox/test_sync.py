"""The spec's acceptance criterion, in one file.

"A fixture inbox with 50 messages from 10 domains, 2 in the pack -> exactly 2
signals." The fake provider records every call it receives, because the second
half of the promise is negative: the 48 rejected messages must never have been
fetched, and a metadata-tier connection must never ask for a body at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import SyncRefused, sync_connection
from apps.portals.models import DeviceAction
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant


def _inbox() -> tuple[MessageHeader, ...]:
    """50 messages from 10 domains; two of those domains are in the pack."""
    domains = [
        "tum.de",
        "daad.de",
        "newsletter.example",
        "linkedin.example",
        "bank.example",
        "tum.de.example",
        "notdaad.de",
        "friend.example",
        "shop.example",
        "news.example",
    ]
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return tuple(
        MessageHeader(
            message_id=f"m{index}",
            sender=f"someone@{domains[index % len(domains)]}",
            received_at=start + timedelta(hours=index),
        )
        for index in range(50)
    )


@pytest.mark.django_db
def test_only_the_two_pack_domains_produce_signals(connection_with_pack) -> None:
    connection = connection_with_pack
    provider = FakeProvider(_inbox())

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert len(signals) == 5 + 5  # tum.de and daad.de each appear five times in 50
    assert {signal.sender_domain for signal in signals} == {"tum.de", "daad.de"}


@pytest.mark.django_db
def test_the_look_alike_domain_is_not_a_signal(connection_with_pack) -> None:
    provider = FakeProvider(_inbox())
    with tenant_scope(connection_with_pack.tenant_id):
        signals = sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    assert all(signal.sender_domain not in {"tum.de.example", "notdaad.de"} for signal in signals)


@pytest.mark.django_db
def test_a_content_tier_connection_fetches_a_body_once_per_matched_message(
    connection_with_pack,
) -> None:
    """The positive half of the promise test_a_metadata_tier_connection_never_asks_for_a_body
    checks the negative half of: a CONTENT connection (connection_with_pack's default
    tier) fetches exactly the ten tum.de/daad.de messages and none of the other 40."""
    inbox = _inbox()
    expected = {
        header.message_id
        for header in inbox
        if header.sender.split("@", 1)[-1] in {"tum.de", "daad.de"}
    }
    provider = FakeProvider(inbox)

    with tenant_scope(connection_with_pack.tenant_id):
        sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    assert sorted(provider.bodies_fetched) == sorted(expected)
    assert len(provider.bodies_fetched) == len(set(provider.bodies_fetched))


@pytest.mark.django_db
def test_a_metadata_tier_connection_never_asks_for_a_body(connection_with_pack) -> None:
    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id):
        connection.tier = MailboxConnection.Tier.METADATA
        connection.save(update_fields=["tier"])
    provider = FakeProvider(_inbox())

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    assert provider.bodies_fetched == []


@pytest.mark.django_db
def test_running_it_twice_produces_no_second_signal_and_no_second_card(
    connection_with_pack,
) -> None:
    """The unique constraint is the mechanism, but the promise is about the
    student: a re-run must not tell them twice that TUM wrote."""
    provider = FakeProvider(_inbox())
    with tenant_scope(connection_with_pack.tenant_id):
        first = sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())
        cache.clear()
        second = sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    assert second == []
    with tenant_transaction(connection_with_pack.tenant_id):
        assert MailSignal.objects.count() == len(first)


@pytest.mark.django_db
def test_the_cursor_advances_to_the_newest_message_seen(connection_with_pack) -> None:
    provider = FakeProvider(_inbox())
    with tenant_scope(connection_with_pack.tenant_id):
        sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    connection_with_pack.refresh_from_db()
    assert connection_with_pack.sync_cursor.startswith("2026-09-")
    assert connection_with_pack.last_sync_at is not None

    with tenant_scope(connection_with_pack.tenant_id):
        cache.clear()
        sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())
    assert provider.listed[-1] is not None


@pytest.mark.django_db
def test_the_cursor_passes_mail_that_was_dropped(connection_with_pack) -> None:
    """The newest message in _inbox() is a stranger's (news.example, hour 49);
    the newest kept one is daad.de at hour 41. Measured live 2026-10-03 on a
    real Outlook inbox: the cursor stopped at the kept message, so every later
    sync re-listed all the dropped mail after it."""
    with tenant_scope(connection_with_pack.tenant_id):
        sync_connection(
            connection_with_pack, provider=FakeProvider(_inbox()), secrets_client=_grant()
        )

    connection_with_pack.refresh_from_db()
    newest = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(hours=49)
    assert datetime.fromisoformat(connection_with_pack.sync_cursor) == newest


@pytest.mark.django_db
def test_a_revoked_connection_is_refused(connection_with_pack) -> None:
    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id):
        connection.status = MailboxConnection.Status.REVOKED
        connection.save(update_fields=["status"])

    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())


@pytest.mark.django_db
def test_an_unrecognised_provider_refuses_instead_of_raising_provider_error(
    student_with_pack,
) -> None:
    """Fix round 1, finding 1: `provider_for(connection.provider, ...)` used to
    run BEFORE the `try/except (GrantRefused, ProviderError)` block, so a
    connection row naming a provider this codebase doesn't build a client for
    raised a bare ProviderError -- which mailbox_check's `except SyncRefused`
    cannot catch. No `provider=` kwarg here, deliberately: passing a fake
    would skip the very call this finding is about.
    """
    student, _pack = student_with_pack
    with tenant_transaction(student.tenant_id):
        connection = MailboxConnection.objects.create(
            tenant_id=student.tenant_id,
            membership=student,
            provider="AOL",
            address="student@aol.test",
        )

    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, secrets_client=_grant())


@pytest.mark.django_db
def test_a_student_with_an_open_objection_is_not_synced(connection_with_pack) -> None:
    from apps.privacy import requests

    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id), tenant_scope(connection.tenant_id):
        requests.record(
            connection.membership,
            kind="objection",
            channel="email",
            received_at=datetime(2026, 10, 2, tzinfo=UTC),
        )
    provider = FakeProvider(_inbox())

    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=provider, secrets_client=_grant())
    assert provider.listed == []


@pytest.mark.django_db
def test_a_lost_grant_marks_the_connection_and_stops(connection_with_pack, monkeypatch) -> None:
    """Nothing retries indefinitely: a refresh that fails is a fact the student
    has to act on, so the row says ERROR and the sweep moves to the next one.

    Opts out of the autouse token stub (conftest) rather than weakening it --
    this is the one test that wants the refusal.
    """
    from apps.mailbox.oauth import GrantRefused

    def _no_grant(*_args, **_kwargs):
        raise GrantRefused("no stored grant")

    monkeypatch.setattr("apps.mailbox.sync.access_token_for", _no_grant)

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    connection.refresh_from_db()
    assert connection.status == MailboxConnection.Status.ERROR


@pytest.mark.django_db
def test_the_sync_is_rate_limited_per_student(connection_with_pack) -> None:
    from apps.mailbox.sync import SYNC_LIMIT

    provider = FakeProvider(())
    with tenant_scope(connection_with_pack.tenant_id):
        for _ in range(SYNC_LIMIT):
            sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())
        with pytest.raises(SyncRefused):
            sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())


@pytest.mark.django_db
def test_each_new_signal_becomes_one_card_the_agent_owns(connection_with_pack) -> None:
    provider = FakeProvider(_inbox())
    with tenant_scope(connection_with_pack.tenant_id):
        signals = sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    with tenant_transaction(connection_with_pack.tenant_id):
        assert Notification.objects.count() == len(signals)
        items = list(RoadmapItem.objects.all())
    assert items
    assert all(item.owner_id is None for item in items)
    assert all(item.owner_kind == RoadmapItem.OwnerKind.AGENT for item in items)
    assert all(item.stage == RoadmapItem.Stage.MONITORING for item in items)


@pytest.mark.django_db
def test_the_card_names_the_institution_and_not_the_message(connection_with_pack) -> None:
    """A subject is read for classification and dropped. It must not arrive in
    a notification by the back door -- the card says who wrote, not what."""
    provider = FakeProvider(_inbox()[:1])
    with tenant_scope(connection_with_pack.tenant_id):
        sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    with tenant_transaction(connection_with_pack.tenant_id):
        message = Notification.objects.values_list("message", flat=True).first()
    assert message is not None
    assert "tum.de" in message
    assert "@" not in message


@pytest.mark.django_db
def test_a_lost_grant_tells_the_student_to_reconnect(connection_with_pack, monkeypatch) -> None:
    from apps.mailbox.oauth import GrantRefused

    def _no_grant(*_args, **_kwargs):
        raise GrantRefused("no stored grant")

    monkeypatch.setattr("apps.mailbox.sync.access_token_for", _no_grant)

    with tenant_scope(connection_with_pack.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection_with_pack, provider=FakeProvider(()), secrets_client=_grant())

    with tenant_transaction(connection_with_pack.tenant_id):
        assert Notification.objects.count() == 1
        assert RoadmapItem.objects.get().stage == RoadmapItem.Stage.PERSONAL_ACTION


@pytest.mark.django_db
def test_a_lost_grant_notification_is_urgent(connection_with_pack, monkeypatch) -> None:
    """Fix round 1, finding 1 (controller ruling): the ERROR flip is already
    announced by announce_lost_grant -- widening apps/watch/mailbox_health.py's
    stale query to ERROR would double-alert one outage. Instead the existing
    card must itself be urgent, so escalation carries it to the student's
    sign-in address and then the counsellor."""
    from apps.mailbox.oauth import GrantRefused

    def _no_grant(*_args, **_kwargs):
        raise GrantRefused("no stored grant")

    monkeypatch.setattr("apps.mailbox.sync.access_token_for", _no_grant)

    with tenant_scope(connection_with_pack.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection_with_pack, provider=FakeProvider(()), secrets_client=_grant())

    with tenant_transaction(connection_with_pack.tenant_id):
        assert Notification.objects.filter(urgent=True).count() == 1


@pytest.mark.django_db
def test_a_revocation_mid_sync_is_not_overwritten_by_the_error(
    connection_with_pack, monkeypatch
) -> None:
    """request_deletion revoked the row while this sync held a stale ACTIVE copy.
    ERROR must not overwrite REVOKED, and an erasing student must not be told
    to reconnect."""
    from apps.mailbox.oauth import GrantRefused

    def _no_grant(*_args, **_kwargs):
        raise GrantRefused("no stored grant")

    monkeypatch.setattr("apps.mailbox.sync.access_token_for", _no_grant)
    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id):
        MailboxConnection.objects.filter(pk=connection.pk).update(
            status=MailboxConnection.Status.REVOKED
        )

    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.REVOKED
        )
        assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_an_early_return_sync_also_clears_a_stale_alert(connection) -> None:
    """Fix round 1, finding 2: the "nothing to read" early return used to save
    only last_sync_at, leaving health_alerted_at set -- so after one alert a
    later outage on the same connection was never alerted again. `connection`
    (membership_a, no pack, no application) has no allowed senders and no
    tracking start, so this sync takes that early-return path."""
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        MailboxConnection.objects.filter(pk=connection.pk).update(
            health_alerted_at=timezone.now()
        )

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    connection.refresh_from_db()
    assert connection.health_alerted_at is None


@pytest.mark.django_db
@pytest.mark.parametrize("authenticated", [True, False])
def test_a_classified_message_reaches_apply_verdict_with_its_own_authentication(
    connection_with_pack, monkeypatch, authenticated: bool
) -> None:
    """The production wiring this exercises, and why it needed its own test:

    Every other test in this file drives the real `classify_message`, which
    fails to construct an `OpenAI()` client (no API key in this environment)
    and raises `ClassificationFailure` -- so execution always lands in
    sync_connection's `except` branch and the `else:` branch that calls
    `apply_verdict(signal, verdict, link_hosts=links,
    authenticated=header.authenticated)` never runs anywhere else in this
    file. Confirmed by temporarily inserting `raise AssertionError` as
    `apply_verdict`'s first line and re-running the rest of this file: every
    other test still passed. That leaves `authenticated=header.authenticated`
    -- the argument the whole gate in apply_verdict rests on -- completely
    unexercised in its actual production call site; a typo hardcoding
    `authenticated=True` or dropping the keyword would pass every other test
    here too.

    Only `classify_message` is monkeypatched (to return a real verdict rather
    than raising) -- the same monkeypatch-a-module-global convention this
    file already uses for `access_token_for` above. `apply_verdict` itself is
    left real and reached by the actual production call site, so a sabotage
    of `apply_verdict` (or of the call site's `authenticated=` argument) is
    caught by this test, not hidden behind a spy standing in for it: the
    action-queuing side effect (a `DeviceAction`, gated on `authenticated`) is
    asserted directly.
    """
    header = MessageHeader(
        message_id="m0",
        sender="someone@tum.de",
        received_at=datetime(2026, 9, 1, tzinfo=UTC),
        authenticated=authenticated,
    )
    provider = FakeProvider((header,))
    verdict = MailVerdict(
        label="VERIFICATION",
        action_kind="OPEN_VERIFICATION_URL",
        action_value="https://tum.de/verify?t=abc123",
    )
    monkeypatch.setattr("apps.mailbox.sync.classify_message", lambda **_kwargs: verdict)

    with tenant_scope(connection_with_pack.tenant_id):
        sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    with tenant_transaction(connection_with_pack.tenant_id):
        action_count = DeviceAction.objects.count()
        label = MailSignal.objects.get().label

    # The label is recorded either way -- only the action is gated.
    assert label == MailSignal.Label.VERIFICATION
    assert action_count == (1 if authenticated else 0)


@pytest.mark.django_db
def test_a_first_sync_starts_where_tracking_began_not_a_fixed_window(
    connection_with_pack,
) -> None:
    """Mail from before the pack or the first application cannot be about them."""
    from apps.funding.services import current_pack

    connection = connection_with_pack
    provider = FakeProvider(())

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            started = current_pack(connection.membership).run.created_at

    assert provider.listed == [started]


@pytest.mark.django_db
def test_gmail_content_tier_asks_only_for_pack_senders(connection_with_pack) -> None:
    provider = FakeProvider(())

    with tenant_scope(connection_with_pack.tenant_id):
        sync_connection(connection_with_pack, provider=provider, secrets_client=_grant())

    assert set(provider.searched[0]) == {"tum.de", "daad.de", "uni-bonn.de"}


def _application_inbox_messages() -> tuple[MessageHeader, ...]:
    """50 messages from 10 REGISTRABLE domains -- deliberately not `_inbox()`'s
    `.example` ones (fix round 1, finding 1). `sender_key` blanks any host
    ending in an RFC 2606 reserved suffix (`.example`/`.test`/`.invalid`/
    `.localhost`/...), so an application-inbox fixture built on `.example`
    senders would silently skip 7 of its 10 domains instead of reading them --
    both `len(signals) == 50` and the "read but untrusted" assertion below
    would pass vacuously. These domains are all real-shaped and none is in
    `connection_with_pack`'s allowlist (tum.de, daad.de, uni-bonn.de) except
    the two pack domains themselves, mirroring `_inbox()`'s shape without
    reusing its fixture (other tests in this file depend on `_inbox()`'s own
    `.example` domains, e.g. the look-alike-domain test)."""
    domains = [
        "tum.de",
        "daad.de",
        "newsletter.co",
        "linkedin.co",
        "bank.co",
        "faketum.de",
        "notdaad.de",
        "friend.co",
        "shop.co",
        "news.co",
    ]
    start = datetime(2026, 9, 1, tzinfo=UTC)
    return tuple(
        MessageHeader(
            message_id=f"a{index}",
            sender=f"someone@{domains[index % len(domains)]}",
            received_at=start + timedelta(hours=index),
        )
        for index in range(50)
    )


@pytest.mark.django_db
def test_an_application_inbox_reads_every_sender(connection_with_pack, monkeypatch) -> None:
    """It holds nothing but application mail, so no sender filter applies (spec §3).

    Deviation from the brief's literal test: connection_with_pack defaults to
    the CONTENT tier, so every one of the 50 messages here reaches
    classify_message. That must never make a paid call, so it is stubbed here
    the same way test_a_classified_message_reaches_apply_verdict_with_its_own_authentication
    stubs it above -- everywhere else in this file it fails naturally (no
    OPENAI_API_KEY in this environment), which this test must not depend on.
    """
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message", lambda **_kwargs: MailVerdict(label="OTHER")
    )
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.kind = MailboxConnection.Kind.APPLICATION
        connection.save(update_fields=["kind"])
    provider = FakeProvider(_application_inbox_messages())

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert len(signals) == 50
    assert provider.searched == [()]
    assert all(not s.trusted for s in signals if s.sender_domain == "newsletter.co")


@pytest.mark.django_db
def test_an_application_inbox_normalises_an_injected_sender(
    connection_with_pack, monkeypatch
) -> None:
    """A From header is attacker-controlled text (fix round 1, finding 1):
    read every sender must not mean store every byte. `x@a.com/path\\ninjected:
    yes` must never land as the raw host with its embedded newline and
    header-injection attempt. Since final review I4 it is not a hostname at
    all, so it is skipped outright rather than trimmed to a guess at one."""
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message", lambda **_kwargs: MailVerdict(label="OTHER")
    )
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.kind = MailboxConnection.Kind.APPLICATION
        connection.save(update_fields=["kind"])
    header = MessageHeader(
        message_id="injected-1",
        sender="x@a.com/path\ninjected: yes",
        received_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    provider = FakeProvider((header,))

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert signals == []
    assert provider.bodies_fetched == []


@pytest.mark.django_db
def test_an_application_inbox_skips_an_overlong_host_without_aborting_the_batch(
    connection_with_pack, monkeypatch
) -> None:
    """Fix round 2 finding: an overlong host used to reach
    `MailSignal.objects.get_or_create` and raise `DataError: value too long for
    type character varying(253)`, uncaught, aborting the whole sync -- one
    crafted email stopped every other message in the same batch from being
    stored. `sender_key` now blanks it before it ever reaches the database."""
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message", lambda **_kwargs: MailVerdict(label="OTHER")
    )
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.kind = MailboxConnection.Kind.APPLICATION
        connection.save(update_fields=["kind"])
    headers = (
        MessageHeader(
            message_id="ok-1",
            sender="someone@tum.de",
            received_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
        MessageHeader(
            message_id="overlong",
            sender="x@" + "a" * 500 + ".com",
            received_at=datetime(2026, 9, 1, 1, tzinfo=UTC),
        ),
        MessageHeader(
            message_id="ok-2",
            sender="someone@daad.de",
            received_at=datetime(2026, 9, 1, 2, tzinfo=UTC),
        ),
    )
    provider = FakeProvider(headers)

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert {s.provider_message_id for s in signals} == {"ok-1", "ok-2"}


@pytest.mark.django_db
def test_gmail_metadata_tier_cannot_search_so_lists_everything(connection_with_pack) -> None:
    """Positive control: gmail.metadata refuses `q`, so asking would fail every sync."""
    connection = connection_with_pack
    provider = FakeProvider(())
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.tier = MailboxConnection.Tier.METADATA
        connection.save(update_fields=["tier"])

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    assert provider.searched == [()]


class _GraphAnswering:
    """A urllib3 stand-in that answers every Graph request with one status."""

    def __init__(self, status: int) -> None:
        self.status = status

    def request(self, method, url, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(status=self.status, data=b"{}")


@pytest.mark.django_db
@pytest.mark.parametrize("status", [429, 500, 503])
def test_a_passing_provider_outage_leaves_the_connection_active(
    connection_with_pack, status
) -> None:
    """Final review I2: a one-off 429/5xx is not a lost grant. The row stays
    ACTIVE and nobody is told to reconnect; the stale-inbox alert covers an
    outage that lasts."""
    from apps.mailbox.providers import MicrosoftMailbox

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(
            connection,
            provider=MicrosoftMailbox(http=_GraphAnswering(status)),
            secrets_client=_grant(),
        )

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.ACTIVE
        )
        assert Notification.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("status", [401, 403])
def test_a_provider_refusing_the_grant_marks_it_lost(connection_with_pack, status) -> None:
    from apps.mailbox.providers import MicrosoftMailbox

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(
            connection,
            provider=MicrosoftMailbox(http=_GraphAnswering(status)),
            secrets_client=_grant(),
        )

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.ERROR
        )
        assert Notification.objects.filter(urgent=True).count() == 1


@pytest.mark.django_db
def test_a_listing_transport_failure_is_a_refusal_not_a_crash(connection_with_pack) -> None:
    """Final review I1(a): a reset while listing used to escape as a raw
    urllib3 error, past sync_mailboxes (skipping every later student and
    record_run) and past mailbox_check's `except SyncRefused`."""
    import urllib3.exceptions

    from apps.mailbox.providers import MicrosoftMailbox

    class _Reset:
        def request(self, *_args, **_kwargs):
            raise urllib3.exceptions.ProtocolError("connection reset")

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(
            connection, provider=MicrosoftMailbox(http=_Reset()), secrets_client=_grant()
        )

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.ACTIVE
        )


class _TokenAnswering:
    """A urllib3 stand-in that answers every refresh POST with one status."""

    def __init__(self, status: int, payload: dict[str, object] | None = None) -> None:
        self.status = status
        self.payload = payload if payload is not None else {}

    def request(self, method, url, **_kwargs):
        import json as _json_module
        from types import SimpleNamespace

        return SimpleNamespace(status=self.status, data=_json_module.dumps(self.payload).encode())


def _real_access_token_for(http):
    """Overrides conftest's autouse `no_live_token_endpoint` stub with the
    real `access_token_for`, bound to a fake transport -- so these tests
    exercise oauth.py's own refusal/availability decision, not a stand-in
    for it."""
    from apps.mailbox.oauth import access_token_for as _real

    def _call(connection, **_kwargs):
        return _real(connection, http=http, secrets_client=_grant())

    return _call


@pytest.mark.django_db
@pytest.mark.parametrize("status", [408, 429, 503])
def test_a_transient_token_refresh_status_leaves_the_connection_active(
    connection_with_pack, monkeypatch, status
) -> None:
    """The rule (brief): 408/429/5xx refreshing the token is not now, never a
    lost grant -- the same shape I2 already gives listing."""
    monkeypatch.setattr(
        "apps.mailbox.sync.access_token_for", _real_access_token_for(_TokenAnswering(status))
    )

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.ACTIVE
        )
        assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_a_transport_failure_refreshing_the_token_leaves_the_connection_active(
    connection_with_pack, monkeypatch
) -> None:
    import urllib3.exceptions

    class _Reset:
        def request(self, *_args, **_kwargs):
            raise urllib3.exceptions.ProtocolError("connection reset")

    monkeypatch.setattr(
        "apps.mailbox.sync.access_token_for", _real_access_token_for(_Reset())
    )

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.ACTIVE
        )
        assert Notification.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("status", [400, 401])
def test_a_real_token_refresh_refusal_still_marks_it_lost(
    connection_with_pack, monkeypatch, status
) -> None:
    """400 (invalid_grant) and 401 at the token endpoint are unchanged: ERROR
    plus exactly one urgent card."""
    monkeypatch.setattr(
        "apps.mailbox.sync.access_token_for", _real_access_token_for(_TokenAnswering(status))
    )

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), pytest.raises(SyncRefused):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        assert (
            MailboxConnection.objects.get(pk=connection.pk).status
            == MailboxConnection.Status.ERROR
        )
        assert Notification.objects.filter(urgent=True).count() == 1


@pytest.mark.django_db
def test_a_signal_left_unclassified_by_an_interrupted_sync_is_classified_next_time(
    connection_with_pack, monkeypatch
) -> None:
    """Final review I1(b): a sync that died between recording a signal and
    classifying it (a worker killed, an exception nobody caught) left the row
    at classify_attempts == 0, and the retry pass only took attempts > 0 -- so
    it was never read again."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    header = MessageHeader(
        message_id="m1", sender="admissions@tum.de", received_at=datetime(2026, 9, 20, tzinfo=UTC)
    )

    class _DiesMidSync(FakeProvider):
        def fetch_body(self, *, access_token, message_id):
            raise RuntimeError("worker killed")

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        with pytest.raises(RuntimeError):
            sync_connection(connection, provider=_DiesMidSync((header,)), secrets_client=_grant())
        good = FakeProvider((header,))
        sync_connection(connection, provider=good, secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        signal = MailSignal.objects.get()
    assert good.bodies_fetched == ["m1"]
    assert signal.label == "OTHER"
    assert signal.classify_attempts == 0


def _burst(count: int) -> tuple[MessageHeader, ...]:
    start = datetime(2026, 9, 20, tzinfo=UTC)
    return tuple(
        MessageHeader(
            message_id=f"b{index}",
            sender="admissions@tum.de",
            received_at=start + timedelta(minutes=index),
        )
        for index in range(count)
    )


@pytest.mark.django_db
def test_our_own_classify_rate_limit_costs_no_attempt_and_stops_the_pass(
    connection_with_pack, monkeypatch
) -> None:
    """Final review I5(a): the model never failed, so nothing counts against
    the message -- and every further body fetch this sync would be wasted."""
    from apps.mailbox import sync as sync_module
    from apps.mailbox.classify import ClassificationRateLimited

    def _limited(**_kwargs):
        raise ClassificationRateLimited("limit")

    monkeypatch.setattr(sync_module, "classify_message", _limited)
    provider = FakeProvider(_burst(3))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        attempts = set(MailSignal.objects.values_list("classify_attempts", flat=True))
        open_cards = Notification.objects.filter(message__icontains="open the message").count()
    assert len(provider.bodies_fetched) == 1
    assert attempts == {0}
    assert open_cards == 0


@pytest.mark.django_db
def test_one_sync_classifies_at_most_its_cap_newest_first(connection_with_pack, monkeypatch):
    """Final review I5(b): 25 new signals -> the 20 newest this sync (a
    waiting verification code is the newest mail), the other 5 next sync."""
    from apps.mailbox import sync as sync_module
    from apps.mailbox.sync import MAX_CLASSIFY_PER_SYNC

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = connection_with_pack
    first = FakeProvider(_burst(25))
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=first, secrets_client=_grant())
        second = FakeProvider(())
        sync_connection(connection, provider=second, secrets_client=_grant())

    assert MAX_CLASSIFY_PER_SYNC == 20
    assert first.bodies_fetched == [f"b{index}" for index in range(24, 4, -1)]
    assert sorted(second.bodies_fetched) == sorted(f"b{index}" for index in range(5))
    with tenant_transaction(connection.tenant_id):
        assert not MailSignal.objects.filter(label="").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("stopped", [False, True])
def test_a_stopped_student_s_mail_never_reaches_the_decision_reader(
    connection_with_pack, monkeypatch, stopped: bool
) -> None:
    """Ruling F10. Jev is processing too, so an open objection must stop it before
    any read. The unstopped run is the positive control: the same unlabelled
    signal on a card does reach read_decision."""
    from apps.mailbox import sync as sync_module
    from apps.mailbox.decision_reader import UNAVAILABLE
    from apps.portals.models import Application
    from apps.privacy import requests

    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id), tenant_scope(connection.tenant_id):
        MailSignal.objects.create(
            tenant_id=connection.tenant_id,
            connection=connection,
            provider_message_id="waiting",
            sender_domain="tum.de",
            received_at=timezone.now(),
            application=Application.objects.get(student=connection.membership),
        )
        if stopped:
            requests.record(
                connection.membership, kind="objection", channel="email",
                received_at=timezone.now(),
            )
    reads: list[str] = []
    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    monkeypatch.setattr(
        sync_module, "read_decision", lambda body, *_a, **_k: reads.append(body) or UNAVAILABLE
    )

    with tenant_scope(connection.tenant_id):
        if stopped:
            with pytest.raises(SyncRefused):
                sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())
        else:
            sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    assert reads == ([] if stopped else ["body text"])


@pytest.mark.django_db
def test_the_content_tier_passes_the_subject_to_jev_stripped(
    connection_with_pack, monkeypatch
) -> None:
    """Ruling F19, fix round 1 item 2: the subject comes from the same body fetch."""
    from apps.mailbox import decision_reader
    from apps.mailbox.providers import MailBody
    from apps.portals.models import Application
    from tests.mailbox.test_decision_reader import FakeJev

    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id), tenant_scope(connection.tenant_id):
        user = connection.membership.user
        user.first_name, user.last_name = "Amina", "Yusuf"
        user.save(update_fields=["first_name", "last_name"])
        MailSignal.objects.create(
            tenant_id=connection.tenant_id, connection=connection,
            provider_message_id="waiting", sender_domain="tum.de",
            received_at=timezone.now(),
            application=Application.objects.get(student=connection.membership),
        )

    class _WithSubject(FakeProvider):
        def fetch_body(self, *, access_token, message_id):
            return MailBody(text="Dear Amina, admitted.", subject="Decision for Amina Yusuf")

    fake = FakeJev({}, {})
    real_read = decision_reader.read_decision
    monkeypatch.setattr(
        "apps.mailbox.sync.read_decision", lambda *a, **k: real_read(*a, **k, client=fake)
    )
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message", lambda **_: MailVerdict(label="OTHER")
    )

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=_WithSubject(()), secrets_client=_grant())

    (state,) = fake.states
    assert state["email"]["subject"] == "Decision for [name] [name]"
    assert state["email"]["body"] == "Dear [name], admitted."


@pytest.mark.django_db
def test_a_reader_that_breaks_never_stops_the_batch(connection_with_pack, monkeypatch) -> None:
    """Fix round 1, item 6: every waiting signal is still labelled."""
    from apps.portals.models import Application

    connection = connection_with_pack
    with tenant_transaction(connection.tenant_id), tenant_scope(connection.tenant_id):
        application = Application.objects.get(student=connection.membership)
        for index in range(2):
            MailSignal.objects.create(
                tenant_id=connection.tenant_id, connection=connection,
                provider_message_id=f"waiting-{index}", sender_domain="tum.de",
                received_at=timezone.now(), application=application,
            )

    def broken(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.mailbox.decision_reader.ask", broken)
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message", lambda **_: MailVerdict(label="OTHER")
    )

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())
        labels = sorted(MailSignal.objects.values_list("label", flat=True))
        readings = [s.decision_reading for s in MailSignal.objects.all()]

    assert labels == ["OTHER", "OTHER"]
    assert all(r["unavailable"] is True for r in readings)
