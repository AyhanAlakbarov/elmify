"""The scheduler, run under a role that RLS actually applies to.

The rest of the audit suite runs as the test superuser, which is BYPASSRLS, so
the command's scan sees every row there and passes for the wrong reason. In
production the runtime role is NOBYPASSRLS and audit_deletionrequest is FORCE
ROW LEVEL SECURITY on app.tenant_id, so without set_local_tenant inside the
transaction the scan is legal SQL returning zero rows: the command finds
nothing, exits 0, and no student is ever erased while every screen says the
erasure is scheduled.

Confirmed RED against a version of the command with set_local_tenant removed.
Same shape as tests/audit/test_identity_rls.py.

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0)


@pytest.fixture
def due_request(agency_a, user_a):
    """An overdue APPROVED request, committed as the superuser before
    rls_enforced_orm swaps the role -- the same ordering the portal and
    identity RLS tests use.
    """
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user_a, role=Membership.Role.STUDENT, active=True
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        DeletionRequest.objects.filter(id=request.id).update(
            execute_after=timezone.now() - timedelta(days=1)
        )
        return request


def test_the_command_erases_under_a_nobypassrls_role(agency_a, due_request, rls_enforced_orm):
    """RED with set_local_tenant removed, and unobservable anywhere else.

    Without the GUC the scan returns zero rows, the command exits 0 having done
    nothing, and the student stays locked out forever with their statutory
    month running.
    """
    call_command("execute_due_erasures")

    # tenant_transaction, not tenant_scope: the ORM is behind the NOBYPASSRLS
    # role by this point, and tenant_scope is only a contextvar -- it never
    # reaches Postgres, so the policy compares tenant_id against a NULL GUC and
    # the row this test is asserting on simply disappears. Same reason
    # test_identity_rls.py uses it.
    with tenant_transaction(agency_a.id):
        due_request.refresh_from_db()
    assert due_request.state == "EXECUTED", (
        "the scan found nothing under RLS -- set_local_tenant is missing "
        "from the command's transaction"
    )
