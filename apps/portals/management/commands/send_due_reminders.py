"""Send every deadline reminder that has come due, in every tenant.

Invoked hourly by ReminderLadderRule (infra/template.yaml). Hourly and not
daily: the 6-hour rung cannot be hit by a daily job, and it is the rung whose
whole purpose is being the last one.

Design: docs/superpowers/specs/2026-09-19-reminder-ladder-design.md
"""

from django.core.management.base import BaseCommand

from apps.portals.reminders import send_due_reminders_for_tenant
from apps.tenancy.models import Agency
from apps.watch.heartbeat import record_run, report_silent


class Command(BaseCommand):
    help = "Send deadline reminders whose rung has come due"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency is not tenant-scoped and carries no RLS policy, so listing it
        # from the runtime role works. send_due_reminders_for_tenant sets its
        # own tenant_scope as its first line (Task 6), so no scope is held
        # here across the loop -- tenant_scope refuses to SWITCH tenants
        # (TenantContextConflict), and a scope held across agencies here would
        # be a redundant, pointless double-wrap even though same-tenant
        # re-entry is harmless by tenant_scope's own design.
        for agency in Agency.objects.all():
            send_due_reminders_for_tenant(agency.id)
        record_run("send_due_reminders")
        report_silent()
