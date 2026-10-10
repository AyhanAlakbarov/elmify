"""Measure the mail decision reader and learn its bars (dashboard spec §4).

    uv run python manage.py decision_eval seed  --run dm-1 [--extra templates.csv]
    uv run python manage.py decision_eval read  --run dm-1 --wording a [--max-usd 1]
    uv run python manage.py decision_eval score --run dm-1

`seed` writes one research.GoldItem per letter per question (kind decision_mail)
for the owner to check in /platform/gold/; the claim is the expected answer.
`read` asks Jev once per letter (record=False) and saves the answers under
.superpowers/engine-eval/<run>/. `score` splits letters into tune and score
halves by hash, learns each gated question's bar with engine_eval.score.ltt_bar
at its delta (decision_questions.DELTAS), and reports precision, coverage and the
95% upper error on the score half, per wording, with the zero-error row counts
and the spend. Rows count as truth when the owner labelled them correct (or
wrong, with a fix); --trust-corpus uses the corpus labels instead, for a
development run that certifies nothing. Synthetic and published-template letters
only: no student's mail is ever written to GoldItem, a platform table.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.mailbox.decision_questions import DECISION, DELTAS, GATED, questions
from apps.research.decisions import Answer, Client, ask
from apps.research.engine_eval.items import RUNS
from apps.research.engine_eval.jev_reader import jev_cost_usd
from apps.research.engine_eval.score import ltt_bar, upper_error, zero_error_rows_needed
from apps.research.models import GoldItem

CORPUS = Path(__file__).resolve().parents[4] / "tests" / "mailbox" / "decision_corpus.json"
#: None reaches Jev through the decision layer; a test swaps in a fake.
CLIENT: Client | None = None


def _truths(row: dict[str, Any]) -> dict[str, Any]:
    funding = bool(row["funding"])
    out: dict[str, Any] = {
        "is_decision": row["is_decision"], "outcome": row["outcome"],
        "other_programme": row["offer"],
        **{qid: row["outcome"] == qid.split(":")[1] for qid in GATED if qid.startswith("gate:")},
    }
    if funding:
        out["funding"] = row["funding_outcome"]
        out.update({qid: row["funding_outcome"] == qid.split(":")[1]
                    for qid in GATED if qid.startswith("fgate:")})
    return out


def _context(row: dict[str, Any]) -> str:
    return json.dumps({k: row[k] for k in ("sender_domain", "programme", "university", "funding",
                                           "id", "case")}, sort_keys=True)


class Command(BaseCommand):
    help = "Seed, read and score the mail decision reader."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("step", choices=["seed", "read", "score"])
        parser.add_argument("--run", required=True)
        parser.add_argument("--wording", choices=["a", "b"], default="a")
        parser.add_argument("--max-usd", type=float, default=1.0)
        parser.add_argument("--extra", default="", help="CSV of published templates, corpus shape")
        parser.add_argument("--trust-corpus", action="store_true")

    def handle(self, *args: object, **opts: Any) -> None:
        getattr(self, f"_{opts['step']}")(opts)

    def _rows(self, opts: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = json.loads(CORPUS.read_text(encoding="utf-8"))
        if opts["extra"]:
            with open(opts["extra"], encoding="utf-8") as handle:
                rows += [
                    {**r, **{k: r[k] == "true" for k in ("is_decision", "offer")}}
                    for r in csv.DictReader(handle)
                ]
        return rows

    def _seed(self, opts: dict[str, Any]) -> None:
        created = 0
        for row in self._rows(opts):
            for qid, truth in _truths(row).items():
                _, made = GoldItem.objects.get_or_create(
                    run=opts["run"], purpose=GoldItem.Purpose.IMPROVEMENT, round=1, question=qid,
                    page_url=f"https://synthetic.invalid/decision-mail/{row['id']}",
                    line_sha256=hashlib.sha256(row["body"].encode()).hexdigest(),
                    defaults={"kind": GoldItem.Kind.DECISION_MAIL, "language": row["language"],
                              "line_text": row["body"], "heading": _context(row),
                              "claim": json.dumps(truth)},
                )
                created += int(made)
        self.stdout.write(f"seeded {created} gold rows for {opts['run']}")

    def _letters(self, opts: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Per letter: its context, body and the truth per question."""
        letters: dict[str, dict[str, Any]] = {}
        for item in GoldItem.objects.filter(run=opts["run"], kind=GoldItem.Kind.DECISION_MAIL):
            if item.verdict == GoldItem.Verdict.CORRECT or opts["trust_corpus"]:
                truth = json.loads(item.claim)
            elif item.verdict == GoldItem.Verdict.WRONG and item.fix:
                truth = json.loads(item.fix)
            else:
                continue
            letter = letters.setdefault(item.line_sha256, {
                "context": json.loads(item.heading), "body": item.line_text,
                "language": item.language, "truth": {},
            })
            letter["truth"][item.question] = truth
        return letters

    def _read(self, opts: dict[str, Any]) -> None:
        out_dir = RUNS / opts["run"]
        out_dir.mkdir(parents=True, exist_ok=True)
        answers: dict[str, Any] = {}
        tokens = 0
        for key, letter in self._letters(opts).items():
            if jev_cost_usd(tokens) >= opts["max_usd"]:
                raise CommandError(f"spend cap {opts['max_usd']} USD reached")
            c = letter["context"]
            state = {"email": {"from_domain": c["sender_domain"], "body": letter["body"]},
                     "application": {"programme": c["programme"], "university": c["university"],
                                     **({"funding": c["funding"]} if c["funding"] else {})}}
            got: dict[str, Answer] = ask(
                state, questions(opts["wording"], funding=bool(c["funding"])),
                decision=DECISION, record=False, client=CLIENT,
            )
            tokens += sum(a.input_tokens for a in got.values())
            answers[key] = {qid: {"value": a.value, "p": a.probabilities} for qid, a in got.items()}
        (out_dir / f"jev-{opts['wording']}.json").write_text(
            json.dumps({"answers": answers, "tokens": tokens}, default=str)
        )
        self.stdout.write(f"read {len(answers)} letters, {tokens} tokens, "
                          f"{jev_cost_usd(tokens):.6f} USD")

    def _score(self, opts: dict[str, Any]) -> None:
        out_dir = RUNS / opts["run"]
        letters = self._letters(opts)
        lines = [f"# decision_eval {opts['run']}", "",
                 f"zero-error rows needed: {zero_error_rows_needed(0.01):,} (1/100), "
                 f"{zero_error_rows_needed(0.002):,} (1/500)", ""]
        for wording in ("a", "b"):
            path = out_dir / f"jev-{wording}.json"
            if not path.exists():
                continue
            saved = json.loads(path.read_text())
            lines += [f"## wording {wording} — {jev_cost_usd(saved['tokens']):.6f} USD", "",
                      "| question | bar | accepted (score half) | wrong | coverage "
                      "| 95% upper error |",
                      "|---|---|---|---|---|---|"]
            bars: dict[str, float | None] = {}
            for qid in GATED:
                pairs: dict[str, list[tuple[float, bool]]] = {"tune": [], "score": []}
                for key, letter in letters.items():
                    got = saved["answers"].get(key, {}).get(qid)
                    if got is None or qid not in letter["truth"]:
                        continue
                    half = "tune" if int(key, 16) % 2 == 0 else "score"
                    p_yes = float(got["p"].get("true", 0.0))
                    pairs[half].append((p_yes, bool(letter["truth"][qid])))
                bar = ltt_bar([p for p in pairs["tune"] if p[0] >= 0.5], DELTAS[qid])
                bars[qid] = bar
                accepted = [t for s, t in pairs["score"] if bar is not None and s >= bar]
                wrong = sum(1 for t in accepted if not t)
                positives = sum(1 for _s, t in pairs["score"] if t) or 1
                lines.append(
                    f"| {qid} | {bar} | {len(accepted)} | {wrong} | "
                    f"{(len(accepted) - wrong) / positives:.2f} | "
                    f"{upper_error(wrong, len(accepted)):.4f} |"
                )
            lines += ["", "```python", f"BARS = {json.dumps(bars, indent=4)}", "```", ""]
        (out_dir / "report.md").write_text("\n".join(lines))
        self.stdout.write(str(out_dir / "report.md"))
