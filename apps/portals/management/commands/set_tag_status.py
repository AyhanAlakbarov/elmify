"""The only path for the shared tag status (plan 3, design decision 4).

No report moves it: a report measures its own account only (tags.py,
security review M2). Setting or correcting a host's status -- a portal that
changed its form, a disputed report in the logs, one of the owner's own
measurements -- is a person's decision, taken here. Setting UNKNOWN reopens
the host: new registrations get the tagged address again.
"""

import logging

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.portals.models import PortalForm

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Set the tag status of every form on one portal host"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("portal_host")
        parser.add_argument("status", choices=PortalForm.TagStatus.values)

    def handle(self, *_args: object, **options: object) -> None:
        host = str(options["portal_host"]).strip().casefold()
        new_status = str(options["status"])
        prior = sorted(
            set(
                PortalForm.objects.filter(portal_host=host).values_list("tag_status", flat=True)
            )
        )
        updated = PortalForm.objects.filter(portal_host=host).update(tag_status=new_status)
        if not updated:
            raise CommandError(f"no portal form on {host}")
        # No AuditEvent: this table has no tenant to attribute it to. This
        # log line is the only durable trace of a human override.
        logger.warning(
            "TagStatusOverride portal=%s from=%s to=%s", host, prior, new_status
        )
        self.stdout.write(f"{host}: {updated} form(s) set to {options['status']}")
