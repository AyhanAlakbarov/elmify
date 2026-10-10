"""Rung 6: the Internet Archive.

A capture is a DIFFERENT claim about the world than a live fetch -- it says
"this page looked like this on some past date", never "this is what the page
says now" -- which is why it gets its own outcome (`Outcome.ARCHIVED`) and
carries `captured_at` rather than reusing `Outcome.FETCHED`.
"""

import functools
import json
import socket
from datetime import UTC, datetime

import pytest

from apps.research.egress import FetchResult, SourceBlocked, fetch_data_file
from apps.research.fetch import archive
from apps.research.fetch.types import Attempt, FetchedPage, Outcome, VendorUnavailable

NOW = datetime(2026, 9, 22, tzinfo=UTC)
_PAGE = b"<html><body>" + b"<p>A CV is required.</p>" * 300 + b"</body></html>"


def _page(body=_PAGE, final_url="https://web.archive.org/web/20260625120000id_/https://daad.de/prime",
          outcome=Outcome.FETCHED, reason=""):
    return FetchedPage(
        final_url=final_url, redirects=(), content_type="text/html", body=body,
        markdown="", outcome=outcome, fetched_via="SCRAPE_DO", rung=3, cost_credits=1,
        status_code=200, reason=reason,
        attempts=(Attempt(rung=3, vendor="SCRAPE_DO", outcome=outcome),),
    )


def _availability(timestamp="20260625120000", available=True):
    payload = {"archived_snapshots": {"closest": {
        "available": available, "timestamp": timestamp,
        "url": f"http://web.archive.org/web/{timestamp}/https://daad.de/prime",
    }}} if available else {"archived_snapshots": {}}
    return json.dumps(payload).encode()


def _probe(body: bytes):
    """The `probe` seam: `Callable[[str], FetchResult]`, matching
    `egress.fetch_data_file`'s real signature restricted to its one required
    argument."""
    def probe(lookup: str) -> FetchResult:
        return FetchResult(final_url=lookup, redirects=(), content_type="application/json",
                            body=body)
    return probe


def test_a_recent_capture_is_archived_and_carries_its_date():
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return _page()

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.outcome is Outcome.ARCHIVED
    assert page.captured_at == "2026-06-25"
    assert page.final_url == "https://daad.de/prime"
    assert "id_/" in calls[0]


def test_a_capture_older_than_the_window_is_stale_not_evidence():
    """Owner decision 2026-09-22: twelve months. A rule two cycles old must not
    reach a student's CV."""
    def fetch(url, **kwargs):
        raise AssertionError("must not fetch a capture outside the window")

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch,
        probe=_probe(_availability(timestamp="20240101120000")),
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_stale:2024-01-01"


def test_no_capture_at_all_leaves_the_outcome_blocked():
    def fetch(url, **kwargs):
        raise AssertionError("must not fetch when nothing is archived")

    page = archive.latest_capture(
        "https://x.test/a", api_key="k", now=NOW, fetch=fetch,
        probe=_probe(_availability(available=False)),
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_absent"


def test_the_lookup_uses_the_bare_url_form():
    """Measured 2026-09-22: DAAD's capture was found under host/path and not
    under the same URL with its scheme."""
    seen = []

    def probe(lookup):
        seen.append(lookup)
        return FetchResult(final_url=lookup, redirects=(), content_type="application/json",
                            body=_availability(available=False))

    archive.latest_capture("https://daad.de/prime?x=1", api_key="k", now=NOW, probe=probe)
    assert "url=daad.de%2Fprime%3Fx%3D1" in seen[0]


def test_an_archive_outage_is_a_retry_not_an_absence():
    """The CDX index answered 'Temporarily Offline' for the whole 2026-09-22
    probe window. Reading that as 'no capture' sends a recoverable host to a
    person. `egress.fetch_data_file` turns that kind of failure into a raised
    `SourceBlocked`, never a returned value -- this is the probe's real error
    contract, not a hand-built one."""
    def probe(lookup):
        raise SourceBlocked("archive.org returned HTTP 503")

    page = archive.latest_capture("https://x.test/a", api_key="k", now=NOW, probe=probe)
    assert page.outcome is Outcome.UNREACHABLE
    assert page.reason == "archive_unavailable"


def test_a_capture_of_a_different_origin_is_refused():
    """The URL inside the archive URL is what the capture claims to be. A
    capture of someone else's page is not evidence about this source."""
    def fetch(url, **kwargs):
        raise AssertionError("must not fetch an off-origin capture")

    payload = json.dumps({"archived_snapshots": {"closest": {
        "available": True, "timestamp": "20260625120000",
        "url": "http://web.archive.org/web/20260625120000/https://evil.test/prime",
    }}}).encode()
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(payload)
    )
    assert page.outcome is Outcome.OFF_SITE


def test_the_archive_credits_are_carried_into_the_result():
    """The probe now runs through `egress.fetch_data_file` -- our own
    transport, unbilled. Only the raw capture, fetched through the vendor at
    rung 3, spends credits."""
    def fetch(url, **kwargs):
        return _page()

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.cost_credits == 1
    assert page.fetched_via == "ARCHIVE"


# --- Critical #1: the probe through a REAL content predicate -------------


def test_probe_routes_through_fetch_data_file_and_a_real_short_payload_survives(monkeypatch):
    """The defect this proves fixed: before this task, the probe ran through
    `scrapedo.scrape`, whose `usable()` floor refuses any 200 under
    `types.MIN_DOCUMENT_BYTES` (1,000 bytes) -- and a real Wayback availability
    payload is ~200 bytes, so `latest_capture` always returned UNREACHABLE,
    regardless of the URL, and no test caught it because every test hand-built
    a FetchedPage and never ran the real predicate.

    This test calls the REAL `egress.fetch_data_file` (the default `probe`),
    with only its low-level `transport` faked, so the short body genuinely
    passes through `fetch_data_file`'s real content-type/size checks -- which
    have no such floor -- rather than through a stub that assumes the fix
    works."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    payload = _availability()
    assert len(payload) < 1_000, "fixture must stay short enough to prove the old floor wrong"

    class _Response:
        def __init__(self, body: bytes) -> None:
            self.status = 200
            self.headers = {"Content-Type": "application/json"}
            self._body = body

        def read(self, amount: int, decode_content: bool = True) -> bytes:
            chunk, self._body = self._body[:amount], self._body[amount:]
            return chunk

        def release_conn(self) -> None:
            pass

    probe = functools.partial(fetch_data_file, transport=lambda _target, _path: _Response(payload))

    def fetch(url, **kwargs):
        return _page()

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=probe
    )
    assert page.outcome is Outcome.ARCHIVED
    assert page.captured_at == "2026-06-25"


# --- Important #2: the raw capture's own final_url ------------------------


def test_a_raw_capture_landing_off_the_archive_wrapper_is_refused():
    """scrape.do's `final_url` is where the bytes actually came from. Wayback's
    `id_` redirect can legitimately serve a different snapshot than the one
    probed, and nothing upstream of the raw fetch checks where it landed --
    labelling those bytes ARCHIVED under the requested url would be
    provenance for a page never actually verified."""
    def fetch(url, **kwargs):
        return _page(final_url="https://web.archive.org/web/20260625120000id_/https://evil.test/prime")

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.outcome is Outcome.OFF_SITE
    assert page.reason.startswith("archive_unwrapped:")


def test_a_raw_capture_whose_final_url_is_not_even_a_wrapper_is_refused():
    def fetch(url, **kwargs):
        return _page(final_url="https://evil.test/prime")

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.outcome is Outcome.OFF_SITE


# --- Important #3: timestamp injection -------------------------------------


def test_a_timestamp_carrying_a_path_separator_is_refused_not_interpolated():
    """`closest['timestamp']` is interpolated into the raw capture URL. A value
    like "20260625120000/https://evil.test/p?" passes an 8-char date check and
    would route the fetch to a different host while a separately crafted
    `closest.url` satisfies the same-origin gate on its own. Only a bare
    14-digit timestamp is accepted."""
    def fetch(url, **kwargs):
        raise AssertionError("must not fetch using an unvalidated timestamp")

    payload = json.dumps({"archived_snapshots": {"closest": {
        "available": True,
        "timestamp": "20260625120000/https://evil.test/p?",
        "url": "http://web.archive.org/web/20260625120000/https://daad.de/prime",
    }}}).encode()
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(payload)
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_timestamp_invalid"


def test_a_non_numeric_timestamp_is_refused_not_treated_as_absent():
    """Fixes the misnomer: a malformed timestamp is not an absent capture --
    they must report differently."""
    payload = json.dumps({"archived_snapshots": {"closest": {
        "available": True, "timestamp": "not-a-date",
        "url": "http://web.archive.org/web/not-a-date/https://daad.de/prime",
    }}}).encode()
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, probe=_probe(payload)
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_timestamp_invalid"
    assert page.reason != "archive_absent"


# --- Important #4: no exception escapes ------------------------------------


def test_malformed_json_from_the_probe_is_unavailable_not_a_crash():
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, probe=_probe(b"{not json")
    )
    assert page.outcome is Outcome.UNREACHABLE
    assert page.reason == "archive_unavailable"


@pytest.mark.parametrize("body", [
    b'"offline"',
    b"[1]",
    b'{"archived_snapshots": "none"}',
    b'{"archived_snapshots": {"closest": "bad"}}',
])
def test_unexpected_but_valid_json_shapes_do_not_crash(body):
    """`json.loads` on these succeeds -- they are valid JSON, just not the
    expected shape. `.get()` on a str/list must not raise AttributeError."""
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, probe=_probe(body)
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_absent"


def test_a_vendor_exception_fetching_the_raw_capture_does_not_escape():
    """`scrapedo.scrape` raises `VendorUnavailable` for a transport failure or
    a missing key -- `latest_capture` must convert it to a value, the same as
    every other refusal, not let it propagate."""
    def fetch(url, **kwargs):
        raise VendorUnavailable("scrape.do transport: ConnectTimeoutError", escalate=False)

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.outcome is Outcome.UNREACHABLE
    assert page.reason.startswith("archive_unfetchable:")


# --- Important #5: previously unreached branches ---------------------------


def test_an_unparseable_captured_url_fails_closed_as_off_site():
    """The regex extracting the claimed original URL from `closest.url` can
    fail to match at all. The fallback must fail CLOSED (refuse), not open
    (assume same-origin)."""
    def fetch(url, **kwargs):
        raise AssertionError("must not fetch when the claimed capture url cannot be parsed")

    payload = json.dumps({"archived_snapshots": {"closest": {
        "available": True, "timestamp": "20260625120000",
        "url": "not-a-wayback-url-at-all",
    }}}).encode()
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(payload)
    )
    assert page.outcome is Outcome.OFF_SITE


def test_a_blocked_raw_capture_fetch_refuses_and_still_carries_its_credits():
    """The only branch that spends a credit and still refuses: the probe found
    a real, fresh, same-origin capture, but the vendor could not actually
    fetch the archived bytes (e.g. a challenge page from the archive itself)."""
    def fetch(url, **kwargs):
        return _page(outcome=Outcome.BLOCKED, reason="challenge")

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_unfetchable:challenge"
    assert page.cost_credits == 1


def test_a_timestamp_of_unicode_digits_is_refused_not_a_valueerror():
    """FIX 2: `\\d` matches Unicode decimal digits in Python, so Arabic-Indic
    digits passed `fullmatch` and then raised `ValueError` out of `strptime` --
    escaping `latest_capture` AND `fetch_page`, whose contract is that only a
    programming error leaves it (`__init__.py` catches SourceBlocked/UnsafeTarget
    only). No injection is possible -- no separator survives the pattern -- so
    this is a broken contract, not a hole."""
    payload = json.dumps({"archived_snapshots": {"closest": {
        "available": True, "timestamp": "٢٠٢٦٠٦٢٥١٢٠٠٠٠",
        "url": "http://web.archive.org/web/20260625120000/https://daad.de/prime",
    }}}).encode()
    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, probe=_probe(payload)
    )
    assert page.outcome is Outcome.BLOCKED
    assert page.reason == "archive_timestamp_invalid"


def test_a_capture_served_from_outside_web_archive_org_is_refused():
    """FIX 3, hardening against an unproven path: the second origin check reads
    the WRAPPED url out of `final_url` and never checks whose host served it,
    so `https://evil.test/web/20260101id_/https://daad.de/prime` passes it.
    Reaching this needs Wayback to redirect off-archive with a crafted path,
    and it rewrites `Location` to stay on its own host -- but the whole reason
    this rung has two origin checks is to not launder provenance."""
    def fetch(url, **kwargs):
        return _page(final_url="https://evil.test/web/20260625120000id_/https://daad.de/prime")

    page = archive.latest_capture(
        "https://daad.de/prime", api_key="k", now=NOW, fetch=fetch, probe=_probe(_availability())
    )
    assert page.outcome is Outcome.OFF_SITE


def test_capture_near_asks_for_the_date_it_was_given(monkeypatch):
    import datetime as dt
    import json

    from apps.research.egress import FetchResult
    from apps.research.fetch import archive

    asked = []

    def probe(lookup):
        asked.append(lookup)
        body = json.dumps({"archived_snapshots": {"closest": {
            "available": True, "timestamp": "20250402120000",
            "url": "http://web.archive.org/web/20250402120000/https://f.example/award"}}})
        return FetchResult(final_url=lookup, redirects=(), content_type="application/json",
                           body=body.encode())

    def fetch(raw, **kw):
        return archive.FetchedPage(
            final_url="https://web.archive.org/web/20250402120000id_/https://f.example/award",
            redirects=(), content_type="text/html", body=b"<main>x</main>" * 100,
            markdown="x", outcome=archive.Outcome.FETCHED, fetched_via="SCRAPE_DO", rung=3,
            cost_credits=1)

    page = archive.capture_near("https://f.example/award", at=dt.date(2025, 3, 26),
                                api_key="k", fetch=fetch, probe=probe)
    assert "timestamp=20250326" in asked[0]
    assert page.outcome == archive.Outcome.ARCHIVED and page.captured_at == "2025-04-02"


def test_capture_near_refuses_a_capture_from_another_cycle(monkeypatch, settings):
    import datetime as dt
    import json

    from apps.research.egress import FetchResult
    from apps.research.fetch import archive

    settings.CYCLE_ARCHIVE_SKEW_DAYS = 120

    def probe(lookup):
        body = json.dumps({"archived_snapshots": {"closest": {
            "available": True, "timestamp": "20230101120000",
            "url": "http://web.archive.org/web/20230101120000/https://f.example/award"}}})
        return FetchResult(final_url=lookup, redirects=(), content_type="application/json",
                           body=body.encode())

    page = archive.capture_near("https://f.example/award", at=dt.date(2025, 3, 26),
                                api_key="k", fetch=lambda *a, **k: None, probe=probe)
    assert page.outcome == archive.Outcome.BLOCKED and page.reason.startswith("archive_skew")
