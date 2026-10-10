"""`remember()`: the write side of the host memory (spec §5).

`_rung_plan` (fetch/__init__.py, Task 7) already READS `HostProfile.start_rung`
and `last_probe_at`; this module is what WRITES them. Two kinds of tests here:
those that drive `remember()` directly against a hand-built `FetchedPage`
(the function's own contract, one outcome/rung combination at a time), and a
second group that drives the real `fetch_page()` ladder with only the
providers faked -- proving `remember()` is actually WIRED IN at the terminal
returns, not just correct in isolation. Task 5 shipped a whole rung dead on
arrival with all seven of its own tests passing; the second group is what
would have caught that here.
"""

import socket
from datetime import timedelta
from ipaddress import ip_address

import pytest
from django.utils import timezone

from apps.research.fetch import SweepBudget, _rung_plan, fetch_page, remember
from apps.research.fetch.types import Attempt, FetchedPage, Outcome
from apps.research.models import FetchAttempt, HostProfile

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _resolve_test_hosts(monkeypatch):
    """`*.test` domains do not resolve in this sandbox (RFC 2606); same fixture
    as test_fetch_ladder.py and test_fetch_router.py, duplicated per-file
    rather than shared, matching the existing convention."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ip_address(host)
            address = host
        except ValueError:
            address = "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _page(outcome, *, rung=1, vendor="FIRECRAWL", credits=1):
    return FetchedPage(
        final_url="https://e.test/a", redirects=(), content_type="text/html",
        body=b"x" * 5_000, markdown="# A", outcome=outcome, fetched_via=vendor,
        rung=rung, cost_credits=credits, status_code=200,
        attempts=(Attempt(rung=rung, vendor=vendor, outcome=outcome, credits=credits),),
    )


def _providers(**overrides):
    def missing(url, **kwargs):
        return _page(Outcome.UNREACHABLE, credits=0, rung=kwargs.get("rung", 1))

    provided = {"firecrawl": missing, "scrapedo": missing, "archive": missing}
    provided.update(overrides)

    def firecrawl(url, *, api_key, tag=None, actions=False, profile=None, request_id=None,
                  **extra):
        return provided["firecrawl"](url, rung=2 if actions else 1)

    def scrapedo(url, *, api_key, rung=3, profile=None, session_id=None, **extra):
        return provided["scrapedo"](url, rung=rung)

    def archive(url, *, api_key, now=None):
        return provided["archive"](url)

    return {"firecrawl": firecrawl, "scrapedo": scrapedo, "archive": archive}


def _blocked(url, **kwargs):
    rung = kwargs.get("rung", 1)
    return _page(Outcome.BLOCKED, vendor="SCRAPE_DO" if rung >= 3 else "FIRECRAWL", rung=rung)


# --- remember() directly, per the brief's seven cases --------------------------


def test_an_expensive_success_is_remembered():
    profile = remember("e.test", _page(Outcome.FETCHED, rung=4, vendor="SCRAPE_DO", credits=25))
    assert profile.start_rung == 4
    assert profile.last_success_rung == 4


def test_a_cheap_success_resets_the_memory_so_it_can_only_save_money():
    HostProfile.objects.create(host="e.test", start_rung=4)
    profile = remember("e.test", _page(Outcome.FETCHED, rung=1))
    assert profile.start_rung == 1


def test_a_block_sets_a_cool_off_that_doubles():
    first = remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO", credits=25))
    assert first.consecutive_blocks == 1
    window_one = first.blocked_until - timezone.now()
    second = remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO", credits=25))
    assert second.consecutive_blocks == 2
    assert second.blocked_until - timezone.now() > window_one


def test_the_cool_off_is_capped_at_seven_days():
    # 40, not 12: `_BLOCK_BASE * (2 ** (consecutive_blocks - 1))` overflows
    # `timedelta` at the 33rd consecutive block if the exponent isn't clamped
    # before the multiply (measured: n=33 raises OverflowError). 12 rounds
    # cannot see that -- this loop walks past it.
    for _ in range(40):
        profile = remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO"))
    assert profile.blocked_until - timezone.now() <= timedelta(days=7, seconds=5)


def test_a_success_clears_the_cool_off():
    remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO"))
    profile = remember("e.test", _page(Outcome.FETCHED, rung=1))
    assert profile.blocked_until is None
    assert profile.consecutive_blocks == 0


def test_an_unchanged_answer_clears_the_cool_off_too():
    """UNCHANGED is the host answering in full, so a cool-off it survives is
    stale. It had no reader until Task 10's retry runner; now a stale
    `blocked_until` delays every queued retry for that host by up to a whole
    window (6h-7d), and a lingering `consecutive_blocks` doubles the next
    block's window from a count that already ended."""
    remember("e.test", _page(Outcome.BLOCKED, rung=4, vendor="SCRAPE_DO"))
    profile = remember("e.test", _page(Outcome.UNCHANGED, rung=1))
    assert profile.blocked_until is None
    assert profile.consecutive_blocks == 0
    # The split the docstring draws: "answered" is not "success".
    assert profile.last_success_rung is None


def test_a_probe_from_rung_one_is_dated_even_when_it_fails():
    """`remember()`'s own contract, one page at a time. It is NOT evidence that
    the clock gets stamped in production: `UNREACHABLE` is not terminal, so the
    ladder never ends on a rung-1 page carrying it, and this call is a shape the
    ladder cannot produce. The claim that matters -- "a walk that probed rung 1
    dates the profile, whatever rung it ended on" -- is driven through the real
    `fetch_page` in `test_the_rung_learned_by_one_fetch_is_honoured_by_the_NEXT_one`
    below. Asserting a field and stopping is what let that bug live nine tasks.
    """
    profile = remember("e.test", _page(Outcome.UNREACHABLE, rung=1, credits=0))
    assert profile.last_probe_at is not None


# --- decisions the brief's pseudocode does not spell out ------------------------


def test_a_rung_three_success_is_remembered_without_needing_a_residential_browser():
    """Rung 3 is a different network, not a render -- CLAUDE.md / the router's
    own docstring. It must be remembered as 3, never rounded up to 4: that
    would send every rung-3 host through the 25-credit tier next time, for no
    reason."""
    profile = remember("e.test", _page(Outcome.FETCHED, rung=3, vendor="SCRAPE_DO", credits=1))
    assert profile.start_rung == 3


def test_an_archived_success_never_writes_start_rung_outside_one_to_four():
    """The archive (rung 6) is a capture, not a rung `_rung_plan` ever starts
    at. Writing 6 into start_rung would be both out of the column's contracted
    1-4 range and a lie -- the archive answering says nothing about whether
    rung 3 or 4 would have worked live."""
    HostProfile.objects.create(host="e.test", start_rung=1)
    profile = remember(
        "e.test", _page(Outcome.ARCHIVED, rung=6, vendor="ARCHIVE", credits=2)
    )
    assert profile.start_rung == 1
    assert profile.last_success_rung == 6


def test_an_unchanged_re_probe_lowers_the_memory_instead_of_re_stamping_it(settings):
    """The loop IMPORTANT #1 names: a host learned start_rung=4, the re-probe
    window elapses, and the re-probe itself comes back UNCHANGED -- the common
    case changeTracking exists for (a host that served us in full, just no new
    bytes). Before this fix, `remember` re-stamped `last_probe_at` for ANY
    outcome at rung<=1 but only lowered `start_rung` for `SERVED`, and UNCHANGED
    is not in SERVED -- so the clock reset while the memory stayed at 4, and the
    NEXT fetch planned straight to the 25-credit rung again, forever."""
    settings.FETCH_REPROBE_DAYS = 30
    stale = timezone.now() - timedelta(days=31)
    HostProfile.objects.create(host="e.test", start_rung=4, last_probe_at=stale)

    profile = remember("e.test", _page(Outcome.UNCHANGED, rung=1, credits=1))

    assert profile.start_rung == 1
    # last_probe_at was just re-stamped to now, so the re-probe branch inside
    # _rung_plan won't fire again -- the plan must come from the LOWERED
    # memory, not fall through to the stale start_rung=4 it just overwrote.
    assert _rung_plan(profile) != [4]
    assert _rung_plan(profile) == [1, 3, 4]


def test_the_host_is_lowercased_on_write():
    remember("Example.Test", _page(Outcome.FETCHED, rung=1))
    assert HostProfile.objects.get(host="example.test")
    assert not HostProfile.objects.filter(host="Example.Test").exists()


# --- fetch_page() wired to remember() at its terminal returns -------------------


def test_a_rung_four_success_through_the_real_ladder_writes_the_profile():
    def scrapedo(url, rung=3, **kwargs):
        if rung == 3:
            return _page(Outcome.BLOCKED, vendor="SCRAPE_DO", rung=3)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=rung, credits=25)

    page = fetch_page(
        "https://e.test/a",
        providers=_providers(firecrawl=_blocked, scrapedo=scrapedo),
    )

    assert page.outcome is Outcome.FETCHED
    profile = HostProfile.objects.get(host="e.test")
    assert profile.start_rung == 4
    assert profile.last_success_rung == 4


def test_an_archived_page_through_the_real_ladder_writes_the_profile_but_not_start_rung():
    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(
            url="https://e.test/a", host="e.test", rung=5, vendor="NONE",
            outcome=Outcome.RETRY_SCHEDULED, attempt_no=attempt_no,
        )

    def archive(url, **kwargs):
        return _page(Outcome.ARCHIVED, vendor="ARCHIVE", rung=6, credits=2)

    page = fetch_page(
        "https://e.test/a",
        providers=_providers(firecrawl=_blocked, scrapedo=_blocked, archive=archive),
    )

    assert page.outcome is Outcome.ARCHIVED
    profile = HostProfile.objects.get(host="e.test")
    assert profile.start_rung == 1  # unchanged default; archive never sets it
    assert profile.last_success_rung == 6


def test_a_final_block_through_the_real_ladder_writes_the_cool_off():
    """Every live rung and the archive itself say BLOCKED; the caller gets the
    final refusal, and the host learns a cool-off from it."""
    for attempt_no in (1, 2, 3):
        FetchAttempt.objects.create(
            url="https://e.test/a", host="e.test", rung=5, vendor="NONE",
            outcome=Outcome.RETRY_SCHEDULED, attempt_no=attempt_no,
        )

    def archive(url, **kwargs):
        return _page(Outcome.BLOCKED, vendor="ARCHIVE", rung=6, credits=0)

    page = fetch_page(
        "https://e.test/a",
        providers=_providers(firecrawl=_blocked, scrapedo=_blocked, archive=archive),
    )

    assert page.outcome is Outcome.BLOCKED
    profile = HostProfile.objects.get(host="e.test")
    assert profile.consecutive_blocks == 1
    assert profile.blocked_until is not None


def test_a_budget_refusal_through_the_real_ladder_never_creates_a_profile():
    """decision #1: escalate=False must never be able to create or consult a
    profile -- and a sweep dropped at its credit ceiling is exactly that door.
    The BUDGET/INVALID/OFF_SITE refusals never reach remember()."""
    spent = SweepBudget({"FIRECRAWL": 0, "SCRAPE_DO": 0})

    # `providers=_providers()` even though `budget.check` refuses before any
    # provider is called: relying on that ordering to protect a real-providers
    # default is exactly what MINOR #4 flags -- a real Firecrawl/scrape.do call,
    # with real money, the moment that ordering ever moves.
    page = fetch_page("https://e.test/a", budget=spent, providers=_providers())

    assert page.outcome is Outcome.BUDGET
    assert not HostProfile.objects.filter(host="e.test").exists()


def test_the_budget_retry_window_is_a_setting(settings) -> None:
    settings.FETCH_BUDGET_RETRY_HOURS = 1
    spent = SweepBudget({"FIRECRAWL": 0, "SCRAPE_DO": 0})
    before = timezone.now()

    fetch_page("https://e.test/a", budget=spent, providers=_providers())

    row = FetchAttempt.objects.get(url="https://e.test/a")
    assert row.retry_after - before < timedelta(hours=2)


# --- the memory loop, driven end to end ----------------------------------------


def _explode(*args, **kwargs):  # pragma: no cover - the assertion is the point
    raise AssertionError("this rung must not be reached")


def _learns_rung_four(rungs: list[int]):
    """Providers for a host only rung 4 can read: Firecrawl and rung 3 both
    refuse with a 403, which is the one code both vendors agree escalates."""

    def firecrawl(url, rung=1, **kwargs):
        rungs.append(rung)
        return _page(Outcome.BLOCKED, rung=rung, credits=1)

    def scrapedo(url, rung=3, **kwargs):
        rungs.append(rung)
        if rung == 3:
            return _page(Outcome.BLOCKED, vendor="SCRAPE_DO", rung=3, credits=1)
        return _page(Outcome.FETCHED, vendor="SCRAPE_DO", rung=4, credits=25)

    return _providers(firecrawl=firecrawl, scrapedo=scrapedo)


def test_the_rung_learned_by_one_fetch_is_honoured_by_the_NEXT_one(settings):
    """The whole point of the host memory, and it was unreachable.

    `remember()` stamped `last_probe_at` only when the FINAL page's rung was
    <= 1, and wrote `start_rung=4` only when it was 3 or 4 -- mutually
    exclusive, and `remember()` is called once per `fetch_page`, with the final
    page. So the very call that learned "this host needs rung 4" left
    `last_probe_at` NULL, and `_rung_plan` forces `start = 1` on a NULL clock:
    the memory was written and never read. Every existing learned-rung test
    hand-built the row with the clock already set, so none of them could see it.
    """
    settings.FETCH_REPROBE_DAYS = 30
    rungs: list[int] = []

    first = fetch_page("https://e.test/a", providers=_learns_rung_four(rungs))

    assert first.rung == 4
    assert rungs == [1, 3, 4]
    assert HostProfile.objects.get(host="e.test").start_rung == 4

    rungs.clear()
    second = fetch_page("https://e.test/a", providers=_learns_rung_four(rungs))

    assert rungs == [4], "the second fetch re-walked the rungs the first one paid for"
    assert second.rung == 4


def test_a_learned_rung_four_is_re_probed_after_the_window_and_DROPPED(settings):
    """Learn 4 -> wait out FETCH_REPROBE_DAYS -> re-probe at rung 1 -> back to 1.

    The loop that bounds what the memory can cost. It is what makes the rung-4
    gate's empty-trail exemption survivable: a host learned at 4 plans straight
    to the 25-credit rung on every fetch until this closes, so if it does not
    close the memory is a tariff rather than a memory.
    """
    settings.FETCH_REPROBE_DAYS = 30
    rungs: list[int] = []
    fetch_page("https://e.test/a", providers=_learns_rung_four(rungs))
    learned = HostProfile.objects.get(host="e.test")
    assert learned.start_rung == 4
    # The precondition the whole loop rests on: aging a clock that was never
    # set proves nothing, because a NULL clock already re-probes on every call.
    assert learned.last_probe_at is not None, "the learning fetch left the clock NULL"

    # The window elapses. Nothing else about the profile changes.
    HostProfile.objects.filter(host="e.test").update(
        last_probe_at=timezone.now() - timedelta(days=31)
    )
    rungs.clear()

    def easier(url, rung=1, **kwargs):
        rungs.append(rung)
        return _page(Outcome.FETCHED, rung=1, credits=1)

    reprobe = fetch_page(
        "https://e.test/a", providers=_providers(firecrawl=easier, scrapedo=_explode)
    )

    assert rungs == [1]
    assert reprobe.rung == 1
    profile = HostProfile.objects.get(host="e.test")
    assert profile.start_rung == 1

    # And it STAYS at 1 -- the drop is remembered, not re-derived every call.
    rungs.clear()
    fetch_page("https://e.test/a", providers=_providers(firecrawl=easier, scrapedo=_explode))
    assert rungs == [1]
