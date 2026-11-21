"""Read one programme page on demand and return its funding card (verified-catalog §3.3, §5).

Fetch through the vendor ladder (pinned to the page's origin), make lines, take the language from
code, screen with D8, ask which headings name awards, then read every award's batches in
parallel and assemble the card. A page a student waits on must finish in under 30 s and spend at
most $0.25 on models (§0.28). The clock starts before the fetch and covers it and D8 too (owner,
2026-10-13): each is handed the time left as `timeout_s`, and the clock is read when each
returns. `Guard` holds the rest, because the engine itself has neither limit (2a's carried
items): every reader call goes through it, it refuses to start a call past the deadline or the
dollar stop, and it bounds each call's HTTP wait by the time left. The dollar stop may overshoot
by the calls already in flight when it trips (owner, 2026-10-14: accepted).

Nothing is hidden in silence: a page that could not be read says so (`unreadable:*`, never a
`read` card with no awards), and a heading nobody could judge, or an award no reading finished,
is an award held with its reason (Rulings P6, P7).

Worker-side only: `fetch_page` writes `FetchAttempt`/`HostProfile`, which `runtime_web` cannot
touch, so a student-facing view QUEUES this (CLAUDE.md, "A student-facing action that needs a
fetch queues it to the worker"). Nothing is stored here; slice 3 stores the card.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from functools import partial
from itertools import count
from typing import Any, cast

from apps.documents.letter_terms import detect_language
from apps.funding.models import Program
from apps.research.candidates import find_all
from apps.research.card_engine import Call, Decision, Limit, Quote, Section
from apps.research.card_engine.engine import Reading, Transport, read
from apps.research.card_engine.readers import (
    READ_TIMEOUT_S,
    Attempt,
    Prompt,
    ReaderSpec,
    Stack,
    _claude_messages,
    anthropic_reader,
    openrouter,
    require_keys,
    stack,
)
from apps.research.card_engine.screen import Screen, ScreenLimited, screen
from apps.research.egress import fetch_json_api
from apps.research.fetch import CARRIES_BYTES, fetch_page
from apps.research.fetch.types import FetchedPage
from apps.research.funding_terms import funding_terms
from apps.research.reader import is_shell, readable_text, redirected_to_a_not_found_page

from .awards import (
    Award,
    AwardNames,
    Page,
    award_section,
    group,
    heading_sections,
    names_award,
    page_lines,
)
from .card import FIELDS, AwardCard, Card, Track, award_card, unread_award
from .parse import Parsed, parse_award, stated_cycle
from .questions import Funding, batches

logger = logging.getLogger(__name__)

DEADLINE_S = 30.0
PAGE_BUDGET_USD = 0.25
#: No call is started with less time left than this: it could not finish anyway.
MIN_CALL_S = 2.0
#: Each reader call's HTTP wait ends this long before the deadline, so the read can collect it.
CALL_MARGIN_S = 1.0
#: After the last wait, how long a call still running is given to land before the card is
#: written (well under CALL_MARGIN_S: a call bounded by the margin should already be done).
GRACE_S = 0.25
WORKERS = 8
#: A Call reason the guard wrote when it refused a call -> the hold reason it means.
_CUT = {"failed:deadline": "deadline", "failed:page_budget": "page_budget"}


def _bounded(spec: ReaderSpec, prompt: Prompt, left: float) -> Attempt:
    """The real transport with every HTTP wait cut to `left` seconds."""
    if spec.transport == "openrouter":
        def post(url: str, **kwargs: Any) -> dict[str, object]:
            return fetch_json_api(url, **{**kwargs, "read_timeout": min(left, READ_TIMEOUT_S)})
        return openrouter(spec, prompt, post=post)

    return anthropic_reader(
        spec, prompt, messages=partial(_claude_messages, timeout=min(left, READ_TIMEOUT_S)))


@dataclass(frozen=True)
class Tally:
    """What the guard saw, read under one lock: the spend and the calls agree."""

    running: dict[str, int]  # reader -> calls still running
    spent: float
    unpriced: int
    calls: tuple[Call, ...]  # the calls of the readings asked for, as the guard recorded them


class Guard:
    """A transport that keeps one page inside its deadline and its dollar stop.

    A refused call is an Attempt that failed (`failed:deadline`, `failed:page_budget`), so the
    engine records it like any failure and the question ends unresolved -- never a guess. An
    unpriced call (cost None) is counted, never treated as free: the stop can only see what the
    vendors priced, which the card reports. Calls running are counted per reader, so a call
    still running when the page returns is reported (`running`), never spent unseen. Every call
    is also recorded per reading (`reading=`), so a reading the page stopped waiting for still
    has its calls on the card when they land during the grace wait (Ruling final minors)."""

    def __init__(self, deadline: float, budget_usd: float, *, inner: Transport | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.deadline, self.budget_usd = deadline, budget_usd
        self.inner, self.clock = inner, clock
        self.spent, self.unpriced, self.tripped = 0.0, 0, ""
        self.in_flight: Counter[str] = Counter()  # reader name -> calls running now
        self.ledger: dict[int, list[Call]] = {}  # reading -> its calls, in the order they ended
        self.tries: Counter[tuple[int, str, Prompt]] = Counter()
        self.lock = threading.Condition()

    def __call__(self, spec: ReaderSpec, prompt: Prompt, *, reading: int = 0) -> Attempt:
        left = self.deadline - self.clock()
        with self.lock:
            refused = ("page_budget" if self.spent >= self.budget_usd
                       else "deadline" if left < MIN_CALL_S else "")
            if refused:
                self.tripped = self.tripped or refused
                attempt = Attempt(None, f"failed:{refused}", None, 0.0)
                self._record(spec, prompt, reading, attempt)
                return attempt
            self.in_flight[spec.name] += 1
        try:
            attempt = (self.inner(spec, prompt) if self.inner
                       else _bounded(spec, prompt, left - CALL_MARGIN_S))
        except BaseException:
            self._finish(spec, prompt, reading, None)
            raise
        self._finish(spec, prompt, reading, attempt)
        return attempt

    def _record(self, spec: ReaderSpec, prompt: Prompt, reading: int,
                attempt: Attempt) -> None:
        """Under the lock: the call as the engine records it (attempt n of this prompt)."""
        self.tries[reading, spec.name, prompt] += 1
        self.ledger.setdefault(reading, []).append(Call(
            spec.name, spec.model, self.tries[reading, spec.name, prompt],
            attempt.reply is not None, attempt.reason, attempt.cost_usd, attempt.latency_s))

    def _finish(self, spec: ReaderSpec, prompt: Prompt, reading: int,
                attempt: Attempt | None) -> None:
        with self.lock:
            self.in_flight[spec.name] -= 1
            if attempt is not None:
                self._record(spec, prompt, reading, attempt)
                if attempt.cost_usd is None:
                    self.unpriced += 1
                else:
                    self.spent += attempt.cost_usd
            self.lock.notify_all()

    def settled(self, timeout: float, readings: Collection[int] = ()) -> Tally:
        """Wait up to `timeout` for every started call to finish; then, under that same lock,
        the calls still running by reader, the spend, and the recorded calls of `readings`."""
        with self.lock:
            self.lock.wait_for(lambda: not any(self.in_flight.values()), timeout)
            return Tally({name: n for name, n in sorted(self.in_flight.items()) if n},
                         self.spent, self.unpriced,
                         tuple(c for n in sorted(readings) for c in self.ledger.get(n, ())))


class _Refused(RuntimeError):
    """The guard had tripped before this reading started: nothing was asked, or counted
    against the rate limit."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _cause(outcome: Reading | BaseException) -> tuple[str, str] | None:
    """Why this reading did not finish, or was cut short by the guard -- from its OWN calls,
    never from what another award's reading did; None when it was read in full."""
    if isinstance(outcome, _Refused):
        return outcome.reason, ""
    if isinstance(outcome, TimeoutError):
        return "deadline", "running"
    calls = outcome.calls if isinstance(outcome, Reading) else getattr(outcome, "calls", ())
    for call in calls:
        if call.reason in _CUT:
            return _CUT[call.reason], ""
    if isinstance(outcome, Reading):
        return None
    return "not_read", type(outcome).__name__


def read_page(
    program: Program,
    url: str,
    *,
    limit: Limit,
    funder_country: str | None = None,
    today: dt.date | None = None,
    readers: Stack | None = None,
    transport: Transport | None = None,
    fetch: Callable[..., FetchedPage] = fetch_page,
    screen_page: Callable[..., Screen] = screen,
    deadline_s: float = DEADLINE_S,
    budget_usd: float = PAGE_BUDGET_USD,
    clock: Callable[[], float] = time.monotonic,
    attach_to: str = "",
    fields: frozenset[str] = frozenset(),
) -> Card:
    """The funding card of one page for one programme.

    `funder_country` decides what a year of study means (decision 5): None is the programme's
    own country (`Program.country_code`), the funder of its own page; "" is unknown and holds
    such a field. `transport` replaces the real readers (tests); it is still wrapped in the
    guard, so the deadline and the stop hold either way. `limit` is the caller's: a student's
    typed programme passes `readers.tenant_limit`, the sweep `readers.run_limit`.

    The site hunt (2c) passes `attach_to`, an award's name, and `fields`: only an award whose
    SECTION HEADING names it by code is read (strict attach; the page title never counts, and
    a page with no award headings attaches nothing), and only the questions those fields are
    parsed from are asked. Every other field of that card is held `not_read` (detail
    `not_hunted`): never asked, never used, and never labelled with a reader
    disagreement or an agreed absence it did not have. A field
    name that is not a card field raises: a typo must not silently ask nothing."""
    if unknown := fields - set(FIELDS):
        raise ValueError(f"unknown card fields: {sorted(unknown)}")
    if fields and not attach_to:
        raise ValueError("hunted fields without attach_to: strict attach cannot be off")
    started = clock()
    readers = readers or stack()
    require_keys(readers)  # the guard wraps the transport, so the engine will not check (2a)
    today = today or dt.date.today()
    country = program.country_code if funder_country is None else funder_country

    def left() -> float:
        return started + deadline_s - clock()

    def done(outcome: str, **extra: Any) -> Card:
        return Card(program.id, url, extra.pop("lang", ""), outcome,
                    seconds=clock() - started, **extra)

    def out_of_time(page: Page) -> Card:
        """No reader was asked: the page is one award under its title, held `deadline`."""
        return done("deadline", lang=page.lang,
                    tracks=(Track("", (unread_award(page.title, None, "deadline"),)),))

    fetched = fetch(url, purpose="read", require_origin=url, timeout_s=max(0.0, left()))
    if fetched.outcome not in CARRIES_BYTES:  # "deadline" only when the time ran out (T7 I1)
        return done("deadline" if fetched.reason == "deadline" else f"fetch:{fetched.outcome}")
    # Ruling P7: the repo's own two checks, never a control fetch (it would cost the time).
    if redirected_to_a_not_found_page(url, fetched):
        return done("unreadable:soft_404")
    if is_shell(readable_text(fetched, terms=None), fetched.body):  # the WHOLE page's prose
        return done("unreadable:shell")
    text = readable_text(fetched, terms=funding_terms())
    lang = detect_language(text)  # from code, never the page's own <html lang> (2a carry)
    page = page_lines(text, lang=lang, html=fetched.body)
    if not page.lines:
        return done("unreadable:empty", lang=lang)
    if left() < MIN_CALL_S:  # the fetch took the time
        return out_of_time(page)
    try:
        cleared = screen_page(page.section(), limit=limit, timeout_s=left())
    except ScreenLimited:
        return done("unscreened:rate_limited", lang=lang)
    if cleared.status == "quarantined":
        return done("quarantined", lang=lang, notes=cleared.notes)
    if cleared.status != "clear" and cleared.reason != "deadline":  # D8's own failure
        return done(f"unscreened:{cleared.reason}", lang=lang, notes=cleared.notes)
    if cleared.status != "clear" or left() < MIN_CALL_S:  # the time ran out in or after D8
        return out_of_time(page)

    guard = Guard(started + deadline_s, budget_usd, inner=transport, clock=clock)
    calls: list[Call] = []
    late = False
    unwaited: set[int] = set()  # readings whose calls the guard's ledger reports instead
    reading_of: dict[Future[Reading], int] = {}
    numbers = count()
    pool = ThreadPoolExecutor(max_workers=WORKERS)

    def run(qset: Any, section: Section) -> Future[Reading]:
        ask = partial(guard, reading=next(numbers))

        def task() -> Reading:
            if guard.tripped:  # a queued reading the guard would refuse call by call
                raise _Refused(guard.tripped)
            return read(qset, section, screen=cleared, limit=limit, readers=readers,
                        transport=ask)
        future = pool.submit(task)
        reading_of[future] = ask.keywords["reading"]
        return future

    def settle(futures: Iterable[Future[Reading]]) -> None:
        wait(list(futures), timeout=max(0.0, guard.deadline - clock()))

    def result(future: Future[Reading]) -> Reading | BaseException:
        nonlocal late
        if not future.done():
            late = True
            unwaited.add(reading_of[future])
            return TimeoutError("deadline")
        try:
            reading = future.result()
        except Exception as error:  # noqa: BLE001 - the award is held, the calls are kept
            calls.extend(getattr(error, "calls", ()))
            return error
        calls.extend(reading.calls)
        return reading

    try:
        heads = [(run(AwardNames(), section), index) for section, index in heading_sections(page)]
        settle(f for f, _ in heads)
        names: set[int] = set()
        unsure: dict[int, tuple[str, str]] = {}  # Ruling P6: never silently dropped
        for future, index in heads:
            outcome = result(future)
            cause = _cause(outcome) or ("not_read", "")
            if not isinstance(outcome, Reading):
                unsure.update(dict.fromkeys(index, cause))
                continue
            for d in outcome.decisions:
                line = index[int(d.question.removeprefix("award_L"))]
                if d.value == "yes":
                    names.add(line)
                elif d.status == "unresolved":
                    unsure[line] = cause
        # T7 I4: a named award whose own extent holds an unsure heading may have lost lines to
        # it (or own them through it): held, never shown with fields "not stated".
        cut: dict[int | None, tuple[str, str]] = {}
        if names:
            for award in group(page, names)[0]:
                inside = [n for n in award.lines[1:] if n in unsure]
                if inside and award.name_line is not None:
                    cut[award.name_line] = (unsure[inside[0]][0], "unsure_heading")
        awards, unread = group(page, names | set(unsure))
        if not names and unsure:  # no heading passed: the page award holds the unsure ones
            [whole], _ = group(page, set())
            cut[None] = (unsure[min(unsure)][0], "unsure_heading")
            awards, unread = (whole, *awards), 0
        if attach_to:  # the hunt: an award this page does not name by heading is never read
            awards = tuple(a for a in awards
                           if a.name_line is not None and names_award(a.name, attach_to))
        jobs: list[tuple[Award, Section | None, list[Future[Reading]]]] = []
        for award in awards:
            if award.name_line in unsure or award.name_line in cut:
                jobs.append((award, None, []))
                continue
            lines = award_section(page, award)
            jobs.append((award, lines, [run(Funding(batch=n, fields=fields), lines)
                                        for n in range(batches(lines, fields) + 1)]))
        settle(f for *_, futures in jobs for f in futures)
        cards: list[AwardCard] = []
        source = fetched.final_url or url
        for award, section, futures in jobs:
            quote = Quote(award.name, "L0.text") if award.name_line is not None else None
            if section is None:
                at = award.name_line
                held = cut.get(at) or unsure[cast(int, at)]
                cards.append(unread_award(award.name, quote, *held))
                continue
            outcomes = [result(f) for f in futures]
            causes = [c for o in outcomes if (c := _cause(o))]
            if causes:  # T7 I3: this award's own reading was cut short or did not finish
                cards.append(unread_award(award.name, quote, *causes[0]))
                continue
            readings = cast(list[Reading], outcomes)
            decisions: list[Decision] = [d for r in readings for d in r.decisions]
            found = find_all(section.lines)
            parsed = parse_award(decisions, found, readings[0].proposed,
                                 source=source, funder_country=country, lang=lang, today=today)
            if fields:  # what was not asked is held as not read, never "not stated"/a split
                parsed = {k: v if k in fields else Parsed(problem="not_read", detail="not_hunted")
                          for k, v in {**dict.fromkeys(FIELDS, Parsed()), **parsed}.items()}
            cards.append(award_card(award.name, quote, parsed, stated_cycle(found)))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    tally = guard.settled(GRACE_S, unwaited)  # spend that lands now is still on this card
    calls.extend(tally.calls)
    running = tally.running
    if running:
        logger.warning("card_funding: %d reader call(s) still running at return: %s",
                       sum(running.values()),
                       ", ".join(f"{name}={n}" for name, n in running.items()))
    if tally.unpriced:
        logger.warning("card_funding: %d reader call(s) reported no price", tally.unpriced)
    out_of_clock = late or guard.tripped == "deadline"
    return done("deadline" if out_of_clock else "read", lang=lang,
                tracks=(Track("", tuple(cards)),), calls=tuple(calls), unread_lines=unread,
                notes=cleared.notes, cost_usd=tally.spent, unpriced_calls=tally.unpriced,
                running_calls=sum(running.values()))
