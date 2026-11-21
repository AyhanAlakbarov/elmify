"""Portal passwords: in Secrets Manager under their own key, never a column.

What must be true is mostly what this module does NOT do -- never log a
password, never enumerate secrets, never make a second password for an account
that already has one -- so the fake records every call.
"""

from __future__ import annotations

import json
import logging
import string
from uuid import uuid4

import botocore.exceptions
import pytest

from apps.portals.credentials import (
    PasswordRulesUnmet,
    create_password,
    delete_password,
    delete_student_portal_credentials,
    generate_password,
    password_for,
    secret_id,
)
from apps.portals.models import PortalForm

TENANT = uuid4()
STUDENT = uuid4()
HOST = "apply.example.edu"


class FakeSecrets:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def create_secret(self, *, Name: str, SecretString: str, **extra: object) -> dict[str, str]:
        self.calls.append(("create_secret", Name, extra))
        if Name in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceExistsException"}}, "CreateSecret"
            )
        self.store[Name] = SecretString
        return {"ARN": Name}

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        self.calls.append(("get_secret_value", SecretId, {}))
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue"
            )
        return {"SecretString": self.store[SecretId]}

    def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict[str, str]:
        self.calls.append(("delete_secret", SecretId, {}))
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "DeleteSecret"
            )
        del self.store[SecretId]
        return {"ARN": SecretId}

    def list_secrets(self, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("ListSecrets cannot be resource-scoped in IAM and must not be called")


def test_a_generated_password_is_long_and_has_every_kind_of_character() -> None:
    for _ in range(200):
        password = generate_password()
        assert len(password) == 24
        assert any(c in string.ascii_lowercase for c in password)
        assert any(c in string.ascii_uppercase for c in password)
        assert any(c in string.digits for c in password)
        # From "!#", not "-_.": a portal counting only !@#$%^&* as special
        # refuses a password whose only symbols are -_. (32.4% of them before).
        assert any(c in "!#" for c in password)
        assert set(password) <= set(string.ascii_letters + string.digits + "!#-_.")


def test_a_box_s_maxlength_shortens_it_and_below_twelve_nothing_is_made() -> None:
    assert len(generate_password(16)) == 16
    assert len(generate_password(200)) == 24
    with pytest.raises(PasswordRulesUnmet):
        generate_password(11)


def test_password_rules_constrain_length_and_allowed_symbols() -> None:
    for _ in range(50):
        alnum = generate_password(password_rules="8-16 characters, letters and numbers only")
        assert len(alnum) == 16
        assert alnum.isalnum()
        assert any(c.islower() for c in alnum)
        assert any(c.isupper() for c in alnum)
        assert any(c.isdigit() for c in alnum)

        custom_sym = generate_password(password_rules="Maximum 14 characters, allowed: @ $ %")
        assert len(custom_sym) == 14
        assert any(c in "@$%" for c in custom_sym)
        assert set(custom_sym) <= set(string.ascii_letters + string.digits + "@$%")


def test_two_passwords_are_never_the_same() -> None:
    assert len({generate_password() for _ in range(50)}) == 50


def test_create_stores_once_and_a_second_create_returns_the_first(settings) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    fake = FakeSecrets()
    first = create_password(
        tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="a@b.c", client=fake
    )
    again = create_password(
        tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="a@b.c", client=fake
    )
    assert again == first
    stored = json.loads(fake.store[secret_id(TENANT, STUDENT, HOST)])
    assert stored == {"username": "a@b.c", "password": first}
    got = password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)
    assert got == first


def test_create_names_the_portal_key_when_one_is_configured(settings) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = "key-123"
    fake = FakeSecrets()
    create_password(
        tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="u", client=fake
    )
    assert fake.calls[0][2] == {"KmsKeyId": "key-123"}


def test_a_missing_secret_reads_as_none_and_logs_no_id(caplog) -> None:
    fake = FakeSecrets()
    with caplog.at_level(logging.DEBUG):
        found = password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)
        assert found is None
    assert str(STUDENT) not in caplog.text


def test_the_password_never_reaches_a_log(caplog, settings) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    fake = FakeSecrets()
    with caplog.at_level(logging.DEBUG):
        password = create_password(
            tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, username="u", client=fake
        )
        password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)
    assert password not in caplog.text


def test_delete_one_says_whether_there_was_one() -> None:
    fake = FakeSecrets()
    fake.store[secret_id(TENANT, STUDENT, HOST)] = json.dumps({"username": "u", "password": "p"})
    assert delete_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)
    assert not delete_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)


def test_another_refusal_on_delete_propagates() -> None:
    class Denied(FakeSecrets):
        def delete_secret(
            self, *, SecretId: str, ForceDeleteWithoutRecovery: bool
        ) -> dict[str, str]:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "AccessDeniedException"}}, "DeleteSecret"
            )

    with pytest.raises(botocore.exceptions.ClientError):
        delete_password(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=Denied())


def test_an_unreadable_store_is_not_an_absent_secret() -> None:
    fake = FakeSecrets()

    def denied(*, SecretId: str) -> dict[str, str]:
        raise botocore.exceptions.ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": SecretId}}, "GetSecretValue"
        )

    fake.get_secret_value = denied  # type: ignore[method-assign]
    with pytest.raises(botocore.exceptions.ClientError):
        password_for(tenant_id=TENANT, student_id=STUDENT, portal_host=HOST, client=fake)


# delete_student_portal_credentials: moved here from test_auth.py, which PR #169
# deletes with the server portal tier. These are erasure's only behaviour tests.


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
                raise botocore.exceptions.ClientError(
                    {"Error": {"Code": code, "Message": "boom"}}, "DeleteSecret"
                )


@pytest.mark.django_db
def test_delete_student_portal_credentials_targets_every_known_host(agency_a) -> None:
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


@pytest.mark.django_db
def test_a_missing_secret_is_handled_not_raised(agency_a) -> None:
    """ResourceNotFoundException genuinely is success: the credential is
    already gone."""
    PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
    client = _StubDeleteClient({"apply.example.edu": "ResourceNotFoundException"})

    deleted = delete_student_portal_credentials(
        tenant_id=agency_a.id, student_id=uuid4(), client=client
    )

    assert deleted == 0
    assert len(client.calls) == 1


@pytest.mark.django_db
def test_an_access_denied_error_propagates_instead_of_recording_success(agency_a) -> None:
    """Anything other than "already absent" must propagate: advance_deletion
    writes EXECUTED only if this function returns, so swallowing AccessDenied
    would record an erasure that did not happen."""
    PortalForm.objects.create(portal_host="apply.example.edu", form_key=f"k-{uuid4()}")
    client = _StubDeleteClient({"apply.example.edu": "AccessDeniedException"})

    with pytest.raises(botocore.exceptions.ClientError):
        delete_student_portal_credentials(
            tenant_id=agency_a.id, student_id=uuid4(), client=client
        )
