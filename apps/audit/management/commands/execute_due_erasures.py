"""Erase every deletion request whose thirty-day window has run out.

Invoked daily by `ExecuteDueErasuresRule` in `infra/template.yaml` (ECS
`RunTask` against `WorkerTaskDefinition`, `rate(1 day)`, `State: ENABLED`),
which runs under `DATABASE_ROLE=runtime_engine` and `WorkerTaskRole`.

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

import logging
from uuid import UUID

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.deletion import DeletionBlocked, advance_deletion
from apps.audit.models import DeletionRequest
from apps.portals.credentials import aws_code
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Execute deletion requests whose reversal window has expired"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency is not tenant-scoped and carries no RLS policy, so listing it
        # from the runtime role works. One scope per agency: tenant_scope
        # refuses to SWITCH tenants (TenantContextConflict), so an outer scope
        # held across the loop would raise on the second agency.
        for agency in Agency.objects.all():
            with tenant_scope(agency.id):
                self._erase_due_for(agency.id)

    def _erase_due_for(self, tenant_id: UUID) -> None:
        with tenant_transaction(tenant_id):
            # tenant_transaction issues SET LOCAL inside the transaction.
            # Without it this scan is legal SQL that returns zero rows under
            # RLS: the command finds nothing, exits 0, and no erasure ever happens.
            due_ids = list(
                DeletionRequest.objects.filter(
                    state="APPROVED", execute_after__lte=timezone.now()
                ).values_list("id", flat=True)
            )

        # One transaction per erasure, never one per agency.
        # delete_student_documents purges S3 outside the database, so an error
        # on the fourth student would roll back the first three students'
        # EXECUTED rows while their objects are already gone. Those three then
        # re-run tomorrow against documents that no longer exist, and in
        # between the database says they were never erased.
        for request_id in due_ids:
            try:
                with tenant_transaction(tenant_id):
                    # select_for_update plus the re-check is what honours a
                    # restore that wins the race: advance_deletion reads state
                    # off the in-memory object, so a request scanned as
                    # APPROVED and cancelled a second later is otherwise erased
                    # anyway -- irreversibly, after the student withdrew it.
                    # The restore view's UPDATE blocks on this lock.
                    request = DeletionRequest.objects.select_for_update().get(id=request_id)
                    if request.state != "APPROVED":
                        continue
                    advance_deletion(request, "EXECUTED")
            except (DeletionBlocked, ClientError) as error:
                # Per request, so one stuck row does not strand the batch. Each
                # request owns its transaction, so a caught failure leaves
                # every other erasure committed. Never an AWS message: it names
                # the SecretId, which names the student. DeletionBlocked's are
                # our own fixed reasons and tell the operator which case it is.
                if isinstance(error, DeletionBlocked):
                    reason = str(error)
                else:
                    reason = aws_code(error)
                logger.warning(
                    "ErasureExecutionFailed request=%s party=%s reason=%s",
                    request_id,
                    type(error).__name__,
                    reason,
                )
                self.stderr.write(f"{request_id}: {reason}")
