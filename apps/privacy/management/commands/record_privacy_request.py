"""Log a privacy request.

Usage: manage.py record_privacy_request --host <tenant host> --email <student>
    --kind objection --channel email [--received 2026-10-03T10:00:00+04:00]
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.privacy import requests
from apps.privacy.models import PrivacyRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership, TenantDomain


class Command(BaseCommand):
    help = "Record a privacy request received by e-mail, paper with ID or e-signature."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--host", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--kind", required=True, choices=PrivacyRequest.Kind.values)
        parser.add_argument("--channel", required=True, choices=PrivacyRequest.Channel.values)
        parser.add_argument("--received")

    def handle(
        self,
        *args: object,
        host: str,
        email: str,
        kind: str,
        channel: str,
        received: str | None = None,
        **options: object,
    ) -> None:
        domain = TenantDomain.objects.filter(host=host, verified_at__isnull=False).first()
        if domain is None:
            raise CommandError(f"no verified tenant host {host!r}")
        try:
            moment = parse_datetime(received) if received else timezone.now()
        except ValueError:
            moment = None
        if moment is None or timezone.is_naive(moment):
            raise CommandError("--received must be an ISO 8601 datetime with a timezone")
        # A command is not a request path: nothing has set the manager's scope or the
        # RLS GUC, and without the GUC every tenant row is invisible (CLAUDE.md, RLS).
        with tenant_scope(domain.agency_id), tenant_transaction(domain.agency_id):
            student = Membership.objects.filter(
                user__username__iexact=email.strip(), role=Membership.Role.STUDENT
            ).first()
            if student is None:
                raise CommandError("no student with that e-mail in this tenant")
            row = requests.record(student, kind=kind, channel=channel, received_at=moment)
        self.stdout.write(f"recorded {kind}; reply due {row.due_at:%Y-%m-%d %H:%M %Z}")
