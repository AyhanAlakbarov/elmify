import pytest
from django.core.cache import cache

from apps.research.discovery import DiscoveryQuery
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.search import EntityExpansionSource, SearchSource, sitemap_urls

QUERY = DiscoveryQuery(field="neuroscience", country_code="JP", max_leads=20)

SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://cbs.riken.jp/en/</loc></url>
  <url><loc>https://cbs.riken.jp/en/admission/fellowship.html</loc></url>
  <url><loc>https://cbs.riken.jp/en/news/2026.html</loc></url>
  <url><loc>https://cbs.riken.jp/en/graduate/scholarship.html</loc></url>
</urlset>
"""
INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://cbs.riken.jp/sitemap-1.xml</loc></sitemap>
</sitemapindex>
"""


class MappedFetch:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def __call__(self, url: str, **_kwargs: object) -> FetchResult:
        self.urls.append(url)
        if url not in self.pages:
            raise SourceBlocked(f"source returned HTTP 404: {url}")
        return FetchResult(url, (), "application/xml", self.pages[url])


def _search(urls: list[str]) -> SearchSource:
    return SearchSource(
        api_key="k",
        post=lambda _url, *, payload, headers: {"results": [{"url": url} for url in urls]},
    )


@pytest.mark.django_db
def test_organisations_enter_internal_and_their_own_pages_enter_as_leads() -> None:
    cache.clear()
    fetch = MappedFetch({"https://cbs.riken.jp/sitemap.xml": SITEMAP})
    source = EntityExpansionSource(search=_search(["https://cbs.riken.jp/en/"]), fetch=fetch)

    leads = list(source.find(QUERY))

    organisation, *pages = leads
    assert organisation.evidence_strength == "ECOSYSTEM_CLUE"
    assert organisation.visibility == "INTERNAL"
    assert organisation.can_support_claim is False
    assert organisation.can_route_research is True
    assert [lead.canonical_url for lead in pages] == [
        "https://cbs.riken.jp/en/admission/fellowship.html",
        "https://cbs.riken.jp/en/graduate/scholarship.html",
    ]
    assert all(lead.discovered_by == "entity-expansion" for lead in leads)


@pytest.mark.django_db
def test_a_host_without_a_sitemap_yields_the_organisation_and_nothing_else() -> None:
    cache.clear()
    fetch = MappedFetch({})
    source = EntityExpansionSource(search=_search(["https://ihep.cas.cn/"]), fetch=fetch)

    assert len(list(source.find(QUERY))) == 1


@pytest.mark.django_db
def test_pages_per_organisation_are_capped() -> None:
    cache.clear()
    many = (
        b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + b"".join(
            f"<url><loc>https://cbs.riken.jp/en/scholarship/{index}.html</loc></url>".encode()
            for index in range(30)
        )
        + b"</urlset>"
    )
    source = EntityExpansionSource(
        search=_search(["https://cbs.riken.jp/en/"]),
        fetch=MappedFetch({"https://cbs.riken.jp/sitemap.xml": many}),
        per_org=3,
    )

    assert len(list(source.find(QUERY))) == 4  # the organisation plus three pages


def test_a_sitemap_index_is_followed_one_level() -> None:
    fetch = MappedFetch(
        {"https://cbs.riken.jp/sitemap.xml": INDEX, "https://cbs.riken.jp/sitemap-1.xml": SITEMAP}
    )

    urls = list(sitemap_urls("cbs.riken.jp", fetch=fetch))

    assert "https://cbs.riken.jp/en/admission/fellowship.html" in urls
    assert fetch.urls == ["https://cbs.riken.jp/sitemap.xml", "https://cbs.riken.jp/sitemap-1.xml"]


def test_a_malformed_sitemap_is_skipped_not_raised() -> None:
    fetch = MappedFetch({"https://cbs.riken.jp/sitemap.xml": b"<not xml"})

    assert list(sitemap_urls("cbs.riken.jp", fetch=fetch)) == []


OFF_HOST_SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://cbs.riken.jp/en/graduate/scholarship.html</loc></url>
  <url><loc>https://scholarship-deals.example/graduate/scholarship</loc></url>
</urlset>
"""


@pytest.mark.django_db
def test_a_sitemap_entry_on_another_host_is_not_promoted_to_a_lead() -> None:
    """A sitemap may name any URL. Only the organisation's own pages are its own."""
    cache.clear()
    fetch = MappedFetch({"https://cbs.riken.jp/sitemap.xml": OFF_HOST_SITEMAP})
    source = EntityExpansionSource(search=_search(["https://cbs.riken.jp/en/"]), fetch=fetch)

    urls = [lead.canonical_url for lead in source.find(QUERY)]

    assert urls == [
        "https://cbs.riken.jp/en",
        "https://cbs.riken.jp/en/graduate/scholarship.html",
    ]


# --- a sitemap is a data file, not a page ------------------------------------

#: Measured 2026-09-19: what Firecrawl's `html` format returns for
#: https://globed.eu/sitemap_index.xml -- 1,610 bytes at contentType text/xml,
#: the XML declaration turned into an HTML comment and the document wrapped in
#: <html><body>. Trimmed to two children; the shape is verbatim.
FIRECRAWL_WRAPPED_INDEX = (
    b'<!--?xml version="1.0" encoding="UTF-8"?-->'
    b'<!--?xml-stylesheet type="text/xsl" href="//globed.eu/main-sitemap.xsl"?-->'
    b'<html><body><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    b"\t<sitemap>\n\t\t<loc>https://cbs.riken.jp/sitemap-1.xml</loc>\n"
    b"\t\t<lastmod>2026-09-09T12:12:07+00:00</lastmod>\n\t</sitemap>\n"
    b"</sitemapindex>\n<!-- XML Sitemap generated by Yoast SEO --></body></html>"
)


def test_a_vendor_rendered_sitemap_yields_no_programme_urls() -> None:
    """Why sitemaps left the vendor path, and it is NOT the failure that was
    predicted. The prediction was that the wrapper would not parse and the
    `except (ParseError, ValueError): return` below would swallow it. Measured:
    it parses fine. What the wrapper destroys is the ROOT TAG -- it is now
    `html`, not `sitemapindex`, so the index hop never fires and _sitemap
    returns the child *sitemap files* as if they were content URLs. Every one of
    them ends in .xml, FUNDING_PATH_TERMS drops the lot, and
    EntityExpansionSource yields zero programme URLs per organisation while
    reporting success. Same silence, one layer further in."""
    fetch = MappedFetch({
        "https://cbs.riken.jp/sitemap.xml": FIRECRAWL_WRAPPED_INDEX,
        "https://cbs.riken.jp/sitemap-1.xml": SITEMAP,
    })

    urls = list(sitemap_urls("cbs.riken.jp", fetch=fetch))

    assert "https://cbs.riken.jp/en/admission/fellowship.html" not in urls
    assert fetch.urls == ["https://cbs.riken.jp/sitemap.xml"], "the index was never followed"


def test_the_origins_own_bytes_are_followed_one_level() -> None:
    """The same document as the origin serves it -- which is what
    egress.fetch_data_file returns, and why sitemaps join the DEQAR CSVs and the
    JSON fixtures on the first-party transport."""
    origin = FIRECRAWL_WRAPPED_INDEX.replace(b"<!--?xml", b"<?xml").replace(b'?-->', b"?>")
    origin = origin.replace(b"<html><body>", b"").replace(b"</body></html>", b"")
    fetch = MappedFetch({
        "https://cbs.riken.jp/sitemap.xml": origin,
        "https://cbs.riken.jp/sitemap-1.xml": SITEMAP,
    })

    urls = list(sitemap_urls("cbs.riken.jp", fetch=fetch))

    assert "https://cbs.riken.jp/en/admission/fellowship.html" in urls


def test_entity_expansion_defaults_to_the_data_file_transport_not_the_vendor() -> None:
    """The boundary this whole fix is: pages to vendors, data files to us. A
    default of retrieve_official_source is how the vendor renderer got handed an
    XML document in the first place."""
    from apps.research.egress import fetch_data_file

    assert EntityExpansionSource(search=_search([])).fetch is fetch_data_file
