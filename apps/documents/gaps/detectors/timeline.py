"""Timeline gap detector: finds uncovered spans across education, experience
and timeline entries.
"""

from __future__ import annotations

from datetime import date

from apps.documents.dates import parse_cv_date
from apps.documents.gaps.models import GapQuestion, Kind, _current
from apps.documents.models import VerifiedFact
from apps.documents.schemas import open_span_end
from apps.tenancy.models import Membership

#: TUM: a CV "must not contain any gaps longer than 3 months". The strictest
#: threshold any source states, so it is the one used: a gap that clears TUM
#: clears ETH, DAAD PRIME (R-011), uni-assist (R-020) and Harvard GSD too.
#: 92 days rather than a month count, because the ledger holds dates.
_MIN_GAP_DAYS = 92


def timeline_gaps(student: Membership) -> tuple[GapQuestion, ...]:
    """Uncovered spans between the education, experience and timeline entries.

    A question since the TIMELINE category exists; it was a NOTE for as long as
    the ledger had nowhere to put the answer. S-045 measured what Cambridge
    actually prints for a gap -- "Full-time carer for family member", "3 months'
    full-time job-hunting" -- and neither has an employer or a bullet, which
    ExperienceEntry requires both of.

    TIMELINE facts are scanned alongside the other two, which is what stops a
    gap being asked twice: an answer covers exactly the span it was asked
    about, so the next run finds the timeline continuous. There is no
    _already_created call here for that reason -- unlike every other create
    group, this detector's own arithmetic tells it the question was answered.

    THE TRAILING SPAN IS A GAP TOO. ETH wants "all details right up to the time
    of application", and the span from the last entry to today is the one most
    likely to exist on a real applicant's CV -- the months between finishing a
    degree and applying. Its answer is stored with NO END DATE, which this
    function already reads as "still running": an end date of today would leave
    the gap reopening a day later and re-firing 93 days after that.

    A between-entries gap's stored span runs from the end of the previous entry
    to the start of the next, so it overlaps each neighbour by a day.
    Deliberate: the alternative is +/- 1 day arithmetic that leaves a one-day
    hole the next run could round back into a gap, and at the month granularity
    the CV prints, the overlap is invisible.

    An entry with no end date is still running, so it covers the timeline up to
    today: end_date=None renders as "present" everywhere else in this codebase
    and means the same thing here. An entry with no start date cannot be placed
    and is skipped rather than guessed at.

    Except an open-ended gap statement, once a later entry has started: it
    stops at that entry's start (schemas.open_span_end), so a post added after
    the trailing gap was answered does not leave the gaps after it unasked.
    """
    current = {
        category: _current(student, category)
        for category in (
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.EXPERIENCE,
            VerifiedFact.Category.RESEARCH,
            VerifiedFact.Category.TIMELINE,
        )
    }
    # Research closes an open gap statement where it is dated, though it
    # covers no span of its own here.
    starts = [
        _read_date(fact.payload.get("start_date") if isinstance(fact.payload, dict) else None)
        for category in (
            VerifiedFact.Category.EDUCATION,
            VerifiedFact.Category.EXPERIENCE,
            VerifiedFact.Category.RESEARCH,
        )
        for fact in current[category]
    ]
    spans: list[tuple[date, date]] = []
    for category in (
        VerifiedFact.Category.EDUCATION,
        VerifiedFact.Category.EXPERIENCE,
        VerifiedFact.Category.TIMELINE,
    ):
        for fact in current[category]:
            payload = fact.payload if isinstance(fact.payload, dict) else {}
            start = _read_date(payload.get("start_date"))
            # An entry that has not started yet -- an accepted place beginning
            # next September -- covers nothing so far. Counted, it would make
            # the months before it a gap ending in the future, and the student
            # would be asked to account for time that has not happened.
            if start is None or start > date.today():
                continue
            end = _read_date(payload.get("end_date"))
            if end is None and category == VerifiedFact.Category.TIMELINE:
                end = open_span_end(start, starts)
            end = end or date.today()
            if end >= start:
                spans.append((start, end))
    # Not `< 2`, as it was while this only looked BETWEEN entries: one entry
    # that ended two years ago is a trailing gap on its own.
    if not spans:
        return ()
    spans.sort()
    questions: list[GapQuestion] = []
    covered_to = spans[0][1]
    for start, end in spans[1:]:
        if (start - covered_to).days > _MIN_GAP_DAYS:
            questions.append(_timeline_question(covered_to, start))
        covered_to = max(covered_to, end)
    if (date.today() - covered_to).days > _MIN_GAP_DAYS:
        questions.append(_timeline_question(covered_to, None))
    return tuple(questions)


def _timeline_question(covered_to: date, start: date | None) -> GapQuestion:
    """One gap, as a question that creates a TIMELINE fact.

    ``start`` is the next entry's start, or None for the span running to today.
    The None case writes no end_date at all -- see timeline_gaps on why.
    """
    until = f"{start:%b %Y}" if start else "now"
    return GapQuestion(
        kind=Kind.TIMELINE_GAP,
        fact_id=None,
        category=VerifiedFact.Category.TIMELINE,
        # The span is in the slug because there can be several gaps on one
        # form and field_name keys on it: two gaps sharing a slug would share
        # one input box. "present" rather than a date for the trailing one,
        # which would otherwise get a new slug -- and a second input -- every
        # day that passes.
        slug=f"timeline-gap:{covered_to:%Y-%m-%d}:{start:%Y-%m-%d}" if start
        else f"timeline-gap:{covered_to:%Y-%m-%d}:present",
        payload_key="statement",
        group_keys=("statement",),
        # The dates are the detector's, not the student's: they are the gap it
        # found, and asking for them would be asking someone to retype what is
        # already on the screen. Sorted by key, matching _group_questions.
        defaults=(
            (("end_date", f"{start:%Y-%m-%d}"), ("start_date", f"{covered_to:%Y-%m-%d}"))
            if start
            else (("start_date", f"{covered_to:%Y-%m-%d}"),)
        ),
        prompt=(
            f"What were you doing between {covered_to:%b %Y} and {until}? One line -- or "
            "pick one of the suggestions. Several destinations require the CV to account "
            "for every month: TUM refuses a gap longer than three months, ETH asks for "
            "periods with no study or work listed explicitly."
        ),
        evidence=(
            f"Nothing on file covers {covered_to:%d %b %Y} to "
            + (f"{start:%d %b %Y}." if start else "today.")
        ),
    )


def _read_date(raw: object) -> date | None:
    """A ledger date as a date, or nothing. Never a guess.

    The ledger stores dates as the CV printed them ("June 2024", "2024-06-30"),
    so parse_cv_date does the reading. Unparseable is None and the entry is
    skipped: a span placed on a misread date invents a gap the student has to
    argue with.
    """
    if not raw:
        return None
    return parse_cv_date(raw)
