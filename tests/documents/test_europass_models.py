import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.documents.models import EuropassCircuit, EuropassRenderCache
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_the_cache_is_unique_per_tenant_and_hash(agency_a):
    with tenant_scope(agency_a.id):
        EuropassRenderCache.objects.create(payload_hash="a" * 64, object_key="k1")
        with pytest.raises(IntegrityError):
            EuropassRenderCache.objects.create(payload_hash="a" * 64, object_key="k2")


def test_the_same_hash_in_two_tenants_is_allowed(agency_a, agency_b):
    """The key is scoped per tenant: a shared artefact across tenants would
    be a cross-tenant data leak, so the uniqueness must not be global."""
    with tenant_scope(agency_a.id):
        EuropassRenderCache.objects.create(payload_hash="b" * 64, object_key="k1")
    with tenant_scope(agency_b.id):
        EuropassRenderCache.objects.create(payload_hash="b" * 64, object_key="k2")
    with tenant_scope(agency_b.id):
        assert EuropassRenderCache.objects.filter(payload_hash="b" * 64).count() == 1


def test_the_circuit_is_a_singleton_readable_without_a_tenant():
    """Global on purpose: one NAT IP means a throttle applies to everyone.

    Asserting only `load().pk == 1` is a tautology -- get_or_create(pk=1) is
    handed that pk itself, so it is satisfied regardless of how many rows
    actually exist. The row count is the part that proves singleton-ness.
    """
    circuit = EuropassCircuit.load()
    assert circuit.pk == 1
    assert circuit.paused_until is None
    assert EuropassCircuit.load().pk == 1
    assert EuropassCircuit.objects.count() == 1


def test_the_circuit_reports_whether_it_is_open():
    circuit = EuropassCircuit.load()
    assert circuit.is_open() is False
    circuit.paused_until = timezone.now() + timezone.timedelta(seconds=60)
    assert circuit.is_open() is True
    circuit.paused_until = timezone.now() - timezone.timedelta(seconds=60)
    assert circuit.is_open() is False


def test_the_circuit_model_carries_no_tenant_or_student_columns():
    """Pins the design decision. A tenant column here would invite someone to
    scope it per tenant, which would let other tenants keep calling an
    endpoint that asked us all to stop.

    Exact field-set equality, not membership: `"tenant" not in names` would
    still pass if someone added a differently-named tenant column such as
    `agency` or `student_email`. Equality fails on ANY new column until
    someone looks at it and updates this list on purpose.
    """
    names = {field.name for field in EuropassCircuit._meta.get_fields()}
    assert names == {"id", "paused_until", "reason", "consecutive_failures"}
