"""The registration-mail expectation, asked and answered in the dock (spec §2a)."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.test_ext_api import _application, _pair

pytestmark = pytest.mark.django_db

TAGGED = "leyla.apply+ab12cd@outlook.com"


@pytest.fixture
def registered(agency_a, membership_a):
    """An account on apply.example.edu that registered with its tag `minutes` ago."""
    from apps.portals.models import PortalAccount

    def _make(minutes=10, address=TAGGED):
        with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
            membership_a.application_email = "leyla.apply@outlook.com"
            membership_a.save(update_fields=["application_email"])
            application = _application(agency_a, membership_a)
            PortalAccount.objects.create(
                tenant=agency_a,
                student=membership_a,
                portal_host="apply.example.edu",
                tag="ab12cd",
                address=address,
                registered_at=timezone.now() - timedelta(minutes=minutes),
            )
            return application

    return _make


def _get(client, application, token, host):
    return client.get(
        f"/ext/applications/{application.id}/registration",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _answer(client, application, token, host, body):
    return client.post(
        f"/ext/applications/{application.id}/registration",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def _outcome(agency, student):
    from apps.portals.models import PortalAccount

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return PortalAccount.objects.get(student=student).tag_outcome


def _learned(agency, student):
    from apps.mailbox.models import LearnedSender

    with tenant_scope(agency.id), tenant_transaction(agency.id):
        return list(LearnedSender.objects.filter(student=student))


@pytest.mark.parametrize(("minutes", "state"), [(1, "waiting"), (10, "ask"), (45, "ask")])
def test_the_dock_is_told_when_to_ask(
    client, agency_a, domain_a, membership_a, user_a, registered, minutes, state
):
    application = registered(minutes=minutes)
    token = _pair(client, agency_a, membership_a, domain_a)

    body = _get(client, application, token, domain_a.host).json()

    assert body["state"] == state
    assert body["portal_host"] == "apply.example.edu"
    assert body["address"] == TAGGED


def test_an_untagged_account_has_nothing_to_ask(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    application = registered(address="leyla.apply@outlook.com")

    token = _pair(client, agency_a, membership_a, domain_a)

    assert _get(client, application, token, domain_a.host).json() == {"state": "none"}


def test_an_untagged_registered_account_refuses_to_answer(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """Ruling F4: `state` is computed once and POST refuses on it, not on a
    narrower "was it ever registered" check -- an untagged account is
    registered (mark_registered does not care about the tag) but has nothing
    for the dock to ask about, and must not be allowed to write the shared
    status for a portal it never measured a tag against."""
    application = registered(address="leyla.apply@outlook.com")
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "tagged"})

    assert response.status_code == 409
    assert response.json() == {"error": "no_registration"}


def test_arrived_at_the_plain_address_measures_strips_and_learns_the_sender_unconfirmed(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "no-reply@mail-eu.portalvendor.com"},
    )

    assert response.json() == {"learned": True}
    [learned] = _learned(agency_a, membership_a)
    assert learned.domain == "portalvendor.com"
    # Ruling F8: a sender the student typed is stored UNCONFIRMED -- read, and
    # never a link target -- until the student confirms one message from it
    # through the existing confirm button (apps/mailbox/views.py).
    assert learned.confirmed_at is None
    assert learned.portal_host == "apply.example.edu"
    # M4 (final review): the answer measures this account only. "Plain" can
    # mean the student retyped the address by hand, so it never moves the
    # shared status; STRIPS reaches that only from mail.
    assert _outcome(agency_a, membership_a) == "STRIPS"
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "UNKNOWN"
    assert _get(client, application, token, domain_a.host).json()["state"] == "done"


def test_arrived_at_the_tagged_address_measures_keeps(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "tagged"})

    assert response.json() == {"learned": False}
    assert _outcome(agency_a, membership_a) == "KEEPS"
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "UNKNOWN"
    assert _learned(agency_a, membership_a) == []


def test_a_shared_platform_sender_is_never_learned(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """Ruling F7: a shared-platform sender is refused for learning, same as
    any other learn path (`learnable_domain`'s existing guard) -- a STRIPS
    portal mailing from a platform like dreamapply.com is read only through a
    human-curated `PortalForm.sender_domains` row, never a per-student learn."""
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "no-reply@mail-eu.dreamapply.com"},
    )

    assert response.json() == {"learned": False}
    assert _outcome(agency_a, membership_a) == "STRIPS"
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "UNKNOWN"
    assert _learned(agency_a, membership_a) == []


def test_a_free_mail_sender_is_never_learned(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """A portal that mails from gmail.com would teach us to read every
    stranger's gmail. The measurement still stands; the sender is refused."""
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(
        client, application, token, domain_a.host, {"arrived": "plain", "sender": "x@gmail.com"}
    )

    assert response.json() == {"learned": False}
    assert _learned(agency_a, membership_a) == []


def test_the_student_s_own_domain_is_never_learned(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        membership_a.application_email = "leyla@uni-example.edu.tr"
        membership_a.save(update_fields=["application_email"])

    response = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "friend@uni-example.edu.tr"},
    )

    assert response.json() == {"learned": False}


def test_no_email_records_nothing(client, agency_a, domain_a, membership_a, user_a, registered):
    from apps.portals.models import PortalForm

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "none"})

    assert response.status_code == 200
    assert PortalForm.objects.get(pk=application.portal_form_id).tag_status == "UNKNOWN"
    assert _get(client, application, token, domain_a.host).json()["state"] == "ask"


@pytest.mark.parametrize(
    "body",
    [
        {"arrived": "plain"},
        {"arrived": "plain", "sender": "not an address"},
        {"arrived": "maybe"},
        {"arrived": "none", "note": "extra"},
    ],
)
def test_an_answer_the_server_cannot_read_is_refused(
    client, agency_a, domain_a, membership_a, user_a, registered, body
):
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, body)

    assert response.status_code == 400


def test_answering_without_a_registration_is_a_conflict(
    client, agency_a, domain_a, membership_a, user_a
):
    with tenant_scope(agency_a.id):
        application = _application(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(client, application, token, domain_a.host, {"arrived": "tagged"})

    assert response.status_code == 409


def test_a_measurement_already_settled_by_a_tagged_answer_learns_nothing_more(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """Fix round 1, finding 2: every `plain` answer used to learn another
    sender regardless of state, bounded only by the rate limit. Once the
    account's first measurement is settled -- here by `tagged` -- a later
    `plain` answer no longer moves anything and must not learn either."""
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)
    first = _answer(client, application, token, domain_a.host, {"arrived": "tagged"})
    assert first.json() == {"learned": False}

    second = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "no-reply@mail-eu.portalvendor.com"},
    )

    assert second.json() == {"learned": False}
    assert _learned(agency_a, membership_a) == []


def test_only_the_first_plain_answer_learns_a_sender(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """Fix round 1, finding 2: a second `plain` answer for the same account is
    not a new measurement -- record_tag_outcome no longer moves anything, so
    it must not add a second, contradicting LearnedSender row."""
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)
    first = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "no-reply@mail-eu.portalvendor.com"},
    )
    assert first.json() == {"learned": True}

    second = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "billing@other-vendor.example.com"},
    )

    assert second.json() == {"learned": False}
    [learned] = _learned(agency_a, membership_a)
    assert learned.domain == "portalvendor.com"


def test_a_smuggled_second_address_is_refused(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    """Fix round 1, finding 3: sender_domain's bare rpartition("@") keeps the
    LAST "@" in the text, so a typed value carrying an injected line resolved
    to the attacker's domain (z.com) instead of being refused. Parsing through
    email.utils.getaddresses must see two addresses (or one malformed empty
    one) and refuse with 400, never silently pick either."""
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _answer(
        client,
        application,
        token,
        domain_a.host,
        {"arrived": "plain", "sender": "x@evil.com\r\nBcc: y@z.com"},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_sender"}
    assert _learned(agency_a, membership_a) == []


def test_another_students_registration_is_404(
    client, agency_a, domain_a, membership_a, user_a, user_b
):
    from apps.tenancy.models import Membership

    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        application = _application(agency_a, other)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _get(client, application, token, domain_a.host)

    assert response.status_code == 404


def test_a_token_from_another_tenants_host_is_refused(
    client, agency_a, domain_a, domain_b, membership_a, user_a, registered
):
    """The token identifies the membership; the host identifies the tenant.
    Presenting one tenant's token on another tenant's host must not
    authenticate -- the same guard every other device route carries."""
    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _get(client, application, token, domain_b.host)

    assert response.status_code == 401


def test_a_pending_erasure_locks_this_route_out_too(
    client, agency_a, domain_a, membership_a, user_a, registered
):
    from apps.audit.models import DeletionRequest

    application = registered()
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="APPROVED", reason="PRIVACY"
        )

    response = _get(client, application, token, domain_a.host)

    assert response.status_code == 403
    assert response.json() == {"error": "account_locked"}
