"""The ROR gate (spec 6.2): measured before ROR writes anything.

Reads the 58 yield hosts and docs/research/ror-gate-names.csv, prints every
count and share, then `ROR GATE: PASS` or `ROR GATE: FAIL` -- and exits
non-zero on FAIL. Never writes to the database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.research import ror
from apps.research.closed_lists import DATA_DIR
from apps.research.egress import SourceBlocked, fetch_json_api

HOSTS = DATA_DIR / "2026-09-18-yield-hosts.txt"
NAMES = DATA_DIR / "ror-gate-names.csv"


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


class Command(BaseCommand):
    help = "Measure ROR's website agreement on the yield hosts; name matching for item 8."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--hosts", default=str(HOSTS))
        parser.add_argument("--names", default=str(NAMES))

    def handle(self, *args: Any, **options: Any) -> None:
        hosts = ror.read_hosts(Path(options["hosts"]))
        names = ror.read_names(Path(options["names"]))
        try:
            gate = ror.ror_gate(hosts, names, call=fetch_json_api)
        except SourceBlocked as error:
            raise CommandError(f"ROR unreachable: {error}") from error
        self.stdout.write(
            f"hosts {gate.hosts}, known {gate.known} ({_share(gate.known, gate.hosts)})"
        )
        self.stdout.write(
            f"website matches queried domain {gate.website_match} of {gate.known} "
            f"({_share(gate.website_match, gate.known)}) -- gated at 95%"
        )
        self.stdout.write(
            f"names {gate.names}, chosen {gate.name_known} "
            f"({_share(gate.name_known, gate.names)}), "
            f"exact name {gate.exact_name} ({_share(gate.exact_name, gate.name_known)}), "
            f"website agrees {gate.name_website_match} "
            f"({_share(gate.name_website_match, gate.name_known)}) -- recorded, not gated"
        )
        if not gate.passed:
            self.stdout.write("ROR GATE: FAIL")
            raise CommandError("ROR gate failed: ROR's website is not a key; Task 11 does not run")
        self.stdout.write("ROR GATE: PASS")
