"""Load curated programme-provider bindings from a CSV.

    DATABASE_ROLE=runtime_engine uv run python manage.py load_program_providers \\
        docs/research/program-providers.csv

Which universities award a programme is shared-catalog data every tenant
reads, so it lives in a checked-in file rather than a bare database write:
in a file it is a reviewed diff, attributable and revertable. This is the
whole curation path now -- the register bindings it used to hand off to were
removed with the institution-safety screen on 2026-09-14 (see CLAUDE.md), so
a binding ends here rather than being resolved to a register code afterwards.

funding_program_awarding_institutions is writable only by runtime_engine
(its runtime_engine_write policy), so run this as runtime_engine. This loader
is insert-only for the pair table, and an INSERT blocked by RLS raises, so a
wrong-role run fails loudly.

It is also the hand-curation route for Institution itself: a row naming an
institution the catalog does not have creates it, which is what makes
"canonical_key is hand-curated" true rather than aspirational.
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, transaction

from apps.funding.models import Institution, Program, ProgramAwardingInstitution

_REQUIRED_COLUMNS = ("program_key", "institution_key", "name", "country_code", "official_website")


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("csv_path")

    def handle(self, *args: object, **options: object) -> None:
        path = str(options["csv_path"])
        # utf-8-sig: an Excel re-export carries a BOM, which under plain utf-8
        # corrupts the first header and makes every row look unmapped.
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
            if missing:
                raise CommandError(f"CSV is missing expected column(s): {missing}")
            rows = list(reader)

        by_program: dict[str, list[tuple[int, dict[str, str]]]] = {}
        for line, row in enumerate(rows, start=2):
            website = row["official_website"].strip()
            if not website.startswith("https://"):
                raise CommandError(f"line {line}: {website!r} must be https")
            if len(row["country_code"].strip()) != 2:
                raise CommandError(
                    f"line {line}: {row['country_code']!r} is not an ISO 3166 alpha-2 code"
                )
            by_program.setdefault(row["program_key"].strip(), []).append((line, row))

        loaded = 0
        resolved = 0
        with transaction.atomic():
            for program_key, program_rows in by_program.items():
                matches = list(
                    Program._base_manager.filter(
                        canonical_key=program_key,
                        provision_type=Program.ProvisionType.JOINT,
                    )
                )
                if not matches:
                    raise CommandError(f"no joint programme with key {program_key!r}")
                if len(matches) > 1:
                    raise CommandError(
                        f"{program_key!r} matches {len(matches)} joint programmes -- "
                        f"a human must say which"
                    )
                program = matches[0]
                institutions = []
                for line, row in program_rows:
                    # get_or_create wraps its INSERT in its own savepoint, so a
                    # constraint it trips (institution_country_iso3166_alpha2 is
                    # the one a "two letters but not real ISO" code like "XX"
                    # hits -- the length check above only rejects the wrong
                    # length) rolls back to that savepoint and leaves this
                    # command's own transaction.atomic() usable for the
                    # CommandError below, not aborted.
                    try:
                        institution, created = Institution._base_manager.get_or_create(
                            canonical_key=row["institution_key"].strip(),
                            defaults={
                                "name": row["name"].strip(),
                                "country_code": row["country_code"].strip().upper(),
                                "official_website": row["official_website"].strip(),
                            },
                        )
                    except IntegrityError as exc:
                        raise CommandError(
                            f"line {line}: institution {row['institution_key']!r} was "
                            f"rejected by the database: {exc}"
                        ) from exc
                    # get_or_create() silently drops `defaults` for an
                    # existing row, so a curator who reuses a wrong-but-
                    # existing key would otherwise get a clean run that binds
                    # the programme to whatever institution already held that
                    # key -- no error, and the checked-in diff would lie
                    # about which institution it is. Only `name` is checked:
                    # it's the field a human actually reads when reviewing
                    # the diff. country_code and official_website are left
                    # alone on purpose -- an institution can legitimately
                    # change its website, and checking every column would
                    # turn this into a full-record sync this loader isn't.
                    csv_name = row["name"].strip()
                    if not created and institution.name != csv_name:
                        raise CommandError(
                            f"line {line}: institution {row['institution_key']!r} is "
                            f"already recorded as {institution.name!r}, but the CSV "
                            f"says {csv_name!r} -- fix the CSV or the canonical_key"
                        )
                    institutions.append(institution)
                    try:
                        ProgramAwardingInstitution._base_manager.create(
                            program=program, institution=institution
                        )
                    except IntegrityError as exc:
                        raise CommandError(
                            f"line {line}: {program_key!r} is already bound to "
                            f"{row['institution_key']!r} -- re-running an "
                            f"already-loaded pair: {exc}"
                        ) from exc
                    loaded += 1
                # Exactly one provider means it was never joint -- the name rule's
                # measured false positives (a bilingual name, a Finnish
                # "University Consortium") resolve here with no special case.
                if len(institutions) == 1:
                    program.institution = institutions[0]
                    program.provision_type = Program.ProvisionType.SINGLE
                    program.provider_text = ""
                    program.save(
                        update_fields=["institution", "provision_type", "provider_text"]
                    )
                    resolved += 1

        self.stdout.write(f"loaded={loaded} resolved={resolved}")
