"""Fixtures for the sender-allowlist tests.

Built from the same model chain tests/funding/conftest.py already uses for a
published pack (RecommendationRun -> PackVersion -> PackCandidate ->
RecommendationCandidate -> EvidenceClaim), plus a portals.Application /
PortalForm for the portal-domain half of the allowlist.

Deviation from the task brief's fixture prose: it names
`https://www.tum.de/en/studies` / `https://www.daad.de/en/` as the evidence
URLs, but `apps/mailbox/filter.py::_host_of` does no "www." stripping -- an
EvidenceClaim on those exact URLs would allowlist `www.tum.de` /
`www.daad.de`, not `tum.de` / `daad.de`, which is what
test_the_allowlist_is_the_student_s_own_pack_and_portals actually asserts.
The URLs below drop "www." so the fixture agrees with the (verbatim, per the
brief) test file rather than with the prose describing it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import botocore.exceptions
import pytest
import urllib3.util.connection
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.funding.models import (
    EvidenceClaim,
    PackCandidate,
    PackVersion,
    RecommendationCandidate,
    RecommendationRun,
)
from apps.funding.services import consider_named_program
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.mailbox.oauth import Grant
from apps.mailbox.providers import MailBody, MessageHeader
from apps.mailbox.sync import SyncRefused
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from tests.funding.conftest import make_published_pack, make_run


class FakeProvider:
    """A fake MailboxProvider that records every call it receives.

    Moved here from test_sync.py (task 13) so test_command.py's log-capture
    test can drive a real sync without duplicating it.
    """

    name = "GOOGLE"

    def __init__(self, headers: tuple[MessageHeader, ...]) -> None:
        self._headers = headers
        self.listed: list[datetime] = []
        self.searched: list[tuple[str, ...]] = []
        self.bodies_fetched: list[str] = []

    def list_headers(self, *, access_token: str, since: datetime, senders=()):
        self.listed.append(since)
        self.searched.append(senders)
        return self._headers

    def fetch_body(self, *, access_token: str, message_id: str) -> MailBody:
        self.bodies_fetched.append(message_id)
        return MailBody("body text")


def _grant():
    import json

    class Grant:
        def get_secret_value(self, *, SecretId):
            return {"SecretString": json.dumps({"refresh_token": "rt"})}

    return Grant()


def _evidenced_candidate(
    agency, run: RecommendationRun, *, program_name: str, source_url: str
) -> RecommendationCandidate:
    with tenant_scope(agency.id):
        evidence = EvidenceClaim.objects.create(
            source_url=source_url,
            claim="Official source confirms funding.",
            last_checked_at=timezone.now(),
        )
        return RecommendationCandidate.objects.create(
            run=run,
            evidence=evidence,
            program_name=program_name,
            funding_gap=Decimal("0.00"),
            currency="EUR",
            eligible=True,
            state=RecommendationCandidate.State.VISIBLE,
            evidence_confidence="HIGH",
        )


@pytest.fixture
def student_with_pack(agency_a, membership_a):
    """A published pack with two evidenced candidates (tum.de, daad.de) plus
    one portal application (uni-bonn.de).

    Left open on the tenant scope it creates in: `allowed_senders` reads
    "inside the caller's tenant transaction" per its own docstring, and none
    of test_filter.py's test functions open one themselves.
    """
    run = make_run(agency_a, membership_a)
    tum = _evidenced_candidate(
        agency_a, run, program_name="MSc Informatics", source_url="https://tum.de/en/studies"
    )
    daad = _evidenced_candidate(
        agency_a, run, program_name="DAAD Scholarship", source_url="https://daad.de/en/"
    )
    pack = make_published_pack(agency_a, run, (tum, daad))

    form = PortalForm.objects.create(portal_host="portal.uni-bonn.de", form_key="application")
    with tenant_scope(agency_a.id):
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        yield membership_a, pack


@pytest.fixture
def second_student(agency_a):
    """Another student in the same tenant, with no pack and no application of
    their own -- kept in agency_a rather than agency_b's membership_b because
    student_with_pack leaves agency_a's tenant scope open for the test body
    (see its docstring), and opening agency_b's scope on top of it would
    raise TenantContextConflict."""
    with tenant_scope(agency_a.id):
        user = get_user_model().objects.create_user(username=f"second-student-{uuid4()}")
        return Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.STUDENT)


@pytest.fixture
def connection(agency_a, membership_a):
    """A saved GOOGLE/CONTENT/ACTIVE MailboxConnection, for test_oauth.py's grant tests."""
    with tenant_scope(agency_a.id):
        return MailboxConnection.objects.create(
            tenant=agency_a,
            membership=membership_a,
            provider=MailboxConnection.Provider.GOOGLE,
            tier=MailboxConnection.Tier.CONTENT,
            status=MailboxConnection.Status.ACTIVE,
            address="student@gmail.test",
        )


@pytest.fixture
def connection_with_pack(student_with_pack):
    """The student_with_pack student, plus an ACTIVE CONTENT connection."""
    student, _pack = student_with_pack
    with tenant_scope(student.tenant_id), tenant_transaction(student.tenant_id):
        return MailboxConnection.objects.create(
            tenant_id=student.tenant_id,
            membership=student,
            provider=MailboxConnection.Provider.GOOGLE,
            address="student@gmail.test",
        )


@pytest.fixture
def two_connections_with_pack(student_with_pack):
    """The student_with_pack student, plus TWO ACTIVE connections -- one
    GOOGLE, one MICROSOFT -- for the revoke-one-provider-only test
    (test_views.py::test_revoking_one_provider_does_not_touch_the_other).
    """
    student, _pack = student_with_pack
    with tenant_scope(student.tenant_id), tenant_transaction(student.tenant_id):
        google = MailboxConnection.objects.create(
            tenant_id=student.tenant_id,
            membership=student,
            provider=MailboxConnection.Provider.GOOGLE,
            address="student@gmail.test",
        )
        microsoft = MailboxConnection.objects.create(
            tenant_id=student.tenant_id,
            membership=student,
            provider=MailboxConnection.Provider.MICROSOFT,
            address="student@outlook.test",
        )
        return google, microsoft


@pytest.fixture(autouse=True)
def _no_outbound_connection(monkeypatch):
    """No test in this package may open a socket to a real host.

    Every provider takes its transport as a default argument, so a test that
    forgets to pass a fake reaches Google or Microsoft for real and, with no
    credentials, fails in a way that looks like a provider refusal. Patched at
    urllib3's own connect helper, which every pool and PoolManager path shares,
    so the failure names the host instead.
    """

    def refuse(address, *_args, **_kwargs):
        raise AssertionError(f"a mailbox test tried to connect to {address}")

    monkeypatch.setattr(urllib3.util.connection, "create_connection", refuse)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _pilot_providers(settings):
    """Existing tests in this package connect with GOOGLE; the pilot default
    (Task 6) is MICROSOFT only. Widen it here so only the dedicated pilot test
    (test_a_provider_not_offered_in_the_pilot_is_refused) exercises the
    production default."""
    settings.MAILBOX_PROVIDERS = ("GOOGLE", "MICROSOFT")


@pytest.fixture
def two_agencies_with_connections(agency_a, membership_a, agency_b, membership_b):
    """One ACTIVE connection in each of two agencies, for the sweep tests."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        MailboxConnection.objects.create(
            tenant_id=agency_a.id,
            membership=membership_a,
            provider=MailboxConnection.Provider.GOOGLE,
            address="student-a@gmail.test",
        )
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        MailboxConnection.objects.create(
            tenant_id=agency_b.id,
            membership=membership_b,
            provider=MailboxConnection.Provider.GOOGLE,
            address="student-b@gmail.test",
        )


@pytest.fixture
def patched_sync(monkeypatch):
    """Records every connection the command hands to sync_connection, never
    actually syncing anything."""

    class _Recorder:
        def __init__(self) -> None:
            self.synced: list[object] = []

        def __call__(self, connection, **_kwargs):
            self.synced.append(connection.id)
            return []

    recorder = _Recorder()
    monkeypatch.setattr(
        "apps.mailbox.management.commands.sync_mailboxes.sync_connection", recorder
    )
    return recorder


@pytest.fixture
def failing_then_working_sync(monkeypatch):
    """Like patched_sync, except the first connection it sees refuses.

    Records on entry, before raising or returning, so its length says how many
    connections the sweep reached -- not how many succeeded. Proves a refusal
    on one connection does not strand the rest.
    """

    class _Recorder:
        def __init__(self) -> None:
            self.synced: list[object] = []

        def __call__(self, connection, **_kwargs):
            self.synced.append(connection.id)
            if len(self.synced) == 1:
                raise SyncRefused("boom")
            return []

    recorder = _Recorder()
    monkeypatch.setattr(
        "apps.mailbox.management.commands.sync_mailboxes.sync_connection", recorder
    )
    return recorder


@pytest.fixture
def recording_provider():
    """One real-shaped tum.de message: enough sender and body text in play
    that a logging leak would be caught, for test_command.py's log-capture
    test."""
    header = MessageHeader(
        message_id="log-capture-m0",
        sender="admissions@tum.de",
        received_at=datetime(2026, 9, 1, tzinfo=UTC),
        authenticated=True,
    )
    return FakeProvider((header,))


@pytest.fixture(autouse=True)
def no_live_token_endpoint(monkeypatch):
    """sync_connection mints an access token, and `http=None` means urllib3.

    Without this every test in test_sync.py POSTs to oauth2.googleapis.com from
    a default `uv run pytest` -- which no test in this repository may do. The
    exchange itself is covered by test_oauth.py against a fake transport; here
    it is noise, so it is stubbed. A test that WANTS the refusal path passes a
    secrets client that has no grant, and GrantRefused is raised before this
    stub is reached.
    """
    monkeypatch.setattr("apps.mailbox.sync.access_token_for", lambda *a, **k: "access-token")


@pytest.fixture
def student_with_named_program(agency_a, membership_a):
    """A pack whose only candidate is a student-named program still awaiting
    review, whose evidence is the `research.pending.internal` placeholder
    `consider_named_program` mints -- the fixture that proves that placeholder
    never becomes an allowed sender domain even if it reached the pack."""
    run = make_run(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        pack = PackVersion.objects.create(run=run, version=1, published_at=timezone.now())
        candidate = consider_named_program(pack, "Some University Program", membership_a)
        PackCandidate.objects.create(pack_version=pack, candidate=candidate)
        RecommendationRun.objects.filter(id=run.id).update(state=RecommendationRun.State.PUBLISHED)
        yield membership_a


@pytest.fixture
def signal_on_application(agency_a, membership_a):
    """A factory for test_actions.py: one MailSignal on one Application whose
    portal lives at the given domain, reached through a MailboxConnection.

    Not named by any earlier task's brief -- Task 11's test file assumes it
    exists but nothing before this task built it. Its test bodies save through
    `signal.application` and `apply_verdict` inside only `tenant_transaction`
    (never their own `tenant_scope`), the same shape `sync.py` uses in
    production -- TenantScopedModel.save() also needs the Python-side
    `current_tenant_id()` contextvar, not just the transaction-local GUC, so
    this fixture stays inside `tenant_scope` for the whole test body, the same
    "left open" shape `student_with_pack` above documents on itself.
    """

    def _make(domain: str) -> MailSignal:
        # get_or_create, both (ruling F6): a test may ask for two signals on
        # the same domain, and the form and the active connection are unique.
        form, _ = PortalForm.objects.get_or_create(portal_host=domain, form_key="application")
        with tenant_transaction(agency_a.id):
            application = Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
            )
            connection, _ = MailboxConnection.objects.get_or_create(
                tenant=agency_a,
                membership=membership_a,
                provider=MailboxConnection.Provider.GOOGLE,
                status=MailboxConnection.Status.ACTIVE,
                defaults={"address": "student@gmail.test"},
            )
            return MailSignal.objects.create(
                tenant=agency_a,
                connection=connection,
                provider_message_id=f"m-{uuid4()}",
                sender_domain=domain,
                received_at=timezone.now(),
                application=application,
            )

    with tenant_scope(agency_a.id):
        yield _make


@pytest.fixture
def student_client(client, domain_a, user_a, membership_a):
    """An authenticated client for membership_a, host-bound to domain_a --
    HostTenantContextMiddleware resolves the tenant from the host, so every
    request this client makes must carry it. Returned with the membership
    itself so a test can assert against it without a second lookup."""
    client.force_login(user_a)
    client.defaults["HTTP_HOST"] = domain_a.host
    return client, membership_a


@pytest.fixture
def second_student_client(domain_a, second_student):
    """A second, independently authenticated client -- never the same Client
    instance student_client uses, so the two sessions cannot bleed into each
    other."""
    other = Client()
    other.force_login(second_student.user)
    other.defaults["HTTP_HOST"] = domain_a.host
    return other


@pytest.fixture
def fake_exchange(monkeypatch):
    """Stubs the token exchange with a provider that always grants.

    Patched on apps.mailbox.views, not apps.mailbox.oauth: the view imported
    the name directly, so that is the reference the view actually calls.
    """
    monkeypatch.setattr(
        "apps.mailbox.views.exchange_code",
        lambda *, provider, code: Grant(address="student@gmail.test", refresh_token="rt-test"),
    )


class _FakeSecrets:
    """The same fake shape tests/mailbox/test_secrets.py uses, minus the call
    log: here it is a stand-in for a real client, not a thing under test."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def create_secret(self, *, Name: str, SecretString: str) -> dict[str, str]:
        if Name in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceExistsException"}}, "CreateSecret"
            )
        self.store[Name] = SecretString
        return {"ARN": Name}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> dict[str, str]:
        self.store[SecretId] = SecretString
        return {"ARN": SecretId}

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "GetSecretValue"
            )
        return {"SecretString": self.store[SecretId]}

    def delete_secret(self, *, SecretId: str, ForceDeleteWithoutRecovery: bool) -> dict[str, str]:
        if SecretId not in self.store:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}}, "DeleteSecret"
            )
        del self.store[SecretId]
        return {"ARN": SecretId}


@pytest.fixture(autouse=True)
def fake_secrets(monkeypatch):
    """Autouse, matching no_live_token_endpoint above: a view under test may
    call store_refresh_token/delete_student_mailbox_tokens without asking for
    this fixture by name, and none of them may reach real Secrets Manager."""
    fake = _FakeSecrets()
    monkeypatch.setattr("apps.mailbox.secrets.boto3.client", lambda *a, **k: fake)
    return fake
