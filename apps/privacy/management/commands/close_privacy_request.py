"""Close a privacy request.

Usage: manage.py close_privacy_request --host <tenant host> --id <request uuid>
    --outcome done|declined|resumed [--handled-by-email <staff e-mail>]

`declined` (a reasoned refusal) and `resumed` (the student asked to resume) lift an
objection's or withdrawal's processing stop; `done` keeps it.
"""

from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q
from django.utils import timezone

from apps.privacy.models import PrivacyRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership, TenantDomain

CLOSING = [o for o in PrivacyRequest.Outcome.values if o != PrivacyRequest.Outcome.OPEN]


class Command(BaseCommand):
    help = "Record the outcome of a privacy request."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--host", required=True)
        parser.add_argument("--id", required=True)
        parser.add_argument("--outcome", required=True, choices=CLOSING)
        parser.add_argument("--handled-by-email", dest="handled_by_email")

    def handle(
        self,
        *args: object,
        host: str,
        outcome: str,
        handled_by_email: str | None = None,
        **options: object,
    ) -> None:
        domain = TenantDomain.objects.filter(host=host, verified_at__isnull=False).first()
        if domain is None:
            raise CommandError(f"no verified tenant host {host!r}")
        try:
            pk = UUID(str(options["id"]))
        except ValueError as exc:
            raise CommandError("--id must be a privacy request UUID") from exc
        # Same reason as record_privacy_request: a command has no request scope and
        # no RLS GUC, and without the GUC every tenant row is invisible.
        with tenant_scope(domain.agency_id), tenant_transaction(domain.agency_id):
            row = PrivacyRequest.objects.select_for_update().filter(id=pk).first()
            if row is None:
                raise CommandError("no privacy request with that id in this tenant")
            if row.outcome != PrivacyRequest.Outcome.OPEN:
                raise CommandError(f"request is already closed ({row.outcome})")
            handler = None
            if handled_by_email:
                address = handled_by_email.strip()
                handler = (
                    Membership.objects.filter(
                        Q(user__email__iexact=address) | Q(user__username__iexact=address)
                    )
                    .exclude(role=Membership.Role.STUDENT)
                    .first()
                )
                if handler is None:
                    raise CommandError("no staff member with that e-mail in this tenant")
            row.outcome = outcome
            row.handled_at = timezone.now()
            row.handled_by = handler
            row.save(update_fields=["outcome", "handled_at", "handled_by"])
        self.stdout.write(f"closed {row.kind} as {outcome}")
