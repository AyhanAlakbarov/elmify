"""Pages in, items out: one item per funding line, with its heading path and its half.

The half is decided by the page's FINAL url, so a listed URL that redirects to another listed page
cannot land in both halves (Review Focus 5). Lines come from the same cut the funding reader uses --
readable_text with the funding terms, then funding_lines -- so the harness measures the input the
reader will really get.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.research.fetch.types import FetchedPage
from apps.research.funding_judge import funding_lines
from apps.research.funding_reader import _FUNDING_TERMS
from apps.research.reader import readable_text

RUNS = Path(__file__).resolve().parents[3] / ".superpowers" / "engine-eval"
MAX_LINES_PER_PAGE = 80


@dataclass(frozen=True)
class PageRow:
    url: str
    language: str
    scheme: str


@dataclass(frozen=True)
class Item:
    id: str
    page: str
    language: str
    scheme: str
    half: str
    text: str
    heading: str


def read_page_set(path: Path) -> list[PageRow]:
    with path.open(encoding="utf-8") as handle:
        return [PageRow(r["url"], r["language"], r["scheme"]) for r in csv.DictReader(handle)]


def half_of(final_url: str, language: str) -> str:
    digest = hashlib.sha256(f"{language}|{final_url}".encode()).digest()
    return "tune" if digest[0] % 2 == 0 else "score"


def items_from_page(row: PageRow, fetched: FetchedPage, page_index: int) -> tuple[list[Item], str]:
    text = readable_text(fetched, terms=_FUNDING_TERMS)
    lines = [ln for ln in funding_lines(text) if len(ln.text.strip()) >= 15][:MAX_LINES_PER_PAGE]
    if not lines:
        return [], "no_lines"
    half = half_of(fetched.final_url, row.language)
    return [Item(id=f"p{page_index}l{n}", page=fetched.final_url, language=row.language,
                 scheme=row.scheme, half=half, text=ln.text.strip(), heading=ln.heading.strip())
            for n, ln in enumerate(lines)], ""


def run_dir(name: str) -> Path:
    path = RUNS / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

