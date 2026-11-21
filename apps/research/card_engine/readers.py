"""The reader stack as configuration, and the two transports that reach it (verified-catalog §5).

Two cheap readers through OpenRouter read every section; a deciding reader through the Anthropic
SDK answers only a split. Which models, which hosts and which decider is `settings.CARD_READERS`,
one setting every question set and every session reuses (§0.25); it stays provisional until owner
round 2 (§5.5). A re-pinned host or model is a re-certification (§5.5), which is why every
OpenRouter reader must name exactly one host.

Every call follows CLAUDE.md's LLM rules: page text travels as labelled DATA, the reply is
validated by a Pydantic model with `extra="forbid"`, output is capped at `MAX_OUTPUT_TOKENS`, and
nothing of the prompt or the reply is logged. Rate limiting and the one retry live in the engine.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import UUID

from django.conf import settings
from pydantic import BaseModel, ConfigDict, ValidationError

from apps.research.egress import SourceBlocked, fetch_json_api
from apps.research.extraction import MessagesAPI, claude_parsed_or_none
from apps.research.model_cost import anthropic_usage, usage_usd

from . import Call, Limit

URL = "https://openrouter.ai/api/v1/chat/completions"
#: One call answers every question about one section. 4,000 is about 25 answers with full
#: quotes; the spike's 8-card calls used under 400 (v2/api/costs.md), and the Anthropic SDK's
#: non-streaming wall is 21,333 (funding_judge._MAX_OUTPUT_TOKENS).
MAX_OUTPUT_TOKENS = 4_000
READ_TIMEOUT_S = 60.0


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    value: str
    quote: str


class Reply(BaseModel):
    """The measured reply shape (slice2-spike v2: 211/211 cards answered on both cheap readers)."""

    model_config = ConfigDict(extra="forbid")

    answers: list[Answer]


#: Sent as OpenRouter's strict json_schema. Hand-written and inline because a Pydantic schema
#: carries `$defs`/`$ref`, which the spike never sent through the hosts; a test pins it to `Reply`.
REPLY_SCHEMA: dict[str, object] = {
    "type": "object", "additionalProperties": False, "required": ["answers"],
    "properties": {"answers": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "value", "quote"],
        "properties": {"id": {"type": "string"}, "value": {"type": "string"},
                       "quote": {"type": "string"}}}}},
}


@dataclass(frozen=True)
class ReaderSpec:
    name: str
    transport: Literal["openrouter", "anthropic"]
    model: str
    host: str = ""  # OpenRouter provider tag; the only host this reader may be served by
    params: Mapping[str, object] = field(default_factory=dict)  # extra OpenRouter body fields


@dataclass(frozen=True)
class Stack:
    pair: tuple[ReaderSpec, ReaderSpec]
    decider: ReaderSpec


class StackMisconfigured(ValueError):
    """CARD_READERS names a reader the engine cannot run as written."""


#: Body fields the transport owns: a reader's params may add to the request, never replace these.
RESERVED_PARAMS = frozenset({"model", "messages", "response_format", "max_tokens", "usage",
                             "provider", "models", "route", "stream", "tools", "tool_choice"})


def _text(raw: Mapping[str, object], key: str, required: bool) -> str:
    value = raw.get(key, "")
    if value is None and not required:
        value = ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise StackMisconfigured(f"{raw.get('name')!r}: {key} must be a non-blank string")
    if not required and value and not value.strip():
        raise StackMisconfigured(f"{raw.get('name')!r}: {key} must be a non-blank string")
    return value


def _spec(raw: object) -> ReaderSpec:
    if not isinstance(raw, Mapping) or not {"name", "transport", "model"} <= set(raw):
        raise StackMisconfigured(f"a reader needs name, transport and model: {raw!r}")
    name, model = _text(raw, "name", True), _text(raw, "model", True)
    host = _text(raw, "host", False)
    transport = raw["transport"]
    if transport not in ("openrouter", "anthropic"):
        raise StackMisconfigured(f"{name}: unknown transport {transport!r}")
    params = raw.get("params") or {}
    if not isinstance(params, Mapping) or not all(isinstance(k, str) for k in params):
        raise StackMisconfigured(f"{name}: params must be an object")
    if clash := RESERVED_PARAMS & set(params):
        raise StackMisconfigured(f"{name}: params may not set {sorted(clash)}")
    spec = ReaderSpec(name, transport, model, host, dict(params))
    if spec.transport == "openrouter" and not spec.host:
        raise StackMisconfigured(f"{spec.name}: an OpenRouter reader is pinned to one host")
    if spec.transport == "anthropic" and (spec.host or spec.params):
        raise StackMisconfigured(f"{spec.name}: the Anthropic SDK takes no host or params")
    if "temperature" in spec.params and spec.model.startswith("openai/gpt-6-luna"):
        raise StackMisconfigured("gpt-6-luna returns 404 when temperature is sent (§5)")
    return spec


def stack(raw: object = None) -> Stack:
    """The configured stack, refused whole when any part is wrong -- never half a stack."""
    raw = settings.CARD_READERS if raw is None else raw
    if not isinstance(raw, Mapping):
        raise StackMisconfigured("CARD_READERS must be an object with pair and decider")
    pair = raw.get("pair")
    if not isinstance(pair, list) or len(pair) != 2:
        raise StackMisconfigured("the pair is exactly two readers")
    first, second = _spec(pair[0]), _spec(pair[1])
    decider = _spec(raw.get("decider"))
    if len({first.name, second.name, decider.name}) != 3:
        raise StackMisconfigured("reader names must be distinct")
    return Stack((first, second), decider)


class ReadersNotConfigured(RuntimeError):
    """A reader of the stack lacks its key. Raised before any call: a missing key is
    configuration, not a missing answer (else every question silently costs decider prices)."""

    calls: tuple[Call, ...] = ()


def require_keys(readers: Stack) -> None:
    """Refuse a stack whose pair or decider has no key, before anything is paid."""
    missing = sorted({
        spec.name for spec in (*readers.pair, readers.decider)
        if not (settings.OPENROUTER_API_KEY if spec.transport == "openrouter"
                else os.environ.get("ANTHROPIC_API_KEY"))
    })
    if missing:
        raise ReadersNotConfigured(f"no API key for reader(s): {', '.join(missing)}")


def run_limit(run_id: UUID | int) -> Limit:
    """A catalogue run's calls in an hour (the sweep, §0.28)."""
    return Limit("card-reader-run", run_id, settings.CARD_READER_RUN_CALLS_PER_HOUR, 3600)


def tenant_limit(tenant_id: UUID) -> Limit:
    """One tenant's on-demand reads in an hour (a typed programme, §3.3)."""
    return Limit("card-reader-tenant", tenant_id, settings.CARD_READER_TENANT_CALLS_PER_HOUR,
                 3600)


@dataclass(frozen=True)
class Prompt:
    system: str  # the rules and the set's criteria: identical for every call of one set
    data: str    # the section, wrapped as untrusted DATA
    ask: str     # the questions


@dataclass(frozen=True)
class Attempt:
    reply: Reply | None
    reason: str  # "" when reply is not None
    cost_usd: float | None
    latency_s: float


Post = Callable[..., dict[str, object]]


def openrouter(spec: ReaderSpec, prompt: Prompt, *, post: Post = fetch_json_api) -> Attempt:
    """One chat completion through OpenRouter, pinned to the reader's host, no fallbacks."""
    if not settings.OPENROUTER_API_KEY:
        return Attempt(None, "not_configured", None, 0.0)
    body: dict[str, object] = {
        **spec.params,  # first: _spec refuses any key the lines below set
        "model": spec.model,
        "messages": [{"role": "system", "content": prompt.system},
                     {"role": "user", "content": prompt.data},
                     {"role": "user", "content": prompt.ask}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "reply", "strict": True, "schema": REPLY_SCHEMA}},
        "max_tokens": MAX_OUTPUT_TOKENS,
        "usage": {"include": True},
        "provider": {"order": [spec.host], "allow_fallbacks": False, "require_parameters": True},
    }
    started = time.monotonic()
    try:
        data = post(URL, payload=body, read_timeout=READ_TIMEOUT_S,
                    headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"})
    except Exception as error:  # noqa: BLE001 - the type only: a message can echo headers
        # the type, plus the HTTP status when egress reports one ("api returned HTTP 429")
        blocked = isinstance(error, SourceBlocked)
        status = re.search(r"HTTP (\d{3})", str(error)) if blocked else None
        reason = f"failed:http_{status[1]}" if status else f"failed:{type(error).__name__}"
        return Attempt(None, reason, None, time.monotonic() - started)
    latency = time.monotonic() - started
    usage = data.get("usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    cost_usd = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else None
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not choices and "error" in data:
        return Attempt(None, "failed:provider_error", cost_usd, latency)
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        return Attempt(None, "truncated", cost_usd, latency)
    try:
        return Attempt(Reply.model_validate_json(str(content or "")), "", cost_usd, latency)
    except ValidationError:
        return Attempt(None, "off_schema", cost_usd, latency)


class _NoKey(Exception):
    pass


def _claude_messages(timeout: float = READ_TIMEOUT_S) -> MessagesAPI:
    import anthropic  # the key is read from ANTHROPIC_API_KEY by the SDK, never a setting

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise _NoKey
    # no SDK retries and a bounded wait: one counted call is one HTTP request
    return cast(MessagesAPI, anthropic.Anthropic(max_retries=0, timeout=timeout).messages)


def anthropic_reader(
    spec: ReaderSpec, prompt: Prompt, *, messages: Callable[[], MessagesAPI] = _claude_messages,
) -> Attempt:
    """The deciding reader through the Anthropic SDK, as every Claude call in this repo is made.

    The system block carries cache_control so a page's second split reuses the rules."""
    seen: list[object] = []
    started = time.monotonic()
    try:
        reply = claude_parsed_or_none(
            messages(), Reply, model=spec.model,
            system=[{"type": "text", "text": prompt.system,
                     "cache_control": {"type": "ephemeral"}}],
            data=f"{prompt.data}\n\n{prompt.ask}", identifier=f"card-reader:{spec.name}",
            max_tokens=MAX_OUTPUT_TOKENS, on_response=seen.append,
        )
    except _NoKey:
        return Attempt(None, "not_configured", None, 0.0)
    except Exception as error:  # noqa: BLE001 - the type only
        return Attempt(None, f"failed:{type(error).__name__}", None, time.monotonic() - started)
    latency = time.monotonic() - started
    response = seen[0] if seen else None
    usage = anthropic_usage(response, model=spec.model) if response is not None else None
    cost = usage_usd(usage) if usage is not None else None  # no price row -> None, never $0
    if reply is not None:
        return Attempt(reply, "", cost, latency)
    stop = getattr(response, "stop_reason", None)
    reason = "off_schema" if response is None or stop == "end_turn" else str(stop)
    return Attempt(None, "truncated" if reason == "max_tokens" else reason, cost, latency)


def call(spec: ReaderSpec, prompt: Prompt) -> Attempt:
    """The default transport for a reader."""
    return openrouter(spec, prompt) if spec.transport == "openrouter" else anthropic_reader(
        spec, prompt)


def section_json(payload: Mapping[str, object]) -> str:
    """Page DATA, labelled as such: the reader's system rules say everything inside is data."""
    body = re.sub(
        r"</section\s*>", "", json.dumps(payload, ensure_ascii=False), flags=re.IGNORECASE
    )
    return '<section untrusted="true">\n' + body + "\n</section>"
