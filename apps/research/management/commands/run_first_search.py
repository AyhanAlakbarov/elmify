"""Queue a student's FIRST search by hand (operator), whatever TAP_AUTOMATIC says."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.research.models import SearchTap
from apps.research.tap import request_tap
from apps.research.wallet import TapRefused
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Agency, Membership


class Command(BaseCommand):
    help = "Queue the first search for one student (membership id)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--student", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            student_id = UUID(options["student"])
        except ValueError as bad:
            raise CommandError("--student must be a membership id (UUID)") from bad
        student = None
        # A membership id says nothing of its tenant and RLS hides it from any
        # other, so look under each agency in turn.
        for agency_id in Agency.objects.values_list("id", flat=True):
            with tenant_transaction(agency_id):
                student = Membership.objects.filter(
                    id=student_id, role=Membership.Role.STUDENT, active=True
                ).first()
            if student is not None:
                break
        if student is None:
            raise CommandError("no active student with that membership id")
        try:
            tap = request_tap(student, kind=SearchTap.Kind.FIRST)
        except TapRefused as refused:
            raise CommandError(str(refused)) from refused
        self.stdout.write(f"queued first search {tap.id}")
