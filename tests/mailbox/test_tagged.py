"""Mail sent to a tag we issued: read from any sender, learned, trusted only when clean."""

from datetime import UTC, datetime

import pytest

from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import LearnedSender, MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import sync_connection
from apps.portals.models import DeviceAction, PortalAccount
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db
TAGGED = "student+ab12cd@gmail.test"


@pytest.fixture
def tagged_account(connection_with_pack):
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
        )
    return connection


def _header(message_id, sender, *, to=TAGGED, junk=False):
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=(to,),
        junk=junk,
    )


def test_tagged_mail_from_an_unknown_vendor_is_read_and_its_sender_learned(tagged_account):
    connection = tagged_account
    provider = FakeProvider((_header("m1", "no-reply@mail-eu.portalvendor.com"),))

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(connection, provider=provider, secrets_client=_grant())
        learned = LearnedSender.objects.get(student=connection.membership)

    assert signal.sender_domain == "portalvendor.com"
    assert signal.trusted is True
    assert learned.domain == "portalvendor.com"
    assert learned.portal_host == "portal.uni-bonn.de"
    assert learned.confirmed_at is None


def test_untagged_junk_is_never_read(connection_with_pack):
    connection = connection_with_pack
    provider = FakeProvider((_header("m1", "a@tum.de", to="student@gmail.test", junk=True),))

    with tenant_scope(connection.tenant_id):
        assert sync_connection(connection, provider=provider, secrets_client=_grant()) == []


def test_tagged_junk_is_read_but_not_trusted(tagged_account):
    connection = tagged_account
    provider = FakeProvider((_header("m1", "a@uni-bonn.de", junk=True),))

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert signal.trusted is False


def test_a_leaked_tag_cannot_open_a_link_off_the_allowlist(tagged_account, monkeypatch):
    """A scammer who learned the tag mails it from their own domain with a link to it."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(
            label="VERIFICATION",
            action_kind="OPEN_VERIFICATION_URL",
            action_value="https://evil.example.org/verify",
        ),
    )
    connection = tagged_account
    provider = FakeProvider((_header("m1", "x@evil.example.org"),))

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
        assert DeviceAction.objects.count() == 0


def test_a_trusted_tagged_message_with_an_allowlisted_link_does_queue(tagged_account, monkeypatch):
    """Positive control for the test above: the same stub, a link on the allowlist."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(
            label="VERIFICATION",
            action_kind="OPEN_VERIFICATION_URL",
            action_value="https://portal.uni-bonn.de/verify",
        ),
    )
    connection = tagged_account
    provider = FakeProvider((_header("m1", "a@uni-bonn.de"),))

    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
        assert DeviceAction.objects.count() == 1


def test_mail_from_an_unconfirmed_learned_sender_is_read_but_not_trusted(tagged_account):
    connection = tagged_account
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        LearnedSender.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            domain="portalvendor.com",
            portal_host="portal.uni-bonn.de",
        )
    header = MessageHeader(
        message_id="m2",
        sender="no-reply@portalvendor.com",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )

    assert signal.trusted is False


def test_the_student_confirms_a_learned_sender(student_client, agency_a, membership_a):
    client, _student = student_client
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        learned = LearnedSender.objects.create(
            tenant=agency_a, student=membership_a, domain="portalvendor.com", portal_host="x"
        )

    response = client.post(f"/mailbox/senders/{learned.id}/confirm/")

    assert response.status_code == 200
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        learned.refresh_from_db()
    assert learned.confirmed_at is not None


def test_signals_stay_one_per_message(tagged_account):
    connection = tagged_account
    provider = FakeProvider((_header("m1", "a@uni-bonn.de"),))
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
        assert MailSignal.objects.count() == 1


def test_tagged_mail_from_a_free_mail_domain_is_read_but_never_learned(tagged_account, monkeypatch):
    """Fix round 1, finding 2 (Important): a leaked tag mailed from gmail.com
    (or any other free-mail provider) must not teach the platform to read
    every gmail.com sender's mail afterward -- gmail.com names millions of
    unrelated people, not one institution. The tagged message itself is still
    read (reading is broader than learning); a second, unrelated gmail.com
    message to the student's plain address must stay unread."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = tagged_account
    provider = FakeProvider(
        (
            _header("m1", "scammer@gmail.com"),
            _header("m2", "mum@gmail.com", to="student@gmail.test"),
        )
    )

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert [s.provider_message_id for s in signals] == ["m1"]
    assert not LearnedSender.objects.filter(domain="gmail.com").exists()


def test_tagged_mail_from_a_shared_platform_apex_is_read_but_never_learned(
    tagged_account, monkeypatch
):
    """Security finding 2026-09-26 follow-up: no-reply@smapply.io is the
    platform apex itself, not a customer subdomain, but it is still a
    _SHARED_PLATFORMS entry -- _key returns it verbatim ("smapply.io", not a
    per-customer host) because domain == host here. Learning it would let
    host_in's suffix match (".smapply.io") and link_hosts admit every other
    smapply.io customer's mail and links once the student confirms it. The
    tagged message itself is still read."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = tagged_account
    provider = FakeProvider((_header("m1", "no-reply@smapply.io"),))

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert [s.provider_message_id for s in signals] == ["m1"]
    assert not LearnedSender.objects.filter(domain="smapply.io").exists()


def test_tagged_mail_from_a_shared_platform_subdomain_is_read_but_never_learned(
    tagged_account, monkeypatch
):
    """Security finding 2026-09-26 follow-up 3: eu.qualtrics.com is not the
    platform's bare apex -- unlike smapply.io, Qualtrics' own subdomains are
    shared across every customer's surveys rather than dedicated to one, so
    _key still returns it verbatim and learning it would admit every other
    customer's mail the same way learning the apex would. The tagged
    message itself is still read."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = tagged_account
    provider = FakeProvider((_header("m1", "no-reply@eu.qualtrics.com"),))

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert [s.provider_message_id for s in signals] == ["m1"]
    assert not LearnedSender.objects.filter(domain="eu.qualtrics.com").exists()


def test_tagged_mail_from_a_genuine_platform_subdomain_is_read_but_never_learned(
    tagged_account, monkeypatch
):
    """Pins the controller ruling on the cleanup brief's docstring correction
    (2026-09-26): kth.smapply.io is a real institution's own corner of
    smapply.io, not an attacker's, but `learnable_domain`'s private-aware
    registrable-domain check cannot tell the two apart -- both collapse to
    "smapply.io" -- so it refuses this one too (fail-closed, accepted). That
    costs nothing here: this portal is not named by any Application or pack
    entry, so nothing vouches for it either way, and the tagged message is
    still read regardless -- reading is broader than learning."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = tagged_account
    provider = FakeProvider((_header("m1", "no-reply@kth.smapply.io"),))

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())

    assert [s.provider_message_id for s in signals] == ["m1"]
    assert not LearnedSender.objects.filter(domain="kth.smapply.io").exists()


def test_a_pack_domain_is_never_unconfirmed_even_with_an_earlier_leaked_learn(
    tagged_account, monkeypatch
):
    """Fix round 1, finding 3 (Important): an unconfirmed LearnedSender row for
    a domain the pack ALREADY justifies (tum.de) must not downgrade that
    domain's trust -- otherwise a leaked tag pre-poisons a real university and
    a later genuine, authenticated tum.de message is read but never acted on."""
    from apps.mailbox import sync as sync_module

    connection = tagged_account
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        LearnedSender.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            domain="tum.de",
            portal_host="portal.uni-bonn.de",
        )
    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(
            label="VERIFICATION",
            action_kind="OPEN_VERIFICATION_URL",
            action_value="https://tum.de/verify",
        ),
    )
    header = MessageHeader(
        message_id="m2",
        sender="noreply@tum.de",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )
        queued = DeviceAction.objects.count()

    assert (signal.trusted, queued) == (True, 1)


def test_a_plus_in_the_student_s_own_address_is_not_a_tag(connection_with_pack, monkeypatch):
    """Final review I7: `tagged()` returns an address that already holds a "+"
    unchanged, so the PortalAccount's address was the student's plain one --
    and every stranger's mail to it looked tagged, trusted, and able to queue
    a code and move SUBMITTED -> CONFIRMED."""
    from apps.mailbox import sync as sync_module
    from apps.portals.models import Application
    from apps.portals.tags import portal_address

    connection = connection_with_pack
    base = "student+me@outlook.com"
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.membership.application_email = base
        connection.membership.save(update_fields=["application_email"])
        application = Application.objects.get(student=connection.membership)
        application.state = Application.State.SUBMITTED
        application.save(update_fields=["state"])
        assert portal_address(application) == base
    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(label="RECEIVED", action_kind="TYPE_CODE", action_value="123456"),
    )
    provider = FakeProvider((_header("m1", "x@scammer-example.com", to=base),))

    with tenant_scope(connection.tenant_id):
        signals = sync_connection(connection, provider=provider, secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            assert DeviceAction.objects.count() == 0
            assert Application.objects.get().state == Application.State.SUBMITTED
            assert not LearnedSender.objects.exists()

    assert signals == []
    assert provider.bodies_fetched == []


@pytest.mark.parametrize(
    ("connection_address", "tag_address"),
    [
        # The connected mailbox is the student's own university M365 account.
        ("student@uni-koeln.de", TAGGED),
        # The tag itself lives on the university domain.
        ("student@gmail.test", "student+ab12cd@uni-koeln.de"),
    ],
)
def test_the_student_s_own_domain_is_read_but_never_learned(
    connection_with_pack, connection_address, tag_address
):
    """Final review M4, with a real registrable domain (a `.test` one is
    blanked by sender_key before the guard is ever reached): a tagged mail
    from the student's own university domain -- their own address, a
    classmate, the IT desk -- is read, and never becomes a learned sender
    that would then read everyone at that university."""
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        connection.address = connection_address
        connection.save(update_fields=["address"])
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=tag_address,
        )
    provider = FakeProvider((_header("m1", "helpdesk@uni-koeln.de", to=tag_address),))

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(connection, provider=provider, secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            learned = LearnedSender.objects.exists()

    assert signal.sender_domain == "uni-koeln.de"
    assert learned is False


@pytest.mark.parametrize("provider_authenticated", [False, True])
def test_only_a_provider_authenticated_decision_records_an_outcome(
    tagged_account, monkeypatch, provider_authenticated
):
    """Fix round 1, item 3. A tag makes mail trusted enough to act on, but the tag
    can leak: an outcome tells a family the result, so it needs the provider's own
    delivery verdict. Tag-only mail still marks the decision available."""
    from apps.mailbox import sync as sync_module
    from apps.mailbox.decision_reader import DecisionReading
    from apps.portals.models import Application

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    monkeypatch.setattr(
        sync_module,
        "read_decision",
        lambda *_a, **_k: DecisionReading(True, "ADMITTED", "", False, measured=True),
    )
    connection = tagged_account
    header = _header("m1", "a@uni-bonn.de").model_copy(
        update={"authenticated": provider_authenticated}
    )

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )
        application = Application.objects.get(id=signal.application_id)

    assert signal.trusted is True
    assert application.decision_available_at is not None
    assert application.outcome == ("ADMITTED" if provider_authenticated else "")


@pytest.mark.parametrize("confirmed", [False, True])
def test_a_learned_sender_writes_an_outcome_only_once_the_student_confirmed_it(
    tagged_account, monkeypatch, confirmed
):
    """Re-review clarification of item 3: a student-confirmed learned sender the
    provider authenticated may write an outcome; an unconfirmed one never."""
    from django.utils import timezone

    from apps.mailbox import sync as sync_module
    from apps.mailbox.decision_reader import DecisionReading
    from apps.portals.models import Application

    connection = tagged_account
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        LearnedSender.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            domain="portalvendor.com",
            portal_host="portal.uni-bonn.de",
            confirmed_at=timezone.now() if confirmed else None,
        )
    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    monkeypatch.setattr(
        sync_module,
        "read_decision",
        lambda *_a, **_k: DecisionReading(True, "ADMITTED", "", False, measured=True),
    )
    header = _header("m1", "no-reply@portalvendor.com").model_copy(update={"authenticated": True})

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )
        application = Application.objects.get(id=signal.application_id)

    assert signal.sender_authenticated is confirmed
    assert application.decision_available_at is not None
    assert application.outcome == ("ADMITTED" if confirmed else "")


def test_an_authenticated_tagged_mail_from_another_application_s_domain_is_not_authenticated(
    tagged_account, monkeypatch
):
    """Final review M3: DMARC proves the mail came from campus.tum.de's university,
    not that it is about the Bonn application whose tag it was sent to. Filed
    authenticated on Bonn, a measured reading would record Bonn's outcome from
    TUM's letter. Only a domain vouched for this application, or for none, is
    tied to it."""
    from uuid import uuid4

    from apps.mailbox import sync as sync_module
    from apps.mailbox.decision_reader import DecisionReading
    from apps.portals.models import Application, PortalForm

    connection = tagged_account
    form = PortalForm.objects.create(portal_host="campus.tum.de", form_key="apply")
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        Application.objects.create(
            tenant_id=connection.tenant_id, student=connection.membership,
            program_id=uuid4(), portal_form=form,
        )
    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    monkeypatch.setattr(
        sync_module,
        "read_decision",
        lambda *_a, **_k: DecisionReading(True, "ADMITTED", "", False, measured=True),
    )
    header = _header("m1", "a@tum.de").model_copy(update={"authenticated": True})

    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )
        bonn = Application.objects.get(portal_form__portal_host="portal.uni-bonn.de")

    assert signal.application_id == bonn.id
    assert signal.trusted is True
    assert signal.sender_authenticated is False
    assert bonn.outcome == ""
