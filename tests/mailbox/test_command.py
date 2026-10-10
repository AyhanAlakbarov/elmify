"""The sweep, and the one test that reads every log line this app emits."""

from __future__ import annotations

import logging

import pytest
from django.core.management import call_command

from apps.mailbox.models import MailboxConnection
from tests.mailbox.conftest import FakeProvider, _grant


@pytest.mark.django_db
def test_the_sweep_syncs_every_active_connection_in_every_agency(
    two_agencies_with_connections, patched_sync
) -> None:
    call_command("sync_mailboxes")

    assert len(patched_sync.synced) == 2


@pytest.mark.django_db
def test_a_revoked_connection_is_not_swept(connection_with_pack, patched_sync) -> None:
    connection_with_pack.status = MailboxConnection.Status.REVOKED
    connection_with_pack.save(update_fields=["status"])

    call_command("sync_mailboxes")

    assert patched_sync.synced == []


@pytest.mark.django_db
def test_one_failing_connection_does_not_strand_the_rest(
    two_agencies_with_connections, failing_then_working_sync
) -> None:
    call_command("sync_mailboxes")

    assert len(failing_then_working_sync.synced) == 2


@pytest.mark.django_db
def test_a_transient_token_failure_on_one_connection_does_not_stop_the_sweep(
    two_connections_with_pack, monkeypatch
) -> None:
    """A urllib3 error minting the access token used to escape sync_connection
    raw, aborting the sweep for every later student and skipping record_run --
    the same shape the final review's I1 fixed for listing, extended here to
    the token-refresh call."""
    from apps.mailbox.oauth import GrantUnavailable

    calls: list[object] = []

    def _access_token(connection, **_kwargs):
        calls.append(connection.id)
        if len(calls) == 1:
            raise GrantUnavailable(
                "token endpoint could not reach oauth2.googleapis.com (ProtocolError)"
            )
        return "access-token"

    recorded: list[str] = []
    monkeypatch.setattr("apps.mailbox.sync.access_token_for", _access_token)
    monkeypatch.setattr(
        "apps.mailbox.sync.provider_for", lambda provider, http=None: FakeProvider(())
    )
    monkeypatch.setattr(
        "apps.mailbox.management.commands.sync_mailboxes.record_run",
        lambda name: recorded.append(name),
    )

    call_command("sync_mailboxes")

    assert len(calls) == 2
    assert recorded == ["sync_mailboxes"]


@pytest.mark.django_db
def test_no_log_line_from_this_app_carries_mail(
    connection_with_pack, caplog, recording_provider
) -> None:
    """The one assertion that covers the whole app at once.

    Everything else in this plan promises not to log a particular thing. This
    drives a real sync with a real fixture inbox and reads every line that came
    out of apps.mailbox.*. `caplog.at_level(logging.DEBUG)` only lowers the
    ROOT logger's level -- config/settings/base.py's LOGGING config fixes the
    "apps" logger at INFO, so a future `logger.debug(...)` call anywhere under
    apps.mailbox.* would never become a LogRecord at all and this test cannot
    see it. What this guards, and keeps guarding after someone adds a line in
    six months, is a leak at INFO, WARNING or ERROR -- every level this app
    actually uses today.
    """
    from apps.mailbox.sync import sync_connection
    from apps.tenancy.context import tenant_scope

    with caplog.at_level(logging.DEBUG), tenant_scope(connection_with_pack.tenant_id):
        sync_connection(connection_with_pack, provider=recording_provider, secrets_client=_grant())

    emitted = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("apps.mailbox")
    )
    assert "@" not in emitted
    assert "tum.de" not in emitted
    assert "rt" not in emitted.split()
    assert "Bearer" not in emitted
    assert connection_with_pack.address not in emitted
