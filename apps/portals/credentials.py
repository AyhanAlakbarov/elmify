"""Portal passwords the platform holds for students (spec 2026-10-09 §6, D3).

In Secrets Manager under their own KMS key, one secret per student per portal,
never in Postgres -- a database dump must not be a set of live portal logins.
The path shape is load-bearing: it is what lets erasure delete every secret a
student owns without ListSecrets, which IAM cannot scope to a resource. The
web tier creates, reads and deletes; the worker only deletes, on erasure.

Nothing here may log a password, a SecretId (it names the student) or a
botocore message (it carries the SecretId).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import string
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import botocore.exceptions  # type: ignore[import-untyped]
from django.conf import settings

from .models import PortalForm

logger = logging.getLogger(__name__)

#: Accepted by every portal sampled so far; no quote, backslash, angle bracket,
#: ampersand, percent or space, which some forms mangle or refuse.
_SYMBOLS = "!#-_."
#: The one guaranteed symbol. Portals that count only !@#$%^&* as special
#: refuse a password whose only symbols are -_. (measured: 32.4% of them).
_REQUIRED_SYMBOLS = "!#"
_LENGTH = 24
#: Below this a generated password is weaker than the student would choose.
_FLOOR = 12


class PasswordRulesUnmet(Exception):
    """The portal's box cannot hold a password we are willing to make."""


def secret_id(tenant_id: UUID, student_id: UUID, portal_host: str) -> str:
    """One secret per student per portal.

    Per *student*, not per tenant: a portal account belongs to the applicant.
    """
    return f"elmify/portal/{tenant_id}/{student_id}/{portal_host}"


def aws_code(error: botocore.exceptions.ClientError) -> str:
    """The error's code -- the one part of a botocore error safe to log: its
    message names the SecretId."""
    return str(error.response.get("Error", {}).get("Code", "unknown"))


def _client(client: object | None) -> object:
    return client if client is not None else boto3.client("secretsmanager")


_SAFE_RULE_SYMBOLS = "!@#$%_-."
_RANGE_CAP_RE = re.compile(
    r"\b(?:(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})\s*(?:char\w*|zeichen\w*|caract\w*|символ\w*)"
    r"|(?:max(?:imum)?|up\s+to|at\s+most|no\s+more\s+than|höchstens|maximal)\s*(\d{1,3})(?:\s*(?:char\w*|zeichen\w*|caract\w*|символ\w*))?)\b",
    re.IGNORECASE,
)
_NO_SYMBOLS_RE = re.compile(
    r"\b(?:letters\s+and\s+(?:numbers|digits)\s+only|alphanumeric\s+only"
    r"|no\s+special\s+characters|without\s+special\s+characters)\b",
    re.IGNORECASE,
)


def _rules_max_length(password_rules: str) -> int | None:
    caps: list[int] = []
    for match in _RANGE_CAP_RE.finditer(password_rules):
        raw = match.group(2) or match.group(3)
        if raw:
            caps.append(int(raw))
    return min(caps) if caps else None


def generate_password(max_length: int | None = None, *, password_rules: str = "") -> str:
    """24 characters (fewer when the portal's box or rules cap it), one of each kind."""
    effective_max = max_length
    if password_rules:
        rule_cap = _rules_max_length(password_rules)
        if rule_cap is not None:
            effective_max = rule_cap if effective_max is None else min(effective_max, rule_cap)
    length = _LENGTH if effective_max is None else min(_LENGTH, effective_max)
    if length < _FLOOR:
        raise PasswordRulesUnmet(f"box holds {length} characters")
    if password_rules and _NO_SYMBOLS_RE.search(password_rules):
        alpha_num = string.ascii_letters + string.digits
        chars = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
            *(secrets.choice(alpha_num) for _ in range(length - 3)),
        ]
        secrets.SystemRandom().shuffle(chars)
        return "".join(chars)
    explicit_symbols = (
        "".join(dict.fromkeys(c for c in password_rules if c in _SAFE_RULE_SYMBOLS))
        if password_rules
        else ""
    )
    req_symbols = explicit_symbols or _REQUIRED_SYMBOLS
    all_symbols = explicit_symbols or _SYMBOLS
    alphabet = string.ascii_letters + string.digits + all_symbols
    chars = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(req_symbols),
        *(secrets.choice(alphabet) for _ in range(length - 4)),
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def create_password(
    *,
    tenant_id: UUID,
    student_id: UUID,
    portal_host: str,
    username: str,
    max_length: int | None = None,
    password_rules: str = "",
    client: object | None = None,
) -> str:
    """Make and store this account's password, or return the one already stored.

    Create-once on purpose: a reloaded sign-up page must type the SAME
    password, and two racing requests must agree -- the loser of CreateSecret
    reads the winner's.

    Erasure finds this secret only through a PortalForm host
    (delete_student_portal_credentials): pass one.
    """
    store = _client(client)
    name = secret_id(tenant_id, student_id, portal_host)
    password = generate_password(max_length, password_rules=password_rules)
    key = settings.PORTAL_SECRETS_KMS_KEY_ID
    try:
        store.create_secret(  # type: ignore[attr-defined]
            Name=name,
            SecretString=json.dumps({"username": username, "password": password}),
            **({"KmsKeyId": key} if key else {}),
        )
    except botocore.exceptions.ClientError as error:
        if aws_code(error) != "ResourceExistsException":
            raise
        existing = password_for(
            tenant_id=tenant_id, student_id=student_id, portal_host=portal_host, client=store
        )
        if existing is None:
            raise
        return existing
    return password


def password_for(
    *, tenant_id: UUID, student_id: UUID, portal_host: str, client: object | None = None
) -> str | None:
    try:
        response = _client(client).get_secret_value(  # type: ignore[attr-defined]
            SecretId=secret_id(tenant_id, student_id, portal_host)
        )
        password = json.loads(response["SecretString"])["password"]
    except botocore.exceptions.ClientError as error:
        # Only "confirmed gone" is None; AccessDenied, throttling and the rest
        # are not evidence the secret is absent and must not read as such.
        if aws_code(error) != "ResourceNotFoundException":
            raise
        logger.warning("no portal password for %s", portal_host)
        return None
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        logger.warning(
            "corrupt portal password payload for %s (%s)", portal_host, type(error).__name__
        )
        return None
    return password if isinstance(password, str) else None


def delete_password(
    *, tenant_id: UUID, student_id: UUID, portal_host: str, client: object | None = None
) -> bool:
    """Destroy one account's password. False when there was none.

    Anything but "already absent" propagates: a caller that records "handed
    over" over a secret that is still live has told the student something false.
    """
    try:
        _client(client).delete_secret(  # type: ignore[attr-defined]
            SecretId=secret_id(tenant_id, student_id, portal_host),
            ForceDeleteWithoutRecovery=True,
        )
    except botocore.exceptions.ClientError as error:
        if aws_code(error) != "ResourceNotFoundException":
            raise
        return False
    return True


def delete_student_portal_credentials(
    *, tenant_id: UUID, student_id: UUID, client: object | None = None
) -> int:
    """Destroy every portal credential belonging to one student. Returns the count.

    Called from apps/audit/deletion.py on the EXECUTED transition, beside
    delete_student_documents: GDPR erasure that leaves live portal logins behind
    is the failure CLAUDE.md's Phase 3 rules name explicitly.

    The portal list comes from PortalForm rather than from ListSecrets, so the
    IAM grant stays scoped to the secret prefix -- ListSecrets cannot be
    resource-scoped, and widening a deletion path to account-wide enumeration
    to save a query is the wrong trade.

    # ponytail: iterates known portals. A credential stored for a portal that
    # has no PortalForm row would be missed. create_password's only caller
    # (ext_api.py::portal_login) passes the host of an application's own
    # PortalForm, so every secret it makes is under a host visited here; a new
    # caller passing any other host must also make erasure find it.
    """
    store = _client(client)
    hosts = PortalForm.objects.values_list("portal_host", flat=True).distinct()
    # delete_password treats "already absent" as success and raises anything
    # else -- AccessDenied above all: advance_deletion writes EXECUTED only if
    # this returns, so a swallowed failure records an erasure that did not happen.
    return sum(
        delete_password(tenant_id=tenant_id, student_id=student_id, portal_host=host, client=store)
        for host in hosts
    )
