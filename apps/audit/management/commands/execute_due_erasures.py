"""Erase every deletion request whose thirty-day window has run out.

THE SCHEDULE IS DEFERRED AND THIS IS A DEPLOYMENT GATE. Nothing invokes this
on a schedule yet; until the EventBridge rule exists (model it on
EuropassCanaryRule in infra/template.yaml -- ECS RunTask against
WorkerTaskDefinition, rate(1 day)), erasures happen by running this by hand.
A deployment that never invokes it leaves every student who asked to be erased
locked out indefinitely and never erased, with every screen saying the right
thing. See CLAUDE.md, "Erasure: the schedule is deferred".

Design: docs/superpowers/specs/2026-09-10-erasure-console-design.md
"""

from uuid import UUID

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.audit.deletion import DeletionBlocked, advance_deletion
from apps.audit.models import DeletionRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency


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
        with transaction.atomic():
            # set_local_tenant issues SET LOCAL, so it belongs inside every
            # transaction and not once per agency. Without it this scan is
            # legal SQL that returns zero rows under RLS: the command finds
            # nothing, exits 0, and no erasure ever happens.
            set_local_tenant(tenant_id)
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
                with transaction.atomic():
                    set_local_tenant(tenant_id)
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
                # every other erasure committed.
                self.stderr.write(f"{request_id}: {error}")
