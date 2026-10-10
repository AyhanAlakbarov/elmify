"""A reading's cost is its recorded tokens at list price.

An unknown price is unpriced, never zero.
"""

from types import SimpleNamespace

import pytest
from django.conf import settings as django_settings

from apps.research.model_cost import CostMeter, Usage, anthropic_usage, openai_usage, usage_usd

SONNET = "claude-sonnet-5"
SONNET_ROW = {"input": 2.0, "cache_read": 0.2, "cache_write": 2.5, "output": 10.0}


def test_openai_cached_tokens_are_split_out_of_input_and_the_billed_tier_is_kept():
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1_000,
            input_tokens_details=SimpleNamespace(cached_tokens=800),
            output_tokens=50,
        ),
        service_tier="flex",
    )
    assert openai_usage(response, model="m") == Usage("openai", "m", "flex", 200, 800, 0, 50)


def test_a_batch_output_line_is_read_from_plain_json_and_tagged_batch():
    body = {
        "usage": {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 4},
                  "output_tokens": 3},
        "service_tier": "default",
    }
    assert openai_usage(body, model="m", batch=True) == Usage("openai", "m", "batch", 6, 4, 0, 3)


def test_anthropic_reports_cache_reads_and_writes_apart_from_input():
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=120, cache_read_input_tokens=1_300, cache_creation_input_tokens=0,
            output_tokens=900,
        )
    )
    assert anthropic_usage(response, model=SONNET) == Usage(
        "claude", SONNET, "default", 120, 1_300, 0, 900
    )


def test_a_response_without_usage_has_no_usage():
    assert openai_usage(SimpleNamespace(), model="m") is None
    assert anthropic_usage(SimpleNamespace(usage=None), model=SONNET) is None


def test_dollars_are_the_list_price_times_the_tier(settings):
    settings.MODEL_PRICES_USD_PER_MTOK = {SONNET: SONNET_ROW}
    # 1,000 x 2.0 + 2,000 x 0.2 + 3,000 x 2.5 + 400 x 10.0 = 13,900 per million
    assert usage_usd(Usage("claude", SONNET, "default", 1_000, 2_000, 3_000, 400)) == (
        pytest.approx(0.0139)
    )
    assert usage_usd(Usage("claude", SONNET, "batch", 1_000, 2_000, 3_000, 400)) == (
        pytest.approx(0.00695)
    )


def test_an_unknown_model_or_tier_is_unpriced_never_zero(settings):
    settings.MODEL_PRICES_USD_PER_MTOK = {SONNET: SONNET_ROW}
    assert usage_usd(Usage("openai", "no-such-model", "default", 10)) is None
    # A tier nobody priced (priority, ultrafast) is not assumed to be list price.
    assert usage_usd(Usage("claude", SONNET, "priority", 10)) is None


def test_the_meter_prices_what_it_can_and_counts_what_it_cannot(settings):
    settings.MODEL_PRICES_USD_PER_MTOK = {SONNET: SONNET_ROW}
    meter = CostMeter()
    meter.record(Usage("claude", SONNET, "default", 1_000_000))  # $2.00
    meter.record(Usage("openai", "unpriced-model", "default", 5))
    meter.record(None)  # a response that carried no usage block
    meter.lost += 1  # a call that raised
    assert meter.usd == pytest.approx(2.0)
    assert meter.unpriced == 1
    data = meter.as_json()
    assert (data["calls"], data["unmetered"], data["lost"], data["unpriced"]) == (3, 1, 1, 1)
    assert data["claude"] == {"input": 1_000_000, "cache_read": 0, "cache_write": 0, "output": 0}


def test_meters_add_up():
    one, two = CostMeter(), CostMeter()
    one.record(Usage("openai", "m", "default", 1))
    two.record(Usage("openai", "m", "default", 2))
    two.flex_fallbacks = 1
    one.add(two)
    assert one.tokens("openai")["input"] == 3 and one.flex_fallbacks == 1


def test_the_shipped_table_prices_the_judge_model():
    """A judge-model switch without a price row must fail here, not report $0."""
    assert django_settings.ANTHROPIC_JUDGE_MODEL in django_settings.MODEL_PRICES_USD_PER_MTOK


def test_a_malformed_price_override_is_refused_at_startup():
    from config.settings.base import _price_override

    assert _price_override("") == {}
    row = '{"m": {"input": 1, "cache_read": 0.1, "cache_write": 1, "output": 4}}'
    assert _price_override(row) == {
        "m": {"input": 1.0, "cache_read": 0.1, "cache_write": 1.0, "output": 4.0}
    }
    for bad in ('[1]', '{"m": {"input": 1}}', '{"m": {"input": "1", "cache_read": 0, '
                '"cache_write": 0, "output": 0}}'):
        with pytest.raises(ValueError, match="MODEL_PRICES_JSON"):
            _price_override(bad)
