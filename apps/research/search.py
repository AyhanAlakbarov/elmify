"""Live search as a lead source (design §2.2b).

Search results are untrusted candidate URLs, never evidence. Only the URL is read
off a provider response and the rest is discarded -- no snippet, title, ranking or
result object is ever persisted, which is what keeps retention inside the provider's
terms rather than resting on an argument (CLAUDE.md, "Search providers: what may be
kept"). Provenance comes from the origin: the URL is fetched and verified against the
institution's own server afterwards, and the provider was only a pointer. The provider is
an egress destination, budgeted on the same call, and constrained at the query
boundary where it supports it. A result on a catalogue host is still returned
as a lead -- ``ResearchLead.from_url`` demotes it to AGGREGATOR, so it routes
research and cannot support a claim.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID

# Element/ParseError are a type annotation and an exception class only --
# the actual parse below runs through defusedxml.ElementTree.fromstring.
from xml.etree.ElementTree import Element, ParseError  # nosec B405

from defusedxml import ElementTree

from apps.documents.templatetags.cv_countries import country_name
from apps.ratelimit import rate_limited

from .discovery import (
    DiscoveryQuery,
    LeadBudgetExceeded,
    ResearchLead,
    RunBudget,
    canonicalize_url,
)
from .domains import CATALOGUE_DOMAINS, is_catalogue, is_hoppable_catalogue
from .egress import FetchResult, SourceBlocked, UnsafeTarget, fetch_data_file, fetch_json_api
from .harvest import anchors
from .providers import SearchMeter, SearchRequest

#: Tavily, chosen on terms and not on index quality: §3.2's use restrictions attach
#: to "the Services", and the agreement states "the term 'Services' does not include
#: Output" -- so retaining a discovered URL is permitted by structure rather than by
#: silence. Exa (ToS §4.2(a)) and Brave (which defines "Search Results" as *any*
#: output from the API) both forbid it; Google Custom Search is closed to new
#: customers. Measured too: Tavily reached 16/16 on the recall fixture set and no
#: other provider added a single target (scripts/search_recall.py). Do not swap this
#: without reading the replacement's *definitions* section -- definitions decide this
#: question, not caching clauses. See
#: docs/superpowers/research/2026-08-30-live-search-synthesis.md.
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

#: Tavily Extract and Crawl -- the fetch path for programme pages since the owner
#: decision of 2026-09-15 (docs/superpowers/specs/2026-09-15-cv-requirement-corpus-design.md).
#: Same vendor and same terms as search: "Services" excludes Output, so extracted
#: text may be retained. Measured against Firecrawl /scrape on Türkiye Bursları and
#: FAU: identical requirement lines; and it reads DAAD and Sciences Po, which refuse
#: this platform's own address outright.
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
TAVILY_CRAWL_URL = "https://api.tavily.com/crawl"
#: Tavily /map: a guided walk of one site that returns URLs and nothing else
#: (fetch-engine 7.3a). Same key as /search.
TAVILY_MAP_URL = "https://api.tavily.com/map"
#: Tavily's per-call ceiling for /extract.
_EXTRACT_BATCH = 20

#: Tavily runs the extract/crawl server-side and answers when it is done; the egress
#: default of 20 s is tuned for one page and killed the first vendor pass on programme 2.
_EXTRACT_READ_TIMEOUT = 60.0
_CRAWL_READ_TIMEOUT = 120.0

#: The background discovery budget's fallback actor (§7.6). The pipeline passes
#: the tenant id instead, so cost is attributed per tenant (CLAUDE.md).
DISCOVERY_ACTOR = UUID("00000000-0000-0000-0000-000000000001")

DEGREE_WORDS = {"MASTER": "master's degree"}


@dataclass(frozen=True)
class SearchSource:
    api_key: str = field(repr=False)
    name: str = "search"
    actor_id: UUID = DISCOVERY_ACTOR
    calls_per_hour: int = 60
    budget: RunBudget | None = None
    source_type: str = "PROGRAM"
    evidence_strength: str = "DIRECT"
    post: Callable[..., dict[str, object]] = field(default=fetch_json_api)
    #: A search hit is one page, not one programme's site.
    one_programme_per_link: bool = False
    #: A search hit says nothing about who awards the programme.
    awards_jointly: bool = False
    #: What this source's searches cost -- the fix for audit finding 3:
    #: find() used to post its own uncharged Tavily request. A fresh meter per
    #: source by default; a caller that wants to read the total cost across
    #: several sources in one run passes its own.
    meter: SearchMeter = field(default_factory=SearchMeter)

    def query_text(self, query: DiscoveryQuery) -> str:
        # Every ISO country, not a hand-kept corridor list: a code missing from
        # a short table went out as "NL" and quietly searched worse.
        country = country_name(query.country_code.upper())
        degree = DEGREE_WORDS.get(query.degree_level, query.degree_level.casefold())
        # No language filter: a German-language page routinely describes an
        # English-taught programme (§2.2). Teaching language is gated on the
        # extracted, cited TeachingLanguageClaim instead.
        return f"{query.field} {degree} {country} official funding scholarship"

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        # Delegates the actual call to the one metered Tavily client
        # (providers.tavily.TavilyProvider) instead of posting its own request:
        # that was audit finding 3 -- a second, uncharged client with its own,
        # uncapped exclusion list. Only the lead-shaping below is this source's own.
        if self.budget is not None:
            self.budget.spend("searches")
        if rate_limited(
            "discovery-search", self.actor_id, limit=self.calls_per_hour, window_seconds=3_600
        ):
            raise LeadBudgetExceeded("discovery search budget exhausted")
        from .providers.tavily import TavilyProvider  # local: providers.tavily imports this module

        provider = TavilyProvider(api_key=self.api_key, post=self.post)
        # No includeDomains: nothing ever set it. Add it back with the caller
        # that needs it, not before.
        request = SearchRequest(
            query=self.query_text(query),
            country_code=query.country_code,
            language="",
            max_results=query.max_leads,
            denylist=tuple(CATALOGUE_DOMAINS),
        )
        for url in provider.search(request, self.meter):
            host = urlsplit(url).hostname or ""
            if not url:
                continue
            if is_catalogue(host) and not is_hoppable_catalogue(host):
                continue  # commercial aggregator: nothing behind it to hop to
            if is_catalogue(host) and self.evidence_strength == "ECOSYSTEM_CLUE":
                continue  # an organisation query that landed on a catalogue is noise
            try:
                yield ResearchLead.from_url(
                    url,
                    source_type=self.source_type,
                    funding_family="",
                    evidence_strength=self.evidence_strength,
                    discovered_by=self.name,
                )
            except ValueError:
                continue  # not HTTPS: canonicalize_url refuses it


#: Path fragments that mark an organisation's own funding/admissions pages.
FUNDING_PATH_TERMS = (
    "scholarship",
    "fellowship",
    "funding",
    "stipend",
    "admission",
    "graduate",
    "doctoral",
    "phd",
)
_MAX_INDEX_CHILDREN = 3


def funding_links(page: FetchResult, *, limit: int = 5) -> list[str]:
    """Funding and admissions pages linked from a page, on that page's own host.

    A consortium's front door routinely carries no funding text at all -- the
    money is a room inside the same site (shadow run 2, §2.2). The links are
    read off a response already retrieved, so finding them costs no extra fetch,
    and the same ``FUNDING_PATH_TERMS`` that triage a sitemap triage them here.
    Sitemaps are not a substitute: ``www.master-wocc.eu`` publishes none, and
    links every one of its funding pages from the home page.

    Off-host links are dropped. The hop is legitimate because a seed catalogue
    vouched for *this host*, and that provenance does not travel to the dozen
    unrelated sites every such page links out to.
    """
    host = urlsplit(page.final_url).hostname or ""
    found: list[str] = []
    seen: set[str] = set()
    try:
        seen.add(canonicalize_url(page.final_url))  # never hop a page onto itself
    except ValueError:
        return found
    for anchor in anchors(page.body):
        if len(found) >= limit:
            break
        target = urljoin(page.final_url, anchor.href)
        split = urlsplit(target)
        if (split.hostname or "") != host:
            continue
        if not any(term in split.path.casefold() for term in FUNDING_PATH_TERMS):
            continue
        try:
            url = canonicalize_url(target)
        except ValueError:
            continue  # not HTTPS
        if url in seen:
            continue
        seen.add(url)
        found.append(url)
    return found


def _locs(root: Element) -> list[str]:
    return [
        element.text.strip()
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "loc" and element.text
    ]


def sitemap_urls(
    host: str,
    *,
    fetch: Callable[..., FetchResult] = fetch_data_file,
    depth: int = 1,
    limit: int = 2_000,
) -> Iterator[str]:
    """Every URL an organisation publishes about itself, from its own sitemap.

    A missing, blocked or malformed sitemap is a dead end, not an error: the
    organisation lead still stands on its own as an ECOSYSTEM_CLUE.

    **A sitemap is a data file, not a page, so it goes through our own transport
    -- the same boundary the DEQAR CSVs and the JSON fixtures sit on.** Measured
    2026-09-19: Firecrawl returns https://globed.eu/sitemap_index.xml through
    its `html` format as a browser-viewer wrapper, not the document -- the XML
    declaration turned into an HTML comment and the root wrapped in
    `<html><body>`, 1,610 bytes at contentType text/xml.

    **It does not fail to parse, and the `except (ParseError, ValueError)` below
    never fires -- that diagnosis was wrong and is the reason this paragraph is
    long.** `ElementTree.fromstring` succeeds on the wrapper. What the wrapper
    destroys is the ROOT TAG: it is `html`, not `sitemapindex`, so the index hop
    below never runs and _sitemap returns the child *sitemap files* as if they
    were content URLs. Every one ends in `.xml`, FUNDING_PATH_TERMS drops the
    lot, and EntityExpansionSource yields zero programme URLs per organisation
    while reporting success. Pinned by
    test_a_vendor_rendered_sitemap_yields_no_programme_urls.

    An earlier review assumed Firecrawl would instead return an EMPTY `html` for
    XML and degrade to scrape.do's raw bytes; it does not, so it never degrades.

    Unwrapping the vendor's rendering, or asking for `rawHtml`, is guessing at
    someone else's markup pipeline for a document they were never asked to
    render. `fetch_data_file` returns the origin's own bytes and
    ALLOWED_CONTENT_TYPES already admits application/xml and text/xml.

    The cost of the boundary, stated in full, because PacedFetch does three
    things and naming only one of them understates it (pipeline.py::__call__).
    A sitemap fetch is now outside ALL THREE: the per-domain lease, the
    RunBudget["fetches"] spend, and the per-actor rate_limited("discovery-fetch")
    hourly cap. At up to 10 organisations per query that is 10 x (1 +
    _MAX_INDEX_CHILDREN) requests, unpaced, unbudgeted and uncapped.

    Accepted for now: they are first-party requests for a static file the host
    publishes for crawlers, they spend no vendor credits, and _MAX_INDEX_CHILDREN
    bounds the fan-out. Exactly as registers.py's CSV downloads are. **Follow-up,
    not done here: give this path its own budget and cap** -- PacedFetch's are
    shaped for the vendor page fetch and cannot simply be reused.
    """
    yield from _sitemap(f"https://{host}/sitemap.xml", fetch=fetch, depth=depth, limit=limit)


def _sitemap(
    url: str, *, fetch: Callable[..., FetchResult], depth: int, limit: int
) -> Iterator[str]:
    try:
        body = fetch(url).body
    except (SourceBlocked, UnsafeTarget, OSError):
        return
    try:
        root = ElementTree.fromstring(body)
    except (ParseError, ValueError):
        # defusedxml's own refusals (DefusedXmlException) subclass ValueError.
        return
    locations = _locs(root)
    if root.tag.rsplit("}", 1)[-1] == "sitemapindex" and depth > 0:
        for child in locations[:_MAX_INDEX_CHILDREN]:
            yield from _sitemap(child, fetch=fetch, depth=depth - 1, limit=limit)
        return
    yield from locations[:limit]


@dataclass(frozen=True)
class EntityExpansionSource:
    """Hidden gems resolve by entity expansion, not query cleverness (§2.3)."""

    #: Still the concrete Tavily source, not `providers.SearchProvider`, and
    #: that is recorded rather than shimmed. Roster §4.6 calls for the
    #: protocol here -- it is what would let an expansion run on Exa where Exa
    #: is the better index for the family -- but `find` below calls
    #: `dataclasses.replace(self.search, name=..., source_type=...,
    #: evidence_strength=...)`, three `SearchSource` fields the protocol does
    #: not carry. Retyping needs `find` restructured to compose a
    #: `SearchRequest`, which belongs with the sweep harness: its first
    #: provider-passing caller. A shim that makes a protocol look like a
    #: concrete class is how a seam stops meaning anything. Spec §13.
    search: SearchSource
    name: str = "entity-expansion"
    #: Sitemaps only -- and a sitemap is a data file, see sitemap_urls. This is
    #: NOT the vendor page fetcher; handing it one sends an XML document
    #: through a renderer that wraps it in <html><body> and yields nothing.
    fetch: Callable[..., FetchResult] = field(default=fetch_data_file)
    per_org: int = 10
    #: A search hit is one page, not one programme's site.
    one_programme_per_link: bool = False
    #: A search hit says nothing about who awards the programme.
    awards_jointly: bool = False

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        organisations = replace(
            self.search,
            name=self.name,
            source_type="RESEARCH_ORGANIZATION",
            evidence_strength="ECOSYSTEM_CLUE",
        )
        organisation_query = replace(
            query,
            field=f"{query.field} research institute graduate school",
            max_leads=min(query.max_leads, 10),
        )
        for organisation in organisations.find(organisation_query):
            yield organisation
            host = urlsplit(organisation.canonical_url).hostname or ""
            if not host:
                continue
            found = 0
            for url in sitemap_urls(host, fetch=self.fetch):
                if found >= self.per_org:
                    break
                split = urlsplit(url)
                # A sitemap may name any URL it likes. Only the organisation's
                # own pages inherit the organisation's provenance, so a <loc>
                # pointing off-host is dropped rather than promoted to DIRECT.
                if (split.hostname or "") != host:
                    continue
                if not any(term in split.path.casefold() for term in FUNDING_PATH_TERMS):
                    continue
                try:
                    lead = ResearchLead.from_url(
                        url,
                        source_type="RESEARCH_ORGANIZATION",
                        funding_family="",
                        discovered_by=self.name,
                    )
                except ValueError:
                    continue
                found += 1
                yield lead


def _url_key(url: str) -> str:
    """Tavily echoes a URL with or without its trailing slash; match on either."""
    return url.strip().rstrip("/")


def tavily_extract(
    urls: Sequence[str],
    *,
    api_key: str,
    post: Callable[..., dict[str, object]] = fetch_json_api,
) -> dict[str, str]:
    """Return {url: markdown} for every URL Tavily could read.

    A URL Tavily could not read is simply absent -- the caller decides whether
    absence means `blocked` or `not_found`; this function does not guess. Keys
    are the URLs exactly as passed, so a caller can look its own key back up.
    """
    out: dict[str, str] = {}
    for start in range(0, len(urls), _EXTRACT_BATCH):
        batch = list(urls[start : start + _EXTRACT_BATCH])
        data: Mapping[str, Any] = post(
            TAVILY_EXTRACT_URL,
            payload={"urls": batch, "extract_depth": "advanced", "format": "markdown"},
            headers={"Authorization": f"Bearer {api_key}"},
            read_timeout=_EXTRACT_READ_TIMEOUT,
        )
        by_key = {
            _url_key(str(item.get("url") or "")): str(item.get("raw_content") or "")
            for item in list(data.get("results") or [])
            if isinstance(item, Mapping)
        }
        for url in batch:
            text = by_key.get(_url_key(url))
            if text:
                out[url] = text
    return out


def tavily_crawl(
    url: str,
    *,
    api_key: str,
    instructions: str,
    limit: int = 30,
    post: Callable[..., dict[str, object]] = fetch_json_api,
) -> dict[str, str]:
    """Return {page_url: markdown} for every page a guided crawl of `url` returned.

    The vendor pass of the corpus pool (spec, "Building the ground truth"). Its
    output is Tavily's own extract of each page, so a sentence found here is
    already verified against the same extractor the digest uses.
    """
    data: Mapping[str, Any] = post(
        TAVILY_CRAWL_URL,
        payload={
            "url": url,
            "instructions": instructions,
            "max_depth": 2,
            "limit": limit,
            "extract_depth": "advanced",
            "format": "markdown",
            # Tavily defaults this to true. A programme's requirements are what the
            # programme's own site says -- off-origin, a page it merely links to becomes
            # a sentence it published (CLAUDE.md, "The CV-requirement corpus").
            "allow_external": False,
        },
        headers={"Authorization": f"Bearer {api_key}"},
        read_timeout=_CRAWL_READ_TIMEOUT,
    )
    return {
        str(item.get("url")): str(item.get("raw_content") or "")
        for item in list(data.get("results") or [])
        if isinstance(item, Mapping) and item.get("url")
    }
