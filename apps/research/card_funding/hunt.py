"""The site hunt: a card's missing facts looked for on the other official pages (§5.5 step 4).

A field is hunted when the page points elsewhere (`needs_hunt`), when the readers' split was never
settled (`unresolved_split`), when code found no candidate for a fact a student is matched on or
acts on, or when every application date it shows has passed. The pages come from the `sitejob`
funnel (`seek.py`), URLs only; each is proven by Part B, fetched, and read by the same engine
with the funding set restricted to the hunted fields. A page's value attaches to an award only
when the page or its section names that award, matched by code. Nothing is stored (slice 3).

The hunt runs as its own worker step, never inside the 30 s on-demand read: that read returns
its card with the fields held, and this step follows it (decision 1 of the 2c plan).
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from apps.funding.models import Program
from apps.research.candidates import Date
from apps.research.card_engine import Limit
from apps.research.card_engine.engine import Transport
from apps.research.card_engine.readers import Stack
from apps.research.card_engine.screen import Screen, screen
from apps.research.fetch import CARRIES_BYTES, fetch_page
from apps.research.fetch.types import FetchedPage

from . import seek
from .awards import nameable
from .card import AwardCard, AwardHunt, Card, Field, Track, _date, _date_conflict, _day, holds_of
from .entry import PAGE_BUDGET_USD, read_page
from .parse import AwardDate, Value
from .seek import CAP, Lead, Vendors, find_leads, page_leads, proven

#: Fields hunted when code found no candidate for them: the facts a student is matched on or
#: acts on. A hunt that finds nothing leaves them not stated (§5 step 7; slice 3's serve rule).
WHEN_EMPTY = ("dates", "nationality", "target_level", "benefits")
#: Holds the rest of the site can answer: a pointer elsewhere, a split no reader settled.
HUNTED_HOLDS = frozenset({"needs_hunt", "unresolved_split"})
#: The dates a student applies by: the dates field is hunted while none of these is still ahead.
APPLY_ROLES = frozenset({"application_deadline", "application_period"})
#: Each hunted page is a worker read, not one a student waits on: its own deadline, generous but
#: bounded, and the same $0.25 model stop as any page (§0.28).
HUNT_PAGE_S = 60.0
#: A hunted page read through to its end: read, or found to hold nothing (a not-found page, no
#: text). A shell may hide its text, and anything else was not read (Ruling P1).
READ_THROUGH = frozenset({"read", "unreadable:soft_404", "unreadable:empty"})
#: Holds that mean a page was cut before it was read through: a hunt that met one did not search
#: everything (Ruling P1). A field a restricted read never asked is `not_read`/`not_hunted`.
CUT = frozenset({"not_read", "deadline", "page_budget"})
#: Holds that are no reading of a value: a pointer elsewhere, or a hunt's own result.
POINTERS = frozenset({"needs_hunt", "hunt_not_found"})
#: List fields: two sections of one page that name the award add their items together.
LISTS = frozenset({"benefits", "fees", "requirements", "funding_duration"})
#: The facts of applying: a page saying students apply to another organisation points to them
#: (spec §5.5 step 4, `apply_elsewhere`), so the hunt looks for whichever the card does not state.
APPLY_FACTS = ("dates", "requirements")


def _last_day(value: Value) -> tuple[int, int, int] | None:
    """The last day a date covers (a period's end); None for a relative date, which has no
    calendar position. A date with no year sorts before every dated one (year 0)."""
    date = value.value.date if isinstance(value.value, AwardDate) else None
    if not isinstance(date, Date):
        return None
    year = date.end_year or date.year or 0
    return (year, (date.end_month or 12) if date.end_year else (date.month or 12),
            (date.end_day or 31) if date.end_year else (date.day or 31))


def _ahead(value: Value, today: dt.date) -> bool:
    """A date a student can still apply by; a relative date has no calendar position, so it
    counts as ahead (it moves with the student). A date with no year counts as passed: nothing
    says which cycle it belongs to, so the hunt looks for a dated one."""
    last = _last_day(value)
    if last is None:
        return True
    return last >= (today.year, today.month, today.day)


def applies_by(award: AwardCard, today: dt.date) -> bool:
    """Whether the award shows an application date still ahead."""
    dates = award.fields["dates"]
    return dates.state == "shown" and any(
        isinstance(v.value, AwardDate) and v.value.role in APPLY_ROLES and _ahead(v, today)
        for v in dates.values)


def wanted(award: AwardCard, today: dt.date) -> frozenset[str]:
    """The fields the hunt looks for on this award (§5.5 step 4's triggers)."""
    out = {name for name, f in award.fields.items()
           if (f.state == "held" and f.hold in HUNTED_HOLDS)
           or (f.state == "not_stated" and name in WHEN_EMPTY)}
    route = award.fields["route"]
    automatic = route.state == "shown" and route.values[0].value == "automatic_on_admission"
    if _yes(award.fields["apply_elsewhere"]) and not _yes(award.fields["apply_here"]):
        out |= {name for name in APPLY_FACTS if award.fields[name].state == "not_stated"}
    if award.fields["dates"].state != "held" and not applies_by(award, today):
        out.add("dates")
    if automatic:  # nothing to apply by: an award given on admission has no deadline of its own
        out.discard("dates")
    return frozenset(out)


def _yes(field: Field) -> bool:
    return field.state == "shown" and field.values[0].value == "yes"


def _cut(card: AwardCard) -> bool:
    return any(f.state == "held" and f.hold in CUT and f.detail != "not_hunted"
               for f in card.fields.values())


def _values(field: Field) -> list[object]:
    return [v.value for v in field.values]


def _pages(name: str, found: Sequence[AwardCard]) -> list[tuple[int | None, Field]]:
    """Each page's reading of one field -- a value, or a hold a reader or code gave -- with the
    page's cycle. Two headings of one page that both name the award give two cards (T4 carry):
    they are one page. List fields add both sections' values; any other field two sections state
    differently is held, because the page contradicts itself. Dates stay one group per section,
    each with its own intake: a 2025 section's results are not this cycle's (T6 I4)."""
    by_page: dict[str, list[tuple[int | None, Field]]] = {}
    for n, card in enumerate(found):
        field = card.fields[name]
        if field.state == "shown" or (field.state == "held" and field.hold not in CUT | POINTERS):
            page = field.values[0].source if field.values else f"#{n}"
            by_page.setdefault(page, []).append((card.cycle, field))
    if name == "dates":  # each section keeps its own intake: one page may carry two (T6 I4)
        return [section for sections in by_page.values() for section in sections]
    out: list[tuple[int | None, Field]] = []
    for sections in by_page.values():
        cycle = max((c for c, _ in sections if c is not None), default=None)
        fields = [f for _, f in sections]
        held = [f for f in fields if f.state == "held"]
        if held or len(fields) == 1:
            out.append((cycle, (held or fields)[0]))
        elif name in LISTS:
            items: list[Value] = []
            for v in (v for f in fields for v in f.values):
                if all(v.value != kept.value for kept in items):
                    items.append(v)
            out.append((cycle, Field(name, "shown", tuple(items))))
        elif any(_values(f) != _values(fields[0]) for f in fields[1:]):
            out.append((cycle, Field(name, "held", tuple(v for f in fields for v in f.values),
                                     "conflicting_values", f"hunt:{name}")))
        else:
            out.append((cycle, fields[0]))
    return out


def _nothing_found(name: str, start: Field, settled: bool, no_list: bool) -> Field:
    """What a hunt that found no value leaves (decision 3, Ruling P1). Only a search that ran to
    the end (`settled`) found nothing; anything less did not search, and a pointer stays
    `needs_hunt`. "International students" with no list is every country but the host only when
    a page that named the award was read cleanly and gave none (`no_list`); any other pointer
    is `hunt_not_found`. A split, a field not stated, anything else stays as it was."""
    if start.hold != "needs_hunt" or not settled:
        return start
    if start.detail == "internationals" and start.values and no_list:
        return Field(name, "shown", start.values)
    return Field(name, "held", hold="hunt_not_found", detail=start.detail)


def _basis(name: str, award: AwardCard, found: Sequence[AwardCard]) -> tuple[Field, int | None]:
    """The reading `_nothing_found` decides from, with its page's cycle: the start page's own,
    or -- when the start page did not state the field -- the first found page's pointer, a list
    elsewhere before "international students" (F-I2). A found page that says where the fact is
    says more than a start page that says nothing; a shown or held start reading is never
    replaced."""
    start = award.fields[name]
    if start.state != "not_stated":
        return start, award.cycle
    pointers = [(card.fields[name], card.cycle) for card in found
                if card.fields[name].hold == "needs_hunt"]
    return min(pointers, key=lambda p: p[0].detail != "eligibility_elsewhere",
               default=(start, award.cycle))


def _cycled(value: Value, cycle: int | None) -> Value:
    """The date with `cycle` as the cycle 2b's rule orders it by; shown as its page printed it."""
    return replace(value, value=replace(_date(value), cycle=cycle))


def _stale(cycle: int | None, values: tuple[Value, ...], newest: int | None,
           today: dt.date) -> bool:
    """A section's dates are last cycle's when it states an older intake than the award states
    anywhere, or when its application dates have all passed (a section with none: every date)."""
    if cycle is not None and newest is not None and cycle < newest:
        return True
    applies = [v for v in values if _date(v).role in APPLY_ROLES]
    return not any(_ahead(v, today) for v in applies or values)


def _dates(start: Field, start_cycle: int | None, sections: list[tuple[int | None, Field]],
           newest: int | None, today: dt.date, settled: bool) -> Field:
    """The dates of every section that named the award and of the start page (§5.5 step 4).

    A section whose dates are last cycle's (`_stale`) is dropped beside a current one, so no date
    role of last cycle is shown unlabelled beside this cycle's (Ruling P3a); an application date
    it carries is held instead when it is later than every application date kept, or none is
    kept (T6 I5). The current sections are one cycle: any two of them that disagree are held,
    whatever their calendar years (T6 I1), and a dated date beats an undated one (owner,
    2026-10-09). Only last cycle's sections left: ordered by 2b's cycle rule -- a section's
    intake, else the date's own year -- and shown labelled `last_cycle`. A section's own
    `conflicting_values` is never released by the merge."""
    held = [f for _, f in sections if f.state == "held" and f.hold != "conflicting_values"]
    if held:  # a section whose dates could not be read may be the newest: nothing is ordered
        return held[0]
    groups = ([(start_cycle, start)] if start.state == "shown" else []) + sections
    if not groups:
        return _nothing_found("dates", start, settled, no_list=False)
    every = tuple(v for _, f in groups for v in f.values)

    def hold(detail: str) -> Field:
        return Field("dates", "held", every, "conflicting_values", f"hunt:{detail}")

    stale = [_stale(cycle, f.values, newest, today) for cycle, f in groups]
    live = [group for group, old in zip(groups, stale, strict=True) if not old]
    if conflicted := [f for _, f in live or groups if f.state == "held"]:
        return hold(conflicted[0].detail)
    if live:  # one cycle: a calendar year orders nothing, it only beats no year at all
        pairs = [(v, _cycled(v, 0 if isinstance(on := _date(v).date, Date) and on.year else None))
                 for _, f in live for v in f.values]
    else:
        pairs = [(v, _cycled(v, next((y for y in (_date(v).cycle, cycle, _year(v))
                                      if y is not None), None)))
                 for cycle, f in groups for v in f.values]
    ordered, conflict = _date_conflict(tuple(d for _, d in pairs))
    if conflict:
        return hold(conflict)
    printed = {id(d): v for v, d in pairs}
    kept: list[Value] = []
    seen: set[tuple[object, ...]] = set()
    for v in (printed[id(d)] for d in ordered):  # one date printed on two pages is one date
        d = _date(v)
        if (key := (d.role, _day(v), d.for_all, d.places, d.held_places)) not in seen:
            seen.add(key)
            kept.append(v)
    if not live:
        return Field("dates", "shown", tuple(kept), label="last_cycle")
    # 2b's cross-place rule by calendar year: a place's deadline in another year than the
    # general one is not the same cycle's (T6 R2); same year, different days is decision 13
    if conflict := _date_conflict(tuple(kept))[1]:
        return hold(conflict)
    applies = [last for v in kept if _date(v).role in APPLY_ROLES and (last := _last_day(v))]
    for (_, f), old in zip(groups, stale, strict=True):
        for v in f.values if old else ():
            if _date(v).role in APPLY_ROLES and (
                    (last := _last_day(v)) is None or all(last > a for a in applies)):
                return hold(_date(v).role)  # never dropped in silence (T6 I5)
    return Field("dates", "shown", tuple(kept))


def _newest(name: str, start: Field, pages: list[tuple[int | None, Field]], settled: bool,
            no_list: bool) -> tuple[Field, int | None]:
    """One page's value and that page's cycle: the page stating the newest cycle; a page stating
    one beats a page stating none; two pages left disagreeing are held, and so is a page left
    beside them whose reading was held. Values compare by their parsed value, never by quote."""
    if not pages:
        return _nothing_found(name, start, settled, no_list), None
    newest = max((cycle for cycle, _ in pages if cycle is not None), default=None)
    top = [field for cycle, field in pages if cycle == newest]
    held = [field for field in top if field.state == "held"]
    if held:
        return held[0], newest
    if any(_values(field) != _values(top[0]) for field in top[1:]):
        return Field(name, "held", tuple(v for f in top for v in f.values), "conflicting_values",
                     f"hunt:{name}"), newest
    return Field(name, "shown", top[0].values), newest


def _year(value: Value) -> int | None:
    d = _date(value)
    if d.cycle is not None:
        return d.cycle
    return (d.date.end_year or d.date.year) if isinstance(d.date, Date) else None


def _open_here(source: str, found: Sequence[AwardCard], today: dt.date) -> bool:
    """Whether the page at `source` prints an application date of its own still ahead."""
    return any(v.source == source and _date(v).role in APPLY_ROLES and _ahead(v, today)
               for card in found for v in card.fields["dates"].values)


def _last_cycle(cycle: int | None, source: str, award: AwardCard, found: Sequence[AwardCard],
                dates: Field, today: dt.date) -> bool:
    """Whether a value from the page at `source`, stating `cycle`, is only last cycle's (owner,
    2026-10-14: amounts and eligibility rules are labelled as dates are): the award states a
    newer cycle somewhere -- its start page, another page that named it, an application date
    still ahead on another page -- or every application date has passed and this page's cycle
    is not newer than the latest of them. A page stating no intake is placed at the year of its
    own application dates when they have all passed; otherwise it cannot be placed and is never
    labelled. A page's own deadline still ahead never makes it last cycle's; a page whose own
    application dates have all passed is last cycle's beside any page with one still ahead,
    whatever the years (T6 R3: a passed early round of the same cycle is over-labelled, never
    shown wrong)."""
    shown = dates.values if dates.state == "shown" else ()
    # every page's dates, held or shown: dates held for a disagreement still say a newer
    # cycle exists (T6 R2)
    read = (*shown, *award.fields["dates"].values,
            *(v for card in found for v in card.fields["dates"].values))
    ahead = [v for v in read if _date(v).role in APPLY_ROLES and v.source != source
             and _ahead(v, today)]
    # the start page's own dates too: its "international students" fallback is placed by them (R3)
    own = [v for v in (*award.fields["dates"].values,
                       *(v for card in found for v in card.fields["dates"].values))
           if v.source == source and _date(v).role in APPLY_ROLES]
    passed_here = bool(own) and not any(_ahead(v, today) for v in own)
    if passed_here and ahead:
        return True
    if cycle is None:  # placed by its own application dates when they have all passed (T6 I3)
        if not passed_here:
            return False
        cycle = max((y for v in own if (y := _year(v)) is not None), default=None)
        if cycle is None:
            return False
    stated = [award.cycle, *(card.cycle for card in found), *(_year(v) for v in ahead)]
    if any(c is not None and cycle < c for c in stated):
        return True
    passed = [y for v in shown if _date(v).role in APPLY_ROLES and (y := _year(v)) is not None]
    return dates.label == "last_cycle" and bool(passed) and cycle <= max(passed)


def merge(award: AwardCard, hunted: frozenset[str], found: Sequence[AwardCard], today: dt.date,
          *, complete: bool) -> AwardCard:
    """The award with what the hunt found: each hunted field from the pages that named the
    award (`found`, one card per section that named it), each value keeping its own page as its
    source, labelled `last_cycle` when it is only last cycle's; every other field as it was.

    `complete` is the caller's word that the search ran to the end: no stage failed, no domain
    was left unproven, every lead was fetched. Without it -- or with any page cut by its
    deadline or budget -- nothing found means not searched, never "not found" (Ruling P1)."""
    settled = complete and not any(map(_cut, found))
    # a page that points to a list elsewhere says a list exists: no fallback (T6 I2)
    readings = [card.fields["nationality"] for card in found]
    no_list = any(f.state == "not_stated" or (f.hold, f.detail) == ("needs_hunt", "internationals")
                  for f in readings) and not any(
        f.hold == "needs_hunt" and f.detail != "internationals" for f in readings)
    newest = max((c for c in (award.cycle, *(card.cycle for card in found)) if c is not None),
                 default=None)
    fields = dict(award.fields)
    if "dates" in hunted:  # first: the other fields' labels read the dates
        fields["dates"] = _dates(_basis("dates", award, found)[0], award.cycle,
                                 _pages("dates", found), newest, today, settled)
    for name in sorted(hunted - {"dates"}):
        pages = _pages(name, found)
        basis, basis_cycle = _basis(name, award, found)
        field, _ = _newest(name, basis, pages, settled, no_list)
        # labelled only when every page giving the value is last cycle's: one current page
        # backing it keeps it current, whatever the pages' order (T6 R2)
        backing = [(cycle, f) for cycle, f in pages
                   if f.state == "shown" and f.values and _values(f) == _values(field)]
        old = [_last_cycle(cycle, f.values[0].source, award, found, fields["dates"], today)
               for cycle, f in backing]
        if field.state == "shown" and not backing:
            # no page gave a value: every country but the host, from the pointer's own page --
            # the start page or a found one -- is labelled as that page is (R1, R3)
            if _last_cycle(basis_cycle, field.values[0].source, award, found, fields["dates"],
                           today):
                field = replace(field, label="last_cycle")
        elif field.state == "shown" and all(old):
            # a current page -- its own application date still ahead -- giving another value,
            # or whose own reading is held, says last cycle's value changed: held, never
            # dropped, and never reordered by date over the owner's stated-cycle rule (F-I3,
            # R2) -- the start page included. A page that cannot be placed is not current: it
            # says nothing about this cycle
            current: list[Field] = []
            every = (award, *found)
            for card in every:
                f = card.fields[name]
                if not ((f.state == "held" and f.hold not in CUT | POINTERS)
                        or (f.state == "shown" and _values(f) != _values(field))):
                    continue
                # a held reading may carry no value: its page is named by its own dates
                source = next((v.source for v in (*f.values, *card.fields["dates"].values)),
                              None)
                if source and _open_here(source, every, today) and not _last_cycle(
                        card.cycle, source, award, found, fields["dates"], today):
                    current.append(f)
            if current:
                values = list(field.values)
                for v in (v for f in current for v in f.values):
                    if v not in values:  # two sections of one page may print one value
                        values.append(v)
                field = Field(name, "held", tuple(values), "conflicting_values",
                              f"hunt:{name}")
            else:
                field = replace(field, label="last_cycle")
        elif field.state == "shown":  # cite a current page, whatever the order (T6 R3)
            field = replace(field, values=next(
                f.values for (_, f), last in zip(backing, old, strict=True) if not last))
        fields[name] = field
    return replace(award, fields=fields, holds=holds_of(fields))


def hunt_owed(card: Card, today: dt.date) -> bool:
    """Whether a card read on demand must be handed to the hunt: its worker step (decision 1).
    An award the hunt has a record for is never owed again here, whatever that attempt found
    (Ruling P3b): when to hunt it again is slice 3's schedule, or a queue keyed on this loops."""
    hunted = {h.award for h in card.hunts}
    return card.outcome == "read" and any(
        award.name not in hunted and wanted(award, today)
        for track in card.tracks for award in track.awards)


def hunt_card(
    card: Card,
    program: Program,
    *,
    limit: Limit,
    funder_country: str | None = None,
    today: dt.date | None = None,
    readers: Stack | None = None,
    transport: Transport | None = None,
    fetch: Callable[..., FetchedPage] = fetch_page,
    screen_page: Callable[..., Screen] = screen,
    vendors: Vendors | None = None,
    prove: Callable[[str], bool | None] = proven,
    page_deadline_s: float = HUNT_PAGE_S,
    budget_usd: float = PAGE_BUDGET_USD,
    clock: Callable[[], float] = time.monotonic,
    cap: int = CAP,
) -> Card:
    """The card with each award's missing facts looked for on the rest of the official site.

    Worker-side only, like `read_page`: every page goes through `fetch_page`, and the funnel's
    stages bill vendors; a student-facing view queues this. Per award: its wanted fields
    (`wanted`), the funnel's proven leads (`seek.find_leads`), at most `cap` of them read by
    `read_page` restricted to that award and those fields -- each with its own deadline and $0.25
    stop, and the caller's `limit` -- the proven links of each page read through to a reading
    (outcome "read": never a quarantined, shell or not-found page's) queued behind them, then
    `merge`. `cap` is the pages this cycle has left (slice 3 counts them across runs; default
    `CAP`). A page is fetched once per hunt whichever awards read it. Reader calls and spend are
    added to the card's own; vendor figures go on the award's `AwardHunt`, with its URLs and,
    when nothing was searched, its reason.

    `merge` is told the search was complete only when every vendor stage ran, no domain a lead
    needed was left unchecked, every page read was read through (`READ_THROUGH`, no reader call
    refused by the dollar stop), and no lead was left unread by the cap (F-I1): anything less
    is "not searched", never "not found" (Ruling P1). A card that was not read, or wants
    nothing, is returned as it was; a start page that cannot be fetched again, or a cap already
    spent, leaves every wanted award a record and its fields untouched."""
    today = today or dt.date.today()
    hunted = [(award, fields) for track in card.tracks for award in track.awards
              if (fields := wanted(award, today))]
    if card.outcome != "read" or not hunted:
        return card
    if cap <= 0:  # this cycle's pages are spent: nothing is fetched or bought
        return replace(card, hunts=card.hunts + tuple(
            AwardHunt(award.name, tuple(sorted(fields)), (), (), (), (), "cap_spent")
            for award, fields in hunted))
    started = clock()
    pages: dict[str, FetchedPage] = {}

    def fetch_once(url: str, **kwargs: Any) -> FetchedPage:
        if url not in pages:
            pages[url] = fetch(url, **kwargs)
        return pages[url]

    start = fetch_once(card.source_url, purpose="read", require_origin=card.source_url)
    if start.outcome not in CARRIES_BYTES:
        return replace(card, seconds=card.seconds + clock() - started, hunts=card.hunts + tuple(
            AwardHunt(award.name, tuple(sorted(fields)), (), (), (), (), "start_failed")
            for award, fields in hunted))
    stages = vendors or seek.vendors()
    calls, cost, unpriced, running = list(card.calls), card.cost_usd, card.unpriced_calls, 0
    tracks, hunts = [], []
    for track in card.tracks:
        awards = []
        for award in track.awards:
            fields = wanted(award, today)
            if not fields:
                awards.append(award)
                continue
            spend: dict[str, float] = {}
            unproven: set[str] = set()
            # an award code cannot name attaches nothing, and a start page Part B did not
            # recognise hunts nowhere: either way nothing was searched, and the record says why.
            # Not cut to `cap` here: a lead the cap leaves unread must stay visible (F-I1)
            queue: list[Lead] = (find_leads(start, award.name, fields, lang=card.lang,
                                            vendors=stages, spend=spend, unproven=unproven,
                                            prove=prove)
                                 if nameable(award.name) else [])
            verdict = prove(start.final_url) if nameable(award.name) else True
            reason = ("unnameable" if not nameable(award.name) else
                      "start_unrecognised" if verdict is False else
                      "start_unproven" if verdict is None else "")
            tried = {start.final_url, card.source_url}  # the start page is never a lead
            read: list[str] = []
            attached: list[str] = []
            found: list[AwardCard] = []
            through = True
            while queue and len(read) < cap:
                lead = queue.pop(0)
                if lead.url in tried:
                    continue
                tried.add(lead.url)
                read.append(lead.url)
                page = read_page(program, lead.url, limit=limit, funder_country=funder_country,
                                 today=today, readers=readers, transport=transport,
                                 fetch=fetch_once, screen_page=screen_page,
                                 deadline_s=page_deadline_s, budget_usd=budget_usd,
                                 clock=clock, attach_to=award.name, fields=fields)
                calls += page.calls
                cost += page.cost_usd
                unpriced += page.unpriced_calls
                running += page.running_calls
                through = through and page.outcome in READ_THROUGH and not any(
                    c.reason == "failed:page_budget" for c in page.calls)
                # a page cut before its headings were judged is one award under its title,
                # which never names an award (strict attach): only a read page attaches
                named = ([a for t in page.tracks for a in t.awards]
                         if page.outcome == "read" else [])
                if named:
                    attached.append(lead.url)
                    found += named
                # hop 2 only from a page read to a reading: a quarantined page, a shell or a
                # not-found page's links never steer what the cap is spent on (F-I4)
                fetched = pages.get(lead.url)  # read_page fetched it pinned to the lead's origin
                if page.outcome == "read" and fetched is not None:
                    queue += page_leads(fetched, fields, prove=prove, unproven=unproven)
            complete = (not reason and through and not unproven
                        and not any(key.endswith("_failed") for key in spend)
                        and all(lead.url in tried for lead in queue))  # F-I1: none left unread
            awards.append(merge(award, fields, found, today, complete=complete))
            hunts.append(AwardHunt(award.name, tuple(sorted(fields)), tuple(read),
                                   tuple(attached), tuple(sorted(spend.items())),
                                   tuple(sorted(unproven)), reason))
        tracks.append(Track(track.name, tuple(awards)))
    return replace(card, tracks=tuple(tracks), calls=tuple(calls), cost_usd=cost,
                   unpriced_calls=unpriced, running_calls=card.running_calls + running,
                   seconds=card.seconds + clock() - started, hunts=card.hunts + tuple(hunts))
