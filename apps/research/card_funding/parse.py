"""Decisions plus code's candidates become typed values (verified-catalog §5 steps 4 and 6).

The readers pointed and judged; code reads every value. An amount, a date, a duration, a place or
a requirement is the slice-1 candidate itself -- its parsed numbers, never a reader's retyping --
and a label is the option the readers agreed on (or the decider chose). Each field comes back as
`Parsed`: the values with the quote and the decisions they were built from, or a problem that
names a hold reason and a key (never page text):

- `unresolved_split`: a decision the field needs came back unresolved;
- `unparseable_value`: code cannot read the value the readers chose (an ambiguous figure, a date
  with no year or an unanswered day/month order, a year of study with no table row, a group
  phrase with no fallback row);
- `held_country_group`: the fallback holds everyone for the group named (§5.2.1);
- `conflicting_values`: every country the page names eligible it also excludes (Task 8 B);
- `needs_hunt`: the value is elsewhere -- a pointer to a list, or only "international students"
  (§5.2.1). Slice 2c hunts it. For "international students" the field also carries the value the
  hunt shows if it finds no list: every country but the funder's own (definitions v3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from functools import partial
from typing import Any

from apps.research.candidates import (
    Amount,
    Candidates,
    Date,
    Found,
    Intake,
    RelativeDate,
    Requirement,
)
from apps.research.candidates.who import find_requirements
from apps.research.card_engine import Decision, Quote

from .groups import expand, group_of
from .questions import BENEFICIARIES, COVERS, EXTRAS, OBLIGATIONS, line_of, on_line, repeats_code
from .years import level_of_year

ABSENT = frozenset({"no", "not_stated", "none"})
BENEFIT_PAYS = frozenset({"paid_to_student", "fee_reduction", "in_kind_value"})
FEE_PAYS = frozenset({"fee_charged_to_student", "application_fee"})
#: Money the readers could not place: held when nothing else is found. ("cost_estimate" and
#: "total_budget_or_count" are agreed non-benefits, so they leave benefits not stated.)
UNPLACED_PAYS = frozenset({"not_stated", "other"})
#: Date roles a card shows; the rest are context ("other") or the page's own date.
SHOWN_ROLES = frozenset({"application_deadline", "application_opening", "fee_deadline",
                         "application_period", "results_announced", "selection_or_award",
                         "funding_period", "programme_start"})
#: The single-option fields: labels, then yes/no flags; each is read the same way (`_label`).
SINGLE_ANSWERS = ("money_form", "holder_kind", "route", "route_order", "tuition_level",
                  "living_level", "apply_here", "apply_elsewhere", "institution_wide",
                  "renewal_condition", "discontinued", "window_closed")


@dataclass(frozen=True)
class Value:
    value: object
    quote: Quote | None
    source: str
    decisions: tuple[Decision, ...]  # who said what, for every decision the value rests on


@dataclass(frozen=True)
class Parsed:
    values: tuple[Value, ...] = ()
    problem: str = ""
    detail: str = ""  # a candidate key, a question id or a group key


@dataclass(frozen=True)
class Benefit:
    amount: Amount
    conversion: Amount | None
    pays: str
    bound: str | None
    covers: frozenset[str]
    frequency: str
    duration: str
    for_whom: frozenset[str]
    for_all: bool
    #: The amount's limit. Shown to a student from `places`, held for one from `held_places`
    #: (a group's uncertain members, named by `held_groups`); both empty: no limit.
    places: tuple[str, ...]
    level: str | None
    intake: Intake | None
    held_places: frozenset[str] = frozenset()
    held_groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class AwardDate:
    role: str
    date: Date | RelativeDate
    for_all: bool
    places: tuple[str, ...]  # limited as Benefit.places is, with held_places beside them
    cycle: int | None = None  # the first year of an intake stated on the date's own line
    held_places: frozenset[str] = frozenset()
    held_groups: tuple[str, ...] = ()


@dataclass(frozen=True)
class Nationality:
    eligible: frozenset[str]
    excluded: frozenset[str]
    held: frozenset[str]  # a student from one of these is held, not told yes or no
    basis: str  # citizenship | residence | both | not_stated
    groups: tuple[str, ...]  # group phrases read; "CIS:beside_list" when the page lists countries
    #: named eligible outright and excluded too (through a group, or on another line): the page
    #: contradicts itself for these, so a student from one is held (Ruling F-I1)
    conflicting: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Condition:
    kind: str  # REQUIREMENT_KINDS, or the code candidate's kind ("language_test", "cefr", ...)
    requirement: Requirement | None  # code's parse of the span, when it has one


class _Problem(Exception):
    def __init__(self, problem: str, detail: str) -> None:
        self.problem, self.detail = problem, detail

    def parsed(self) -> Parsed:
        return Parsed(problem=self.problem, detail=self.detail)


def _safe(build: Callable[[], Parsed]) -> Parsed:
    try:
        return build()
    except _Problem as error:
        return error.parsed()


class _Answers:
    def __init__(self, decisions: Iterable[Decision]) -> None:
        self.by = {d.question: d for d in decisions}

    def get(self, qid: str, used: list[Decision]) -> str:
        """The decided value; raises when it is unresolved or was never answered."""
        decision = self.by.get(qid)
        if decision is None or decision.value is None:
            raise _Problem("unresolved_split", qid)
        used.append(decision)
        return decision.value

    def yes(self, qid: str, used: list[Decision]) -> bool:
        return self.get(qid, used) == "yes"

    def opt(self, qid: str, used: list[Decision]) -> str | None:
        """Like get, but a question that was not asked (a conditional one) is None."""
        return self.get(qid, used) if qid in self.by else None


def _quote(found: Found[Any]) -> Quote:
    part = "header" if found.from_header else "text"
    return Quote(found.value.text, f"L{found.line}.{part}")


@dataclass(frozen=True)
class _Scope:
    for_all: bool
    places: tuple[str, ...]
    held_places: frozenset[str]
    held_groups: tuple[str, ...]


def _says_dac(c: Candidates) -> bool:
    """The page itself names the DAC list (or ODA), so "developing countries" means it."""
    return any(group_of(f.value.text) == "DAC" for f in c.places.values()
               if f.value.kind == "unknown_group")


def _scope(a: _Answers, c: Candidates, key: str, line: int, on: dt.date,
           used: list[Decision]) -> _Scope:
    """Who a candidate is limited to. A group a limit names is read through the fallback at the
    page's date, so a limit and a student's country compare code to code (Ruling F-I2a): its
    certain members are `places`, its uncertain ones `held_places` -- held for a student from
    one, never shown to them (Task 8 A). "International students" is no limit at all. A limit
    code cannot read, a group that holds everyone, or "all applicants" together with a place
    limit is held, never guessed."""
    for_all = a.yes(f"for_all_{key}", used)
    codes: set[str] = set()
    held: dict[str, frozenset[str]] = {}  # group -> its uncertain members
    for p in sorted(on_line(c.places, line)):
        if not a.yes(f"for_{p}_{key}", used):
            continue
        place = c.places[p].value
        if place.kind == "country" and place.code:
            codes.add(place.code)
            continue
        group = place.code or group_of(place.text)
        if group == "INTERNATIONAL":
            continue
        expansion = expand(group, on=on, page_says_dac=_says_dac(c)) if group else None
        if group is None or expansion is None:
            raise _Problem("unparseable_value", p)
        if expansion.everyone_held:
            raise _Problem("held_country_group", group)
        codes |= expansion.eligible
        held[group] = held.get(group, frozenset()) | expansion.held
    # named outright, or a certain member of another group named: certain, not held
    held = {group: members - codes for group, members in held.items() if members - codes}
    if for_all and (codes or held):
        raise _Problem("unparseable_value", key)
    return _Scope(for_all, tuple(sorted(codes)), frozenset().union(*held.values()), tuple(held))


def _money(a: _Answers, c: Candidates, on: dt.date, source: str) -> dict[str, Parsed]:
    """Benefits and fees, each held for its own problem only. An amount whose payer is
    unresolved holds both: nobody knows which field it belongs to. The readers' "an estimate"
    or "a budget" is an agreed non-benefit; only "not stated"/"other" with nothing else found
    holds benefits (code found money it cannot place: never "not stated") -- Ruling F-I3."""
    values: dict[str, list[Value]] = {"benefits": [], "fees": []}
    failed: dict[str, Parsed] = {}
    unplaced: list[str] = []
    converted = {base: c.amounts[conv].value for conv, base in c.conversion_of.items()}
    for key, found in c.amounts.items():
        if key in c.conversion_of:
            continue
        used: list[Decision] = []
        pays = a.get(f"pays_{key}", used)
        if pays in UNPLACED_PAYS:
            unplaced.append(key)
            continue
        if pays not in BENEFIT_PAYS | FEE_PAYS:
            continue
        field = "benefits" if pays in BENEFIT_PAYS else "fees"
        if field in failed:
            continue
        try:
            values[field].append(Value(_benefit(a, c, key, found, pays, converted, on, used),
                                       _quote(found), source, tuple(used)))
        except _Problem as error:
            failed[field] = error.parsed()
    if unplaced and not (values["benefits"] or values["fees"]):
        failed.setdefault("benefits", Parsed(problem="unparseable_value", detail=unplaced[0]))
    return {f: failed.get(f) or Parsed(tuple(v)) for f, v in values.items()}


def _benefit(a: _Answers, c: Candidates, key: str, found: Found[Any], pays: str,
             converted: Mapping[str, Amount], on: dt.date, used: list[Decision]) -> Benefit:
    if found.value.low is None:
        raise _Problem("unparseable_value", key)
    level = a.opt(f"level_{key}", used)
    intake = a.opt(f"intake_{key}", used)
    scope = _scope(a, c, key, found.line, on, used)
    return Benefit(
        amount=found.value, conversion=converted.get(key), pays=pays,
        bound=found.value.bound or _present(a.opt(f"bound_{key}", used)),
        covers=frozenset(x for x in COVERS if a.yes(f"covers_{x}_{key}", used)),
        frequency=a.get(f"frequency_{key}", used),
        duration=a.get(f"duration_{key}", used),
        for_whom=frozenset(x for x in BENEFICIARIES if a.yes(f"for_{x}_{key}", used)),
        for_all=scope.for_all, places=scope.places,
        held_places=scope.held_places, held_groups=scope.held_groups,
        level=("all" if level == "all_levels" else
               c.levels[level].value.level if level in c.levels else None),
        intake=c.intakes[intake].value if intake in c.intakes else None,
    )


def _present(value: str | None) -> str | None:
    return None if value in ABSENT else value


def _resolved(date: Date, order: str | None, key: str) -> Date:
    """The date with its day and month in place. An impossible date never arrives: the slice-1
    finder keeps only real calendar dates ("30 February 2027" is read as "February 2027"), and
    an ambiguous order is two numbers of 12 or less, real either way."""
    if date.order_ambiguous:
        if order == "day_first":
            date = replace(date, day=date.first, month=date.second, end_day=date.end_first,
                           end_month=date.end_second, order_ambiguous=False)
        elif order == "month_first":
            date = replace(date, month=date.first, day=date.second, end_month=date.end_first,
                           end_day=date.end_second, order_ambiguous=False)
        else:
            raise _Problem("unparseable_value", key)
    if date.year is None:
        raise _Problem("unparseable_value", key)
    return date


def _dates(a: _Answers, c: Candidates, on: dt.date, source: str) -> Parsed:
    out: list[Value] = []
    every: list[tuple[str, Found[Any]]] = [*c.dates.items(), *c.relative_dates.items()]
    for key, found in every:
        used: list[Decision] = []
        role = a.get(f"role_{key}", used)
        if role not in SHOWN_ROLES:
            continue
        value: Date | RelativeDate = found.value
        if isinstance(value, Date):
            value = _resolved(value, a.opt(f"order_{key}", used), key)
        scope = _scope(a, c, key, found.line, on, used)
        cycle = min((i.value.start_year for i in c.intakes.values() if i.line == found.line),
                    default=None)
        out.append(Value(AwardDate(role, value, scope.for_all, scope.places, cycle,
                                   scope.held_places, scope.held_groups),
                         _quote(found), source, tuple(used)))
    return Parsed(tuple(out))


def stated_cycle(c: Candidates) -> int | None:
    """The newest intake label a section states ("2026/27" -> 2026), read by code. A calendar
    year inside a date is never a cycle. The hunt orders pages by it; None states none."""
    return max((f.value.start_year for f in c.intakes.values()), default=None)


def page_date(decisions: Iterable[Decision], c: Candidates, default: dt.date) -> dt.date:
    """The page's own published/updated date when the readers found one; else `default`."""
    by = {d.question: d.value for d in decisions}
    return max((dt.date(d.year, d.month, d.day or 1) for k, f in c.dates.items()
                if by.get(f"role_{k}") == "page_published_or_updated"
                and (d := f.value).year and d.month and not d.order_ambiguous), default=default)


def _level(a: _Answers, funder_country: str, lang: str, source: str) -> Parsed:
    used: list[Decision] = []
    value = a.get("target_level", used)
    if value in ABSENT:
        return Parsed()
    quote = used[0].quote
    if value == "year_of_study":  # the funder's country decides; unknown is held (decision 5)
        mapped = level_of_year(quote.text, funder_country, lang) if quote else None
        if mapped is None:
            return Parsed(problem="unparseable_value", detail="target_level")
        value = mapped
    return Parsed((Value(value, quote, source, tuple(used)),))


def _nationality(a: _Answers, c: Candidates, on: dt.date, source: str, host: str) -> Parsed:
    used: list[Decision] = []
    eligible_keys = [k for k in c.places if a.yes(f"eligible_{k}", used)]
    excluded_keys = [k for k in c.places if a.yes(f"excluded_{k}", used)]
    both = set(eligible_keys) & set(excluded_keys)  # contradicts itself: not stated (§5 step 6)
    eligible_keys = [k for k in eligible_keys if k not in both]
    excluded_keys = [k for k in excluded_keys if k not in both]
    elsewhere = a.yes("eligibility_elsewhere", used)
    internationals = a.yes("internationals", used)
    basis = a.get("place_basis", used)
    named = any(c.places[k].value.kind == "country" for k in eligible_keys)
    says_dac = _says_dac(c)
    eligible: set[str] = set()
    named_eligible: set[str] = set()  # countries the page names outright
    excluded: set[str] = set()
    held: set[str] = set()
    held_by_exclusion: set[str] = set()  # uncertain, but never evidence anyone may apply
    groups: list[str] = []
    hunt = elsewhere
    # a contradicted group/uncoded place cannot be held by code: no fallback is built (2c)
    no_fallback = any(not (c.places[k].value.kind == "country" and c.places[k].value.code)
                      for k in both)
    for key, into in [*((k, "eligible") for k in eligible_keys),
                      *((k, "excluded") for k in excluded_keys)]:
        place = c.places[key].value
        if place.kind == "country" and place.code:
            (eligible if into == "eligible" else excluded).add(place.code)
            if into == "eligible":
                named_eligible.add(place.code)
            continue
        group = place.code or group_of(place.text)
        if group == "INTERNATIONAL":
            if into == "excluded":  # "not open to international students": held, whatever
                hunt = no_fallback = True  # `internationals` answered -- empty reads as open
            else:
                hunt = True
            continue
        if group is None:
            raise _Problem("unparseable_value", key)
        if into == "eligible" and named and place.kind != "region":
            groups.append(f"{group}:beside_list")  # the funder's own list comes first
            continue
        sole = a.opt(f"sole_{key}", used) == "yes"
        expansion = expand(group, on=on, page_says_dac=says_dac, sole_criterion=sole)
        if expansion is None:
            raise _Problem("unparseable_value", key)
        if expansion.everyone_held:
            raise _Problem("held_country_group", group)
        groups.append(group)
        if into == "eligible":
            eligible |= expansion.eligible
            held |= expansion.held
        else:
            excluded |= expansion.eligible
            held_by_exclusion |= expansion.held
    if internationals and not eligible and not held:
        hunt = True
    if hunt:
        yes = [d for d in used if d.value == "yes" and d.quote is not None]
        quote = next((d.quote for d in yes if d.question == "internationals"
                      or (d.question.startswith("eligible_")
                          and d.question[len("eligible_"):] not in both)),
                     next((d.quote for d in yes), None))
        if elsewhere or not host or eligible or held or named_eligible or no_fallback:
            # a list exists somewhere, no host to fall back from, or the page names countries
            raise _Problem("needs_hunt", "eligibility_elsewhere" if elsewhere else "internationals")
        out = excluded | {host}  # carried for the hunt, shown only when it finds no list (2c)
        # a country the readers marked both eligible and excluded is not stated: held, never
        # turned eligible by "everyone but the excluded"
        unsure = {code for k in both if c.places[k].value.kind == "country"
                  and (code := c.places[k].value.code)}
        fallback = Nationality(frozenset(), frozenset(out),
                               frozenset((held_by_exclusion | unsure) - out),
                               basis, (*groups, "INTERNATIONAL"))
        return Parsed((Value(fallback, quote, source, tuple(used)),), "needs_hunt",
                      "internationals")
    if not (eligible or excluded or held or held_by_exclusion):
        return Parsed()
    quote = next((d.quote for d in used if d.quote is not None and d.value == "yes"), None)
    # a page naming a country eligible outright AND excluding it (through a group it certainly
    # belongs to, or on another line) contradicts itself: held for that country only (F-I1)
    conflicting = named_eligible & excluded
    if conflicting and not named_eligible - conflicting:
        # every country it names eligible is contradicted: nothing would be shown, and the
        # field would read as open to everyone (Task 8 B, residual I-A) -- held whole
        raise _Problem("conflicting_values", "nationality")
    excluded -= conflicting
    # a group never makes an uncertain member of an excluded group eligible; a named country does
    shown = (named_eligible | (eligible - held_by_exclusion)) - excluded - conflicting
    value = Nationality(frozenset(shown), frozenset(excluded),
                        frozenset((held | held_by_exclusion) - shown - excluded - conflicting),
                        basis, tuple(groups), frozenset(conflicting))
    return Parsed((Value(value, quote, source, tuple(used)),))


def _requirements(a: _Answers, c: Candidates, proposed: Mapping[str, tuple[Quote, ...]],
                  source: str) -> Parsed:
    out: list[Value] = []
    for key, found in c.requirements.items():
        used: list[Decision] = []
        if a.yes(f"requires_{key}", used):
            out.append(Value(Condition(found.value.kind, found.value), _quote(found), source,
                             tuple(used)))
    for n, quote in enumerate(proposed.get("requirements", ())):
        used = []
        kind = a.opt(f"kind_{n}", used)
        if kind is None:
            if repeats_code(c, quote):
                continue  # code's own requirement already carries it
            raise _Problem("unparseable_value", "too_many_proposals")  # past the batch cap
        if kind in ABSENT:
            continue
        parsed = next(iter(find_requirements(quote.text)), None)
        out.append(Value(Condition(kind, parsed), quote, source, tuple(used)))
    return Parsed(tuple(out))


def _durations(a: _Answers, c: Candidates, source: str) -> Parsed:
    out = []
    for key, found in c.durations.items():
        used: list[Decision] = []
        if a.yes(f"funds_{key}", used):
            out.append(Value(found.value, _quote(found), source, tuple(used)))
    return Parsed(tuple(out))


def _label(a: _Answers, qid: str, source: str) -> Parsed:
    used: list[Decision] = []
    value = a.get(qid, used)
    if value in ABSENT - {"none"}:  # "none" is a stated value ("covers no tuition")
        return Parsed()
    return Parsed((Value(value, used[0].quote, source, tuple(used)),))


def _set(a: _Answers, prefix: str, items: tuple[str, ...], source: str) -> Parsed:
    used: list[Decision] = []
    found = frozenset(x for x in items if a.yes(f"{prefix}_{x}", used))
    if not found:
        return Parsed()
    quote = next((d.quote for d in used if d.value == "yes"), None)
    return Parsed((Value(found, quote, source, tuple(used)),))


def _funding_period(a: _Answers, c: Candidates, source: str) -> Parsed:
    used: list[Decision] = []
    if not a.yes("funding_period", used):
        return Parsed()
    quote = used[0].quote  # the period is the one intake on the line the readers pointed at
    on = [f for f in c.intakes.values() if quote and f.line == line_of(quote)]
    if len(on) != 1:
        return Parsed(problem="unparseable_value", detail="funding_period")
    return Parsed((Value(on[0].value, _quote(on[0]), source, tuple(used)),))


def parse_award(decisions: Iterable[Decision], c: Candidates,
                proposed: Mapping[str, tuple[Quote, ...]], *, source: str,
                funder_country: str, lang: str, today: dt.date) -> dict[str, Parsed]:
    """Every field of one award. A field's problem stops that field only: the others still
    parse, so the card can say exactly what is held and why. `funder_country` ("" unknown)
    decides what a year of study means (decision 5)."""
    decisions = tuple(decisions)
    a = _Answers(decisions)
    on = page_date(decisions, c, today)
    fields: dict[str, Parsed] = {}
    try:
        fields.update(_money(a, c, on, source))
    except _Problem as error:  # a payer unresolved: neither field is known
        fields["benefits"] = fields["fees"] = error.parsed()
    fields["dates"] = _safe(partial(_dates, a, c, on, source))
    fields["target_level"] = _safe(partial(_level, a, funder_country, lang, source))
    fields["nationality"] = _safe(partial(_nationality, a, c, on, source, funder_country))
    fields["requirements"] = _safe(partial(_requirements, a, c, proposed, source))
    fields["funding_duration"] = _safe(partial(_durations, a, c, source))
    fields["funding_period"] = _safe(partial(_funding_period, a, c, source))
    for name in SINGLE_ANSWERS:
        fields[name] = _safe(partial(_label, a, name, source))
    route = fields["route"].values
    if route and route[0].value == "considered_with_admission":
        fields["route_order"] = Parsed()  # asked always, read only when it applies (§5.2)
    fields["extras"] = _safe(partial(_set, a, "extra", EXTRAS, source))
    fields["obligations"] = _safe(partial(_set, a, "obligation", OBLIGATIONS, source))
    return fields
