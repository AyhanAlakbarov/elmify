from apps.research.fetch.types import Attempt, FetchedPage, Outcome, usable


def test_a_short_two_hundred_is_a_block_not_a_document():
    """Measured 2026-09-19: mischolarship.com answered HTTP 200 with 469 bytes
    of nothing and was billed 1 credit. Treating that as FETCHED is how a
    blocked page becomes 'this programme states no CV rules'."""
    ok, reason = usable("text/html", b"x" * 469, 200)
    assert ok is False
    assert reason == "short_body"


def test_a_challenge_interstitial_is_a_block():
    body = b"<html><title>Just a moment...</title>" + b"y" * 2_000 + b"</html>"
    ok, reason = usable("text/html", body, 200)
    assert ok is False
    assert reason == "challenge"


def test_a_real_page_is_usable():
    body = b"<html><body>" + b"<p>Applicants must submit a CV.</p>" * 200 + b"</body></html>"
    assert usable("text/html", body, 200) == (True, "")


def test_a_disallowed_content_type_is_refused():
    ok, reason = usable("application/zip", b"z" * 5_000, 200)
    assert ok is False
    assert reason == "content_type:application/zip"


def test_a_vendor_parsed_image_or_office_document_is_usable():
    """Measured 2026-09-22: Firecrawl OCRs a PNG through /scrape for 1 credit
    and parses DOCX/XLSX by URL. Our old allowlist was written for a client
    that could read none of these; on the vendor path, `markdown` is what a
    reader reads and the content type is informational."""
    assert usable(
        "image/png", b"\x89PNG" + b"\x00" * 2_000, 200, markdown="Başvuru için CV."
    ) == (True, "")
    assert usable(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        b"PK" + b"\x00" * 5_000, 200, markdown="# Guidelines",
    ) == (True, "")
    ok, reason = usable("image/png", b"\x89PNG" + b"\x00" * 2_000, 200)
    assert (ok, reason) == (False, "content_type:image/png")  # no markdown: nothing to read


def test_a_body_over_the_cap_is_refused():
    ok, reason = usable("text/html", b"x" * (10 * 1024 * 1024 + 1), 200)
    assert ok is False
    assert reason == "too_large"


def test_outcome_is_a_closed_set_of_eleven_plus_the_intermediate_state():
    """Spec §6: eleven outcomes, plus RETRY_SCHEDULED, which is the one
    intermediate state and never reaches a caller of fetch_page. A twelfth
    OUTCOME is a design change, not an implementation detail -- every caller
    switches on this set."""
    assert sorted(o.value for o in Outcome) == [
        "ARCHIVED", "BLOCKED", "BUDGET", "DEAD", "FETCHED", "FETCHED_PARTIAL",
        "INVALID", "OFF_SITE", "RETRY_SCHEDULED", "UNCHANGED", "UNREACHABLE",
        "UNREADABLE",
    ]


def test_a_fetched_page_carries_its_trail():
    # FetchedPage's cost field is `cost_credits`, not `credits` -- master's
    # name, kept so fetch_ladder/SweepBudget.spend/test_fetch_router.py keep
    # reading it unchanged. Attempt.credits is a distinct, new field.
    page = FetchedPage(
        final_url="https://example.test/a",
        redirects=(),
        content_type="text/html",
        body=b"<html></html>",
        markdown="# A",
        outcome=Outcome.FETCHED,
        fetched_via="FIRECRAWL",
        rung=1,
        cost_credits=1,
        status_code=200,
        attempts=(Attempt(rung=1, vendor="FIRECRAWL", outcome=Outcome.FETCHED, credits=1),),
    )
    assert page.ok is True
    assert page.attempts[0].vendor == "FIRECRAWL"


def test_an_unreadable_page_is_not_ok_but_is_not_an_exception():
    page = FetchedPage(
        final_url="https://example.test/a", redirects=(), content_type="text/html",
        body=b"", markdown="", outcome=Outcome.UNREADABLE, fetched_via="SCRAPE_DO",
        rung=4, cost_credits=25, status_code=200, attempts=(),
    )
    assert page.ok is False
