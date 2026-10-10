import pytest
from django.db import IntegrityError

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment


@pytest.mark.django_db
def test_unassigned_counselor_cannot_be_looked_up_for_student(
    agency_a, counselor_membership, membership_a
):
    with tenant_scope(agency_a.id):
        with pytest.raises(CounselorAssignment.DoesNotExist):
            CounselorAssignment.objects.get(
                counselor=counselor_membership, student=membership_a, active=True
            )


@pytest.mark.django_db
def test_assignment_is_unique_per_student(agency_a, counselor_membership, membership_a):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        with pytest.raises(IntegrityError):
            CounselorAssignment.objects.create(
                tenant=agency_a, counselor=counselor_membership, student=membership_a
            )
