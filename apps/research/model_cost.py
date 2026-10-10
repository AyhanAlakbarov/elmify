"""What a model reading cost: recorded token counts, priced from a data table.

Funding master spec §8.2, §9.3, §13. The counts are the vendor's own (`usage`
on every response); the dollars are those counts at the list price in
settings. A reading whose model or tier has no price row is UNPRICED and
counted as such -- never priced at zero, which would make an unmeasured cost
look like a saving (item 15's brief: "a saving nobody measured is not a
saving").

Nothing here calls a model or touches the database.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from django.conf import settings

#: OpenAI's flex guide raises the client timeout to 15 minutes: a flex request
#: waits for spare capacity rather than failing fast.
FLEX_TIMEOUT_SECONDS = 900.0


class ReadingTier(StrEnum):
    """How a funding reading is bought. STANDARD is today's synchronous call."""

    STANDARD = "standard"
    #: OpenAI only; Anthropic has no flex tier, so the Claude reading stays standard.
    FLEX = "flex"
    #: Both vendors' batch APIs, through apps.research.batch_reading.
    BATCH = "batch"


class ReadingTierRefused(RuntimeError):
    """The vendor rejected the tier itself (a 400 on a flex request).

    Raised, never swallowed: every reading of every page would otherwise come
    back lost, and a page whose readings are all lost reads as a page that
    states no funding -- the silent failure this repo keeps meeting.
    """


def _get(obj: object, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


@dataclass(frozen=True)
class Usage:
    family: str
    model: str
    #: The tier the vendor says it BILLED, not the one we asked for: a flex
    #: request can be served, and billed, at default.
    tier: str
    #: Uncached input only.
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


def openai_usage(response: object, *, model: str, batch: bool = False) -> Usage | None:
    """OpenAI counts cached tokens INSIDE input_tokens; split them out.

    `response` is a Responses API object or, from a batch output file, the
    plain JSON body of one.
    """
    usage = _get(response, "usage")
    if usage is None:
        return None
    total = _int(_get(usage, "input_tokens"))
    details = _get(usage, "input_tokens_details")
    cached = _int(_get(details, "cached_tokens")) if details is not None else 0
    tier = "batch" if batch else str(_get(response, "service_tier") or "default")
    return Usage(
        "openai", model, tier, max(total - cached, 0), cached, 0, _int(_get(usage, "output_tokens"))
    )


def anthropic_usage(response: object, *, model: str, batch: bool = False) -> Usage | None:
    """Anthropic reports cache reads and writes APART from input_tokens."""
    usage = _get(response, "usage")
    if usage is None:
        return None
    return Usage(
        "claude",
        model,
        "batch" if batch else "default",
        _int(_get(usage, "input_tokens")),
        _int(_get(usage, "cache_read_input_tokens")),
        _int(_get(usage, "cache_creation_input_tokens")),
        _int(_get(usage, "output_tokens")),
    )


def usage_usd(usage: Usage) -> float | None:
    """List price times the billed tier, or None when either has no row."""
    row = settings.MODEL_PRICES_USD_PER_MTOK.get(usage.model)
    multiplier = settings.MODEL_TIER_MULTIPLIER.get(usage.tier)
    if row is None or multiplier is None:
        return None
    dollars = (
        usage.input_tokens * row["input"]
        + usage.cache_read_tokens * row["cache_read"]
        + usage.cache_write_tokens * row["cache_write"]
        + usage.output_tokens * row["output"]
    ) / 1_000_000
    return float(dollars * multiplier)


@dataclass
class CostMeter:
    """Every reading one page -- or one run -- paid for."""

    usages: list[Usage] = field(default_factory=list)
    #: A call that raised: no response, no usage. Whether the vendor billed it
    #: is unknown, so it is counted and never priced.
    lost: int = 0
    #: A reply that came back without a readable usage block -- no `usage`, or
    #: an answer the SDK rejected inside parse() (off-schema, or cut off at the
    #: output cap): paid for, unpriceable. A `unmetered` count is spend the
    #: dollars do not include.
    unmetered: int = 0
    #: Flex readings the vendor had no capacity for, re-asked at default price.
    flex_fallbacks: int = 0

    def record(self, usage: Usage | None) -> None:
        if usage is None:
            self.unmetered += 1
        else:
            self.usages.append(usage)

    def add(self, other: CostMeter) -> None:
        self.usages.extend(other.usages)
        self.lost += other.lost
        self.unmetered += other.unmetered
        self.flex_fallbacks += other.flex_fallbacks

    def tokens(self, family: str) -> dict[str, int]:
        rows = [usage for usage in self.usages if usage.family == family]
        return {
            "input": sum(usage.input_tokens for usage in rows),
            "cache_read": sum(usage.cache_read_tokens for usage in rows),
            "cache_write": sum(usage.cache_write_tokens for usage in rows),
            "output": sum(usage.output_tokens for usage in rows),
        }

    @property
    def unpriced(self) -> int:
        return sum(1 for usage in self.usages if usage_usd(usage) is None)

    @property
    def usd(self) -> float:
        """Dollars over the PRICED readings only -- always read `unpriced` beside it."""
        return sum(cost for usage in self.usages if (cost := usage_usd(usage)) is not None)

    def as_json(self) -> dict[str, object]:
        return {
            "calls": len(self.usages) + self.unmetered,
            "lost": self.lost,
            "unmetered": self.unmetered,
            "unpriced": self.unpriced,
            "flex_fallbacks": self.flex_fallbacks,
            "tiers": sorted({usage.tier for usage in self.usages}),
            "openai": self.tokens("openai"),
            "claude": self.tokens("claude"),
            "usd": round(self.usd, 6),
            "prices_verified_on": settings.MODEL_PRICES_VERIFIED_ON,
        }

    def line(self) -> str:
        openai, claude = self.tokens("openai"), self.tokens("claude")
        # Per family: "flex" on an OpenAI reading is the vendor's word that it
        # billed flex; the gate reads this, not what was requested.
        tiers = Counter(f"{usage.family}:{usage.tier}" for usage in self.usages)
        return (
            f"calls={len(self.usages) + self.unmetered} lost={self.lost} "
            f"openai(in={openai['input']} cached={openai['cache_read']} out={openai['output']}) "
            f"claude(in={claude['input']} cache_read={claude['cache_read']} "
            f"cache_write={claude['cache_write']} out={claude['output']}) "
            f"usd={self.usd:.4f} unpriced={self.unpriced} flex_fallbacks={self.flex_fallbacks} "
            f"tiers={dict(sorted(tiers.items()))}"
        )
