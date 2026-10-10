"""A verification's spend, composed from the three places it is already recorded.

Model spend is item 15's `model_cost.CostMeter`, priced from
`MODEL_PRICES_USD_PER_MTOK`; this file never re-prices a token, it only checks
that the Meter composes the CostMeter with the run budget and search spend and
that anything the CostMeter could not price makes the total a floor.
"""

from decimal import Decimal
from types import SimpleNamespace

from apps.research.fetch import SweepBudget
from apps.research.metering import Meter
from apps.research.model_cost import Usage, anthropic_usage, openai_usage

PRICES = {
    "gpt-x": {"input": 1.0, "cache_read": 0.1, "cache_write": 1.0, "output": 4.0},
    "claude-y": {"input": 3.0, "cache_read": 0.3, "cache_write": 3.75, "output": 15.0},
}


def _meter(settings):
    settings.MODEL_PRICES_USD_PER_MTOK = PRICES
    run = SweepBudget({"FIRECRAWL": 1000, "SCRAPE_DO": 1000})
    return run, Meter(run)


def test_openai_cached_tokens_are_priced_as_cache_reads_not_twice(settings):
    _run, meter = _meter(settings)
    response = SimpleNamespace(usage=SimpleNamespace(
        input_tokens=1_000_000, output_tokens=0,
        input_tokens_details=SimpleNamespace(cached_tokens=400_000),
    ))
    meter.models.record(openai_usage(response, model="gpt-x"))
    usd, detail, complete = meter.total()
    # 600k uncached at $1 + 400k cached at $0.10
    assert usd == Decimal("0.640000") and complete
    assert detail["models"]["openai"]["cache_read"] == 400_000


def test_anthropic_usage_is_read_as_reported(settings):
    _run, meter = _meter(settings)
    response = SimpleNamespace(usage=SimpleNamespace(
        input_tokens=100_000, output_tokens=10_000,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    ))
    meter.models.record(anthropic_usage(response, model="claude-y"))
    assert meter.total()[0] == Decimal("0.450000")


def test_a_model_with_no_list_price_makes_the_cost_a_floor_never_a_guess(settings):
    _run, meter = _meter(settings)
    meter.models.record(Usage("openai", "unpriced-model", "default", 10, 0, 0, 10))
    usd, detail, complete = meter.total()
    assert usd == Decimal("0") and complete is False
    assert detail["models"]["unpriced"] == 1


def test_a_call_that_raised_makes_the_cost_a_floor(settings):
    _run, meter = _meter(settings)
    meter.models.lost += 1
    assert meter.total()[2] is False


def test_a_reply_without_usage_makes_the_cost_a_floor(settings):
    _run, meter = _meter(settings)
    meter.models.record(None)
    usd, detail, complete = meter.total()
    assert complete is False and detail["models"]["unmetered"] == 1


def test_fetch_cost_is_the_run_budgets_delta_since_this_award_began(settings):
    run, _ = _meter(settings)
    run.spend("FIRECRAWL", 50)          # an earlier award in the same run
    meter = Meter(run)
    run.spend("FIRECRAWL", 12)
    run.spend("SCRAPE_DO", 25)
    usd, detail, complete = meter.total()
    assert detail["credits"] == {"FIRECRAWL": 12, "SCRAPE_DO": 25}
    assert usd == Decimal("0.012860") and complete  # 12 x 83/100k + 25 x 29/250k


def test_search_spend_is_added_as_the_provider_reported_it(settings):
    _run, meter = _meter(settings)
    meter.add_search("exa", 0.0097)
    usd, detail, _ = meter.total()
    assert usd == Decimal("0.009700")
    assert detail["searches"] == {"exa": 1} and detail["search_usd"] == 0.0097


def test_the_three_sources_add_up(settings):
    run, meter = _meter(settings)
    run.spend("FIRECRAWL", 100)
    meter.models.record(Usage("openai", "gpt-x", "default", 1_000_000, 0, 0, 0))
    meter.add_search("brave", 0.005)
    usd, _detail, complete = meter.total()
    assert usd == Decimal("1.088000") and complete  # 100 x 83/100k + 1.0 + 0.005
