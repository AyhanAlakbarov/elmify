"""Apply the platform operators' decided answers to the shared catalog.

The console records a decision; this command is where it lands, because only
`runtime_engine` (or the table owner) may write the catalogue -- the console
runs as `runtime_web`, which holds no grant on it. So the first query checks
the role, and a wrong one is refused before anything runs rather than
producing a run that writes nothing.

Order: expire the never-opened, apply the decided, then print one line per
item and the per-corridor share -- the gate reads those lines.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.resolution.apply import apply_decided, expire_unopened, known_organisations
from apps.research.resolution.platform import platform_agency
from apps.research.resolution.priority import corridor_lines, corridor_share
from apps.tenancy.models import Agency

#: CASE, not AND: pg_has_role raises on a role that does not exist, and SQL
#: does not promise to short-circuit a boolean expression.
_CAN_WRITE_CATALOGUE = """
SELECT CASE
    WHEN current_user = (SELECT tableowner FROM pg_tables
                          WHERE schemaname = 'public' AND tablename = 'research_organisation')
        THEN true
    WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'runtime_engine')
        THEN pg_has_role(current_user, 'runtime_engine', 'USAGE')
    ELSE false
END
"""


def can_write_catalogue() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(_CAN_WRITE_CATALOGUE)
        row = cursor.fetchone()
    return bool(row and row[0])


class Command(BaseCommand):
    help = (
        "Write the resolution queue's decided answers back to the catalog, delete "
        "each applied item, and expire items nobody opened." + CATALOG_ROLE_NOTE
    )

    def handle(self, *_args: object, **_options: object) -> None:
        if not can_write_catalogue():
            raise CommandError(
                "apply_resolutions writes the shared catalogue and this connection's role "
                "cannot." + CATALOG_ROLE_NOTE
            )
        try:
            platform_agency()
        except Agency.DoesNotExist as error:
            raise CommandError(str(error)) from error
        now = timezone.now()
        expired = expire_unopened(now=now)
        report = apply_decided(now=now)
        self.stdout.write(
            f"applied={report.applied} reopened={report.reopened} expired={expired}"
        )
        for line in report.lines:
            self.stdout.write(line)
        for line in corridor_lines(corridor_share(known=known_organisations)):
            self.stdout.write(line)
