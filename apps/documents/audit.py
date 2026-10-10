from __future__ import annotations

from uuid import UUID

from apps.funding.models import AuditEvent
from apps.tenancy.context import TenantContextMissing
from apps.tenancy.models import Membership


def record_event(*, actor: Membership | None, event: str, object_id: UUID) -> AuditEvent | None:
    """Append one audit event.

    Every document write path calls this rather than AuditEvent directly, so
    "events carry identifiers and decisions, never document text" has exactly
    one place to be audited. The signature has no room for a content argument
    on purpose.

    Returns None when there is no tenant context to write into -- the only
    caller in that position is catalog format resolution, which has no tenant
    and therefore no counselor queue to flag.
    """
    try:
        return AuditEvent.objects.create(actor=actor, event=event, object_id=object_id)
    except TenantContextMissing:
        return None
