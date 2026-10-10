"""The ladder (`fetch_page`) and the sweep command named after it.

Two subjects in one file because they are one ladder: `fetch_page` walks the
rungs, and `manage.py fetch_ladder` is the operator's view of a whole sweep of
them. The command's tests stub `retrieve_official_source` and never reach the
real ladder; the ladder's tests stub the three PROVIDERS and exercise
everything above them for real.
"""

import ast
import socket
from datetime import UTC, datetime, timedelta
from io import StringIO
from ipaddress import ip_address
from pathlib import Path

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.egress import SourceBlocked
from apps.research.fetch import FetchBudgetExhausted, SweepBudget, fetch_page
from apps.research.fetch.types import Attempt, FetchedPage, Outcome, VendorUnavailable
from apps.research.models import FetchAttempt, HostProfile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _resolve_test_hosts(monkeypatch):
    """`*.test` domains do not resolve in this sandbox (RFC 2606), so
    `validate_public_url` would refuse every URL here before the ladder ran.
    Host-aware, exactly like test_fetch_firecrawl.py's: a literal IP is returned
    unchanged so the link-local refusal below still exercises `is_global`."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ip_address(host)
            address = host
        except ValueError:
            address = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


_BODY = b"<html><body>" + b"<p>A CV is required.</p>" * 300 + b"</body></html>"


def _page(
    outcome,
    *,
    vendor="FIRECRAWL",
    rung=1,
    credits=1,
    body=_BODY,
    final_url="https://e.test/a",
    reason="",
    markdown="# A",
    **extra,
):
    return FetchedPage(
        final_url=final_url,
        redirects=(),
        content_type="text/html",
        body=body,
        markdown=markdown,
        outcome=outcome,
        fetched_via=vendor,
        rung=rung,
        cost_credits=credits,
        status_code=200,
        reason=reason,
        attempts=(
            Attempt(rung=rung, vendor=vendor, outcome=outcome, credits=credits, reason=reason),
        ),
        **extra,
    )


def _providers(**overrides):
    """Three providers, each answering UNREACHABLE unless a test says otherwise.

    The stubs take the REAL keyword names the ladder calls with, so a rename in
    `fetch_page` fails here rather than passing on a silently ignored kwarg.
    """

    def missing(url, **kwargs):
        return _page(Outcome.UNREACHABLE, credits=0, rung=kwargs.get("rung", 1))

    provided = {"firecrawl": missing, "scrapedo": missing, "archive": missing}
    provided.update(overrides)

    def firecrawl(url, *, api_key, tag=None, actions=False, profile=None, request_id=None,
                  screenshot=False):
        return provided["firecrawl"](url, actions=actions)

    def scrapedo(url, *, api_key, rung=3, profile=None, session_id=None,
                 screenshot=False):
        return provided["scrapedo"](url, rung=rung, session_id=session_id)

    def archive(url, *, api_key, now=None):
        return provided["archive"](url)

    return {"firecrawl": firecrawl, "scrapedo": scrapedo, "archive": archive}


def _explode(*args, **kwargs):  # pragma: no cover - the assertion is the point
    raise AssertionError("this rung must not be reached")


def _blocked(url, **kwargs):
    """A host that refuses every rung. 403 is the one code both providers agree
    escalates, so this walks the ladder to its end."""
    rung = kwargs.get("rung", 1)
    return _page(Outcome.BLOCKED, vendor="SCRAPE_DO" if rung >= 3 else "FIRECRAWL",
                 rung=rung, reason="origin_403")


# --- stopping at the first usable document -----------------------------------


def test_rung_one_serving_stops_the_ladder() -> None:
    calls = []

    def firecrawl(url, actions=False, **kwargs):
        calls.append(actions)
        return _page(Outcome.FETCHED)

    page = fetch_page("https://e.test/a", providers=_providers(firecrawl=firecrawl))

    assert page.outcome is Outcome.FETCHED
    assert page.rung == 1
    assert calls == [False]  # the actions rung is not bought by a page that read


def test_a_shell_at_rung_one_escalates_to_actions_not_to_another_vendor() -> None:
    """The page is reachable, it just has not run its JavaScript yet -- which is
    a second Firecrawl call, not a second vendor."""
    seen = []

    def firecrawl(url, actions=False, **kwargs):
        seen.append(actions)
        if actions:
            return _page(Outcome.FETCHED, rung=2)
        return _page(Outcome.UNREADABLE, rung=1, reason="shell")

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=_explode)
    )

    assert seen == [False, True]
    assert page.outcome is Outcome.FETCHED
    assert page.rung == 2


def test_a_shell_that_survives_rung_two_skips_the_plain_transport() -> None:
    """Rung 2 already rendered and still got a shell, so rung 3 -- a transport
    with render=false -- cannot do better. Spending its credit to find that out
    is the one thing the rung table (spec §4, rung 4 "or rung 2 was still a
    shell") says not to do."""
    rungs = []

    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.UNREADABLE, rung=2 if actions else 1, reason="shell")

    def scrapedo(url, rung=3, **kwargs):
        rungs.append(rung)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung, credits=25)

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=scrapedo)
    )

    assert rungs == [4]
    assert page.rung == 4


def test_no_document_at_rung_one_goes_to_scrapedo_plain_first() -> None:
    rungs = []

    def scrapedo(url, rung=3, **kwargs):
        rungs.append(rung)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung)

    page = fetch_page("https://e.test/a", providers=_providers(scrapedo=scrapedo))

    assert rungs == [3]  # never the 25-credit rung on the way past
    assert page.rung == 3


def test_a_block_that_survives_rung_three_reaches_the_residential_browser() -> None:
    rungs = []

    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.BLOCKED, reason="origin_403")

    def scrapedo(url, rung=3, **kwargs):
        rungs.append(rung)
        if rung == 3:
            return _page(Outcome.BLOCKED, vendor="SCRAPE_DO", rung=3, reason="origin_403")
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=4, credits=25)

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=scrapedo)
    )

    assert rungs == [3, 4]
    assert (page.rung, page.cost_credits) == (4, 27)  # 1 + 1 + 25, the whole trail


def test_the_session_id_is_stable_across_processes() -> None:
    """A residential address that changes between pages of one site re-triggers
    the challenge rung 4 exists to pass, so the session key may not be `hash()`
    -- which is salted per process (spec §4 rung 4)."""
    seen = []

    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.BLOCKED, reason="origin_403")

    def scrapedo(url, rung=3, session_id=None, **kwargs):
        seen.append(session_id)
        return _page(Outcome.BLOCKED, vendor="SCRAPE_DO", rung=rung, reason="origin_403")

    fetch_page("https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=scrapedo))
    fetch_page("https://e.test/b", providers=_providers(firecrawl=firecrawl, scrapedo=scrapedo))

    assert len(set(seen)) == 1 and seen[0] is not None


# --- an answer is an answer: the ladder stops -----------------------------------


def test_a_dead_origin_stops_at_rung_one_and_spends_nothing_more() -> None:
    """A 404 is an ANSWER. Firecrawl escalates proxies on 401/403/429 only, for
    exactly this reason; so does the ladder."""
    calls = []

    def firecrawl(url, actions=False, **kwargs):
        calls.append("firecrawl")
        return _page(Outcome.DEAD, reason="origin_404")

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=_explode)
    )

    assert page.outcome is Outcome.DEAD
    assert calls == ["firecrawl"]


def test_an_http_400_is_terminal_like_any_other_dead_answer() -> None:
    """Obligation 6, decided TERMINAL. scrapedo.py classifies 400 as DEAD; the
    counter-argument is that a 400 can mean WE built the request wrong, which is
    not "permanently gone". It is still terminal here, because rung 4 sends the
    SAME url and would earn the same 400 -- and scrape.do's published billing
    counts 400 as a successful request, so asking again costs 25 credits for a
    byte-identical refusal. A malformed request is a code fix, not a rung."""
    def scrapedo(url, rung=3, **kwargs):
        if rung == 3:
            return _page(Outcome.DEAD, vendor="SCRAPE_DO", rung=3, reason="origin_400")
        raise AssertionError("a 400 does not become a 200 on a residential proxy")

    page = fetch_page("https://e.test/a", providers=_providers(scrapedo=scrapedo))

    assert (page.outcome, page.reason) == (Outcome.DEAD, "origin_400")


def test_an_unsafe_url_never_reaches_a_vendor() -> None:
    page = fetch_page(
        "http://169.254.170.2/creds",
        providers=_providers(firecrawl=_explode, scrapedo=_explode, archive=_explode),
    )

    assert page.outcome is Outcome.INVALID
    assert page.cost_credits == 0


def test_an_off_site_final_url_is_refused_when_provenance_is_required() -> None:
    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.FETCHED, final_url="https://elsewhere.test/a")

    page = fetch_page(
        "https://e.test/a",
        require_origin="https://e.test/a",
        providers=_providers(firecrawl=firecrawl, scrapedo=_explode),
    )

    assert page.outcome is Outcome.OFF_SITE
    assert page.body == b""  # the bytes do not travel with a refusal


def test_provenance_is_compared_on_ORIGIN_not_on_the_whole_url() -> None:
    """Official pages redirect /x to /x/ as housekeeping; whole-URL equality
    rejects the real page over a trailing slash (CLAUDE.md, Decision B)."""
    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.FETCHED, final_url="https://e.test/a/2027-intake")

    page = fetch_page(
        "https://e.test/a", require_origin="https://e.test/a",
        providers=_providers(firecrawl=firecrawl),
    )

    assert page.outcome is Outcome.FETCHED


def test_unchanged_short_circuits_every_later_rung() -> None:
    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.UNCHANGED)

    page = fetch_page(
        "https://e.test/a", tag="2027",
        providers=_providers(firecrawl=firecrawl, scrapedo=_explode),
    )

    assert page.outcome is Outcome.UNCHANGED


# --- rungs 5 and 6 ------------------------------------------------------------


def test_exhausting_every_live_rung_schedules_a_retry_before_the_archive() -> None:
    """Rung 5 comes before rung 6: a host that is merely down must not be
    answered from a year-old capture on the first failure."""
    page = fetch_page(
        "https://e.test/a",
        providers=_providers(firecrawl=_blocked, scrapedo=_blocked, archive=_explode),
    )

    assert page.outcome is Outcome.RETRY_SCHEDULED
    assert [attempt.rung for attempt in page.attempts] == [1, 3, 4, 5]


def test_the_archive_is_read_only_once_retries_are_spent() -> None:
    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(
            url="https://e.test/a", host="e.test", rung=5, vendor="NONE",
            outcome=Outcome.RETRY_SCHEDULED, attempt_no=attempt_no,
        )

    def archive(url, **kwargs):
        return _page(Outcome.ARCHIVED, vendor="ARCHIVE", rung=6, credits=2,
                     captured_at="2026-06-25")

    page = fetch_page(
        "https://e.test/a",
        providers=_providers(firecrawl=_blocked, scrapedo=_blocked, archive=archive),
    )

    assert page.outcome is Outcome.ARCHIVED
    assert page.captured_at == "2026-06-25"


def test_an_archive_miss_after_every_rung_ends_as_the_failure_that_caused_it() -> None:
    """"BLOCKED" and "UNREACHABLE" are different fixes, and the last rung read
    (the archive) is not what the caller needs to be told about."""
    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(
            url="https://e.test/a", host="e.test", rung=5, vendor="NONE",
            outcome=Outcome.RETRY_SCHEDULED, attempt_no=attempt_no,
        )

    def archive(url, **kwargs):
        return _page(Outcome.BLOCKED, vendor="ARCHIVE", rung=6, credits=0,
                     reason="archive_absent")

    page = fetch_page(
        "https://e.test/a",
        providers=_providers(firecrawl=_blocked, scrapedo=_blocked, archive=archive),
    )

    assert page.outcome is Outcome.BLOCKED
    assert [attempt.rung for attempt in page.attempts] == [1, 3, 4, 6]


def test_the_retry_delay_is_shorter_for_a_block_than_for_an_outage(settings) -> None:
    """A rate-limit window clears in hours; an outage does not."""
    settings.FETCH_RETRY_HOURS = {"unreachable": [24], "blocked": [6]}
    before = timezone.now()

    fetch_page("https://e.test/blocked",
               providers=_providers(firecrawl=_blocked, scrapedo=_blocked))
    fetch_page("https://e.test/down", providers=_providers())

    rows = {
        row.url: row.retry_after
        for row in FetchAttempt.objects.filter(outcome=Outcome.RETRY_SCHEDULED)
    }
    assert rows["https://e.test/blocked"] - before < timedelta(hours=7)
    assert rows["https://e.test/down"] - before > timedelta(hours=23)


# --- money --------------------------------------------------------------------


def test_a_budget_refusal_stops_the_ladder_without_calling_a_vendor() -> None:
    spent = SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})
    spent.spend("FIRECRAWL", 1)
    spent.spend("SCRAPE_DO", 1)

    page = fetch_page(
        "https://e.test/a", budget=spent,
        providers=_providers(firecrawl=_explode, scrapedo=_explode, archive=_explode),
    )

    assert page.outcome is Outcome.BUDGET
    assert page.cost_credits == 0


def test_a_budget_refusal_re_enters_the_url_in_the_next_window() -> None:
    """Spec §6: a URL dropped at a budget boundary comes back. It must NOT come
    back as a RETRY_SCHEDULED row -- `_retries_spent` counts those for a URL
    forever, so one would spend a retry round on a failure that was never the
    host's fault. The BUDGET row carries `retry_after` instead, and Task 10's
    queue scans for it alongside RETRY_SCHEDULED."""
    spent = SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 1})
    spent.spend("FIRECRAWL", 1)
    spent.spend("SCRAPE_DO", 1)

    page = fetch_page(
        "https://e.test/a", budget=spent,
        providers=_providers(firecrawl=_explode, scrapedo=_explode, archive=_explode),
    )

    assert page.outcome is Outcome.BUDGET
    row = FetchAttempt.objects.get(url="https://e.test/a")
    assert row.outcome == str(Outcome.BUDGET)
    assert row.retry_after is not None
    assert row.retry_after > timezone.now()
    # No retry round spent: the next real failure still gets all three.
    assert not FetchAttempt.objects.filter(outcome=str(Outcome.RETRY_SCHEDULED)).exists()


def test_a_budget_refusal_at_the_archive_rung_also_carries_a_retry_after(settings) -> None:
    """The second budget exit, past rung 5. Same contract, or a URL that got all
    the way to the archive is the one the queue silently forgets."""
    settings.FETCH_MAX_RETRIES = 0  # retries already spent: the archive is next
    budget = SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 26})

    def scrapedo(url, rung=3, **kwargs):
        return _page(Outcome.BLOCKED, vendor="SCRAPE_DO", rung=rung,
                     credits=25 if rung == 4 else 1, reason="origin_403")

    page = fetch_page("https://e.test/a", budget=budget,
                      providers=_providers(firecrawl=_blocked, scrapedo=scrapedo,
                                           archive=_explode))

    assert page.outcome is Outcome.BUDGET
    row = FetchAttempt.objects.filter(rung=6).get()
    assert row.retry_after is not None


def test_an_overspend_mid_ladder_keeps_the_page_and_never_raises() -> None:
    """`spend` records the overspend and raises -- the credits are gone either
    way, so throwing away the page we paid for would be the second loss. The
    refusal bites on the NEXT rung's check, which is what `check` is for."""
    budget = SweepBudget({"FIRECRAWL": 5, "SCRAPE_DO": 30})

    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.FETCHED, credits=200)

    page = fetch_page("https://e.test/a", budget=budget,
                      providers=_providers(firecrawl=firecrawl))

    assert page.outcome is Outcome.FETCHED
    assert budget.spent["FIRECRAWL"] == 200
    with pytest.raises(FetchBudgetExhausted):
        budget.check("FIRECRAWL")


def test_a_budget_never_escapes_as_an_exception_from_any_rung() -> None:
    """FetchBudgetExhausted subclasses SourceBlocked, so one escaping here
    reaches a caller's `except SourceBlocked` as "this host is blocked"."""
    budget = SweepBudget({"FIRECRAWL": 1, "SCRAPE_DO": 0})

    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.BLOCKED, credits=400, reason="origin_403")

    page = fetch_page("https://e.test/a", budget=budget,
                      providers=_providers(firecrawl=firecrawl, scrapedo=_explode))

    assert page.outcome is Outcome.BUDGET
    assert [attempt.rung for attempt in page.attempts] == [1, 3]


def test_every_attempt_is_recorded_under_one_sweep_id() -> None:
    budget = SweepBudget({"FIRECRAWL": 100, "SCRAPE_DO": 500})

    fetch_page("https://e.test/a", budget=budget,
               providers=_providers(firecrawl=_blocked, scrapedo=_blocked))

    rows = FetchAttempt.objects.filter(url="https://e.test/a").order_by("rung")
    assert [row.rung for row in rows] == [1, 3, 4, 5]
    assert rows.last().retry_after is not None
    assert {row.sweep_id for row in rows} == {budget.sweep_id}


# --- the contract every caller reads -------------------------------------------


def test_a_vendor_outage_is_not_a_blocked_site() -> None:
    """VendorUnavailable means THEIR API failed. Recording it as a block would
    teach the host profile a lie and send every later fetch to rung 4."""
    def firecrawl(url, actions=False, **kwargs):
        raise VendorUnavailable("firecrawl: HTTP 503", escalate=False)

    def scrapedo(url, rung=3, **kwargs):
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung)

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=scrapedo)
    )

    assert page.outcome is Outcome.FETCHED
    assert page.attempts[0].outcome is Outcome.UNREACHABLE
    assert page.attempts[0].reason.startswith("vendor_unavailable")


@pytest.mark.parametrize(
    "outcome",
    [Outcome.FETCHED, Outcome.DEAD, Outcome.BLOCKED, Outcome.UNCHANGED, Outcome.UNREADABLE],
)
def test_every_page_the_ladder_returns_names_its_outcome_and_its_rung(outcome) -> None:
    """Ten of the eleven outcomes are VALUES, so the outcome IS the report. A
    page reaching a caller without one is the silence this engine exists to
    end."""
    def answer(url, **kwargs):
        return _page(outcome, rung=kwargs.get("rung", 1), reason="x")

    page = fetch_page("https://e.test/a",
                      providers=_providers(firecrawl=answer, scrapedo=answer, archive=answer))

    assert page.outcome in set(Outcome)
    assert page.rung >= 1
    assert page.attempts and all(a.outcome in set(Outcome) for a in page.attempts)


# --- host memory (read side; the write side is Task 8) --------------------------


def test_a_learned_start_rung_skips_the_cheap_rungs_it_already_paid_for() -> None:
    HostProfile.objects.create(host="e.test", start_rung=4, last_probe_at=timezone.now())
    rungs = []

    def scrapedo(url, rung=3, **kwargs):
        rungs.append(rung)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung, credits=25)

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=_explode, scrapedo=scrapedo)
    )

    assert rungs == [4]  # remembered, not guessed -- and no escalation bought it
    assert page.rung == 4


def test_a_start_rung_past_the_last_rung_still_walks_one(settings) -> None:
    """`HostProfile.start_rung` is a bare PositiveSmallIntegerField with no
    validator, so only Task 8's discipline keeps it in range. Unclamped, a 5
    yields an EMPTY plan: no vendor is called, `blocked` stays False, and the
    call returns RETRY_SCHEDULED silently -- three times over, before answering
    from a year-old capture."""
    settings.FETCH_REPROBE_DAYS = 30
    HostProfile.objects.create(host="e.test", start_rung=5, last_probe_at=timezone.now())
    rungs = []

    def scrapedo(url, rung=3, **kwargs):
        rungs.append(rung)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung, credits=25)

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=_explode, scrapedo=scrapedo)
    )

    assert rungs == [4]
    assert page.outcome is Outcome.FETCHED


def test_a_long_purpose_is_recorded_truncated_not_raised(settings) -> None:
    """`purpose` is the one value the row builder did not truncate, and
    FetchAttempt.purpose is max_length=10 -- so a caller passing a longer one
    raised a database error straight out of a function whose whole contract is
    that only a programming error leaves it."""
    page = fetch_page(
        "https://e.test/a", purpose="provenance-and-then-some",
        providers=_providers(firecrawl=lambda url, **kwargs: _page(Outcome.FETCHED)),
    )

    assert page.outcome is Outcome.FETCHED
    assert FetchAttempt.objects.get(url="https://e.test/a").purpose == "provenance"


def test_a_host_remembered_expensive_is_re_probed_from_rung_one(settings) -> None:
    """A memory that can only ever entrench a cost is not a memory, it is a
    tariff. The re-probe is what lets a host that got easier stop paying."""
    settings.FETCH_REPROBE_DAYS = 30
    HostProfile.objects.create(
        host="e.test", start_rung=4,
        last_probe_at=datetime(2020, 1, 1, tzinfo=UTC),
    )

    def firecrawl(url, actions=False, **kwargs):
        return _page(Outcome.FETCHED)

    page = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=firecrawl, scrapedo=_explode)
    )

    assert page.rung == 1


# --- manage.py fetch_ladder: the operator's view of a whole sweep ---------------

_COMMAND = "apps.research.management.commands.fetch_ladder.retrieve_official_source"


def _command_page(url: str) -> FetchedPage:
    return FetchedPage(
        final_url=url, redirects=(), content_type="text/html", body=b"<p>ok</p>",
        fetched_via="SCRAPE_DO", cost_credits=25,
    )


def test_the_ladder_prints_the_tier_per_host_and_the_bill_in_dollars(monkeypatch) -> None:
    """The §4.5 gate is a cost question, so the run has to end in money: credits
    from two vendors are not addable, and a host list is only worth sweeping if
    the residue is cheap."""
    def retrieve(url, *, budget=None):
        if "dead" in url:
            raise SourceBlocked("every vendor tier failed: FIRECRAWL VendorUnavailable")
        return _command_page(url)

    monkeypatch.setattr(_COMMAND, retrieve)
    out = StringIO()

    call_command("fetch_ladder", "https://a.example/", "https://dead.example/", stdout=out)

    text = out.getvalue()
    assert "caps=" in text
    assert "a.example  SCRAPE_DO  9 bytes" in text
    assert "dead.example  UNREACHABLE" in text and "FIRECRAWL VendorUnavailable" in text
    assert "USD" in text


def test_it_reads_a_url_file_and_stops_the_sweep_on_the_budget(monkeypatch, tmp_path) -> None:
    """An exhausted budget ends the run; a blocked host only skips a line. The
    except order is the whole behaviour -- FetchBudgetExhausted subclasses
    SourceBlocked, so catching the general one first would turn a spent budget
    into one more unreachable host and keep buying."""
    seen: list[str] = []

    def retrieve(url, *, budget=None):
        seen.append(url)
        raise FetchBudgetExhausted("SCRAPE_DO: 700 credits exceeds the sweep cap 500")

    monkeypatch.setattr(_COMMAND, retrieve)
    urls = tmp_path / "urls.txt"
    urls.write_text("https://a.example/\n\nhttps://b.example/\n")
    out = StringIO()

    call_command("fetch_ladder", urls_file=urls, stdout=out)

    assert seen == ["https://a.example/"]  # the sweep stopped at the first budget refusal
    assert "a.example  BUDGET" in out.getvalue()


def test_the_budget_it_builds_is_per_vendor_from_settings(monkeypatch, settings) -> None:
    """Not one pool: a shared ceiling is seven different ceilings depending on
    which vendor answered (Firecrawl's credit is 7.16x scrape.do's)."""
    settings.FETCH_SWEEP_CREDITS = {"FIRECRAWL": 7, "SCRAPE_DO": 11}
    seen: dict[str, object] = {}

    def retrieve(url, *, budget=None):
        seen["caps"] = budget.caps
        return _command_page(url)

    monkeypatch.setattr(_COMMAND, retrieve)

    call_command("fetch_ladder", "https://a.example/", stdout=StringIO())

    assert seen["caps"] == {"FIRECRAWL": 7, "SCRAPE_DO": 11}


@pytest.mark.parametrize("failure", [ValueError("http is refused"), SourceBlocked("blocked")])
def test_a_refused_url_is_named_not_swallowed(monkeypatch, failure) -> None:
    """A gate that prints nothing for a host it could not read reports a clean
    sweep of a list it never fetched."""
    monkeypatch.setattr(_COMMAND, lambda url, *, budget=None: (_ for _ in ()).throw(failure))
    out = StringIO()

    call_command("fetch_ladder", "https://a.example/", stdout=out)

    assert "a.example  UNREACHABLE" in out.getvalue()
    assert type(failure).__name__ in out.getvalue()


# --- the EGRESS label ---------------------------------------------------------
#
# The plan's Global Constraints: `fetched_via == "EGRESS"` remains reachable
# only for europa.eu, and a test asserts no other host uses it. EGRESS names OUR
# OWN client. After this engine exactly one path in `apps/` still fetches a PAGE
# with it -- `apps/documents/europass.py`, which POSTs a student's name, date of
# birth and history to europa.eu over a pinned transport and never constructs a
# FetchResult at all (grep: that module holds no `fetched_via`). So in code the
# constraint reads: no research fetch produces EGRESS-labelled BYTES, and no new
# module mints the label.
#
# Two halves because neither sees the other's failure. The label reaches
# provenance by assignment (`snapshot.persist_snapshot` copies `fetch.fetched_via`
# onto `OfficialSourceSnapshot.fetched_via` unexamined), so a new first-party rung
# would pass the structural half by inheriting FetchResult's default and pass
# every snapshot assertion by writing a true-looking row.

_APPS = Path(__file__).resolve().parents[2] / "apps"


def _mints_egress_label(source: str) -> bool:
    """True if `source` assigns, annotates, or passes as a call keyword a
    `fetched_via` target whose value literally contains the string "EGRESS"
    -- the dataclass defaults, the model column default (`models.CharField(...,
    default="EGRESS")`, where "EGRESS" sits inside the `CharField(...)` call
    rather than directly on the RHS -- caught by walking the whole value
    subtree, not just its top node), and `_refuse`'s placeholder.

    Replaces a regex (`fetched_via[^\\n]*=\\s*"EGRESS"`) a reviewer showed
    passing on `fetched_via = 'EGRESS'` (single quotes -- this repo's Ruff
    config has no Q rule and never runs `ruff format`, so single-quoted
    Python is rejected nowhere), unable to cross a multi-line assignment, and
    matching `!=` as a false positive. An AST walk is immune to spelling and
    layout because it reasons about the parsed assignment, not its source text.

    Residual limit, not closed by this walk either: an INDIRECT assignment
    through a module constant (`fetched_via = _SOME_LABEL` where
    `_SOME_LABEL = "EGRESS"` is defined elsewhere) is invisible here -- this
    only inspects the expression actually written at the `fetched_via` site,
    never a name's definition elsewhere in the file.
    """
    tree = ast.parse(source)

    def _is_fetched_via(target: ast.expr) -> bool:
        if isinstance(target, ast.Name):
            return target.id == "fetched_via"
        if isinstance(target, ast.Attribute):
            return target.attr == "fetched_via"
        return False

    def _names_egress(value: ast.expr) -> bool:
        return any(
            isinstance(node, ast.Constant) and node.value == "EGRESS"
            for node in ast.walk(value)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(_is_fetched_via(t) for t in node.targets) and _names_egress(node.value):
                return True
        elif isinstance(node, ast.AnnAssign):
            if (
                node.value is not None
                and _is_fetched_via(node.target)
                and _names_egress(node.value)
            ):
                return True
        elif isinstance(node, ast.keyword):
            if node.arg == "fetched_via" and _names_egress(node.value):
                return True
    return False


#: Every code site in `apps/` allowed to say it, and why. Migrations are
#: excluded: they are frozen history and cannot be edited into a new fetch path.
_MAY_LABEL_EGRESS = {
    # FetchResult's own default. Its one live producer is `fetch_data_file` --
    # XML sitemaps and a JSON fixture (CLAUDE.md, "Web fetching"), never a page
    # and never provenance.
    "research/egress.py",
    # FetchedPage's default and the closed FETCHED_VIA vocabulary.
    "research/fetch/types.py",
    # `_refuse`'s placeholder, on a page carrying no bytes.
    "research/fetch/__init__.py",
    # OfficialSourceSnapshot.fetched_via's column default.
    "funding/models.py",
}


def test_only_the_four_known_sites_may_label_a_fetch_egress() -> None:
    labelled = {
        path.relative_to(_APPS).as_posix()
        for path in _APPS.rglob("*.py")
        if "migrations" not in path.parts
        and _mints_egress_label(path.read_text(encoding="utf-8"))
    }

    assert labelled == _MAY_LABEL_EGRESS


def test_no_page_carrying_bytes_ever_leaves_the_ladder_labelled_egress() -> None:
    """Every rung that can return bytes, asked in turn.

    The assertion is about BYTES, not about the label alone: `_refuse` labels
    every refusal EGRESS on purpose (FETCHED_VIA admits no "nobody", and a page
    with no bytes has no provenance to lie about), so a blanket
    `fetched_via != "EGRESS"` would fail on the engine as designed.
    """
    pages = [
        fetch_page(
            "https://e.test/a",
            providers=_providers(firecrawl=lambda url, **kwargs: _page(Outcome.FETCHED)),
        ),
        fetch_page(
            "https://e.test/a",
            providers=_providers(
                firecrawl=_blocked,
                scrapedo=lambda url, **kwargs: _page(
                    Outcome.FETCHED, vendor="SCRAPE_DO", rung=kwargs.get("rung", 3), credits=25
                ),
            ),
        ),
    ]
    # Spent HERE, not before the first walk: the three rounds are an EPISODE
    # budget now, and each FETCHED above ends an episode (`_retries_spent`), so
    # rows seeded ahead of them would be cleared before the archive rung is due.
    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(
            url="https://e.test/a", host="e.test", rung=5, vendor="NONE",
            outcome=Outcome.RETRY_SCHEDULED, attempt_no=attempt_no,
        )
    pages.append(
        fetch_page(
            "https://e.test/a",
            providers=_providers(
                firecrawl=_blocked, scrapedo=_blocked,
                archive=lambda url, **kwargs: _page(
                    Outcome.ARCHIVED, vendor="ARCHIVE", rung=6, credits=2,
                    captured_at="2026-06-25",
                ),
            ),
        )
    )

    assert [page.outcome for page in pages] == [
        Outcome.FETCHED, Outcome.FETCHED, Outcome.ARCHIVED
    ]
    assert all(page.body for page in pages)
    assert [page.fetched_via for page in pages if page.body and page.fetched_via == "EGRESS"] == []
    assert {page.fetched_via for page in pages} == {"FIRECRAWL", "SCRAPE_DO", "ARCHIVE"}


def test_the_three_retry_rounds_are_an_EPISODE_budget_a_served_page_clears(settings) -> None:
    """Rung 5's three rounds were a per-URL LIFETIME budget nothing cleared.

    `retry_due_fetches` only nulls `retry_after` on a served retry; it never
    rewrites `outcome`, and nothing else does either. So once a URL had spent
    three rounds in its whole history, every later transient failure -- years
    and successes later -- skipped rung 5 entirely and bought the 25-credit
    archive rung on the first flake.
    """
    settings.FETCH_MAX_RETRIES = 3
    url = "https://e.test/a"

    for _round in range(settings.FETCH_MAX_RETRIES):
        assert fetch_page(url, providers=_providers()).outcome is Outcome.RETRY_SCHEDULED

    # The episode ends: the host answers.
    served = fetch_page(
        url, providers=_providers(firecrawl=lambda url, **kwargs: _page(Outcome.FETCHED))
    )
    assert served.outcome is Outcome.FETCHED

    # A fresh failure is a fresh episode, so it gets rung 5 again -- not the archive.
    again = fetch_page(url, providers=_providers(archive=_explode))
    assert again.outcome is Outcome.RETRY_SCHEDULED
    assert FetchAttempt.objects.filter(
        url=url, outcome=str(Outcome.RETRY_SCHEDULED)
    ).latest("created_at").attempt_no == 1


def test_a_hostname_too_long_for_its_column_is_recorded_truncated_not_raised() -> None:
    """The same contract break already fixed for `purpose`: `_record` bounded
    every free-text column except `host` (max 253) and `change_status` (max 10),
    and `host` is reachable on the UnsafeTarget path, where nothing bounds the
    hostname's length -- so a long host raised a DataError straight out of a
    function whose contract is that only a programming error leaves it."""
    url = "https://" + "a" * 300 + ".test/a"

    page = fetch_page(url, providers=_providers(firecrawl=_explode))

    assert page.outcome is Outcome.INVALID
    assert len(FetchAttempt.objects.get(url=url[:2048]).host) == 253
