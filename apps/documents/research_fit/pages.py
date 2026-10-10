"""Fetch one search hit through the research fetch path and turn it into
sentences (design D4). `retrieve_official_source` now fetches through the
Firecrawl/scrape.do vendor path (CLAUDE.md, "Web fetching"): DNS resolution
and redirect-following happen on the vendor's own infrastructure, not ours,
and only the landing URL is validated -- inside each vendor module
(`apps/research/fetch/firecrawl.py`, `.../scrapedo.py`), which both raise
rather than fall back to the requested URL when a landing URL is missing, so
`fetched.final_url` is trustworthy when present. That is why the checks below
matter: `on_domain` and the https scheme check run against that `final_url`
here, because nothing upstream of this function enforces the institution's
domain. A client-rendered shell is recorded as unreadable, never as a page
that says nothing.

The page text is cached per tenant for a week, keyed by nothing about a
student, on the same shared backend apps.ratelimit uses in production
(Redis/Valkey; config/settings/production.py requires CACHE_URL).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from django.core.cache import cache

from apps.research.discovery import retrieve_official_source
from apps.research.egress import FetchResult
from apps.research.harvest import content_digest
from apps.research.providers.base import on_domain
from apps.research.reader import is_shell, page_lines

from .split import page_sentences

PAGE_CACHE_TTL_SECONDS = 7 * 24 * 3600
PageOutcome = Literal["ok", "off_domain", "unreadable", "fetch_failed"]


@dataclass(frozen=True)
class Page:
    url: str
    digest: str
    sentences: tuple[str, ...]
    #: `%Y-%m-%d` when these sentences came from an Internet Archive capture
    #: (rung 6), empty when the page was read live. `retrieve_official_source`
    #: returns `Outcome.ARCHIVED` as SERVED and the page's `final_url` is the
    #: ORIGINAL url, so a capture up to a year old
    #: (`FETCH_ARCHIVE_MAX_AGE_DAYS`) is otherwise indistinguishable here from
    #: what the institution says today -- and these sentences are quoted in a
    #: student's letter. Same producer and format as
    #: `snapshot.archive_marker`'s date; this consumer has no snapshot row to
    #: stamp, so it travels on the Page and lands in the NarrativeInput's
    #: `provenance` beside `source_url` and `page_digest`.
    captured_at: str = ""


def _cache_key(tenant_id: UUID, url: str) -> str:
    return f"research-fit:page:{tenant_id}:{hashlib.sha256(url.encode()).hexdigest()}"


def fetch_page(
    url: str,
    *,
    domain: str,
    tenant_id: UUID,
    fetch: Callable[[str], FetchResult] = retrieve_official_source,
    use_cache: bool = True,
) -> tuple[Page | None, PageOutcome]:
    key = _cache_key(tenant_id, url)
    cached = cache.get(key) if use_cache else None
    if isinstance(cached, dict):
        return Page(
            url=cached["url"], digest=cached["digest"], sentences=tuple(cached["sentences"]),
            # A week-long TTL means most reads are cache hits, so a field the
            # cached dict does not carry is a field almost nobody sees.
            # `.get` rather than `[...]`: entries written before this key
            # existed are still live.
            captured_at=cached.get("captured_at", ""),
        ), "ok"
    try:
        fetched = fetch(url)
    except Exception:  # SourceBlocked, UnsafeTarget, transport -- one outcome, never a raise (D11)
        return None, "fetch_failed"
    if not on_domain(fetched.final_url, domain):
        return None, "off_domain"
    # validate_public_url permits http, and on_domain compares host only, so
    # an http:// hit (or an https->http redirect on the same host) would
    # otherwise be fetched in plaintext and its sentences cited as a claim --
    # the same hazard require_same_origin's scheme check guards elsewhere
    # (CLAUDE.md, "Decision B vouches for the SOURCE ROW, not the BYTES").
    if urlsplit(fetched.final_url).scheme != "https":
        return None, "off_domain"
    lines = page_lines(fetched)
    text = "\n".join(lines)
    if is_shell(text, fetched.body):
        return None, "unreadable"
    page = Page(
        url=fetched.final_url,
        digest=content_digest(fetched.body),
        sentences=page_sentences(lines),
        captured_at=getattr(fetched, "captured_at", "") or "",
    )
    cache.set(
        key,
        {
            "url": page.url, "digest": page.digest, "sentences": list(page.sentences),
            "captured_at": page.captured_at,
        },
        timeout=PAGE_CACHE_TTL_SECONDS,
    )
    return page, "ok"
