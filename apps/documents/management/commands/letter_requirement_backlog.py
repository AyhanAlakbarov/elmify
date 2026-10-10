"""Count the letter requirements no column can type, so the next one can be.

    POSTGRES_DB=... uv run python manage.py letter_requirement_backlog

Spec `2026-09-19-letter-shape-tailoring` section 3b: a sentence the shape
cannot type travels as data (path 2) or as a student action (path 3), and the
research sample is grown FROM PRODUCTION rather than from another reading
pass. This command is that loop's counter -- a kind of requirement seen on
three or more programmes is the next closed question worth adding a column
for.

It prints counts and ONE example URL per group, never a tenant, a student or a
letter: these rows are catalogue data about programmes, and nothing here
touches a tenant table.
"""

from __future__ import annotations

import re
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandParser

from apps.funding.models import ApplicationPrompt

#: Grouping is by NORMALISED sentence: case folded, whitespace collapsed,
#: trailing punctuation dropped. Two pages wording the same rule differently
#: still count separately -- that is a limit of counting sentences, and the
#: honest one: the point is to find the rule a human reads across the top
#: groups, not to cluster prose automatically.
_TRAILING = re.compile(r"[\s.;:,!?]+$")


def _normalised(text: str) -> str:
    return _TRAILING.sub("", " ".join(text.split()).casefold())


class Command(BaseCommand):
    help = "Count letter requirements and student actions across every application prompt."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--minimum",
            type=int,
            default=1,
            help="Only print groups seen at least this many times (spec 3b uses 3).",
        )

    def handle(self, *args: object, **options: object) -> None:
        minimum = int(options["minimum"])  # type: ignore[call-overload]
        counts: dict[tuple[str, str], int] = defaultdict(int)
        examples: dict[tuple[str, str], tuple[str, str]] = {}
        for prompt in ApplicationPrompt.objects.all().only(
            "letter_written_requirements", "letter_student_actions", "source_url"
        ):
            for path, entries in (
                ("written", prompt.letter_written_requirements),
                ("action", prompt.letter_student_actions),
            ):
                for entry in entries:
                    text = str(entry.get("text", "")).strip()
                    if not text:
                        continue
                    key = (path, _normalised(text))
                    counts[key] += 1
                    # The FIRST example is kept, so a re-run over unchanged
                    # rows prints the same line and a diff is readable.
                    examples.setdefault(
                        key, (text, str(entry.get("source_url", "")) or prompt.source_url)
                    )
        if not counts:
            self.stdout.write("no letter requirements recorded yet")
            return
        for (path, _), count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            if count < minimum:
                continue
            text, url = examples[(path, _)]
            self.stdout.write(f"{count:>4}  {path:<7}  {text}")
            self.stdout.write(f"      {url}")
