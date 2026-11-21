"""Portal reads, run under a role that RLS actually applies to.

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

from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

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


@pytest.fixture
def answering_application(agency_a, membership_a):
    """An application whose one box the map is unsure of, and an APPROVED
    erasure for its student. Committed as the superuser before the ORM changes
    roles, like every fixture here."""
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy
    from apps.portals.models import Application, FieldMap, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu",
        form_key=f"answers-{uuid4()}",
        form_url="https://apply.example.edu/personal",
        review_required=False,
    )
    FieldMap.objects.create(portal_form=form, version=1, entries=[{
        "profile_field": "personal.home_town", "sure": False,
        "action": {"selector": "#y", "method": "fill", "arguments": ["%value%"]},
    }])
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
    return application, request


@pytest.mark.django_db(transaction=True)
def test_a_typed_answer_is_written_typed_back_and_erased_under_row_level_security(
    answering_application, rls_enforced_orm, monkeypatch
):
    """PortalAnswer is FORCE RLS and the test superuser bypasses it, so only
    here do its three paths meet the policy: record_answers writes inside the
    caller's tenant_transaction, mint_packet reads it back inside its own, and
    advance_deletion deletes it inside its set_local_tenant block -- outside
    that block the DELETE matches zero rows and EXECUTED is written anyway."""
    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.portals.answers import Answer, record_answers
    from apps.portals.models import PortalAnswer
    from apps.portals.packets import mint_packet

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    application, request = answering_application
    tenant_id = application.tenant_id

    def stored() -> int:
        with tenant_transaction(tenant_id):
            return PortalAnswer.objects.filter(student_id=application.student_id).count()

    with tenant_scope(tenant_id):
        assert [h.selector for h in mint_packet(application).hints] == ["#y"]
        with tenant_transaction(tenant_id):
            saved = record_answers(
                application, [Answer(selector="#y", kind="hint", value="Ganja")]
            )
        assert len(saved) == 1
        assert stored() == 1
        assert PortalAnswer.objects.count() == 0  # no GUC: the policy hides the row

        [own] = mint_packet(application).entries
        assert (own.selector, own.value, own.from_answer) == ("#y", "Ganja", True)

        advance_deletion(request, "EXECUTED")
        assert stored() == 0
