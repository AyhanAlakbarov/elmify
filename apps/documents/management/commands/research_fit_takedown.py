"""Remove a named person from every tenant's research-fit inputs (design D14).

Per-tenant storage means a professor's takedown or correction is no longer
one catalog fix. This is the audited admin route CLAUDE.md sanctions for
data that is not about a student: one tenant scope and one transaction per
agency, exactly as execute_due_erasures does, never a policy bypass. The
row keeps its id (a letter may cite it; verification then fails D9 and the
counselor sees why) and loses the sentence and the provenance.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from apps.documents.audit import record_event
from apps.documents.models import NarrativeInput
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency

_REMOVED_TEXT = "removed at the request of the person named"


class Command(BaseCommand):
    help = "Remove a named person from every tenant's RESEARCH_FIT narrative inputs, audited."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--name", required=True, help="text to match in the provenance entity, case-insensitive"
        )
        parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    def handle(self, *_args: object, **options: object) -> None:
        name = str(options["name"]).strip()
        dry_run = bool(options.get("dry_run"))
        if not name:
            self.stderr.write("--name must not be empty")
            return
        needle = name.casefold()
        for agency in Agency.objects.all():
            with tenant_scope(agency.id), transaction.atomic():
                set_local_tenant(agency.id)
                # A JSON-key __icontains lookup on provenance__entity is not
                # reliably supported across Django's key-transform machinery,
                # so the entity match is done in Python on the small,
                # already-tenant-scoped RESEARCH_FIT row set instead.
                rows = [
                    row
                    for row in NarrativeInput.objects.filter(kind=NarrativeInput.Kind.RESEARCH_FIT)
                    if row.provenance and needle in str(row.provenance.get("entity", "")).casefold()
                ]
                for row in rows:
                    if dry_run:
                        continue
                    row.provenance = None
                    row.text = _REMOVED_TEXT
                    row.save(update_fields=["provenance", "text"])
                    record_event(
                        actor=None, event="document.research_fit.takedown", object_id=row.id
                    )
                suffix = " (dry run)" if dry_run else ""
                self.stdout.write(f"{agency.id}: {len(rows)} rows{suffix}")
