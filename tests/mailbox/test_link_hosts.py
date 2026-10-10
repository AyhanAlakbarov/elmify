"""A link is opened only on a host the pack or an application names in full.

Security finding 2026-09-26 (vuln 1): the allowlist key is a registrable
domain, so a pack link to kth.smapply.io keyed as smapply.io -- and every other
smapply customer's page became a host this student's browser would be sent to.
Reading keeps its registrable keys; acting checks full hosts (filter.link_hosts).
"""

from datetime import UTC, datetime

import pytest

from apps.mailbox.classify import MailVerdict
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.mailbox.providers import MessageHeader
from apps.mailbox.sync import sync_connection
from apps.portals.models import DeviceAction, PortalAccount
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.funding.conftest import make_published_pack, make_run
from tests.mailbox.conftest import FakeProvider, _evidenced_candidate, _grant

pytestmark = pytest.mark.django_db
TAGGED = "student+ab12cd@gmail.test"


def _connection(agency, student, source_url: str, *, tag_portal: str = "") -> MailboxConnection:
    run = make_run(agency, student)
    candidate = _evidenced_candidate(agency, run, program_name="MSc", source_url=source_url)
    make_published_pack(agency, run, (candidate,))
    with tenant_scope(agency.id), tenant_transaction(agency.id):
        if tag_portal:
            PortalAccount.objects.create(
                tenant_id=agency.id,
                student=student,
                portal_host=tag_portal,
                tag="ab12cd",
                address=TAGGED,
            )
        return MailboxConnection.objects.create(
            tenant_id=agency.id,
            membership=student,
            provider=MailboxConnection.Provider.GOOGLE,
            address="student@gmail.test",
        )


def _sync(connection, monkeypatch, header: MessageHeader, link: str) -> tuple[list, int]:
    verdict = MailVerdict(
        label="VERIFICATION", action_kind="OPEN_VERIFICATION_URL", action_value=link
    )
    monkeypatch.setattr("apps.mailbox.sync.classify_message", lambda **_: verdict)
    with tenant_scope(connection.tenant_id):
        sync_connection(connection, provider=FakeProvider((header,)), secrets_client=_grant())
        with tenant_transaction(connection.tenant_id):
            trusted = list(MailSignal.objects.filter(trusted=True))
            return trusted, DeviceAction.objects.count()


def test_the_platform_s_own_mail_cannot_open_another_customer_s_page(
    agency_a, membership_a, monkeypatch
):
    """The reviewer's attack, verbatim: the attacker opens their own programme
    on smapply, smapply mails the student from no-reply@smapply.io (DMARC
    passes), and the body links to the attacker's smapply page."""
    connection = _connection(agency_a, membership_a, "https://kth.smapply.io/prog/1")
    header = MessageHeader(
        message_id="m1",
        sender="no-reply@smapply.io",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    trusted, queued = _sync(connection, monkeypatch, header, "https://attacker.smapply.io/login")

    assert (trusted, queued) == ([], 0)


@pytest.mark.parametrize(
    ("link", "queued"),
    [("https://attacker.smapply.io/login", 0), ("https://kth.smapply.io/verify", 1)],
)
def test_a_trusted_tagged_mail_opens_only_the_named_platform_host(
    agency_a, membership_a, monkeypatch, link, queued
):
    """The Microsoft half: a leaked tag makes the message trusted without any
    provider authentication, so the link's host check is the only guard left.
    It must be the full host the pack named, never the platform's domain."""
    connection = _connection(
        agency_a, membership_a, "https://kth.smapply.io/prog/1", tag_portal="kth.smapply.io"
    )
    header = MessageHeader(
        message_id="m1",
        sender="no-reply@smapply.io",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=(TAGGED,),
    )

    trusted, actions = _sync(connection, monkeypatch, header, link)

    assert len(trusted) == 1
    assert actions == queued


@pytest.mark.parametrize(
    ("evidence_url", "queued"),
    [("https://www.tum.de/en/studies", 0), ("https://tum.de/en/studies", 1)],
)
def test_a_sibling_subdomain_is_a_link_target_only_under_the_named_host(
    agency_a, membership_a, monkeypatch, evidence_url, queued
):
    """Pinned on purpose, not an accident of the fix. mail.tum.de is READ under
    either pack link (reading keys on the registrable domain), but a link to
    portal.tum.de is followed only when the pack named tum.de itself:
    portal.tum.de is not a subdomain of www.tum.de. No "www." stripping --
    www.<shared platform> would widen to every customer of it. A genuine
    portal.tum.de link still works when the application names that portal."""
    connection = _connection(agency_a, membership_a, evidence_url)
    header = MessageHeader(
        message_id="m1",
        sender="noreply@mail.tum.de",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    trusted, actions = _sync(connection, monkeypatch, header, "https://portal.tum.de/verify")

    assert len(trusted) == 1
    assert actions == queued


def test_a_platform_nobody_listed_still_cannot_link_to_another_customer(
    agency_a, membership_a, monkeypatch
):
    """The half of the fix no list can supply. A vendor missing from both the
    PSL's private section and _SHARED_PLATFORMS still keys as its own domain,
    so its mail is read AND trusted for this student -- and only the full-host
    link check keeps the attacker's page on it out of the student's browser."""
    connection = _connection(agency_a, membership_a, "https://kth.newvendor.io/prog/1")
    header = MessageHeader(
        message_id="m1",
        sender="no-reply@newvendor.io",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    trusted, queued = _sync(connection, monkeypatch, header, "https://attacker.newvendor.io/x")

    assert (len(trusted), queued) == (1, 0)


def test_a_pack_linked_to_a_platform_apex_still_admits_no_customer(
    agency_a, membership_a, monkeypatch
):
    """Security findings 2026-09-26 follow-up 1: a pack whose own evidence URL
    is the platform's bare apex (https://smapply.io/prog/1, not a customer
    subdomain) must not let link_hosts admit ANY customer's page under it --
    _key still returns "smapply.io" itself as a truthy key, and without this
    guard it becomes a link target that every *.smapply.io mail can point at."""
    connection = _connection(agency_a, membership_a, "https://smapply.io/prog/1")
    header = MessageHeader(
        message_id="m1",
        sender="no-reply@smapply.io",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    trusted, queued = _sync(connection, monkeypatch, header, "https://attacker.smapply.io/login")

    assert (len(trusted), queued) == (1, 0)


def test_a_pack_link_to_a_path_tenanted_host_cannot_link_elsewhere_on_it(
    agency_a, membership_a, monkeypatch
):
    """Security finding 2026-09-26 follow-up 2: sites.google.com and its
    siblings separate customers by URL path, not by host -- the identical
    host serves everyone, so the whole host must never become a link
    target, however _key reads it for reading purposes."""
    connection = _connection(agency_a, membership_a, "https://sites.google.com/view/kth-msc")
    header = MessageHeader(
        message_id="m1",
        sender="no-reply@sites.google.com",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    trusted, queued = _sync(
        connection, monkeypatch, header, "https://sites.google.com/view/attacker"
    )

    assert (len(trusted), queued) == (1, 0)


def test_a_pack_link_to_a_named_customer_subdomain_still_queues_its_own_link(
    agency_a, membership_a, monkeypatch
):
    """Positive control for the two fixes above: kth.smapply.io is neither
    the platform's bare apex nor a path-tenanted host, so a genuine link on
    it must still be queued -- the fixes narrow link_hosts, they do not
    empty it."""
    connection = _connection(agency_a, membership_a, "https://kth.smapply.io/prog/1")
    header = MessageHeader(
        message_id="m1",
        sender="no-reply@kth.smapply.io",
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        recipients=("student@gmail.test",),
        authenticated=True,
    )

    trusted, queued = _sync(connection, monkeypatch, header, "https://kth.smapply.io/verify")

    assert (len(trusted), queued) == (1, 1)
