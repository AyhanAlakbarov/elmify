"""Who may reach the queue. Every refusal is a 403 or a 404, never an empty 200.

The stub templates render nothing (tests/templates/README.md), so these assert
status codes, the database and the view's context -- never markup.
"""

import pytest

from apps.funding.models import AuditEvent
from apps.research.models import ResolutionItem
from apps.research.resolution.writers import file_item
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from tests.conftest import verify_mfa_session

pytestmark = pytest.mark.django_db

_ZERO = "00000000-0000-0000-0000-000000000000"


def _file(subject="host:shut.test"):
    return file_item(
        "HOST_UNREACHABLE", subject,
        {"host": subject[5:], "url": f"https://{subject[5:]}/p", "trail": []},
        country_code="TR",
    )


@pytest.fixture
def signed_in(client, platform_domain, operator_user, operator):
    client.force_login(operator_user)
    verify_mfa_session(client, operator_user)
    return client


def _get(client, path, host):
    return client.get(path, HTTP_HOST=host)


def test_an_agency_owner_on_their_own_host_is_refused(
    client, agency_a, domain_a, django_user_model
):
    user = django_user_model.objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    verify_mfa_session(client, user)
    assert _get(client, "/platform/resolution/", domain_a.host).status_code == 403


def test_a_platform_admin_of_an_ordinary_agency_is_refused(
    client, platform, agency_a, domain_a, django_user_model
):
    """PLATFORM_ADMIN is a role any agency can hold; the platform is one agency.
    Every route refuses, and a live item's id reveals nothing: 403, not 404."""
    item = _file()
    user = django_user_model.objects.create_user(username="padmin-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.PLATFORM_ADMIN
        )
    client.force_login(user)
    verify_mfa_session(client, user)
    assert _get(client, "/platform/resolution/", domain_a.host).status_code == 403
    assert _get(client, f"/platform/resolution/{item.id}/", domain_a.host).status_code == 403
    for action in ("decide", "park"):
        response = client.post(
            f"/platform/resolution/{item.id}/{action}/", {"option": "closed"},
            HTTP_HOST=domain_a.host,
        )
        assert response.status_code == 403
    item.refresh_from_db()
    assert (item.state, item.opened_at) == ("OPEN", None)


def test_an_operator_without_mfa_is_refused(client, platform_domain, operator_user, operator):
    client.force_login(operator_user)
    assert _get(client, "/platform/resolution/", platform_domain.host).status_code == 403


def test_a_platform_member_who_is_not_an_admin_is_refused(
    client, platform, platform_domain, django_user_model
):
    user = django_user_model.objects.create_user(username="platform-counselor")
    with tenant_scope(platform.id):
        Membership.objects.create(tenant=platform, user=user, role=Membership.Role.COUNSELOR)
    client.force_login(user)
    verify_mfa_session(client, user)
    assert _get(client, "/platform/resolution/", platform_domain.host).status_code == 403


def test_signed_out_is_sent_to_log_in(client, platform_domain):
    response = _get(client, "/platform/resolution/", platform_domain.host)
    assert response.status_code == 302


def test_the_operator_sees_the_queue(signed_in, platform_domain):
    item = _file()
    response = _get(signed_in, "/platform/resolution/", platform_domain.host)
    assert response.status_code == 200
    rows = response.context["rows"]
    assert [row.item.id for row in rows] == [item.id]
    assert rows[0].packs is None and rows[0].country_code == "TR"
    assert response.context["waiting_for_the_applier"] == 0


def test_opening_an_item_stamps_it_and_shows_its_question(signed_in, platform_domain):
    item = _file()
    response = _get(signed_in, f"/platform/resolution/{item.id}/", platform_domain.host)
    assert response.status_code == 200
    assert response.context["item"].id == item.id
    assert response.context["options"] == ["paste", "closed"]
    item.refresh_from_db()
    assert item.opened_at is not None


def test_an_unknown_item_is_a_404(signed_in, platform_domain):
    detail = _get(signed_in, f"/platform/resolution/{_ZERO}/", platform_domain.host)
    assert detail.status_code == 404
    for action in ("decide", "park"):
        response = signed_in.post(
            f"/platform/resolution/{_ZERO}/{action}/", {"option": "closed"},
            HTTP_HOST=platform_domain.host,
        )
        assert response.status_code == 404


def test_a_refused_decision_is_a_400_and_changes_nothing(signed_in, platform_domain):
    item = _file()
    response = signed_in.post(
        f"/platform/resolution/{item.id}/decide/", {"option": "nonsense"},
        HTTP_HOST=platform_domain.host,
    )
    assert response.status_code == 400
    item.refresh_from_db()
    assert item.state == "OPEN"


def test_deciding_and_parking_redirect_to_the_queue(
    signed_in, platform, platform_domain, operator
):
    decided, parked = _file("host:a.test"), _file("host:b.test")
    response = signed_in.post(
        f"/platform/resolution/{decided.id}/decide/", {"option": "closed", "url": ""},
        HTTP_HOST=platform_domain.host,
    )
    assert response.status_code == 302 and response["Location"] == "/platform/resolution/"
    response = signed_in.post(
        f"/platform/resolution/{parked.id}/park/", HTTP_HOST=platform_domain.host
    )
    assert response.status_code == 302
    assert ResolutionItem.objects.get(id=decided.id).state == "DECIDED"
    assert ResolutionItem.objects.get(id=parked.id).state == "PARKED"
    with tenant_scope(platform.id):
        assert set(
            AuditEvent.objects.filter(actor=operator).values_list("event", flat=True)
        ) == {"resolution.decided", "resolution.parked"}


def test_the_actions_are_post_only(signed_in, platform_domain):
    item = _file()
    for action in ("decide", "park"):
        response = _get(signed_in, f"/platform/resolution/{item.id}/{action}/",
                        platform_domain.host)
        assert response.status_code == 405


@pytest.fixture
def two_filed(db):
    """Filed as the superuser (the engine's side) BEFORE `web_role_orm` swaps
    the connection -- it is requested after this -- because runtime_web has no
    INSERT policy on the queue."""
    return _file("host:a.test"), _file("host:b.test")


@pytest.mark.django_db(transaction=True)
def test_the_console_runs_as_runtime_web_without_the_catalogue(
    client, platform, platform_domain, operator_user, operator, two_filed, web_role_orm
):
    """Brief D3: list, detail, decide and park, through Django's own connection
    logged in as a member of the real `runtime_web`. That role holds no grant
    on any catalogue table, so a catalogue read anywhere on this path is a
    `permission denied` here, as it would be in production. It also runs
    behind the platform policy for real, since runtime_web is NOBYPASSRLS."""
    to_decide, to_park = two_filed
    client.force_login(operator_user)
    verify_mfa_session(client, operator_user)
    host = platform_domain.host

    listed = client.get("/platform/resolution/", HTTP_HOST=host)
    assert listed.status_code == 200
    assert {row.item.id for row in listed.context["rows"]} == {to_decide.id, to_park.id}
    assert client.get(f"/platform/resolution/{to_decide.id}/", HTTP_HOST=host).status_code == 200
    assert client.post(
        f"/platform/resolution/{to_decide.id}/decide/", {"option": "closed"}, HTTP_HOST=host
    ).status_code == 302
    parked = client.post(f"/platform/resolution/{to_park.id}/park/", HTTP_HOST=host)
    assert parked.status_code == 302

    with tenant_transaction(platform.id):
        states = dict(ResolutionItem.objects.values_list("id", "state"))
        opened = ResolutionItem.objects.get(id=to_decide.id).opened_at
    assert states == {to_decide.id: "DECIDED", to_park.id: "PARKED"}
    assert opened is not None
