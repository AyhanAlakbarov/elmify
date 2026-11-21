# tests/research/card_engine/test_live.py
"""The configured stack against the real vendors, once. Skipped by default; costs about $0.01.

Checks decision 7 against the configured host: DeepSeek is pinned to the OpenRouter provider in
`settings.CARD_READERS` (inference-net/fp8 at the time of writing), so a reply that comes back ok
means that host served it; a 404/429 naming the provider means the pin is wrong.

Run: OPENROUTER_API_KEY=... ANTHROPIC_API_KEY=... \\
     POSTGRES_DB=elmify_card_engine uv run pytest tests/research/card_engine/test_live.py -m live -s
"""

import os
from dataclasses import dataclass
from uuid import uuid4

import pytest

from apps.research.candidates import Line, find_all
from apps.research.card_engine import Section, yes_no
from apps.research.card_engine.engine import _prompt, read
from apps.research.card_engine.readers import call, run_limit, stack
from apps.research.card_engine.screen import screen

pytestmark = [pytest.mark.live, pytest.mark.django_db]

SECTION = Section("DAAD EPOS scholarship", "en", (
    Line("Scholarship holders receive a monthly payment of EUR 934.", heading="## Benefits"),
    Line("Applications must be submitted by 31 August 2026.", heading="## Application"),
))
PAID = yes_no("paid", "Do these lines state that a student is paid money directly?")


@dataclass
class _Set:
    name: str = "live"
    version: str = "1"
    criteria: str = ""

    def proposals(self, section):
        return ()

    def questions(self, section, candidates, proposed):
        return (PAID,)


@pytest.fixture(autouse=True)
def _keys(settings):
    if not (os.environ.get("OPENROUTER_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        pytest.skip("needs OPENROUTER_API_KEY and ANTHROPIC_API_KEY")
    settings.OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
    settings.DECISIONS_BASE_URL = "https://openrouter.ai/api"


def test_the_configured_stack_reads_one_section_end_to_end():
    readers = stack()
    # every OpenRouter reader must be pinned to a host: that pin is what is being checked
    assert all(s.host for s in readers.pair if s.transport == "openrouter"), readers.pair
    limit = run_limit(uuid4())
    cleared = screen(SECTION, limit=limit, record=False)
    assert cleared.status == "clear", cleared
    reading = read(_Set(), SECTION, screen=cleared, limit=limit)
    for c in reading.calls:
        print(c)
    print("dropped_quotes", reading.dropped_quotes)
    decision = reading.decisions[0]
    assert (decision.status, decision.value) == ("agreed", "yes"), decision
    assert decision.quote is not None and decision.quote.where == "L0.text"
    assert all(c.ok and c.cost_usd is not None for c in reading.calls)
    # the decider is asked only on a split, so reach it directly once
    attempt = call(readers.decider,
                   _prompt(_Set(), SECTION, find_all(SECTION.lines), {}, (PAID,)))
    print(attempt.reason, attempt.cost_usd, attempt.latency_s)
    assert attempt.reply is not None, attempt.reason
