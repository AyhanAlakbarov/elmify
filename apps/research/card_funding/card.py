"""The typed card: per award, every field shown, held with a reason, or not stated (§5 step 6-7).

A field is `not_stated` only when code found nothing for it, or the readers agreed the page states
nothing -- code-certain or agreed absence, never doubt. Anything short of a value both readers
agreed on (or the decider chose) and code could read is `held`, with the reason the operator's
hold queue sorts by (§5.5 step 6). A held field hides its award from every student until the
operator fixes the wording or a data row and re-runs; slice 3 stores and serves this.

The card is track-shaped (§3.2): a programme carries one or more tracks, each with its awards. A
single page read here is one track (""); the EMJM programme reader fills the others.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from apps.research.candidates import Date
from apps.research.card_engine import Call, Quote

from .parse import AwardDate, Benefit, Nationality, Parsed, Value

#: Why a field or an award is held. The first five arise from reading; the next three from the
#: read itself (a section never read, the on-demand deadline, the page's dollar stop); the last
#: from the site hunt (2c): a pointer it followed and did not resolve.
HOLD_REASONS = ("unresolved_split", "held_country_group", "conflicting_values",
                "unparseable_value", "needs_hunt", "not_read", "deadline", "page_budget",
                "hunt_not_found")
#: Every field a funding card has, in display order.
FIELDS = ("benefits", "fees", "dates", "target_level", "nationality", "requirements",
          "funding_duration", "funding_period", "money_form", "holder_kind", "route",
          "route_order", "tuition_level", "living_level", "extras", "obligations", "apply_here",
          "apply_elsewhere", "institution_wide", "renewal_condition", "discontinued",
          "window_closed")
#: Date roles an award has one of per cycle; two different values on one page are a conflict.
SINGLE_ROLES = frozenset({"application_deadline", "application_opening", "fee_deadline"})

State = Literal["shown", "held", "not_stated"]


@dataclass(frozen=True)
class Field:
    name: str
    state: State
    values: tuple[Value, ...] = ()
    hold: str = ""  # a HOLD_REASONS member when held
    detail: str = ""  # a candidate key, question id or group key; never page text
    #: "last_cycle": shown, but only last cycle's (an amount, benefit, eligibility or date role
    #: from an older cycle's page): a student reads "Last cycle: ..." (owner, 2026-10-14)
    label: Literal["", "last_cycle"] = ""


@dataclass(frozen=True)
class Hold:
    reason: str
    field: str
    detail: str = ""
    #: Empty: held for every student. Otherwise held only for a student from one of these.
    countries: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.reason not in HOLD_REASONS:
            raise ValueError(f"unknown hold reason {self.reason!r}")


@dataclass(frozen=True)
class AwardCard:
    name: str
    name_quote: Quote | None
    fields: Mapping[str, Field]
    holds: tuple[Hold, ...]
    #: the newest intake year code reads in the award's own section (`parse.stated_cycle`):
    #: what the site hunt orders pages by (§5.5 step 4); None states none
    cycle: int | None = None


@dataclass(frozen=True)
class Track:
    name: str  # "" for a programme with one track
    awards: tuple[AwardCard, ...]


@dataclass(frozen=True)
class AwardHunt:
    """What the site hunt did for one award (2c): URLs and figures, never page text. Slice 3
    stores it, and counts `pages` against the cap of 6 extra pages per award per cycle. A record
    with no pages is still an attempt: `hunt_owed` is false once one exists (Ruling P3b)."""

    award: str
    fields: tuple[str, ...]  # the fields looked for
    pages: tuple[str, ...]  # every page read, in order
    attached: tuple[str, ...]  # of those, the pages that named the award
    #: vendor figures per stage (`map_credits`, `guided_usd`, `navigator_credits`), or
    #: "<stage>_failed" counts
    spend: tuple[tuple[str, float], ...]
    unproven: tuple[str, ...]  # domains never checked by Part B: not followed, owed a check
    #: why nothing was searched, "" when the funnel ran: "unnameable" (code cannot name the
    #: award, so nothing could attach), "start_unrecognised" (Part B checked the start page's
    #: domain and did not recognise it), "start_unproven" (never checked; the domain is also in
    #: `unproven`), "start_failed" (the start page could not be fetched again), "cap_spent"
    #: (the caller's `cap` left no page this cycle)
    reason: str = ""


@dataclass(frozen=True)
class Card:
    program_id: UUID | None
    source_url: str
    lang: str
    #: "read", "fetch:<Outcome>", "quarantined", "unscreened:<reason>", "deadline", or
    #: "unreadable:<soft_404|shell|empty>" (a page with nothing to read is never "read")
    outcome: str
    tracks: tuple[Track, ...] = ()
    calls: tuple[Call, ...] = ()
    unread_lines: int = 0  # lines above the first award, which no award holds
    notes: tuple[tuple[str, float], ...] = ()  # D8's review band, carried to whatever shows this
    cost_usd: float = 0.0
    unpriced_calls: int = 0
    #: reader calls still running when the read returned: spent, but not on this card
    running_calls: int = 0
    seconds: float = 0.0
    hunts: tuple[AwardHunt, ...] = ()  # the site hunt's record, one per award per hunt (2c)


def _date(value: Value) -> AwardDate:
    return cast(AwardDate, value.value)


def _day(value: Value) -> tuple[object, ...]:
    """The calendar key of a date: the same day written twice, in any spelling or at any
    position on the line, is one date."""
    d = _date(value).date
    if isinstance(d, Date):
        return (d.year, d.month, d.day, d.end_year, d.end_month, d.end_day)
    return (d.low, d.high, d.unit, d.direction, d.anchor, d.approximately)


def _when(value: Value) -> tuple[int, int, int] | None:
    d = _date(value).date
    if not isinstance(d, Date):
        return None  # a relative date has no calendar position to compare
    return (d.year or 0, d.month or 0, d.day or 0)


def _newest(values: list[Value]) -> int | None:
    return max((c for v in values if (c := _date(v).cycle) is not None), default=None)


def _year(value: Value) -> int | None:
    """The year a date belongs to: its stated cycle, else its own calendar year; a relative date
    has none (Ruling F-I2b)."""
    d = _date(value)
    if d.cycle is not None:
        return d.cycle
    return d.date.year if isinstance(d.date, Date) else None


def _cycle_filter(same: list[Value]) -> list[Value] | None:
    """The values of the newest stated cycle (a stated cycle beats none, §5.5 step 4); None when
    that would drop a later calendar date than every one it keeps -- the cycle label and the
    date disagree about which is newer, so a human decides. A newest cycle stated only in
    relative dates keeps no calendar date, so any absolute date it would drop is held too, never
    dropped in silence (Ruling F-I2d)."""
    newest = _newest(same)
    top = [v for v in same if _date(v).cycle == newest]
    kept = [w for v in top if (w := _when(v))]
    for v in same:
        when = _when(v)
        if v not in top and when and (not kept or all(when > k for k in kept)):
            return None
    return top


def _date_conflict(values: tuple[Value, ...]) -> tuple[tuple[Value, ...], str]:
    """Per single-valued role, per set of places: keep the newest stated cycle; two different
    dates left in one group, two groups naming one country with different dates, or a group --
    place or general -- whose year is older than the newest year of any group, are a conflict
    (Ruling F-I2b: a year is the stated cycle, else the date's own year). Places arrive as
    country codes, groups already expanded (parse). A place group and the general group on
    different days of the same year never conflict (a deadline for named applicants beside one
    for the others, decision 13). A group is its certain places with its held ones beside them;
    only a certain place is a member when one country's groups are compared -- a held one is
    held for that country on the card, never read as its deadline (Task 8 A)."""
    kept = [v for v in values if _date(v).role not in SINGLE_ROLES]
    for role in sorted(SINGLE_ROLES):
        groups: dict[_Limit, list[Value]] = {}
        for v in values:
            d = _date(v)
            if d.role == role:
                groups.setdefault((frozenset(d.places), d.held_places), []).append(v)
        tops: dict[_Limit, list[Value]] = {}
        for scope, same in sorted(groups.items(), key=_order):
            top = _cycle_filter(same)
            if top is None or len({_day(v) for v in top}) > 1:
                return values, _where(role, scope)
            tops[scope] = top
        years = {scope: max((y for v in top if (y := _year(v)) is not None), default=None)
                 for scope, top in tops.items()}
        newest = max((y for y in years.values() if y is not None), default=None)
        for scope, year in sorted(years.items(), key=_order):
            if year is not None and newest is not None and year < newest:
                return values, _where(role, scope)
        for country in sorted(set().union(*(places for places, _ in tops))):
            days = {_day(top[0]) for (places, _), top in tops.items() if country in places}
            if len(days) > 1:
                return values, f"{role}:{country}"
        kept += [top[0] for top in tops.values()]
    return tuple(kept), ""


#: A date's limit: (certain places, held places); both empty is the general group.
_Limit = tuple[frozenset[str], frozenset[str]]


def _order(item: tuple[_Limit, object]) -> tuple[list[str], list[str]]:
    return sorted(item[0][0]), sorted(item[0][1])


def _where(role: str, scope: _Limit) -> str:
    places = scope[0] | scope[1]
    return f"{role}:{','.join(sorted(places))}" if places else role


def _field(name: str, parsed: Parsed) -> Field:
    if parsed.problem:  # values beside a hold are never shown: the hunt's fallback (2c)
        return Field(name, "held", parsed.values, parsed.problem, parsed.detail)
    if not parsed.values:
        return Field(name, "not_stated")
    if name == "dates":
        values, conflict = _date_conflict(parsed.values)
        if conflict:
            return Field(name, "held", parsed.values, "conflicting_values", conflict)
        return Field(name, "shown", values)
    return Field(name, "shown", parsed.values)


def award_card(name: str, name_quote: Quote | None, parsed: Mapping[str, Parsed],
               cycle: int | None = None) -> AwardCard:
    if set(parsed) - set(FIELDS):
        raise ValueError(f"unknown card fields: {sorted(set(parsed) - set(FIELDS))}")
    fields = {key: _field(key, parsed.get(key, Parsed())) for key in FIELDS}
    return AwardCard(name, name_quote, fields, holds_of(fields), cycle)


def holds_of(fields: Mapping[str, Field]) -> tuple[Hold, ...]:
    """Every hold the fields carry: each held field, and the countries a shown value holds."""
    holds = [Hold(f.hold, f.name, f.detail) for f in fields.values() if f.state == "held"]
    nationality = fields["nationality"]
    if nationality.state == "shown":
        value = nationality.values[0].value
        assert isinstance(value, Nationality)
        if value.held:
            groups = ",".join(g for g in value.groups if ":" not in g)
            holds.append(Hold("held_country_group", "nationality", groups, value.held))
        if value.conflicting:  # named eligible and excluded: held for those countries only
            holds.append(Hold("conflicting_values", "nationality", "", value.conflicting))
    for key in ("benefits", "fees", "dates"):  # a group's uncertain members are held
        shown = fields[key].values if fields[key].state == "shown" else ()
        limits = [cast(Benefit | AwardDate, v.value) for v in shown]
        held = frozenset().union(*(x.held_places for x in limits))
        if held:
            groups = ",".join(dict.fromkeys(g for x in limits for g in x.held_groups))
            holds.append(Hold("held_country_group", key, groups, held))
    return tuple(holds)


def unread_award(name: str, name_quote: Quote | None, reason: str, detail: str = "") -> AwardCard:
    """An award whose section was never fully read: every field held for one reason."""
    fields = {key: Field(key, "held", hold=reason, detail=detail) for key in FIELDS}
    return AwardCard(name, name_quote, fields, (Hold(reason, "*", detail),))
