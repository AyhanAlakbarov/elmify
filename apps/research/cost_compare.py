"""The per-page cost record of a funding read, and the comparison of two runs.

Item 15's rule is "measure before and after per changed page". A page is
keyed by `content_digest` -- what the reader would call the page -- so a run
over saved pages and a run over live ones still join on the pages that did
not change, and a page that did change is reported as unmatched rather than
compared against a different text.

Pure: files in, numbers out. Nothing here calls a model or the database.
"""

from __future__ import annotations

import csv
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .egress import FetchResult
from .harvest import content_digest
from .model_cost import CostMeter

VERDICT_COLUMNS = (
    "served", "agreed_unserved", "unagreed", "abstained", "noise", "disputed_offered",
)
TOKEN_COLUMNS = (
    "openai_input", "openai_cached", "openai_output",
    "claude_input", "claude_cache_read", "claude_cache_write", "claude_output",
)
COST_COLUMNS = (
    "host", "final_url", "content_sha256", "tier", "chunks", "calls", "lost", "unmetered",
    "unpriced", "flex_fallbacks", *TOKEN_COLUMNS, "usd", *VERDICT_COLUMNS,
)


def cost_row(
    *,
    host: str,
    page: FetchResult,
    chunks: int,
    meter: CostMeter,
    verdicts: Mapping[str, int],
    tier: str,
) -> dict[str, str]:
    openai, claude = meter.tokens("openai"), meter.tokens("claude")
    row = {
        "host": host,
        "final_url": page.final_url,
        "content_sha256": content_digest(page.body),
        "tier": tier,
        "chunks": str(chunks),
        "calls": str(len(meter.usages) + meter.unmetered),
        "lost": str(meter.lost),
        "unmetered": str(meter.unmetered),
        "unpriced": str(meter.unpriced),
        "flex_fallbacks": str(meter.flex_fallbacks),
        "openai_input": str(openai["input"]),
        "openai_cached": str(openai["cache_read"]),
        "openai_output": str(openai["output"]),
        "claude_input": str(claude["input"]),
        "claude_cache_read": str(claude["cache_read"]),
        "claude_cache_write": str(claude["cache_write"]),
        "claude_output": str(claude["output"]),
        "usd": f"{meter.usd:.6f}",
    }
    row.update({column: str(verdicts.get(column, 0)) for column in VERDICT_COLUMNS})
    return row


def write_cost_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_cost_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COST_COLUMNS:
            raise ValueError(f"{path} is not a funding cost CSV (header differs)")
        return list(reader)


@dataclass(frozen=True)
class Comparison:
    matched: int
    only_before: int
    only_after: int
    usd_before: float
    usd_after: float
    #: The median of after/before over matched pages that cost anything before.
    median_ratio: float | None
    tokens_before: dict[str, int]
    tokens_after: dict[str, int]
    verdicts_before: dict[str, int]
    verdicts_after: dict[str, int]
    unpriced: int
    #: Rows sharing a digest with an earlier row of the same run: two pages
    #: with identical text. Only the first is compared; the rest are counted.
    duplicates: int = 0
    #: Matched pages that cost nothing before, so no ratio: in the sums, not
    #: in the median.
    unratioed: int = 0

    def verdict_line(self) -> str:
        return "verdicts " + " ".join(
            f"{column}={self.verdicts_before[column]}->{self.verdicts_after[column]}"
            for column in VERDICT_COLUMNS
        )

    def lines(self) -> list[str]:
        saving = 1 - self.usd_after / self.usd_before if self.usd_before else None
        ratio = f"{self.median_ratio:.3f}" if self.median_ratio is not None else "n/a"
        out = [
            f"pages matched by content digest: {self.matched} "
            f"(only before: {self.only_before}, only after: {self.only_after})",
            f"usd before={self.usd_before:.4f} after={self.usd_after:.4f}"
            + (f" saving={saving:.1%}" if saving is not None else ""),
            f"median per-page ratio after/before: {ratio}"
            + (f" (over {self.matched - self.unratioed}; {self.unratioed} cost $0 before)"
               if self.unratioed else ""),
            "tokens " + " ".join(
                f"{column}={self.tokens_before[column]}->{self.tokens_after[column]}"
                for column in TOKEN_COLUMNS
            ),
            self.verdict_line(),
        ]
        if self.duplicates:
            out.append(
                f"note: {self.duplicates} rows repeat a digest already seen in their run "
                "(identical page text); each digest is compared once"
            )
        if self.unpriced:
            out.append(
                f"WARNING: {self.unpriced} unpriced readings -- the dollars are a floor, "
                "not a total; compare the token lines"
            )
        return out


def _by_digest(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    keyed: dict[str, dict[str, str]] = {}
    for row in rows:
        digest = row["content_sha256"]
        if digest and digest not in keyed:
            keyed[digest] = row
    return keyed


def compare(before: list[dict[str, str]], after: list[dict[str, str]]) -> Comparison:
    """Page by page, over the pages both runs read with identical text."""
    old, new = _by_digest(before), _by_digest(after)
    keys = [digest for digest in old if digest in new]
    ratios = [
        float(new[k]["usd"]) / float(old[k]["usd"]) for k in keys if float(old[k]["usd"]) > 0
    ]
    return Comparison(
        matched=len(keys),
        only_before=len(old.keys() - new.keys()),
        only_after=len(new.keys() - old.keys()),
        usd_before=sum(float(old[k]["usd"]) for k in keys),
        usd_after=sum(float(new[k]["usd"]) for k in keys),
        median_ratio=statistics.median(ratios) if ratios else None,
        tokens_before={c: sum(int(old[k][c]) for k in keys) for c in TOKEN_COLUMNS},
        tokens_after={c: sum(int(new[k][c]) for k in keys) for c in TOKEN_COLUMNS},
        verdicts_before={c: sum(int(old[k][c]) for k in keys) for c in VERDICT_COLUMNS},
        verdicts_after={c: sum(int(new[k][c]) for k in keys) for c in VERDICT_COLUMNS},
        unpriced=sum(int(old[k]["unpriced"]) + int(new[k]["unpriced"]) for k in keys),
        duplicates=_repeats(before) + _repeats(after),
        unratioed=len(keys) - len(ratios),
    )


def _repeats(rows: list[dict[str, str]]) -> int:
    digests = [row["content_sha256"] for row in rows if row["content_sha256"]]
    return len(digests) - len(set(digests))
