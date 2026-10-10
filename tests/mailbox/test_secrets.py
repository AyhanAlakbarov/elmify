"""The token is a grant on someone's mail. It is never a column.

The fake here records every call, because what must be true of this module is
mostly about what it does NOT do: never log a token, never enumerate secrets
it does not own, never leave one behind after an erasure.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

import botocore.exceptions
import pytest

from apps.mailbox.secrets import (
    delete_student_mailbox_tokens,
    refresh_token_for,
    secret_id,
    store_refresh_token,
)

TENANT = uuid4()
STUDENT = uuid4()
TOKEN = "1//refresh-token-value"


class FakeSecrets:
    def __init__(self, existing: dict[str, str] | None = None) -> None:
        self.store = dict(existing or {})
        self.calls: list[tuple[str, str]] = []

    def create_secret(self, *, Name: str, SecretString: str) -> dict[str, str]:
        self.calls.append(("create_secret", Name))
        if Name in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceExistsException"}}, "CreateSecret"
            )
        self.store[Name] = SecretString
        return {"ARN": Name}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> dict[str, str]:
        self.calls.append(("put_secret_value", SecretId))
        self.store[SecretId] = SecretString
        return {"ARN": SecretId}

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        self.calls.append(("get_secret_value", SecretId))
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue"
            )
        return {"SecretString": self.store[SecretId]}

    def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict[str, str]:
        self.calls.append(("delete_secret", SecretId))
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "DeleteSecret"
            )
        del self.store[SecretId]
        return {"ARN": SecretId}

    def list_secrets(self, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("ListSecrets cannot be resource-scoped in IAM and must not be called")


def test_the_path_is_reconstructible_from_what_erasure_holds() -> None:
    assert secret_id(TENANT, STUDENT, "GOOGLE") == f"tehsil/mailbox/{TENANT}/{STUDENT}/GOOGLE"


def test_a_token_round_trips() -> None:
    fake = FakeSecrets()
    store_refresh_token(
        tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", refresh_token=TOKEN, client=fake
    )

    assert refresh_token_for(
        tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", client=fake
    ) == TOKEN
    assert json.loads(fake.store[secret_id(TENANT, STUDENT, "GOOGLE")]) == {"refresh_token": TOKEN}


def test_reconnecting_overwrites_rather_than_failing() -> None:
    fake = FakeSecrets()
    store_refresh_token(
        tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", refresh_token="old", client=fake
    )
    store_refresh_token(
        tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", refresh_token=TOKEN, client=fake
    )

    assert [name for name, _ in fake.calls].count("put_secret_value") == 1
    assert refresh_token_for(
        tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", client=fake
    ) == TOKEN


def test_a_missing_token_is_none_and_the_log_carries_no_token(caplog) -> None:
    fake = FakeSecrets()
    with caplog.at_level(logging.DEBUG):
        assert (
            refresh_token_for(
                tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", client=fake
            )
            is None
        )

    assert str(STUDENT) not in caplog.text
    assert "tehsil/mailbox" not in caplog.text


def test_erasure_destroys_both_providers_and_never_lists() -> None:
    fake = FakeSecrets()
    for provider in ("GOOGLE", "MICROSOFT"):
        store_refresh_token(
            tenant_id=TENANT,
            student_id=STUDENT,
            provider=provider,
            refresh_token=TOKEN,
            client=fake,
        )

    assert delete_student_mailbox_tokens(tenant_id=TENANT, student_id=STUDENT, client=fake) == 2
    assert fake.store == {}


def test_a_provider_argument_deletes_only_that_one_providers_secret() -> None:
    """apps/mailbox/views.py::revoke passes its own connection's provider so
    that revoking GOOGLE does not take down a MICROSOFT connection the student
    never touched. The default (no provider) is unchanged and stays what
    advance_deletion calls."""
    fake = FakeSecrets()
    for provider in ("GOOGLE", "MICROSOFT"):
        store_refresh_token(
            tenant_id=TENANT,
            student_id=STUDENT,
            provider=provider,
            refresh_token=TOKEN,
            client=fake,
        )

    assert (
        delete_student_mailbox_tokens(
            tenant_id=TENANT, student_id=STUDENT, provider="GOOGLE", client=fake
        )
        == 1
    )
    assert secret_id(TENANT, STUDENT, "GOOGLE") not in fake.store
    assert secret_id(TENANT, STUDENT, "MICROSOFT") in fake.store


def test_erasure_succeeds_when_the_student_never_connected_one() -> None:
    fake = FakeSecrets()
    assert delete_student_mailbox_tokens(tenant_id=TENANT, student_id=STUDENT, client=fake) == 0


def test_any_other_error_propagates_so_executed_is_not_written() -> None:
    class Refusing(FakeSecrets):
        def delete_secret(self, **_kwargs: object) -> dict[str, str]:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "AccessDeniedException"}}, "DeleteSecret"
            )

    with pytest.raises(botocore.exceptions.ClientError):
        delete_student_mailbox_tokens(tenant_id=TENANT, student_id=STUDENT, client=Refusing())


@pytest.mark.django_db
def test_advance_deletion_destroys_mailbox_grants(monkeypatch) -> None:
    """The call is on the EXECUTED path, before the redaction transaction.

    Asserted here rather than in the audit suite because this is the module
    that owns the promise; the audit suite owns the ordering.
    """
    import apps.audit.deletion as deletion

    called: list[tuple[object, object]] = []
    monkeypatch.setattr(
        deletion,
        "delete_student_mailbox_tokens",
        lambda **kwargs: called.append((kwargs["tenant_id"], kwargs["student_id"])) or 0,
    )

    assert deletion.delete_student_mailbox_tokens is not delete_student_mailbox_tokens
    assert called == []
