"""Reauthentication is a recovery, not an escalation -- except for the one
thing that reaches the student's own device."""

import json
from uuid import uuid4

import botocore.exceptions
import pytest

from apps.tenancy.context import tenant_scope
from tests.portals.fakes import FakePortalSession

pytestmark = pytest.mark.django_db


def test_the_credentials_repr_does_not_render_the_password() -> None:
    """NamedTuple's default repr prints every field, password included.

    Nothing renders one today, which is exactly why this is worth pinning:
    the leak arrives when somebody wires up an error reporter that captures
    locals, in a change that never touches apps/portals/auth.py.
    """
    from apps.portals.auth import PortalCredentials

    credentials = PortalCredentials(username="student@example.com", password="hunter2")

    for rendering in (repr(credentials), str(credentials), f"{credentials}", str([credentials])):
        assert "hunter2" not in rendering, rendering
    assert "student@example.com" in repr(credentials)
    # Still a tuple: the password is hidden from display, not from callers.
    assert credentials.password == "hunter2"

LOGIN_ENTRIES = [
    {
        "profile_field": "portal.username",
        "action": {"selector": "#user", "method": "fill", "arguments": ["%value%"]},
    },
    {
        "profile_field": "portal.password",
        "action": {"selector": "#pass", "method": "fill", "arguments": ["%value%"]},
    },
]


def _portal(agency, student, **form_kwargs):
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key="personal-details",
        form_url="https://apply.example.edu/personal",
        review_required=False,
        **form_kwargs,
    )
    login = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="login", form_url="https://apply.example.edu/login"
    )
    FieldMap.objects.create(portal_form=login, version=1, entries=LOGIN_ENTRIES)
    application = Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )
    return form, application


class StaticProvider:
    def __init__(self, credentials=None):
        self._credentials = credentials
        self.asked = []

    def credentials_for(self, *, tenant_id, student_id, portal_host):
        self.asked.append((tenant_id, student_id, portal_host))
        return self._credentials


def test_the_login_marker_is_how_expiry_is_detected(agency_a, membership_a):
    """Deterministic, like challenge detection: a known element on the page,
    never an inference from how the page 'feels'."""
    from apps.portals.auth import session_expired

    with tenant_scope(agency_a.id):
        form, _ = _portal(agency_a, membership_a, login_marker="#login-form")

        assert session_expired(FakePortalSession(elements={"#login-form": {}}), form) is True
        assert session_expired(FakePortalSession(), form) is False


def test_a_portal_with_no_marker_is_never_treated_as_expired(agency_a, membership_a):
    """An unconfigured marker must not mean "always expired" -- that would
    reauthenticate on every single step."""
    from apps.portals.auth import session_expired

    with tenant_scope(agency_a.id):
        form, _ = _portal(agency_a, membership_a, login_marker="")

        assert session_expired(FakePortalSession(elements={"#login-form": {}}), form) is False


def test_reauthentication_types_the_credential_and_submits(agency_a, membership_a):
    from apps.portals.auth import PortalCredentials, reauthenticate

    session = FakePortalSession(elements={"#login-form": {}})
    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        # The marker disappears once the form is submitted.
        def press_enter():
            session.elements.pop("#login-form", None)
            session.enter_presses += 1

        session.press_enter = press_enter

        assert (
            reauthenticate(
                session,
                application,
                provider=StaticProvider(PortalCredentials("ada", "s3cret")),
            )
            is True
        )
        assert session.values == {"#user": "ada", "#pass": "s3cret"}
        assert session.enter_presses == 1


def test_reauthentication_is_recorded_as_a_recovery_without_the_credential(
    agency_a, membership_a
):
    """§5.5 wants the action recorded. The password is not part of the action."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.models import RecoveryEvent

    session = FakePortalSession(elements={"#login-form": {}})
    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")
        session.press_enter = lambda: session.elements.pop("#login-form", None)

        reauthenticate(
            session, application, provider=StaticProvider(PortalCredentials("ada", "s3cret"))
        )

        event = RecoveryEvent.objects.get()
        assert event.kind == RecoveryEvent.Kind.SESSION_EXPIRED

        # §5.5: RecoveryEvent is platform-scoped and carries no application
        # reference, so the tenant's own audit trail needs its own record.
        step = application.steps.get()
        assert step.kind == "RECOVERY"
        assert step.detail == {"kind": "SESSION_EXPIRED", "portal_host": "apply.example.edu"}

        serialised = f"{event.detail}{list(application.steps.values_list('detail', flat=True))}"
        assert "s3cret" not in serialised
        assert "ada" not in serialised


def test_a_fill_failure_during_reauthentication_escalates_without_crashing(
    agency_a, membership_a
):
    """fill_form can raise FillInterrupted, MissingFact or UnsafeAction -- a
    login page drifts like any other. That must become a consultant
    escalation, never an uncaught exception the worker surfaces as a
    traceback, and the escalation detail must never carry ActFailed's
    page-controlled message."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.engine import ActFailed
    from apps.portals.models import Application

    session = FakePortalSession(elements={"#login-form": {}})

    def _act(action, variables):
        raise ActFailed(f"{action.selector}: a page-controlled message with s3cret in it")

    session.act = _act

    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        assert (
            reauthenticate(
                session,
                application,
                provider=StaticProvider(PortalCredentials("ada", "s3cret")),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR
        serialised = str(list(application.steps.values_list("detail", flat=True)))
        assert "a page-controlled message" not in serialised
        assert "s3cret" not in serialised


def test_an_mfa_prompt_escalates_to_the_student(agency_a, membership_a):
    """The credential reaches the student's own device. No amount of platform
    credential management resolves that, which is why it is in §5.4's table."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.models import Application

    session = FakePortalSession(elements={"#login-form": {}, "#mfa": {}})
    with tenant_scope(agency_a.id):
        _, application = _portal(
            agency_a, membership_a, login_marker="#login-form", mfa_marker="#mfa"
        )
        session.press_enter = lambda: session.elements.pop("#login-form", None)

        assert (
            reauthenticate(
                session,
                application,
                provider=StaticProvider(PortalCredentials("ada", "s3cret")),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PERSONAL_ACTION


def test_a_missing_platform_credential_reaches_the_consultant_desk(agency_a, membership_a):
    """Not a crash and not a student task: §5.2 routes reauthentication to a
    consultant, and only personal authentication to the student."""
    from apps.portals.auth import reauthenticate
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        assert (
            reauthenticate(
                FakePortalSession(elements={"#login-form": {}}),
                application,
                provider=StaticProvider(None),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR


def test_a_login_that_does_not_take_is_a_portal_error(agency_a, membership_a):
    """The marker is still there after submitting: wrong password, locked
    account, changed login page. All three need a human, none need the student."""
    from apps.portals.auth import PortalCredentials, reauthenticate
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        _, application = _portal(agency_a, membership_a, login_marker="#login-form")

        assert (
            reauthenticate(
                FakePortalSession(elements={"#login-form": {}}),
                application,
                provider=StaticProvider(PortalCredentials("ada", "wrong")),
            )
            is False
        )

        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_PORTAL_ERROR


def _client_error(code: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError({"Error": {"Code": code, "Message": "boom"}}, "op")


class _StubDeleteClient:
    """Records delete_secret calls; raises a scripted ClientError for any
    SecretId ending in a host named in `fail_hosts`."""

    def __init__(self, fail_hosts: dict[str, str] | None = None):
        self.fail_hosts = fail_hosts or {}
        self.calls: list[dict[str, object]] = []

    def delete_secret(self, *, SecretId, ForceDeleteWithoutRecovery):
        self.calls.append(
            {"SecretId": SecretId, "ForceDeleteWithoutRecovery": ForceDeleteWithoutRecovery}
        )
        for host, code in self.fail_hosts.items():
            if SecretId.endswith(f"/{host}"):
                raise _client_error(code)


class _StubGetClient:
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self._response = response
        self._error = error

    def get_secret_value(self, *, SecretId):
        if self._error is not None:
            raise self._error
        return self._response


def test_delete_student_portal_credentials_targets_every_known_host(agency_a):
    from apps.portals.auth import delete_student_portal_credentials, secret_id
    from apps.portals.models import PortalForm

    PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
    PortalForm.objects.create(portal_host="apply.other.edu", form_key=f"k-{uuid4()}")
    student_id = uuid4()
    client = _StubDeleteClient()

    deleted = delete_student_portal_credentials(
        tenant_id=agency_a.id, student_id=student_id, client=client
    )

    assert deleted == 2
    ids = {call["SecretId"] for call in client.calls}
    assert ids == {
        secret_id(agency_a.id, student_id, "apply.example.edu"),
        secret_id(agency_a.id, student_id, "apply.other.edu"),
    }
    assert all(call["ForceDeleteWithoutRecovery"] is True for call in client.calls)


def test_a_missing_secret_is_handled_not_raised(agency_a):
    """ResourceNotFoundException genuinely is success: the credential is
    already gone."""
    from apps.portals.auth import delete_student_portal_credentials
    from apps.portals.models import PortalForm

    PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
    client = _StubDeleteClient({"apply.example.edu": "ResourceNotFoundException"})

    deleted = delete_student_portal_credentials(
        tenant_id=agency_a.id, student_id=uuid4(), client=client
    )

    assert deleted == 0
    assert len(client.calls) == 1


def test_an_access_denied_error_propagates_instead_of_recording_success(agency_a):
    """Anything other than "already absent" must propagate: advance_deletion
    writes EXECUTED only if this function returns, so swallowing AccessDenied
    would record an erasure that did not happen. The IAM grant lands in
    Task 14, so AccessDenied is the current production case."""
    from apps.portals.auth import delete_student_portal_credentials
    from apps.portals.models import PortalForm

    PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
    client = _StubDeleteClient({"apply.example.edu": "AccessDeniedException"})

    with pytest.raises(botocore.exceptions.ClientError):
        delete_student_portal_credentials(
            tenant_id=agency_a.id, student_id=uuid4(), client=client
        )


def test_credentials_for_returns_credentials_on_the_happy_path():
    from apps.portals.auth import PortalCredentials, SecretsManagerCredentials

    client = _StubGetClient(
        response={"SecretString": json.dumps({"username": "ada", "password": "s3cret"})}
    )
    provider = SecretsManagerCredentials(client=client)

    result = provider.credentials_for(
        tenant_id=uuid4(), student_id=uuid4(), portal_host="apply.example.edu"
    )

    assert result == PortalCredentials("ada", "s3cret")


def test_credentials_for_returns_none_when_the_secret_does_not_exist():
    from apps.portals.auth import SecretsManagerCredentials

    provider = SecretsManagerCredentials(
        client=_StubGetClient(error=_client_error("ResourceNotFoundException"))
    )

    assert (
        provider.credentials_for(
            tenant_id=uuid4(), student_id=uuid4(), portal_host="apply.example.edu"
        )
        is None
    )


def test_credentials_for_returns_none_rather_than_crashing_on_a_malformed_secret():
    """A bare scalar SecretString -- an operator pasting a plain password --
    parses as valid JSON but is not a mapping, so payload["username"] raises
    TypeError. That must escalate as "no credential", not crash the worker."""
    from apps.portals.auth import SecretsManagerCredentials

    client = _StubGetClient(response={"SecretString": json.dumps("hunter2")})
    provider = SecretsManagerCredentials(client=client)

    assert (
        provider.credentials_for(
            tenant_id=uuid4(), student_id=uuid4(), portal_host="apply.example.edu"
        )
        is None
    )
