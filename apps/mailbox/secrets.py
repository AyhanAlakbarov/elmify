"""The refresh token: in Secrets Manager, keyed by a path erasure can rebuild.

Modelled on apps/portals/auth.py, which holds portal passwords the same way and
for the same reason. The one thing to keep in mind when reading either: the path
shape is not cosmetic. It is what lets an erasure delete every secret a student
owns without calling ListSecrets, which IAM cannot scope to a resource -- so a
role that could enumerate this student's secrets could enumerate everyone's.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import botocore.exceptions  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

#: Both providers, always. delete_student_mailbox_tokens walks this rather than
#: reading MailboxConnection rows: an erasure that trusted the table would miss
#: a secret whose row was already gone, and a secret nobody has a row for is
#: exactly the one worth deleting.
PROVIDERS = ("GOOGLE", "MICROSOFT")


def secret_id(tenant_id: UUID, student_id: UUID, provider: str) -> str:
    """One secret per student per provider."""
    return f"tehsil/mailbox/{tenant_id}/{student_id}/{provider}"


def _client(client: object | None) -> object:
    return client if client is not None else boto3.client("secretsmanager")


def store_refresh_token(
    *,
    tenant_id: UUID,
    student_id: UUID,
    provider: str,
    refresh_token: str,
    client: object | None = None,
) -> None:
    """Write the grant, creating the secret the first time and overwriting after.

    Reconnecting is the ordinary case -- a refresh failure marks the connection
    ERROR and the student connects again -- so an existing secret is not an
    error.
    """
    secrets = _client(client)
    name = secret_id(tenant_id, student_id, provider)
    payload = json.dumps({"refresh_token": refresh_token})
    try:
        secrets.create_secret(Name=name, SecretString=payload)  # type: ignore[attr-defined]
    except botocore.exceptions.ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceExistsException":
            raise
        secrets.put_secret_value(SecretId=name, SecretString=payload)  # type: ignore[attr-defined]


def replace_refresh_token(
    *,
    tenant_id: UUID,
    student_id: UUID,
    provider: str,
    refresh_token: str,
    client: object | None = None,
) -> None:
    """Overwrite an existing grant with the one a refresh just rotated in.

    Put only, never create: the sync worker calls this, and it holds
    PutSecretValue but not CreateSecret. A secret that is gone was erased or
    revoked, and recreating it would undo that.
    """
    _client(client).put_secret_value(  # type: ignore[attr-defined]
        SecretId=secret_id(tenant_id, student_id, provider),
        SecretString=json.dumps({"refresh_token": refresh_token}),
    )


def refresh_token_for(
    *, tenant_id: UUID, student_id: UUID, provider: str, client: object | None = None
) -> str | None:
    secrets = _client(client)
    try:
        response = secrets.get_secret_value(SecretId=secret_id(tenant_id, student_id, provider))  # type: ignore[attr-defined]
        token = json.loads(response["SecretString"])["refresh_token"]
    except (botocore.exceptions.ClientError, KeyError, TypeError, json.JSONDecodeError):
        # Deliberately not logging the exception or the id: botocore puts the
        # SecretId in its message, and the SecretId names the student.
        logger.warning("no mailbox grant for provider %s", provider)
        return None
    return str(token)


def delete_student_mailbox_tokens(
    *, tenant_id: UUID, student_id: UUID, provider: str | None = None, client: object | None = None
) -> int:
    """Destroy this student's mailbox grant(s). Returns how many existed.

    `provider=None` (the default) walks every provider in PROVIDERS -- the
    shape advance_deletion needs and must keep using: an erasure destroys
    everything a student ever connected, not one connection at a time. A
    caller revoking a single connection (apps/mailbox/views.py::revoke) passes
    that connection's own provider instead, so revoking GOOGLE does not take
    down a MICROSOFT connection the student never touched.

    Called from advance_deletion before the redaction transaction, on the same
    path and for the same reason as delete_student_portal_credentials: a grant
    on a person's mail outliving their erasure is the failure this ordering
    exists to prevent. An absent secret is success; anything else propagates, so
    EXECUTED is never written over a secret that is still live.
    """
    secrets = _client(client)
    destroyed = 0
    for candidate in (provider,) if provider is not None else PROVIDERS:
        try:
            secrets.delete_secret(  # type: ignore[attr-defined]
                SecretId=secret_id(tenant_id, student_id, candidate),
                ForceDeleteWithoutRecovery=True,
            )
        except botocore.exceptions.ClientError as error:
            if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
            continue
        destroyed += 1
    return destroyed
