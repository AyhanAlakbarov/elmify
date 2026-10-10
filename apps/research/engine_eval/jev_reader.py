"""Jev through the decision layer, record=False, sized against the measured 32k limit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.research.decisions import Answer, Client, Question, _estimate_tokens, ask

from .chat import Spend
from .evidence import amounts
from .items import Item
from .questions import LINE_QUESTIONS, jev_amount_choice, jev_noul

DECISION = "engine_eval"


def jev_cost_usd(tokens: int) -> float:
    return tokens * 0.042 / 1e6


def _p_yes(answer: Answer) -> float:
    return float(answer.probabilities.get(
        "true", answer.confidence if answer.value else 1 - answer.confidence))


def _request(chunk: list[Item], wording: str) -> tuple[dict[str, Any], dict[str, Question]]:
    state: dict[str, Any] = {"lines": {}, "amounts": {}}
    questions: dict[str, Question] = {}
    for item in chunk:
        state["lines"][item.id] = {"heading": item.heading, "text": item.text}
        for q in LINE_QUESTIONS:
            questions[f"{item.id}|{q.id}"] = jev_noul(q, item.id, wording)
        for k, span in enumerate(amounts(item.text)):
            aid = f"{item.id}_m{k}"
            state["amounts"][aid] = span
            questions[f"amt|{aid}|fwd"] = jev_amount_choice(aid, wording, reverse=False)
            questions[f"amt|{aid}|rev"] = jev_amount_choice(aid, wording, reverse=True)
    return state, questions


def _chunks(items: list[Item], wording: str, max_tokens: int) -> list[list[Item]]:
    chunks: list[list[Item]] = [[]]
    for item in items:
        trial = chunks[-1] + [item]
        if chunks[-1] and _estimate_tokens(*_request(trial, wording)) > max_tokens:
            chunks.append([item])
        else:
            chunks[-1] = trial
    return [c for c in chunks if c]


def read_jev(items: list[Item], *, wording: str, client: Client | None = None,
             max_tokens: int = 30_000, spend: Spend | None = None) -> dict[str, dict[str, Any]]:
    """Per item: question id -> P(yes), plus `_amounts` -> amount id -> value/conf/agree."""
    by_page: dict[str, list[Item]] = {}
    for item in items:
        by_page.setdefault(item.page, []).append(item)
    out: dict[str, dict[str, Any]] = {}
    for page_items in by_page.values():
        for chunk in _chunks(page_items, wording, max_tokens):
            state, questions = _request(chunk, wording)
            if spend is not None:
                spend.check()
            try:
                answers: Mapping[str, Answer] = ask(state, questions, decision=DECISION,
                                                    record=False, client=client)
            except Exception:
                if spend is not None:  # the request may have been billed before it failed
                    spend.add(jev_cost_usd(_estimate_tokens(state, questions)))
                raise
            if spend is not None:  # the request's tokens sit on its first answer only
                spend.add(jev_cost_usd(sum(a.input_tokens for a in answers.values())))
            for item in chunk:
                row: dict[str, Any] = {
                    q.id: _p_yes(answers[f"{item.id}|{q.id}"]) for q in LINE_QUESTIONS}
                row["_amounts"] = {}
                for aid in (a for a in state["amounts"] if a.startswith(f"{item.id}_m")):
                    fwd, rev = answers[f"amt|{aid}|fwd"], answers[f"amt|{aid}|rev"]
                    options = set(fwd.probabilities) | set(rev.probabilities)
                    avg = {o: (fwd.probabilities.get(o, 0.0) + rev.probabilities.get(o, 0.0)) / 2
                           for o in options}
                    value = max(avg, key=avg.__getitem__)
                    row["_amounts"][aid] = {"value": value, "conf": avg[value],
                                            "agree": fwd.value == rev.value}
                out[item.id] = row
    return out
