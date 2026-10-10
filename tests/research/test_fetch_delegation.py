"""The boundary where fetch outcomes become exceptions again.

Ten of the eleven outcomes are VALUES inside `apps/research/fetch`. All eight
callers of `retrieve_official_source` predate that engine and are written
against a raised `SourceBlocked`, so this wrapper is the one place the
translation happens -- and a translation that silently does not happen is the
failure CLAUDE.md names as this repo's worst: a refusal carrying no bytes read
as "the page states nothing".

The last two tests are the ones that matter. Every other test of this seam
injects `fetch=`, which means the seam itself is never exercised; those two
drive `reader.read_program_page` and the ladder with no injection at all,
through the real providers with only their HTTP transport faked.
"""

import json
import socket
from types import SimpleNamespace
from uuid import uuid4

import pytest
import urllib3
from django.core.cache import cache

from apps.funding.models import (
    Institution,
    OfficialSource,
    OfficialSourceSnapshot,
    Program,
    ProgramStatement,
)
from apps.research.discovery import retrieve_official_source
from apps.research.egress import SourceBlocked
from apps.research.fetch import FetchBudgetExhausted, fetch_page
from apps.research.fetch.types import Attempt, FetchedPage, Outcome
from apps.research.models import ConsultantResearchTask, FetchAttempt
from apps.research.reader import read_program_page

pytestmark = pytest.mark.django_db

_URL = "https://official.example/program"
_BODY = b"<html><body><main>" + b"<p>A CV is required.</p>" * 120 + b"</main></body></html>"


def _page(outcome: Outcome, **overrides: object) -> FetchedPage:
    fields: dict[str, object] = {
        "final_url": _URL, "redirects": (), "content_type": "text/html", "body": _BODY,
        "markdown": "# A", "outcome": outcome, "fetched_via": "FIRECRAWL", "rung": 1,
        "cost_credits": 1, "status_code": 200,
        "attempts": (Attempt(rung=1, vendor="FIRECRAWL", outcome=outcome),),
    }
    fields.update(overrides)
    return FetchedPage(**fields)  # type: ignore[arg-type]


def _returning(page: FetchedPage):
    def fetch(_url: str, **_kwargs: object) -> FetchedPage:
        return page

    return fetch


# --- values that stay values -------------------------------------------------


@pytest.mark.parametrize(
    "outcome", [Outcome.FETCHED, Outcome.FETCHED_PARTIAL, Outcome.ARCHIVED]
)
def test_a_served_outcome_comes_back_as_a_page(outcome: Outcome) -> None:
    """ARCHIVED is served too: rung 6 exists to produce a readable page, and a
    caller that only knows FetchResult must not lose it because the bytes came
    from a capture. `Outcome.ARCHIVED` is the signal that they did."""
    page = retrieve_official_source(_URL, fetch=_returning(_page(outcome)))

    assert page.body == _BODY
    assert page.outcome is outcome


def test_an_unchanged_page_still_carries_its_bytes_to_the_old_callers() -> None:
    """UNCHANGED is the host answering in full -- firecrawl.py builds it from
    the same payload as a FETCHED page, body and all (`_CARRIES_BYTES`). The
    saving is the READER's own digest short-circuit, which needs those bytes;
    raising here would instead file every unchanged page as a blocked source and
    put a consultant on a page that did not move."""
    page = retrieve_official_source(
        _URL, fetch=_returning(_page(Outcome.UNCHANGED, change_status="same"))
    )

    assert page.body == _BODY
    assert page.outcome is Outcome.UNCHANGED


# --- values that become exceptions -------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome.BLOCKED, Outcome.UNREACHABLE, Outcome.UNREADABLE, Outcome.DEAD,
        Outcome.OFF_SITE, Outcome.INVALID, Outcome.RETRY_SCHEDULED,
    ],
)
def test_every_unserved_outcome_raises_for_the_old_callers(outcome: Outcome) -> None:
    fetch = _returning(_page(outcome, body=b"", content_type="", reason="origin_403"))

    with pytest.raises(SourceBlocked) as error:
        retrieve_official_source(_URL, fetch=fetch)

    # The outcome travels as an attribute: pipeline.py decides from it which
    # refusals are a question for the resolution queue, and never parses it
    # back out of the message. The message keeps it for a person reading a log.
    assert error.value.outcome == str(outcome)
    assert str(outcome) in str(error.value)
    assert "origin_403" in str(error.value)


def test_an_unchanged_page_with_no_bytes_is_refused_rather_than_served() -> None:
    """firecrawl.py returns UNCHANGED *before* its usable() checks, so an
    empty one is possible and would reach the reader as a page that says
    nothing -- the exact confusion this engine exists to remove."""
    with pytest.raises(SourceBlocked) as error:
        retrieve_official_source(_URL, fetch=_returning(_page(Outcome.UNCHANGED, body=b"")))

    assert error.value.outcome == "UNCHANGED"
    assert str(Outcome.UNCHANGED) in str(error.value)


def test_a_budget_stop_raises_the_subclass_that_stops_a_whole_sweep() -> None:
    """`manage.py fetch_ladder` catches FetchBudgetExhausted BEFORE
    SourceBlocked: an exhausted budget ends the sweep where a blocked host skips
    one line. Flattening BUDGET into a bare SourceBlocked would keep the sweep
    running against a cap it has already passed."""
    fetch = _returning(_page(Outcome.BUDGET, body=b"", content_type="", reason="100 of 100"))

    with pytest.raises(FetchBudgetExhausted) as error:
        retrieve_official_source(_URL, fetch=fetch)

    assert isinstance(error.value, SourceBlocked)
    assert error.value.outcome == "BUDGET"
    assert str(Outcome.BUDGET) in str(error.value)


# --- the tests that do not inject anything -----------------------------------


@pytest.fixture
def refusing_vendors(monkeypatch, settings):
    """Both vendors keyed, both transports faked, DNS faked.

    `urllib3.request` is the single call `firecrawl._post` and `scrapedo._get`
    both make, so replacing it drives the REAL providers behind the REAL ladder
    while making a real API call impossible. Every rung is answered with the
    origin's own 403 -- BLOCKED on both vendors -- so the ladder walks 1, 3, 4
    and ends at rung 5's RETRY_SCHEDULED.
    """
    settings.FIRECRAWL_API_KEY = "test-key"
    settings.SCRAPEDO_API_KEY = "test-key"
    cache.clear()

    def fake_getaddrinfo(host, port, *_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    calls: list[str] = []

    def refuse(method: str, url: str, **_kwargs: object):
        calls.append(url)
        if "firecrawl" in url:
            payload = json.dumps({
                "success": True,
                "data": {
                    "markdown": "", "html": "",
                    "metadata": {"url": _URL, "statusCode": 403, "contentType": "text/html"},
                },
            }).encode()
            return SimpleNamespace(status=200, data=payload, headers={})
        return SimpleNamespace(status=403, data=b"Forbidden", headers={})

    monkeypatch.setattr(urllib3, "request", refuse)
    yield calls
    cache.clear()


@pytest.fixture
def program() -> Program:
    institution = Institution.objects.create(
        canonical_key=f"institution:{uuid4()}",
        name="Example University",
        country_code="DE",
        official_website="https://official.example",
    )
    return Program.objects.create(
        institution=institution,
        canonical_key=f"program:{uuid4()}",
        name="MSc Chemistry",
        campus_name="Main Campus",
        city="Berlin",
        country_code="DE",
        location_key="de:berlin",
        degree_level="MASTER",
        teaching_languages=["English"],
        duration_months=24,
    )


class _MustNotBeCalled:
    def parse(self, **_kwargs: object) -> object:  # pragma: no cover - the raise is the point
        raise AssertionError("no model call may be made for a page that was never read")


class _MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: list[tuple[str, bytes]] = []

    def put(self, key: str, body: bytes) -> str:  # pragma: no cover - nothing may be stored
        self.objects.append((key, body))
        return "version-1"


def test_a_refusal_reaches_a_real_caller_as_an_exception(refusing_vendors, program) -> None:
    """THE test this task exists for: no `retrieve=`, no `fetch=`.

    Every other test of the reader fills the seam under test, so none of them
    can see a refusal arriving as an empty success. Here the vendors refuse for
    real and `read_program_page` must raise -- not archive an empty snapshot,
    not call the model, and not report a programme page that states nothing.
    """
    source = OfficialSource.objects.create(
        canonical_url=_URL,
        publisher="Official University",
        source_type=OfficialSource.Type.PROGRAM,
    )
    store = _MemoryObjectStore()

    with pytest.raises(SourceBlocked) as error:
        read_program_page(
            program=program, source=source, store=store,
            parser=_MustNotBeCalled(), admissions_cycle="2027",
        )

    assert str(Outcome.RETRY_SCHEDULED) in str(error.value)
    assert refusing_vendors, "the real providers were never driven"
    assert store.objects == []
    assert OfficialSourceSnapshot.objects.count() == 0
    assert ProgramStatement.objects.count() == 0
    # The ledger is still written: a refusal is recorded, never silent.
    assert sorted(FetchAttempt.objects.values_list("rung", flat=True)) == [1, 3, 4, 5]


def test_the_ladder_writes_no_tenant_scoped_row(refusing_vendors) -> None:
    """`ConsultantResearchTask` is tenant-scoped under FORCE RLS and the ladder
    runs on the tenantless catalog read too, where `current_tenant_id()` raises.
    So the ladder returns the outcome and the FetchAttempt trail; the pipeline
    files a BLOCKED/UNREACHABLE host to the platform's resolution queue
    (`file_host_unreachable`). `_base_manager` because there is no tenant here
    to scope the count to."""
    page = fetch_page(_URL)

    assert page.outcome is Outcome.RETRY_SCHEDULED
    assert ConsultantResearchTask._base_manager.count() == 0
