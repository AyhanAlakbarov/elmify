"""One-off loader: seed ApplicationPrompt from letter_prompt_fixtures.py.

Idempotent per (programme, cycle): re-running updates the existing VERIFIED
row for that programme/cycle rather than creating a duplicate.
"""

from typing import Any, cast

from django.core.management.base import BaseCommand

from apps.funding.letter_prompt_fixtures import LETTER_PROMPT_FIXTURES
from apps.funding.models import ApplicationPrompt, Program


class Command(BaseCommand):
    help = __doc__

    def handle(self, *_args: object, **_options: object) -> None:
        for key, raw_fixture in LETTER_PROMPT_FIXTURES.items():
            fixture = cast("dict[str, Any]", raw_fixture)
            lookup = cast("dict[str, Any]", fixture["lookup"])
            try:
                program = Program.objects.get(**lookup)
            except Program.DoesNotExist:
                self.stderr.write(f"no Program matches lookup {lookup!r} for fixture {key!r}")
                continue
            except Program.MultipleObjectsReturned:
                # canonical_key alone isn't unique on Program (only
                # (institution, canonical_key, location_key, origin_domain)
                # is) -- never silently pick one of several candidates.
                count = Program.objects.filter(**lookup).count()
                self.stderr.write(
                    f"lookup {lookup!r} for fixture {key!r} matches {count} Programs -- "
                    f"widen it (e.g. add an institution key) to disambiguate"
                )
                continue
            ApplicationPrompt.objects.update_or_create(
                programme=program,
                cycle=fixture["cycle"],
                defaults={
                    "source_url": fixture["source_url"],
                    "confidence": fixture["confidence"],
                    "verified_for_cycle": fixture["verified_for_cycle"],
                    "source": ApplicationPrompt.Source.VERIFIED,
                    "funder_kind": fixture["funder_kind"],
                    "structure": fixture["structure"],
                    "archetypes": fixture["archetypes"],
                    "questions": fixture["questions"],
                    "programme_evidence": fixture["programme_evidence"],
                    "document_language": fixture["document_language"],
                    "header_block_required": fixture["header_block_required"],
                    # Derived from funder_kind, never trusted from the fixture itself --
                    # a hand-set "immigration" key on the fixture is a value a fixture
                    # author could get wrong (and drift from funder_kind); this can't.
                    "immigration": (
                        fixture["funder_kind"] == ApplicationPrompt.FunderKind.IMMIGRATION_AUTHORITY
                    ),
                },
            )
            self.stdout.write(f"{key} -> {program.canonical_key}")
