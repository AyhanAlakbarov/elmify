"""Raise overdue-expectation alerts and escalate unacknowledged urgent ones.

Invoked hourly by WatchApplicationsRule (infra/template.yaml).
Design: docs/superpowers/specs/2026-09-25-application-watch-design.md §4, §5.
"""

from django.core.management.base import BaseCommand

from apps.tenancy.models import Agency
from apps.watch.escalation import escalate_for_tenant
from apps.watch.heartbeat import record_run, report_silent
from apps.watch.mailbox_health import alert_stale_mailboxes_for_tenant
from apps.watch.watchdog import watch_applications_for_tenant


class Command(BaseCommand):
    help = "Alert on overdue expectations and escalate unacknowledged urgent alerts"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency carries no RLS policy, so listing it as the runtime role works.
        # Each sweep sets its own tenant_scope; none is held across the loop,
        # because tenant_scope refuses to switch tenants.
        for agency in Agency.objects.all():
            watch_applications_for_tenant(agency.id)
            escalate_for_tenant(agency.id)
            alert_stale_mailboxes_for_tenant(agency.id)
        # Recorded only after the loop: a run that died halfway did not finish.
        record_run("watch_applications")
        report_silent()
