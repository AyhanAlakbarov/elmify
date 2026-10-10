"""The portal spine, run under a role that RLS actually applies to.

The rest of the suite runs as the local test superuser, which is BYPASSRLS, so
a tenant-scoped read taken outside a ``tenant_transaction`` passes there and
returns zero rows in production. That difference is why this module exists
rather than being folded into test_services.py.

tests/conftest.py::runtime_connection proves the same property with a raw
psycopg connection; that cannot exercise the ORM, and the bug this guards is a
*lazy FK traversal* -- pure ORM machinery.

The ``rls_enforced_orm`` fixture these tests run behind lives in tests/conftest.py:
tests/audit/test_identity_rls.py needs it too.
"""

from contextlib import contextmanager
from functools import partial
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from tests.portals.fakes import FakePortalSession

ENTRIES = [
    {
        "profile_field": "identity.full_name",
        "action": {"selector": "#name", "method": "fill", "arguments": ["%value%"]},
    },
    {
        "profile_field": "personal.city",
        "action": {"selector": "#city", "method": "fill", "arguments": ["%value%"]},
    },
]


@pytest.fixture
def prepared_application(agency_a, membership_a):
    """Committed as the test superuser, before the ORM changes roles."""
    from apps.documents.models import VerifiedFact
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"personal-details-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        review_required=False,
    )
    FieldMap.objects.create(portal_form=form, version=1, entries=ENTRIES)
    with tenant_scope(agency_a.id):
        for category, payload in (
            ("IDENTITY", {"full_name": "Ada Byron"}),
            ("PERSONAL", {"city": "London"}),
        ):
            VerifiedFact.objects.create(
                tenant=agency_a,
                student=membership_a,
                category=category,
                payload=payload,
                source_tier=VerifiedFact.SourceTier.AUTHORITATIVE_DOCUMENT,
                source_ref="passport.pdf",
                confirmed_by=membership_a,
                confirmed_at=timezone.now(),
                created_by=membership_a,
            )
        return Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )


@pytest.fixture
def escalated_application(prepared_application):
    """One escalated application, committed as the superuser like its parent."""
    from apps.portals.escalation import Trigger, escalate

    with tenant_scope(prepared_application.tenant_id):
        item = escalate(prepared_application, Trigger.MISSING_FACT, detail="passport number")
    return prepared_application, item


@contextmanager
def _session_factory(session):
    yield session


class _FakeSQS:
    """Same shape as tests/documents/test_europass_queue.py::_FakeSQS."""

    def __init__(self, messages=()):
        self.sent = []
        self.deleted = []
        self._messages = list(messages)

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {}

    def receive_message(self, **kwargs):
        return {"Messages": self._messages}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)
        return {}


@pytest.mark.django_db(transaction=True)
def test_the_spine_reads_the_student_and_their_facts_under_row_level_security(
    prepared_application, rls_enforced_orm
):
    """RED before the fix, in two independent places.

    1. ``handle_portal_message`` traversed ``application.student`` lazily, after
       the loading transaction had committed and taken ``app.tenant_id`` with
       it. Django resolves a forward FK through ``_base_manager``, so RLS is the
       only filter left and it matches nothing -- ``RelatedObjectDoesNotExist``,
       uncaught, out of the worker loop and into the DLQ.
    2. ``prepare_application`` called ``verified_values`` at autocommit, so
       every ``documents_verifiedfact`` row was invisible and a complete
       application escalated as MISSING_FACT.

    ``verified_values`` is deliberately NOT monkeypatched here; every other
    prepare_application test patches it away, which is one of the three reasons
    this never showed up.
    """
    from apps.portals.models import Application
    from apps.portals.schemas import PortalMessage
    from apps.portals.worker import handle_portal_message

    session = FakePortalSession()
    message = PortalMessage(
        kind="prepare_application",
        tenant_id=prepared_application.tenant_id,
        application_id=prepared_application.id,
    )
    with tenant_scope(prepared_application.tenant_id):
        handle_portal_message(message, session_factory=lambda _app: _session_factory(session))

        with tenant_transaction(prepared_application.tenant_id):
            application = Application.objects.get(id=prepared_application.id)

    assert application.state == Application.State.READY_TO_SUBMIT
    assert session.values == {"#name": "Ada Byron", "#city": "London"}


@pytest.fixture
def portal_worker(monkeypatch, settings, tmp_path):
    """Run the real management command with a fake queue and a fake browser.

    Both commands below are entry points, so they run with *no* ambient
    transaction (``django_db(transaction=True)``) -- which is the only place a
    missing ``transaction.atomic()`` around ``set_local_tenant`` raises rather
    than passing silently. Combined with ``rls_enforced_orm`` this is the shape
    production actually has, and neither half is observable in the rest of the
    suite.
    """
    from apps.portals.management.commands import run_portal_worker as command
    from apps.portals.worker import handle_portal_message

    settings.PORTAL_PROFILE_ROOT = tmp_path / "profiles"
    settings.PORTAL_QUEUE_URL = "https://sqs.test/portal"

    def _run(sqs, session=None):
        monkeypatch.setattr(command, "boto3", SimpleNamespace(client=lambda _name: sqs))
        if session is not None:
            monkeypatch.setattr(
                command,
                "handle_portal_message",
                partial(
                    handle_portal_message,
                    session_factory=lambda _app: _session_factory(session),
                ),
            )
        call_command("run_portal_worker", "--once")

    return _run


def _reload(application):
    from apps.portals.models import Application

    with tenant_scope(application.tenant_id), tenant_transaction(application.tenant_id):
        return Application.objects.get(id=application.id)


@pytest.mark.django_db(transaction=True)
def test_the_worker_loop_prepares_one_message_under_row_level_security(
    prepared_application, rls_enforced_orm, portal_worker
):
    """The loop itself, not its pieces: sweep, resume sweep, receive, handle, delete.

    ``handle_portal_message`` is patched only to swap the browser for
    FakePortalSession; the tenant scope, the transaction boundaries, the state
    guard and prepare_application are the real ones.
    """
    from apps.portals.models import Application
    from apps.portals.schemas import PortalMessage

    session = FakePortalSession()
    message = PortalMessage(
        kind="prepare_application",
        tenant_id=prepared_application.tenant_id,
        application_id=prepared_application.id,
    )
    sqs = _FakeSQS([{"Body": message.model_dump_json(), "ReceiptHandle": "rh-1"}])

    portal_worker(sqs, session)

    assert _reload(prepared_application).state == Application.State.READY_TO_SUBMIT
    assert session.values == {"#name": "Ada Byron", "#city": "London"}
    # Deleted only after the handler returned, which is the whole retry story.
    assert sqs.deleted == [
        {"QueueUrl": "https://sqs.test/portal", "ReceiptHandle": "rh-1"}
    ]


@pytest.mark.django_db(transaction=True)
def test_the_worker_loop_resumes_a_finished_exception_under_row_level_security(
    escalated_application, rls_enforced_orm, portal_worker
):
    """resume_completed_exceptions' select joins concierge_roadmapitem.

    Both tables carry tenant policies, so the join returns zero rows unless the
    GUC is set -- silently, with no error, which is precisely how the spine's
    other RLS bug behaved.
    """
    from apps.concierge.models import RoadmapItem
    from apps.portals.models import Application

    application, item = escalated_application
    with tenant_scope(application.tenant_id), tenant_transaction(application.tenant_id):
        RoadmapItem.objects.filter(id=item.id).update(state=RoadmapItem.State.DONE)

    sqs = _FakeSQS()
    portal_worker(sqs)

    resumed = _reload(application)
    assert resumed.state == Application.State.PREPARING
    assert resumed.exception_item_id is None
    assert len(sqs.sent) == 1
    assert sqs.sent[0]["QueueUrl"] == "https://sqs.test/portal"
    assert '"kind":"resume_application"' in sqs.sent[0]["MessageBody"].replace(" ", "")


@pytest.mark.django_db(transaction=True)
def test_the_intervention_report_counts_rows_under_row_level_security(
    escalated_application, rls_enforced_orm
):
    """§5.4's measured rate, from the command an operator actually runs.

    Without ``transaction.atomic()`` set_local_tenant raises here; without
    set_local_tenant the per-tenant aggregations return zero and every count
    prints 0. The suite's BYPASSRLS superuser sees neither failure.
    """
    out = StringIO()
    call_command("report_portal_interventions", stdout=out)

    rows = [line.split() for line in out.getvalue().splitlines()]
    row = next(row for row in rows if row[0] == "apply.example.edu")
    assert row[1:] == ["1", "1", "0", "100.00%"]
