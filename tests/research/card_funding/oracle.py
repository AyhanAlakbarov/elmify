"""A scripted reader stack for the funding tests: no model is ever called.

`Oracle(answers)` answers every question it is asked from `answers` (question id -> (value,
quote)); anything not scripted gets the question's absence option. A proposal id maps to a list of
quotes. `split` names questions on which the two cheap readers disagree, so the decider answers
them; `silent` names questions nobody answers, which the engine records as unresolved.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping

from apps.research.card_engine.readers import Attempt, Reply


class Oracle:
    def __init__(self, answers: Mapping[str, object] | None = None, *, split: Iterable[str] = (),
                 silent: Iterable[str] = (), cost: float = 0.0001, latency: float = 0.1):
        self.answers = dict(answers or {})
        self.split, self.silent = set(split), set(silent)
        self.cost, self.latency = cost, latency
        self.asked: list[tuple[str, list[str]]] = []
        self.lock = threading.Lock()

    def __call__(self, spec, prompt) -> Attempt:
        questions = json.loads(prompt.ask)["questions"]
        with self.lock:
            self.asked.append((spec.name, [q["id"] for q in questions]))
        out = []
        for q in questions:
            qid = q["id"]
            if qid in self.silent:
                continue
            if q["options"] == ["quote"]:
                out += [{"id": qid, "value": "quote", "quote": text}
                        for text in self.answers.get(qid, [])  # type: ignore[union-attr]
                        if text in prompt.data]
                continue
            value, quote = self.answers.get(qid, (q["no_quote_for"][0], ""))  # type: ignore[misc]
            if quote and quote not in prompt.data:
                value, quote = q["no_quote_for"][0], ""
            if qid in self.split and spec.name == "luna":
                value, quote = q["no_quote_for"][0], ""
            out.append({"id": qid, "value": value, "quote": quote})
        reply = Reply.model_validate({"answers": out})
        return Attempt(reply, "", self.cost, self.latency)

    def ids(self, reader: str = "deepseek") -> list[str]:
        return [qid for name, ids in self.asked if name == reader for qid in ids]
