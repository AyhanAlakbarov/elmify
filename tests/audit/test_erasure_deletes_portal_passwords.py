"""Erasure destroys a platform-held portal password, end to end.

Every other erasure test replaces delete_student_portal_credentials with a
lambda. This one runs the REAL helper against a fake Secrets Manager, so the
guarantee survives anything that rewrites the call site (PR #169 does).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.audit import deletion
from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.portals import credentials
from apps.portals.models import PortalForm
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership
from tests.portals.test_credentials import FakeSecrets

pytestmark = pytest.mark.django_db

HOST = "apply.example.edu"


def test_executing_a_deletion_destroys_the_students_portal_password(
    agency_a, django_user_model, monkeypatch, settings
) -> None:
    settings.PORTAL_SECRETS_KMS_KEY_ID = ""
    store = FakeSecrets()
    monkeypatch.setattr(credentials, "_client", lambda client=None: store)
    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    PortalForm.objects.create(portal_host=HOST, form_key=f"k-{uuid4()}")
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="erase-portal")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        credentials.create_password(
            tenant_id=agency_a.id, student_id=student.id, portal_host=HOST, username="s@e.edu"
        )
        assert list(store.store) == [credentials.secret_id(agency_a.id, student.id, HOST)]

        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")

    assert store.store == {}
