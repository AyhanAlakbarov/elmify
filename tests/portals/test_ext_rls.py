"""The extension API, behind a role that cannot bypass row-level security.

The rest of the suite runs as the test superuser, which is BYPASSRLS: a read
taken outside a tenant_transaction passes there and returns nothing in
production. CLAUDE.md is explicit that a test which does not run behind
rls_enforced_orm has verified nothing about tenant isolation, and the failure
it catches is silent -- legal SQL returning an empty set.

These are deliberately the same calls tests/portals/test_ext_api.py makes. The
duplication is the point: what differs is the database role, not the request.

Two shape rules, both learned from tests/portals/test_rls_spine.py and both
load-bearing:

``django_db(transaction=True)``, because the fixture closes and reopens the
connection to swap roles, and an ambient atomic block held by the superuser
connection dies with it ("the connection is closed").

Every fixture that writes setup data is listed BEFORE ``rls_enforced_orm`` in
the signature, so it runs while the connection is still the superuser's.
Afterwards the only writes are the ones under test.

The pairing itself is minted through the dashboard's own route rather than by
calling issue_pairing_code directly: that write needs the app.tenant_id GUC,
which HostTenantContextMiddleware sets around a real request and a bare
tenant_scope() does not. Calling the function directly here would fail under
the policy -- correctly, and for a reason that has nothing to do with what
these tests are about.
"""

import json
from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db(transaction=True)


def _form_and_application(agency, membership, *, with_map: bool):
    from apps.portals.models import Application, FieldMap, PortalForm

    with tenant_scope(agency.id):
        form = PortalForm.objects.create(
            portal_host="apply.example.edu",
            form_key=f"rls-{uuid4()}",
            form_url="https://apply.example.edu/personal",
        )
        if with_map:
            FieldMap.objects.create(
                portal_form=form,
                version=1,
                entries=[
                    {
                        "profile_field": "identity.full_name",
                        "action": {
                            "selector": "#name",
                            "method": "fill",
                            "arguments": ["%value%"],
                        },
                    }
                ],
            )
        return Application.objects.create(
            tenant=agency, student=membership, program_id=uuid4(), portal_form=form
        )


@pytest.fixture
def application_a(agency_a, membership_a):
    return _form_and_application(agency_a, membership_a, with_map=True)


@pytest.fixture
def application_a_with_email(agency_a, membership_a):
    """A student with an application_email and a field map asking for it --
    the packet route's only path that writes a PortalAccount row."""
    from apps.portals.models import Application, FieldMap, PortalForm

    with tenant_scope(agency_a.id):
        membership_a.application_email = "leyla.apply@outlook.com"
        membership_a.save(update_fields=["application_email"])
        form = PortalForm.objects.create(
            portal_host="apply.example.edu",
            form_key=f"rls-email-{uuid4()}",
            form_url="https://apply.example.edu/personal",
        )
        FieldMap.objects.create(
            portal_form=form,
            version=1,
            entries=[
                {
                    "profile_field": "contact.email",
                    "action": {"selector": "#email", "method": "fill", "arguments": ["%value%"]},
                }
            ],
        )
        return Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )


@pytest.fixture
def mapless_application_a(agency_a, membership_a):
    return _form_and_application(agency_a, membership_a, with_map=False)


@pytest.fixture
def application_b(agency_b, membership_b):
    return _form_and_application(agency_b, membership_b, with_map=True)


def _paired(client, user, domain):
    """Pair the way the product does: the dashboard mints, the extension redeems.

    Logged out afterwards, so the /ext/* calls that follow carry a bearer token
    and no session cookie -- which is the only credential those routes accept.
    """
    client.force_login(user)
    minted = client.post("/api/extension/pairing-code", HTTP_HOST=domain.host)
    assert minted.status_code == 201, minted.content
    client.logout()

    response = client.post(
        "/ext/pair",
        data=json.dumps({"code": minted.json()["code"], "installation_id": "rls-install"}),
        content_type="application/json",
        HTTP_HOST=domain.host,
    )
    assert response.status_code == 201, response.content
    return response.json()["token"]


def test_pairing_and_authenticating_work_behind_the_policy(
    agency_a, domain_a, membership_a, user_a, client, rls_enforced_orm
) -> None:
    """RED if ExtensionPairing has no policy, or if either half of the handshake
    escapes its scope: redeem_pairing_code's conditional UPDATE would match zero
    rows and a valid code would come back 'invalid_code'."""
    token = _paired(client, user_a, domain_a)

    response = client.delete(
        "/ext/pair", HTTP_HOST=domain_a.host, HTTP_AUTHORIZATION=f"Bearer {token}"
    )

    assert response.status_code == 204


def test_the_packet_route_reads_facts_behind_the_policy(
    agency_a, domain_a, membership_a, user_a, application_a, client, rls_enforced_orm, monkeypatch
) -> None:
    """RED if mint_packet's reads escape their tenant_transaction: verified
    values come back empty and a complete application refuses as missing_fact."""
    from apps.portals import packets

    monkeypatch.setattr(
        packets, "verified_values", lambda student: {"identity.full_name": "Ada Byron"}
    )
    token = _paired(client, user_a, domain_a)

    response = client.get(
        f"/ext/applications/{application_a.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 200, response.content
    assert response.json()["entries"][0]["value"] == "Ada Byron"


def test_the_packet_route_writes_a_portal_account_behind_the_policy(
    agency_a,
    domain_a,
    membership_a,
    user_a,
    application_a_with_email,
    client,
    rls_enforced_orm,
    monkeypatch,
) -> None:
    """RED if portal_address's write escapes its tenant_transaction: the
    INSERT is refused by the policy, so contact.email never gets filled and
    the route refuses with missing_fact (409) instead of minting a packet
    carrying the tagged address."""
    from apps.portals import packets
    from apps.portals.models import PortalAccount
    from apps.tenancy.db import tenant_transaction

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    token = _paired(client, user_a, domain_a)

    response = client.get(
        f"/ext/applications/{application_a_with_email.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 200, response.content
    value = response.json()["entries"][0]["value"]
    assert value.startswith("leyla.apply+") and value.endswith("@outlook.com")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = PortalAccount.objects.get(student=membership_a)
    assert account.address == value


def test_the_address_route_writes_registration_and_rejection_behind_the_policy(
    agency_a,
    domain_a,
    membership_a,
    user_a,
    application_a_with_email,
    client,
    rls_enforced_orm,
    monkeypatch,
) -> None:
    """RED if mark_registered's or record_tag_outcome's conditional UPDATEs
    escape their tenant_transaction: registered_at stays NULL, no SIGNUP step
    is written, and neither the account nor the shared PortalForm ever reaches
    REJECTS."""
    from apps.portals import packets
    from apps.portals.models import ApplicationStep, PortalAccount, PortalForm
    from apps.tenancy.db import tenant_transaction

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    token = _paired(client, user_a, domain_a)

    packet_response = client.get(
        f"/ext/applications/{application_a_with_email.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert packet_response.status_code == 200, packet_response.content

    given = client.post(
        f"/ext/applications/{application_a_with_email.id}/address",
        data=json.dumps({"event": "given"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert given.status_code == 200, given.content

    rejected = client.post(
        f"/ext/applications/{application_a_with_email.id}/address",
        data=json.dumps({"event": "rejected", "evidence": "form"}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert rejected.status_code == 200, rejected.content

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = PortalAccount.objects.get(student=membership_a)
        steps = ApplicationStep.objects.filter(
            application=application_a_with_email, kind="SIGNUP"
        ).count()
        form_status = PortalForm.objects.get(
            pk=application_a_with_email.portal_form_id
        ).tag_status

    assert account.registered_at is not None
    assert steps == 1
    assert account.tag_outcome == "REJECTS"
    assert form_status == "UNKNOWN"  # account-only evidence (security review M2)


def test_an_event_is_written_behind_the_policy(
    agency_a, domain_a, membership_a, user_a, mapless_application_a, client, rls_enforced_orm
) -> None:
    """RED if the step write escapes its tenant_transaction: the INSERT is
    refused by the policy rather than silently dropped, so this one fails
    loudly -- which is why it is worth having beside the reads."""
    token = _paired(client, user_a, domain_a)

    response = client.post(
        f"/ext/applications/{mapless_application_a.id}/events",
        data=json.dumps({"kind": "FILL", "detail": {"filled": ["#name"]}}),
        content_type="application/json",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert response.status_code == 201, response.content


def test_a_token_cannot_reach_another_tenant_s_application(
    agency_a,
    agency_b,
    domain_a,
    domain_b,
    membership_a,
    membership_b,
    user_a,
    application_b,
    client,
    rls_enforced_orm,
) -> None:
    """The isolation claim the whole design rests on, measured under the policy
    rather than under the ORM filter alone."""
    token = _paired(client, user_a, domain_a)

    on_own_host = client.get(
        f"/ext/applications/{application_b.id}/packet",
        HTTP_HOST=domain_a.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    on_their_host = client.get(
        f"/ext/applications/{application_b.id}/packet",
        HTTP_HOST=domain_b.host,
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert on_own_host.status_code == 404
    # The pairing row itself is invisible under tenant B's scope, so the token
    # authenticates nothing there. The host decides the tenant; the token only
    # ever says which membership.
    assert on_their_host.status_code == 401


def test_the_policy_really_is_on_the_two_new_tables(
    agency_a, domain_a, membership_a, user_a, application_a, client, rls_enforced_orm
) -> None:
    """The positive control. Every assertion above is an absence -- 404, 401, a
    row that is not there -- and an absence proves nothing unless the policy is
    demonstrably capable of producing one. So: read the pairing table with no
    app.tenant_id set, under the NOBYPASSRLS role, and watch it return nothing
    that the superuser can plainly see.

    Without this, deleting the RunSQL from migration 0010 would leave every
    test in this file green.
    """
    from django.db import connection

    from apps.tenancy.db import tenant_transaction

    _paired(client, user_a, domain_a)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname IN ('portals_extensionpairing', 'portals_deviceaction') "
            "ORDER BY relname"
        )
        flags = cursor.fetchall()
    assert flags == [
        ("portals_deviceaction", True, True),
        ("portals_extensionpairing", True, True),
    ]

    # Two-sided, same role, same query: with app.tenant_id set the row is
    # there, without it the policy compares tenant_id against NULL and it is
    # gone. That second half is the production failure CLAUDE.md describes --
    # legal SQL, zero rows, nothing raised.
    #
    # Raw SQL rather than the ORM because TenantManager raises
    # TenantContextMissing first, so an ORM read can never reach the policy and
    # can never show it working.
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM portals_extensionpairing")
        (unscoped,) = cursor.fetchone()

    with tenant_transaction(agency_a.id), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM portals_extensionpairing")
        (scoped,) = cursor.fetchone()

    assert scoped == 1
    assert unscoped == 0


def test_the_address_and_registration_reports_write_behind_the_policy(
    agency_a,
    domain_a,
    membership_a,
    user_a,
    application_a_with_email,
    client,
    rls_enforced_orm,
    monkeypatch,
) -> None:
    """RED if any write of plan 3's two device routes escapes its
    tenant_transaction: registered_at, the SIGNUP step, the account's
    tag_outcome, or the LearnedSender row would be refused by the policy.

    F8: a typed sender is stored UNCONFIRMED -- ``confirmed_at`` stays NULL
    until the student separately confirms a real message, so this asserts
    ``is None``, not ``is not None``.
    """
    from apps.funding.models import AuditEvent
    from apps.mailbox.models import LearnedSender
    from apps.portals import packets
    from apps.portals.models import ApplicationStep, PortalAccount
    from apps.tenancy.db import tenant_transaction

    monkeypatch.setattr(packets, "verified_values", lambda student: {})
    token = _paired(client, user_a, domain_a)
    auth = {"HTTP_HOST": domain_a.host, "HTTP_AUTHORIZATION": f"Bearer {token}"}
    base = f"/ext/applications/{application_a_with_email.id}"
    assert client.get(f"{base}/packet", **auth).status_code == 200

    given = client.post(
        f"{base}/address",
        data=json.dumps({"event": "given"}),
        content_type="application/json",
        **auth,
    )
    answered = client.post(
        f"{base}/registration",
        data=json.dumps({"arrived": "plain", "sender": "no-reply@mail-eu.portalvendor.com"}),
        content_type="application/json",
        **auth,
    )

    assert given.status_code == 200, given.content
    assert given.json()["awaiting_mail"] is True
    assert answered.status_code == 200, answered.content
    assert answered.json() == {"learned": True}
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        account = PortalAccount.objects.get(student=membership_a)
        assert account.registered_at is not None
        assert account.tag_outcome == "STRIPS"
        assert ApplicationStep.objects.filter(kind="SIGNUP").count() == 1
        # M4: the dock answer is this account's evidence only -- nothing shared
        # moved, so nothing names a measurer.
        assert AuditEvent.objects.filter(event="portal.tag_status_set").count() == 0
        assert LearnedSender.objects.get(student=membership_a).confirmed_at is None
