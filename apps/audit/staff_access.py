"""The record of Elmify staff looking at a student's file (owner decision 2026-10-11).

A PLATFORM_ADMIN may view and download any student's files in their agency without a
SupportGrant; what makes that acceptable is that every access is recorded before a byte
is read. Two records: a StaffFileAccess row in the agency, naming the staff member, the
student and the kind of document, so the agency sees Elmify looked; and a `StaffFileView`
log line, so one query lists them across every agency without a cross-tenant database
read. Neither carries a filename or a name.
"""

import logging
from typing import Literal
from uuid import UUID

from apps.audit.models import StaffFileAccess
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

logger = logging.getLogger(__name__)


def record_staff_access(
    staff: Membership,
    student: Membership,
    *,
    action: Literal["view", "download"],
    kind: str,
    document_id: UUID,
) -> None:
    """Write the StaffFileAccess row, then log the line. Raises whatever the write raises:
    the caller serves nothing unless this returns. `kind` is the row's document_kind."""
    with tenant_scope(staff.tenant_id), tenant_transaction(staff.tenant_id):
        StaffFileAccess.objects.create(
            staff=staff, student=student, action=StaffFileAccess.Action(action.upper()),
            document_kind=kind, document_id=document_id,
        )
    logger.info(
        "StaffFileView action=%s tenant=%s staff=%s student=%s document=%s:%s",
        action, staff.tenant_id, staff.id, student.id, kind, document_id,
    )
