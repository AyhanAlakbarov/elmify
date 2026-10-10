"""The cross-tenant guard, run under a role that RLS actually applies to.

The rest of the audit suite runs as the test superuser, which is BYPASSRLS, so
``redact_identity``'s guard sees every agency's memberships there and passes for
the wrong reason. In production the runtime role is NOBYPASSRLS and
``tenancy_membership`` is FORCE ROW LEVEL SECURITY on ``app.tenant_id``, so the
same query sees only the erasing agency, finds nothing, and scrubs the login of
someone still enrolled elsewhere.

Design: docs/superpowers/specs/2026-09-09-identity-erasure-design.md
"""

import pytest

from apps.audit.identity import IdentityRetention, redact_identity
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def student_at_two_agencies(agency_a, agency_b, user_a):
    """One login, an erased membership at A and a live one at B.

    Committed as the superuser before ``rls_enforced_orm`` swaps the role, the
    same shape the portal RLS tests use. The membership at A is already
    inactive because ``advance_deletion`` deactivates it before calling the
    guard.
    """
    with tenant_scope(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=user_a, role=Membership.Role.STUDENT, active=False
        )
    with tenant_scope(agency_b.id):
        Membership.objects.create(
            tenant=agency_b, user=user_a, role=Membership.Role.STUDENT, active=True
        )
    return user_a


def test_the_guard_sees_a_live_membership_at_another_agency(
    agency_a, student_at_two_agencies, rls_enforced_orm
):
    """RED before the fix, and unobservable anywhere else in the suite.

    ``tenant_transaction`` is what production does: it sets ``app.tenant_id`` to
    the *erasing* agency on the same connection the guard then runs on. A
    tenant-filtered read of ``tenancy_membership`` therefore cannot see agency
    B's row, the guard passes, and a login agency B is still using is
    irreversibly scrubbed and recorded as a complete erasure.
    """
    with tenant_transaction(agency_a.id):
        retention = redact_identity(
            user_id=student_at_two_agencies.pk, membership_role=Membership.Role.STUDENT
        )

    assert retention is IdentityRetention.STILL_ENROLLED, (
        "scrubbed a login still in use at another agency"
    )
    student_at_two_agencies.refresh_from_db()
    assert student_at_two_agencies.username == "student-a"
    assert student_at_two_agencies.is_active is True


def test_the_guard_still_scrubs_when_no_membership_survives(
    agency_a, user_a, rls_enforced_orm
):
    """The other half: reading across tenants must not stop erasure working."""
    # Both scopes: tenant_scope feeds the tenant-scoped manager, and
    # tenant_transaction sets the GUC the policy's WITH CHECK reads. The ORM is
    # already behind the NOBYPASSRLS role by this point, so the insert needs
    # both.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        Membership.objects.create(
            tenant=agency_a, user=user_a, role=Membership.Role.STUDENT, active=False
        )
        retention = redact_identity(user_id=user_a.pk, membership_role=Membership.Role.STUDENT)

    assert retention is None
    user_a.refresh_from_db()
    assert user_a.username.startswith("deleted-")
    assert user_a.email == ""
    assert user_a.is_active is False
