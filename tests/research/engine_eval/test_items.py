from apps.research.engine_eval.items import PageRow, half_of, items_from_page
from apps.research.fetch.types import FetchedPage

HTML = b"""<html><body><main>
<h2>Scholarship coverage</h2><p>Holders receive a monthly stipend of 43,000 HUF.</p>
<h2>Eligibility</h2><p>Citizens of Azerbaijan may apply for master's programmes.</p>
</main></body></html>"""


def _page(url="https://example.org/a", body=HTML):
    return FetchedPage(final_url=url, redirects=(), content_type="text/html", body=body,
                       fetched_via="FIRECRAWL")


def test_lines_carry_their_heading_path():
    items, reason = items_from_page(PageRow("https://example.org/a", "en", "sh"), _page(), 0)
    assert reason == ""
    stipend = next(i for i in items if "stipend" in i.text)
    assert "coverage" in stipend.heading.lower()
    # the heading "Scholarship coverage" is itself line 0 (funding_lines keeps headings as lines)
    assert stipend.id == "p0l1" and stipend.language == "en" and stipend.scheme == "sh"


def test_a_page_without_lines_is_skipped_with_a_reason():
    items, reason = items_from_page(PageRow("https://example.org/b", "az", "x"),
                                    _page(body=b"<html><body></body></html>"), 1)
    assert items == [] and reason == "no_lines"


def test_split_is_by_final_url_and_deterministic():
    assert half_of("https://example.org/a", "en") == half_of("https://example.org/a", "en")
    halves = {half_of(f"https://e.org/{n}", "tr") for n in range(40)}
    assert halves == {"tune", "score"}
