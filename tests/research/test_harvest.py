from apps.research.discovery import canonicalize_url
from apps.research.egress import FetchResult
from apps.research.harvest import (
    anchors,
    content_digest,
    official_url_from_catalogue_page,
    page_text,
)

DETAIL_PAGE = b"""
<html><head><title>AI &amp; Robotics</title><style>.x{color:red}</style></head>
<body>
<script>var tracking = "ignore me";</script>
<h1>AI &amp; Robotics (MSc)</h1>
<p>Taught in English over 4 semesters.</p>
<a href="/deutschland/studienangebote/international-programmes/en/detail/9894/">Overview</a>
<a href="https://www.facebook.com/DAAD">Facebook</a>
<a href="https://my.uni-assist.de/studiengaenge">uni-assist</a>
<a class="btn visitCourseWebsite" href="https://direc.to/ozyQ" target="_blank">Course website</a>
</body></html>
"""


def _page(body: bytes, url: str = "https://www2.daad.de/detail/9894/") -> FetchResult:
    return FetchResult(url, (), "text/html", body)


def test_anchors_carry_href_text_and_class() -> None:
    harvested = anchors(DETAIL_PAGE)

    assert ("https://direc.to/ozyQ", "Course website") in [
        (anchor.href, anchor.text) for anchor in harvested
    ]
    assert any("visitcoursewebsite" in anchor.css_class.casefold() for anchor in harvested)


def test_the_course_website_anchor_is_the_hop_target() -> None:
    assert official_url_from_catalogue_page(_page(DETAIL_PAGE)) == "https://direc.to/ozyQ"


def test_a_catalogue_page_without_a_course_website_link_resolves_to_nothing() -> None:
    body = b'<html><body><a href="https://www.facebook.com/DAAD">Facebook</a></body></html>'

    assert official_url_from_catalogue_page(_page(body)) is None


def test_same_host_links_are_never_the_hop_target() -> None:
    body = (
        b'<html><body><a class="visitCourseWebsite" '
        b'href="https://www2.daad.de/detail/9894/apply">Course website</a></body></html>'
    )

    assert official_url_from_catalogue_page(_page(body)) is None


def test_page_text_drops_markup_scripts_and_styles() -> None:
    text = page_text(DETAIL_PAGE)

    assert "AI & Robotics (MSc)" in text
    assert "Taught in English over 4 semesters." in text
    assert "ignore me" not in text
    assert "color:red" not in text
    assert "<a" not in text


def test_page_text_is_bounded() -> None:
    assert len(page_text(b"<p>" + b"x" * 50_000 + b"</p>", limit=100)) == 100


def test_canonicalization_strips_campaign_parameters_but_keeps_real_ones() -> None:
    assert canonicalize_url(
        "https://www.utn.de/en/study/ai-robotics-en/?utm_campaign=daad_portal&utm_source=daad"
    ) == "https://www.utn.de/en/study/ai-robotics-en"
    assert canonicalize_url("https://example.org/search?id=7&utm_medium=portal") == (
        "https://example.org/search?id=7"
    )


SHELL = b"""
<html><head><title>Opintopolku</title></head><body>
<div id="app"></div><script>window.__DATA__={};</script></body></html>
"""

CONTENT_PAGE = b"""
<html><head><title>MSc Robotics</title><style>.x{color:red}</style></head>
<body>
<header><a href="/">Home</a><span>Search</span></header>
<nav><a href="/news">News</a></nav>
<main><h1>MSc Robotics</h1><p>Tuition is EUR 0 per semester.</p></main>
<aside><p>Upcoming events: open day</p></aside>
<footer>Last reviewed 2026-08-27. Session a1b2c3.</footer>
</body></html>
"""


def test_content_digest_ignores_boilerplate_that_changes_between_fetches() -> None:
    later = CONTENT_PAGE.replace(b"Session a1b2c3", b"Session z9y8x7").replace(
        b"open day", b"campus tour"
    )
    assert content_digest(later) == content_digest(CONTENT_PAGE)


def test_content_digest_changes_when_the_content_region_changes() -> None:
    changed = CONTENT_PAGE.replace(b"EUR 0 per semester", b"EUR 1500 per semester")
    assert content_digest(changed) != content_digest(CONTENT_PAGE)


def test_content_digest_is_stable_across_whitespace_only_reflow() -> None:
    reflowed = CONTENT_PAGE.replace(b"<p>Tuition", b"<p>\n\n    Tuition")
    assert content_digest(reflowed) == content_digest(CONTENT_PAGE)


def test_content_digest_falls_back_to_the_whole_body_when_there_is_no_main() -> None:
    # A page with no <main> still has to produce a usable digest, not an empty one.
    plain = b"<html><body><h1>MSc Robotics</h1><p>Tuition is EUR 0.</p></body></html>"
    assert content_digest(plain) != content_digest(b"<html><body><h1>Other</h1></body></html>")
