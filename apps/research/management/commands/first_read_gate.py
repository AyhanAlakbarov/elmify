"""The cheap first read against the judge, side by side (funding master spec §8.9).

Firecrawl's `json` format reads a page for 4 credits; the judge reads it with
three model calls and sometimes a fourth. This command fetches each page
ONCE, with the json format riding on the same scrape, reads that same page
with the judge, and writes one row per award either reader would show -- for
a person to label. `--score` reads the labelled sheet back and prints the
outcome §8.9 names:

  (a) the first read is at least as precise as the judge -> it becomes the
      first pass, and the judge reads only where a fact reaches a student or
      the two disagree;
  (b) less precise, but it flags >= 95% of the pages where the judge found a
      correct award -> it becomes triage, deciding which pages the judge reads;
  (c) otherwise -> recorded, and the judge stays alone.

Nothing here routes a production read: adopting (a) or (b) is its own change.
Pages only scrape.do can fetch are skipped, because they have no first read to
compare. Labels are a person's: an agent may prepare the sheet, never fill it.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

import anthropic
from django.core.management.base import BaseCommand, CommandError, CommandParser
from openai import OpenAI

from apps.research.egress import SourceBlocked, UnsafeTarget
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import (
    CATALOG_ROLE_NOTE,
    USD_PER_CREDIT,
    SweepBudget,
    _default_providers,
    fetch_page,
    firecrawl,
)
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.first_read import (
    FirstReadVerdict,
    first_read_verdicts,
    json_format,
    quotes_match,
)
from apps.research.funding_judge import FundingDecision, funding_chunks, read_funding
from apps.research.funding_reader import _FUNDING_TERMS
from apps.research.management.commands.funding_yield import read_hosts, served_by_gate
from apps.research.model_cost import CostMeter
from apps.research.models import FetchAttempt
from apps.research.reader import _MIN_BYTES_FOR_FLOOR, _MIN_READABLE_CHARS, readable_text
from apps.research.search import funding_links

GATE_COLUMNS = (
    "host", "page_url", "quote", "judge_claims", "first_claims", "judge_holder", "judge_scope",
    "first_holder", "first_scope", "judge_correct", "first_correct",
)
#: The owner's 30-card practice (spec §8.8), applied per reader.
MIN_LABELS = 30
#: Triage may miss at most one page in twenty where the judge found a real award.
TRIAGE_RECALL = 0.95


def _row(
    host: str,
    url: str,
    quote: str,
    *,
    judge: FundingDecision | None = None,
    first: FirstReadVerdict | None = None,
) -> dict[str, str]:
    return {
        "host": host,
        "page_url": url,
        "quote": quote,
        "judge_claims": "y" if judge else "n",
        "first_claims": "y" if first else "n",
        "judge_holder": judge.holder if judge else "",
        "judge_scope": judge.scope if judge else "",
        "first_holder": first.holder if first else "",
        "first_scope": first.scope if first else "",
        "judge_correct": "",
        "first_correct": "",
    }


def claim_rows(
    host: str,
    url: str,
    decisions: Iterable[FundingDecision],
    verdicts: tuple[FirstReadVerdict, ...],
) -> list[dict[str, str]]:
    """One row per award either reader would show.

    The judge claims an award it would serve; the first read claims every
    verified YES sentence. Every first-read sentence matching any of a served
    award's quotes joins that award's row -- a multi-line award is one claim,
    not one per line -- and the rest become first-read-only rows. A sentence
    is the first read's claim on ONE row only: when it matches two served
    awards, the first wins and the second row shows no first-read claim for
    it, so one sentence is never labelled (and scored) twice.
    """
    offered = [verdict for verdict in verdicts if verdict.offered == "YES"]
    used: set[int] = set()
    rows: list[dict[str, str]] = []
    for decision in decisions:
        if not served_by_gate(decision):
            continue
        matched = [
            i for i, verdict in enumerate(offered)
            if any(quotes_match(verdict.quote, quote) for quote in decision.quotes)
        ]
        fresh = [i for i in matched if i not in used]
        used.update(matched)
        rows.append(
            _row(host, url, decision.quotes[0], judge=decision,
                 first=offered[fresh[0]] if fresh else None)
        )
    rows.extend(
        _row(host, url, verdict.quote, first=verdict)
        for i, verdict in enumerate(offered)
        if i not in used
    )
    return rows


@dataclass(frozen=True)
class GateScore:
    judge_labelled: int
    judge_correct: int
    first_labelled: int
    first_correct: int
    #: Pages with at least one correct judge award.
    judge_pages: int
    #: Of those, pages where the first read claimed anything at all.
    flagged_pages: int

    def outcome(self) -> str:
        if self.judge_labelled < MIN_LABELS or self.first_labelled < MIN_LABELS:
            return (
                f"undecided -- fewer than {MIN_LABELS} labelled claims for a reader; "
                "read more pages"
            )
        judge = self.judge_correct / self.judge_labelled
        first = self.first_correct / self.first_labelled
        if first >= judge:
            return (
                "(a) first pass: the judge reads only where a fact reaches a student or the "
                "two disagree"
            )
        if self.judge_pages and self.flagged_pages / self.judge_pages >= TRIAGE_RECALL:
            return "(b) triage: the first read decides which pages the judge reads"
        return "(c) judge alone: recorded; the first read decides nothing"

    def lines(self) -> list[str]:
        return [
            f"judge precision: {self.judge_correct}/{self.judge_labelled}",
            f"first-read precision: {self.first_correct}/{self.first_labelled}",
            f"triage recall (pages with a correct judge award the first read flagged): "
            f"{self.flagged_pages}/{self.judge_pages}",
            f"outcome: {self.outcome()}",
        ]


def score_rows(rows: list[dict[str, str]]) -> GateScore:
    """Every claim labelled y or n by its own reader's column, nothing else.

    Every cell is read stripped and lower-cased, claims and labels alike: a
    hand-edited sheet carries " Y " as often as "y".
    """

    def cell(row: dict[str, str], column: str) -> str:
        return row[column].strip().lower()

    judge_labelled = judge_correct = first_labelled = first_correct = 0
    judge_pages: set[str] = set()
    flagged: set[str] = set()
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        for reader in ("judge", "first"):
            claims = cell(row, f"{reader}_claims") == "y"
            label = cell(row, f"{reader}_correct")
            if claims and label not in {"y", "n"}:
                raise ValueError(f"row {number}: {reader}_correct must be y or n")
            if not claims and label:
                raise ValueError(f"row {number}: {reader}_correct labels a claim it did not make")
        if cell(row, "judge_claims") == "y":
            judge_labelled += 1
            if cell(row, "judge_correct") == "y":
                judge_correct += 1
                judge_pages.add(row["page_url"])
        if cell(row, "first_claims") == "y":
            first_labelled += 1
            flagged.add(row["page_url"])
            if cell(row, "first_correct") == "y":
                first_correct += 1
    return GateScore(
        judge_labelled, judge_correct, first_labelled, first_correct,
        len(judge_pages), len(judge_pages & flagged),
    )


def gate_providers() -> dict[str, Callable[..., FetchedPage]]:
    """The ladder's own providers, with the json first read riding every Firecrawl scrape."""
    return {
        **_default_providers(),
        "firecrawl": partial(firecrawl.scrape, json_format=json_format()),
    }


@dataclass
class JsonSpend:
    """Json-format credits Firecrawl billed during one gate run -- every call.

    Summed per scrape, not per page read: the surcharge lands on dead, blocked,
    invalid and shell pages too, and on both calls of a rung-1 shell that
    escalates to rung 2. Counting only pages both readers read under-reports
    the first read's cost by exactly the pages it could not be compared on.
    """

    credits: int = 0

    @property
    def usd(self) -> float:
        return self.credits * USD_PER_CREDIT["FIRECRAWL"]


def gate_fetch(
    credits: int, *, providers: dict[str, Callable[..., FetchedPage]] | None = None
) -> tuple[Callable[[str], FetchedPage], SweepBudget, JsonSpend]:
    """The gate's fetcher, the budget it spends against, and its json spend.

    scrape.do is capped at zero: a page only it can fetch has no first read to
    compare. `SweepBudget.check` refuses a capped vendor BEFORE the request, so
    such a page comes back `Outcome.BUDGET` and nothing is billed for it -- and
    no retry is left queued: `fetch_page` stamps that refusal with a
    `retry_after`, which `manage.py retry_due_fetches` would later honour under
    the PRODUCTION budget (scrape.do's 25-credit tier included), so the gate
    clears it on this sweep's BUDGET rows after every fetch. Every BUDGET row in
    the gate's own sweep is the gate's own refusal; the cap holds past the run.
    """
    budget = SweepBudget({"FIRECRAWL": credits, "SCRAPE_DO": 0})
    chosen = dict(providers if providers is not None else gate_providers())
    spend = JsonSpend()
    scrape = chosen["firecrawl"]

    def counted(*args: object, **kwargs: object) -> FetchedPage:
        page = scrape(*args, **kwargs)
        spend.credits += page.json_credits
        return page

    chosen["firecrawl"] = counted

    def fetch(url: str) -> FetchedPage:
        try:
            return fetch_page(url, budget=budget, providers=chosen)
        finally:
            FetchAttempt.objects.filter(
                sweep_id=budget.sweep_id, outcome=str(Outcome.BUDGET), retry_after__isnull=False
            ).update(retry_after=None)

    return fetch, budget, spend


#: What one fetch may raise instead of returning a refusal: an unsafe host
#: (`UnsafeTarget` is a ValueError) or a vendor failure the ladder did not
#: absorb (`SourceBlocked` and its subclasses). One bad host must not end a run
#: that has already paid for the hosts before it.
_FETCH_ERRORS = (SourceBlocked, UnsafeTarget, ValueError)


class Command(BaseCommand):
    help = (
        "Measure Firecrawl's json first read against the funding judge on the same pages "
        "(spec §8.9) and write a labelling sheet; --score reads it back." + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--hosts", default="")
        parser.add_argument("--pages", type=int, default=2)
        parser.add_argument(
            "--credits", type=int, default=600, help="Firecrawl credits this run may spend"
        )
        parser.add_argument("--out", default="")
        parser.add_argument("--score", default="")

    def handle(self, *_args: object, **options: object) -> None:
        if options["score"]:
            path = Path(str(options["score"]))
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            try:
                score = score_rows(rows)
            except (KeyError, ValueError) as error:
                raise CommandError(f"{path}: {error}") from error
            for line in score.lines():
                self.stdout.write(line)
            return
        if not options["hosts"] or not options["out"]:
            raise CommandError(
                "running the gate needs --hosts and --out; --score reads a labelled sheet"
            )
        if not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("OPENAI_API_KEY"):
            raise CommandError("both model keys are needed: the judge is half of this comparison")
        fetch, budget, spend = gate_fetch(int(str(options["credits"])))
        rows = self._run(
            read_hosts(Path(str(options["hosts"]))),
            pages=max(1, int(str(options["pages"]))),
            parser=cast(ResponsesAPI, OpenAI().responses),
            claude=cast(MessagesAPI, anthropic.Anthropic().messages),
            fetch=fetch,
            spend=spend,
        )
        out = Path(str(options["out"]))
        with out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=GATE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(
            f"wrote {len(rows)} claims to {out}; label judge_correct / first_correct y or n "
            "against the live page, then run --score"
        )
        self.stdout.write(
            f"firecrawl credits spent: {budget.spent['FIRECRAWL']} (${budget.usd():.4f})"
        )

    def _run(
        self,
        hosts: list[tuple[str, str]],
        *,
        pages: int,
        parser: ResponsesAPI,
        claude: MessagesAPI,
        fetch: Callable[[str], FetchedPage],
        spend: JsonSpend,
    ) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        judge_meter = CostMeter()
        read = answers = off_schema = dropped = unreadable = 0
        for host, _label in hosts:
            home = self._fetch(fetch, host, f"https://{host}/")
            if home is None:
                continue
            targets = [home]
            for url in funding_links(home)[: pages - 1]:
                page = self._fetch(fetch, host, url)
                if page is not None:
                    targets.append(page)
            for page in targets:
                whole = readable_text(page, terms=None)
                if len(whole) < _MIN_READABLE_CHARS and len(page.body) >= _MIN_BYTES_FOR_FLOOR:
                    unreadable += 1
                    continue
                chunks = funding_chunks(
                    readable_text(page, terms=_FUNDING_TERMS, select_only_over_cap=False)
                )
                meter = CostMeter()
                decisions = (
                    read_funding(
                        parser, claude, source_id=page.final_url, chunks=chunks, meter=meter
                    ).decisions
                    if chunks
                    else ()
                )
                judge_meter.add(meter)
                first = first_read_verdicts(page.json_extract, page.markdown)
                answers += int(first.returned)
                off_schema += int(first.off_schema)
                dropped += first.dropped
                rows.extend(claim_rows(host, page.final_url, decisions, first.verdicts))
                read += 1
        # Every json credit billed in the run, not answers x 4: the surcharge also
        # lands on the pages skipped above, and on both calls of an escalated shell.
        first_usd = spend.usd

        def per_page(usd: float) -> str:
            return f" -- ${usd / read:.4f} a page" if read else ""

        self.stdout.write(f"pages read by both: {read} (unreadable shells skipped: {unreadable})")
        self.stdout.write(f"judge: {judge_meter.line()}{per_page(judge_meter.usd)}")
        self.stdout.write(
            f"first read: {answers} answers, {off_schema} off-schema, {dropped} quotes not on "
            f"the page, {spend.credits} json credits billed, ${first_usd:.4f}{per_page(first_usd)}"
        )
        return rows

    def _fetch(
        self, fetch: Callable[[str], FetchedPage], host: str, url: str
    ) -> FetchedPage | None:
        """A readable page, or None with the reason on stderr -- never a raise."""
        try:
            page = fetch(url)
        except _FETCH_ERRORS as error:
            self.stderr.write(f"{host}: {url} raised {type(error).__name__}: {error}")
            return None
        if not page.ok:
            self.stderr.write(f"{host}: {url} {page.outcome} {page.reason}")
            return None
        return page
