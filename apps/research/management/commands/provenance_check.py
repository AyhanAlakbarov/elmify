"""Compute provenance verdicts (spec §7.1, §7.7). Outside any tenant transaction.

Default: the (body, domain) pairs in play whose check is due. `--all`: every
pair in play, due or not -- the rollout backfill that must run before
PROVENANCE_GATE_ENFORCED is turned on. `--domain`: those domains only, each
reduced to its registrable domain ("www.tum.de" -> "tum.de").

Exits non-zero when any pair errored, after printing the tally, so a scheduled
run that crashed on a body is not reported as a clean one.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.hosts import registrable_domain
from apps.research.models import OrganisationDomain
from apps.research.provenance_job import Deps, bodies_in_play, due, run_checks


class Command(BaseCommand):
    help = "Compute provenance verdicts for bodies in play (spec §7.1)." + CATALOG_ROLE_NOTE

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--all", action="store_true", help="every body in play (backfill)")
        parser.add_argument("--domain", action="append", default=[], dest="domains")

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        if options["domains"]:
            domains = {value: registrable_domain(value) for value in options["domains"]}
            unkeyable = sorted(value for value, domain in domains.items() if not domain)
            if unkeyable:
                raise CommandError(f"no registrable domain in: {', '.join(unkeyable)}")
            pairs = OrganisationDomain.objects.filter(
                registrable_domain__in=set(domains.values())
            ).select_related("organisation")
        elif options["all"]:
            pairs = bodies_in_play()
        else:
            pairs = due(now)
        tally = run_checks(pairs, now=now, deps=Deps())
        for code, count in sorted(tally.items()):
            self.stdout.write(f"{code}: {count}")
        self.stdout.write(f"checked {sum(tally.values())} domains")
        if tally["error"]:
            raise CommandError(f"{tally['error']} domain(s) errored; see the log")
