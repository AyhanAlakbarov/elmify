"""Give an existing account Elmify staff access to the staff desk (/staff/).

    manage.py make_staff --username ayhan --agency-host localhost

Creates the account's PLATFORM_ADMIN membership in that agency. The person signs in
as usual, is sent to the two-step code setup on first sign-in, and then sees the staff
desk. An account that already has another active membership is refused: one login, one
role.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership, TenantDomain


class Command(BaseCommand):
    help = "Make an existing account an Elmify staff member (PLATFORM_ADMIN) of an agency."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", required=True)
        parser.add_argument(
            "--agency-host", required=True, help="the agency's domain, e.g. localhost"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user = get_user_model().objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError(f"no account named {options['username']!r}")
        domain = (
            TenantDomain.objects.select_related("agency")
            .filter(host=options["agency_host"].lower())
            .first()
        )
        if domain is None:
            raise CommandError(f"no agency domain {options['agency_host']!r}")
        agency = domain.agency
        with tenant_scope(agency.id), tenant_transaction(agency.id):
            current = Membership.objects.filter(user=user, active=True).first()
            if current is not None and current.role == Membership.Role.PLATFORM_ADMIN:
                self.stdout.write("Already staff.")
                return
            if current is not None:
                raise CommandError(
                    f"{user.get_username()} is already an active {current.role}; "
                    "use a separate account for staff access"
                )
            Membership.objects.update_or_create(
                tenant=agency,
                user=user,
                defaults={"role": Membership.Role.PLATFORM_ADMIN, "active": True},
            )
        self.stdout.write(f"{user.get_username()} is now staff of {agency.name}.")
