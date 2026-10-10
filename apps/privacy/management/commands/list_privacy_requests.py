"""List open privacy requests across every tenant, soonest deadline first within each.

Usage: manage.py list_privacy_requests
"""

from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.privacy.models import PrivacyRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, TenantDomain


class Command(BaseCommand):
    help = "Print open privacy requests per tenant, marking overdue ones."

    def handle(self, *args: object, **options: Any) -> None:
        now = timezone.now()
        hosts = dict(
            TenantDomain.objects.filter(verified_at__isnull=False)
            .order_by("-host")  # the first host alphabetically wins the dict
            .values_list("agency_id", "host")
        )
        # Every agency, not only those with a verified host: a request in a tenant whose
        # domain is unverified or gone still has a legal deadline.
        for agency in Agency.objects.order_by("name"):
            label = hosts.get(agency.id) or f"{agency.name} (no verified host)"
            with tenant_scope(agency.id), tenant_transaction(agency.id):
                rows = list(
                    PrivacyRequest.objects.filter(outcome="")
                    .select_related("student__user")
                    .order_by("due_at")
                )
            for row in rows:
                flag = "OVERDUE" if row.due_at < now else "open"
                self.stdout.write(
                    f"{label}  {row.id}  {row.student.user.username}  {row.kind}  "
                    f"{row.channel}  due {row.due_at:%Y-%m-%d %H:%M %Z}  {flag}"
                )
