"""The spec 9.3 gate: run the ladder over a hand-labelled truth set and score it.

    manage.py cycle_verify --truth docs/research/2026-09-cycle-truth-set.csv [--dry-run] [--out MD]

`passed` is precision >= 0.95 on OPEN **and** on UPCOMING **and** no
contradicted row -- an OPEN/UPCOMING the engine gave while the very sentence
the labeller decided SUSPENDED/ENDED/CLOSED_FOR_INTAKE on is among its own
evidence. Projection hit rate, conditional-deadline accuracy and per-country
recall are REPORTED, never asserted (spec 15: recall is printed and recorded,
never asserted by a test); the owner reads them beside the pass.

It never writes a catalog row. A truth row is not an award in the catalog, and
the gate must not make it one: every verdict is scored in memory and nothing is
persisted but what the fetch engine itself records. That fetch ledger
(FetchAttempt/HostProfile) is written at runtime by the catalogue's writer, so a
real run uses DATABASE_ROLE=runtime_engine, as the scheduled worker does -- not
the migration role, which owns those tables and so bypasses their policies.

A truth set must be labelled by a person, blind, from the organisations' own
sites (plan Task 12). A file with no data rows is refused for a real run: it is
unlabelled, and a gate over nothing would record a pass it never measured.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from apps.funding.cycle_evidence import deadline_student, observations, to_evidence
from apps.funding.validity import (
    cycle_validity,
    intake_start_year,
    project_window,
    select_deadline,
    served_intake_year,
)
from apps.research.fetch.site import crawl_ceiling

COLUMNS = (
    "organisation_domain", "country", "award_name", "award_kind", "award_scope", "own_url",
    "intake", "nationality", "country_of_residence", "expected_state", "expected_deadline",
    "deadline_condition", "evidence_url", "sentence", "last_call_opened", "prior_call_opened",
    "labelled_on", "labelled_by",
)
GATED = ("OPEN", "UPCOMING")
STATES = ("OPEN", "UPCOMING", "CLOSED_FOR_INTAKE", "SUSPENDED", "ENDED", "UNVERIFIED")
_SHUT = frozenset({"SUSPENDED", "ENDED", "CLOSED_FOR_INTAKE"})
PRECISION_BAR = 0.95


@dataclass(frozen=True)
class GateRow:
    """One truth row, labelled for one profile, and what the engine said."""

    domain: str
    expected: str
    got: str
    expected_deadline: str
    got_deadline: str
    contradicted: bool
    projected_open: dt.date | None
    actual_open: dt.date | None
    step: str
    #: A conditional row's second profile reuses the first's verdict and costs 0.
    cost_usd: float
    country: str
    #: The labelled `deadline_condition`; "" or "ALL" is not a conditional row.
    condition: str = ""
    cost_complete: bool = True
    hop_withheld: int = 0
    cycles_without_opening: int = 0
    #: The ladder run this row was scored from, `<own_url>@<intake year>`. A
    #: conditional row's two profiles share one; "" counts the row on its own.
    run: str = ""
    #: The verdict joined no evidence, yet the hop withheld a link: whatever
    #: the answer was, it sat behind a link plan decision 1 refused to follow.
    withheld_only: bool = False


@dataclass(frozen=True)
class GateReport:
    rows: int
    precision: dict[str, float | None]
    recall: dict[str, float | None]
    confusion: dict[tuple[str, str], int]
    contradicted: int
    projection_hit_rate: float | None
    deadline_accuracy: float | None
    deadline_accuracy_by_kind: dict[str, float]
    steps: dict[str, int]
    recall_by_country: dict[str, float]
    cost_per_verified: float | None
    cost_complete: bool
    settled_at_step_zero: float | None
    hop_withheld: int
    cycles_without_opening: int
    passed: bool
    #: Truth rows with no joined evidence and at least one withheld hop.
    withheld_only: int = 0
    notes: list[str] = field(default_factory=list)


def _ratio(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _conditional(row: GateRow) -> bool:
    return bool(row.condition) and row.condition != "ALL"


def score(rows: list[GateRow]) -> GateReport:
    """Pure: the report from scored rows. Nothing here fetches or writes."""
    confusion = Counter((row.expected, row.got) for row in rows)
    precision = {
        state: _ratio(confusion[(state, state)], sum(1 for r in rows if r.got == state))
        for state in STATES
    }
    recall = {
        state: _ratio(confusion[(state, state)], sum(1 for r in rows if r.expected == state))
        for state in STATES
    }
    contradicted = sum(1 for row in rows if row.contradicted)
    lapse = dt.timedelta(days=settings.CYCLE_PROJECTION_LAPSE_DAYS)
    backtest = [r for r in rows if r.projected_open and r.actual_open]
    hits = sum(
        1 for r in backtest
        if abs(cast(dt.date, r.actual_open) - cast(dt.date, r.projected_open)) <= lapse
    )
    conditional = [r for r in rows if _conditional(r)]
    by_kind: dict[str, list[bool]] = defaultdict(list)
    for row in conditional:
        by_kind[row.condition.split(":", 1)[0]].append(row.got_deadline == row.expected_deadline)
    country_rows: dict[str, list[GateRow]] = defaultdict(list)
    for row in rows:
        if row.expected in GATED:
            country_rows[row.country].append(row)
    # One scholarship per ladder run: a conditional row's second profile reuses
    # the first's verdict (and costs 0), so it is not a second one verified.
    verified = len({row.run or f"#{i}" for i, row in enumerate(rows) if row.got in GATED})
    total_cost = sum(row.cost_usd for row in rows)
    passed = (
        all((precision[state] or 0.0) >= PRECISION_BAR for state in GATED)
        and all(precision[state] is not None for state in GATED)
        and contradicted == 0
    )
    return GateReport(
        rows=len(rows),
        precision=precision,
        recall=recall,
        confusion=dict(confusion),
        contradicted=contradicted,
        projection_hit_rate=_ratio(hits, len(backtest)),
        deadline_accuracy=_ratio(
            sum(1 for r in conditional if r.got_deadline == r.expected_deadline), len(conditional)
        ),
        deadline_accuracy_by_kind={
            kind: cast(float, _ratio(sum(results), len(results)))
            for kind, results in by_kind.items()
        },
        steps=dict(Counter(row.step for row in rows)),
        recall_by_country={
            country: cast(float, _ratio(sum(1 for r in group if r.got == r.expected), len(group)))
            for country, group in sorted(country_rows.items())
        },
        cost_per_verified=round(total_cost / verified, 6) if verified else None,
        cost_complete=all(row.cost_complete for row in rows),
        settled_at_step_zero=_ratio(sum(1 for r in rows if r.step == "0"), len(rows)),
        hop_withheld=sum(row.hop_withheld for row in rows),
        cycles_without_opening=sum(row.cycles_without_opening for row in rows),
        passed=passed,
        withheld_only=sum(1 for row in rows if row.withheld_only),
    )


def render(report: GateReport) -> str:
    lines = [
        f"## Gate report ({report.rows} rows): {'PASS' if report.passed else 'FAIL'}",
        "",
        "| state | precision | recall |",
        "|---|---|---|",
        *(
            f"| {state} | {report.precision[state]} | {report.recall[state]} |"
            for state in STATES
        ),
        "",
        f"- contradicted: {report.contradicted}",
        f"- projection hit rate (within {settings.CYCLE_PROJECTION_LAPSE_DAYS} days): "
        f"{report.projection_hit_rate}",
        f"- conditional-deadline accuracy: {report.deadline_accuracy} "
        f"by kind {report.deadline_accuracy_by_kind}",
        f"- ladder steps: {report.steps}; settled at step 0: {report.settled_at_step_zero}",
        f"- recall of OPEN+UPCOMING by country: {report.recall_by_country}",
        f"- cost per verified scholarship: ${report.cost_per_verified}"
        + ("" if report.cost_complete else " (a floor: some spend could not be priced)"),
        f"- hop_withheld links: {report.hop_withheld}",
        f"- truth rows with no evidence but a withheld hop: {report.withheld_only}",
        f"- cycles_without_opening: {report.cycles_without_opening}",
        "",
        "Confusion (expected -> got):",
        *(
            f"- {expected} -> {got}: {n}"
            for (expected, got), n in sorted(report.confusion.items())
        ),
    ]
    return "\n".join(lines) + "\n"


def _date(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _normalised(text: str) -> str:
    return " ".join(text.split()).casefold()


def read_truth(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise CommandError(
                f"{path} does not carry the truth-set columns, in order: {', '.join(COLUMNS)}"
            )
        return [dict(row) for row in reader]


def _run_key(row: dict[str, str]) -> tuple[str, int]:
    year = intake_start_year(row["intake"])
    if year is None:
        raise CommandError(f"intake {row['intake']!r} names no year: {row['own_url']}")
    return row["own_url"], year


class Command(BaseCommand):
    help = (
        "Score the cycle-verification ladder against a hand-labelled truth set (spec 9.3 gate). "
        "Writes no catalog row; run with DATABASE_ROLE=runtime_engine (the fetch ledger's "
        "writer)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--truth", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--out", default="")

    def handle(self, *args: Any, **options: Any) -> None:
        truth = read_truth(Path(options["truth"]))
        runs = sorted({_run_key(row) for row in truth})
        if options["dry_run"]:
            self._estimate(truth, runs)
            return
        if not truth:
            raise CommandError(
                f"{options['truth']} has no data rows: the truth set is unlabelled. It must be "
                "labelled by a person, blind, from the organisations' own sites (plan Task 12) "
                "before the gate can run."
            )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise CommandError(
                "cycle_verify needs ANTHROPIC_API_KEY: the ladder reads with two model families"
            )
        report, disagreements = self._run(truth)
        text = render(report)
        self.stdout.write(text)
        for line in disagreements:
            self.stdout.write(line)
        if options["out"]:
            with Path(options["out"]).open("a", encoding="utf-8") as handle:
                handle.write("\n" + text)

    def _estimate(self, truth: list[dict[str, str]], runs: list[tuple[str, int]]) -> None:
        for row in truth:
            self.stdout.write(
                f"  {row['organisation_domain']} {row['award_name']} {row['intake']} "
                f"[{row['nationality']}/{row['country_of_residence']}] "
                f"expects {row['expected_state']}"
            )
        # Per run: the own page (one scrape) plus the worst-case crawl.
        ceiling = len(runs) * (1 + crawl_ceiling(settings.CYCLE_CRAWL_LIMIT))
        self.stdout.write(
            f"{len(truth)} rows, {len(runs)} ladder run{'s' if len(runs) != 1 else ''}: "
            f"at most {ceiling} Firecrawl credits "
            f"(CYCLE_CRAWL_LIMIT={settings.CYCLE_CRAWL_LIMIT}); nothing spent"
        )

    def _run(self, truth: list[dict[str, str]]) -> tuple[GateReport, list[str]]:
        # Imported here: the dry run and the scoring need no vendor client.
        import anthropic
        from openai import OpenAI

        from apps.research import cycle_verification
        from apps.research.cycle_verification import Subject, verify_cycle
        from apps.research.extraction import MessagesAPI, ResponsesAPI
        from apps.research.fetch import SweepBudget
        from apps.research.metering import Meter

        today = timezone.now().date()
        parser = cast(ResponsesAPI, OpenAI().responses)
        claude = cast(MessagesAPI, anthropic.Anthropic().messages)
        run_budget = SweepBudget(settings.CYCLE_RUN_CREDITS)
        verdicts: dict[tuple[str, int], tuple[Any, float, bool]] = {}
        scored: list[GateRow] = []
        disagreements: list[str] = []
        for row in truth:
            key = _run_key(row)
            first = key not in verdicts
            if first:
                subject = Subject(
                    name=row["award_name"], kind=row["award_kind"], scope=row["award_scope"],
                    own_urls=(row["own_url"],),
                    domains=frozenset({row["organisation_domain"]}),
                    primary_domain=row["organisation_domain"], ambiguous=False, cadence=None,
                )
                meter = Meter(run_budget)
                seams = cycle_verification.build_seams(
                    meter, parser, claude, source_id=f"truth:{row['organisation_domain']}"
                )
                verdict = verify_cycle(subject, intake_year=key[1], today=today, seams=seams,
                                       meter=meter, stored=[])
                usd, _detail, complete = meter.total()
                verdicts[key] = (verdict, float(usd), complete)
            verdict, usd_run, complete = verdicts[key]
            gate_row = self._score_row(row, key[1], verdict, today,
                                       cost=usd_run if first else 0.0, complete=complete)
            scored.append(gate_row)
            if gate_row.got != gate_row.expected or gate_row.contradicted:
                disagreements.append(self._disagreement(row, gate_row, verdict))
        return score(scored), disagreements

    @staticmethod
    def _score_row(
        row: dict[str, str], year: int, verdict: Any, today: dt.date, *, cost: float,
        complete: bool,
    ) -> GateRow:
        evidence = to_evidence(verdict.entries, target_year=year, cadence=None,
                               page_removed=verdict.page_removed, lapsed=verdict.lapsed)
        student = deadline_student(row["nationality"], row["country_of_residence"])
        got = cycle_validity(evidence, student=student, target_intake=str(year), today=today)
        deadline = select_deadline(evidence, student)
        sentence = _normalised(row["sentence"])
        contradicted = bool(
            got in GATED and row["expected_state"] in _SHUT and sentence
            and any(sentence in _normalised(e["quote"]) or _normalised(e["quote"]) in sentence
                    for e in verdict.entries if e["quote"])
        )
        hop_withheld = sum(1 for t in verdict.trail if t["outcome"] == "hop_withheld")
        last, prior = _date(row["last_call_opened"]), _date(row["prior_call_opened"])
        projected = (
            project_window(((prior, None),), target_year=served_intake_year(last))[0]
            if last and prior else None
        )
        return GateRow(
            domain=row["organisation_domain"], expected=row["expected_state"], got=got,
            expected_deadline=row["expected_deadline"],
            got_deadline=deadline.date.isoformat() if deadline else "",
            contradicted=contradicted, projected_open=projected, actual_open=last,
            step=verdict.step, cost_usd=cost, country=row["country"],
            condition=row["deadline_condition"], cost_complete=complete,
            hop_withheld=hop_withheld,
            cycles_without_opening=sum(
                1 for o in observations(verdict.entries) if o["open"] is None
            ),
            run=f"{row['own_url']}@{year}",
            withheld_only=not verdict.entries and hop_withheld > 0,
        )

    @staticmethod
    def _disagreement(row: dict[str, str], gate_row: GateRow, verdict: Any) -> str:
        quotes = [e["quote"] for e in verdict.entries if e["quote"]][:5]
        trail = [f"{t['step']}:{t['outcome']}:{t['url']}" for t in verdict.trail][:20]
        return (
            f"- {row['organisation_domain']} {row['award_name']} {row['intake']} "
            f"[{row['nationality']}/{row['country_of_residence']}]: expected "
            f"{gate_row.expected}, got {gate_row.got} at step {gate_row.step}"
            f"{' CONTRADICTED' if gate_row.contradicted else ''}\n"
            f"  quotes: {quotes}\n  trail: {trail}"
        )
