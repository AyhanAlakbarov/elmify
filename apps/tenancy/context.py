from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID


class TenantContextMissing(RuntimeError):
    pass


class TenantContextConflict(RuntimeError):
    pass


_tenant_id: ContextVar[UUID | None] = ContextVar("tenant_id", default=None)


def current_tenant_id() -> UUID:
    tenant_id = _tenant_id.get()
    if tenant_id is None:
        raise TenantContextMissing("tenant context is required")
    return tenant_id


@contextmanager
def tenant_scope(tenant_id: UUID) -> Iterator[None]:
    """Enter ``tenant_id``'s scope, refusing to *switch* away from an active one.

    Service functions take a tenant_id argument that may come from an untrusted
    request. Re-entering the scope already established from the verified host is
    fine; silently overriding it with a different tenant is the "conflicting
    context" case Global Constraint 1 requires to fail closed. (The Postgres
    ``app.tenant_id`` set by HostTenantContextMiddleware never moved with these
    scopes anyway, so RLS was the only thing catching this.)
    """
    active = _tenant_id.get()
    if active is not None and active != tenant_id:
        raise TenantContextConflict(f"active tenant {active} cannot be switched to {tenant_id}")
    token = _tenant_id.set(tenant_id)
    try:
        yield
    finally:
        _tenant_id.reset(token)
