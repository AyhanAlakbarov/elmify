"""Re-ask the grammar over stored sentences, without refetching a page.

Spec §6.5. When an operation enters the grammar -- because the unapplied count
said the kind was real -- every programme that ever stated that rule should get
it. The sentences are already stored, so the questions are simply asked again.

**This is the sweep CLAUDE.md warns about.** It calls the decision layer
directly rather than through `read_program_page`, which is where the
per-programme limiter lives, so it carries its own budget or it is an unbounded
call per programme. It never falls back to the frontier judge: with no decision
provider it stops (2026-09-26 addendum §2 -- the fallback is the page read's,
not this sweep's). CV rows only; the letter shape is per cycle.

Every programme's read-ask-write is its own `_atomic_keeping_decisions` block
(`program_rules`, Task 6/10's mechanism): a refusal or budget stop on one
programme rolls back only that programme's own would-be write, never an
already-committed one from an earlier programme in this run, and the
DecisionRecord rows spent or refused along the way survive the rollback --
exactly the guarantee a page read gets, applied once per programme instead of
once per page.

**It owns less than a page read does** (final review, I3). A page read also
sees the lines code finds on the page, which are not stored as statements, so
this sweep never writes the CV format switch or its confidence, and it replaces
only the rules and directives whose sentence it re-read -- every other stored
rule is kept. `ProgramStatement` stores no heading, so each sentence is asked
about with none.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.documents.constraints import ConstraintRule, _quote
from apps.documents.derive import (
    _THIRD_PARTY,
    CV_STATEMENT_KINDS,
    Candidate,
    _grammar_rules,
    _split_oversize,
    _write_program,
)
from apps.documents.grammar_questions import AskFn
from apps.documents.program_rules import _atomic_keeping_decisions
from apps.documents.rule_sinks import (
    resolve_conflicts,
    to_constraint_rules,
    to_directives,
    to_notes,
    to_referee,
)
from apps.funding.models import Program, ProgramStatement
from apps.research.decisions import (
    DecisionBudgetExhausted,
    DecisionsUnavailable,
    run_budget,
)

_PAGE_INDEX = re.compile(r"^PAGE-(\d+)-")


def _past_kept(kept: list[dict[str, Any]]) -> int:
    """The first sentence index no kept rule's id uses. The sweep numbers its
    sentences from here, so a re-read note never shares a kept note's id:
    resolve_rules slots notes by rule_id and a shared id drops one silently."""
    used = [int(m[1]) for r in kept if (m := _PAGE_INDEX.match(str(r.get("rule_id", ""))))]
    return max(used, default=-1) + 1


def _shifted(note: ConstraintRule, offset: int) -> ConstraintRule:
    rule_id = _PAGE_INDEX.sub(lambda m: f"PAGE-{int(m[1]) + offset}-", note.rule_id)
    return note.model_copy(update={"rule_id": rule_id})


# <!-- reconciled 2026-09-26: _grammar_rules takes AskFn | None -->
def _client() -> AskFn | None:
    """The decision client. A seam so a test injects without a network call."""
    return None


class Command(BaseCommand):
    help = "Re-derive every programme's CV rules from its stored sentences. Fetches nothing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--program", help="one programme id; default is every programme")
        parser.add_argument("--dry-run", action="store_true",
                            help="still ask the decision provider (spends tokens) and "
                                 "report what would change, but write nothing -- no "
                                 "Program row and no DecisionRecord")

    def handle(self, *args: Any, **options: Any) -> None:
        budget = run_budget()
        client = _client()
        # Ordered, not `.all()`: a stable order makes a stopped run resumable
        # by eye and makes which programme committed before a later one
        # stopped the sweep a property of the data, not of a heap scan.
        programmes = Program.objects.order_by("canonical_key")
        if options["program"]:
            programmes = programmes.filter(id=options["program"])

        changed = 0
        stopped = False
        for program in programmes.iterator():
            # Fix round 1, finding 2: the same kinds `derive_page_rules` asks
            # the grammar about (derive.CV_STATEMENT_KINDS), reused rather
            # than restated -- a COMPETENCY/LANGUAGE/OTHER statement is never
            # fed to the grammar as a CV candidate.
            statements = list(
                ProgramStatement.objects.filter(program=program, kind__in=CV_STATEMENT_KINDS)
                .order_by("id")
                .values_list("text", "snapshot__final_url")
            )
            if not statements:
                # Nothing has read this programme. An empty re-derivation here
                # would erase rules a real read DID produce.
                continue
            source_url = statements[0][1] or ""
            reread = {_quote(text) for text, _ in statements}
            kept_rules = [r for r in program.cv_constraints if r.get("rule_text") not in reread]
            kept_directives = [
                d for d in program.cv_directives if d.get("rule_text") not in reread
            ]
            kept_referee = [
                d for d in program.referee_requirements if d.get("rule_text") not in reread
            ]
            offset = _past_kept(kept_rules)
            candidates = tuple(
                # `heading` is empty until plan 2 stores heading_path on the
                # statement; the sentence stands alone, which is why this sweep
                # is run deliberately and its output read, not scheduled.
                Candidate(text=text, heading="", europass="europass" in text.lower(),
                          third_party=bool(_THIRD_PARTY.search(text)))
                for text, _ in statements
            )
            # Controller ruling: reuse derive's own oversize path rather than
            # duplicating it -- one candidate too large for the decision layer
            # to ask about becomes an unapplied note, and the rest of the page
            # is still read.
            kept, oversize_notes = _split_oversize(candidates, source_url=source_url)
            try:
                with _atomic_keeping_decisions(source_url=source_url):
                    # Fix round 1, finding 1: a dry run must not spend a
                    # DecisionRecord row either -- it still asks the provider
                    # (there is no cheaper way to know what would change), but
                    # record=False means ask() neither reads nor writes the
                    # cache for this call, so nothing is left behind by a run
                    # whose own help text promises "write nothing".
                    raw, _slots = _grammar_rules(kept, language="", budget=budget,
                                                 client=client, record=not options["dry_run"])
                    rules = tuple(replace(r, index=r.index + offset)
                                  for r in resolve_conflicts(raw))
                    stored = [
                        *to_constraint_rules(rules, source_url=source_url),
                        *to_notes(rules, source_url=source_url),
                        *(_shifted(n, offset) for n in oversize_notes),
                    ]
                    payload = kept_rules + [r.model_dump(mode="json") for r in stored]
                    directives = kept_directives + list(
                        to_directives(rules, source_url=source_url)
                    )
                    referee = kept_referee + list(to_referee(rules, source_url=source_url))
                    if (payload == program.cv_constraints
                            and directives == program.cv_directives
                            and referee == program.referee_requirements):
                        continue
                    changed += 1
                    self.stdout.write(
                        f"{program.canonical_key}: {[r['key'] for r in payload]} "
                        f"{[d['action'] for d in directives]}"
                    )
                    if options["dry_run"]:
                        continue
                    # Never the format switch: a page read saw lines this
                    # sweep cannot, and owns it (module docstring).
                    # _write_program, not a bare update(): under RLS a role
                    # without the grant updates zero rows and reports success.
                    _write_program(program.id, cv_constraints=payload,
                                   cv_directives=directives, referee_requirements=referee)
            except DecisionBudgetExhausted as error:
                self.stdout.write(f"stopping: decision budget reached ({error})")
                stopped = True
                break
            except DecisionsUnavailable as error:
                self.stdout.write(f"stopping: decision layer unavailable ({error})")
                stopped = True
                break

        self.stdout.write(
            f"{changed} programmes changed; {budget.spent} decision tokens spent"
            + (" (stopped early)" if stopped else "")
        )
