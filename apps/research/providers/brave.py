"""Brave: the independent second index, and the deepest per query.

It returned 84 hosts Exa did not, which is why both are in the roster rather
than the better one alone. Depth is what it is for: 3 -> 10 pages gave +47%,
+68%, +27% and +104% local funders across Germany, Türkiye, Azerbaijan and
Indonesia.

**Pagination stops on the first empty `results` array.** `more_results_available`
is documented but is not present in the response -- measured 2026-09-18 on the
paid Search plan, where a real German foundation query returned 110 results
across offsets 0-5 and empty arrays from 6 on. A loop gated on that field
would run to the ceiling on every query and pay for four empty calls.

`country` and `search_lang` are not sent. `country` measured -8 local funders
in Indonesia and inert in the other three; `search_lang` is measurably inert
(Jaccard of the result sets with and without: 1.000, 0.985, 1.000, 1.000). The
local-language steering happens in the query text instead (see
`domains.Steering`).

Permitted by written permission from Brave (owner correspondence 2026-09-17),
condition: Output may not train a competing search index.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..egress import fetch_json_api
from . import SearchMeter, SearchRequest
from .base import ProviderUnavailable, SiteSearchResult, urls_on_domain

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

#: Brave's documented maximum. A ceiling, not an expectation: a real query
#: exhausts around offset 5, and the empty-page check is what usually stops
#: the loop. This exists so a provider that kept answering could not turn one
#: query into unbounded spend.
_MAX_OFFSET = 9

#: Brave's maximum page size.
_COUNT = 20

#: $5 per 1,000 requests on the Search plan (spec section 13). Brave reports no
#: per-call cost, so the list rate is charged per request made -- an empty
#: page included, because it was billed.
BRAVE_REQUEST_USD = 0.005


@dataclass(frozen=True)
class BraveProvider:
    api_key: str = field(repr=False)
    name: str = "brave"
    get: Callable[..., dict[str, object]] = field(default=fetch_json_api)
    #: A public HTTPS URL for tehsil-funders.goggle. Empty until the file is
    #: hosted, and the parameter is then omitted: the Goggle is a precision
    #: win (aggregators 33% -> 14% in the probe), never a recall one, so the
    #: sweep is correct without it and merely noisier.
    goggle_url: str = ""

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        for offset in range(_MAX_OFFSET + 1):
            params: dict[str, object] = {
                "q": request.terms or request.query,
                "count": _COUNT,
                "offset": offset,
                "result_filter": "web",
            }
            if self.goggle_url:
                params["goggles"] = self.goggle_url
            data: Mapping[str, Any] = self.get(
                BRAVE_SEARCH_URL,
                params=params,
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            )
            if meter is not None:
                meter.charge(self.name, BRAVE_REQUEST_USD)
            results = (data.get("web") or {}).get("results") or []
            if not results:
                return
            for item in results:
                url = str(item.get("url") or "")
                if url:
                    yield url


def brave_site_search(
    *,
    query: str,
    domain: str,
    api_key: str | None = None,
    get: Callable[..., dict[str, object]] = fetch_json_api,
    count: int = 10,
) -> SiteSearchResult:
    """One `site:` page: the step-3 fallback when Exa returns nothing (spec 9.2).

    One request, never paginated -- a fallback that walks ten pages is not a
    fallback. The cost is Brave's list price per request (master spec 13);
    Brave's response carries no cost field of its own. A hit off `domain` is
    dropped here, before any caller could fetch it.
    """
    from django.conf import settings

    key = api_key if api_key is not None else settings.BRAVE_API_KEY
    if not key:
        raise ProviderUnavailable("BRAVE_API_KEY is not set")
    try:
        data = get(
            BRAVE_SEARCH_URL,
            params={"q": f"site:{domain} {query}", "count": count, "result_filter": "web"},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
    except Exception as error:  # transport, HTTP status, JSON -- one outcome here
        raise ProviderUnavailable("brave search failed") from error
    web = data.get("web") if isinstance(data, dict) else None
    results = web.get("results") if isinstance(web, dict) else None
    return SiteSearchResult(
        urls=urls_on_domain(results, domain),
        cost_usd=settings.BRAVE_USD_PER_REQUEST,
        provider="brave",
    )
