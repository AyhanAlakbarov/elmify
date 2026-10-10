"""One-off loader: seed Program.cv_format_requirement from docs/research/cv-rules.csv.

Writes shared-catalog rows, which only runtime_engine may update
(funding_program's runtime_engine_write policy). Run it as:

    DATABASE_ROLE=runtime_engine uv run python manage.py load_cv_format_requirements \\
        docs/research/cv-rules.csv
"""

from __future__ import annotations

import csv
import re

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.funding.cv_ruleset_scope_map import RULE_TO_PROGRAM
from apps.funding.models import Program

#: Values that change what gets rendered and can get an application rejected.
_HIGH_RISK_VALUES = frozenset(
    {
        Program.CVFormatRequirement.EUROPASS_REQUIRED,
        Program.CVFormatRequirement.FUNDER_TEMPLATE,
    }
)

#: Substrings that mean the cycle cell is a caveat, not a cycle. Taken from the
#: real values in cv-rules.csv ("re-fetched ... STALE ... reverify",
#: "cycle label unconfirmed", "not established (others)", "CoMEM TBA").
_HEDGES = (
    "reverify",
    "unconfirmed",
    "stale",
    "unverified",
    "not established",
    "tba",
    "v1-only",
    "evergreen",
    "mixed - see rows",
)

#: A "concrete cycle" needs a positive signal, not just the absence of a
#: hedge -- R-066's real cell ("current template, cycle label not printed on
#: file") states outright that it has no dated cycle while matching none of
#: _HEDGES. Every real dated cell in cv-rules.csv carries a 4-digit year.
_YEAR_RE = re.compile(r"\d{4}")


def _is_verified(cycle: str, confidence: str) -> bool:
    """A row is VERIFIED only if it names a real cycle and says so confidently."""
    normalised = cycle.strip().lower()
    if not normalised or any(hedge in normalised for hedge in _HEDGES):
        return False
    if not _YEAR_RE.search(cycle):
        return False
    return confidence.strip().lower() == "high"


def _field(row: dict[str, str], column: str) -> str:
    """Same KeyError, everywhere a column is read -- a renamed CSV header
    should name itself in a CommandError, not crash the loop on a bare
    KeyError from whichever column happened to be read first."""
    try:
        return row[column]
    except KeyError:
        raise CommandError(f"CSV is missing expected column {column!r}") from None


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("csv_path")
        parser.add_argument(
            "--allow-unverified",
            action="store_true",
            help="load europass_required/funder_template from a row we could not verify",
        )

    def handle(self, *_args: object, **options: object) -> None:
        csv_path = str(options["csv_path"])
        allow_unverified = bool(options["allow_unverified"])
        # utf-8-sig: an Excel re-export of the CSV can carry a BOM, which
        # under plain utf-8 corrupts the first header into "﻿ID" and
        # makes every row look unmapped -- a silent whole-file skip.
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                self._apply_row(row, allow_unverified=allow_unverified)

    def _apply_row(self, row: dict[str, str], *, allow_unverified: bool) -> None:
        rule_id = _field(row, "ID").strip()
        target = RULE_TO_PROGRAM.get(rule_id)
        if target is None:
            return
        if target.requirement not in set(Program.CVFormatRequirement.values):
            raise CommandError(
                f"{rule_id}: map entry has unknown requirement {target.requirement!r}"
            )
        cycle = _field(row, "Verified for cycle").strip()
        confidence = _field(row, "Confidence")
        source_url = _field(row, "Source URL [provenance]").strip()
        verified = _is_verified(cycle, confidence)
        if target.requirement in _HIGH_RISK_VALUES and not verified and not allow_unverified:
            self.stderr.write(
                f"{rule_id}: refusing {target.requirement} from an unverified row "
                f"(cycle={cycle!r}, confidence={confidence!r}); "
                f"pass --allow-unverified to override"
            )
            return
        # cv_format_verified_for_cycle is a CharField(max_length=40); .update()
        # skips full_clean() so an oversized value hits Postgres as an
        # unhandled DataError instead. Only relevant when verified -- an
        # unverified row always stores None here regardless of length.
        cycle_max_length = Program._meta.get_field("cv_format_verified_for_cycle").max_length
        if verified and cycle_max_length is not None and len(cycle) > cycle_max_length:
            self.stderr.write(
                f"{rule_id}: cycle {cycle!r} is {len(cycle)} chars, over the "
                f"{cycle_max_length}-char cv_format_verified_for_cycle column; skipping"
            )
            return
        # Two rows differing only by origin_domain are one programme as two
        # sites describe it -- at most one of them the university's own. Which
        # one a hand-verified rule belongs to is a human's call, never ours.
        places: dict[tuple[object, str], str] = {}
        for institution_id, place, origin in Program.objects.filter(
            canonical_key=target.canonical_key
        ).values_list("institution_id", "location_key", "origin_domain"):
            if places.setdefault((institution_id, place), origin) != origin:
                self.stderr.write(
                    f"{rule_id}: {target.canonical_key!r} matches the same programme "
                    f"from more than one site ({places[(institution_id, place)]!r}, "
                    f"{origin!r}); refusing -- a human must say which"
                )
                return
        updated = Program.objects.filter(canonical_key=target.canonical_key).update(
            cv_format_requirement=target.requirement,
            cv_format_verified_for_cycle=cycle if verified else None,
            cv_format_source_url=source_url,
            cv_format_confidence=(
                Program.CVFormatConfidence.VERIFIED
                if verified
                else Program.CVFormatConfidence.UNVERIFIED
            ),
        )
        if updated == 0:
            self.stderr.write(
                f"{rule_id}: no Program with canonical_key {target.canonical_key!r} "
                f"(if one exists, re-run under DATABASE_ROLE=runtime_engine -- no other "
                f"role can update funding_program)"
            )
        else:
            # canonical_key is not unique on Program (only the
            # (institution, canonical_key, location_key, origin_domain) key
            # is), so this can legitimately update several rows -- the same
            # programme across campuses. Not an error; must not be silent
            # either. The same campus from two sites was refused above.
            self.stdout.write(f"{rule_id} -> {updated} programme(s)")
