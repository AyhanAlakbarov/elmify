"""Batch-API fakes for both vendors, answering like ScriptedReaders.

They read the request fields the real APIs read (an OpenAI JSONL line's
`body`, an Anthropic request's `params`) and pass them to the same scripted
reader the synchronous tests use, so a request shape these accept is the
shape tests/research/test_funding_cost_live.py then checks for real.
"""

import json
from types import SimpleNamespace

_OPENAI_USAGE = {
    "input_tokens": 31, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 17,
}
#: A reply that came back, was billed, and does not match the schema.
_OFF_SCHEMA = '{"verdicts": "not a list"}'


class FakeOpenAIBatches:
    """client.files + client.batches.

    `statuses`: what successive retrieves report. `drop`: custom_ids that never
    appear in any output (unfinished). `errors`: custom_ids answered non-200.
    `off_schema`: custom_ids answered 200 with an off-schema body (usage kept).
    """

    def __init__(self, script, *, statuses=("completed",), drop=(), errors=(), off_schema=()):
        self.script, self.statuses = script, list(statuses)
        self.drop, self.errors, self.off_schema = set(drop), set(errors), set(off_schema)
        self.uploads: list[list[dict]] = []
        self.deleted: list[str] = []
        self.cancelled: list[str] = []
        self._outputs: dict[str, str] = {}
        self._polls = 0
        self.files = SimpleNamespace(
            create=self._upload, content=self._content, delete=self.deleted.append
        )
        self.batches = SimpleNamespace(
            create=self._create, retrieve=self._retrieve, cancel=self.cancelled.append
        )

    def _upload(self, *, file, purpose):
        assert purpose == "batch"
        _name, payload = file
        self.uploads.append([json.loads(line) for line in payload.decode().splitlines()])
        return SimpleNamespace(id=f"file-in-{len(self.uploads)}")

    def _create(self, *, input_file_id, endpoint, completion_window):
        assert endpoint == "/v1/responses" and completion_window == "24h"
        lines = []
        for request in self.uploads[-1]:
            assert request["method"] == "POST" and request["url"] == endpoint
            custom_id = request["custom_id"]
            if custom_id in self.drop:
                continue
            if custom_id in self.errors:
                lines.append({"custom_id": custom_id, "response": {"status_code": 500, "body": {}}})
                continue
            answer = self.script.parse(**request["body"])
            text = (
                _OFF_SCHEMA if custom_id in self.off_schema
                else answer.output_parsed.model_dump_json()
            )
            body = {
                "status": "completed",
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }],
                "usage": _OPENAI_USAGE,
            }
            lines.append({"custom_id": custom_id, "response": {"status_code": 200, "body": body}})
        batch_id = f"batch-{len(self.uploads)}"
        self._outputs[f"out-{batch_id}"] = "\n".join(json.dumps(line) for line in lines)
        self._polls = 0
        return SimpleNamespace(id=batch_id)

    def _retrieve(self, batch_id):
        status = self.statuses[min(self._polls, len(self.statuses) - 1)]
        self._polls += 1
        done = status in {"completed", "expired", "cancelled", "failed"}
        return SimpleNamespace(
            id=batch_id, status=status,
            output_file_id=f"out-{batch_id}" if done else None, error_file_id=None,
        )

    def _content(self, file_id):
        return SimpleNamespace(text=self._outputs[file_id])


class FakeAnthropicBatches:
    """client.messages.batches.

    `expired`/`errored`: custom_ids given that result. `off_schema`: custom_ids
    that succeed with an off-schema message (usage kept).
    """

    def __init__(self, script, *, expired=(), errored=(), off_schema=(), polls_to_end=1):
        self.script = script
        self.expired, self.errored = set(expired), set(errored)
        self.off_schema = set(off_schema)
        self.polls_to_end = polls_to_end
        self.cancelled: list[str] = []
        self.requests: list[dict] = []
        self._polls = 0
        self.messages = SimpleNamespace(
            batches=SimpleNamespace(
                create=self._create, retrieve=self._retrieve, results=self._results,
                cancel=self.cancelled.append,
            )
        )

    def _create(self, *, requests):
        self.requests, self._polls = list(requests), 0
        return SimpleNamespace(id="msgbatch-1")

    def _retrieve(self, batch_id):
        self._polls += 1
        ended = self._polls >= self.polls_to_end
        return SimpleNamespace(id=batch_id, processing_status="ended" if ended else "in_progress")

    def _results(self, batch_id):
        for request in self.requests:
            custom_id = request["custom_id"]
            if custom_id in self.expired:
                yield SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="expired"))
                continue
            if custom_id in self.errored:
                yield SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="errored"))
                continue
            answer = self.script.parse(**request["params"])
            text = (
                _OFF_SCHEMA if custom_id in self.off_schema
                else answer.output_parsed.model_dump_json()
            )
            message = SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(
                    input_tokens=31, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                    output_tokens=17,
                ),
            )
            yield SimpleNamespace(
                custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=message)
            )
