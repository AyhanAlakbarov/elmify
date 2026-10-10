"""Mark the one agency that is the platform (resolution queue, spec 11).

The only writer of `research.PlatformAgency`. Run it once per environment, as
the migration role (`DATABASE_ROLE=migration`): both runtime roles hold SELECT
on the table and nothing else (research/0013), so under either of them the
write is refused with `permission denied` -- deliberately, because moving the
platform moves who can read the resolution queue.

Refuses a second platform rather than moving it. Moving it is a hand edit by the
database owner, taken knowingly.
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import ProgrammingError, transaction

from apps.research.models import PlatformAgency
from apps.tenancy.models import Agency


class Command(BaseCommand):
    help = "Mark the one agency that is the platform (resolution queue, spec 11)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("agency_id")

    def handle(self, *_args: object, **options: object) -> None:
        raw = str(options["agency_id"])
        try:
            agency_id = uuid.UUID(raw)
        except ValueError as error:
            raise CommandError(f"no agency {raw}: not a UUID") from error
        target = Agency.objects.filter(id=agency_id).first()
        if target is None:
            raise CommandError(f"no agency {agency_id}")
        try:
            with transaction.atomic():
                current = PlatformAgency.objects.select_for_update().first()
                if current is not None and current.agency_id != target.id:
                    raise CommandError(
                        f"{current.agency_id} is already the platform; unset it by hand "
                        "first -- moving the platform moves who can read the resolution queue"
                    )
                if current is None:
                    PlatformAgency.objects.create(agency=target)
        except ProgrammingError as error:
            raise CommandError(
                "this role cannot write research_platformagency; run with "
                f"DATABASE_ROLE=migration ({error})"
            ) from error
        self.stdout.write(f"{target.id} is the platform agency")
