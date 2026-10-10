"""One protocol for every search index: a request in, URLs out.

`search` returns an iterable of URL strings and nothing else. That is not a
simplification of a richer return type -- it is the design's retention rule
expressed as a signature. A snippet, a title or a ranking cannot be persisted
by accident if the adapter never hands one back, and a provider whose terms
change tomorrow costs a deleted adapter rather than a data migration.

Adding a provider is writing one of these and appending it to a tally. It is
deliberately not a plugin system: there are four, they are named in the spec,
and a registry with one implementation is the abstraction this repo's rules
forbid.

Not to be confused with `providers/base.py`'s `SiteSearch`, which is the
*domain-restricted* shape research-fit calls (`exa_site_search`): one
institution's own host, five results, asking what that host says. This
protocol is the open-web discovery shape -- it asks the index who exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from ..domains import AGGREGATOR_DOMAINS


@dataclass(frozen=True)
class SearchRequest:
    """One call's worth of intent, provider-independent.

    There is no field here a student fact could travel in, and the test suite
    asserts that by enumerating the fields: spec §8's profile-free rule is an
    ongoing obligation under Tavily §9.2's perpetual licence over query text,
    so it is enforced by the shape rather than by review.
    """

    query: str
    country_code: str
    language: str
    #: The same angle as `query`, written as terms with operators for a keyword
    #: index (spec 6.3: "Brave gets the same vocabulary as terms, not a
    #: sentence" -- `intitle:vakfı "burs başvurusu"`). Empty means the provider
    #: sends `query`. Never a second topic: one angle, two spellings.
    terms: str = ""
    #: "local" or "english" -- carried so a tally can attribute a hit to the
    #: pass that found it, which is what decides whether the second pass earns
    #: its cost per country.
    phrasing: str = "local"
    #: Decision 30 (2026-09-24): breadth, page-voiced -- 10-15 per angle. The
    #: 25->100 depth win was measured per *query*; the saturation cell's
    #: breadth finding governs the pass, and Exa's own guidance names one query
    #: at 100 as the anti-pattern.
    max_results: int = 15
    denylist: tuple[str, ...] = field(default=AGGREGATOR_DOMAINS)


@dataclass
class SearchMeter:
    """What a run's searches cost, per provider, as each provider reports it.

    Exa's `costDollars.total` is what Exa billed; Brave and Tavily report no
    per-call cost, so they charge their list rate per request. This is the
    economic stop rule's spend input (spec 6.7), never a ceiling on its own --
    the harness compares it to its budget before every call.
    """

    spent_usd: dict[str, float] = field(default_factory=dict)
    calls: dict[str, int] = field(default_factory=dict)

    def charge(self, provider: str, usd: float) -> None:
        self.spent_usd[provider] = self.spent_usd.get(provider, 0.0) + usd
        self.calls[provider] = self.calls.get(provider, 0) + 1

    def total(self) -> float:
        return sum(self.spent_usd.values())


class SearchProvider(Protocol):
    """One index. `name` is a read-only property for the same reason
    `LeadSource.name` is: implementations are frozen dataclasses, and mypy
    refuses a frozen field against a settable protocol member.
    """

    @property
    def name(self) -> str: ...

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterable[str]: ...
