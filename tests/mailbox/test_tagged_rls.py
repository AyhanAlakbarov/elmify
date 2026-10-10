"""The tagged-mail sync path, behind a role that RLS actually applies to.

The rest of the suite runs as the local test superuser, which is BYPASSRLS, so
a tenant-scoped read or write taken outside a ``tenant_transaction`` passes
there and would return zero rows (or be silently refused) in production.
CLAUDE.md is explicit that a test which does not run behind
``rls_enforced_orm`` has verified nothing about tenant isolation.

This exercises exactly the path task-10-brief.md names: a ``PortalAccount`` is
built, a tagged header is synced through a ``FakeProvider`` from a learnable
vendor domain, and the result is a ``MailSignal`` (``trusted``) plus a
``LearnedSender`` row -- the reads (``PortalAccount``, ``LearnedSender``,
``Application``) and the writes (``MailSignal``, ``LearnedSender``,
``Notification``, ``DeviceAction``) sync.py's tagged branch performs, all under the production
NOBYPASSRLS role.

Shape rules learned from tests/portals/test_ext_rls.py and
tests/portals/test_rls_spine.py:

``django_db(transaction=True)``, because the fixture closes and reopens the
connection to swap roles.

``connection_with_pack`` is listed BEFORE ``rls_enforced_orm`` in the
signature, so its setup writes run while the connection is still the
superuser's; everything in the test body runs after the swap, under the
NOBYPASSRLS role.

``classify_message`` is stubbed regardless of environment: a real call would
be a paid OpenAI call, and CLAUDE.md's rate limiting note plus this branch's
own controller ruling ("no paid vendor calls, ever stubbed") both forbid one
in a test.

``portalvendor.com`` is a real registrable domain, not a ``.test`` one: the
brief notes ``sender_key`` blanks reserved TLDs like ``.test``, so a domain
under it can never become a ``LearnedSender``.
"""

from datetime import UTC, datetime

import pytest

from apps.concierge.models import Notification
from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import LearnedSender, MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import sync_connection
from apps.portals.models import DeviceAction, PortalAccount
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db(transaction=True)

TAGGED = "student+ab12cd@gmail.test"


def _header(message_id: str, sender: str) -> MessageHeader:
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=(TAGGED,),
        junk=False,
    )


def test_tagged_sync_writes_a_signal_and_learns_the_sender_behind_the_policy(
    connection_with_pack, monkeypatch, rls_enforced_orm
) -> None:
    """RED if any of sync.py's tagged-branch reads or writes escape their
    tenant_transaction: the PortalAccount lookup would miss the tag, the
    MailSignal/LearnedSender insert would be refused by the policy, or the
    later read would see nothing the superuser-run suite would otherwise see."""
    from apps.mailbox import sync as sync_module

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
        )

    # A DECISION carrying a link to an allowlisted host, so the acting half of
    # the path -- the urgent label card and the queued DeviceAction -- also
    # runs under the policy (final review M3), not only the recording half.
    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(
            label="DECISION",
            action_kind="OPEN_VERIFICATION_URL",
            action_value="https://portal.uni-bonn.de/verify?t=abc123",
        ),
    )
    provider = FakeProvider((_header("m1", "no-reply@mail-eu.portalvendor.com"),))

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert signal.sender_domain == "portalvendor.com"
    assert signal.trusted is True

    with tenant_transaction(connection.tenant_id):
        assert MailSignal.objects.filter(pk=signal.pk).exists()
        learned = LearnedSender.objects.get(student=connection.membership)
        decision_cards = Notification.objects.filter(
            recipient=connection.membership, urgent=True, message__contains="sent a decision"
        ).count()
        action = DeviceAction.objects.get(membership=connection.membership)

    assert learned.domain == "portalvendor.com"
    assert learned.portal_host == "portal.uni-bonn.de"
    assert decision_cards == 1
    assert action.kind == DeviceAction.Kind.OPEN_VERIFICATION_URL


def test_the_mail_measures_the_tag_behind_the_policy(
    connection_with_pack, monkeypatch, rls_enforced_orm
) -> None:
    """RED if sync's registration reads or tag writes escape their
    tenant_transaction: _awaiting_registration would see no account under the
    policy and the STRIPS measurement would silently never happen."""
    from django.utils import timezone

    from apps.funding.models import AuditEvent
    from apps.mailbox import sync as sync_module
    from apps.portals.models import PortalForm

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
            registered_at=timezone.now(),
        )
    header = MessageHeader(
        message_id="m-strip",
        sender="noreply@uni-bonn.de",
        received_at=timezone.now(),
        recipients=("student@gmail.test",),
    )

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((header,)), secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        account = PortalAccount.objects.get(student=connection.membership)
        audited = AuditEvent.objects.filter(event="portal.tag_status_set").count()
    assert account.tag_outcome == "STRIPS"
    # Security review M2: mail measures this account only; the platform-wide
    # row is moved by `manage.py set_tag_status` alone.
    assert audited == 0
    assert PortalForm.objects.get(portal_host="portal.uni-bonn.de").tag_status == "UNKNOWN"


def test_tag_mail_corrects_a_false_rejects_behind_the_policy(
    connection_with_pack, monkeypatch, rls_enforced_orm
) -> None:
    """RED if restore_tag's write (final review M3) escapes the sync's
    tenant_transaction: the conditional UPDATE would match zero rows under the
    policy and the account would silently stay REJECTS on its plain address."""
    from apps.mailbox import sync as sync_module
    from apps.portals.models import PortalForm

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address="student@gmail.test",
            tag_outcome=PortalForm.TagStatus.REJECTS,
        )

    with tenant_scope(connection.tenant_id):
        sync_connection(
            connection,
            provider=FakeProvider((_header("m-restore", "noreply@uni-bonn.de"),)),
            secrets_client=_grant(),
        )

    with tenant_transaction(connection.tenant_id):
        account = PortalAccount.objects.get(student=connection.membership)
    assert (account.tag_outcome, account.address) == ("KEEPS", TAGGED)
