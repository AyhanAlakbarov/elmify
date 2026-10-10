"""Fixtures for the platform-only resolution queue.

The platform is an ordinary `tenancy.Agency` plus the one
`research.PlatformAgency` row that names it -- the marker lives on the research
side (no tenancy migration), and `manage.py set_platform_agency` is its only
production writer. Tests create the row directly, as the superuser, because
what they exercise is the policy that READS it.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.research.models import PlatformAgency
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Agency, Membership, TenantDomain


@pytest.fixture
def platform(db) -> Agency:
    agency = Agency.objects.create(name="Platform")
    PlatformAgency.objects.create(agency=agency)
    return agency


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch) -> None:
    """`validate_public_url` resolves DNS, and no test here may reach the
    network. Replaced where kinds.py imported it; test_kinds.py restores the
    real function once to prove a private address is refused."""
    from apps.research.resolution import kinds

    monkeypatch.setattr(kinds, "validate_public_url", lambda url: None)


def _platform_admin(platform: Agency, username: str) -> Membership:
    user = get_user_model().objects.create_user(username=username)
    with tenant_scope(platform.id):
        return Membership.objects.create(
            tenant=platform, user=user, role=Membership.Role.PLATFORM_ADMIN
        )


@pytest.fixture
def operator(platform) -> Membership:
    """An active PLATFORM_ADMIN of the platform agency: the one kind of person
    who may see or answer the queue."""
    return _platform_admin(platform, "operator-one")


@pytest.fixture
def operator_user(operator):
    return operator.user


@pytest.fixture
def second_operator(platform) -> Membership:
    return _platform_admin(platform, "operator-two")


@pytest.fixture
def platform_domain(platform) -> TenantDomain:
    return TenantDomain.objects.create(
        agency=platform, host="platform.example.test", verified_at=timezone.now()
    )
