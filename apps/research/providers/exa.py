"""Exa, in two shapes, because two callers ask different questions.

`exa_site_search` is the **domain-restricted** one (design D3): one
institution's host, five results, no `contents` -- three cheap fetches make
highlights unnecessary and keep the URL-only discipline. `costDollars.total`
is what Exa billed; it is recorded, never estimated. Research-fit calls it.

`ExaProvider` is the **open-web discovery** one: the primary index for the
three families no register covers. Best single performer in the 2026-09-17
probe (132 unique hosts, 79% origin, strongest on the Azerbaijani and Turkish
legs) and the only one that does not decay -- across 99 queries in one cell
its per-batch contribution barely moved (124, 63, 45, 43, 45, 38, 34, 42, 42)
while Brave fell 81 -> 11 and Tavily 62 -> 5. So a sweep drops the decaying
engines early and keeps Exa running.

Two parameters the vendor recommends are not set on the discovery path, and
both are measurements rather than opinions: `category: "company"` scored -2.7
points on the 377-funder German key because its entity pipeline is tuned to
businesses and misses foundations, and `includeText` -0.8 because it narrows
the pool like every other filter. Depth measured 25 -> 100 results multiplying
local funders by 3.4, 2.0, 1.7 and 2.2 across four countries -- but that win
was measured per *query*. Decision 30 (2026-09-24) governs the sweep instead:
breadth, page-voiced -- 10-15 results per angle, run across more queries with
different angles, never one query at n=100 (Exa's own guidance names that the
anti-pattern).

Permitted by written permission from Exa (owner correspondence 2026-09-17)
with one condition: Output may not train a competing search index. Neither
shape stores Output at all -- both yield URLs and discard the rest of the
response at the boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from ..egress import fetch_json_api
from . import SearchMeter, SearchRequest
from .base import ProviderUnavailable, SiteSearchResult, urls_on_domain

EXA_SEARCH_URL = "https://api.exa.ai/search"


def exa_site_search(
    *,
    query: str,
    domain: str,
    api_key: str | None = None,
    post: Callable[..., dict[str, object]] = fetch_json_api,
    num_results: int = 5,
) -> SiteSearchResult:
    key = api_key if api_key is not None else settings.EXA_API_KEY
    if not key:
        raise ProviderUnavailable("EXA_API_KEY is not set")
    payload = {
        "query": query,
        "type": "auto",
        "numResults": num_results,
        "includeDomains": [domain, f"*.{domain}"],
    }
    try:
        data = post(EXA_SEARCH_URL, payload=payload, headers={"x-api-key": key})
    except Exception as error:  # transport, HTTP status, JSON -- all one outcome here
        raise ProviderUnavailable("exa search failed") from error
    cost = data.get("costDollars") if isinstance(data, dict) else None
    total = float(cost.get("total", 0.0)) if isinstance(cost, dict) else 0.0
    return SiteSearchResult(
        urls=urls_on_domain(data.get("results"), domain), cost_usd=total, provider="exa"
    )


@dataclass(frozen=True)
class ExaProvider:
    """The open-web discovery shape. See this module's docstring for why
    `category` and `includeText` are absent and `numResults` defaults to 15."""

    api_key: str = field(repr=False)
    name: str = "exa"
    post: Callable[..., dict[str, object]] = field(default=fetch_json_api)

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        payload: dict[str, object] = {
            "query": request.query,
            # `auto` lets Exa pick neural or keyword per query. Pinning either
            # was not measured and the default was what the probe scored.
            "type": "auto",
            "numResults": request.max_results,
            "excludeDomains": list(request.denylist),
        }
        data: Mapping[str, Any] = self.post(
            EXA_SEARCH_URL,
            payload=payload,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
        )
        if meter is not None:
            # What Exa billed, read from the response and nothing else read
            # from it but URLs. Absent is charged as zero rather than guessed:
            # the monthly reconciliation catches a response that stopped
            # carrying it.
            cost = data.get("costDollars")
            billed = float(cost.get("total", 0.0)) if isinstance(cost, dict) else 0.0
            meter.charge(self.name, billed)
        for item in data.get("results") or []:
            url = str(item.get("url") or "")
            if url:
                yield url
