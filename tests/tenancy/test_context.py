from uuid import uuid4

import pytest

from apps.tenancy.context import (
    TenantContextConflict,
    TenantContextMissing,
    current_tenant_id,
    tenant_scope,
)


def test_missing_tenant_context_fails_closed() -> None:
    with pytest.raises(TenantContextMissing, match="tenant context is required"):
        current_tenant_id()


def test_sequential_tenant_contexts_do_not_leak() -> None:
    first = uuid4()
    second = uuid4()

    with tenant_scope(first):
        assert current_tenant_id() == first
    with tenant_scope(second):
        assert current_tenant_id() == second

    with pytest.raises(TenantContextMissing):
        current_tenant_id()


def test_nested_scope_cannot_switch_tenants() -> None:
    """A service given an untrusted tenant_id must not override the verified one."""
    verified = uuid4()
    attacker_supplied = uuid4()

    with tenant_scope(verified):
        with pytest.raises(TenantContextConflict):
            with tenant_scope(attacker_supplied):
                pass
        assert current_tenant_id() == verified


def test_nested_scope_for_the_same_tenant_is_allowed() -> None:
    tenant = uuid4()
    with tenant_scope(tenant), tenant_scope(tenant):
        assert current_tenant_id() == tenant
