"""Fixtures the bench's test modules share (platform, operator, a portal form,
the faked object store). Here rather than imported from a test module, which
trips ruff F811 at every test that takes them."""

import pytest
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.tenancy.context import tenant_scope
from tests.portals.test_ext_api import _pair


@pytest.fixture
def platform(db):
    from apps.research.models import PlatformAgency
    from apps.tenancy.models import Agency

    agency = Agency.objects.create(name="Platform")
    PlatformAgency.objects.create(agency=agency)
    return agency


@pytest.fixture
def platform_domain(platform):
    from apps.tenancy.models import TenantDomain

    return TenantDomain.objects.create(
        agency=platform, host="platform.example.test", verified_at=timezone.now()
    )


@pytest.fixture
def operator(platform, django_user_model):
    from apps.tenancy.models import Membership

    user = django_user_model.objects.create_user(
        username="operator", email="owner@example.org",
        first_name="Orkhan", last_name="Abdullayev",
    )
    TOTPDevice.objects.create(user=user, name="default", confirmed=True)
    with tenant_scope(platform.id):
        return Membership.objects.create(
            tenant=platform, user=user, role=Membership.Role.PLATFORM_ADMIN
        )


@pytest.fixture
def operator_token(client, platform, platform_domain, operator) -> str:
    return _pair(client, platform, operator, platform_domain)


@pytest.fixture
def portal_form():
    from apps.portals.models import PortalForm

    return PortalForm.objects.create(
        portal_host="apply.example.edu", form_key="bench-1",
        form_url="https://apply.example.edu/apply",
    )


@pytest.fixture
def bench_store(monkeypatch, fake_store):
    from apps.portals import bench

    monkeypatch.setattr(bench, "_store", lambda: fake_store)
    return fake_store


@pytest.fixture
def user_a_password(user_a):
    user_a.set_password("correct horse battery staple")
    user_a.save(update_fields=["password"])
    return "correct horse battery staple"
