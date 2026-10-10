"""Tavily, in two shapes: a site-restricted fallback, and the discovery leg.

`tavily_site_search` is the **domain-restricted** one -- the keyword fallback
when Exa returns nothing for a domain. Research-fit calls it.

`TavilyProvider` is the **open-web** one: name-to-site resolution, host
inventory, and the local-language discovery leg. Its terms are the cleanest of
any provider surveyed -- its restrictions attach to "the Services", which it
defines to exclude "Output" -- so its retention is permitted by structure
rather than by silence. That is why it keeps the jobs where we hold a URL or a
name already, and why it is no longer *the* provider: provider choice is
settled by measurement now (roster §4.13), and Tavily alone reaches 165
funding-relevant hosts where four indexes reach 507.

`basic` depth on both (advanced costs two credits and measured five times
worse at resolution, roster §4.13a); never `language`/`filter_by_language` --
measured -1.0 on the 377-funder German key and -2.3 with the filter, harmful
in three of four countries. They narrow the pool rather than re-ranking it,
and the local language belongs in the query text.

Tavily §9.2 takes a perpetual licence over every query string we send, so no
query may carry a student fact. `SearchRequest` has no field one could travel
in, and a test enumerates its fields.
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings

from ..domains import AGGREGATOR_DOMAINS, is_catalogue
from ..egress import SourceBlocked, fetch_json_api
from ..search import _CRAWL_READ_TIMEOUT, TAVILY_MAP_URL, TAVILY_SEARCH_URL
from . import SearchMeter, SearchRequest
from .base import ProviderUnavailable, SiteSearchResult, on_domain, urls_on_domain

#: Tavily bills credits, not dollars; one basic search is one credit. The
#: dollar figure is the paid plan's list rate so ceilings compare across
#: providers -- re-read the plan page when it changes.
TAVILY_CREDIT_USD = 0.008


def tavily_site_search(
    *,
    query: str,
    domain: str,
    api_key: str | None = None,
    post: Callable[..., dict[str, object]] = fetch_json_api,
    max_results: int = 5,
) -> SiteSearchResult:
    key = api_key if api_key is not None else settings.SEARCH_API_KEY
    if not key:
        raise ProviderUnavailable("SEARCH_API_KEY is not set")
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_domains": [domain],
    }
    try:
        data = post(TAVILY_SEARCH_URL, payload=payload, headers={"Authorization": f"Bearer {key}"})
    except Exception as error:
        raise ProviderUnavailable("tavily search failed") from error
    return SiteSearchResult(
        urls=urls_on_domain(data.get("results") if isinstance(data, dict) else None, domain),
        cost_usd=TAVILY_CREDIT_USD,
        provider="tavily",
    )


#: Tavily's documented maximum for one call.
_MAX_RESULTS = 20
#: "exclude_domains ... Maximum 150 domains" (docs.tavily.com, read 2026-09-26).
#: The denylist is longer, so Tavily gets its prefix -- ordered in domains.py
#: so the cut drops national catalogues -- and the rest is refused afterwards.
_EXCLUDE_MAX = 150

logger = logging.getLogger(__name__)


@functools.cache
def _log_cut(dropped: tuple[str, ...]) -> None:
    """Once per distinct cut, with the names: a count says something fell off,
    the names say whether it mattered. Cached so a lookup run per organisation
    does not repeat the same hundred names on every call."""
    logger.info(
        "tavily: %d excluded domains not sent (cap %d): %s",
        len(dropped), _EXCLUDE_MAX, ", ".join(dropped),
    )


def _exclusions(denylist: Sequence[str]) -> list[str]:
    """The prefix Tavily accepts; what did not fit is logged by name."""
    if len(denylist) > _EXCLUDE_MAX:
        _log_cut(tuple(denylist[_EXCLUDE_MAX:]))
    return list(denylist[:_EXCLUDE_MAX])

#: basic, not advanced. Advanced costs 2 credits against 1 -- halving a
#: 1,000-credit cycle to 500 calls -- and measured five times WORSE at the job
#: the roster actually gives Tavily: resolving 30 German foundations by name,
#: basic scored 10/30 and advanced 2/30, with advanced returning the Wikipedia
#: article instead of the foundation's own site on five of them. Roster §4.13a.
_DEPTH = "basic"


@dataclass(frozen=True)
class TavilyProvider:
    """The open-web shape. See this module's docstring for why `language`
    and `filter_by_language` are absent and why depth is `basic`."""

    api_key: str = field(repr=False)
    name: str = "tavily"
    post: Callable[..., dict[str, object]] = field(default=fetch_json_api)

    def _post(self, payload: dict[str, object]) -> Mapping[str, Any]:
        return self.post(
            TAVILY_SEARCH_URL,
            payload=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        data = self._post(
            {
                "query": request.query,
                "search_depth": _DEPTH,
                "max_results": min(request.max_results, _MAX_RESULTS),
                "exclude_domains": _exclusions(request.denylist),
            }
        )
        if meter is not None:
            meter.charge(self.name, TAVILY_CREDIT_USD)
        for item in data.get("results") or []:
            url = str(item.get("url") or "")
            if url:
                yield url

    def candidates(self, organisation_name: str) -> list[str]:
        """The top ten URLs for an organisation named but not linked, in rank order.

        Registers list names without URLs -- the VGM foundation register is the
        motivating case. The adapter does not choose among these: measured on 25
        German foundations, the first result was right 3 times and the best
        lexical match among these ten was right 20 times, on the same responses
        (roster §4.13a). Choosing is the resolver's job, beside the register
        writer, where the name's tokens and the register's own hints are both
        in hand.

        A catalogue or aggregator host is dropped here, not by each caller:
        the exclusion list is a request Tavily may ignore, and is cut to its
        cap, so every caller of this lookup would otherwise have to remember
        to refuse them again. Rank order is kept among what remains.
        """
        data = self._post(
            {
                "query": f'"{organisation_name}"',
                "search_depth": _DEPTH,
                "max_results": 10,
                "exclude_domains": _exclusions(AGGREGATOR_DOMAINS),
            }
        )
        urls = [str(item.get("url")) for item in (data.get("results") or []) if item.get("url")]
        return [url for url in urls if not is_catalogue(urlsplit(url).hostname or "")]


#: 2 credits per ten successful pages WITH `instructions`, 1 without
#: (docs.tavily.com, read 2026-09-23). Rounded UP per started ten, which is
#: how the tariff reads and which errs toward over-reporting our own spend --
#: the safe direction for a ceiling.
_MAP_CREDITS_PER_TEN = 2


def tavily_guided_map(
    *,
    url: str,
    instructions: str,
    select_domains: Sequence[str],
    limit: int | None = None,
    api_key: str | None = None,
    post: Callable[..., dict[str, object]] = fetch_json_api,
) -> SiteSearchResult:
    """Funnel stage 3: a guided walk of one site, URLs only.

    Beside `tavily_site_search` rather than replacing it: that function is the
    research-fit keyword fallback and answers a different question (which
    pages on this domain match this query) with a different billing line.
    One module, two endpoints, one key.

    **Nothing but the URL is read from the response.** Tavily's terms permit
    retention -- its restrictions attach to "the Services", which it defines
    to exclude "Output" -- so this is the discipline CLAUDE.md keeps on
    merits, not a contract term: a vendor's rendering of someone else's page
    goes stale silently, and a cached pointer is a second source of truth for
    a question the origin already answers.

    `allow_external` defaults to TRUE on this endpoint, so the domain filter
    is applied here as well as sent: a stray aggregator URL costs one wasted
    ladder walk and, worse, reads as a page on the institution's own site.
    **The filter narrows `urls`; the bill is counted off the raw response,
    before it -- Tavily bills per successful page MAPPED, not per URL we kept,
    so counting post-filter under-reports spend on a page that returned
    aggregator noise alongside the real ones.**

    `read_timeout=_CRAWL_READ_TIMEOUT` (120s): this walks the site
    server-side up to `max_depth=2`, the same shape as `tavily_crawl`, whose
    own comment says why the egress default (20s, tuned for one page) killed
    the first vendor pass -- a `limit=50` guided walk is exactly the request
    that default cannot cover.
    """
    key = api_key if api_key is not None else settings.SEARCH_API_KEY
    if not key:
        raise ProviderUnavailable("SEARCH_API_KEY is not set")
    payload = {
        "url": url,
        "instructions": instructions,
        "limit": int(limit if limit is not None else settings.FETCH_GUIDED_MAP_LIMIT),
        "max_depth": 2,
        "select_domains": [f"^(.*\\.)?{re.escape(domain)}$" for domain in select_domains],
    }
    try:
        data = post(
            TAVILY_MAP_URL,
            payload=payload,
            headers={"Authorization": f"Bearer {key}"},
            read_timeout=_CRAWL_READ_TIMEOUT,
        )
    except SourceBlocked as error:
        # Narrow on purpose, the same reasoning as site._call: a bare `except
        # Exception` would turn our own TypeError into a vendor outage and
        # hide the defect. `fetch_json_api` (the default `post`) raises
        # SourceBlocked for every real transport/vendor failure; anything
        # else is a bug in this module's own code and must not be laundered
        # into "the vendor is unavailable".
        #
        # A failed stage must never read as "this site has no such page":
        # the funnel treats an empty stage as a miss and moves on to the
        # navigator, which would then be paid for on every Tavily outage.
        raise ProviderUnavailable("tavily map failed") from error
    results = data.get("results") if isinstance(data, dict) else None
    raw_results = results if isinstance(results, list) else []
    urls: list[str] = []
    for item in raw_results:
        candidate = str(item.get("url") or "") if isinstance(item, dict) else str(item)
        if not candidate or candidate in urls:
            continue
        if any(on_domain(candidate, domain) for domain in select_domains):
            urls.append(candidate)
    tens = -(-len(raw_results) // 10)
    return SiteSearchResult(
        urls=tuple(urls),
        cost_usd=tens * _MAP_CREDITS_PER_TEN * TAVILY_CREDIT_USD,
        provider="tavily-map",
    )
