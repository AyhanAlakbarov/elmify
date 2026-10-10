"""Publish every `apps/privacy/legal/<kind>.<lang>.md` whose text changed.

Run as the migration role (DATABASE_ROLE=migration): the runtime roles may only
read privacy_legaldocument, and an owner-only trigger refuses anyone else.
`--minor` marks the new versions as non-material, so students are not asked to
re-accept a typo fix.
"""

from django.core.management.base import BaseCommand, CommandParser

from apps.privacy import documents


class Command(BaseCommand):
    help = "Publish changed legal document texts as new versions."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--minor", action="store_true", help="the change is not material")

    def handle(self, *args: object, minor: bool = False, **options: object) -> None:
        for kind, language, path in documents.shipped_files():
            row, created = documents.publish(
                kind, language, path.read_text(encoding="utf-8"), material=not minor
            )
            state = "published" if created else "unchanged"
            self.stdout.write(f"{kind}.{language}: v{row.version} {state}")
