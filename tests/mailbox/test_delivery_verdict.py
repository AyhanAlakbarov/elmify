"""Outlook mail may act once Microsoft says it is genuine (live test, 2026-10-03).

Three gaps the live Outlook test found, one block each: Microsoft's delivery
verdict was never read, so no Outlook mail could act; a verification email
raised no card the student could act on; and a reconnect announced old mail
a second time.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.concierge.models import Notification
from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.mailbox.providers import MessageHeader, ProviderError, _microsoft_authenticated
from apps.mailbox.sync import sync_connection
from apps.portals.models import DeviceAction
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

#: The header shapes measured on a live Outlook.com inbox, 2026-10-03.
_MS_UFAZ = (
    "mx.microsoft.com 1; spf=pass (sender IP is 40.107.130.128) smtp.mailfrom=ufaz.az; "
    "dkim=pass (signature was verified) header.d=ufaz.az;dmarc=bestguesspass action=none "
    "header.from=ufaz.az;compauth=pass reason=109"
)
_MS_GMAIL = (
    "mx.microsoft.com 1; spf=pass (sender IP is 74.125.229.43) smtp.mailfrom=gmail.com; "
    "dkim=pass (signature was verified) header.d=gmail.com;dmarc=pass action=none "
    "header.from=gmail.com;compauth=pass reason=100"
)


def _h(name: str, value: str) -> dict[str, str]:
    return {"name": name, "value": value}


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        # Measured: a university with no DMARC record, aligned SPF and DKIM.
        (
            [_h("ARC-Authentication-Results", "i=2; x"), _h("Authentication-Results", _MS_UFAZ)],
            True,
        ),
        ([_h("Authentication-Results", _MS_GMAIL)], True),
        # A failed or absent DMARC result binds nothing.
        ([_h("Authentication-Results", _MS_GMAIL.replace("dmarc=pass", "dmarc=fail"))], False),
        ([_h("Authentication-Results", "mx.microsoft.com 1; spf=pass; dkim=pass")], False),
        # A sender's own header claiming a pass, placed first: not Microsoft's.
        (
            [
                _h("Authentication-Results", "evil.example; dmarc=pass header.from=ufaz.az"),
                _h("Authentication-Results", _MS_UFAZ),
            ],
            False,
        ),
        # Microsoft's says fail; a forged pass further down changes nothing.
        (
            [
                _h("Authentication-Results", _MS_GMAIL.replace("dmarc=pass", "dmarc=fail")),
                _h("Authentication-Results", "mx.microsoft.com 1; dmarc=pass"),
            ],
            False,
        ),
        # An earlier hop's verdict, renamed by Microsoft, is not the verdict.
        ([_h("Authentication-Results-Original", "mx.microsoft.com 1; dmarc=pass")], False),
        ([], False),
        (None, False),
        ("not a list", False),
    ],
)
def test_only_microsoft_s_own_first_verdict_counts(headers, expected) -> None:
    sender = "x@ufaz.az" if headers and _MS_UFAZ in str(headers) else "x@gmail.com"
    assert _microsoft_authenticated(headers, sender) is expected


#: The envelope-sender trick (re-review 2026-10-04): "=" is legal in a local part,
#: and Microsoft repeats the envelope sender in its own header.
_MS_TRICK = (
    "mx.microsoft.com 1; spf=pass (sender IP is 203.0.113.9) "
    "smtp.mailfrom=x+dmarc=pass@attacker.example; dkim=none (message not signed) "
    "header.d=none;dmarc=fail action=none header.from=tum.de;compauth=fail reason=000"
)


@pytest.mark.parametrize(
    ("value", "sender"),
    [
        (_MS_TRICK, "admissions@tum.de"),
        # A pass for another domain is not a pass for the one the mail is filed under.
        (_MS_GMAIL, "admissions@tum.de"),
        # A pass inside a comment is not a result.
        (
            "mx.microsoft.com 1; spf=pass (dmarc=pass header.from=tum.de) "
            "smtp.mailfrom=tum.de;dmarc=fail action=none header.from=tum.de",
            "admissions@tum.de",
        ),
        # A pass inside a quoted string is not a result either.
        (
            'mx.microsoft.com 1; spf=pass smtp.mailfrom="x;dmarc=pass header.from=tum.de"'
            "@attacker.example;dmarc=fail action=none header.from=tum.de",
            "admissions@tum.de",
        ),
    ],
)
def test_microsoft_reads_the_dmarc_result_itself_for_the_from_domain(value, sender) -> None:
    assert _microsoft_authenticated([_h("Authentication-Results", value)], sender) is False


@pytest.mark.parametrize(
    ("value", "sender"),
    [
        # Round 3: a stray ")", a duplicated property, a sender with no "@".
        ("mx.microsoft.com 1; spf=pass oops);dmarc=pass action=none header.from=tum.de",
         "a@tum.de"),
        ("mx.microsoft.com 1; dmarc=pass action=none header.from=evil.example "
         "header.from=tum.de", "a@tum.de"),
        ("mx.microsoft.com 1; dmarc=pass action=none header.from=tum.de", "tum.de"),
    ],
)
def test_microsoft_fails_closed_on_what_it_cannot_read(value, sender) -> None:
    assert _microsoft_authenticated([_h("Authentication-Results", value)], sender) is False


def test_a_microsoft_pass_binds_the_from_domain_case_insensitively() -> None:
    assert _microsoft_authenticated([_h("Authentication-Results", _MS_UFAZ)], "X@UFAZ.AZ") is True


class _Outlook(FakeProvider):
    name = "MICROSOFT"

    def __init__(self, headers, *, verdict: bool | Exception = True) -> None:
        super().__init__(headers)
        self.verdict = verdict
        self.verified: list[str] = []

    def delivery_verified(self, *, access_token: str, message_id: str, sender: str) -> bool:
        self.verified.append(message_id)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


def _outlook(connection, tier: str) -> MailboxConnection:
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        MailboxConnection.objects.filter(id=connection.id).update(
            provider=MailboxConnection.Provider.MICROSOFT, tier=tier
        )
        return MailboxConnection.objects.select_related("membership").get(id=connection.id)


def _mail(message_id: str, sender: str) -> MessageHeader:
    return MessageHeader(
        message_id=message_id, sender=sender, received_at=datetime(2026, 9, 1, tzinfo=UTC)
    )


_VERIFY = MailVerdict(
    label="VERIFICATION",
    action_kind="OPEN_VERIFICATION_URL",
    action_value="https://tum.de/verify?t=abc123",
)


@pytest.fixture
def verify_verdict(monkeypatch):
    monkeypatch.setattr("apps.mailbox.sync.classify_message", lambda **_kwargs: _VERIFY)


@pytest.mark.django_db
def test_verified_outlook_mail_from_the_pack_now_acts(connection_with_pack, verify_verdict):
    connection = _outlook(connection_with_pack, MailboxConnection.Tier.CONTENT)
    provider = _Outlook((_mail("m-tum", "admissions@tum.de"),))

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    assert provider.verified == ["m-tum"]
    with tenant_transaction(connection.tenant_id):
        assert MailSignal.objects.get().trusted is True
        assert DeviceAction.objects.count() == 1


@pytest.mark.django_db
def test_a_stranger_s_mail_is_never_asked_about(connection_with_pack, verify_verdict):
    """The verdict fetch reads ~16 KB of headers, subject included. It is made
    only for mail the pack already justified reading."""
    connection = _outlook(connection_with_pack, MailboxConnection.Tier.CONTENT)
    provider = _Outlook((_mail("m-x", "someone@friend.example"), _mail("m-tum", "a@tum.de")))

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    assert provider.verified == ["m-tum"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("tier", "verdict", "asked"),
    [
        # Mail.ReadBasic cannot read the headers: never asked, never trusted.
        (MailboxConnection.Tier.METADATA, True, False),
        (MailboxConnection.Tier.CONTENT, False, True),
        (MailboxConnection.Tier.CONTENT, ProviderError("MICROSOFT answered 503"), True),
    ],
)
def test_unverified_outlook_mail_never_acts(
    connection_with_pack, verify_verdict, tier, verdict, asked
):
    connection = _outlook(connection_with_pack, tier)
    provider = _Outlook((_mail("m-tum", "admissions@tum.de"),), verdict=verdict)

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    assert bool(provider.verified) is asked
    with tenant_transaction(connection.tenant_id):
        assert MailSignal.objects.get().trusted is False
        assert DeviceAction.objects.count() == 0


@pytest.mark.django_db
def test_an_unverified_verification_mail_tells_the_student_without_a_link(
    connection_with_pack, verify_verdict
):
    connection = _outlook(connection_with_pack, MailboxConnection.Tier.CONTENT)
    provider = _Outlook((_mail("m-tum", "admissions@tum.de"),), verdict=False)

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        messages = list(Notification.objects.values_list("message", "urgent"))
    card = [(text, urgent) for text, urgent in messages if "confirm your email" in text]
    assert card == [
        (
            "tum.de (unverified) asked you to confirm your email address. "
            "Open the message in your inbox and use its link.",
            False,
        )
    ]
    assert all("https://" not in text for text, _urgent in messages)


@pytest.mark.django_db
def test_a_verification_card_is_never_urgent_even_when_trusted(
    connection_with_pack, verify_verdict
):
    """The extension opens a trusted link itself; escalating to email and a
    counsellor for a mail already handled would be noise."""
    connection = _outlook(connection_with_pack, MailboxConnection.Tier.CONTENT)
    provider = _Outlook((_mail("m-tum", "admissions@tum.de"),), verdict=True)

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())

    with tenant_transaction(connection.tenant_id):
        assert not Notification.objects.filter(
            message__contains="confirm your email", urgent=True
        ).exists()


@pytest.mark.django_db
def test_a_reconnect_does_not_announce_or_reclassify_mail_already_seen(
    connection_with_pack, monkeypatch
):
    """Measured live: switching tier made a second connection, which told the
    student about the same email again."""
    first = connection_with_pack
    header = _mail("m-tum", "admissions@tum.de")
    with tenant_scope(first.tenant_id):
        sync_connection(first, provider=FakeProvider((header,)), secrets_client=_grant())
    with tenant_scope(first.tenant_id), tenant_transaction(first.tenant_id):
        MailSignal.objects.filter(connection=first).update(label="OTHER")
        MailboxConnection.objects.filter(id=first.id).update(
            status=MailboxConnection.Status.REVOKED
        )
        second = MailboxConnection.objects.create(
            tenant_id=first.tenant_id,
            membership=first.membership,
            provider=first.provider,
            address=first.address,
        )
        before = Notification.objects.count()
    classified: list[str] = []
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message",
        lambda **kwargs: classified.append("called") or _VERIFY,
    )

    with tenant_scope(second.tenant_id):
        created = sync_connection(second, provider=FakeProvider((header,)), secrets_client=_grant())

    assert len(created) == 1  # recorded on the new connection
    assert created[0].label == "OTHER"  # inherited, not paid for again
    assert classified == []
    with tenant_transaction(second.tenant_id):
        assert Notification.objects.count() == before


def test_the_verdict_binds_the_listing_s_sender_not_a_second_fetch() -> None:
    """Round 3, residual 3: the domain compared is the one the mail is filed under,
    which is the listing's sender -- not a `from` fetched again on the verdict call."""
    from apps.mailbox.providers import MicrosoftMailbox
    from tests.mailbox.test_providers import FakeHTTP

    detail = {"internetMessageHeaders": [_h("Authentication-Results", _MS_UFAZ)]}
    for sender, expected in (("info@ufaz.az", True), ("info@tum.de", False)):
        http = FakeHTTP({"https://graph.microsoft.com/v1.0/me/messages/AAMk1": detail})
        mailbox = MicrosoftMailbox(http=http)
        verdict = mailbox.delivery_verified(access_token="at", message_id="AAMk1", sender=sender)
        assert verdict is expected
        [(_method, url, _headers)] = http.requests
        assert url.endswith("%24select=internetMessageHeaders")
