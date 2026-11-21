"""CvFixRevert behind a role that cannot bypass row-level security.

Shape from tests/documents/test_transcript_reading_rls.py: transaction=True
because the fixture reconnects, and setup fixtures before rls_enforced_orm so
they write as the superuser.
"""

from uuid import uuid4

import pytest

from apps.documents.cv_fixes import remember_revert, reverted_subjects
from apps.documents.models import CvFixRevert
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def revert_a(agency_a, django_user_model):
    user = django_user_model.objects.create(username=f"rv-{uuid4().hex[:8]}")
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        remember_revert(student, "soft_skill", "a" * 64)
        return CvFixRevert.objects.get(student=student)


def test_the_owning_tenant_reads_its_reverts(revert_a, rls_enforced_orm):
    with tenant_scope(revert_a.tenant_id), tenant_transaction(revert_a.tenant_id):
        student = Membership.objects.get(id=revert_a.student_id)
        assert reverted_subjects(student) == frozenset({"a" * 64})


def test_another_tenant_sees_nothing_even_without_the_orm_filter(
    revert_a, agency_b, rls_enforced_orm
):
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert not CvFixRevert._base_manager.filter(id=revert_a.id).exists()
        assert CvFixRevert._base_manager.filter(id=revert_a.id).update(subject="b" * 64) == 0
