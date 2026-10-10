from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.documents.research_fit.pages import fetch_page
from apps.research.egress import FetchResult, SourceBlocked
from apps.research.fetch.types import FetchedPage, Outcome

_HTML = (
    b"<html><body><main><h1>Chair of Robotics</h1>"
    b"<p>Prof. Dr. A. Schmidt leads the chair. We work on legged locomotion.</p>"
    b"</main></body></html>"
)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()


def test_a_page_on_the_domain_is_fetched_split_and_digested():
    calls = []

    def fetch(url):
        calls.append(url)
        return FetchResult("https://www.tum.de/robotics", (), "text/html", _HTML)

    page, outcome = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=uuid4(), fetch=fetch
    )
    assert outcome == "ok"
    assert page.url == "https://www.tum.de/robotics"
    assert "Prof. Dr. A. Schmidt leads the chair." in page.sentences
    assert len(page.digest) == 64 and calls == ["https://www.tum.de/robotics"]


def test_a_redirect_off_the_domain_is_refused_unread():
    def fetch(url):
        return FetchResult("https://evil.example/", ("https://www.tum.de/x",), "text/html", _HTML)

    page, outcome = fetch_page(
        "https://www.tum.de/x", domain="tum.de", tenant_id=uuid4(), fetch=fetch
    )
    assert page is None and outcome == "off_domain"


def test_a_plaintext_http_final_url_is_refused_unread():
    def fetch(url):
        return FetchResult("http://www.tum.de/robotics", (), "text/html", _HTML)

    page, outcome = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=uuid4(), fetch=fetch
    )
    assert page is None and outcome == "off_domain"


def test_a_shell_is_unreadable_not_empty():
    shell = b"<html><body><div id='app'></div>" + b"<script>x</script>" * 2000 + b"</body></html>"

    def fetch(url):
        return FetchResult(url, (), "text/html", shell)

    page, outcome = fetch_page(
        "https://www.tum.de/app", domain="tum.de", tenant_id=uuid4(), fetch=fetch
    )
    assert page is None and outcome == "unreadable"


def test_a_fetch_failure_is_an_outcome_not_an_exception():
    def fetch(url):
        raise SourceBlocked("403")

    page, outcome = fetch_page(
        "https://www.tum.de/x", domain="tum.de", tenant_id=uuid4(), fetch=fetch
    )
    assert page is None and outcome == "fetch_failed"


def test_the_second_fetch_of_the_same_url_in_a_tenant_hits_the_cache():
    tenant = uuid4()
    calls = []

    def fetch(url):
        calls.append(url)
        return FetchResult(url, (), "text/html", _HTML)

    first, _ = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=tenant, fetch=fetch
    )
    second, _ = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=tenant, fetch=fetch
    )
    assert first == second and calls == ["https://www.tum.de/robotics"]
    third, _ = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=uuid4(), fetch=fetch
    )
    assert third == first and len(calls) == 2  # another tenant pays its own fetch


def test_a_capture_carries_its_date_onto_the_page():
    """These sentences are cited in a student's letter. `retrieve_official_source`
    returns ARCHIVED as SERVED and `final_url` is the ORIGINAL url, so a capture
    up to a year old is otherwise indistinguishable here from a live read."""
    archived = FetchedPage(
        final_url="https://www.tum.de/robotics", redirects=(), content_type="text/html",
        body=_HTML, fetched_via="ARCHIVE", outcome=Outcome.ARCHIVED, rung=6,
        captured_at="2026-06-25",
    )
    page, outcome = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=uuid4(),
        fetch=lambda _url: archived,
    )
    assert outcome == "ok" and page.captured_at == "2026-06-25"


def test_a_live_page_carries_no_capture_date():
    page, _ = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=uuid4(),
        fetch=lambda url: FetchResult(url, (), "text/html", _HTML),
    )
    assert page.captured_at == ""


def test_the_capture_date_survives_the_page_cache():
    """The cache stores a dict, not the Page -- a field it does not carry is
    lost on every hit after the first, which is most of them."""
    tenant = uuid4()
    archived = FetchedPage(
        final_url="https://www.tum.de/robotics", redirects=(), content_type="text/html",
        body=_HTML, fetched_via="ARCHIVE", outcome=Outcome.ARCHIVED, rung=6,
        captured_at="2026-06-25",
    )
    first, _ = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=tenant,
        fetch=lambda _url: archived,
    )
    second, _ = fetch_page(
        "https://www.tum.de/robotics", domain="tum.de", tenant_id=tenant,
        fetch=lambda _url: pytest.fail("the cache should have answered"),
    )
    assert first == second and second.captured_at == "2026-06-25"
