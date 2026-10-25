"""Fetch today's exchange-rate table and print it: the live check for research.rates.

    uv run python manage.py check_rates

Read-only toward the database. Exits non-zero when neither CBAR nor the ECB
answered with a fresh table -- which is exactly when packs come out empty.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.research.rates import load_rates


class Command(BaseCommand):
    help = "Fetch and print today's exchange-rate table (CBAR, else ECB)"

    def handle(self, *_args: object, **_options: object) -> None:
        table = load_rates()
        if table is None:
            raise CommandError("no fresh rate table from CBAR or the ECB; packs will be empty")
        self.stdout.write(
            f"{table.source}, base {table.base}, dated {table.retrieved_on}: "
            f"{len(table.rates)} currencies"
        )
        for code in ("EUR", "USD", "GBP", "AZN", "KZT", "UZS", "GEL", "TRY", "CNY", "KRW"):
            if code in table.rates:
                self.stdout.write(f"  {code}  {table.rates[code]}")
