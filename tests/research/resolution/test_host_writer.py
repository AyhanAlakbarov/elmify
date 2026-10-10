"""HOST_UNREACHABLE: the pipeline's one queue writer (plan Task 9).

A host the whole fetch ladder could not open is one closed question for the
platform ("where is this page now?"), keyed by the full lowercased hostname, so
every tenant's run that meets it lands on one item. The answer is written back
as a MovedPage or HostProfile.retired_at, and the writer and the fetch seam both
read those first -- so an answered host is never asked about, or paid for,
again.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.research.discovery import retrieve_official_source
from apps.research.egress import SourceBlocked
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.models import FetchAttempt, HostProfile, MovedPage, ResolutionItem
from apps.research.register import record_organisation
from apps.research.resolution.writers import file_host_unreachable

pytestmark = pytest.mark.django_db

_URL = "https://WWW.Shut.edu.tr/apply"
_CANONICAL = "https://www.shut.edu.tr/apply"


def _attempt(url: str, **fields: object) -> FetchAttempt:
    defaults: dict[str, object] = {
        "host": "www.shut.edu.tr", "rung": 1, "vendor": "FIRECRAWL", "outcome": "BLOCKED",
    }
    return FetchAttempt.objects.create(url=url, **{**defaults, **fields})


def test_a_blocked_host_files_one_item_keyed_by_its_lowercased_hostname() -> None:
    item = file_host_unreachable(_URL, "BLOCKED: origin_403")

    assert item is not None
    assert item.kind == "HOST_UNREACHABLE"
    assert item.subject_key == "host:www.shut.edu.tr"
    assert item.evidence["host"] == "www.shut.edu.tr"
    assert item.evidence["url"] == _CANONICAL
    assert item.evidence["why"] == "BLOCKED: origin_403"


def test_the_trail_is_the_last_ten_fetch_attempts_oldest_first_mapped_as_they_are() -> None:
    base = timezone.now()
    for index in range(12):
        row = _attempt(
            _CANONICAL, rung=index % 7, vendor="SCRAPE_DO", outcome="UNREACHABLE",
            reason=f"attempt {index}", status_code=503 if index == 11 else None,
        )
        FetchAttempt.objects.filter(id=row.id).update(created_at=base + timedelta(minutes=index))
    _attempt("https://www.shut.edu.tr/other", reason="another page's attempt")

    item = file_host_unreachable(_CANONICAL, "UNREACHABLE: timeout")

    assert item is not None
    trail = item.evidence["trail"]
    assert [step["reason"] for step in trail[:-1]] == [f"attempt {i}" for i in range(2, 11)]
    # The status code is the one FetchAttempt fact TrailStep has no field for,
    # so it leads the reason rather than being dropped.
    assert trail[-1]["reason"] == "HTTP 503: attempt 11"
    assert trail[-1] == {
        "vendor": "SCRAPE_DO", "rung": 11 % 7, "outcome": "UNREACHABLE",
        "reason": "HTTP 503: attempt 11",
        "at": (base + timedelta(minutes=11)).isoformat(),
    }


def test_a_url_with_no_attempts_files_an_empty_trail() -> None:
    """A test fetch, or a first-party transport, leaves no FetchAttempt. The
    question is still real; the trail is simply empty, never invented."""
    item = file_host_unreachable(_URL, "BLOCKED")

    assert item is not None and item.evidence["trail"] == []


def test_a_page_already_moved_is_not_asked_about_again() -> None:
    MovedPage.objects.create(from_url=_CANONICAL, to_url="https://www.shut.edu.tr/apply-2027")

    assert file_host_unreachable(_URL, "BLOCKED") is None
    assert not ResolutionItem.objects.exists()


def test_a_retired_host_is_not_asked_about_again() -> None:
    HostProfile.objects.create(host="www.shut.edu.tr", retired_at=timezone.now())

    assert file_host_unreachable(_URL, "BLOCKED") is None
    assert not ResolutionItem.objects.exists()


def test_the_subject_facts_come_from_the_register() -> None:
    record_organisation(
        domain="shut.edu.tr", name="Shut", kind="INSTITUTION", country_code="TR", found_via="x"
    )

    item = file_host_unreachable(_URL, "BLOCKED")

    assert item is not None and item.country_code == "TR"


def test_filing_the_same_host_twice_is_one_item() -> None:
    file_host_unreachable(_URL, "BLOCKED")
    file_host_unreachable("https://www.shut.edu.tr/fees", "UNREACHABLE")

    assert ResolutionItem.objects.count() == 1
    assert ResolutionItem.objects.get().evidence["url"] == "https://www.shut.edu.tr/fees"


# --- the fetch seam reads the answers first -----------------------------------


def _served(url: str, **_kwargs: object) -> FetchedPage:
    return FetchedPage(
        final_url=url, redirects=(), content_type="text/html", body=b"<p>page</p>",
        outcome=Outcome.FETCHED, fetched_via="FIRECRAWL", cost_credits=1,
    )


def test_a_moved_page_is_fetched_at_its_new_address() -> None:
    MovedPage.objects.create(from_url=_CANONICAL, to_url="https://www.shut.edu.tr/apply-2027")
    asked: list[str] = []

    def fetch(url: str, **kwargs: object) -> FetchedPage:
        asked.append(url)
        return _served(url)

    page = retrieve_official_source(_URL, fetch=fetch)

    assert asked == ["https://www.shut.edu.tr/apply-2027"]
    assert page.final_url == "https://www.shut.edu.tr/apply-2027"


def test_a_retired_host_raises_dead_without_a_vendor_call() -> None:
    """The saving: a host a person declared closed costs nothing on every
    later run."""
    HostProfile.objects.create(host="www.shut.edu.tr", retired_at=timezone.now())

    def must_not_be_called(_url: str, **_kwargs: object) -> FetchedPage:
        raise AssertionError("a retired host must not reach a vendor")

    with pytest.raises(SourceBlocked) as error:
        retrieve_official_source(_URL, fetch=must_not_be_called)

    assert error.value.outcome == "DEAD"
    assert "retired by an operator" in str(error.value)


def test_a_profile_without_retirement_still_fetches() -> None:
    HostProfile.objects.create(host="www.shut.edu.tr")

    page = retrieve_official_source(_URL, fetch=_served)

    assert page.outcome is Outcome.FETCHED
