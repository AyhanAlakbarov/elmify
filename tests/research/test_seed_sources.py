from dataclasses import replace

from apps.research.discovery import DiscoveryQuery
from apps.research.egress import FetchResult
from apps.research.seeds import EACEA_ERASMUS_MUNDUS, HtmlCatalogue

EACEA_PAGE = b"""
<html><body>
<a href="https://erasmus-plus.ec.europa.eu/projects/search/details/101241136">Detail</a>
<a href="https://erasmus-plus.ec.europa.eu/projects/search/details/101240350">Detail</a>
<a href="https://erasmus-plus.ec.europa.eu/projects/search/details/101241136">Duplicate</a>
<a href="https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_de">Deutsch</a>
<a href="https://erasmus-plus.ec.europa.eu/opportunities/individuals/students">Opportunities</a>
</body></html>
"""
EACEA_EMPTY = b"<html><body><a href='/scholarships_en'>Home</a></body></html>"


class HtmlFetch:
    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies)
        self.urls: list[str] = []

    def __call__(self, url: str, **_kwargs: object) -> FetchResult:
        self.urls.append(url)
        body = self.bodies.pop(0) if self.bodies else EACEA_EMPTY
        return FetchResult(url, (), "text/html", body)


#: Pattern mode is still supported and still the right shape for a catalogue
#: whose listing does not link out to the programme's own site. The shipped
#: EACEA configuration no longer uses it, so these two exercise it explicitly.
def _pattern_mode(fetch) -> HtmlCatalogue:
    return HtmlCatalogue(
        name="seed:eacea",
        list_url="https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en",
        funding_family="MULTILATERAL",
        detail_pattern=r"^https://erasmus-plus\.ec\.europa\.eu/projects/search/details/\d+$",
        page_param="page",
        fetch=fetch,
    )


def test_html_catalogue_yields_matching_detail_links_only_once() -> None:
    fetch = HtmlFetch(EACEA_PAGE, EACEA_EMPTY)

    leads = list(
        _pattern_mode(fetch).find(
            DiscoveryQuery(field="robotics", country_code="DE", max_leads=50)
        )
    )

    assert [lead.canonical_url for lead in leads] == [
        "https://erasmus-plus.ec.europa.eu/projects/search/details/101241136",
        "https://erasmus-plus.ec.europa.eu/projects/search/details/101240350",
    ]
    assert all(lead.source_type == "AGGREGATOR" for lead in leads)
    assert all(lead.can_support_claim is False for lead in leads)
    assert all(lead.funding_family == "MULTILATERAL" for lead in leads)
    assert all(lead.discovered_by == "seed:eacea" for lead in leads)
    assert all(lead.identity is None for lead in leads)


def test_html_catalogue_pages_until_a_page_matches_nothing() -> None:
    fetch = HtmlFetch(EACEA_PAGE, EACEA_EMPTY, EACEA_PAGE)

    list(
        _pattern_mode(fetch).find(
            DiscoveryQuery(field="robotics", country_code="DE", max_leads=50)
        )
    )

    assert fetch.urls == [
        "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en?page=0",
        "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en?page=1",
    ]


def test_a_corridor_specific_catalogue_ignores_other_corridors() -> None:
    fetch = HtmlFetch(EACEA_PAGE)
    korea_only = replace(EACEA_ERASMUS_MUNDUS, country_code="KR", fetch=fetch)

    assert list(korea_only.find(DiscoveryQuery(field="robotics", country_code="DE"))) == []
    assert fetch.urls == []


#: The real listing page's shape, verified 2026-08-28: each entry links straight
#: to the consortium's own site. The `europa.eu` detail pages the adapter used to
#: harvest are refused server-side (HTTP 403) and were never needed -- a
#: catalogue detail page is an AGGREGATOR that may not support a claim anyway,
#: while the consortium's own site is the origin the pipeline wants.
EACEA_LISTING = b"""
<html><body>
<a href="https://www.multidiverse.eu/">Erasmus Mundus Joint Master in Multilingualism</a>
<a href="https://epsmaster.eu/">European Politics and Society: Vaclav Havel Joint Master</a>
<a href="https://lawgid.ius.bg.ac.rs/">Law and Gender, Intersectionality and Diversity</a>
<a href="https://erasmus-plus.ec.europa.eu/projects/search/details/101241136">Detail</a>
<a href="https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_de">Deutsch</a>
<a href="https://commission.europa.eu/index_en">Commission</a>
<a href="https://www.facebook.com/EUErasmusPlusProgramme">Facebook</a>
<a href="/scholarships_en">Relative</a>
</body></html>
"""


def test_the_catalogue_harvests_consortium_sites_not_its_own_detail_pages() -> None:
    fetch = HtmlFetch(EACEA_LISTING, EACEA_EMPTY)

    leads = list(
        HtmlCatalogue(
            name="seed:eacea",
            list_url="https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en",
            funding_family="MULTILATERAL",
            exclude_suffix="europa.eu",
            source_type="PROGRAM",
            page_param="page",
            fetch=fetch,
        ).find(DiscoveryQuery(field="robotics", country_code="DE", max_leads=50))
    )

    assert [lead.canonical_url for lead in leads] == [
        "https://www.multidiverse.eu/",
        "https://epsmaster.eu/",
        "https://lawgid.ius.bg.ac.rs/",
    ]
    assert all("europa.eu" not in lead.canonical_url for lead in leads)


def test_consortium_leads_can_support_a_claim_unlike_catalogue_leads() -> None:
    fetch = HtmlFetch(EACEA_LISTING, EACEA_EMPTY)

    leads = list(
        replace(EACEA_ERASMUS_MUNDUS, fetch=fetch).find(
            DiscoveryQuery(field="robotics", country_code="DE", max_leads=50)
        )
    )

    assert leads, "the shipped configuration must harvest the listing"
    assert all(lead.source_type == "PROGRAM" for lead in leads)
    assert all(lead.can_support_claim for lead in leads)


def test_one_unusable_link_does_not_kill_the_whole_harvest() -> None:
    """A live run found `http://resco-master.eu/` on the real listing.

    canonicalize_url refuses non-HTTPS, and an uncaught ValueError there ends
    the generator -- so a single plain-HTTP anchor cost every other programme on
    the page. EntityExpansionSource already guards this; this one did not.
    """
    page = b"""
    <html><body>
    <a href="https://www.multidiverse.eu/">Good</a>
    <a href="http://resco-master.eu/">Plain HTTP</a>
    <a href="https://epsmaster.eu/">Also good</a>
    </body></html>
    """
    fetch = HtmlFetch(page, EACEA_EMPTY)

    leads = list(
        replace(EACEA_ERASMUS_MUNDUS, fetch=fetch).find(
            DiscoveryQuery(field="robotics", country_code="DE", max_leads=50)
        )
    )

    assert [lead.canonical_url for lead in leads] == [
        "https://www.multidiverse.eu/",
        "https://epsmaster.eu/",
    ]


def test_social_profiles_on_a_catalogue_page_are_not_harvested() -> None:
    """A live harvest pulled in `bsky.app/profile/ec.europa.eu`.

    Only facebook.com was on CATALOGUE_DOMAINS, so every other social host on
    the catalogue's footer passed the off-site filter.
    """
    page = b"""
    <html><body>
    <a href="https://www.multidiverse.eu/">Programme</a>
    <a href="https://bsky.app/profile/ec.europa.eu">Bluesky</a>
    <a href="https://www.linkedin.com/company/eacea">LinkedIn</a>
    <a href="https://x.com/EUErasmusPlus">X</a>
    <a href="https://www.instagram.com/erasmusplus/">Instagram</a>
    <a href="https://www.youtube.com/user/EUErasmusPlus">YouTube</a>
    </body></html>
    """
    fetch = HtmlFetch(page, EACEA_EMPTY)

    leads = list(
        replace(EACEA_ERASMUS_MUNDUS, fetch=fetch).find(
            DiscoveryQuery(field="robotics", country_code="DE", max_leads=50)
        )
    )

    assert [lead.canonical_url for lead in leads] == ["https://www.multidiverse.eu/"]
