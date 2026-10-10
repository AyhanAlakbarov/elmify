"""A batched read sends the synchronous bytes and decides what the synchronous read decides."""

import itertools
import json
import re

from anthropic.lib._parse._transform import transform_schema
from openai.lib._parsing._responses import type_to_text_format_param
from pydantic import TypeAdapter

from apps.research.batch_reading import (
    BatchClients,
    PageRead,
    anthropic_request,
    openai_request,
    read_funding_batched,
)
from apps.research.funding_judge import FundingVerdicts, Line, judge, read_funding, reading_prompts
from apps.research.model_cost import CostMeter
from tests.research.batch_fakes import FakeAnthropicBatches, FakeOpenAIBatches
from tests.research.conftest import FakeResponse, FakeResponses, ScriptedReaders

CHUNK = (
    Line("Scholarships", ""),
    Line("All admitted international students receive a 50% tuition waiver.", "Scholarships"),
)
OTHER = (
    Line("Funding", ""),
    Line("Every student is paid a monthly stipend of 900 euros.", "Funding"),
)
_WAIVER, _STIPEND = "tuition waiver.", "900 euros."
_SCRIPT = {_WAIVER: {}, _STIPEND: {"kind": "I3_STIPEND_OR_ASSISTANTSHIP"}}


def _clients(openai, anthropic, **over):
    return BatchClients(
        openai=openai, anthropic=anthropic, poll_seconds=0, sleep=lambda _s: None, **over
    )


def _fakes(openai_over=None, **anthropic_over):
    return (
        FakeOpenAIBatches(ScriptedReaders(_SCRIPT), **(openai_over or {})),
        FakeAnthropicBatches(ScriptedReaders(_SCRIPT), **anthropic_over),
    )


def test_batch_requests_carry_the_synchronous_bytes():
    sync = FakeResponses(FakeResponse(output_parsed=FundingVerdicts()))
    judge(sync, sync, source_id="src-1", chunk=CHUNK)
    instructions, (first, _), claude_data = reading_prompts(CHUNK)
    line = openai_request("p0-c0-o1", instructions=instructions, data=first, source_id="src-1")
    for name in ("model", "input", "safety_identifier", "prompt_cache_key", "max_output_tokens",
                 "store"):
        assert line["body"][name] == sync.calls[0][name], name
    # responses.parse(text_format=T) sends text.format = type_to_text_format_param(T).
    assert line["body"]["text"] == {
        "format": type_to_text_format_param(sync.calls[0]["text_format"])
    }
    assert line["body"]["text"]["format"]["strict"] is True
    json.dumps(line)  # a JSONL line: nothing in it may be a Python object
    request = anthropic_request(
        "p0-c0-c", instructions=instructions, data=claude_data, source_id="src-1"
    )
    for name in ("model", "system", "messages", "max_tokens", "metadata"):
        assert request["params"][name] == sync.calls[2][name], name
    # messages.parse(output_format=T) sends output_config.format =
    # {"type": "json_schema", "schema": transform_schema(TypeAdapter(T).json_schema())}.
    assert request["params"]["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": transform_schema(TypeAdapter(sync.calls[2]["output_format"]).json_schema()),
        }
    }
    json.dumps(request)
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", request["custom_id"])


def test_a_batched_read_decides_exactly_what_a_synchronous_read_decides():
    sync = ScriptedReaders(_SCRIPT)
    expected = read_funding(sync, sync, source_id="src-1", chunks=[CHUNK, OTHER])
    assert expected.decisions  # never a comparison of two empty reads
    got = read_funding_batched(_clients(*_fakes()), [PageRead("src-1", [CHUNK, OTHER])])
    assert got == [expected]


def test_a_request_the_batch_did_not_finish_leaves_only_its_page_undecided():
    got = read_funding_batched(
        _clients(*_fakes(expired={"p0-c0-c"})), [PageRead("a", [CHUNK]), PageRead("b", [CHUNK])]
    )
    assert got[0] is None
    assert got[1] is not None and got[1].decisions


def test_an_openai_line_missing_from_an_expired_batch_is_missing_too():
    openai = FakeOpenAIBatches(ScriptedReaders(_SCRIPT), statuses=("expired",), drop={"p1-c0-o2"})
    anthropic = FakeAnthropicBatches(ScriptedReaders(_SCRIPT))
    got = read_funding_batched(
        _clients(openai, anthropic), [PageRead("a", [CHUNK]), PageRead("b", [CHUNK])]
    )
    assert got[0] is not None and got[1] is None


def test_an_answered_error_is_a_lost_reading_so_the_award_abstains():
    meter = CostMeter()
    (result,) = read_funding_batched(
        _clients(*_fakes(errored={"p0-c0-c"})), [PageRead("a", [CHUNK], meter)]
    )
    assert result is not None
    assert [decision.agreement for decision in result.decisions] == ["ABSTAINED"]
    assert meter.lost == 1


def test_an_off_schema_answer_was_billed_so_its_usage_is_metered_never_lost():
    """The synchronous path counts an off-schema reply as billed (fda7499); a
    batch body carries its usage even then, so the batch path prices it."""
    meter = CostMeter()
    (result,) = read_funding_batched(
        _clients(*_fakes({"off_schema": {"p0-c0-o1"}}, off_schema={"p0-c0-c"})),
        [PageRead("a", [CHUNK], meter)],
    )
    assert result is not None
    assert [decision.agreement for decision in result.decisions] == ["ABSTAINED"]
    assert (meter.lost, meter.unmetered, len(meter.usages)) == (0, 0, 3)
    assert {usage.family for usage in meter.usages} == {"openai", "claude"}


def test_a_batch_that_outlives_its_wait_is_cancelled_and_decides_nothing():
    openai, anthropic = _fakes(polls_to_end=10**6)
    ticks = itertools.count()
    got = read_funding_batched(
        _clients(openai, anthropic, max_wait_seconds=5, clock=lambda: float(next(ticks))),
        [PageRead("a", [CHUNK])],
    )
    assert got == [None] and anthropic.cancelled == ["msgbatch-1"]


def test_a_split_on_offered_is_settled_by_a_second_openai_batch_when_paid():
    openai = FakeOpenAIBatches(ScriptedReaders({_WAIVER: {}}))
    anthropic = FakeAnthropicBatches(ScriptedReaders({_WAIVER: {"offered": "NO"}}))
    meter = CostMeter()
    read_funding_batched(
        _clients(openai, anthropic), [PageRead("a", [CHUNK], meter)],
        pay_for_tie_break=lambda: True,
    )
    assert len(openai.uploads) == 2
    assert [request["custom_id"] for request in openai.uploads[1]] == ["p0-c0-t"]
    assert len(meter.usages) == 4


def test_an_unpaid_tie_break_is_never_submitted():
    openai = FakeOpenAIBatches(ScriptedReaders({_WAIVER: {}}))
    anthropic = FakeAnthropicBatches(ScriptedReaders({_WAIVER: {"offered": "NO"}}))
    read_funding_batched(
        _clients(openai, anthropic), [PageRead("a", [CHUNK])], pay_for_tie_break=lambda: False
    )
    assert len(openai.uploads) == 1


def test_batch_readings_are_metered_at_the_batch_tier_and_the_files_are_deleted():
    openai, anthropic = _fakes()
    meter = CostMeter()
    read_funding_batched(_clients(openai, anthropic), [PageRead("a", [CHUNK], meter)])
    assert len(meter.usages) == 3 and {usage.tier for usage in meter.usages} == {"batch"}
    assert openai.deleted == ["file-in-1", "out-batch-1"]


def test_one_failed_status_poll_does_not_discard_the_run():
    """Up to a day of polling: a transient error is 'not known yet', never the end."""
    openai, anthropic = _fakes()
    real_retrieve, failures = anthropic.messages.batches.retrieve, [0]

    def flaky(batch_id):
        if not failures[0]:
            failures[0] += 1
            raise ConnectionError("reset by peer")
        return real_retrieve(batch_id)

    anthropic.messages.batches.retrieve = flaky
    (result,) = read_funding_batched(_clients(openai, anthropic), [PageRead("a", [CHUNK])])
    assert result is not None and result.decisions and failures[0] == 1


def test_a_second_vendor_that_refuses_the_batch_cancels_the_first_and_deletes_its_upload():
    openai, anthropic = _fakes()

    def refuse(*, requests):
        raise RuntimeError("request too large")

    anthropic.messages.batches.create = refuse
    try:
        read_funding_batched(_clients(openai, anthropic), [PageRead("a", [CHUNK])])
    except RuntimeError:
        pass
    else:
        raise AssertionError("the refusal must propagate")
    assert openai.cancelled == ["batch-1"] and openai.deleted == ["file-in-1"]


def test_an_upload_whose_batch_was_refused_is_deleted():
    openai, anthropic = _fakes()

    def refuse(**_kwargs):
        raise RuntimeError("quota")

    openai.batches.create = refuse
    try:
        read_funding_batched(_clients(openai, anthropic), [PageRead("a", [CHUNK])])
    except RuntimeError:
        pass
    else:
        raise AssertionError("the refusal must propagate")
    assert openai.deleted == ["file-in-1"] and anthropic.requests == []
