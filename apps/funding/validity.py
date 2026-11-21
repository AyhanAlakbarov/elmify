"""Is this award's money there for the intake this student is applying to?

Spec: docs/superpowers/specs/2026-09-18-funder-reader-fetch-tiers-and-resolution-queue-design.md
section 3.5. The owner's requirement, in their words: *the system should be so
robust that it verifies by its own and gives only the scholarships that are
verified for a cycle.* No counsellor sits in this loop, so the decision has to
be made from recorded evidence and plain arithmetic.

Pure and deliberately model-free: every state below is a conditional over dates
a page printed. A model reads the sentences (apps.research.funding_judge); it
never decides whether a scheme is open, and the projection for a scheme whose
window has not opened yet is arithmetic on the cycles actually observed, never
a guess about a funder's next budget.

Nothing here names a scheme, a funder or a country. The cases live in the truth
set (docs/research/2026-09-cycle-truth-set.csv), which is data.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Literal, cast

from pydantic import ValidationError

from apps.funding.eligibility import DEADLINE_PARTITION_KEYS, ConditionTriple, Key, Outcome, decide

Validity = Literal[
    "OPEN", "UPCOMING", "CLOSED_FOR_INTAKE", "SUSPENDED", "ENDED", "UNVERIFIED"
]

#: A master's intake is taken to start on 1 September of its first year --
#: the resolution a page's "2026-2028" offers, and only ever used to compare
#: months. It is a DEFAULT, not a fact: a February intake in the southern
#: hemisphere is the case it gets wrong, which is why every entry point takes
#: `intake_starts_on` and a caller holding the programme's own start date
#: should pass it.
_ASSUMED_INTAKE_START = (9, 1)

#: Country-specific primary and secondary academic intake start dates `(month, day)` for
#: Southern Hemisphere (`AU`, `NZ`) and East/Southeast Asian biannual academic calendars
#: (`KR`, `JP`, `SG`, `MY`, `BN`).
_COUNTRY_INTAKE_STARTS: dict[str, tuple[tuple[int, int], ...]] = {
    "AU": ((2, 15), (7, 15)),
    "NZ": ((2, 15), (7, 15)),
    "KR": ((3, 1), (9, 1)),
    "JP": ((4, 1), (10, 1)),
    "SG": ((8, 1), (1, 15)),
    "MY": ((9, 1), (2, 15)),
    "BN": ((8, 1), (1, 15)),
}


def default_intake_start_for_country(
    country_code: str, year: int, *, today: dt.date | None = None
) -> dt.date:
    """Resolve the default academic intake start date in `year` for `country_code`.

    For Northern Hemisphere annual calendars, returns `year-09-01`. For Southern
    Hemisphere (`AU`, `NZ`) and biannual Asian calendars (`KR`, `JP`, `SG`, `MY`, `BN`),
    returns the next upcoming intake start in `year` on or after `today` (or the
    country's primary intake in `year` when `today` is not in `year`).
    """
    starts = _COUNTRY_INTAKE_STARTS.get((country_code or "").strip().upper())
    if not starts:
        month, day = _ASSUMED_INTAKE_START
        return dt.date(year, month, day)
    candidates = sorted(dt.date(year, m, d) for m, d in starts)
    if today is not None and today.year == year:
        for cand in candidates:
            if cand >= today:
                return cand
    month, day = starts[0]
    return dt.date(year, month, day)

_YEAR = re.compile(r"(?:19|20)\d{2}")
#: Month names are matched in English only here. A page's own month name
#: reaches this module already normalised by the reader; this is the fallback
#: for a curated register row.
_MONTHS = {name.casefold(): number for number, name in enumerate(calendar.month_name) if name}

#: A deadline condition names either an eligibility key (decided by the shared
#: vocabulary, so a country list or a region works exactly as it does on an
#: award) or one of the four partition keys, which are not eligibility and
#: decide by equality against the student's own answer.
_ELIGIBILITY_ALIASES = {"NATIONALITY": "CITIZENSHIP"}

#: DESCENT decides by equality here, not through the shared decider:
#: decide()'s DESCENT branch abstains unconditionally, because the eligibility
#: profile deliberately never collects descent (spec) -- right for "are they
#: eligible", wrong for "did they tell us, and does it match", which is the
#: only question a deadline partition asks. Kept out of DEADLINE_PARTITION_KEYS
#: (Task 2 pins that tuple to exactly four keys) but decided the same way as
#: those four.
_EQUALITY_KINDS = (*DEADLINE_PARTITION_KEYS, "DESCENT")


@dataclass(frozen=True)
class Deadline:
    """One application deadline and whose it is."""

    date: dt.date
    condition: str = "ALL"
    #: A condition this student satisfies for which the page stated no date.
    #: The card says so rather than showing them somebody else's deadline.
    missing_for: str = ""


@dataclass(frozen=True)
class RegisterCadence:
    """A curated, sourced, expiring cadence from the funder register.

    This is how "everyone knows it runs every year" enters the system: as a
    fact with a URL and the cycle it was checked in. Verified within the last
    cycle it counts as recurrence evidence; older it only raises re-check
    priority and verifies nothing.
    """

    open_month: int
    deadline_month: int
    source: str
    verified_for_cycle: int


@dataclass(frozen=True)
class Evidence:
    """Everything recorded about one award for one intake, dates already parsed."""

    offered: str = "YES"
    #: The intake the award's own lines named, as the page wrote it.
    applies_to: str = "UNSTATED"
    stated_on: dt.date | None = None
    deadline: dt.date | None = None
    #: (date, condition) for every deadline the lines stated.
    deadlines: tuple[tuple[dt.date, str], ...] = ()
    #: Conditions the page named without giving a date for them.
    conditions_without_dates: tuple[str, ...] = ()
    #: A later, dated statement that contradicts the award for an intake.
    contrary_on: dt.date | None = None
    contrary_intake: str = ""
    #: (opening, deadline) per observed past cycle, from the site's own
    #: archive or Wayback captures of the call page.
    past_calls: tuple[tuple[dt.date, dt.date | None], ...] = ()
    #: A month the page itself names as when the scheme runs, every year.
    recurrence_stated: str | None = None
    register_cadence: RegisterCadence | None = None
    #: A register record asserting funding, and the end of its grant period.
    from_register: bool = False
    grant_window_end: dt.date | None = None
    page_removed: bool = False
    cycles_observed: tuple[str, ...] = field(default_factory=tuple)


def intake_start_year(text: str) -> int | None:
    """The first four-digit year in an intake as a page writes it.

    "2026-2028", "2026/27", "2026-27" and "Fall 2026" are all intake 2026;
    UNSTATED and anything with no year are None, never a guess.
    """
    found = _YEAR.search(text or "")
    return int(found.group()) if found else None


_MULTI_INTAKE_SPLIT_RE = re.compile(r"\s*(?:,|;|&|\band\b|\bor\b)\s*", re.IGNORECASE)
_OPEN_ENDED_FROM_RE = re.compile(
    r"\b(?:from|since)\s+(?:the\s+)?((?:19|20)\d{2})\b"
    r"|\b((?:19|20)\d{2})(?:[-/]\d{2,4})?\s+onwards\b",
    re.IGNORECASE,
)
_OPEN_ENDED_AFTER_RE = re.compile(
    r"\bafter\s+(?:the\s+)?((?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def intake_start_years(text: str) -> tuple[int, ...]:
    """All intake start years named in `text`.

    A single cohort range ("2027-2029", "2026/27") yields its start year `(2027,)` /
    `(2026,)`; a list ("2026 and 2027", "2026-2028, 2027-2029") yields each cohort's
    start year `(2026, 2027)`.
    """
    raw = (text or "").strip()
    if not raw or raw == "UNSTATED":
        return ()
    parts = _MULTI_INTAKE_SPLIT_RE.split(raw)
    years: list[int] = []
    for part in parts:
        y = intake_start_year(part)
        if y is not None and y not in years:
            years.append(y)
    return tuple(years)


def intake_matches_target(text: str, target: int | str | None) -> bool:
    """True when `text` is unstated/blank or names an intake/range that includes `target`."""
    raw = (text or "").strip()
    if not raw or raw == "UNSTATED":
        return True
    target_int = (
        target
        if isinstance(target, int)
        else (intake_start_year(str(target)) if target is not None else None)
    )
    if target_int is None:
        return False
    m_from = _OPEN_ENDED_FROM_RE.search(raw)
    if m_from:
        from_year = int(m_from.group(1) or m_from.group(2))
        if target_int >= from_year:
            return True
    m_after = _OPEN_ENDED_AFTER_RE.search(raw)
    if m_after:
        after_year = int(m_after.group(1))
        if target_int > after_year:
            return True
    years = intake_start_years(raw)
    if not years:
        return True
    return target_int in years


def _intake_start(intake: str, override: dt.date | None) -> dt.date | None:
    if override is not None:
        return override
    year = intake_start_year(intake)
    if year is None:
        return None
    month, day = _ASSUMED_INTAKE_START
    return dt.date(year, month, day)


def _shift(value: dt.date, years: int) -> dt.date:
    """The same day, `years` later. 29 February becomes 28 February."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def served_intake_year(when: dt.date) -> int:
    """The intake a call dated `when` serves: the first intake start on or after it.

    A deadline in May serves that September's intake; one in November serves
    the next. The calendar year of the date is only right for the first kind,
    and reading it for both projected every autumn call a year late.
    """
    month, day = _ASSUMED_INTAKE_START
    return when.year if when <= dt.date(when.year, month, day) else when.year + 1


def project_window(
    past_calls: tuple[tuple[dt.date, dt.date | None], ...], *, target_year: int
) -> tuple[dt.date, dt.date | None]:
    """The latest observed cycle, moved to the intake `target_year` serves.

    Arithmetic, not a model. The shift is measured from the intake the observed
    cycle served -- its deadline's year, or its opening's when it stated none --
    so a call that opens in October for the following autumn projects to the
    October before the target intake, not to the October inside it.
    """
    latest_open, latest_deadline = max(past_calls, key=lambda cycle: cycle[0])
    delta = target_year - served_intake_year(latest_deadline or latest_open)
    return _shift(latest_open, delta), (
        _shift(latest_deadline, delta) if latest_deadline is not None else None
    )


def _recurs(past_calls: tuple[tuple[dt.date, dt.date | None], ...]) -> bool:
    """Two consecutive observed cycles. One cycle is not a cadence, and a gap
    year breaks the chain -- a scheme that skipped a year has to show its next
    call before it is projected again."""
    years = sorted({open_.year for open_, _deadline in past_calls}, reverse=True)
    return any(a - b == 1 for a, b in zip(years, years[1:]))


def _month_before(month: int, start: dt.date) -> dt.date:
    """The last first-of-`month` on or before `start`."""
    candidate = dt.date(start.year, month, 1)
    return candidate if candidate <= start else dt.date(start.year - 1, month, 1)


def _projection(
    evidence: Evidence, *, target_year: int, start: dt.date, today: dt.date
) -> tuple[dt.date, dt.date | None] | None:
    """The window this intake's call is expected in, from the strongest
    recurrence evidence available, or None when there is none."""
    if _recurs(evidence.past_calls):
        return project_window(evidence.past_calls, target_year=target_year)
    if evidence.recurrence_stated:
        month = _MONTHS.get(evidence.recurrence_stated.strip().casefold())
        if month is not None:
            return _month_before(month, start), None
    cadence = evidence.register_cadence
    # Expiring on purpose: a cadence nobody has re-checked since an earlier
    # cycle is a hint, not evidence (spec 3.5.1).
    if cadence is not None and cadence.verified_for_cycle >= today.year - 1:
        opening = _month_before(cadence.open_month, start)
        deadline = dt.date(
            opening.year + (1 if cadence.deadline_month < cadence.open_month else 0),
            cadence.deadline_month,
            1,
        )
        return opening, deadline
    return None


def _condition_outcome(condition: str, student: dict[str, object]) -> Outcome:
    """SATISFIED/FAILED/UNDECIDABLE for one condition against one student.

    Three-valued so the two callers can collapse it differently: choosing a
    date only ever acts on SATISFIED (an abstention must not silently pick a
    date that may not be the student's), while flagging a page-named group
    with no date (`missing_for`) is right to act on anything that is not
    FAILED -- an abstention is exactly what that flag exists to report.
    """
    if condition == "ALL":
        return "SATISFIED"
    kind, _, value = condition.partition(":")
    if kind in _EQUALITY_KINDS:
        if not value:
            # A bare "ROUND" or "DESCENT" names no group at all; it must not
            # match every student whose dict happens to lack that key.
            return "FAILED"
        student_val = str(student.get(kind.casefold(), "")).casefold()
        target_val = value.casefold()
        if kind == "APPLICANT_CLASS" and student_val:
            if student_val in ("eu", "eea", "eu_eea") and target_val in (
                "eu",
                "eea",
                "eu_eea",
            ):
                return "SATISFIED"
            if student_val in (
                "non_eu",
                "non_eea",
                "non_eu_eea",
                "international",
            ) and target_val in (
                "non_eu",
                "non_eea",
                "non_eu_eea",
                "international",
            ):
                return "SATISFIED"
        matched = student_val == target_val
        return "SATISFIED" if matched else "FAILED"
    key = _ELIGIBILITY_ALIASES.get(kind, kind)
    # key is plain str (an unvalidated condition prefix); ConditionTriple.key is a
    # closed Literal. Pydantic validates the actual value at construction regardless
    # of this cast, which only satisfies the static type -- same seam as
    # evaluation.py::_as_triple.
    try:
        triple = ConditionTriple(key=cast(Key, key), operator="IN", value=value, quote=condition)
    except ValidationError:
        return "FAILED"
    return decide(triple, _profile_view(student)).outcome


def _profile_view(student: dict[str, object]) -> SimpleNamespace:
    """A namespace the shared deciders can `getattr` unchanged.

    Each decider reads its own field with its own default via
    `getattr(profile, name, default)` -- AGE's default is None,
    PRIOR_INSTITUTION's is `()`. A dict-backed shim that always answers (the
    old `_StudentView`) returns its own default ("") for every name the
    student dict lacks, which overrides every one of those and would reach
    PRIOR_INSTITUTION's `tuple(getattr(profile, "academic_history", ()))` as
    `tuple("")` rather than `()`. `SimpleNamespace(**student)` fixes that: a
    missing attribute really raises `AttributeError`, so each decider's own
    default applies -- except a key that is *present and null*, which
    `.items()` would still set as an attribute equal to `None` rather than
    omit, and PRIOR_INSTITUTION's `tuple(None)` raises `TypeError`, uncaught
    by this module's `ValidationError` guard. Dropping the `None` entries
    makes a recorded null mean the same as an absent key here, which is what
    every decider's own default already assumes.
    """
    return SimpleNamespace(**{key: value for key, value in student.items() if value is not None})


def _is_unconditional(condition: str) -> bool:
    """"ALL" and a bare OPEN row both describe nobody in particular:
    decide()'s OPEN branch is SATISFIED unconditionally ("the page states the
    award is open to all"), so an OPEN row must not compete with a genuinely
    specific condition for "most specific" any more than ALL does."""
    return condition == "ALL" or condition.partition(":")[0] == "OPEN"


def select_deadline(evidence: Evidence, student: dict[str, object]) -> Deadline | None:
    """This student's own deadline: the most specific condition they satisfy.

    A scheme routinely states one date per nationality, per applicant class or
    per round, and the pack shows the student theirs -- showing somebody else's
    is how a student misses a deadline they had. `missing_for` records that the
    page named their group without giving it a date, so the card can say so
    instead of implying the general date is theirs.

    `student` keys a deadline condition may read: `nationality` and
    `country_of_residence` (the shared eligibility vocabulary -- country- or
    region-aware), `descent` (matched by plain equality, not the shared
    decider), and the four casefolded partition keys `applicant_class`,
    `funding`, `route`, `round`.
    """
    matching = [
        (date, whose)
        for date, whose in evidence.deadlines
        if _condition_outcome(whose, student) == "SATISFIED"
    ]
    if not matching and evidence.deadline is not None:
        matching = [(evidence.deadline, "ALL")]
    if not matching:
        return None
    specific = [pair for pair in matching if not _is_unconditional(pair[1])]
    date, whose = min(specific or matching)
    missing = next(
        (
            condition
            for condition in evidence.conditions_without_dates
            if condition != "ALL" and _condition_outcome(condition, student) != "FAILED"
        ),
        "",
    )
    return Deadline(date=date, condition=whose, missing_for=missing)


def cycle_validity(
    evidence: Evidence,
    *,
    student: dict[str, object],
    target_intake: str,
    today: dt.date,
    intake_starts_on: dt.date | None = None,
) -> Validity:
    """The one function a card asks. Only OPEN and UPCOMING are ever shown.

    The order is the spec's and it matters: a dated statement of suspension
    beats every kind of history, because history is not a promise.
    """
    target = intake_start_year(target_intake)
    start = _intake_start(target_intake, intake_starts_on)
    if evidence.page_removed:
        return "ENDED"
    if evidence.contrary_on is not None and intake_matches_target(evidence.contrary_intake, target):
        return "SUSPENDED"
    stated_for = intake_start_year(evidence.applies_to)
    no_intake = (
        evidence.applies_to
        if evidence.applies_to != "UNSTATED"
        else evidence.contrary_intake
    )
    if evidence.offered == "NO" and intake_matches_target(no_intake, target):
        return "SUSPENDED"
    if (
        evidence.from_register
        and evidence.grant_window_end is not None
        and start is not None
        and evidence.grant_window_end < start
    ):
        # The register asserts funding only inside the project's funded period;
        # after it, only the page decides (spec 3.5.4).
        return "ENDED"
    if target is None or start is None:
        return "UNVERIFIED"
    if evidence.offered != "YES":
        return "UNVERIFIED"
    # The deadline first: a page stating this intake's call is still a call
    # whose deadline can have passed, and reading the statement first returned
    # OPEN for a window that had already shut.
    chosen = select_deadline(evidence, student)
    latest_start = max(start, dt.date(target, *_ASSUMED_INTAKE_START))
    if chosen is not None and (
        chosen.date <= latest_start
        or (
            stated_for == target
            and chosen.date.year == target
            and chosen.date.month <= 10
        )
    ):
        # A deadline for this intake: ahead of us it is open, behind us the
        # window is over and the student is offered the next intake instead.
        return "OPEN" if chosen.date >= today else "CLOSED_FOR_INTAKE"
    if (
        stated_for == target
        and evidence.stated_on is not None
        and start - dt.timedelta(days=365) <= evidence.stated_on <= start
    ):
        return "OPEN"
    projected = _projection(evidence, target_year=target, start=start, today=today)
    if projected is not None:
        opening, deadline = projected
        if (deadline or opening) >= today:
            return "UPCOMING"
        return "CLOSED_FOR_INTAKE"
    # Nothing found meets either bar: a scheme seen once, with no history and
    # no "every year", stays unverified until its call appears. Projecting a
    # first cycle would be the guess this module exists to refuse.
    return "UNVERIFIED"


#: Public for the evidence side (apps/funding/cycle_evidence.py), which must
#: put a deadline in the same intake window this module compares against.
ASSUMED_INTAKE_START = _ASSUMED_INTAKE_START


def projected_window(
    evidence: Evidence, *, target_intake: str, today: dt.date,
    intake_starts_on: dt.date | None = None,
) -> tuple[dt.date, dt.date | None] | None:
    """The window `cycle_validity` projected, for display and scheduling only.

    A read-only view of `_projection`: it decides nothing and changes nothing
    `cycle_validity` returns.
    """
    target = intake_start_year(target_intake)
    start = _intake_start(target_intake, intake_starts_on)
    if target is None or start is None:
        return None
    return _projection(evidence, target_year=target, start=start, today=today)
