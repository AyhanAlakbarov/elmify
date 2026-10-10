"""One shape for a site-restricted search, whichever index answers it.

A provider yields URLs and a billed cost and nothing else (roster §4.6):
no snippet, no title, no ranking is kept. The origin is then fetched and
verified; the provider was a pointer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit


class ProviderUnavailable(RuntimeError):
    """The provider could not answer -- no key, transport failure, malformed reply."""


@dataclass(frozen=True)
class SiteSearchResult:
    urls: tuple[str, ...]
    cost_usd: float
    provider: str


class SiteSearch(Protocol):
    def __call__(self, *, query: str, domain: str) -> SiteSearchResult: ...


def on_domain(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def urls_on_domain(items: object, domain: str) -> tuple[str, ...]:
    urls: list[str] = []
    for item in items if isinstance(items, list) else []:
        url = str(item.get("url") or "") if isinstance(item, dict) else ""
        if url and on_domain(url, domain) and url not in urls:
            urls.append(url)
    return tuple(urls)
