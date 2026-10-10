"""Mark one student's academic-year cycle paid -- the stand-in for a checkout (R13).

Owner decision 2026-10-05: a minimal cycle record now, the payment provider later. Whoever runs
this is attesting that the fee was received; the AuditEvent is the record that they did.
"""

import re
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.concierge.models import StudentCycle
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Membership


class Command(BaseCommand):
    help = "Mark a student's academic-year cycle paid (until a checkout exists)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", type=UUID, required=True)
        parser.add_argument("--student", type=UUID, required=True)
        parser.add_argument("--academic-year", required=True)

    def handle(self, *args: object, **options: object) -> None:
        # call_command(**kwargs) skips argparse's type=, so coerce here too.
        tenant = UUID(str(options["tenant"]))
        student = UUID(str(options["student"]))
        year = str(options["academic_year"])
        if not re.fullmatch(r"\d{4}-\d{4}", year) or int(year[5:]) != int(year[:4]) + 1:
            raise CommandError("the academic year is two consecutive years, e.g. 2026-2027")
        with tenant_scope(tenant), transaction.atomic():
            set_local_tenant(tenant)
            if not Membership.objects.filter(id=student, role=Membership.Role.STUDENT).exists():
                raise CommandError("no student with that id in that tenant")
            cycle, _ = StudentCycle.objects.select_for_update().get_or_create(
                student_id=student, academic_year=year
            )
            if cycle.paid_at is not None:
                self.stdout.write(f"already paid on {cycle.paid_at:%Y-%m-%d}")
                return
            cycle.paid_at = timezone.now()
            cycle.save(update_fields=["paid_at"])
            AuditEvent.objects.create(
                actor=None,
                actor_kind=AuditEvent.ActorKind.SYSTEM,
                event="cycle.marked_paid",
                object_id=cycle.id,
            )
        self.stdout.write(f"cycle {year} paid")
