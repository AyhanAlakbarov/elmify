"""What one cycle verification spent, as the vendors billed it (spec 9.3).

Three sources, none estimated, and none re-implemented here:

- fetch: the run's `SweepBudget`, which every `fetch_page` call spends against
  -- this award's share is the delta since it began, at `USD_PER_CREDIT`;
- models: item 15's `model_cost.CostMeter` (`models` below), which the read
  seam hands to `funding_judge.read_funding(..., meter=...)` so every reading's
  usage is recorded where every other funding read records it, and priced at
  `MODEL_PRICES_USD_PER_MTOK` -- one price table, not a second;
- search: the provider's own figure (`SiteSearchResult.cost_usd`).

`total()` is a floor, and says so (`complete` False), whenever the CostMeter
holds a reading it could not price (no price row for the model or tier), a
reply that carried no usage, or a call that raised before reporting any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from apps.research.fetch import USD_PER_CREDIT, SweepBudget
from apps.research.model_cost import CostMeter

_MICRO = Decimal("0.000001")


@dataclass
class Meter:
    run: SweepBudget
    models: CostMeter = field(default_factory=CostMeter)
    search_usd: float = 0.0
    searches: dict[str, int] = field(default_factory=dict)
    _start: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self._start = dict(self.run.spent)

    def add_search(self, provider: str, usd: float) -> None:
        self.search_usd += usd
        self.searches[provider] = self.searches.get(provider, 0) + 1

    def credits(self) -> dict[str, int]:
        return {
            vendor: spent - self._start.get(vendor, 0) for vendor, spent in self.run.spent.items()
        }

    def complete(self) -> bool:
        return not (self.models.unpriced or self.models.unmetered or self.models.lost)

    def total(self) -> tuple[Decimal, dict[str, Any], bool]:
        credits = self.credits()
        fetch_usd = sum(USD_PER_CREDIT[vendor] * n for vendor, n in credits.items())
        usd = Decimal(str(fetch_usd + self.models.usd + self.search_usd)).quantize(_MICRO)
        detail: dict[str, Any] = {
            "credits": credits,
            "fetch_usd": round(fetch_usd, 6),
            "models": self.models.as_json(),
            "search_usd": round(self.search_usd, 6),
            "searches": dict(self.searches),
        }
        return usd, detail, self.complete()
