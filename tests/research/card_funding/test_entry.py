import datetime as dt
import json
import socket
import threading
from dataclasses import replace
from decimal import Decimal
from functools import partial
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.research.card_engine import Limit, Quote
from apps.research.card_engine.readers import Attempt, ReadersNotConfigured, stack
from apps.research.card_engine.screen import Screen
from apps.research.card_funding import entry
from apps.research.card_funding.awards import nameable
from apps.research.card_funding.card import Hold
from apps.research.card_funding.entry import Guard, read_page
from apps.research.card_funding.questions import AWARD, BATCH
from apps.research.fetch import fetch_page
from apps.research.fetch.types import Attempt as FetchAttemptRecord
from apps.research.fetch.types import FetchedPage, Outcome
from apps.research.models import FetchAttempt

from .oracle import Oracle

URL = "https://beu.edu.az/scholarships"
HTML = b"""<html lang="de"><head><title>Scholarships</title></head><body><main>
<h1>Scholarships at Baku Engineering University</h1>
<p>The university offers the following scholarships for the academic year.</p>
<h2>Rector's Scholarship</h2>
<p>Monthly stipend of AZN 300 for master students.</p>
<p>Applications close on 15 May 2027.</p>
<h2>Merit Award</h2>
<p>Tuition waiver of 50% for master students from Azerbaijan.</p>
</main></body></html>"""
ANSWERS = {
    "award_L1": ("yes", "Rector's Scholarship"),
    "award_L2": ("yes", "Merit Award"),
    "pays_m1": ("paid_to_student", "Monthly stipend of AZN 300"),
    "frequency_m1": ("monthly", "Monthly stipend"),
    "bound_m1": ("exact", "AZN 300"),
    "for_student_m1": ("yes", "stipend"),
    "role_d1": ("application_deadline", "Applications close on 15 May 2027."),
    "target_level": ("master", "master students"),
    "tuition_level": ("partial", "Tuition waiver of 50%"),
    "eligible_p1": ("yes", "students from Azerbaijan"),
    "place_basis": ("not_stated", ""),
}
PROGRAM = SimpleNamespace(id=uuid4(), country_code="AZ")


class Clock:
    """An injected monotonic clock (Ruling P11): a test moves time, nothing sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _keys(settings, monkeypatch):
    settings.OPENROUTER_API_KEY = "test-openrouter-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


def _fetch(outcome=Outcome.FETCHED, body=HTML, final_url=URL, reason=""):
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return FetchedPage(final_url=final_url, redirects=(), content_type="text/html",
                           body=body, fetched_via="FIRECRAWL", outcome=outcome, reason=reason)
    fetch.calls = calls
    return fetch


def _clear(section, *, limit, timeout_s=None):
    return Screen("clear", section.texts())


def _no_screen(section, **kwargs):  # pragma: no cover - the assertion is the point
    raise AssertionError("D8 must not be asked")


def _read(oracle, **kwargs):
    kwargs.setdefault("fetch", _fetch())
    kwargs.setdefault("screen_page", _clear)
    return read_page(PROGRAM, URL, limit=Limit("card-funding-test", uuid4(), 500, 3600),
                     today=dt.date(2026, 10, 13), transport=oracle, **kwargs)


def test_a_page_becomes_a_track_of_typed_award_cards():
    oracle = Oracle(ANSWERS)
    fetch = _fetch()
    card = _read(oracle, fetch=fetch)
    [(url, kwargs)] = fetch.calls
    assert url == URL and 0 < kwargs.pop("timeout_s") <= entry.DEADLINE_S
    assert kwargs == {"purpose": "read", "require_origin": URL}
    assert (card.outcome, card.lang, card.unread_lines) == ("read", "en", 2)  # not <html lang>
    [track] = card.tracks
    rector, merit = track.awards
    assert (rector.name, merit.name) == ("Rector's Scholarship", "Merit Award")
    [stipend] = rector.fields["benefits"].values
    assert (stipend.value.amount.low, stipend.value.frequency) == (Decimal("300"), "monthly")
    assert stipend.source == URL
    [deadline] = rector.fields["dates"].values
    assert (deadline.value.role, deadline.value.date.day) == ("application_deadline", 15)
    assert rector.fields["target_level"].values[0].value == "master"
    assert rector.fields["nationality"].state == "not_stated"
    assert merit.fields["tuition_level"].values[0].value == "partial"
    # "Tuition waiver of 50%" is printed only under Merit: Rector's card never borrows it.
    # (The oracle's absence option here is "none", a stated label since Task 5's ruling I2.)
    assert [v.value for v in rector.fields["tuition_level"].values] == ["none"]
    assert merit.fields["nationality"].values[0].value.eligible == {"AZ"}
    assert merit.fields["benefits"].state == "not_stated"
    assert rector.holds == () and merit.holds == ()
    assert card.cost_usd == pytest.approx(sum(c.cost_usd for c in card.calls))
    assert {c.reader for c in card.calls} == {"deepseek", "luna"}  # nothing split


def test_a_split_goes_to_the_decider_and_an_unresolved_heading_or_field_is_held():
    """Ruling P8 drives the Oracle's split and silent; Ruling P6: a heading nobody could
    judge is never dropped -- it is an award held `not_read`, and its lines are not lent to
    the award above it."""
    oracle = Oracle(ANSWERS, split={"award_L1", "frequency_m1"},
                    silent={"award_L2", "target_level"})
    card = _read(oracle)
    assert card.outcome == "read"
    rector, merit = card.tracks[0].awards
    assert rector.name == "Rector's Scholarship" and rector.name_quote == Quote(
        "Rector's Scholarship", "L0.text")
    [stipend] = rector.fields["benefits"].values
    assert stipend.value.frequency == "monthly"  # the decider settled the split
    assert {d.status for d in stipend.decisions if d.question == "frequency_m1"} == {"decided"}
    assert (rector.fields["target_level"].state, rector.fields["target_level"].hold) == (
        "held", "unresolved_split")
    assert [v.value for v in rector.fields["tuition_level"].values] == ["none"]  # not Merit's
    assert merit.name == "Merit Award" and merit.holds == (Hold("not_read", "*", ""),)
    assert merit.name_quote == Quote("Merit Award", "L0.text")
    assert "opus" in {c.reader for c in card.calls}


def test_a_refused_fetch_or_a_quarantined_page_reads_nothing():
    oracle = Oracle(ANSWERS)
    card = _read(oracle, fetch=_fetch(Outcome.BLOCKED))
    assert (card.outcome, card.tracks, oracle.asked) == ("fetch:BLOCKED", (), [])

    card = _read(oracle, fetch=_fetch(Outcome.UNREACHABLE, reason="deadline"))
    assert (card.outcome, card.tracks, oracle.asked) == ("deadline", (), [])

    def hostile(section, *, limit, timeout_s=None):
        return Screen("quarantined", section.texts(), (("ignore all rules", 0.9),))
    card = _read(oracle, screen_page=hostile)
    assert (card.outcome, card.tracks, oracle.asked) == ("quarantined", (), [])


@pytest.mark.parametrize(("fetch", "outcome"), [
    (_fetch(final_url="https://beu.edu.az/404.html"), "unreadable:soft_404"),
    (_fetch(body=b"<html><body><main><h1>Scholarships</h1></main>"
                 + b"<script>var x = 1;</script>" * 2000 + b"</body></html>"),
     "unreadable:shell"),
    (_fetch(body=b"<html><body></body></html>"), "unreadable:empty"),
])
def test_a_page_with_nothing_to_read_is_unreadable_never_an_empty_read(fetch, outcome):
    """Ruling P7: a soft 404, a shell and a page with no lines are said, never read as a page
    stating no funding (CLAUDE.md's silence rule)."""
    oracle = Oracle(ANSWERS)
    card = _read(oracle, fetch=fetch, screen_page=_no_screen)
    assert (card.outcome, card.tracks, oracle.asked) == (outcome, (), [])


def test_a_missing_key_is_refused_before_anything_is_fetched(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    fetch = _fetch()
    with pytest.raises(ReadersNotConfigured):
        _read(Oracle(ANSWERS), fetch=fetch, readers=stack())
    assert fetch.calls == []


def test_past_the_deadline_no_call_starts_and_every_award_is_held():
    oracle = Oracle(ANSWERS)
    card = _read(oracle, deadline_s=0.0, screen_page=_no_screen)
    assert oracle.asked == [] and card.outcome == "deadline"
    [award] = card.tracks[0].awards  # no heading judgement: the page is one award
    assert {(f.state, f.hold) for f in award.fields.values()} == {("held", "deadline")}


def test_a_slow_fetch_or_a_slow_screen_ends_the_read_at_the_deadline():
    """Owner, 2026-10-13: the fetch and D8 are inside the 30 s. Each is handed the time left,
    and the clock is read when each returns."""
    deadline_s = entry.MIN_CALL_S + 0.5
    seen = []
    fetch = _fetch()

    for slow in ("fetch", "screen"):
        clock = Clock()

        def slow_fetch(url, clock=clock, **kwargs):
            seen.append(("fetch", kwargs["timeout_s"]))
            clock.now += 0.6
            return fetch(url, **kwargs)

        def slow_screen(section, *, limit, timeout_s, clock=clock):
            seen.append(("screen", timeout_s))
            clock.now += 0.6
            return Screen("clear", section.texts())

        oracle = Oracle(ANSWERS)
        chosen = {"fetch": slow_fetch} if slow == "fetch" else {"screen_page": slow_screen}
        card = _read(oracle, deadline_s=deadline_s, clock=clock, **chosen)
        assert card.outcome == "deadline" and oracle.asked == []
        [award] = card.tracks[0].awards
        assert award.holds == (Hold("deadline", "*", ""),)
    assert seen == [("fetch", deadline_s), ("screen", deadline_s)]


def test_the_readers_stop_at_the_deadline_and_what_they_could_not_read_is_held():
    """The guard refuses every call once the time left is under MIN_CALL_S: the heading pair
    took 29 of the 30 seconds, so no award batch is asked and every award is held."""
    clock = Clock()
    inner = Oracle(ANSWERS)

    def slow(spec, prompt):
        clock.now += 14.5  # the pair runs at once: 29 s gone after it
        return inner(spec, prompt)

    card = _read(slow, clock=clock)
    assert card.outcome == "deadline"
    assert [a.name for a in card.tracks[0].awards] == ["Rector's Scholarship", "Merit Award"]
    assert {h.reason for a in card.tracks[0].awards for h in a.holds} == {"deadline"}
    assert sorted(inner.ids()) == ["award_L0", "award_L1", "award_L2"]  # nothing after them


def test_the_funders_country_decides_a_year_of_study_and_none_is_the_programmes():
    html = HTML.replace(b"for master students.", b"for 4th year students.")
    answers = {**ANSWERS, "target_level": ("year_of_study", "4th year students")}
    levels = {}
    for funder_country in (None, "DE", ""):
        card = _read(Oracle(answers), fetch=_fetch(body=html), funder_country=funder_country)
        level = card.tracks[0].awards[0].fields["target_level"]
        levels[funder_country] = (level.state, level.values[0].value if level.values
                                  else level.hold)
    assert levels == {None: ("shown", "bachelor"),  # the programme's AZ: a 4-year bachelor's
                      "DE": ("held", "unparseable_value"),  # a German 4th year may be a master's
                      "": ("held", "unparseable_value")}  # an unknown funder is never guessed


def test_the_dollar_stop_holds_what_it_could_not_pay_for():
    oracle = Oracle(ANSWERS, cost=0.2)
    card = _read(oracle, budget_usd=0.25)
    assert card.cost_usd == pytest.approx(0.4)  # the heading pair, started before the stop
    awards = card.tracks[0].awards
    assert awards and all(any(h.reason == "page_budget" for h in a.holds) for a in awards)
    assert all(h.reason == "page_budget" for a in awards for h in a.holds)


def test_the_guard_counts_unpriced_calls_and_bounds_each_wait(monkeypatch):
    now = [0.0]
    guard = Guard(10.0, 0.25, inner=lambda spec, prompt: Attempt(None, "off_schema", None, 1.0),
                  clock=lambda: now[0])
    spec = stack().pair[0]
    assert guard(spec, None).reason == "off_schema" and guard.unpriced == 1
    now[0] = 8.5  # 1.5 s left: under MIN_CALL_S, so no call starts
    assert guard(spec, None).reason == "failed:deadline" and guard.tripped == "deadline"
    seen = {}

    def post(url, **kwargs):
        seen.update(kwargs)
        raise TimeoutError
    monkeypatch.setattr(entry, "fetch_json_api", post)
    entry._bounded(spec, SimpleNamespace(system="s", data="d", ask="a"), left=4.0)
    assert seen["read_timeout"] == 4.0


def test_an_award_the_rate_limit_refused_is_held_not_read():
    oracle = Oracle(ANSWERS)
    card = read_page(PROGRAM, URL, limit=Limit("card-funding-test", uuid4(), 2, 3600),
                     today=dt.date(2026, 10, 13), transport=oracle, fetch=_fetch(),
                     screen_page=_clear)
    awards = card.tracks[0].awards
    assert [a.name for a in awards] == ["Rector's Scholarship", "Merit Award"]
    assert {(h.reason, h.detail) for a in awards for h in a.holds} == {("not_read",
                                                                        "ReaderLimited")}
    assert len(card.calls) == 2  # the heading pair it could pay for, kept


@pytest.mark.django_db
def test_a_host_that_blocks_every_rung_with_time_left_is_a_blocked_fetch_not_a_deadline(
        monkeypatch):
    """Ruling T7 I1, through the real ladder: 25 s left, every rung refused -> fetch:BLOCKED.
    "deadline" means the time ran out, and no retry is queued for a read nobody will collect."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))])

    def blocked(url, **kwargs):
        rung = kwargs.get("rung", 1)
        vendor = "SCRAPE_DO" if rung >= 3 else "FIRECRAWL"
        return FetchedPage(final_url=url, redirects=(), content_type="", body=b"",
                           fetched_via=vendor, outcome=Outcome.BLOCKED, rung=rung,
                           reason="origin_403", attempts=(FetchAttemptRecord(
                               rung=rung, vendor=vendor, outcome=Outcome.BLOCKED,
                               reason="origin_403"),))

    def archive(url, **kwargs):  # pragma: no cover - the assertion is the point
        raise AssertionError("no archive under a deadline")

    fetch = partial(fetch_page, providers={"firecrawl": blocked, "scrapedo": blocked,
                                           "archive": archive})
    oracle = Oracle(ANSWERS)
    card = _read(oracle, fetch=fetch, deadline_s=25.0, screen_page=_no_screen)
    assert (card.outcome, oracle.asked) == ("fetch:BLOCKED", [])
    rows = FetchAttempt.objects.filter(url=URL)
    assert rows.exists() and not rows.filter(outcome=str(Outcome.RETRY_SCHEDULED)).exists()


def test_a_call_still_running_when_the_read_returns_is_on_the_card_and_logged(monkeypatch,
                                                                             caplog):
    """Ruling T7 I2: a call the read could not wait for is spent money, so the card counts it
    (`running_calls`) and the log names the readers -- and the awards it was reading are held
    `deadline` (the not-finished path)."""
    release = threading.Event()
    both_in = threading.Barrier(3, timeout=5)
    inner = Oracle(ANSWERS)

    def stuck(spec, prompt):
        both_in.wait()
        release.wait(5)
        return inner(spec, prompt)

    def no_wait(futures, timeout):  # the deadline passes the moment both calls are in
        if not getattr(no_wait, "passed", False):
            no_wait.passed = True
            both_in.wait()

    monkeypatch.setattr(entry, "wait", no_wait)
    monkeypatch.setattr(entry, "GRACE_S", 0.0)
    try:
        card = _read(stuck)
    finally:
        release.set()
    assert (card.outcome, card.running_calls, card.calls) == ("deadline", 2, ())
    page_award, *awards = card.tracks[0].awards
    assert awards and {h for a in awards for h in a.holds} == {Hold("deadline", "*", "running")}
    # no heading was judged, so the whole-page award holds the unsure ones (final minor a)
    assert page_award.name_quote is None
    assert page_award.holds == (Hold("deadline", "*", "unsure_heading"),)
    assert "2 reader call(s) still running at return: deepseek=1, luna=1" in caplog.text


def test_an_award_whose_own_proposal_pair_was_refused_is_held():
    """Ruling T7 I3: the cut is read from the award's OWN calls -- a refused batch-0 proposal
    would otherwise leave its requirements silently "not stated"."""
    oracle = Oracle(ANSWERS)

    def refuse_rectors_proposal(spec, prompt):
        proposal = any(q["options"] == ["quote"] for q in json.loads(prompt.ask)["questions"])
        if proposal and "Monthly stipend" in prompt.data:
            return Attempt(None, "failed:page_budget", None, 0.0)
        return oracle(spec, prompt)

    card = _read(refuse_rectors_proposal)
    rector, merit = card.tracks[0].awards
    assert rector.holds == (Hold("page_budget", "*", ""),)
    assert merit.holds == () and merit.fields["tuition_level"].state == "shown"


def test_a_genuine_split_on_a_fully_read_award_is_not_hidden_by_another_awards_stop(
        monkeypatch):
    """Ruling T7 I3 the other way, and minor (a): Merit's reading trips the dollar stop after
    Rector was read in full. Rector keeps its cards and its one unresolved field; Merit is held,
    and once the stop has tripped a queued batch never starts (no rate-limit count spent)."""
    monkeypatch.setattr(entry, "WORKERS", 1)  # first in, first read: Rector, then Merit
    oracle = Oracle(ANSWERS, silent={"target_level"})
    entered: list[str] = []
    real_read = entry.read

    def counting_read(qset, section, **kwargs):
        entered.append(section.lines[0].text)
        return real_read(qset, section, **kwargs)

    both_in = threading.Barrier(2, timeout=5)

    def merit_costs_a_dollar(spec, prompt):
        """Merit's proposal pair costs $1 a call, both started before either is paid."""
        attempt = oracle(spec, prompt)
        proposal = any(q["options"] == ["quote"] for q in json.loads(prompt.ask)["questions"])
        if proposal and "Tuition waiver" in prompt.data:
            both_in.wait()
            return replace(attempt, cost_usd=1.0)
        return attempt

    monkeypatch.setattr(entry, "read", counting_read)
    card = _read(merit_costs_a_dollar)
    rector, merit = card.tracks[0].awards
    assert (rector.fields["target_level"].state, rector.fields["target_level"].hold) == (
        "held", "unresolved_split")
    assert rector.fields["benefits"].state == "shown"
    assert {h.reason for h in rector.holds} == {"unresolved_split"}
    assert merit.holds == (Hold("page_budget", "*", ""),)
    # batch 0 paid, batch 1 refused call by call; every later batch never entered the engine
    assert len(AWARD) > BATCH and entered.count("Merit Award") == 2


def test_an_unsure_sub_heading_holds_the_award_above_it():
    """Ruling T7 I4: "Eligibility" (h3) under "Rector's Scholarship" (h2) could not be judged.
    Read without it, Rector would show nationality "not stated" while its eligibility lines sat
    in a held award of their own -- so Rector is held too."""
    html = HTML.replace(b"<p>Applications close on 15 May 2027.</p>",
                        b"<h3>Eligibility</h3><p>Open to students from Azerbaijan.</p>")
    answers = {**ANSWERS, "award_L3": ("yes", "Merit Award")}
    del answers["award_L2"]
    card = _read(Oracle(answers, silent={"award_L2"}), fetch=_fetch(body=html))
    rector, eligibility, merit = card.tracks[0].awards
    assert rector.holds == (Hold("not_read", "*", "unsure_heading"),)
    assert rector.fields["nationality"].state == "held"
    assert eligibility.name == "Eligibility" and eligibility.holds == (
        Hold("not_read", "*", ""),)
    assert merit.holds == ()


def test_each_real_call_ends_a_margin_before_the_deadline(monkeypatch):
    seen = []

    def bounded(spec, prompt, left):
        seen.append(left)
        return Attempt(None, "off_schema", 0.0, 0.0)

    monkeypatch.setattr(entry, "_bounded", bounded)
    Guard(10.0, 0.25, clock=lambda: 0.0)(stack().pair[0], None)
    assert seen == [10.0 - entry.CALL_MARGIN_S]


def test_the_deciding_readers_wait_is_bounded_too(monkeypatch):
    """Minor (d): the Anthropic branch of `_bounded` -- no SDK retry, the time left."""
    made = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            made.update(kwargs)
            self.messages = "the messages API"

    def reader(spec, prompt, *, messages):
        assert messages() == "the messages API"
        return Attempt(None, "off_schema", None, 0.0)

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)
    monkeypatch.setattr(entry, "anthropic_reader", reader)
    assert entry._bounded(stack().decider, None, left=4.0).reason == "off_schema"
    assert made == {"max_retries": 0, "timeout": 4.0}


@pytest.mark.parametrize(("reason", "outcome"), [("failed", "unscreened:failed"),
                                                  ("deadline", "deadline")])
def test_a_d8_failure_is_said_as_itself_unless_the_time_ran_out(reason, outcome):
    """Minor (g): a screen that failed is `unscreened:<reason>` even when little time is left;
    only a screen that ran out of time ends the read as `deadline`."""
    clock = Clock()

    def failing(section, *, limit, timeout_s):
        clock.now += 29.0
        return Screen("unscreened", frozenset(), (), reason)

    oracle = Oracle(ANSWERS)
    card = _read(oracle, screen_page=failing, clock=clock)
    assert (card.outcome, oracle.asked) == (outcome, [])


def test_calls_that_land_during_the_grace_wait_are_on_the_card(monkeypatch):
    """Final minor (c): the heading pair is still running when the read stops waiting, and
    lands during the grace wait. Its calls are on the card, and the spend and the calls agree
    (read under one lock)."""
    release = threading.Event()
    both_in = threading.Barrier(3, timeout=5)
    inner = Oracle(ANSWERS, cost=0.01)

    def stuck(spec, prompt):
        both_in.wait()
        release.wait(5)
        return inner(spec, prompt)

    def no_wait(futures, timeout):
        if not getattr(no_wait, "passed", False):
            no_wait.passed = True
            both_in.wait()

    class Releasing(Guard):
        def settled(self, timeout, *args, **kwargs):
            release.set()  # the calls land only once the grace wait has begun
            return super().settled(timeout, *args, **kwargs)

    monkeypatch.setattr(entry, "wait", no_wait)
    monkeypatch.setattr(entry, "Guard", Releasing)
    monkeypatch.setattr(entry, "GRACE_S", 5.0)
    try:
        card = _read(stuck)
    finally:
        release.set()
    assert (card.outcome, card.running_calls) == ("deadline", 0)
    assert sorted((c.reader, c.attempt, c.ok) for c in card.calls) == [
        ("deepseek", 1, True), ("luna", 1, True)]
    assert card.cost_usd == pytest.approx(sum(c.cost_usd for c in card.calls)) == 0.02


def test_no_award_heading_and_an_unsure_one_holds_the_page_award():
    """Final minor (a), the I4 rule: no heading named an award and one could not be judged, so
    the whole page is the award -- and it holds the unsure heading, so it is held `not_read`
    rather than missing (Merit's lines no longer vanish into the unread count)."""
    answers = {**ANSWERS, "award_L2": ("no", "")}
    card = _read(Oracle(answers, silent={"award_L1"}))
    assert card.outcome == "read" and card.unread_lines == 0
    page_award, rector = card.tracks[0].awards
    assert (page_award.name, page_award.name_quote) == (
        "Scholarships at Baku Engineering University", None)
    assert page_award.holds == (Hold("not_read", "*", "unsure_heading"),)
    assert rector.name == "Rector's Scholarship" and rector.holds == (Hold("not_read", "*", ""),)


@pytest.mark.parametrize(("value", "printed"), [
    ("master_among_several", b"for bachelor's and master's students."),
    ("higher_education_general", b"for university students."),
])
def test_a_level_among_several_or_in_general_is_shown_with_its_quote(value, printed):
    """Task 8 D: both new target_level options are stated values, shown with their quote."""
    html = HTML.replace(b"for master students.", printed)
    quote = printed.decode().removeprefix("for ").removesuffix(".")
    card = _read(Oracle({**ANSWERS, "target_level": (value, quote)}), fetch=_fetch(body=html))
    level = card.tracks[0].awards[0].fields["target_level"]
    assert level.state == "shown"
    [shown] = level.values
    assert shown.value == value and shown.quote is not None and shown.quote.text == quote


HUNTED = b"""<html><head><title>Calls</title></head><body><main>
<h1>Open calls</h1>
<h2>Rector's Scholarship</h2>
<p>Applications close on 15 May 2027.</p>
<h2>Nizami Scholarship</h2>
<p>Call for applications 2027/28: master students from Azerbaijan.</p>
<p>Applications close on 1 June 2027.</p>
</main></body></html>"""


def test_a_hunted_page_reads_only_the_award_it_names_and_only_the_hunted_fields():
    """2c: strict attach by code, and only the hunted fields asked. (A generic name such as
    "Merit Award" is not nameable, T3, so the award here has a proper name.)"""
    oracle = Oracle({**ANSWERS, "award_L1": ("yes", "Rector's Scholarship"),
                     "award_L2": ("yes", "Nizami Scholarship")})
    card = _read(oracle, fetch=_fetch(body=HUNTED), attach_to="Nizami Scholarship",
                 fields=frozenset({"target_level"}))
    [nizami] = card.tracks[0].awards
    assert nizami.name == "Nizami Scholarship" and nizami.cycle == 2027
    assert nizami.fields["target_level"].values[0].value == "master"
    asked = set(oracle.ids())
    assert {q for q in asked if not q.startswith("award_L")} == {"target_level"}
    for name, field in nizami.fields.items():  # never asked: held not_read, never used
        if name != "target_level":
            assert (field.state, field.hold, field.detail) == ("held", "not_read", "not_hunted")


def test_a_hunted_page_that_names_no_such_award_reads_nothing_else():
    oracle = Oracle({**ANSWERS, "award_L1": ("yes", "Rector's Scholarship"),
                     "award_L2": ("yes", "Nizami Scholarship")})
    assert nameable("Bolashak Fellowship")
    card = _read(oracle, fetch=_fetch(body=HUNTED), attach_to="Bolashak Fellowship",
                 fields=frozenset({"dates"}))
    assert card.outcome == "read" and card.tracks[0].awards == ()
    assert all(q.startswith("award_L") for q in oracle.ids())


def test_a_site_wide_title_never_attaches_an_award():
    """T3 contract: the page title names the award, but the only heading is another award's."""
    body = HUNTED.replace(b"<title>Calls</title>", b"<title>Nizami Scholarship calls</title>") \
                 .replace(b"<h2>Nizami Scholarship</h2>", b"<h2>Rector's Prize</h2>")
    oracle = Oracle({**ANSWERS, "award_L1": ("yes", "Rector's Scholarship"),
                     "award_L2": ("yes", "Rector's Prize")})
    card = _read(oracle, fetch=_fetch(body=body), attach_to="Nizami Scholarship",
                 fields=frozenset({"dates"}))
    assert card.outcome == "read" and card.tracks[0].awards == ()


def test_a_field_name_that_is_not_a_card_field_is_refused():
    with pytest.raises(ValueError, match="targt_level"):
        _read(Oracle(ANSWERS), fields=frozenset({"targt_level"}))


def test_every_question_maps_to_a_card_field():
    from apps.research.card_funding.card import FIELDS
    from apps.research.card_funding.questions import AWARD_FIELD
    assert {AWARD_FIELD.get(q, q) for q, *_ in AWARD} <= set(FIELDS)


def test_hunted_fields_need_an_award_to_attach_to():
    with pytest.raises(ValueError, match="attach_to"):
        _read(Oracle(ANSWERS), fields=frozenset({"dates"}))


def test_the_field_names_code_questions_writes_are_card_fields():
    from apps.research.card_funding.card import FIELDS
    assert {"benefits", "fees", "dates", "nationality", "requirements",
            "funding_duration"} <= set(FIELDS)
