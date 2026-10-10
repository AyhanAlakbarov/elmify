"""The gate spec 6.6 puts in front of any count: >= 95% on kind AND on
funds_students over a person-labelled set spanning two scripts, with the
abstain rate printed beside accuracy so a classifier that abstains its way to
95% is seen for what it is. Reads pages, calls the model, writes nothing.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand
from openai import OpenAI

from apps.ratelimit import rate_limited
from apps.research.classify import _USABLE, FrontierClassifier, HostClassifier
from apps.research.extraction import ResponsesAPI
from apps.research.fetch import fetch_page
from apps.research.reader import is_shell, readable_text


def _classifier() -> HostClassifier:
    return FrontierClassifier(cast(ResponsesAPI, OpenAI().responses))


def _read(domain: str) -> tuple[str, bytes]:
    page = fetch_page(f"https://{domain}/", purpose="read", tag="classifier-gate")
    if page.outcome not in _USABLE:
        return "", b""
    return readable_text(page, terms=None), page.body


class Command(BaseCommand):
    help = "Score the classifier against docs/research/host-kind-labels.csv; writes nothing."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--labels", default="docs/research/host-kind-labels.csv")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        with Path(options["labels"]).open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))[: options["limit"]]
        classifier = _classifier()
        run_id = uuid4()
        hits: Counter[tuple[str, str, bool]] = Counter()
        misses: list[str] = []
        abstained = unreadable = 0
        scored = 0
        for row in rows:
            text, body = _read(row["domain"])
            if not text or is_shell(text, body):
                unreadable += 1
                continue
            if rate_limited(
                "org-classify", run_id, limit=settings.ORG_CLASSIFY_RUN_LIMIT, window_seconds=3600
            ):
                self.stdout.write(f"rate limited after {scored}")
                break
            verdict = classifier.classify(domain=row["domain"], page_text=text)
            scored += 1
            if (
                verdict is None
                or verdict.funds_students is None
                or verdict.confidence < settings.ORG_CLASSIFY_MIN_P
            ):
                abstained += 1
                continue
            expected_funds = row["funds_students"] == "yes"
            checks = (
                ("kind", verdict.kind == row["kind"]),
                ("funds_students", verdict.funds_students == expected_funds),
            )
            for key, ok in checks:
                hits[(row["script"], key, ok)] += 1
                if not ok:
                    got = getattr(verdict, key)
                    misses.append(f"{row['domain']}: {key} expected {row[key]} got {got}")
        for key in ("kind", "funds_students"):
            right = sum(v for (_, k, ok), v in hits.items() if k == key and ok)
            decided = sum(v for (_, k, _), v in hits.items() if k == key)
            self.stdout.write(f"{key}: {right}/{decided} decided right")
        self.stdout.write(
            f"abstained: {abstained}/{len(rows)}  unreadable: {unreadable}/{len(rows)}"
        )
        for script in sorted({s for s, _, _ in hits}):
            kind_ok, kind_no = hits[(script, "kind", True)], hits[(script, "kind", False)]
            fs_ok, fs_no = (
                hits[(script, "funds_students", True)], hits[(script, "funds_students", False)]
            )
            self.stdout.write(
                f"{script}: kind {kind_ok}/{kind_ok + kind_no}, "
                f"funds_students {fs_ok}/{fs_ok + fs_no}"
            )
        for miss in misses:
            self.stdout.write(f"  miss {miss}")
