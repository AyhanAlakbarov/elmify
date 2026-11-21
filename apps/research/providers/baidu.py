"""Baidu Web Search provider for Chinese university (`.edu.cn`) and scholarship discovery.

Used as an optional secondary index for China (`CN`) when `BAIDU_API_KEY` is configured,
complementing Exa, Brave, and our curated Chinese closed lists (`CampusChina`, `Shanghai SGS`,
`Jiangsu Jasmine`, and `all_53_ministries_and_agencies.csv`). Yields URLs only and records cost
in `SearchMeter`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from ..domains import is_catalogue
from ..egress import fetch_json_api
from . import SearchMeter, SearchRequest
from .base import ProviderUnavailable, SiteSearchResult, urls_on_domain

BAIDU_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
BAIDU_REQUEST_USD = 0.004


def _is_denied(url: str, denylist: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").casefold().strip(".")
    if not host:
        return True
    if is_catalogue(host):
        return True
    return any(host == d or host.endswith(f".{d}") for d in denylist)


@dataclass(frozen=True)
class BaiduProvider:
    api_key: str = field(repr=False)
    name: str = "baidu"
    endpoint_url: str = BAIDU_SEARCH_URL
    get: Callable[..., dict[str, object]] = field(
        default=partial(fetch_json_api, retry_throttled=True)
    )

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        if not self.api_key:
            raise ProviderUnavailable("BAIDU_API_KEY is not set")
        query_text = request.terms or request.query
        data: Mapping[str, Any] = self.get(
            self.endpoint_url,
            params={"q": query_text, "count": request.max_results},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        if meter is not None:
            meter.charge(self.name, BAIDU_REQUEST_USD)
        raw_items = (
            data.get("references")
            or (data.get("web") or {}).get("results")
            or data.get("results")
            or []
        )
        seen: set[str] = set()
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or "").strip()
            if not url or url in seen or _is_denied(url, request.denylist):
                continue
            seen.add(url)
            yield url


def baidu_site_search(
    *,
    query: str,
    domain: str,
    api_key: str,
    get: Callable[..., dict[str, object]] = fetch_json_api,
    count: int = 10,
) -> SiteSearchResult:
    """Domain-restricted `site:<domain>` search via Baidu for `.edu.cn` university subdomains."""
    if not api_key:
        raise ProviderUnavailable("BAIDU_API_KEY is not set")
    clean_query = query.strip()
    if clean_query.lower().startswith(f"site:{domain.lower()}"):
        clean_query = clean_query[len(f"site:{domain}") :].strip()
    try:
        data = get(
            BAIDU_SEARCH_URL,
            params={"q": f"site:{domain} {clean_query}".strip(), "count": count},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
    except Exception as error:
        raise ProviderUnavailable("baidu search failed") from error
    raw_items = (
        data.get("references")
        if isinstance(data, dict) and "references" in data
        else (data.get("results") if isinstance(data, dict) else None)
    )
    return SiteSearchResult(
        urls=urls_on_domain(raw_items, domain),
        cost_usd=BAIDU_REQUEST_USD,
        provider="baidu",
    )
