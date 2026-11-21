"""Naver OpenAPI Web Search (`webkr.json`) provider for South Korean (`.ac.kr`) discovery.

Used as an optional secondary index for South Korea (`KR`) when `NAVER_CLIENT_ID` and
`NAVER_CLIENT_SECRET` are configured, complementing Exa, Brave, Study in Korea (GKS),
and Korean foundation/IST closed lists (`UST`, `KAIST`, `GIST`, `UNIST`, `KDI School`,
`POSCO TJ Park`). Yields URLs only and records cost in `SearchMeter`.
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
from .base import ProviderUnavailable, SiteSearchResult, on_domain

NAVER_SEARCH_URL = "https://openapi.naver.com/v1/search/webkr.json"
NAVER_REQUEST_USD = 0.002


def _is_denied(url: str, denylist: tuple[str, ...]) -> bool:
    host = (urlsplit(url).hostname or "").casefold().strip(".")
    if not host:
        return True
    if is_catalogue(host):
        return True
    return any(host == d or host.endswith(f".{d}") for d in denylist)


@dataclass(frozen=True)
class NaverProvider:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    name: str = "naver"
    endpoint_url: str = NAVER_SEARCH_URL
    get: Callable[..., dict[str, object]] = field(
        default=partial(fetch_json_api, retry_throttled=True)
    )

    def search(self, request: SearchRequest, meter: SearchMeter | None = None) -> Iterator[str]:
        if not (self.client_id and self.client_secret):
            raise ProviderUnavailable("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are not set")
        query_text = request.terms or request.query
        data: Mapping[str, Any] = self.get(
            self.endpoint_url,
            params={
                "query": query_text,
                "display": min(max(request.max_results, 1), 100),
                "start": 1,
            },
            headers={
                "Accept": "application/json",
                "X-Naver-Client-Id": self.client_id,
                "X-Naver-Client-Secret": self.client_secret,
            },
        )
        if meter is not None:
            meter.charge(self.name, NAVER_REQUEST_USD)
        items = data.get("items") or []
        seen: set[str] = set()
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            # Naver webkr returns the target URL in `link` (or `url` in normalized mocks).
            url = str(item.get("link") or item.get("url") or "").strip()
            if not url or url in seen or _is_denied(url, request.denylist):
                continue
            seen.add(url)
            yield url


def naver_site_search(
    *,
    query: str,
    domain: str,
    client_id: str,
    client_secret: str,
    get: Callable[..., dict[str, object]] = fetch_json_api,
    count: int = 10,
) -> SiteSearchResult:
    """Domain-restricted `site:<domain>` search via Naver OpenAPI for `.ac.kr` domains."""
    if not (client_id and client_secret):
        raise ProviderUnavailable("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are not set")
    clean_query = query.strip()
    if clean_query.lower().startswith(f"site:{domain.lower()}"):
        clean_query = clean_query[len(f"site:{domain}") :].strip()
    try:
        data = get(
            NAVER_SEARCH_URL,
            params={
                "query": f"site:{domain} {clean_query}".strip(),
                "display": min(max(count, 1), 100),
            },
            headers={
                "Accept": "application/json",
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
        )
    except Exception as error:
        raise ProviderUnavailable("naver search failed") from error
    items = data.get("items") if isinstance(data, dict) else None
    urls: list[str] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or item.get("url") or "").strip()
        if url and on_domain(url, domain) and url not in urls:
            urls.append(url)
    return SiteSearchResult(
        urls=tuple(urls),
        cost_usd=NAVER_REQUEST_USD,
        provider="naver",
    )
