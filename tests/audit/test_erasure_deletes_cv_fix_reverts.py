"""Erasure removes the student's undone-fix rows (CV design 2026-10-12 §10).

Two rows on purpose: redacting both subjects to "" without the delete would
collide on cvfixrevert_one_per_subject and fail the whole erasure.
"""

import pytest
from django.utils import timezone

from apps.audit import deletion
from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.documents.cv_fixes import remember_revert
from apps.documents.models import CvFixRevert
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def test_executing_a_deletion_removes_the_students_cv_fix_reverts(
    agency_a, django_user_model, monkeypatch
) -> None:
    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    with tenant_scope(agency_a.id):
        user = django_user_model.objects.create(username="erase-fixes")
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        remember_revert(student, "soft_skill", "c" * 64)
        remember_revert(student, "verb_opener", "d" * 64)
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        advance_deletion(request, "EXECUTED")
        assert not CvFixRevert.objects.filter(student_id=student.id).exists()
