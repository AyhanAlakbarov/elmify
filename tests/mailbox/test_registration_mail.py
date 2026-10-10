"""The registration-mail expectation, resolved by the mail itself (spec §2a).

Tagged mail says the portal keeps the tag. Untagged mail from the portal the
student just registered on says it strips it. Nothing else is inferred.
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.mailbox.classify import MailVerdict
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import sync_connection
from apps.portals.models import PortalAccount, PortalForm
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.mailbox.conftest import FakeProvider, _grant

pytestmark = pytest.mark.django_db
TAGGED = "student+ab12cd@gmail.test"


@pytest.fixture(autouse=True)
def _no_paid_classification(monkeypatch):
    monkeypatch.setattr(
        "apps.mailbox.sync.classify_message", lambda **_: MailVerdict(label="OTHER")
    )


@pytest.fixture
def registering(connection_with_pack):
    """connection_with_pack's student registered on portal.uni-bonn.de with a
    tag two minutes ago."""
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
            registered_at=timezone.now() - timedelta(minutes=2),
        )
    return connection


def _header(sender, *, to, received_at=None):
    return MessageHeader(
        message_id=f"m-{sender}-{to}",
        sender=sender,
        received_at=received_at or timezone.now(),
        recipients=(to,),
    )


def _sync(connection, *headers):
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider(headers), secrets_client=_grant())


def _outcome(connection):
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        return PortalAccount.objects.get(student=connection.membership).tag_outcome


def _shared():
    return PortalForm.objects.get(portal_host="portal.uni-bonn.de").tag_status


def test_mail_to_the_tag_measures_keeps(registering):
    _sync(registering, _header("noreply@uni-bonn.de", to=TAGGED))

    assert _outcome(registering) == "KEEPS"
    assert _shared() == "UNKNOWN"  # mail measures the account only (review M2)


def test_untagged_mail_from_the_portal_inside_the_window_measures_strips(registering):
    _sync(registering, _header("noreply@mail.uni-bonn.de", to="student@gmail.test"))

    assert _outcome(registering) == "STRIPS"
    assert _shared() == "UNKNOWN"


def test_untagged_mail_from_before_the_registration_says_nothing(registering):
    """A first sync reads back to when tracking began; a portal email from
    before the student registered is not the registration email."""
    _sync(
        registering,
        _header(
            "noreply@uni-bonn.de",
            to="student@gmail.test",
            received_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
    )

    assert _outcome(registering) == "UNKNOWN"


def test_untagged_mail_after_the_window_says_nothing(registering):
    with tenant_scope(registering.tenant_id), tenant_transaction(registering.tenant_id):
        PortalAccount.objects.filter(student=registering.membership).update(
            registered_at=timezone.now() - timedelta(hours=2)
        )

    _sync(registering, _header("noreply@uni-bonn.de", to="student@gmail.test"))

    assert _outcome(registering) == "UNKNOWN"
    assert _shared() == "UNKNOWN"


def test_untagged_mail_from_another_pack_domain_says_nothing(registering):
    """tum.de is in the pack, not the portal the student registered on."""
    _sync(registering, _header("noreply@tum.de", to="student@gmail.test"))

    assert _outcome(registering) == "UNKNOWN"


def test_a_set_shared_status_survives_the_mail(registering):
    PortalForm.objects.filter(portal_host="portal.uni-bonn.de").update(
        tag_status=PortalForm.TagStatus.KEEPS
    )

    _sync(registering, _header("noreply@uni-bonn.de", to="student@gmail.test"))

    assert _outcome(registering) == "STRIPS"
    assert _shared() == "KEEPS"


def test_untagged_mail_newer_than_tagged_mail_in_one_sync_still_measures_keeps(registering):
    """Fix round 1, finding 1. Providers list newest first, so a naive
    inline-write would record the newer untagged signal's STRIPS before the
    older tagged signal's KEEPS is ever read -- the weaker evidence wins."""
    older = timezone.now() - timedelta(minutes=1)
    _sync(
        registering,
        _header("prof@uni-bonn.de", to="student@gmail.test"),  # untagged, newest
        _header("noreply@uni-bonn.de", to=TAGGED, received_at=older),  # tagged, older
    )

    assert _outcome(registering) == "KEEPS"
    assert _shared() == "UNKNOWN"  # mail measures the account only (review M2)


def test_tagged_mail_newer_than_untagged_mail_in_one_sync_measures_keeps(registering):
    """Same pair, opposite order -- the outcome must not depend on order."""
    older = timezone.now() - timedelta(minutes=1)
    _sync(
        registering,
        _header("noreply@uni-bonn.de", to=TAGGED),  # tagged, newest
        _header("prof@uni-bonn.de", to="student@gmail.test", received_at=older),  # untagged, older
    )

    assert _outcome(registering) == "KEEPS"
    assert _shared() == "UNKNOWN"  # mail measures the account only (review M2)


def test_two_awaiting_accounts_sharing_a_key_measure_nothing(connection_with_pack):
    """Fix round 1, finding 2. portal.uni-bonn.de and apply.uni-bonn.de both
    key as uni-bonn.de; an unordered query must not let `setdefault` hand
    untagged mail to whichever account happens to come back first."""
    connection = connection_with_pack
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="portal.uni-bonn.de",
            tag="ab12cd",
            address=TAGGED,
            registered_at=timezone.now() - timedelta(minutes=2),
        )
        PortalAccount.objects.create(
            tenant_id=connection.tenant_id,
            student=connection.membership,
            portal_host="apply.uni-bonn.de",
            tag="zz9988",
            address="student+zz9988@gmail.test",
            registered_at=timezone.now() - timedelta(minutes=2),
        )

    _sync(connection, _header("noreply@uni-bonn.de", to="student@gmail.test"))

    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        outcomes = set(
            PortalAccount.objects.filter(student=connection.membership).values_list(
                "tag_outcome", flat=True
            )
        )
    assert outcomes == {"UNKNOWN"}


def _awaiting_on_apply(agency, student):
    """The reviewer's input: registered on apply.example.edu two minutes ago."""
    PortalForm.objects.create(portal_host="apply.example.edu", form_key="apply")
    PortalAccount.objects.create(
        tenant=agency, student=student, portal_host="apply.example.edu", tag="ab12cd",
        address="leyla.apply+ab12cd@outlook.com",
        registered_at=timezone.now() - timedelta(minutes=2),
    )


def test_a_lone_awaiting_portal_keys_on_its_registrable_domain(agency_a, membership_a):
    """Positive control for the two below: nothing else claims example.edu."""
    from apps.mailbox.sync import _awaiting_registration

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _awaiting_on_apply(agency_a, membership_a)
        assert "example.edu" in _awaiting_registration(membership_a, timezone.now())


def test_another_portal_account_on_the_same_university_drops_the_key(agency_a, membership_a):
    """M2 (final review): plain mail from the student's OTHER portal at the same
    university (campus.example.edu, measured long ago) is not apply's
    registration mail, so the shared key measures nothing."""
    from apps.mailbox.sync import _awaiting_registration

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _awaiting_on_apply(agency_a, membership_a)
        PortalAccount.objects.create(
            tenant=agency_a, student=membership_a, portal_host="campus.example.edu",
            tag="zz9988", address="leyla.apply+zz9988@outlook.com",
            tag_outcome=PortalForm.TagStatus.KEEPS,
        )
        assert "example.edu" not in _awaiting_registration(membership_a, timezone.now())


def test_another_application_on_the_same_university_drops_the_key(agency_a, membership_a):
    """M2, the same through an application with no issued address: its portal's
    mail is read (vouched_senders) all the same."""
    from uuid import uuid4

    from apps.mailbox.sync import _awaiting_registration
    from apps.portals.models import Application

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _awaiting_on_apply(agency_a, membership_a)
        campus = PortalForm.objects.create(portal_host="campus.example.edu", form_key="campus")
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=campus
        )
        assert "example.edu" not in _awaiting_registration(membership_a, timezone.now())


def _rejected(connection, *, by_student):
    """The account's own REJECTS: the extension's page reading, or the
    student's own "use my plain address" button."""
    from apps.portals.tags import record_tag_outcome

    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        account = PortalAccount.objects.get(student=connection.membership)
        record_tag_outcome(account, PortalForm.TagStatus.REJECTS, force=by_student)
        assert account.address == "student@gmail.test"


def _account(connection):
    with tenant_scope(connection.tenant_id), tenant_transaction(connection.tenant_id):
        return PortalAccount.objects.get(student=connection.membership)


def test_mail_to_the_tag_corrects_a_false_rejects(registering):
    """M3 (final review): a `page` REJECTS rewrote the address to the plain one,
    but the portal holds the tag after all. Mail to the tag proves it: the
    account goes back to KEEPS and its tagged address -- and only the account."""
    _rejected(registering, by_student=False)

    _sync(registering, _header("noreply@uni-bonn.de", to=TAGGED))

    account = _account(registering)
    assert (account.tag_outcome, account.address) == ("KEEPS", TAGGED)
    assert _shared() == "UNKNOWN"


def test_mail_to_the_tag_never_overrides_the_students_own_button(registering):
    """The student pressed "use my plain address": their word on their own form
    stands, whatever mail to the old tag says."""
    _rejected(registering, by_student=True)

    _sync(registering, _header("noreply@uni-bonn.de", to=TAGGED))

    account = _account(registering)
    assert (account.tag_outcome, account.address) == ("REJECTS", "student@gmail.test")
    assert _shared() == "UNKNOWN"
