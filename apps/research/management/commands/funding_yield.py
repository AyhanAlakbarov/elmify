"""The 58-host re-run as a command -- gate 3.4 of the funder-reader design.

The measurement of 2026-09-18 found **2 awards served over 58 funder hosts**,
neither from a funder, with the richest scholarship pages producing the most
pointers. That run lived in a session scratchpad. This command is the same
thing made permanent: same hosts, same pages, same serve rule, so the number
after the holder axis is comparable to the number before it and the next
person does not rebuild the harness.

**It is also item 15's cost instrument.** Every reading's recorded tokens are
priced (apps.research.model_cost) and, with --cost-csv, written one row per
page keyed by content digest; --save-pages / --load-pages make two runs read
the same bytes, so `manage.py funding_cost_compare` measures a change to the
READING and nothing else.

Pure: nothing here writes a catalog row. The serve rule is imported from the
writer rather than restated, because a tally that computed its own would
measure something the product does not do.
"""

from __future__ import annotations

import base64
import csv
import json
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import anthropic
from django.core.management.base import BaseCommand, CommandError, CommandParser
from openai import OpenAI

from apps.funding.card import card_fill, card_values
from apps.research.batch_reading import BatchClients, PageRead, read_funding_batched
from apps.research.cost_compare import cost_row, write_cost_csv
from apps.research.discovery import retrieve_official_source
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.extraction import MessagesAPI, ResponsesAPI
from apps.research.fetch import CATALOG_ROLE_NOTE
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.funding_judge import (
    FundingDecision,
    FundingReadResult,
    Line,
    funding_chunks,
    read_funding,
)
from apps.research.funding_reader import _FUNDING_TERMS, _benefit_kinds, card_of
from apps.research.model_cost import FLEX_TIMEOUT_SECONDS, CostMeter, ReadingTier
from apps.research.reader import _MIN_BYTES_FOR_FLOOR, _MIN_READABLE_CHARS, readable_text
from apps.research.search import funding_links
from apps.research.services import DomainBusy

#: Every tier. BATCH fetches everything first, then reads in one batch per vendor.
_TIERS = tuple(tier.value for tier in ReadingTier)


def served_by_gate(decision: FundingDecision) -> bool:
    """The writer's serve rule, minus the lead (a measurement has no lead).

    `write_funding_decision` and `write_holder_decision` both additionally
    require `lead.can_support_claim`, which is true of every host read here:
    the list is funder and institution hosts, not catalogues.
    """
    return (
        decision.agreement == "AGREED"
        and decision.offered == "YES"
        and bool(_benefit_kinds(decision) or decision.money_form != "UNSTATED")
    )


@dataclass
class Tally:
    """What one page, one host or one tier produced."""

    pages: int = 0
    served: int = 0
    agreed_unserved: int = 0
    unagreed: int = 0
    abstained: int = 0
    pointers: int = 0
    negations: int = 0
    #: The recall the agreement rule spends: a line one reading alone called
    #: funding, and a line the readings split on. Hand-checked, not tuned.
    noise: int = 0
    disputed_offered: int = 0
    #: Awards a negation decided -- the groups negations joined (spec 3.5.3).
    suspended: int = 0
    unreadable: int = 0
    refused: int = 0
    #: Pages served from an Internet Archive capture (rung 6) rather than read
    #: live. `retrieve_official_source` returns ARCHIVED as SERVED under the
    #: ORIGINAL url, so without this a capture up to a year old counts into
    #: this measurement as the funder's current page -- and this command
    #: writes no row, so the tally line is the only place it can show.
    archived: int = 0
    #: Pages a batch did not finish: submitted, and decided nothing (item 15).
    batch_missing: int = 0
    #: Which fields the readings actually split on. Without this an unagreed
    #: tally says only that nothing agreed, which is not a diagnosis.
    fields: Counter[str] = field(default_factory=Counter)
    names: list[str] = field(default_factory=list)
    pointer_names: list[str] = field(default_factory=list)
    #: "<field>=<state>" over SERVED decisions only (spec 10.4: discovery is
    #: measured on cards filled, and an unserved row is no card).
    cards: Counter[str] = field(default_factory=Counter)
    #: Copies a reading gave that were not on their line (Task 3).
    card_off_line: int = 0
    #: One row per served card field, for --cards-csv and the hand check.
    card_rows: list[dict[str, str]] = field(default_factory=list)
    #: Every reading these pages paid for (item 15).
    meter: CostMeter = field(default_factory=CostMeter)

    def record(self, read: FundingReadResult, page_url: str = "") -> None:
        self.pages += 1
        self.pointers += read.pointers
        self.negations += read.negations
        self.noise += read.noise
        self.pointer_names.extend(lead.name for lead in read.pointer_leads)
        for decision in read.decisions:
            self.fields.update(decision.disputed)
            self.card_off_line += decision.card_off_line
            if "offered" in decision.disputed:
                self.disputed_offered += 1
            if decision.suspension_quote:
                self.suspended += 1
            if served_by_gate(decision):
                self.served += 1
                self.names.append(f"{decision.name} [{decision.holder}/{decision.kind}]")
                card = card_of(decision)
                values = card_values(card)
                quotes = dict(card.quotes)
                for name, state in card_fill(card).items():
                    self.cards[f"{name}={state}"] += 1
                    self.card_rows.append({
                        "page_url": page_url, "award": decision.name, "field": name,
                        "state": state, "value": values[name],
                        "quote": next(
                            (q for key, q in quotes.items() if key.split(":")[0] == name), ""
                        ),
                    })
                for condition in decision.conditions:
                    # The same file carries the spec's "zero false eligibility"
                    # half of the 30-card check (8.8).
                    self.card_rows.append({
                        "page_url": page_url, "award": decision.name, "field": "condition",
                        "state": "FILLED",
                        "value": f"{condition.key} {condition.operator} {condition.value} "
                                 f"{condition.unit or ''}".strip(),
                        "quote": condition.quote,
                    })
            elif decision.agreement == "AGREED":
                self.agreed_unserved += 1
            elif decision.agreement == "UNAGREED":
                self.unagreed += 1
            else:
                self.abstained += 1

    def add(self, other: Tally) -> None:
        self.pages += other.pages
        self.served += other.served
        self.agreed_unserved += other.agreed_unserved
        self.unagreed += other.unagreed
        self.abstained += other.abstained
        self.pointers += other.pointers
        self.negations += other.negations
        self.noise += other.noise
        self.disputed_offered += other.disputed_offered
        self.suspended += other.suspended
        self.fields.update(other.fields)
        self.unreadable += other.unreadable
        self.refused += other.refused
        self.archived += other.archived
        self.batch_missing += other.batch_missing
        self.meter.add(other.meter)
        self.cards.update(other.cards)
        self.card_off_line += other.card_off_line
        self.card_rows.extend(other.card_rows)

    def verdicts(self) -> dict[str, int]:
        return {
            "served": self.served,
            "agreed_unserved": self.agreed_unserved,
            "unagreed": self.unagreed,
            "abstained": self.abstained,
            "noise": self.noise,
            "disputed_offered": self.disputed_offered,
        }

    def line(self) -> str:
        return (
            f"pages={self.pages} served={self.served} agreed-unserved={self.agreed_unserved} "
            f"unagreed={self.unagreed} abstained={self.abstained} pointers={self.pointers} "
            f"negations={self.negations} noise={self.noise} "
            f"disputed-offered={self.disputed_offered} suspended={self.suspended} "
            f"unreadable={self.unreadable} "
            f"archived={self.archived} "
            f"batch-missing={self.batch_missing} "
            f"refused={self.refused}"
            + (f" split-on={dict(self.fields.most_common())}" if self.fields else "")
            + (f" cards={dict(sorted(self.cards.items()))}" if self.cards else "")
            + f" off-line={self.card_off_line}"
        )


def read_hosts(path: Path) -> list[tuple[str, str]]:
    """`host`, or `host<TAB>tier<TAB>country`, one per line; `#` comments out."""
    rows: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        rows.append((parts[0].strip(), parts[1].strip() if len(parts) > 1 else "?"))
    return rows


def save_page(directory: Path, host: str, page: FetchResult) -> None:
    """One JSON file per page, numbered in fetch order.

    A later --load-pages run reads these exact bytes, so a cost comparison
    measures the reading, never a page that changed between two fetches.
    Public pages only; this directory is a scratch area, never the repo.
    """
    index = len(list(directory.glob("*.json")))
    record = {
        "host": host,
        "final_url": page.final_url,
        "content_type": page.content_type,
        "body": base64.b64encode(page.body).decode("ascii"),
        "markdown": str(getattr(page, "markdown", "")),
        "fetched_via": page.fetched_via,
        "captured_at": str(getattr(page, "captured_at", "")),
    }
    (directory / f"{index:05d}.json").write_text(json.dumps(record), encoding="utf-8")


def load_pages(directory: Path) -> dict[str, list[FetchResult]]:
    pages: dict[str, list[FetchResult]] = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        captured = str(record["captured_at"])
        pages.setdefault(str(record["host"]), []).append(
            FetchedPage(
                final_url=str(record["final_url"]),
                redirects=(),
                content_type=str(record["content_type"]),
                body=base64.b64decode(record["body"]),
                markdown=str(record["markdown"]),
                fetched_via=str(record["fetched_via"]),
                captured_at=captured,
                outcome=Outcome.ARCHIVED if captured else Outcome.FETCHED,
            )
        )
    return pages


class Command(BaseCommand):
    help = (
        "Read funder hosts for funding and tally the yield (gate 3.4) and its model cost "
        "(item 15). Writes no catalog row." + CATALOG_ROLE_NOTE
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--hosts", required=True)
        parser.add_argument("--pages", type=int, default=4)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--cards-csv", default="")
        parser.add_argument(
            "--reading-tier", choices=_TIERS, default=ReadingTier.STANDARD.value
        )
        parser.add_argument(
            "--cost-csv", default="", help="write one row per page read: tokens, dollars, verdicts"
        )
        parser.add_argument(
            "--save-pages", default="", help="keep every fetched page in this directory"
        )
        parser.add_argument(
            "--load-pages", default="", help="read the pages a --save-pages run kept; fetch nothing"
        )

    def handle(self, *_args: object, **options: object) -> None:
        rows = read_hosts(Path(str(options["hosts"])))
        pages = max(1, int(str(options["pages"])))
        if bool(options["dry_run"]):
            for host, tier in rows:
                self.stdout.write(f"{host}\t{tier}")
            self.stdout.write(f"would read {len(rows)} hosts, up to {pages} pages each")
            return
        if not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("OPENAI_API_KEY"):
            raise CommandError(
                "both keys are needed: an award is agreed only when two model families agree"
            )
        load, save = str(options["load_pages"]), str(options["save_pages"])
        if load and save:
            raise CommandError("--save-pages and --load-pages belong to two different runs")
        reading_tier = ReadingTier(str(options["reading_tier"]))
        # Flex waits for spare capacity by design; its guide raises the timeout.
        openai_client = (
            OpenAI(timeout=FLEX_TIMEOUT_SECONDS) if reading_tier is ReadingTier.FLEX else OpenAI()
        )
        anthropic_client = anthropic.Anthropic()
        save_dir = Path(save) if save else None
        if save_dir is not None:
            # A second run into the same directory would ADD its pages: every
            # page then loads twice and the cost total doubles in silence.
            if save_dir.exists() and any(save_dir.glob("*.json")):
                raise CommandError(f"{save_dir} already holds saved pages; use an empty directory")
            save_dir.mkdir(parents=True, exist_ok=True)
        cost_rows: list[dict[str, str]] = []
        # Through the vendor seam, not our own client: the gate re-measures the
        # JavaScript shells the vendor path already closed if it fetches the way
        # the 2026-09-18 run did (eligibility spec 5).
        totals = self._run(
            rows,
            pages=pages,
            parser=cast(ResponsesAPI, openai_client.responses),
            claude=cast(MessagesAPI, anthropic_client.messages),
            fetch=retrieve_official_source,
            tier=reading_tier,
            batch=(
                BatchClients(openai=openai_client, anthropic=anthropic_client)
                if reading_tier is ReadingTier.BATCH
                else None
            ),
            loaded=load_pages(Path(load)) if load else None,
            save_dir=save_dir,
            cost_rows=cost_rows,
        )
        if options["cards_csv"]:
            with Path(str(options["cards_csv"])).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=("page_url", "award", "field", "state", "value", "quote")
                )
                writer.writeheader()
                writer.writerows(totals.card_rows)
        if options["cost_csv"]:
            write_cost_csv(Path(str(options["cost_csv"])), cost_rows)
            self.stdout.write(f"wrote {len(cost_rows)} page rows to {options['cost_csv']}")

    def _run(
        self,
        rows: list[tuple[str, str]],
        *,
        pages: int,
        parser: ResponsesAPI,
        claude: MessagesAPI,
        fetch: Callable[..., FetchResult],
        tier: ReadingTier = ReadingTier.STANDARD,
        batch: BatchClients | None = None,
        loaded: dict[str, list[FetchResult]] | None = None,
        save_dir: Path | None = None,
        cost_rows: list[dict[str, str]] | None = None,
    ) -> Tally:
        if tier is ReadingTier.BATCH:
            if batch is None:
                raise CommandError("a batch run needs the batch clients")
            return self._run_batched(
                rows, pages=pages, fetch=fetch, batch=batch, loaded=loaded, save_dir=save_dir,
                cost_rows=cost_rows,
            )
        totals = Tally()
        per_label: dict[str, Tally] = {}
        for host, label in rows:
            host_tally = self._read_host(
                host, pages=pages, parser=parser, claude=claude, fetch=fetch, tier=tier,
                loaded=loaded, save_dir=save_dir, cost_rows=cost_rows,
            )
            self._report_host(host, label, host_tally)
            per_label.setdefault(label, Tally()).add(host_tally)
            totals.add(host_tally)
        return self._report_totals(rows, per_label, totals, tier)

    def _run_batched(
        self,
        rows: list[tuple[str, str]],
        *,
        pages: int,
        fetch: Callable[..., FetchResult],
        batch: BatchClients,
        loaded: dict[str, list[FetchResult]] | None,
        save_dir: Path | None,
        cost_rows: list[dict[str, str]] | None,
    ) -> Tally:
        """Fetch (or load) every host's pages, read them all in one batch per
        vendor, then report exactly as the synchronous run does.

        Every decided page goes through `_record`, as in `_run`, so the card
        rows --cards-csv writes and the cost rows --cost-csv writes are the
        same in both modes.
        """
        host_tallies: list[tuple[str, str, Tally]] = []
        queued: list[tuple[str, Tally, FetchResult, PageRead]] = []
        for host, label in rows:
            tally = Tally()
            for page in self._host_pages(
                host, pages=pages, fetch=fetch, tally=tally, loaded=loaded, save_dir=save_dir
            ):
                chunks = self._prepare(page, tally=tally)
                if chunks is not None:
                    request = PageRead(page.final_url, chunks, CostMeter())
                    queued.append((host, tally, page, request))
            host_tallies.append((host, label, tally))
        results = read_funding_batched(batch, [request for *_, request in queued])
        for (host, tally, page, request), read in zip(queued, results, strict=True):
            meter = request.meter or CostMeter()
            if read is None:
                tally.batch_missing += 1
                tally.meter.add(meter)  # paid for in part, decided nothing
                self.stderr.write(f"{host}: {page.final_url} -- unfinished by the batch")
                continue
            self._record(
                read, host=host, page=page, chunks=request.chunks, meter=meter, tally=tally,
                tier=ReadingTier.BATCH, cost_rows=cost_rows,
            )
        totals = Tally()
        per_label: dict[str, Tally] = {}
        for host, label, tally in host_tallies:
            self._report_host(host, label, tally)
            per_label.setdefault(label, Tally()).add(tally)
            totals.add(tally)
        return self._report_totals(rows, per_label, totals, ReadingTier.BATCH)

    def _report_host(self, host: str, label: str, tally: Tally) -> None:
        self.stdout.write(f"{host}\t{label}\t{tally.line()}")
        self.stdout.write(f"    cost: {tally.meter.line()}")
        for name in tally.names:
            self.stdout.write(f"    served: {name}")
        for name in tally.pointer_names:
            self.stdout.write(f"    pointer: {name}")

    def _report_totals(
        self,
        rows: list[tuple[str, str]],
        per_label: dict[str, Tally],
        totals: Tally,
        tier: ReadingTier,
    ) -> Tally:
        for label, tally in sorted(per_label.items()):
            self.stdout.write(f"tier {label}: {tally.line()}")
        self.stdout.write(f"TOTAL over {len(rows)} hosts: {totals.line()}")
        self.stdout.write(f"COST ({tier.value}): {totals.meter.line()}")
        return totals

    def _read_host(
        self,
        host: str,
        *,
        pages: int,
        parser: ResponsesAPI,
        claude: MessagesAPI,
        fetch: Callable[..., FetchResult],
        tier: ReadingTier = ReadingTier.STANDARD,
        loaded: dict[str, list[FetchResult]] | None = None,
        save_dir: Path | None = None,
        cost_rows: list[dict[str, str]] | None = None,
    ) -> Tally:
        tally = Tally()
        for page in self._host_pages(
            host, pages=pages, fetch=fetch, tally=tally, loaded=loaded, save_dir=save_dir
        ):
            self._read_page(
                page, tally=tally, parser=parser, claude=claude, tier=tier, host=host,
                cost_rows=cost_rows,
            )
        return tally

    def _host_pages(
        self,
        host: str,
        *,
        pages: int,
        fetch: Callable[..., FetchResult],
        tally: Tally,
        loaded: dict[str, list[FetchResult]] | None = None,
        save_dir: Path | None = None,
    ) -> list[FetchResult]:
        """The homepage plus up to pages-1 funding pages -- fetched, or loaded."""
        if loaded is not None:
            saved = loaded.get(host, [])
            if not saved:
                tally.refused += 1
                self.stderr.write(f"{host}: no saved pages")
            return saved
        home = None
        last = ""
        for scheme in ("https", "http"):
            try:
                home = fetch(f"{scheme}://{host}/")
                break
            except (SourceBlocked, DomainBusy, ValueError) as error:
                last = str(error)[:120]
        if home is None:
            tally.refused += 1
            self.stderr.write(f"{host}: refused ({last})")
            return []
        found = [home] + [
            page
            for url in funding_links(home)[: pages - 1]
            if (page := self._fetch_quietly(url, host, fetch)) is not None
        ]
        if save_dir is not None:
            for page in found:
                save_page(save_dir, host, page)
        return found

    def _fetch_quietly(
        self, url: str, host: str, fetch: Callable[..., FetchResult]
    ) -> FetchResult | None:
        try:
            return fetch(url)
        except (SourceBlocked, DomainBusy, ValueError) as error:
            self.stderr.write(f"{host}: {url} refused ({str(error)[:120]})")
            return None

    def _prepare(self, page: FetchResult, *, tally: Tally) -> list[tuple[Line, ...]] | None:
        """The page's chunks, or None when there is nothing to read."""
        if getattr(page, "captured_at", ""):
            # Counted before any readability verdict: whether the bytes came
            # from a capture is a fact about the fetch, not about the read.
            tally.archived += 1
        whole = readable_text(page, terms=None)
        if len(whole) < _MIN_READABLE_CHARS and len(page.body) >= _MIN_BYTES_FOR_FLOOR:
            tally.unreadable += 1  # a shell, never "this page states no funding"
            return None
        chunks = funding_chunks(
            readable_text(page, terms=_FUNDING_TERMS, select_only_over_cap=False)
        )
        if not chunks:
            tally.pages += 1
            return None
        return chunks

    def _read_page(
        self,
        page: FetchResult,
        *,
        tally: Tally,
        parser: ResponsesAPI,
        claude: MessagesAPI,
        tier: ReadingTier = ReadingTier.STANDARD,
        host: str = "",
        cost_rows: list[dict[str, str]] | None = None,
    ) -> None:
        chunks = self._prepare(page, tally=tally)
        if chunks is None:
            return
        meter = CostMeter()
        read = read_funding(
            parser, claude, source_id=page.final_url, chunks=chunks, meter=meter, tier=tier
        )
        self._record(
            read, host=host, page=page, chunks=chunks, meter=meter, tally=tally, tier=tier,
            cost_rows=cost_rows,
        )

    def _record(
        self,
        read: FundingReadResult,
        *,
        host: str,
        page: FetchResult,
        chunks: list[tuple[Line, ...]],
        meter: CostMeter,
        tally: Tally,
        tier: ReadingTier,
        cost_rows: list[dict[str, str]] | None,
    ) -> None:
        tally.record(read, page_url=page.final_url)
        tally.meter.add(meter)
        if cost_rows is not None:
            page_tally = Tally()
            page_tally.record(read, page_url=page.final_url)
            cost_rows.append(
                cost_row(
                    host=host, page=page, chunks=len(chunks), meter=meter,
                    verdicts=page_tally.verdicts(), tier=tier.value,
                )
            )
