"""Daily (spec §7.6): re-check due provenance verdicts, then sweep packs.

Scheduled by ProvenanceRecheckRule on WorkerTaskDefinition (runtime_engine).
A RECOGNISED pair is never due (spec §4.1): this re-checks UNCONFIRMED pairs
and anything not yet checked. RECOGNISED pairs get a free yearly screen (RDAP +
mill list, no page fetch); only a flagged one is fully re-checked.

provenance_check raises CommandError when any body errored. That error is
caught here so the sweep still runs -- a failed check must never suppress the
sweep that carries yesterday's already-resolved verdicts into packs -- and
re-raised afterward, so a scheduled run that hit an error still exits
non-zero.
"""

from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.provenance_job import Deps, screen_recognised


class Command(BaseCommand):
    help = "Re-check due provenance verdicts, then carry changes into packs." + CATALOG_ROLE_NOTE

    def handle(self, *args: Any, **options: Any) -> None:
        check_error: CommandError | None = None
        try:
            call_command("provenance_check", stdout=self.stdout)
        except CommandError as error:
            check_error = error
        tally = screen_recognised(now=timezone.now(), deps=Deps())
        for code, count in sorted(tally.items()):
            self.stdout.write(f"screen {code}: {count}")
        self.stdout.write(f"screened {sum(tally.values())} recognised domains")
        call_command("provenance_pack_sweep", stdout=self.stdout)
        if tally["error"] and check_error is None:
            check_error = CommandError(f"{tally['error']} recognised screen(s) errored")
        if check_error is not None:
            raise check_error
