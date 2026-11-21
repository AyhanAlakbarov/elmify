"""POST /ext/applications/<id>/portal-login: the password goes to the paired
extension, for this account's own portal host, and nowhere else."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from apps.funding.models import AuditEvent
from apps.portals import credentials
from apps.tenancy.context import tenant_scope
from tests.portals.test_credentials import FakeSecrets
from tests.portals.test_ext_api import _pair

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"


@pytest.fixture
def fake(monkeypatch, settings):
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    store = FakeSecrets()
    monkeypatch.setattr(credentials, "_client", lambda client=None: store)
    return store


def _setup(agency, membership, host=HOST):
    from apps.portals.models import Application, PortalForm
    from apps.portals.tags import portal_address

    with tenant_scope(agency.id):
        membership.application_email = "leyla.apply@outlook.com"
        membership.save(update_fields=["application_email"])
        form = PortalForm.objects.create(
            portal_host=host,
            form_key=f"ext-{uuid4()}",
            form_url=f"https://{host}/personal",
        )
        application = Application.objects.create(
            tenant=agency, student=membership, program_id=uuid4(), portal_form=form
        )
        address = portal_address(application)
    return application, address


def _ask(client, application, token, domain, body):
    return client.post(
        f"/ext/applications/{application.id}/portal-login",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_HOST=domain.host,
    )


def test_signup_makes_one_password_and_a_reload_gets_the_same_one(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, address = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    first = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})
    again = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})

    assert first.status_code == 200, first.content
    assert first["Cache-Control"] == "no-store"
    assert first.json()["username"] == address
    assert again.json()["password"] == first.json()["password"]
    assert len(fake.store) == 1
    with tenant_scope(agency_a.id):
        account = application.student.portal_accounts.get()
        events = list(
            AuditEvent.objects.filter(object_id=account.id).values_list("event", flat=True)
        )
    assert account.password_held_at is not None
    assert events.count("portal.password_created") == 1
    assert events.count("portal.password_sent") == 2


def test_login_hands_out_the_stored_password(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    made = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST}).json()

    login = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert login.status_code == 200
    assert login.json() == made


def test_login_with_nothing_held_is_the_student_s_turn(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "no_portal_password"}
    assert fake.store == {}


@pytest.mark.parametrize("host", ["login.example.com", "apply.example.edu.evil.com", ""])
def test_another_host_gets_nothing(client, agency_a, domain_a, membership_a, fake, host) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(client, application, token, domain_a, {"page": "signup", "host": host})

    assert response.status_code == 409
    assert response.json() == {"error": "wrong_host"}
    assert fake.store == {}


def test_a_taken_over_account_is_never_logged_into(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    from django.utils import timezone

    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})
    with tenant_scope(agency_a.id):
        application.student.portal_accounts.update(student_managed_at=timezone.now())

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "student_managed"}


def test_an_account_registered_by_hand_gets_no_new_password(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    from django.utils import timezone

    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    with tenant_scope(agency_a.id):
        application.student.portal_accounts.update(registered_at=timezone.now())

    response = _ask(client, application, token, domain_a, {"page": "signup", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "registered_without_us"}
    assert fake.store == {}


def test_a_box_too_short_for_a_strong_password_writes_nothing(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(
        client, application, token, domain_a, {"page": "signup", "host": HOST, "max_length": 8}
    )

    assert response.status_code == 409
    assert response.json() == {"error": "password_rules"}
    assert fake.store == {}


@pytest.mark.parametrize(
    "body",
    [{"page": "register", "host": HOST}, {"page": "login"}, {"page": "login", "host": HOST, "x": 1},
     {"page": "signup", "host": HOST, "max_length": 0}],
)
def test_a_malformed_ask_is_refused(client, agency_a, domain_a, membership_a, fake, body) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(client, application, token, domain_a, body)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_request"}


def test_another_student_s_application_is_404(
    client, agency_a, domain_a, membership_a, fake, django_user_model
) -> None:
    from apps.tenancy.models import Membership

    application, _ = _setup(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        other_user = django_user_model.objects.create_user(username="other", password="x")
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT
        )
    token = _pair(client, agency_a, other, domain_a)

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 404


def _signup(client, application, token, domain, host=HOST):
    return _ask(client, application, token, domain, {"page": "signup", "host": host})


def test_a_store_failure_is_503_and_names_no_student(
    client, agency_a, domain_a, membership_a, fake, caplog
) -> None:
    import logging

    import botocore.exceptions

    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    def denied(*, Name, **_kw):
        raise botocore.exceptions.ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": f"no access to {Name}"}},
            "CreateSecret",
        )

    fake.create_secret = denied
    with caplog.at_level(logging.DEBUG):
        response = _signup(client, application, token, domain_a)

    assert response.status_code == 503
    assert response.json() == {"error": "secrets_unavailable"}
    student = str(application.student_id)
    for record in caplog.records:
        assert student not in record.getMessage()
        assert student not in str(record.exc_info)
    assert student not in caplog.text


def test_a_marker_over_a_vanished_secret_is_cleared(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    _signup(client, application, token, domain_a)
    fake.store.clear()

    response = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert response.status_code == 409
    assert response.json() == {"error": "no_portal_password"}
    with tenant_scope(agency_a.id):
        assert application.student.portal_accounts.get().password_held_at is None


def test_a_trailing_dot_is_the_same_host_a_port_is_not(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    assert _signup(client, application, token, domain_a, HOST + ".").status_code == 200
    port = _signup(client, application, token, domain_a, HOST + ":443")
    assert port.status_code == 409
    assert port.json() == {"error": "wrong_host"}


def test_a_secret_that_already_exists_logs_one_created_event(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    _signup(client, application, token, domain_a)
    with tenant_scope(agency_a.id):
        application.student.portal_accounts.update(password_held_at=None)
        before = AuditEvent.objects.count()

    for _ in range(2):
        assert _signup(client, application, token, domain_a).status_code == 200

    with tenant_scope(agency_a.id):
        events = list(AuditEvent.objects.order_by("created_at").values_list("event", flat=True))[
            before:
        ]
    assert events.count("portal.password_created") == 1
    assert events.count("portal.password_sent") == 2


def test_an_idn_portal_matches_the_hostname_the_browser_reports(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    # location.hostname is always the punycode form; the form row may hold either.
    application, _ = _setup(agency_a, membership_a, host="bewerbung.universität.example")
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _signup(client, application, token, domain_a, "bewerbung.xn--universitt-y5a.example")

    assert response.status_code == 200, response.content


def test_login_finds_a_password_whose_marker_was_never_written(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    made = _signup(client, application, token, domain_a).json()
    with tenant_scope(agency_a.id):
        application.student.portal_accounts.update(password_held_at=None)

    login = _ask(client, application, token, domain_a, {"page": "login", "host": HOST})

    assert login.status_code == 200, login.content
    assert login.json() == made
    with tenant_scope(agency_a.id):
        assert application.student.portal_accounts.get().password_held_at is not None


def test_a_sign_up_the_portal_sent_back_never_mints_a_password(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    # The page says we typed this sign-up before; with nothing stored, that
    # guess is wrong (the student's own address, say), and a new password
    # would be one the portal never got.
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)

    response = _ask(
        client, application, token, domain_a, {"page": "signup", "host": HOST, "came_back": True}
    )

    assert response.status_code == 409
    assert response.json() == {"error": "no_portal_password"}
    assert fake.store == {}


def test_a_sign_up_the_portal_sent_back_gets_the_password_already_made(
    client, agency_a, domain_a, membership_a, fake
) -> None:
    application, _ = _setup(agency_a, membership_a)
    token = _pair(client, agency_a, membership_a, domain_a)
    made = _signup(client, application, token, domain_a).json()

    again = _ask(
        client, application, token, domain_a, {"page": "signup", "host": HOST, "came_back": True}
    )

    assert again.json() == made
