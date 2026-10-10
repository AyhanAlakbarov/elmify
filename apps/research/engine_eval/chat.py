"""One OpenRouter chat call that returns closed labels with their probabilities.

The page is the first user message on its own, so OpenRouter's sticky routing and the host's prefix
cache see the same prefix for every question about one page (OpenRouter keys stickiness on the first
system and first non-system message). The probability of an answer is read at the token where its
value starts -- never at the first token that merely spells a label, because a key such as
`no_funding` begins with the token "no" (the 2026-10-03 spike's bug).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from apps.research.egress import fetch_json_api

URL = "https://openrouter.ai/api/v1/chat/completions"
TOP_LOGPROBS = 5
THINKING_MAX_TOKENS = 16000
UNMETERED_LIMIT = 3


class SpendCapReached(RuntimeError):
    """Raised before a paid call, never after one."""


class ChatFailed(RuntimeError):
    """Transport failure; the message names the type only (headers carry the key)."""


@dataclass
class Spend:
    cap_usd: float
    spent_usd: float = 0.0
    unmetered: int = 0  # consecutive calls that may have cost money and added none

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise SpendCapReached(f"spent {self.spent_usd:.4f} of {self.cap_usd:.2f} USD")

    def add(self, usd: float) -> None:
        self.spent_usd += usd
        self.unmetered = 0

    def add_unmetered(self) -> None:
        """A call that failed or came back without a cost: the cap is a lower bound until a
        metered call resets it, so three in a row mean the real spend is unknown (ruling R10)."""
        self.unmetered += 1
        if self.unmetered >= UNMETERED_LIMIT:
            raise SpendCapReached(f"{UNMETERED_LIMIT} consecutive unmetered calls: "
                                  f"the real spend is unknown (counted {self.spent_usd:.4f} USD)")


@dataclass(frozen=True)
class Reader:
    model: str
    host: str | None
    thinking: str = "off"


@dataclass(frozen=True)
class ChatAnswer:
    values: dict[str, str]
    probs: dict[str, dict[str, float] | None]
    cost_usd: float
    cached_tokens: int
    reasoning_tokens: int
    ok: bool
    reason: str = ""


def _stem(option: str) -> str:
    return re.split(r"[_\s-]", option, maxsplit=1)[0].lower()


def check_first_tokens(options: Sequence[str]) -> None:
    stems = [_stem(o) for o in options]
    for i, a in enumerate(stems):
        for b in stems[i + 1:]:
            # ponytail: two leading characters stand in for the tokenizer's first token ("not" vs
            # "none" both open with "no"); a real tokenizer check needs the host's vocabulary.
            if a[:2] == b[:2] or a.startswith(b) or b.startswith(a):
                raise ValueError(f"options share a first token: {options}")


def _body(reader: Reader, system: str, page: str, question: str,
          schema_props: dict[str, list[str]], session_id: str) -> dict[str, Any]:
    longest = max(len(o) for opts in schema_props.values() for o in opts)
    off = reader.thinking == "off"
    body: dict[str, Any] = {
        "model": reader.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": '<page untrusted="true">\n' + page + "\n</page>"},
            {"role": "user", "content": question},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "answer", "strict": True,
            "schema": {"type": "object", "additionalProperties": False,
                       "required": list(schema_props),
                       "properties": {k: {"type": "string", "enum": v}
                                      for k, v in schema_props.items()}}}},
        "temperature": 0,
        # A thinking reader needs room to reason and returns no probabilities (ruling R1).
        "max_tokens": 16 + len(schema_props) * (longest + 12) if off else THINKING_MAX_TOKENS,
        "session_id": session_id,
        "usage": {"include": True},
        "reasoning": {"enabled": False} if off else {"effort": reader.thinking},
    }
    if off:
        body["logprobs"] = True
        body["top_logprobs"] = TOP_LOGPROBS
    if reader.host:
        body["provider"] = {"only": [reader.host], "allow_fallbacks": False,
                            "require_parameters": True}
    return body


def _value_probs(content: str, tokens: list[dict[str, Any]], key: str,
                 options: Sequence[str]) -> dict[str, float] | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"', content)
    if not match or not tokens:
        return None
    pos, start = 0, match.end()
    for tok in tokens:
        if pos + len(tok["token"]) > start:
            mass: dict[str, float] = {}
            for alt in tok.get("top_logprobs", []):
                piece = alt["token"].strip().strip('"').lower()
                for option in options:
                    if piece and option.lower().startswith(piece):
                        mass[option] = mass.get(option, 0.0) + math.exp(alt["logprob"])
                        break
            total = sum(mass.values())
            return {o: mass.get(o, 0.0) / total for o in options} if total else None
        pos += len(tok["token"])
    return None


def chat_json(reader: Reader, *, system: str, page: str, question: str,
              schema_props: dict[str, list[str]], session_id: str, spend: Spend,
              post: Callable[..., dict[str, Any]] = fetch_json_api) -> ChatAnswer:
    spend.check()
    failed = False
    try:
        data = post(URL, payload=_body(reader, system, page, question, schema_props, session_id),
                    headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                    read_timeout=120)
    except Exception as error:  # noqa: BLE001 - the type only, never the message
        failed, name = True, type(error).__name__
    if failed:
        spend.add_unmetered()  # may raise SpendCapReached; outside the except so nothing chains
        raise ChatFailed(name)
    usage = data.get("usage") or {}
    cost = float(usage.get("cost") or 0.0)
    if usage.get("cost") is None:
        spend.add_unmetered()
    else:
        spend.add(cost)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content") or ""

    def unsure(reason: str) -> ChatAnswer:
        return ChatAnswer({}, {}, cost, cached, reasoning, ok=False, reason=reason)
    # Thinking was asked off, so reasoning means the host ignored it; a thinking reader reasons.
    if reasoning > 0 and reader.thinking == "off":
        return unsure("reasoning_tokens")
    if choice.get("finish_reason") != "stop" or not content:
        return unsure("not_stopped_or_empty")
    try:
        values = json.loads(content)
    except ValueError:
        return unsure("malformed")
    if set(values) != set(schema_props) or any(values[k] not in v for k, v in schema_props.items()):
        return unsure("off_schema")
    tokens = (choice.get("logprobs") or {}).get("content") or []
    probs = {k: _value_probs(content, tokens, k, v) for k, v in schema_props.items()}
    return ChatAnswer(values, probs, cost, cached, reasoning, ok=True)
