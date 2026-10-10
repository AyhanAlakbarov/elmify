"""Live probes for item 15: run before the gate, never in a default run.

    ANTHROPIC_API_KEY=... OPENAI_API_KEY=... uv run pytest \\
      tests/research/test_funding_cost_live.py -m live -v

Each costs cents. Excluded from a default run by addopts; skipped when a key is absent.
"""

import os

import anthropic
import pytest
from django.conf import settings
from openai import OpenAI

from apps.research.funding_judge import Line, claude_system, judge, reading_prompts
from apps.research.model_cost import FLEX_TIMEOUT_SECONDS, CostMeter, ReadingTier

pytestmark = pytest.mark.live

anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY is not set"
)
both_keys = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("OPENAI_API_KEY")),
    reason="both model keys are needed",
)

#: Sonnet 5's minimum cacheable prefix (Anthropic prompt-caching reference,
#: read 2026-09-25). Below it a cache_control block is ignored with no error.
_ANTHROPIC_MIN_CACHEABLE = 1_024

CHUNK = (
    Line(text="Scholarships", heading=""),
    Line(text="All admitted international students receive a 50% tuition waiver.",
         heading="Scholarships"),
)


@anthropic_key
def test_the_claude_system_prefix_is_long_enough_to_be_cached():
    instructions, _, _ = reading_prompts(CHUNK)
    counted = anthropic.Anthropic().messages.count_tokens(
        model=settings.ANTHROPIC_JUDGE_MODEL,
        system=claude_system(instructions),
        messages=[{"role": "user", "content": "."}],
    )
    # The count includes the one-character user turn; the margin keeps it honest.
    assert counted.input_tokens >= _ANTHROPIC_MIN_CACHEABLE + 10, counted.input_tokens


@both_keys
def test_the_extraction_model_accepts_flex_and_reports_the_tier_it_billed():
    """If this raises ReadingTierRefused, OPENAI_EXTRACTION_MODEL has no flex
    tier: record that in the gate note and skip the flex run -- do not
    special-case the model in code."""
    meter = CostMeter()
    readings = judge(
        OpenAI(timeout=FLEX_TIMEOUT_SECONDS).responses,
        anthropic.Anthropic().messages,
        source_id="item-15-flex-probe",
        chunk=CHUNK,
        meter=meter,
        tier=ReadingTier.FLEX,
    )
    assert len(readings) == 3
    openai_tiers = {usage.tier for usage in meter.usages if usage.family == "openai"}
    assert openai_tiers <= {"flex", "default"}, openai_tiers
    print(meter.line())


from apps.research.batch_reading import BatchClients, PageRead, read_funding_batched  # noqa: E402


@both_keys
def test_one_page_reads_through_both_batch_apis():
    """Up to an hour of wall-clock; costs cents. Proves both request shapes are
    accepted -- including structured output inside a batch -- and that usage
    comes back to meter."""
    meter = CostMeter()
    (result,) = read_funding_batched(
        BatchClients(
            openai=OpenAI(), anthropic=anthropic.Anthropic(), poll_seconds=30,
            max_wait_seconds=3_600,
        ),
        [PageRead("item-15-batch-probe", [CHUNK], meter)],
    )
    assert result is not None, "a batch did not finish within the hour"
    assert len(meter.usages) >= 3 and {usage.tier for usage in meter.usages} == {"batch"}
    print(meter.line())


from pathlib import Path  # noqa: E402

from apps.research.fetch import firecrawl  # noqa: E402
from apps.research.first_read import first_read_verdicts, json_format  # noqa: E402

firecrawl_key = pytest.mark.skipif(
    not settings.FIRECRAWL_API_KEY, reason="FIRECRAWL_API_KEY is not set"
)
_CONTROL_HOSTS = (
    Path(__file__).resolve().parents[2] / "docs/research/2026-09-18-positive-control-hosts.txt"
)


@firecrawl_key
def test_a_real_page_answers_the_first_read_schema():
    """Step 0 of the first-read gate: 5 credits.

    If Firecrawl answers HTTP 400 naming checkPromptInjection, move that key
    from first_read.json_format() to the top level of the scrape body in
    firecrawl.scrape; if it is refused in both places, drop it and record that
    in the gate note. Never drop the "data, never instructions" prompt line.
    """
    host = next(
        line.split("\t")[0]
        for line in _CONTROL_HOSTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    )
    page = firecrawl.scrape(
        f"https://{host}/", api_key=settings.FIRECRAWL_API_KEY, json_format=json_format()
    )
    assert page.json_extract is not None, page.reason
    outcome = first_read_verdicts(page.json_extract, page.markdown)
    assert not outcome.off_schema
    print(f"{host}: {len(outcome.verdicts)} verified, {outcome.dropped} dropped, "
          f"{page.cost_credits} credits")
