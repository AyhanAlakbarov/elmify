"""Read every connected mailbox once, one agency at a time: the backstop.

Every six hours (SyncMailboxesRule in infra/template.yaml). Graph push
(apps/mailbox/push.py) is what reads a Microsoft mailbox within seconds; this
sweep is what catches every notification push dropped -- which both vendors
say happens -- and every connection push does not cover (Gmail, an agency
with no verified host, MAILBOX_PUSH_ENABLED off). It also keeps each Microsoft
connection's subscription alive before syncing it: created when absent,
renewed with under two days left, recreated when Graph no longer has it.

A deployment that never invokes this leaves every connected student believing
the platform is watching their inbox while nothing is, and every screen says
the right thing -- the same failure shape as the erasure command next door.
record_run feeds the heartbeat, so a schedule that stops is an alarm.

Design: docs/superpowers/specs/2026-09-15-student-owned-mailbox-design.md and
the application-watch spec's §3a (push).
"""

from __future__ import annotations

from uuid import UUID

from django.core.management.base import BaseCommand

from apps.mailbox.models import MailboxConnection
from apps.mailbox.providers import ProviderError
from apps.mailbox.push import ensure_subscription
from apps.mailbox.sync import SyncRefused, sync_connection
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency
from apps.watch.heartbeat import record_run


class Command(BaseCommand):
    help = "Read new mail on every active mailbox connection"

    def handle(self, *_args: object, **_options: object) -> None:
        # Agency is not tenant-scoped and carries no policy, so listing it from
        # the runtime role works. One scope per agency: tenant_scope refuses to
        # SWITCH tenants, so an outer scope held across the loop would raise on
        # the second agency.
        for agency in Agency.objects.all():
            with tenant_scope(agency.id):
                self._sync_agency(agency.id)
        record_run("sync_mailboxes")

    def _sync_agency(self, tenant_id: UUID) -> None:
        with tenant_transaction(tenant_id):
            # set_local_tenant issues SET LOCAL, so the read belongs inside a
            # transaction. Without it this is legal SQL returning zero rows
            # under RLS: the sweep finds nothing and exits 0.
            connection_ids = list(
                MailboxConnection.objects.filter(
                    status=MailboxConnection.Status.ACTIVE
                ).values_list("id", flat=True)
            )

        for connection_id in connection_ids:
            try:
                with tenant_transaction(tenant_id):
                    connection = MailboxConnection.objects.select_related("membership").get(
                        id=connection_id
                    )
                # Raises for neither Graph nor a grant; a connection it cannot
                # subscribe stays on this sweep, all any connection had before.
                ensure_subscription(connection)
                sync_connection(connection)
            except (SyncRefused, ProviderError) as error:
                # Per connection, so one student's expired grant does not
                # strand every other student in the agency. The message names
                # the connection, never the student or the mailbox.
                self.stderr.write(f"{connection_id}: {error}")
