"""When to look again, which intakes to watch, and when a projection lapses (spec 9.3). Pure."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from django.conf import settings

from apps.funding.cycle_evidence import intake_start


def tracked_intakes(today: dt.date) -> tuple[int, ...]:
    """The next CYCLE_TRACKED_INTAKES intakes that have not started."""
    first = today.year if today < intake_start(today.year) else today.year + 1
    return tuple(first + n for n in range(settings.CYCLE_TRACKED_INTAKES))


def _next_anniversary(value: dt.date, today: dt.date) -> dt.date:
    for year in (today.year, today.year + 1):
        try:
            candidate = value.replace(year=year)
        except ValueError:  # 29 February
            candidate = value.replace(year=year, day=28)
        if candidate >= today:
            return candidate
    return value


def next_check(
    *,
    today: dt.date,
    deadlines: Iterable[dt.date],
    last_call_open: dt.date | None,
    projected_open: dt.date | None,
) -> dt.date:
    days = dt.timedelta
    ahead = [d for d in deadlines if d >= today]
    # Where each watched window begins; a check scheduled past one of these
    # would skip the start of the daily/weekly checks it exists for.
    starts = [d - days(settings.CYCLE_DEADLINE_WINDOW_DAYS) for d in ahead]
    if ahead and min(ahead) - today <= days(settings.CYCLE_DEADLINE_WINDOW_DAYS):
        return today + days(settings.CYCLE_CHECK_DAYS_DEADLINE)
    if projected_open is not None:
        lead = projected_open - days(settings.CYCLE_PROJECTION_LEAD_DAYS)
        if lead <= today <= projected_open + days(settings.CYCLE_PROJECTION_LAPSE_DAYS):
            return today + days(settings.CYCLE_CHECK_DAYS_SEASON)
        starts.append(lead)
    if last_call_open is not None:
        anniversary = _next_anniversary(last_call_open, today)
        if anniversary - today <= days(settings.CYCLE_SEASON_WINDOW_DAYS):
            return today + days(settings.CYCLE_CHECK_DAYS_SEASON)
        starts.append(anniversary - days(settings.CYCLE_SEASON_WINDOW_DAYS))
    upcoming = [start for start in starts if start > today]
    return min([today + days(settings.CYCLE_CHECK_DAYS_DEFAULT), *upcoming])


def projection_lapsed(projected_open: dt.date | None, *, today: dt.date, call_seen: bool) -> bool:
    if projected_open is None or call_seen:
        return False
    return today > projected_open + dt.timedelta(days=settings.CYCLE_PROJECTION_LAPSE_DAYS)
