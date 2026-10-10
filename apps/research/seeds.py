"""Seed-catalogue lead sources (design §2.2a).

Every lead here is an AGGREGATOR lead: catalogues route research and seed
identity, and never support a claim (§2.5, §7.2). Catalogue-asserted facts are
deliberately not carried onto the lead, so there is no path by which they could
become evidence.

Only the EACEA Erasmus Mundus catalogue ships in this increment. A DAAD
International Programmes adapter was planned and deliberately not written: the
2026-08-27 access-terms review could not establish that DAAD's published terms
permit automated retrieval and storage, and the design's rule is that an adapter
for such a host is not written at all -- it becomes a ConsultantResearchTask
instead. See docs/superpowers/research/2026-08-27-seed-source-access-terms.md.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from .discovery import DiscoveryQuery, ResearchLead, retrieve_official_source
from .domains import is_catalogue
from .egress import FetchResult
from .harvest import anchors


@dataclass(frozen=True)
class HtmlCatalogue:
    """A catalogue whose listing is plain HTML: harvest the detail links.

    Identity is not read off the listing -- these pages give a link and little
    else, and a catalogue may not support a claim anyway (§2.5). Identity comes
    from the official page's own extraction.
    """

    name: str
    list_url: str
    funding_family: str
    #: Anchors to take. Exactly one of these two selects the links:
    #: ``detail_pattern`` matches a URL shape, and ``exclude_suffix`` instead
    #: takes every anchor *outside* the catalogue's own domain. The second is
    #: what a catalogue that links straight to the programme's own site needs.
    detail_pattern: str = ""
    exclude_suffix: str = ""
    #: What the harvested link is. A catalogue's own detail page is an
    #: AGGREGATOR and may never support a claim (§2.5); a programme's own site
    #: is the origin, and ``from_url`` re-demotes it if the host turns out to be
    #: a catalogue after all, so setting this wrongly cannot upgrade a catalogue.
    source_type: str = "AGGREGATOR"
    country_code: str = ""  # "" -- the catalogue is not corridor-specific
    page_param: str = ""
    pages: int = 3
    fetch: Callable[..., FetchResult] = field(default=retrieve_official_source)
    #: Whether each harvested link is one programme's own site. EACEA's listing
    #: is one row per EMJM consortium, so the pages behind one of its links
    #: describe one programme and may pool their gate facts. A catalogue whose
    #: links are institution front doors must leave this False.
    one_programme_per_link: bool = False
    #: Whether every programme this catalogue lists is awarded by several
    #: universities together. True for EACEA: its listing is one row per
    #: Erasmus Mundus consortium.
    awards_jointly: bool = False

    def _wanted(self, target: str, pattern: re.Pattern[str] | None) -> bool:
        if pattern is not None:
            return bool(pattern.match(target))
        host = (urlsplit(target).hostname or "").casefold()
        # No host: a relative link, i.e. the catalogue's own navigation.
        # is_catalogue also drops the social links every such page carries.
        return bool(host) and not host.endswith(self.exclude_suffix) and not is_catalogue(host)

    def find(self, query: DiscoveryQuery) -> Iterator[ResearchLead]:
        if self.country_code and query.country_code.upper() != self.country_code:
            return
        pattern = re.compile(self.detail_pattern) if self.detail_pattern else None
        seen: set[str] = set()
        for page in range(self.pages if self.page_param else 1):
            url = f"{self.list_url}?{self.page_param}={page}" if self.page_param else self.list_url
            matched = 0
            for anchor in anchors(self.fetch(url).body):
                target = urljoin(url, anchor.href)
                if target in seen or not self._wanted(target, pattern):
                    continue
                seen.add(target)
                try:
                    lead = ResearchLead.from_url(
                        target,
                        source_type=self.source_type,
                        funding_family=self.funding_family,
                        discovered_by=self.name,
                    )
                except ValueError:
                    # canonicalize_url refuses plain HTTP and malformed targets.
                    # A live run found one http:// consortium link on the real
                    # listing, and letting that propagate cost every other
                    # programme on the page. One bad anchor is not a bad page.
                    continue
                matched += 1
                yield lead
            if not matched:
                return


#: Verified 2026-08-28: the listing links straight to each consortium's own
#: site -- 20 per page, ?page=N paginating cleanly to roughly 200 programmes.
#:
#: It used to harvest ``erasmus-plus.ec.europa.eu/projects/search/details/<id>``
#: instead, and that is why the first shadow run wrote zero rows: those detail
#: pages are refused server-side with HTTP 403, and re-probing after the
#: robots.txt policy changed showed the refusal is EACEA's edge rather than our
#: own compliance, so it did not lift. The detail pages were never needed. A
#: catalogue detail page is an AGGREGATOR that may not support a claim (§2.5);
#: the consortium's own site is the origin, and it is on the same listing.
#:
#: **That 403 is those URLs and nothing wider -- do not read it as "EACEA
#: refuses us".** Re-measured 2026-09-14, all three at once: the detail page
#: still returns 403, ``/projects/search`` returns **200**, and the endpoint
#: that page actually calls --
#: ``POST ec.europa.eu/programmes/service/search/project/search`` -- returns
#: **200 to plain curl**, no browser, no session, no token. That API publishes
#: each project's participating organisations with name, country, city, PIC and
#: website, which is the partner list a joint programme needs. The wider reading
#: of this comment cost three wrong attempts before it was measured; see
#: docs/superpowers/specs/2026-09-14-emjm-partner-source-design.md §2.
EACEA_ERASMUS_MUNDUS = HtmlCatalogue(
    name="seed:eacea",
    list_url="https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en",
    funding_family="MULTILATERAL",
    exclude_suffix="europa.eu",
    source_type="PROGRAM",
    page_param="page",
    pages=12,
    one_programme_per_link=True,
    awards_jointly=True,
)
