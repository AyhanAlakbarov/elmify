"""Create one student account for testing.

    uv run python manage.py create_student --agency <uuid> --host a.example.test --username amina

The password is prompted twice and is never an argument: an argument lands in
shell history and the process list. Creates the User and one STUDENT
Membership and nothing else -- no profile, no pack, no mailbox.

Self-signup with consent is available at /signup/. A student created by this
command will be sent to /privacy/accept/ on first login to accept the current
legal documents, before reaching /student/.
"""

from __future__ import annotations

import getpass
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, Membership, TenantDomain


class Command(BaseCommand):
    help = (
        "Create a test student: one User and one STUDENT Membership. "
        "Self-signup exists at /signup/. Students created by this command are sent to "
        "/privacy/accept/ on first login before reaching /student/."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--agency", required=True, help="The agency's id (UUID).")
        parser.add_argument("--host", required=True, help="A verified domain of that agency.")
        parser.add_argument("--username", required=True)

    def handle(self, *args: object, **options: Any) -> None:
        try:
            agency = Agency.objects.get(id=UUID(str(options["agency"])))
        except (ValueError, Agency.DoesNotExist):
            raise CommandError("No agency with that id.") from None
        host = str(options["host"]).strip().lower()
        if not TenantDomain.objects.filter(
            agency=agency, host=host, verified_at__isnull=False
        ).exists():
            raise CommandError(f"{host} is not a verified domain of {agency.name}.")
        username = str(options["username"]).strip()
        user_model = get_user_model()
        if not username or user_model.objects.filter(username=username).exists():
            raise CommandError("That username is empty or already taken.")
        password = self._password(username)
        with transaction.atomic():
            user = user_model.objects.create_user(username=username, password=password)
            with tenant_scope(agency.id), tenant_transaction(agency.id):
                Membership.objects.create(tenant=agency, user=user, role=Membership.Role.STUDENT)
        self.stdout.write(f"Created {username}. Log in at https://{host}/accounts/login/")

    def _password(self, username: str) -> str:
        first = getpass.getpass("Password: ")
        if first != getpass.getpass("Password (again): "):
            raise CommandError("The passwords do not match.")
        try:
            validate_password(first, user=get_user_model()(username=username))
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from None
        return first
