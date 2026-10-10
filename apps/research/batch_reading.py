"""Funding readings bought through the vendors' batch APIs (50% of list price).

Funding master spec §8.2 / §13: a reading nothing waits on may be batched.
The prompts are the synchronous judge's, byte for byte
(funding_judge.reading_prompts), and so is the decision (funding_judge.decide);
only the transport differs, and test_batch_reading pins that a batched read
decides exactly what a synchronous one does.

Two rules this module exists to keep:

- **A request the batch did not finish is MISSING, and a page with a missing
  reading is not decided at all** (`None` in the result). Returning it as a
  lost reading would write ABSTAINED rows and let
  `funding_reader.withdraw_unread` unserve awards the page still states. A
  request the vendor ANSWERED with an error is a lost reading, exactly as a
  synchronous call that raised is. A missing tie-break is the one exception:
  the tie stands, as it does when the tie-break is unpaid.
- **No database work happens here, and no caller may hold a transaction
  across `read_funding_batched`**: each batch may take up to
  `max_wait_seconds` (24 hours by default), and a tie-break batch submitted
  after the first two gets its own window, so a call can last twice that.

Metering follows the synchronous path (funding_judge._openai_reading /
_claude_reading, and fda7499): an answer that came back is billed whether or
not it parses, so its usage is recorded -- a batch body carries `usage` even
when its text is off-schema, which the synchronous SDK's parse() loses, so
here it is priced rather than merely counted `unmetered`. Only a request the
vendor answered with an error counts `lost`.

The files uploaded to OpenAI for a batch hold public page text and nothing
else, and they are deleted once the results are read.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# Private SDK helpers, used on purpose: they are what responses.parse(text_format=)
# and messages.parse(output_format=) call to build the wire body (openai 3.19,
# resources/responses/responses.py; anthropic 1.5, resources/messages/messages.py),
# so a batch request built with them is the synchronous request, not a copy of it.
from anthropic.lib._parse._transform import transform_schema
from django.conf import settings
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import TypeAdapter, ValidationError

from .extraction import privacy_safe_identifier
from .funding_judge import (
    _MAX_OUTPUT_TOKENS,
    FundingReadResult,
    FundingVerdicts,
    Line,
    claude_system,
    decide,
    needs_tie_break,
    reading_prompts,
    surviving,
    tie_break_data,
)
from .model_cost import CostMeter, anthropic_usage, openai_usage

logger = logging.getLogger(__name__)

#: What messages.parse(output_format=FundingVerdicts) sends as
#: `output_config.format`, built the way the installed SDK builds it: a batch
#: request cannot carry a pydantic type, so the schema is spelled out.
_CLAUDE_FORMAT = {
    "type": "json_schema",
    "schema": transform_schema(TypeAdapter(FundingVerdicts).json_schema()),
}
_OPENAI_DONE = frozenset({"completed", "failed", "expired", "cancelled"})
#: Two OpenAI phrasings and the Claude reading, in funding_judge.surviving's order.
_SLOTS = ("o1", "o2", "c")

#: custom_id -> (the reading, or None when it learned nothing; the raw response
#: to meter, or None when the vendor answered with an error). A request with
#: NO key is missing.
_Results = dict[str, tuple[FundingVerdicts | None, object | None]]


@dataclass(frozen=True)
class BatchClients:
    """Whole SDK clients: a batch needs files and batches, not only messages."""

    openai: Any
    anthropic: Any
    poll_seconds: float = 60.0
    #: Both vendors' own window is 24 hours; no ONE batch is waited on longer
    #: (a tie-break batch after the first two has its own window).
    max_wait_seconds: float = 24 * 3600.0
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class PageRead:
    """One page's chunks, and the meter its readings are charged to."""

    source_id: str
    chunks: list[tuple[Line, ...]]
    meter: CostMeter | None = None


def _custom_id(page: int, chunk: int, slot: str) -> str:
    # Anthropic accepts ^[a-zA-Z0-9_-]{1,64}$ only: no colons, no dots.
    return f"p{page}-c{chunk}-{slot}"


def _location(custom_id: str) -> tuple[int, int]:
    page, chunk, _slot = custom_id.split("-")
    return int(page[1:]), int(chunk[1:])


def openai_request(
    custom_id: str, *, instructions: str, data: str, source_id: str
) -> dict[str, Any]:
    """One /v1/responses batch line: what funding_judge._openai_reading sends."""
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": settings.OPENAI_EXTRACTION_MODEL,
            "input": [
                {"role": "developer", "content": instructions},
                {"role": "user", "content": data},
            ],
            "text": {"format": type_to_text_format_param(FundingVerdicts)},
            "safety_identifier": privacy_safe_identifier(source_id),
            "prompt_cache_key": privacy_safe_identifier(source_id),
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "store": False,
        },
    }


def anthropic_request(
    custom_id: str, *, instructions: str, data: str, source_id: str
) -> dict[str, Any]:
    """One Message Batches request: what funding_judge._claude_reading sends."""
    return {
        "custom_id": custom_id,
        "params": {
            "model": settings.ANTHROPIC_JUDGE_MODEL,
            "max_tokens": 2 * _MAX_OUTPUT_TOKENS,
            "system": claude_system(instructions),
            "messages": [{"role": "user", "content": data}],
            "output_config": {"format": _CLAUDE_FORMAT},
            "metadata": {"user_id": privacy_safe_identifier(source_id)},
        },
    }


def _openai_reading(body: Mapping[str, Any]) -> FundingVerdicts | None:
    """parsed_or_none's three outcomes, read off a batch output body."""
    if body.get("status") == "incomplete":
        return None  # a truncated verdict list would read as "these lines state nothing"
    for item in body.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "refusal":
                return None
            if part.get("type") == "output_text":
                try:
                    return FundingVerdicts.model_validate_json(part.get("text") or "")
                except ValidationError:
                    return None
    return None


def _claude_reading(message: Any) -> FundingVerdicts | None:
    """claude_parsed_or_none's rules: end_turn or nothing, then the schema."""
    if getattr(message, "stop_reason", None) != "end_turn":
        return None
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text":
            try:
                return FundingVerdicts.model_validate_json(block.text)
            except ValidationError:
                return None
    return None


def _wait(
    clients: BatchClients,
    started: float,
    retrieve: Callable[[], Any],
    done: Callable[[Any], bool],
) -> Any:
    """The finished batch, or None once max_wait_seconds have passed since submit.

    A poll that raises is "not known yet", never the end of the wait: one
    transient error in up to a day of polling must not discard every paid
    reading of the run.
    """
    current = _poll(retrieve)
    while current is None or not done(current):
        if clients.clock() - started > clients.max_wait_seconds:
            return None
        clients.sleep(clients.poll_seconds)
        current = _poll(retrieve)
    return current


def _poll(retrieve: Callable[[], Any]) -> Any:
    try:
        return retrieve()
    except Exception:  # transient: the deadline, not one error, ends the wait
        logger.warning("batch status poll failed; polling again", exc_info=True)
        return None


@dataclass
class _OpenAIBatch:
    clients: BatchClients
    requests: list[dict[str, Any]]
    upload_id: str = ""
    batch_id: str = ""
    started: float = 0.0

    def submit(self) -> _OpenAIBatch:
        if self.requests:
            payload = "\n".join(json.dumps(request) for request in self.requests).encode()
            self.upload_id = self.clients.openai.files.create(
                file=("funding-readings.jsonl", payload), purpose="batch"
            ).id
            try:
                self.batch_id = self.clients.openai.batches.create(
                    input_file_id=self.upload_id,
                    endpoint="/v1/responses",
                    completion_window="24h",
                ).id
            except Exception:
                self.abandon()  # never leave page text uploaded with no batch to read it
                raise
            self.started = self.clients.clock()
        return self

    def abandon(self) -> None:
        """Cancel a submitted batch and delete its upload; best effort."""
        if self.batch_id:
            try:
                self.clients.openai.batches.cancel(self.batch_id)
            except Exception:
                logger.warning("could not cancel openai batch %s", self.batch_id)
        if self.upload_id:
            try:
                self.clients.openai.files.delete(self.upload_id)
            except Exception:
                logger.warning("could not delete openai batch file %s", self.upload_id)

    def collect(self) -> _Results:
        if not self.requests:
            return {}
        files = [self.upload_id]
        try:
            batch = _wait(
                self.clients, self.started,
                lambda: self.clients.openai.batches.retrieve(self.batch_id),
                lambda current: current.status in _OPENAI_DONE,
            )
            if batch is None:
                self.clients.openai.batches.cancel(self.batch_id)
                logger.warning("openai batch %s outlived its wait; cancelled", self.batch_id)
                return {}
            if batch.status != "completed":
                logger.warning(
                    "openai batch %s ended %s: its unfinished requests are missing",
                    self.batch_id, batch.status,
                )
            results: _Results = {}
            for file_id in (batch.output_file_id, batch.error_file_id):
                if not file_id:
                    continue
                files.append(file_id)
                for raw in self.clients.openai.files.content(file_id).text.splitlines():
                    if not raw.strip():
                        continue
                    line = json.loads(raw)
                    response = line.get("response") or {}
                    body = response.get("body") or {}
                    if response.get("status_code") == 200:
                        # Answered and billed, parsed or not: the body is metered.
                        results[line["custom_id"]] = (_openai_reading(body), body)
                    elif batch.status == "completed":
                        # The vendor answered this request with an error: a lost reading.
                        results[line["custom_id"]] = (None, None)
                    # Otherwise it was unfinished when the batch expired: missing.
            return results
        finally:
            for file_id in files:
                try:
                    self.clients.openai.files.delete(file_id)
                except Exception:  # cleanup must never cost a batch that finished
                    logger.warning("could not delete openai batch file %s", file_id)


@dataclass
class _AnthropicBatch:
    clients: BatchClients
    requests: list[dict[str, Any]]
    batch_id: str = ""
    started: float = 0.0

    def submit(self) -> _AnthropicBatch:
        if self.requests:
            self.batch_id = self.clients.anthropic.messages.batches.create(
                requests=self.requests
            ).id
            self.started = self.clients.clock()
        return self

    def abandon(self) -> None:
        """Cancel a submitted batch; best effort."""
        if self.batch_id:
            try:
                self.clients.anthropic.messages.batches.cancel(self.batch_id)
            except Exception:
                logger.warning("could not cancel anthropic batch %s", self.batch_id)

    def collect(self) -> _Results:
        if not self.requests:
            return {}
        batches = self.clients.anthropic.messages.batches
        ended = _wait(
            self.clients, self.started,
            lambda: batches.retrieve(self.batch_id),
            lambda current: current.processing_status == "ended",
        )
        if ended is None:
            batches.cancel(self.batch_id)
            logger.warning("anthropic batch %s outlived its wait; cancelled", self.batch_id)
            return {}
        results: _Results = {}
        for entry in batches.results(self.batch_id):
            kind = entry.result.type
            if kind == "succeeded":
                # Answered and billed, parsed or not: the message is metered.
                message = entry.result.message
                results[entry.custom_id] = (_claude_reading(message), message)
            elif kind == "errored":
                results[entry.custom_id] = (None, None)
            # canceled / expired: missing.
        return results


def _meter(meter: CostMeter | None, slot: str, response: object | None) -> None:
    """`lost` only for an answered error; an answer without usage is `unmetered`
    (CostMeter.record(None)), exactly as on the synchronous path."""
    if meter is None:
        return
    if response is None:
        meter.lost += 1
    elif slot == "c":
        meter.record(anthropic_usage(response, model=settings.ANTHROPIC_JUDGE_MODEL, batch=True))
    else:
        meter.record(openai_usage(response, model=settings.OPENAI_EXTRACTION_MODEL, batch=True))


def read_funding_batched(
    clients: BatchClients,
    pages: list[PageRead],
    *,
    pay_for_tie_break: Callable[[], bool] | None = None,
) -> list[FundingReadResult | None]:
    """Every page's readings in one batch per vendor, then one tie-break batch.

    One entry per page, in order: its decisions, or None when any of its first
    three readings on any chunk was not finished by the batch.
    """
    openai_requests: list[dict[str, Any]] = []
    claude_requests: list[dict[str, Any]] = []
    for p, page in enumerate(pages):
        for c, chunk in enumerate(page.chunks):
            instructions, openai_data, claude_data = reading_prompts(chunk)
            for slot, data in zip(_SLOTS[:2], openai_data, strict=True):
                openai_requests.append(
                    openai_request(
                        _custom_id(p, c, slot), instructions=instructions, data=data,
                        source_id=page.source_id,
                    )
                )
            claude_requests.append(
                anthropic_request(
                    _custom_id(p, c, "c"), instructions=instructions, data=claude_data,
                    source_id=page.source_id,
                )
            )
    # Both submitted before either is awaited: the wall-clock is the slower
    # vendor's, not the sum of the two.
    openai_batch = _OpenAIBatch(clients, openai_requests).submit()
    try:
        claude_batch = _AnthropicBatch(clients, claude_requests).submit()
    except Exception:
        openai_batch.abandon()  # a half-submitted read is paid for and never read
        raise
    try:
        openai_answers = openai_batch.collect()
    except Exception:
        claude_batch.abandon()
        raise
    answers = {**openai_answers, **claude_batch.collect()}

    missing: set[int] = set()
    readings: dict[tuple[int, int], list[FundingVerdicts]] = {}
    for p, page in enumerate(pages):
        for c in range(len(page.chunks)):
            got: list[FundingVerdicts | None] = []
            for slot in _SLOTS:
                custom_id = _custom_id(p, c, slot)
                if custom_id not in answers:
                    missing.add(p)
                    continue
                reading, response = answers[custom_id]
                _meter(page.meter, slot, response)
                got.append(reading)
            if p not in missing:
                readings[(p, c)] = surviving(got, page.source_id)

    tie_breaks: list[dict[str, Any]] = []
    for (p, c), chunk_readings in readings.items():
        if p in missing or not needs_tie_break(pages[p].chunks[c], chunk_readings):
            continue
        if pay_for_tie_break is not None and not pay_for_tie_break():
            continue  # unpaid: the tie stands and the dispute goes to review
        chunk = pages[p].chunks[c]
        instructions, _, _ = reading_prompts(chunk)
        tie_breaks.append(
            openai_request(
                _custom_id(p, c, "t"), instructions=instructions, data=tie_break_data(chunk),
                source_id=pages[p].source_id,
            )
        )
    if tie_breaks:
        tie_answers = _OpenAIBatch(clients, tie_breaks).submit().collect()
        for request in tie_breaks:
            custom_id = str(request["custom_id"])
            if custom_id not in tie_answers:
                continue  # a missing tie-break leaves the tie standing, as an unpaid one does
            p, c = _location(custom_id)
            reading, response = tie_answers[custom_id]
            _meter(pages[p].meter, "t", response)
            if reading is not None:
                readings[(p, c)] = readings[(p, c)] + [reading]

    return [
        None
        if p in missing
        else decide(page.chunks, [readings[(p, c)] for c in range(len(page.chunks))])
        for p, page in enumerate(pages)
    ]
