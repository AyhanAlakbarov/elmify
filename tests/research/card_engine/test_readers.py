import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.research.card_engine.readers import (
    MAX_OUTPUT_TOKENS,
    REPLY_SCHEMA,
    Prompt,
    ReaderSpec,
    Reply,
    StackMisconfigured,
    anthropic_reader,
    call,
    openrouter,
    run_limit,
    stack,
    tenant_limit,
)
from apps.research.egress import SourceBlocked

PROMPT = Prompt(system="RULES", data='<section untrusted="true">\n{}\n</section>', ask="{}")
DEEPSEEK = ReaderSpec("deepseek", "openrouter", "deepseek/deepseek-v4.1-flash", "inference-net/fp8",
                      {"reasoning": {"enabled": False}, "temperature": 0})
OPUS = ReaderSpec("opus", "anthropic", "claude-opus-5-5")
GOOD = {"answers": [{"id": "open", "value": "yes", "quote": "Applications open"}]}


def test_the_default_stack_is_the_owners():
    readers = stack()
    assert [(r.name, r.model, r.host) for r in readers.pair] == [
        ("deepseek", "deepseek/deepseek-v4.1-flash", "inference-net/fp8"),
        ("luna", "openai/gpt-6-luna", "openai"),
    ]
    assert (readers.decider.name, readers.decider.transport, readers.decider.model) == (
        "opus", "anthropic", "claude-opus-5-5")
    assert "temperature" not in readers.pair[1].params  # 404s on Luna (measured 2026-10-11)


def _raw(**changes):
    raw = {"pair": [{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h"},
                    {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}],
           "decider": {"name": "c", "transport": "anthropic", "model": "claude-x"}}
    raw.update(changes)
    return raw


@pytest.mark.parametrize("raw, message", [
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h"}]),
     "exactly two"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a"},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "pinned to one host"),
    (_raw(decider={"name": "c", "transport": "anthropic", "model": "x", "host": "h"}),
     "no host or params"),
    (_raw(decider={"name": "c", "transport": "grpc", "model": "x"}), "unknown transport"),
    (_raw(decider={"name": "a", "transport": "anthropic", "model": "x"}), "distinct"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "openai/gpt-6-luna",
                 "host": "openai", "params": {"temperature": 0}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "temperature"),
    (_raw(decider={"name": "c"}), "name, transport and model"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": {"max_tokens": 100000, "provider": {"allow_fallbacks": True},
                            "model": "other/model"}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "may not set"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": {"models": ["x/y"]}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "may not set"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": {"stream": True}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "may not set"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": {"route": "fallback"}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "may not set"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": {"tools": []}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "may not set"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": {"tool_choice": "auto"}},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "may not set"),
    ([], "object"),
    ({}, "exactly two"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": "ab"},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "params must be an object"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": "h",
                 "params": [1]},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "params must be an object"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "", "host": "h"},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "non-blank"),
    (_raw(pair=[{"name": "a", "transport": "openrouter", "model": "m/a", "host": " "},
                {"name": "b", "transport": "openrouter", "model": "m/b", "host": "h"}]),
     "non-blank"),
    (_raw(decider={"name": None, "transport": "anthropic", "model": "x"}), "non-blank"),
])
def test_a_wrong_stack_is_refused_whole(raw, message):
    with pytest.raises(StackMisconfigured, match=message):
        stack(raw)


def test_the_sent_schema_and_the_pydantic_model_agree():
    assert REPLY_SCHEMA["additionalProperties"] is False
    item = REPLY_SCHEMA["properties"]["answers"]["items"]  # type: ignore[index]
    assert set(item["required"]) == set(Reply.model_fields["answers"].annotation.__args__[0]
                                        .model_fields)
    with pytest.raises(ValidationError):
        Reply.model_validate({"answers": [{"id": "x", "value": "y", "quote": "", "why": "z"}]})


def _post(response, seen=None):
    def post(url, *, payload, headers, read_timeout):
        if seen is not None:
            seen.update(url=url, payload=payload, headers=headers)
        if isinstance(response, Exception):
            raise response
        return response
    return post


def _completion(content, finish="stop", cost=0.0002):
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}],
            "usage": {"cost": cost}}


def test_openrouter_pins_the_host_labels_the_data_and_caps_the_output(settings):
    settings.OPENROUTER_API_KEY = "sk-or-test"
    seen: dict = {}
    attempt = openrouter(DEEPSEEK, PROMPT, post=_post(_completion(json.dumps(GOOD)), seen))
    assert attempt.reply == Reply.model_validate(GOOD)
    assert attempt.reason == "" and attempt.cost_usd == 0.0002 and attempt.latency_s >= 0
    body = seen["payload"]
    assert body["provider"] == {"order": ["inference-net/fp8"], "allow_fallbacks": False,
                                "require_parameters": True}
    assert body["max_tokens"] == MAX_OUTPUT_TOKENS
    assert body["temperature"] == 0 and body["reasoning"] == {"enabled": False}
    assert body["messages"][1]["content"].startswith('<section untrusted="true">')
    assert body["response_format"]["json_schema"]["strict"] is True
    assert seen["headers"] == {"Authorization": "Bearer sk-or-test"}


@pytest.mark.parametrize("response, reason, cost", [
    (_completion("{not json"), "off_schema", 0.0002),
    (_completion(json.dumps({"answers": [{"id": "a", "value": "b"}]})), "off_schema", 0.0002),
    (_completion(json.dumps(GOOD), finish="length"), "truncated", 0.0002),
    (_completion(json.dumps(GOOD), cost=None), "", None),
    (TimeoutError("read timed out, Authorization: Bearer sk-or-test"), "failed:TimeoutError", None),
    (SourceBlocked("api returned HTTP 429"), "failed:http_429", None),
    ({"error": {"message": "no capacity"}}, "failed:provider_error", None),
    (_completion(json.dumps(GOOD), cost=True), "", None),
])
def test_openrouter_failures_are_typed_and_never_carry_the_message(settings, response, reason,
                                                                   cost):
    settings.OPENROUTER_API_KEY = "sk-or-test"
    attempt = openrouter(DEEPSEEK, PROMPT, post=_post(response))
    assert (attempt.reason, attempt.cost_usd) == (reason, cost)
    assert "sk-or" not in attempt.reason


def test_openrouter_without_a_key_sends_nothing(settings):
    settings.OPENROUTER_API_KEY = ""
    attempt = openrouter(DEEPSEEK, PROMPT, post=_post(AssertionError("must not be called")))
    assert attempt.reason == "not_configured" and attempt.reply is None


class _Messages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, {}

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


def _claude(parsed, stop="end_turn"):
    usage = SimpleNamespace(input_tokens=900, output_tokens=60, cache_read_input_tokens=0,
                            cache_creation_input_tokens=0)
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop, usage=usage)


def test_the_decider_goes_through_the_anthropic_sdk_with_its_own_model(settings):
    settings.MODEL_PRICES_USD_PER_MTOK = {
        "claude-opus-5-5": {"input": 5.0, "cache_read": 0.5, "cache_write": 6.25, "output": 25.0}}
    messages = _Messages(_claude(Reply.model_validate(GOOD)))
    attempt = anthropic_reader(OPUS, PROMPT, messages=lambda: messages)
    assert attempt.reply == Reply.model_validate(GOOD)
    assert messages.kwargs["model"] == "claude-opus-5-5"
    assert messages.kwargs["max_tokens"] == MAX_OUTPUT_TOKENS
    assert messages.kwargs["output_format"] is Reply
    assert messages.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert messages.kwargs["messages"][0]["content"].startswith('<section untrusted="true">')
    assert attempt.cost_usd == pytest.approx((900 * 5.0 + 60 * 25.0) / 1_000_000)


def test_an_unpriced_decider_records_no_cost_never_zero(settings):
    settings.MODEL_PRICES_USD_PER_MTOK = {}
    attempt = anthropic_reader(OPUS, PROMPT, messages=lambda: _Messages(
        _claude(Reply.model_validate(GOOD))))
    assert attempt.reply is not None and attempt.cost_usd is None


@pytest.mark.parametrize("messages, reason", [
    (_Messages(_claude(None, stop="max_tokens")), "truncated"),
    (_Messages(_claude(None, stop="refusal")), "refusal"),
    (_Messages(_claude(None)), "off_schema"),
    (_Messages(error=ConnectionError("x-api-key: sk-ant")), "failed:ConnectionError"),
])
def test_decider_failures_are_typed(messages, reason):
    attempt = anthropic_reader(OPUS, PROMPT, messages=lambda: messages)
    assert attempt.reply is None and attempt.reason == reason


def test_the_two_limits_are_separate_buckets_sized_by_settings(settings):
    settings.CARD_READER_RUN_CALLS_PER_HOUR = 7
    settings.CARD_READER_TENANT_CALLS_PER_HOUR = 3
    run, tenant = run_limit(uuid4()), tenant_limit(uuid4())
    assert (run.bucket, run.limit, run.window_seconds) == ("card-reader-run", 7, 3600)
    assert (tenant.bucket, tenant.limit) == ("card-reader-tenant", 3)


def test_params_cannot_override_what_the_transport_owns(settings):
    settings.OPENROUTER_API_KEY = "k"
    seen: dict = {}
    openrouter(DEEPSEEK, PROMPT, post=_post(_completion(json.dumps(GOOD)), seen))
    assert seen["payload"]["model"] == "deepseek/deepseek-v4.1-flash"


def test_a_missing_anthropic_key_sends_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    attempt = anthropic_reader(OPUS, PROMPT)
    assert attempt.reason == "not_configured" and attempt.reply is None


def test_call_dispatches_on_the_transport(monkeypatch):
    sent = []
    monkeypatch.setattr("apps.research.card_engine.readers.openrouter",
                        lambda spec, prompt: sent.append(("or", spec.name)) or "O")
    monkeypatch.setattr("apps.research.card_engine.readers.anthropic_reader",
                        lambda spec, prompt: sent.append(("an", spec.name)) or "A")
    assert call(DEEPSEEK, PROMPT) == "O" and call(OPUS, PROMPT) == "A"
    assert sent == [("or", "deepseek"), ("an", "opus")]


def test_a_bad_card_readers_setting_fails_manage_check(settings):
    from apps.research.apps import check_card_readers

    settings.CARD_READERS = {}
    assert [m.id for m in check_card_readers()] == ["research.E001"]


def test_malformed_card_readers_json_reports_e001_not_an_import_crash(monkeypatch):
    import importlib

    from django.core.management import call_command
    from django.test.utils import override_settings

    from config.settings import base

    monkeypatch.setenv("CARD_READERS_JSON", "{bad")
    try:
        reloaded = importlib.reload(base)
        assert reloaded.CARD_READERS == "{bad"
        with override_settings(CARD_READERS=reloaded.CARD_READERS):
            from apps.research.apps import check_card_readers
            assert [m.id for m in check_card_readers()] == ["research.E001"]
            from django.core.management.base import SystemCheckError
            with pytest.raises(SystemCheckError, match="E001"):
                call_command("check")
    finally:
        monkeypatch.delenv("CARD_READERS_JSON")
        importlib.reload(base)


def test_the_default_price_table_prices_the_decider():
    messages = _Messages(_claude(Reply.model_validate(GOOD)))
    attempt = anthropic_reader(OPUS, PROMPT, messages=lambda: messages)
    assert attempt.cost_usd == pytest.approx((900 * 4.0 + 60 * 20.0) / 1_000_000)
