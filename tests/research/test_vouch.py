"""A body no authority names is RECOGNISED(vouched_by_link) only by its
recogniser's own structural link to it (spec §5.3). UFAZ is the case."""

import gzip
from pathlib import Path

from apps.research.vouch import EXCLUDED_TERMS, STRUCTURAL_TERMS, find_vouch
from tests.research.provenance_helpers import FakeFetch, page

UFAZ = "https://ufaz.az/"
ASOIU = "https://asoiu.edu.az/"
UFAZ_HOME = '<html><body><h1>UFAZ</h1><footer><a href="https://asoiu.edu.az/">ASOIU</a></footer></body></html>'
#: The measured shape (asoiu.edu.az, 2026-09-26): the UFAZ link sits in
#: header > nav > ... > ul.top, beside a dual-degree programme link.
ASOIU_HOME = """<html><head><title>ASOIU |</title></head><body><header>
<nav class="scroll_nav navigations"><div id="nav"><ul class="top">
<li><a href="/warwick">Vorvik İkili Diplom Proqramı</a></li>
<li><a href="https://www.ufaz.az/en/">UFAZ</a></li></ul></div></nav></header>
<main><p>News</p></main></body></html>"""
RECOGNISERS = {"asoiu.edu.az": "curated_list"}
FIXTURES = Path(__file__).parent / "fixtures"


def test_ufaz_is_vouched_by_asoius_navigation() -> None:
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)})
    result = find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert (result.vouch_url, result.recogniser_domain, result.failed) == (
        ASOIU, "asoiu.edu.az", False
    )


def test_a_parent_named_only_on_the_candidates_about_page_is_followed() -> None:
    """The measured shape (www.ufaz.az, 2026-09-27): the homepage links no
    other university; "Establishment of UFAZ" under /about-us/ links ASOIU."""
    www, established = "https://www.ufaz.az/", "https://www.ufaz.az/en/about-us/establishment-of-ufaz/"
    home = f'<html><body><nav><a href="{established}">Establishment of UFAZ</a></nav></body></html>'
    about = '<html><body><h1>Establishment</h1><a href="https://asoiu.edu.az/">ASOIU</a></body></html>'
    fetch = FakeFetch({
        www: page(www, home), established: page(established, about), ASOIU: page(ASOIU, ASOIU_HOME),
    })
    result = find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert (result.vouch_url, result.recogniser_domain) == (ASOIU, "asoiu.edu.az")


def test_about_pages_are_read_only_when_the_homepage_points_nowhere_useful() -> None:
    home = UFAZ_HOME.replace("<h1>", '<a href="/about">About</a><h1>')
    fetch = FakeFetch({UFAZ: page(UFAZ, home), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ASOIU
    assert fetch.calls == [UFAZ, ASOIU]


def test_ufaz_is_vouched_on_the_real_captured_pages() -> None:
    """Plain-HTTP captures, 2026-09-27 (CSRF value scrubbed): ufaz.az's bare
    host does not answer, www redirects to /en/, and the homepage links no
    parent -- the establishment page does, and ASOIU's header links back."""

    def captured(name: str) -> bytes:
        return gzip.decompress((FIXTURES / f"vouch_{name}.html.gz").read_bytes())

    established = "http://www.ufaz.az/en/about-us/establishment-of-ufaz/"
    fetch = FakeFetch({
        "https://www.ufaz.az/": page(
            "https://www.ufaz.az/", captured("ufaz_home"), final_url="https://www.ufaz.az/en/"
        ),
        established: page(
            established, captured("ufaz_establishment"),
            final_url=established.replace("http:", "https:"),
        ),
        ASOIU: page(ASOIU, captured("asoiu_home")),
    })
    result = find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert (result.vouch_url, result.recogniser_domain, result.failed) == (
        ASOIU, "asoiu.edu.az", False
    )


def test_a_structural_page_within_two_hops_vouches() -> None:
    home = """<html><body><main><a href="/structure">Faculties and institutes</a>
<a href="https://www.ufaz.az/">UFAZ</a></main></body></html>"""
    structure = '<html><body><h1>Faculties</h1><a href="https://www.ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/structure": page("https://asoiu.edu.az/structure", structure),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == "https://asoiu.edu.az/structure"


def test_a_second_hop_structural_page_vouches() -> None:
    home = '<html><body><main><a href="/about">Institutes</a></main></body></html>'
    about = '<html><body><h1>Institutes</h1><a href="/campuses">Campuses</a></body></html>'
    campuses = '<html><body><h1>Campuses</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/about": page("https://asoiu.edu.az/about", about),
        "https://asoiu.edu.az/campuses": page("https://asoiu.edu.az/campuses", campuses),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == "https://asoiu.edu.az/campuses"


def test_an_azerbaijani_heading_is_read_as_utf8() -> None:
    """Given bytes and no <meta charset>, lxml reads Latin-1 and "Fakültələr"
    would never match its own term."""
    home = '<html><body><main><a href="/f">Fakültələr</a></main></body></html>'
    faculties = '<html><body><h1>Fakültələr</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/f": page("https://asoiu.edu.az/f", faculties),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == "https://asoiu.edu.az/f"


def test_a_partners_page_never_vouches() -> None:
    home = '<html><body><main><a href="/structure">Faculties</a></main></body></html>'
    partners = '<html><body><h1>Partner universities</h1><a href="https://www.ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/structure": page("https://asoiu.edu.az/structure", partners),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_partners_strip_in_the_footer_never_vouches() -> None:
    """The footer is structural, but a partner-logo strip in it is a partners
    page by another name: franchise colleges are linked from exactly there."""
    headed = """<html><body><footer><h4>Our partners</h4>
<ul><li><a href="https://ufaz.az/">UFAZ</a></li></ul></footer></body></html>"""
    classed = """<html><body><footer><div class="footer-partners">
<a href="https://ufaz.az/"><img alt="UFAZ"></a></div></footer></body></html>"""
    for home in (headed, classed):
        fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home)})
        assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_partners_section_on_a_structural_page_never_vouches() -> None:
    home = '<html><body><main><a href="/f">Faculties</a></main></body></html>'
    faculties = """<html><body><h1>Faculties</h1><a href="/f/chem">Chemistry</a>
<h2>Erasmus partners</h2><a href="https://ufaz.az/">UFAZ</a></body></html>"""
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/f": page("https://asoiu.edu.az/f", faculties),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_an_excluded_term_inside_a_korean_compound_still_excludes() -> None:
    """Korean writes compounds without spaces: 협력기관 is "partner
    institutions", and a word-boundary match would miss its 협력."""
    home = '<html><body><main><a href="/g">대학원</a></main></body></html>'
    mixed = '<html><body><h1>대학원 협력기관</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/g": page("https://asoiu.edu.az/g", mixed),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_mail_address_is_not_a_link_to_the_body() -> None:
    home = '<html><body><footer><a href="mailto:office@ufaz.az">Contact</a></footer></body></html>'
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_link_on_a_user_subdomain_never_vouches() -> None:
    home = '<html><body><main><a href="https://blog.asoiu.edu.az/faculties">Faculties</a></main></body></html>'
    blog = '<html><body><h1>Faculties</h1><a href="https://www.ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://blog.asoiu.edu.az/faculties": page("https://blog.asoiu.edu.az/faculties", blog),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert "https://blog.asoiu.edu.az/faculties" not in fetch.calls


def test_a_personal_page_on_the_main_host_is_never_followed() -> None:
    home = '<html><body><main><a href="/~aliyev/faculties">Faculties</a></main></body></html>'
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert fetch.calls == [UFAZ, ASOIU]


def test_a_recogniser_that_redirects_off_its_host_vouches_for_nothing() -> None:
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME),
        ASOIU: page(ASOIU, ASOIU_HOME, final_url="https://parked-domains.com/lander"),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_structural_page_that_redirects_off_the_host_vouches_for_nothing() -> None:
    home = '<html><body><main><a href="/f">Faculties</a></main></body></html>'
    landed = '<html><body><h1>Faculties</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/f": page("https://asoiu.edu.az/f", landed, final_url="https://evil.example/f"),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_body_admitted_by_link_vouches_for_nothing() -> None:
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", {"asoiu.edu.az": "vouched_by_link"}, fetch=fetch).vouch_url == ""


def test_a_recogniser_is_chosen_by_the_candidates_link_never_by_a_name() -> None:
    """ASOIU links UFAZ, but UFAZ's own page does not link ASOIU: nothing to
    follow, and ASOIU is never fetched."""
    silent = "<html><body><h1>UFAZ, part of ASOIU</h1></body></html>"
    fetch = FakeFetch({UFAZ: page(UFAZ, silent), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert fetch.calls == [UFAZ]


def test_a_candidate_that_lands_on_another_site_points_nowhere() -> None:
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME, final_url="https://parked-domains.com/lander"),
        ASOIU: page(ASOIU, ASOIU_HOME),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert fetch.calls == [UFAZ]


def test_a_www_only_site_is_read_through_its_www_host() -> None:
    www = "https://www.ufaz.az/"
    fetch = FakeFetch({www: page(www, UFAZ_HOME), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ASOIU


def test_the_structural_crawl_is_bounded() -> None:
    home = "<html><body><main>" + "".join(
        f'<a href="/faculty-{n}">Faculty {n}</a>' for n in range(25)
    ) + "</main></body></html>"
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home)})
    find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert len(fetch.calls) <= 2 + 10


def test_an_unreachable_candidate_is_a_failed_lookup() -> None:
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=FakeFetch({})).failed is True


def test_an_unreachable_recogniser_is_a_failed_lookup() -> None:
    fetch = FakeFetch({UFAZ: page(UFAZ, UFAZ_HOME)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).failed is True


def _vouch(home: str, extra: dict[str, str] | None = None) -> str:
    """ASOIU's homepage is `home`; `extra` maps its other URLs to their HTML."""
    pages = {UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home)}
    pages |= {url: page(url, html) for url, html in (extra or {}).items()}
    return find_vouch("ufaz.az", RECOGNISERS, fetch=FakeFetch(pages)).vouch_url


def test_a_news_article_reached_from_the_homepage_never_vouches() -> None:
    """Its link text and its <h1> both read as structural ("Institute of ..."):
    only the news section, the /news/ path or the <title> says what it is.
    Each case below leaves exactly one of those three signals."""
    article = """<html><head><title>ASOIU</title></head><body><h1>Institute of
Petroleum signs MoU with UFAZ</h1><a href="https://ufaz.az/">UFAZ</a></body></html>"""
    link = '<a href="{url}">Institute of Petroleum signs MoU with UFAZ</a>'

    def home(url: str, section: str = "") -> str:
        anchor = link.format(url=url)
        return f'<html><body><main><div class="{section}">{anchor}</div></main></body></html>'

    news, neutral = "https://asoiu.edu.az/news/2026/mou", "https://asoiu.edu.az/p/1"
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home(news)), news: page(news, article),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert news not in fetch.calls
    assert _vouch(home(neutral, section="news"), {neutral: article}) == ""
    titled = article.replace("<title>ASOIU", "<title>News | ASOIU")
    assert _vouch(home(neutral), {neutral: titled}) == ""
    assert _vouch(home(neutral), {neutral: article}) == neutral


def test_an_event_page_never_vouches() -> None:
    home = '<html><body><main><a href="/event/42">Faculty open day at UFAZ</a></main></body></html>'
    event = '<html><body><h1>Faculty open day at UFAZ</h1><a href="https://ufaz.az/r">Register</a></body></html>'
    assert _vouch(home, {"https://asoiu.edu.az/event/42": event}) == ""


def test_a_page_that_lands_on_a_news_path_never_vouches() -> None:
    home = '<html><body><main><a href="/f">Faculties</a></main></body></html>'
    faculties = '<html><body><h1>Faculties</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/f": page(
            "https://asoiu.edu.az/f", faculties, final_url="https://asoiu.edu.az/news/9"
        ),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""


def test_a_header_or_footer_inside_a_news_card_is_not_navigation() -> None:
    """WordPress renders every post card as article > header/footer."""
    header = """<html><body><main><section class="posts"><article>
<header><h3><a href="https://ufaz.az/">UFAZ signs MoU</a></h3></header>
</article></section></main></body></html>"""
    footer = """<html><body><div class="latest"><article><p>Signed.</p>
<footer><a href="https://ufaz.az/">Source</a></footer></article></div></body></html>"""
    aside = '<html><body><aside><nav><a href="https://ufaz.az/">UFAZ</a></nav></aside></body></html>'
    for home in (header, footer, aside):
        assert _vouch(home) == ""


def test_an_excluded_class_above_the_navigation_still_excludes() -> None:
    home = """<html><body><div class="partners-band"><footer>
<a href="https://ufaz.az/">UFAZ</a></footer></div></body></html>"""
    assert _vouch(home) == ""


def test_a_users_comment_on_a_structural_page_never_vouches() -> None:
    home = '<html><body><nav><a href="/faculties">Faculties</a></nav></body></html>'
    commented = """<html><body><h1>Faculties</h1><div id="comments"><ol>
<li><a href="https://ufaz.az/" class="url">Bob</a></li></ol></div></body></html>"""
    rel = """<html><body><h1>Faculties</h1><p>By
<a href="https://ufaz.az/" rel="external nofollow ugc">Bob</a></p></body></html>"""
    for faculties in (commented, rel):
        assert _vouch(home, {"https://asoiu.edu.az/faculties": faculties}) == ""


def test_a_useful_links_column_never_vouches() -> None:
    for label in ("Useful links", "Quick links", "Resources", "External links", "Liens utiles"):
        home = f'<html><body><footer><h4>{label}</h4><a href="https://ufaz.az/">UFAZ</a></footer></body></html>'
        assert _vouch(home) == "", label


def test_a_staff_directory_headed_faculty_never_vouches() -> None:
    """English "faculty" also means teaching staff, whose personal sites are
    linked from exactly such a page."""
    home = '<html><body><nav><a href="/staff">Faculty</a></nav></body></html>'
    directory = (
        '<html><body><h1>Faculty and staff</h1><a href="https://ufaz.az/">Dr X</a></body></html>'
    )
    assert _vouch(home, {"https://asoiu.edu.az/staff": directory}) == ""
    for heading in ("Faculty and staff", "People", "Faculty directory"):
        listed = directory.replace("Faculty and staff", heading)
        found = _vouch(home.replace("/staff", "/f"), {"https://asoiu.edu.az/f": listed})
        assert found == "", heading


def test_a_page_wide_class_on_html_or_body_is_not_a_section() -> None:
    """Modernizr puts "no-touchevents" on <html>, themes put "newsletter-..."
    on <body>: both hold an excluded substring and describe the whole page,
    whose type is judged by its title and path instead."""
    faculties = '<html><body><h1>Faculties</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    for link in ('<a href="https://ufaz.az/">UFAZ</a>', '<a href="/faculties">Faculties</a>'):
        home = (
            '<html class="js no-touchevents"><body class="newsletter-signup">'
            f"<nav>{link}</nav></body></html>"
        )
        assert _vouch(home, {"https://asoiu.edu.az/faculties": faculties}), link


def test_a_homepage_link_is_judged_by_the_headings_of_its_own_section() -> None:
    faculties = '<html><body><h1>Faculties</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    extra = {"https://asoiu.edu.az/faculties": faculties}
    after_main = """<html><body><main><h2>Latest news</h2><p>...</p><h2>Our partners</h2></main>
<footer><ul><li><a href="/faculties">Faculties</a></li></ul></footer></body></html>"""
    after_h1 = """<html><body><h1 class="sr-only">ASOIU news portal</h1>
<nav><a href="/faculties">Faculties</a></nav></body></html>"""
    for home in (after_main, after_h1):
        assert _vouch(home, extra) == "https://asoiu.edu.az/faculties"
    in_own = """<html><body><footer><h4>Our partners</h4>
<a href="/faculties">Faculties</a></footer></body></html>"""
    assert _vouch(in_own, extra) == ""


def test_list_words_inside_a_bodys_name_do_not_exclude() -> None:
    """"Resources", "staff", "people" and "external" exclude a link column or
    a staff directory as its label, never as a body's own name."""
    for name in (
        "Institute of Human Resources", "People's Friendship University branch",
        "Command and Staff College", "Faculty of External Relations",
    ):
        linked = f'<html><body><nav><a href="https://ufaz.az/">{name}</a></nav></body></html>'
        assert _vouch(linked) == ASOIU, name
    named = "Faculty of Human Resources Management"
    home = f'<html><body><nav><a href="/f">{named}</a></nav></body></html>'
    faculty = f'<html><body><h1>{named}</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    assert _vouch(home, {"https://asoiu.edu.az/f": faculty}) == "https://asoiu.edu.az/f"
    home = '<html><body><nav><a href="/f">Faculties</a></nav></body></html>'
    headed = """<html><body><h1>Faculties</h1><h2>Faculty of External Relations</h2>
<a href="https://ufaz.az/">UFAZ</a></body></html>"""
    assert _vouch(home, {"https://asoiu.edu.az/f": headed}) == "https://asoiu.edu.az/f"


def test_a_related_sites_or_recent_posts_box_on_a_structural_page_never_vouches() -> None:
    home = '<html><body><nav><a href="/institutes">Institutes</a></nav></body></html>'
    for heading in ("Related sites", "Related links", "Recent posts"):
        boxed = f"""<html><body><h1>Institutes</h1><aside class="widget"><h3>{heading}</h3>
<ul><li><a href="https://ufaz.az/">UFAZ</a></li></ul></aside></body></html>"""
        assert _vouch(home, {"https://asoiu.edu.az/institutes": boxed}) == "", heading


def test_a_link_in_the_homepages_main_content_does_not_vouch() -> None:
    home = '<html><body><main><a href="https://ufaz.az/">UFAZ</a></main></body></html>'
    assert _vouch(home) == ""


def test_a_page_not_headed_by_a_structural_term_does_not_vouch() -> None:
    home = '<html><body><main><a href="/f">Faculties</a></main></body></html>'
    contact = '<html><body><h1>Contact</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    assert _vouch(home, {"https://asoiu.edu.az/f": contact}) == ""


def test_a_recogniser_on_a_hosting_platform_is_never_asked() -> None:
    hosted = "https://asoiu.github.io/"
    home = '<html><body><footer><a href="https://asoiu.github.io/">ASOIU</a></footer></body></html>'
    fetch = FakeFetch({UFAZ: page(UFAZ, home), hosted: page(hosted, ASOIU_HOME)})
    assert find_vouch("ufaz.az", {"asoiu.github.io": "curated_list"}, fetch=fetch).vouch_url == ""
    assert fetch.calls == [UFAZ]


def test_the_candidate_never_vouches_for_itself() -> None:
    home = '<html><body><nav><a href="https://ufaz.az/">Home</a></nav></body></html>'
    fetch = FakeFetch({UFAZ: page(UFAZ, home)})
    assert find_vouch("ufaz.az", {"ufaz.az": "curated_list"}, fetch=fetch).vouch_url == ""


def test_at_most_three_recognisers_are_asked() -> None:
    domains = [f"uni{n}.edu.az" for n in range(4)]
    home = "<html><body><footer>" + "".join(
        f'<a href="https://{domain}/">{domain}</a>' for domain in domains
    ) + "</footer></body></html>"
    back = '<html><body><nav><a href="https://ufaz.az/">UFAZ</a></nav></body></html>'
    last = "https://uni3.edu.az/"
    fetch = FakeFetch({UFAZ: page(UFAZ, home), last: page(last, back)})
    result = find_vouch("ufaz.az", dict.fromkeys(domains, "curated_list"), fetch=fetch)
    assert result.vouch_url == ""
    assert last not in fetch.calls


def test_at_most_three_about_pages_are_read() -> None:
    abouts = [f"https://ufaz.az/about-{n}" for n in range(4)]
    links = "".join(f'<a href="{url}">About</a>' for url in abouts)
    home = f"<html><body>{links}</body></html>"
    parent = '<html><body><a href="https://asoiu.edu.az/">ASOIU</a></body></html>'
    fetch = FakeFetch({
        UFAZ: page(UFAZ, home), abouts[3]: page(abouts[3], parent), ASOIU: page(ASOIU, ASOIU_HOME),
    })
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).vouch_url == ""
    assert abouts[3] not in fetch.calls


def test_an_about_page_on_another_site_is_never_fetched() -> None:
    home = '<html><body><a href="https://elsewhere.az/about">About</a></body></html>'
    fetch = FakeFetch({UFAZ: page(UFAZ, home)})
    find_vouch("ufaz.az", RECOGNISERS, fetch=fetch)
    assert fetch.calls == [UFAZ]


def test_the_structural_budget_is_shared_across_recognisers() -> None:
    crowded = "<html><body><main>" + "".join(
        f'<a href="/faculty-{n}">Faculty {n}</a>' for n in range(25)
    ) + "</main></body></html>"
    other = "https://uni.edu.az/"
    home = UFAZ_HOME.replace("</footer>", f'<a href="{other}">Uni</a></footer>')
    fetch = FakeFetch({
        UFAZ: page(UFAZ, home), ASOIU: page(ASOIU, crowded),
        other: page(other, crowded.replace("/faculty-", f"{other}faculty-")),
    })
    find_vouch("ufaz.az", {**RECOGNISERS, "uni.edu.az": "curated_list"}, fetch=fetch)
    assert len([url for url in fetch.calls if "faculty-" in url]) <= 10


def test_a_dead_structural_link_is_an_answer_not_a_failed_lookup() -> None:
    """Only an unreachable candidate or recogniser homepage fails the lookup:
    a link that goes nowhere, or off the host, is simply not a vouch."""
    home = '<html><body><main><a href="/f">Faculties</a><a href="/g">Institutes</a></main></body>'
    landed = '<html><body><h1>Institutes</h1><a href="https://ufaz.az/">UFAZ</a></body></html>'
    result = find_vouch("ufaz.az", RECOGNISERS, fetch=FakeFetch({
        UFAZ: page(UFAZ, UFAZ_HOME), ASOIU: page(ASOIU, home),
        "https://asoiu.edu.az/g": page("https://asoiu.edu.az/g", landed, final_url="https://evil.example/g"),
    }))
    assert (result.vouch_url, result.failed) == ("", False)


def test_a_dead_about_link_is_an_answer_not_a_failed_lookup() -> None:
    home = '<html><body><a href="/about">About</a><a href="/about-us">About us</a></body></html>'
    result = find_vouch("ufaz.az", RECOGNISERS, fetch=FakeFetch({
        UFAZ: page(UFAZ, home),
        "https://ufaz.az/about-us": page(
            "https://ufaz.az/about-us", home, final_url="https://parked-domains.com/lander"
        ),
    }))
    assert (result.vouch_url, result.failed) == ("", False)


def test_a_vouch_found_despite_a_failed_page_is_not_a_failure() -> None:
    home = UFAZ_HOME.replace("<h1>", '<a href="/about">About</a><h1>')
    fetch = FakeFetch({UFAZ: page(UFAZ, home), ASOIU: page(ASOIU, ASOIU_HOME)})
    assert find_vouch("ufaz.az", RECOGNISERS, fetch=fetch).failed is False


def test_the_term_lists_are_pinned() -> None:
    assert STRUCTURAL_TERMS == (
        "faculties", "faculty", "schools", "institutes", "campuses", "branches",
        "affiliated institutions",
        "fakültələr", "fakültə", "institutlar", "filiallar", "kampuslar",
        "fakülteler", "enstitüler", "yüksekokullar", "kampüsler",
        "fakultäten", "fachbereiche", "institute", "standorte",
        "facultés", "écoles", "instituts", "composantes",
        "단과대학", "대학원", "캠퍼스", "부속기관",
    )
    assert EXCLUDED_TERMS == (
        "partners", "partner", "agents", "representatives", "study abroad", "erasmus",
        "sponsors", "alumni", "events", "news",
        "tərəfdaşlar", "xəbərlər", "tədbirlər", "məzunlar",
        "ortaklar", "partnerler", "haberler", "etkinlikler", "mezunlar",
        "nachrichten", "veranstaltungen", "auslandsstudium",
        "partenaires", "actualités", "événements",
        "협력", "뉴스", "행사", "동문",
    )
