from datetime import UTC, datetime, timedelta

import pytest

from apps.concierge.models import Notification
from apps.mailbox.classify import ClassificationFailure, MailVerdict
from apps.mailbox.models import MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import MAX_CLASSIFY_ATTEMPTS, MAX_RETRIES_PER_SYNC, sync_connection
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db


def _authenticated(message_id="m1", sender="admissions@tum.de"):
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        authenticated=True,
    )


@pytest.mark.parametrize("label", ["DECISION", "INTERVIEW", "DOCUMENT_REQUEST", "FEE"])
def test_a_trusted_message_that_needs_the_student_raises_an_urgent_alert(
    connection_with_pack, monkeypatch, label
):
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label=label))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        sync_connection(
            connection, provider=FakeProvider((_authenticated(),)), secrets_client=_grant()
        )
        urgent = Notification.objects.filter(recipient=connection.membership, urgent=True)
        assert urgent.count() == 1
        assert "tum.de" in urgent.get().message


def test_an_untrusted_decision_raises_no_urgent_alert(connection_with_pack, monkeypatch):
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    header = MessageHeader(
        message_id="m1", sender="a@tum.de", received_at=datetime(2026, 9, 20, tzinfo=UTC)
    )
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((header,)), secrets_client=_grant())
        assert not Notification.objects.filter(urgent=True).exists()


def test_a_failed_classification_is_retried_and_then_shown(connection_with_pack, monkeypatch):
    from apps.mailbox import sync as sync_module

    def fail(**_):
        raise ClassificationFailure("down")

    monkeypatch.setattr(sync_module, "classify_message", fail)
    monkeypatch.setattr(sync_module, "rate_limited", lambda *a, **k: False)
    connection = connection_with_pack
    provider = FakeProvider((_authenticated(),))
    with tenant_scope(connection.tenant_id):
        for _ in range(MAX_CLASSIFY_ATTEMPTS):
            sync_connection(connection, provider=provider, secrets_client=_grant())
        signal = MailSignal.objects.get()
        assert signal.classify_attempts == MAX_CLASSIFY_ATTEMPTS
        assert Notification.objects.filter(message__icontains="open the message").count() == 1
        assert len(provider.bodies_fetched) == MAX_CLASSIFY_ATTEMPTS


def test_the_retry_pass_fetches_at_most_ten_bodies_in_one_sync(connection_with_pack, monkeypatch):
    """Fix round 1, finding 1: an unbounded retry query is a provider-quota
    problem after a classify outage -- exactly what SYNC_LIMIT elsewhere
    exists to prevent."""
    from apps.mailbox import sync as sync_module

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="OTHER"))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        for i in range(12):
            MailSignal.objects.create(
                tenant_id=connection.tenant_id,
                connection=connection,
                provider_message_id=f"retry-{i}",
                sender_domain="tum.de",
                received_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=i),
                classify_attempts=1,
            )
    provider = FakeProvider(())
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=provider, secrets_client=_grant())
    assert len(provider.bodies_fetched) == MAX_RETRIES_PER_SYNC
    # Oldest first: the ten earliest, never a mix that skips one of them.
    assert set(provider.bodies_fetched) == {f"retry-{i}" for i in range(MAX_RETRIES_PER_SYNC)}


def test_overlapping_syncs_do_not_double_a_card_or_the_attempt_count(
    connection_with_pack, monkeypatch
):
    """Fix round 1, finding 2: the increment-then-reread was check-then-act.
    Simulate a second, overlapping sync recording this exact failure between
    this sync's retry query reading the signal and this call's own failure
    being recorded -- from inside the stubbed classify_message, as the
    finding directs."""
    from apps.mailbox import sync as sync_module

    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        signal = MailSignal.objects.create(
            tenant_id=connection.tenant_id,
            connection=connection,
            provider_message_id="racey",
            sender_domain="tum.de",
            received_at=datetime(2026, 9, 1, tzinfo=UTC),
            classify_attempts=MAX_CLASSIFY_ATTEMPTS - 1,
        )

    def fail(**_):
        # The other overlapping sync already reached the ceiling for this
        # same signal and created its own card -- before this call's own
        # failure is recorded.
        with tenant_transaction(connection.tenant_id):
            MailSignal.objects.filter(pk=signal.pk).update(
                classify_attempts=MAX_CLASSIFY_ATTEMPTS
            )
            sync_module._card(
                connection,
                stage=sync_module.RoadmapItem.Stage.MONITORING,
                message="tum.de wrote to you. Open the message to see what it says.",
            )
        raise ClassificationFailure("down")

    monkeypatch.setattr(sync_module, "classify_message", fail)
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider(()), secrets_client=_grant())

    signal.refresh_from_db()
    assert signal.classify_attempts == MAX_CLASSIFY_ATTEMPTS
    assert Notification.objects.filter(message__icontains="open the message").count() == 1


def _plain(message_id="m1", sender="admissions@tum.de", minutes=0):
    return MessageHeader(
        message_id=message_id,
        sender=sender,
        received_at=datetime(2026, 9, 20, tzinfo=UTC) + timedelta(minutes=minutes),
    )


def test_an_untrusted_decision_from_a_vouched_domain_still_tells_the_student(
    connection_with_pack, monkeypatch
):
    """Final review I6(a): on Microsoft `authenticated` is always False, so no
    plain-address mail ever raised a decision/interview/request/fee card. A
    domain the pack or an application vouches for gets the same label card,
    not urgent, and never a link -- reading is broader than acting."""
    from apps.mailbox import sync as sync_module
    from apps.portals.models import DeviceAction

    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(
            label="DECISION",
            action_kind="OPEN_VERIFICATION_URL",
            action_value="https://tum.de/verify?t=1",
        ),
    )
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((_plain(),)), secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            cards = list(
                Notification.objects.filter(message__contains="sent a decision").values_list(
                    "message", "urgent"
                )
            )
            assert DeviceAction.objects.count() == 0
    assert cards == [
        ("tum.de (unverified) sent a decision. Open your portal to read it.", False)
    ]


def test_an_untrusted_interview_states_no_time_and_sets_no_deadline(
    connection_with_pack, monkeypatch
):
    """Task 11 minor: an unverified mail's stated time is not the platform's to
    repeat or sort by (Task 10's trusted-only rule). The generic card, the
    default horizon."""
    from django.utils import timezone

    from apps.concierge.models import RoadmapItem
    from apps.mailbox import sync as sync_module

    when = (timezone.now() + timedelta(days=30)).replace(microsecond=0)
    monkeypatch.setattr(
        sync_module,
        "classify_message",
        lambda **_: MailVerdict(label="INTERVIEW", interview_at=when.isoformat()),
    )
    connection = connection_with_pack
    before = timezone.now()
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((_plain(),)), secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            note = Notification.objects.get(
                recipient=connection.membership, message__contains="interview"
            )
            item = RoadmapItem.objects.get(id=note.roadmap_item_id)
    assert note.message == (
        "tum.de (unverified) invited you to an interview. Check the time and reply."
    )
    assert before + timedelta(days=6) < item.deadline < before + timedelta(days=8)


def test_an_untrusted_decision_from_a_learned_domain_raises_no_label_card(
    connection_with_pack, monkeypatch
):
    """Only the pack and the applications vouch: a learned domain -- which a
    leaked tag can create for anyone -- does not."""
    from apps.mailbox import sync as sync_module
    from apps.mailbox.models import LearnedSender

    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id):
        with tenant_transaction(connection.tenant_id):
            LearnedSender.objects.create(
                tenant_id=connection.tenant_id,
                student=connection.membership,
                domain="portalvendor.com",
                portal_host="portal.uni-bonn.de",
            )
        [signal] = sync_connection(
            connection,
            provider=FakeProvider((_plain(sender="x@portalvendor.com"),)),
            secrets_client=_grant(),
        )
        with tenant_transaction(connection.tenant_id):
            messages = list(Notification.objects.values_list("message", flat=True))
    assert signal.label == "DECISION"
    assert messages == ["portalvendor.com wrote to you."]


def test_a_tagged_decision_on_a_shared_portal_says_which_portal_and_how_many(
    connection_with_pack, monkeypatch
):
    """Final review I6(b): two applications on one portal host, so the tag
    cannot say which one. The card says so instead of guessing -- and still
    carries nothing from the email itself."""
    from uuid import uuid4

    from apps.mailbox import sync as sync_module
    from apps.portals.models import Application, PortalAccount, PortalForm

    tagged = "student+ab12cd@gmail.test"
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=tagged,
        )
        Application.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            program_id=uuid4(),
            portal_form=PortalForm.objects.get(portal_host="portal.uni-bonn.de"),
        )
    monkeypatch.setattr(sync_module, "classify_message", lambda **_: MailVerdict(label="DECISION"))
    header = MessageHeader(
        message_id="m1",
        sender="admissions@uni-bonn.de",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=(tagged,),
    )
    with tenant_scope(connection.tenant_id):
        [signal] = sync_connection(
            connection, provider=FakeProvider((header,)), secrets_client=_grant()
        )
        with tenant_transaction(connection.tenant_id):
            card = Notification.objects.get(urgent=True)
    assert signal.application_id is None
    assert card.message == (
        "uni-bonn.de wrote about one of your 2 applications on "
        "portal.uni-bonn.de. Open your portal to see which."
    )


@pytest.mark.parametrize(("offset", "keeps_deadline"), [(-1, False), (3, True)])
def test_a_label_alert_uses_the_application_deadline_only_while_it_is_ahead(
    signal_on_application, offset, keeps_deadline
):
    """Final review M1: a past deadline put every alert straight onto the
    4-hour counsellor ladder."""
    from django.utils import timezone

    from apps.concierge.models import RoadmapItem
    from apps.mailbox.actions import apply_verdict

    signal = signal_on_application("portal.uni-bonn.de")
    deadline = timezone.now() + timedelta(days=offset)
    with tenant_transaction(signal.tenant_id):
        signal.application.deadline = deadline
        signal.application.save(update_fields=["deadline"])
        apply_verdict(signal, MailVerdict(label="DECISION"), link_hosts=(), authenticated=True)
        item = RoadmapItem.objects.get(stage=RoadmapItem.Stage.MONITORING)

    if keeps_deadline:
        assert item.deadline == deadline
    else:
        assert item.deadline > timezone.now() + timedelta(days=6)


@pytest.mark.parametrize(
    "meanwhile",
    [
        # Another sync's failure took the row to the ceiling: vouched() would
        # now read an automatic label as one the student named.
        {"classify_attempts": MAX_CLASSIFY_ATTEMPTS},
        # The student named the message themselves.
        {"label": "DOCUMENT_REQUEST", "document_name": "Passport"},
    ],
)
def test_a_verdict_lands_only_on_the_row_it_was_read_for(
    connection_with_pack, monkeypatch, meanwhile
):
    """Task 15 minor: the success path locks the row and re-checks it is still
    unlabelled at the attempt count it was read at; otherwise it writes nothing."""
    from apps.mailbox import sync as sync_module

    connection = connection_with_pack

    def classify(**_):
        with tenant_transaction(connection.tenant_id):
            MailSignal.objects.filter(provider_message_id="m1").update(**meanwhile)
        return MailVerdict(label="DOCUMENT_REQUEST", document_name="Bank statement")

    monkeypatch.setattr(sync_module, "classify_message", classify)
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((_plain(),)), secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            signal = MailSignal.objects.get(provider_message_id="m1")
    assert (signal.label, signal.document_name) == (
        meanwhile.get("label", ""), meanwhile.get("document_name", "")
    )
