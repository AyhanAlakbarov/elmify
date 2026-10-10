"""Measure the decision engine's readers on real funding pages (spec 2026-10-03 §6, plan 1).

Paid: pages, key, read and probe spend money; `--max-usd` caps the OpenRouter and Jev total across
invocations (spend.json). `pages` also writes FetchAttempt rows through `fetch_page`, and its vendor
credits are bounded by `default_budget`, not by `--max-usd`. The other table written is
research.GoldItem (queue); nothing writes a DecisionRecord.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.research.engine_eval import chat_reader
from apps.research.engine_eval import items as items_mod
from apps.research.engine_eval import key as key_mod
from apps.research.engine_eval import score as score_mod
from apps.research.engine_eval.chat import Reader, Spend, SpendCapReached
from apps.research.engine_eval.evidence import evidence
from apps.research.engine_eval.firecrawl_reader import firecrawl_json_format, read_firecrawl
from apps.research.engine_eval.jev_reader import read_jev
from apps.research.engine_eval.probe import probe
from apps.research.engine_eval.questions import LINE_QUESTIONS, TIERS
from apps.research.fetch.types import FetchedPage
from apps.research.models import GoldItem

PAGES_CSV = Path(__file__).resolve().parents[4] / "docs" / "research" / "engine-eval-pages.csv"
BATCH = 25
# Any reader can stand second: round 1 measured Kimi K3 on 1,248 lines when Flash read 313.
SECONDS = ("ds_pro", "ds_flash", "kimi_k3", "gemini_flash", "firecrawl")


class Command(BaseCommand):
    help = "Measure Jev and the second/third readers; queue facts for the owner's gold check."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("step", choices=["pages", "key", "read", "probe", "queue", "score"])
        parser.add_argument("--run", required=True)
        parser.add_argument("--max-usd", type=float, default=25.0)
        parser.add_argument("--reader", default="jev",
                            help="jev, firecrawl (no paid call: reads the extracts `pages` stored) "
                                 "or a chat reader name")
        parser.add_argument("--wording", choices=["a", "b"], default="a")
        parser.add_argument("--host", default="")
        parser.add_argument("--purpose", choices=["improvement", "certification"],
                            default="improvement")
        parser.add_argument("--round", type=int, default=1)
        parser.add_argument("--per-kind", type=int, default=50)
        parser.add_argument("--provisional-bar", type=float, default=0.9)
        parser.add_argument("--only-unsettled", action="store_true",
                            help="third readers: only items the Jev + second pair leaves unsettled")

    def handle(self, *args: Any, **opts: Any) -> None:
        d = items_mod.run_dir(opts["run"])
        self._spend_file = d / "spend.json"
        spent = 0.0
        if self._spend_file.exists():
            spent = json.loads(self._spend_file.read_text())["usd"]
        spend = Spend(cap_usd=opts["max_usd"], spent_usd=spent)
        try:
            getattr(self, f"_{opts['step']}")(d, spend, opts)
        except SpendCapReached as stop:
            self.stdout.write(f"stopped: {stop}")
        finally:
            self._save_spend(spend)

    def _save_spend(self, spend: Spend) -> None:
        # after every batch too, so a killed run cannot overshoot the cap on resume
        self._spend_file.write_text(json.dumps({"usd": spend.spent_usd}))

    def _items(self, d: Path) -> list[items_mod.Item]:
        return [items_mod.Item(**r) for r in items_mod.load_jsonl(d / "items.jsonl")]

    def _load(self, d: Path, name: str, wording: str = "a") -> dict[str, Any]:
        path = d / f"reader-{name}-{wording}.json"
        loaded: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}
        return loaded

    def _pages(self, d: Path, spend: Spend, opts: Any) -> None:
        from apps.research.fetch import _default_providers, fetch_page
        from apps.research.fetch import firecrawl as firecrawl_module

        providers: dict[str, Callable[..., FetchedPage]] = {
            **_default_providers(),
            "firecrawl": partial(firecrawl_module.scrape, json_format=firecrawl_json_format()),
        }
        pages = items_mod.load_jsonl(d / "pages.jsonl")
        all_items = items_mod.load_jsonl(d / "items.jsonl")
        have = {p["url"] for p in pages}  # a page already paid for is never fetched again
        fetched_now = 0
        for n, row in enumerate(items_mod.read_page_set(PAGES_CSV)):
            if row.url in have:
                continue
            fetched = fetch_page(row.url, purpose="read", providers=providers)
            if fetched.ok:
                got, reason = items_mod.items_from_page(row, fetched, n)
            else:
                got, reason = [], f"not_served:{fetched.outcome}"
            pages.append({"url": row.url, "final_url": fetched.final_url, "language": row.language,
                          "scheme": row.scheme, "skip_reason": reason,
                          "text": "\n".join(f"{i.id}: {i.text}" for i in got),
                          "json_extract": dict(fetched.json_extract or {})})
            all_items += [asdict(i) for i in got]
            fetched_now += 1
            if fetched_now % BATCH == 0:
                items_mod.save_jsonl(d / "pages.jsonl", pages)
                items_mod.save_jsonl(d / "items.jsonl", all_items)
                self._save_spend(spend)
        items_mod.save_jsonl(d / "pages.jsonl", pages)
        items_mod.save_jsonl(d / "items.jsonl", all_items)
        counts: dict[str, int] = {}
        for i in all_items:
            counts[i["language"]] = counts.get(i["language"], 0) + 1
        self.stdout.write(f"lines per language: {counts}")
        for p in pages:
            if p["skip_reason"]:
                self.stdout.write(f"skipped {p['url']}: {p['skip_reason']}")

    def _key(self, d: Path, spend: Spend, opts: Any) -> None:
        path = d / "key.json"
        key = json.loads(path.read_text()) if path.exists() else {}
        todo = [i for i in self._items(d) if i.id not in key]
        totals: Counter[str] = Counter()
        try:
            # whole labeller calls per batch: 25 lines would end every batch in a 1-line call
            step = key_mod.LINES_PER_CALL * 4
            for start in range(0, len(todo), step):
                key.update(key_mod.build_key(todo[start:start + step], spend, stats=totals))
                path.write_text(json.dumps(key))
                self._save_spend(spend)
        finally:
            self.stdout.write(f"key: {len(key)} items, {dict(totals)}")

    def _read(self, d: Path, spend: Spend, opts: Any) -> None:
        name, wording = opts["reader"], opts["wording"]
        if name not in ("jev", "firecrawl") and name not in chat_reader.READERS:
            raise CommandError(f"unknown reader {name!r}")
        if name != "jev" and wording != "a" and not opts["only_unsettled"]:
            # a chat reader has one wording; its "-b" file is only the third reader picked
            # against jev-b, which is the file _rows reads for the jev-b sections
            raise CommandError("--wording b applies to jev, or to a third reader with "
                               "--only-unsettled")
        path = d / f"reader-{name}-{wording}.json"
        done = self._load(d, name, wording)
        todo = [i for i in self._items(d) if i.id not in done]
        if opts["only_unsettled"]:
            # As production would: a third reader is asked only where the pair is not both sure.
            second = self._load(d, "ds_pro") or self._load(d, "ds_flash")
            jev = self._load(d, "jev", wording)
            bar = opts["provisional_bar"]

            def settled(iid: str) -> bool:
                if (second.get(iid) or {}).get("_vote"):
                    return True  # both_or_third needs a measured second answer: a third cannot help
                for q in LINE_QUESTIONS:
                    a, b = (jev.get(iid) or {}).get(q.id), self._p(second, iid, q.id)
                    pair = score_mod.joint(a, b)
                    if a is None or b is None or pair is None:
                        return False
                    if not (pair >= bar or max(a, b) <= 1 - bar):
                        return False
                return True
            todo = [i for i in todo if not settled(i.id)]
        pages = {p["final_url"]: p for p in items_mod.load_jsonl(d / "pages.jsonl")}
        page_text = {url: p["text"] for url, p in pages.items()}
        extracts = {u: p["json_extract"] for u, p in pages.items() if p.get("json_extract")}
        # Saving after every batch is the recovery: a spend cap or a Jev outage mid-run keeps
        # everything read so far, and the error is not swallowed.
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            if name == "jev":
                done.update(read_jev(batch, wording=wording, spend=spend))
            elif name == "firecrawl":
                done.update(read_firecrawl(batch, extracts))
            else:
                done.update(chat_reader.read_chat(name, batch, spend, page_text=page_text))
            path.write_text(json.dumps(done))
            self._save_spend(spend)

    def _probe(self, d: Path, spend: Spend, opts: Any) -> None:
        if opts["reader"] not in chat_reader.READERS:
            raise CommandError(f"--reader must be one of {sorted(chat_reader.READERS)}")
        base = chat_reader.READERS[opts["reader"]]
        pair = Reader(base.model, opts["host"] or base.host, base.thinking)
        self.stdout.write(str(probe(pair, spend)))

    @staticmethod
    def _p(reader: dict[str, Any], iid: str, question: str) -> float | None:
        # a vote row holds 1.0/0.0 for a missing probability: certainty it never measured (R13)
        row = reader.get(iid) or {}
        return None if row.get("_vote") else row.get(question)

    def _rows(self, d: Path, second_name: str, wording: str = "a") -> list[dict[str, Any]]:
        items = {i.id: i for i in self._items(d)}
        key_path = d / "key.json"
        key = json.loads(key_path.read_text()) if key_path.exists() else {}
        jev, second = self._load(d, "jev", wording), self._load(d, second_name)
        # a third reader's file carries the Jev wording its unsettled set was picked against
        third: dict[str, Any] = next(
            (t for n in (os.environ.get("ENGINE_EVAL_THIRD", "kimi_k3"), "kimi_k3", "gemini_flash")
             if n != second_name and (t := self._load(d, n, wording))), {})
        return [{"id": iid, "language": it.language, "page": it.page, "half": it.half,
                 "question": q.id,
                 "truth": (key.get(iid) or {}).get(q.id), "jev": (jev.get(iid) or {}).get(q.id),
                 "second": self._p(second, iid, q.id),
                 "third": self._p(third, iid, q.id),
                 "evidence": evidence(q.id, it.text), "text": it.text, "heading": it.heading}
                for iid, it in items.items() for q in LINE_QUESTIONS]

    def _queue(self, d: Path, spend: Spend, opts: Any) -> None:
        half = "score" if opts["purpose"] == "improvement" else "cert"
        # the second reader that read the most lines decides what the owner checks
        second = max(("ds_pro", "ds_flash", "kimi_k3"), key=lambda n: len(self._load(d, n)))
        every = self._rows(d, second, opts["wording"])
        bars = score_mod.learn_bars(every, "both")
        # Round 1 has no learned bar yet (Learn-then-Test needs labelled data): a provisional
        # joint bar decides what the owner checks, and the report says so.
        accepted = []
        for r in every:
            if r["half"] != half:
                continue
            bar = bars.get((TIERS[r["question"]], r["evidence"]))
            if score_mod._accepted(r, "both", opts["provisional_bar"] if bar is None else bar):
                accepted.append(r)
        wording = {q.id: q.wording_a for q in LINE_QUESTIONS}
        rng = random.Random(f"{opts['run']}-{opts['purpose']}-{opts['round']}")  # nosec B311
        by_kind: dict[str, list[dict[str, Any]]] = {}
        unsafe = created = existing = 0
        for r in accepted:
            # the checking page renders page_url as a link: only http(s) ever reaches it
            if not r["page"].startswith(("https://", "http://")):
                unsafe += 1
                continue
            by_kind.setdefault(TIERS[r["question"]], []).append(r)
        for kind, kind_rows in by_kind.items():
            rng.shuffle(kind_rows)
            per_lang: dict[str, list[dict[str, Any]]] = {}
            for r in kind_rows:
                per_lang.setdefault(r["language"], []).append(r)
            picked: list[dict[str, Any]] = []
            while len(picked) < opts["per_kind"] and any(per_lang.values()):
                for lang in sorted(per_lang):  # round-robin: stratified by language
                    if per_lang[lang] and len(picked) < opts["per_kind"]:
                        picked.append(per_lang[lang].pop())
            for r in picked:
                _, was_created = GoldItem.objects.get_or_create(
                    run=opts["run"], purpose=opts["purpose"], round=opts["round"],
                    question=r["question"], page_url=r["page"],
                    line_sha256=hashlib.sha256(r["text"].encode()).hexdigest(),
                    defaults={"kind": kind, "language": r["language"], "heading": r["heading"],
                              "line_text": r["text"],
                              "claim": wording[r["question"]].format(p="this line")
                              + " Reader's answer: yes."})
                created += int(was_created)
                existing += int(not was_created)
        if half == "cert" and not any(i.half == "cert" for i in self._items(d)):
            self.stdout.write("no items with half 'cert' in this run: nothing to queue for "
                              "certification (build a fresh page set first)")
        self.stdout.write(
            f"queued for {opts['purpose']} round {opts['round']}: {created} created, "
            f"{existing} already existed; skipped {unsafe} with a non-http(s) page URL")

    def _score(self, d: Path, spend: Spend, opts: Any) -> None:
        results: dict[str, Any] = {}
        bars_out: dict[str, Any] = {}
        sweeps: dict[str, list[dict[str, Any]]] = {}
        wordings = [w for w in ("a", "b") if self._load(d, "jev", w)] or ["a"]
        for wording in wordings:
            for second_name in SECONDS:
                if not self._load(d, second_name):
                    continue
                rows = self._rows(d, second_name, wording)
                for policy in ("jev", "both", "both_or_third"):
                    name = f"{policy}/{second_name}/jev-{wording}"
                    bars = score_mod.learn_bars(rows, policy)
                    results[name] = score_mod.score_rows(rows, policy, bars)
                    bars_out[name] = bars
                    sweeps[name] = rows
        readers = (*SECONDS, os.environ.get("ENGINE_EVAL_THIRD", "kimi_k3"), "gemini_flash")
        votes = {f"{n}-{w}": sum(1 for r in self._load(d, n, w).values() if r.get("_vote"))
                 for n in readers for w in wordings if self._load(d, n, w)}
        certification = {}
        for kind in ("deadline", "eligibility", "money"):
            checked = GoldItem.objects.filter(
                run=opts["run"], purpose="certification", kind=kind).exclude(verdict="")
            gold = [(str(g.id), g.verdict == "correct") for g in checked]
            certification[kind] = score_mod.certify(gold, kind)
        text = score_mod.report(results, bars_out, certification, {"spent_total": spend.spent_usd},
                                sweeps, votes)
        (d / "report.md").write_text(text)
        self.stdout.write(str(d / "report.md"))
