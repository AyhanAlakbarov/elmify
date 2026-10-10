"""Platform-managed portal credentials, and the one case that is not.

§5.2 routes an expired session to reauthentication first, a consultant second,
and the student only for authentication that reaches their own device.

Credentials are never stored in Postgres. The provider resolves them at use
time from AWS Secrets Manager, so a database dump is not a set of live portal
logins and the credential's whole lifecycle (rotation, access audit, deletion)
belongs to the secret store rather than to this app.
"""

import json
import logging
from typing import NamedTuple, Protocol
from uuid import UUID

import boto3  # type: ignore[import-untyped]
import botocore.exceptions  # type: ignore[import-untyped]

from apps.tenancy.db import tenant_transaction

from .escalation import Trigger, escalate
from .fill import FillInterrupted, MissingFact, fill_form
from .models import Application, ApplicationStep, FieldMap, PortalForm, RecoveryEvent
from .session import PortalSession, UnsafeAction

logger = logging.getLogger(__name__)

LOGIN_FORM_KEY = "login"
LOGIN_USERNAME_FIELD = "portal.username"
#: A profile field *name*, not a credential -- bandit's B105 pattern-matches
#: the string regardless.
LOGIN_PASSWORD_FIELD = "portal.password"  # nosec B105


class PortalCredentials(NamedTuple):
    username: str
    password: str

    def __repr__(self) -> str:
        """NamedTuple's default repr prints the password.

        Nothing renders one today -- no error reporter capturing locals is
        wired up -- so this is a latent leak rather than a live one. It is
        also the kind that becomes a breach on the day somebody adds one,
        in a change that never touches this file.
        """
        return f"PortalCredentials(username={self.username!r}, password=***)"


class CredentialProvider(Protocol):
    def credentials_for(
        self, *, tenant_id: UUID, student_id: UUID, portal_host: str
    ) -> PortalCredentials | None: ...


def secret_id(tenant_id: UUID, student_id: UUID, portal_host: str) -> str:
    """One secret per student per portal.

    Per *student*, not per tenant: a portal account belongs to the applicant,
    so a tenant-wide credential would log every student into one person's
    account. The path shape is also what makes erasure possible without
    ListSecrets -- see delete_student_portal_credentials.
    """
    return f"tehsil/portal/{tenant_id}/{student_id}/{portal_host}"


class SecretsManagerCredentials:
    """Resolved at use time, never stored in Postgres (CLAUDE.md, Phase 3 rules).

    A missing or unreadable secret returns None rather than raising: an
    unconfigured portal is a consultant task, not a worker crash that
    redelivers the message until the DLQ catches it.
    """

    def __init__(self, client: object | None = None) -> None:
        self._client = client or boto3.client("secretsmanager")

    def credentials_for(
        self, *, tenant_id: UUID, student_id: UUID, portal_host: str
    ) -> PortalCredentials | None:
        try:
            response = self._client.get_secret_value(  # type: ignore[union-attr]
                SecretId=secret_id(tenant_id, student_id, portal_host)
            )
            payload = json.loads(response["SecretString"])
            return PortalCredentials(payload["username"], payload["password"])
        except (botocore.exceptions.ClientError, KeyError, TypeError, json.JSONDecodeError):
            # Deliberately not logging the exception: botocore puts the SecretId
            # in the message, and a ResourceNotFound for a name we constructed
            # is not information a log reader needs. Nothing here may reach a
            # log or an exception message with a credential in it. TypeError
            # covers a SecretString that parses as valid JSON but is a scalar
            # or list -- e.g. an operator pasting a bare "hunter2" -- where
            # payload["username"] raises rather than returning None.
            logger.warning("no portal credential for %s", portal_host)
            return None


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
    # has no PortalForm row would be missed; nothing can create one today,
    # because a portal with no form is a portal nothing can apply to.
    """
    secrets = client or boto3.client("secretsmanager")
    deleted = 0
    hosts = PortalForm.objects.values_list("portal_host", flat=True).distinct()
    for portal_host in hosts:
        try:
            secrets.delete_secret(  # type: ignore[union-attr]
                SecretId=secret_id(tenant_id, student_id, portal_host),
                ForceDeleteWithoutRecovery=True,
            )
            deleted += 1
        except botocore.exceptions.ClientError as error:
            # Already absent is success. Anything else -- AccessDenied,
            # InvalidRequest -- must propagate: advance_deletion writes
            # EXECUTED only if this returns, so a swallowed failure records an
            # erasure that did not happen. Until the WorkerTaskRole grant
            # lands (Task 14), AccessDenied is the live production case this
            # branch exists to catch.
            if error.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            logger.debug("no credential to delete for %s", portal_host)
            continue
    return deleted


def session_expired(session: PortalSession, portal_form: PortalForm) -> bool:
    return bool(portal_form.login_marker) and session.exists(portal_form.login_marker)


def reauthenticate(
    session: PortalSession, application: Application, *, provider: CredentialProvider
) -> bool:
    """Log back in. Returns True when the session is usable again.

    Every False path has already escalated, so the caller stops rather than
    deciding what a failure means.
    """
    portal_form = application.portal_form
    assert portal_form is not None  # never queued portal-less
    credentials = provider.credentials_for(
        tenant_id=application.tenant_id,
        student_id=application.student_id,
        portal_host=portal_form.portal_host,
    )
    if credentials is None:
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"no platform credential configured for {portal_form.portal_host}",
        )
        return False

    login_form = PortalForm.objects.filter(
        portal_host=portal_form.portal_host, form_key=LOGIN_FORM_KEY
    ).first()
    login_map = (
        FieldMap.current_for(login_form, application.tenant_id)
        if login_form is not None
        else None
    )
    if login_form is None or login_map is None:
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"login form for {portal_form.portal_host} has not been learned",
        )
        return False

    session.goto(login_form.form_url)
    # The credential travels the same path a student value does -- as a
    # Stagehand variable at act() time -- so it is never written to a FieldMap
    # and never reaches a model prompt.
    try:
        fill_form(
            session,
            login_map,
            {
                LOGIN_USERNAME_FIELD: credentials.username,
                LOGIN_PASSWORD_FIELD: credentials.password,
            },
        )
    except (MissingFact, UnsafeAction, FillInterrupted):
        # Host-only detail, deliberately: FillInterrupted wraps ActFailed,
        # whose message comes from Stagehand's act() result on a third-party
        # page and must never be interpolated into an escalation string.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"could not fill the login form for {portal_form.portal_host}",
        )
        return False
    session.press_enter()

    if portal_form.mfa_marker and session.exists(portal_form.mfa_marker):
        escalate(
            application,
            Trigger.APPLICANT_MFA,
            detail=f"{portal_form.portal_host} is asking for a second factor",
        )
        return False

    if session.exists(portal_form.login_marker):
        # Wrong password, locked account, or a login page that changed shape.
        # All three need a human and none of them need the student.
        escalate(
            application,
            Trigger.PORTAL_ERROR,
            detail=f"reauthentication to {portal_form.portal_host} did not take",
        )
        return False

    with tenant_transaction(application.tenant_id):
        RecoveryEvent.objects.create(
            portal_form=portal_form,
            kind=RecoveryEvent.Kind.SESSION_EXPIRED,
            page_url=login_form.form_url,
            detail={"portal_host": portal_form.portal_host},
        )
        # The tenant-side half of the same recovery: RecoveryEvent is
        # platform-scoped and carries no application reference, so without
        # this the tenant's own audit trail has no record a reauthentication
        # happened on their application (§5.5).
        ApplicationStep.objects.create(
            tenant=application.tenant,
            application=application,
            sequence=application.next_step_sequence(),
            kind="RECOVERY",
            detail={
                "kind": RecoveryEvent.Kind.SESSION_EXPIRED.value,
                "portal_host": portal_form.portal_host,
            },
        )
    logger.info("PortalRecovery kind=SESSION_EXPIRED portal=%s", portal_form.portal_host)
    return True
