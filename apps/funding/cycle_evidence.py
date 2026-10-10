"""Stored cycle evidence -> `validity.Evidence`. Pure; the decision is validity's.

An `EvidenceEntry` is one award decision read off one page: the quote, where we
fetched it (URL, digest, date; `captured_at` for a Wayback capture), and the
dates it states. Entries are facts about pages, not about intakes, so one list
serves every intake; `to_evidence` picks what speaks to the target.

Two rules here are the evidence side's own, and each closes a way the pure
function would otherwise be fed a wrong fact:

- A deadline belongs to the intake whose window (previous 1 September, this
  1 September] contains it (`intake_of`), never to "whatever intake is asked
  about". An undated line
  "Deadline: 15 January 2026" is last cycle's deadline when 2027 is asked.
- A past cycle is a DATED CALL (`past_calls`) only when a line of that cycle
  carried a date of its own, and that date falls in the cycle's own window: a
  page stamped after its intake began is not when that intake's call opened.
  A cycle seen only by its deadline is observed and counted, never given an
  invented opening (plan decision 3).

And one rule of the judge's: only an AGREED decision is evidence (`_agreed`).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any, TypedDict

from apps.funding.regions import REGIONS
from apps.funding.validity import ASSUMED_INTAKE_START, Evidence, RegisterCadence


class EvidenceEntry(TypedDict):
    step: str
    url: str
    sha256: str
    at: str
    archived: bool
    captured_at: str
    offered: str
    applies_to: str
    intake_year: int | None
    stated_on: str | None
    #: [[iso date, as written, normalised condition], ...]
    deadlines: list[list[str]]
    quote: str
    #: The judge's `agreement` for the decision this entry came from. Only
    #: "AGREED" is evidence (`_agreed`); readings that split are not.
    agreement: str


def _agreed(entry: EvidenceEntry | dict[str, Any]) -> bool:
    """Three readings that did not agree have not established a line.

    An UNAGREED NO must not suspend an award, and an UNAGREED YES must not open
    one. An entry with no `agreement` key is not agreed: fail closed.
    """
    return entry.get("agreement") == "AGREED"


def _date(value: str | None) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def intake_start(year: int) -> dt.date:
    month, day = ASSUMED_INTAKE_START
    return dt.date(year, month, day)


def intake_of(date: dt.date) -> int:
    """The intake whose window (previous start, start] contains `date`."""
    return date.year if date <= intake_start(date.year) else date.year + 1


def observations(
    entries: Iterable[EvidenceEntry] | Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Every cycle the YES entries show, one row per (intake, deadline)."""
    seen: dict[tuple[int, str], dict[str, Any]] = {}
    for entry in entries:
        if entry["offered"] != "YES" or not _agreed(entry):
            continue
        opened = _date(entry["stated_on"])
        for iso, _raw, _condition in entry["deadlines"]:
            deadline = _date(iso)
            if deadline is None:
                continue
            year = intake_of(deadline)
            # An opening counts only when it precedes its own deadline by less
            # than a year: a page's "updated" stamp after the deadline is not
            # when the call opened.
            dated = (
                opened
                if opened and deadline - dt.timedelta(days=365) < opened <= deadline
                else None
            )
            key = (year, iso)
            current = seen.get(key)
            if current is None or (
                dated and (current["open"] is None or dated.isoformat() < current["open"])
            ):
                seen[key] = {
                    "intake_year": year,
                    "open": dated.isoformat() if dated else None,
                    "deadline": iso,
                    "url": entry["url"],
                    "captured_at": entry["captured_at"],
                }
        intake_year = entry["intake_year"]
        # Without a deadline to anchor it, `stated_on` is an opening only when it
        # lies in the named intake's own window; a stamp after the intake began
        # would invent a past call (and with it a projected season).
        if not entry["deadlines"] and opened and intake_year and intake_of(opened) == intake_year:
            seen.setdefault(
                (intake_year, ""),
                {
                    "intake_year": intake_year,
                    "open": opened.isoformat(),
                    "deadline": None,
                    "url": entry["url"],
                    "captured_at": entry["captured_at"],
                },
            )
    return sorted(seen.values(), key=lambda row: (row["intake_year"], row["deadline"] or ""))


def past_calls(
    observed: Sequence[dict[str, Any]], *, before: int
) -> tuple[tuple[dt.date, dt.date | None], ...]:
    """Dated calls of intakes before `before`, earliest opening per intake."""
    by_year: dict[int, tuple[dt.date, dt.date | None]] = {}
    for row in observed:
        opened = _date(row["open"])
        if opened is None or row["intake_year"] >= before:
            continue
        pair = (opened, _date(row["deadline"]))
        if row["intake_year"] not in by_year or pair[0] < by_year[row["intake_year"]][0]:
            by_year[row["intake_year"]] = pair
    return tuple(by_year[year] for year in sorted(by_year, reverse=True))


def _rank(entry: EvidenceEntry, target: int) -> tuple[bool, bool, dt.date]:
    # Ranked on the parsed date: an unparseable `stated_on` is undated, and
    # must not outrank an undated NO.
    stated = _date(entry["stated_on"])
    return (entry["intake_year"] == target, stated is not None, stated or dt.date.min)


def to_evidence(
    entries: Sequence[EvidenceEntry],
    *,
    target_year: int,
    cadence: RegisterCadence | None,
    page_removed: bool,
    lapsed: bool,
) -> Evidence:
    relevant = [
        e for e in entries
        if _agreed(e)
        and (e["intake_year"] == target_year or (e["intake_year"] is None and not e["archived"]))
    ]
    yes = [e for e in relevant if e["offered"] == "YES"]
    no = [e for e in relevant if e["offered"] == "NO"]

    def best_of(group: list[EvidenceEntry]) -> EvidenceEntry:
        return max(group, key=lambda e: _rank(e, target_year))

    offered, best = "YES", None
    # Across pages as within one (spec 9.2): the more specific statement wins
    # for this intake -- naming it, then dated, then the later date. A tie
    # goes to the NO: hiding an open award costs a student one option,
    # showing a closed one costs them an application.
    if no and (
        not yes or _rank(best_of(no), target_year) >= _rank(best_of(yes), target_year)
    ):
        offered, best = "NO", best_of(no)
    elif yes:
        best = best_of(yes)
    deadlines = tuple(
        dict.fromkeys(
            (date, condition)
            for e in yes
            for iso, _raw, condition in e["deadlines"]
            if (date := _date(iso)) is not None and intake_of(date) == target_year
        )
    )
    observed = observations(entries)
    return Evidence(
        offered=offered,
        applies_to=str(target_year) if best and best["intake_year"] == target_year else "UNSTATED",
        stated_on=_date(best["stated_on"]) if best else None,
        deadlines=deadlines,
        past_calls=() if lapsed else past_calls(observed, before=target_year),
        register_cadence=None if lapsed else cadence,
        page_removed=page_removed,
        cycles_observed=tuple(dict.fromkeys(str(row["intake_year"]) for row in observed)),
    )


def deadline_student(nationality: str, country_of_residence: str) -> dict[str, object]:
    """The student keys `validity.select_deadline` reads, from a profile's own answers.

    `applicant_class` is derived from the sourced EU membership in `REGIONS`,
    because a page's "non-EU applicants" deadline is otherwise matched by
    nobody (plan, decision-side findings). Blank when nationality is unknown --
    an unknown class matches no class, which is right.
    """
    code = (nationality or "").upper()
    klass = "" if not code else ("EU" if code in REGIONS["EU"].countries else "NON_EU")
    return {
        "nationality": code,
        "country_of_residence": (country_of_residence or "").upper(),
        "applicant_class": klass,
    }
