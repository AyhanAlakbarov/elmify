"""The vendor path against the real vendors, through the code that ships.

This file exists because eleven reviews approved this branch against stubs, and
the first live run found four defects in an hour -- a body that was markdown, a
redirect guard that refused correct answers at 25 credits each, a 429 storm that
escalated every page to the residue tier, and an XML sitemap eaten by a
renderer. None of them was visible to a stub, because a stub returns what the
author believed the vendor returns. Every assertion below goes through
``fetch_page`` and ``scrapedo.scrape`` themselves, not a reimplementation.

Excluded from a default run by ``addopts = "-m 'not live'"``; select with
``-m live``. Skipped cleanly when a key is absent.

    FIRECRAWL_API_KEY=... SCRAPEDO_API_KEY=... \\
      POSTGRES_DB=tehsil_fetch_engine_core uv run pytest \\
      tests/research/test_fetch_live.py -m live -v

**Two halves, and they assert different things.** The five tests at the top pin
the vendors' CONTRACT -- the body is markup, the final URL is where the vendor
landed -- and each names the defect it caught. The ladder gate below pins the
ENGINE's outcome class and credit ceiling per host, never content: a university
editing a page must not fail this suite, and a host moving from BLOCKED to
FETCHED is good news, so every assertion is "at least as good as", never
equality.

**Cost ceiling per run: 267 credits, plus the funnel stage 3 additions below.**
3 Firecrawl + 50 scrape.do for the contract tests (two calls at render+super,
25 each), 202 for the twelve hard hosts (the sum of their ceilings below), 10
for the PDF and 2 for the unchanged-page pair. At Firecrawl's $83/100k that
whole ceiling is $0.22; at scrape.do's $29/250k it is $0.031, and the real
bill sits between them. Adding a scrape.do case here is a 25-credit decision,
not a free one. The three funnel-stage cases add: 1 Firecrawl credit for
``/map``, 5 Firecrawl credits for a bounded ``/crawl`` (``limit=5``, not the
sweep's 25), and ~$0.03 of Tavily for the guided ``/map`` -- roughly 6 more
Firecrawl credits and $0.03 on top of the ceiling above.

**The ceiling is checked after the vendor reports the cost**, because
scrape.do's per-domain multiplier is applied server-side (``SweepBudget``'s own
docstring). So one over-cap call can land before the budget stops the next rung:
these ``cost_credits`` assertions are a cost ALARM, not a spend guard. The guard
that cannot be outrun is the per-key spend limit set in each vendor's dashboard
-- layer 1, configuration rather than code (``docs/runbooks/deploy.md``).
"""

from __future__ import annotations

import pytest
from django.conf import settings

from apps.research.fetch import SweepBudget, fetch_page, scrapedo
from apps.research.fetch.site import crawl, map_site
from apps.research.fetch.types import SERVED, Outcome
from apps.research.harvest import anchors, content_digest
from apps.research.providers.tavily import tavily_guided_map

#: Every test here reaches the ladder, and the ladder writes a FetchAttempt row
#: for each rung. Without this the whole file errors on "Database access not
#: allowed" -- invisible until someone spends real money selecting `-m live`.
pytestmark = pytest.mark.django_db

#: Recorded in the 2026-09-19 live run: 30 anchors through Firecrawl.
_GLOBED = "https://globed.eu/how-to-apply/"
#: The same page with no trailing slash. Firecrawl's docs say `metadata.url` is
#: the FINAL url and `sourceURL` the requested one; this is the assertion that
#: holds them to it, because that value becomes OfficialSource.canonical_url.
_GLOBED_NO_SLASH = "https://globed.eu/how-to-apply"
#: A JS-shell page: 62 anchors through Firecrawl where our own client saw a
#: shell. CLAUDE.md's "A programme page the reader cannot see" is about this
#: host -- the vendor tier is the answer to it, and this is the check that the
#: answer still works.
_TURKIYE = "https://www.turkiyeburslari.gov.tr/applysteps"
#: A public, stable redirector. The point is that the LANDED url comes back, not
#: the one we asked for: that is what makes reader.require_same_origin a real
#: comparison on the scrape.do tier instead of a value compared against itself.
_REDIRECTOR = "https://httpbin.org/redirect-to?url=https://example.com/"

firecrawl_key = pytest.mark.skipif(
    not settings.FIRECRAWL_API_KEY, reason="FIRECRAWL_API_KEY is not set"
)
scrapedo_key = pytest.mark.skipif(
    not settings.SCRAPEDO_API_KEY, reason="SCRAPEDO_API_KEY is not set"
)
search_key = pytest.mark.skipif(
    not settings.SEARCH_API_KEY, reason="SEARCH_API_KEY is not set"
)

#: One host with a real sitemap and a real admissions section. 1 credit for
#: the map; the crawl below is bounded to 5 pages, not the sweep's 25.
_FAU = "https://ai.study.fau.eu/prospective-students/master-ai/"


@pytest.mark.live
@firecrawl_key
def test_the_map_returns_addresses_for_one_credit():
    """1 credit whatever it returns. The assertion is that it returns
    addresses at all -- the 2026-09-15 measurement had a filtered map return
    zero for a site the unfiltered call mapped at 76, which is why the
    fallback exists and why this gate watches the shape, not a count."""
    result = map_site(_FAU, api_key=settings.FIRECRAWL_API_KEY, search=("documents",))

    assert result.credits in (1, 2)
    assert all(url.startswith("https://") for url in result.urls)


@pytest.mark.live
@firecrawl_key
def test_a_crawl_reports_its_errors_endpoint_even_when_nothing_failed():
    """The endpoint is read on every crawl because the status counters cannot
    report a failure: completed == total on every finished crawl. This gate
    exists to catch the endpoint being renamed or moved -- which a stub
    cannot see, because a stub returns what the author believed.

    maxConcurrency=1: Firecrawl documents that crawl results vary between runs
    of the same configuration, and a gate that varies is not a gate.
    5 credits, not 25."""
    result = crawl(
        _FAU, api_key=settings.FIRECRAWL_API_KEY, limit=5, tag="live", max_concurrency=1
    )

    assert result.status in {"completed", "failed", "cancelled"}
    assert isinstance(result.errors, tuple)
    assert isinstance(result.robots_blocked, tuple)


@pytest.mark.live
@search_key
def test_the_guided_map_returns_urls_and_nothing_else():
    """The pointer shape the funnel wants. Also the standing check on the two
    behaviours Tavily's documentation does not state (spec 7.3a): if this
    starts returning objects with snippets, the provider function silently
    keeps only URLs and the stage's price stops matching its tariff.
    ~$0.03."""
    result = tavily_guided_map(
        url=_FAU,
        instructions="Find the pages listing the documents an applicant must submit.",
        select_domains=("fau.eu",),
        limit=10,
    )

    assert result.provider == "tavily-map"
    assert all(url.startswith("https://") for url in result.urls)
    assert result.cost_usd >= 0


@pytest.mark.live
@firecrawl_key
def test_the_default_tier_returns_markup_four_consumers_can_parse():
    """content_type, anchors and digest in one assertion block on purpose: the
    markdown defect satisfied "a body came back" and failed all three."""
    page = fetch_page(_GLOBED)

    assert page.fetched_via == "FIRECRAWL"
    assert page.content_type == "text/html"
    assert page.cost_credits == 1
    assert len(anchors(page.body)) > 0
    assert content_digest(page.body) != ""


@pytest.mark.live
@firecrawl_key
def test_a_javascript_shell_page_comes_back_with_its_links():
    """The whole reason a vendor tier exists. Our own client reads this host as
    a shell (CLAUDE.md, "A programme page the reader cannot see")."""
    page = fetch_page(_TURKIYE)

    assert page.fetched_via == "FIRECRAWL"
    assert len(anchors(page.body)) > 0


@pytest.mark.live
@firecrawl_key
def test_the_final_url_is_where_the_vendor_landed_not_what_we_asked_for():
    """This value becomes OfficialSource.canonical_url and is what
    reader.require_same_origin compares. A vendor that echoed the request back
    would make that guard pass by construction."""
    page = fetch_page(_GLOBED_NO_SLASH)

    assert page.final_url == _GLOBED


@pytest.mark.live
@scrapedo_key
def test_the_residue_tier_no_longer_refuses_a_page_that_answers_200():
    """25 credits. The shipped guard raised ChargedFailure on this exact URL --
    "origin answered HTTP '301'" -- for a page a direct request answers 200 to.
    The 301 is a proxy bounce landing on the identical URL."""
    page = scrapedo.scrape(_GLOBED, api_key=settings.SCRAPEDO_API_KEY)

    assert page.fetched_via == "SCRAPE_DO"
    assert page.final_url == _GLOBED
    assert len(page.body) > 500


@pytest.mark.live
@scrapedo_key
def test_the_residue_tier_reports_a_redirect_it_followed():
    """25 credits, and the one that proves `scrape.do-resolved-url` is really
    read rather than coincidentally equal to the request. If this ever returns
    the redirector's own URL, the same-origin guard on this tier is a tautology
    again and provenance is worth nothing."""
    page = scrapedo.scrape(_REDIRECTOR, api_key=settings.SCRAPEDO_API_KEY)

    assert page.final_url != _REDIRECTOR
    assert page.final_url.startswith("https://example.com/")


# --- the ladder gate: outcome class and credit ceiling ------------------------

#: Each entry: url, the outcomes that still pass, the credit ceiling.
#: Sources, all of them earlier measurements rather than this task's:
#: the hosts our own client refused on 2026-09-19; the shell pages measured
#: 2026-09-12 (CLAUDE.md, "A programme page the reader could not see"); the two
#: hosts recovered only from captures on 2026-09-15 (DAAD 2026-06-25, Sciences
#: Po 2026-02-01), whose Sciences Po capture could NOT be reproduced on
#: 2026-09-22 (design spec §16) -- which is why both accept BLOCKED; and the
#: five artifact hosts measured through /scrape on 2026-09-22 (a Drive PDF
#: parsed as 5 pages, a Google Doc, a Notion page, a PNG OCR'd for 1 credit).
_ANY_SERVED = frozenset(SERVED)
_SERVED_OR_REFUSED = _ANY_SERVED | {Outcome.BLOCKED}

HARD_HOSTS = [
    ("https://globed.eu/how-to-apply/", _ANY_SERVED, 2),
    ("https://mes.gov.ge/", _ANY_SERVED, 2),
    ("https://www.freiheit.org/", _ANY_SERVED, 2),
    ("https://www.bildungsserver.de/", _ANY_SERVED, 2),
    ("https://www.turkiyeburslari.gov.tr/applysteps", _ANY_SERVED, 30),
    (
        "https://www.sciencespo.fr/students/en/admissions/application-file.html",
        _SERVED_OR_REFUSED,
        60,
    ),
    (
        "https://www.daad.de/en/studying-in-germany/scholarships/"
        "daad-funding-programmes/prime/faq/",
        _SERVED_OR_REFUSED,
        60,
    ),
    # JASSO moved its scholarships page; the old /en/study_j/scholarships/ URL
    # answers HTTP 200 with a "not found" body. No fetch tier can tell a moved
    # page from a thin one, so SERVED here is never "the right page" -- the
    # labelled corpus's human label is what sees a soft 404.
    ("https://www.jasso.go.jp/en/ryugaku/scholarship_j/index.html", _ANY_SERVED, 30),
    ("https://drive.google.com/file/d/1KSLhcNlZT9r6hc-SwPWnjlrcOLdu7e-F/view", _ANY_SERVED, 8),
    (
        "https://docs.google.com/document/d/"
        "1HyVSOmli4bEY9xa5QFWoAETX6cixlC3fLpwHe_GqZc4/edit",
        _ANY_SERVED,
        2,
    ),
    (
        "https://cicscareers.notion.site/"
        "Guide-to-Grad-School-404d0dcd860c434385a1e2478814e845",
        _ANY_SERVED,
        2,
    ),
    ("https://tesseract-ocr.github.io/tessdoc/images/eurotext.png", _ANY_SERVED, 2),
]

#: A 60-page PDF at 1 credit a page would be the single most expensive call in
#: this file; the Rhodes template measured 1 credit whole (CLAUDE.md, "Web
#: fetching"), so this is a ten-fold alarm, not a prediction.
_RHODES_PDF = (
    "https://www.rhodeshouse.ox.ac.uk/media/2151/rhodes-scholarship-cv-template.pdf"
)


def _ceiling(credits: int) -> SweepBudget:
    """One number, both vendors: a host's ceiling is what the WALK may cost, and
    the walk crosses vendors. Per-vendor caps are a sweep's shape, not a page's.
    """
    return SweepBudget({"FIRECRAWL": credits, "SCRAPE_DO": credits})


@pytest.mark.live
@firecrawl_key
@scrapedo_key
@pytest.mark.parametrize("url,acceptable,ceiling", HARD_HOSTS)
def test_a_hard_host_reaches_an_acceptable_outcome_inside_its_ceiling(
    url, acceptable, ceiling
) -> None:
    page = fetch_page(url, budget=_ceiling(ceiling))

    assert page.outcome in acceptable, f"{url}: {page.outcome} ({page.reason})"
    assert page.cost_credits <= ceiling, f"{url}: spent {page.cost_credits}, ceiling {ceiling}"
    if page.outcome in SERVED:
        # Served-but-empty is the failure that reads as success: CLAUDE.md's
        # "a page that states nothing" is exactly what a shell looks like from
        # the outside, and 500 characters is well under any real programme page.
        assert len(page.markdown) > 500, f"{url}: served but nearly empty"
        assert page.fetched_via in {"FIRECRAWL", "SCRAPE_DO", "ARCHIVE"}


@pytest.mark.live
@firecrawl_key
def test_a_pdf_is_read_and_a_truncated_one_says_so() -> None:
    """`FETCHED_PARTIAL` exists so a rule missing from page 61 is a recorded
    truncation rather than a rule the page does not state."""
    page = fetch_page(_RHODES_PDF, budget=_ceiling(10))

    assert page.outcome in SERVED
    assert page.cost_credits <= 10
    if page.total_pages and page.page_count:
        assert page.page_count <= settings.FETCH_PDF_MAX_PAGES
        if page.total_pages > page.page_count:
            assert page.outcome is Outcome.FETCHED_PARTIAL


@pytest.mark.live
@firecrawl_key
def test_a_second_fetch_of_the_same_page_reports_a_change_status() -> None:
    """The saving the whole economics rests on: a free comparison instead of a
    reader run. `change_status` None is NOT "same" -- a caller that read it as
    "same" would skip a read the page earned -- so this asserts the vendor
    reported one at all, on the SECOND fetch, the first being the baseline.
    """
    budget = _ceiling(2)
    fetch_page(_GLOBED, tag="live-gate", budget=budget)
    second = fetch_page(_GLOBED, tag="live-gate", budget=budget)

    assert second.outcome in SERVED | {Outcome.UNCHANGED}
    assert second.change_status in {"new", "same", "changed", "removed"}
