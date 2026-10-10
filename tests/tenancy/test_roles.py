import pytest

from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership, SupportGrant
from apps.tenancy.services import require_active_support_grant


@pytest.mark.django_db
def test_platform_admin_role_exists(agency_a, user_a):
    with tenant_scope(agency_a.id):
        admin = Membership.objects.create(
            tenant=agency_a, user=user_a, role=Membership.Role.PLATFORM_ADMIN
        )
    assert admin.role == "PLATFORM_ADMIN"


@pytest.mark.django_db
def test_support_grant_required_before_admin_data_access(agency_a, user_a):
    with pytest.raises(SupportGrant.DoesNotExist):
        require_active_support_grant(user_a, agency_a.id)


@pytest.mark.django_db
def test_expired_support_grant_denied(agency_a, user_a):
    from datetime import timedelta

    from django.utils import timezone

    with tenant_scope(agency_a.id):
        SupportGrant.objects.create(
            tenant=agency_a,
            administrator=user_a,
            reason="billing investigation",
            starts_at=timezone.now() - timedelta(days=2),
            ends_at=timezone.now() - timedelta(days=1),
        )
    with pytest.raises(SupportGrant.DoesNotExist):
        require_active_support_grant(user_a, agency_a.id)


@pytest.mark.django_db
def test_active_support_grant_returned(agency_a, user_a):
    from datetime import timedelta

    from django.utils import timezone

    with tenant_scope(agency_a.id):
        grant = SupportGrant.objects.create(
            tenant=agency_a,
            administrator=user_a,
            reason="billing investigation",
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
        )
    found = require_active_support_grant(user_a, agency_a.id)
    assert found.id == grant.id


@pytest.mark.django_db
def test_revoked_support_grant_denied(agency_a, user_a):
    from datetime import timedelta

    from django.utils import timezone

    with tenant_scope(agency_a.id):
        SupportGrant.objects.create(
            tenant=agency_a,
            administrator=user_a,
            reason="billing investigation",
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=1),
            revoked_at=timezone.now(),
        )
    with pytest.raises(SupportGrant.DoesNotExist):
        require_active_support_grant(user_a, agency_a.id)
