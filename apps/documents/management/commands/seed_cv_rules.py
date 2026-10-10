"""Load the curated CV rule catalog.

    DATABASE_ROLE=runtime_engine uv run python manage.py seed_cv_rules

funding_catalogrule is writable only by runtime_engine (its
runtime_engine_write policy); under any other non-owner role an UPDATE matches
no rows and writes nothing -- silently. Run this as runtime_engine, the same way
derive.py::_write_program requires.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.documents.catalog_seed import seed_cv_rules
from apps.funding.models import CatalogRule


def _any_rules() -> bool:
    return CatalogRule.objects.exists()


class Command(BaseCommand):
    help = "Load the curated CV rule catalog into funding_catalogrule."

    def handle(self, *args: object, **options: object) -> None:
        created, updated, deleted = seed_cv_rules()
        if created == updated == deleted == 0 and not _any_rules():
            raise CommandError(
                "seed wrote nothing and the catalog is empty -- only runtime_engine "
                "can write funding_catalogrule; re-run with DATABASE_ROLE=runtime_engine"
            )
        self.stdout.write(f"created={created} updated={updated} deleted={deleted}")
