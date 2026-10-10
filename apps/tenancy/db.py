from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import connection, transaction
from django.db.transaction import TransactionManagementError


def set_local_tenant(tenant_id: UUID) -> None:
    if not connection.in_atomic_block:
        raise TransactionManagementError("tenant database context requires an atomic block")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])


@contextmanager
def tenant_transaction(tenant_id: UUID) -> Iterator[None]:
    """One short transaction with ``app.tenant_id`` set inside it.

    The GUC is transaction-local, so scope and transaction are the same object
    and there is no way to hold one without the other. Callers that must not
    hold a transaction open -- anything driving a browser or an LLM -- wrap each
    database interaction in this instead of wrapping the whole operation.

    Nesting is a savepoint and re-runs set_config harmlessly, so a caller does
    not have to know whether it is already inside one.
    """
    with transaction.atomic():
        set_local_tenant(tenant_id)
        yield
