"""When to look again, which intakes to watch, and when a projection lapses (spec 9.3). Pure."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable, Sequence

from django.conf import settings

from apps.funding.cycle_evidence import intake_start

_DAYS_IN_YEAR = 365.25
_INTEGRATION_STEPS = 73


def _day_of_year(value: dt.date) -> float:
    return float(value.timetuple().tm_yday)


def _month_center_doy(month: int) -> float:
    m = min(12, max(1, int(month)))
    return float(dt.date(2025, m, 15).timetuple().tm_yday)


def circular_mean_doy(dates: Iterable[dt.date]) -> tuple[float | None, float]:
    """Circular mean day-of-year and von Mises concentration kappa from past call dates."""
    angles = [2.0 * math.pi * (_day_of_year(d) / _DAYS_IN_YEAR) for d in dates]
    if not angles:
        return None, 0.0
    sin_sum = sum(math.sin(a) for a in angles)
    cos_sum = sum(math.cos(a) for a in angles)
    n = float(len(angles))
    r_bar = math.hypot(sin_sum, cos_sum) / n
    mean_angle = math.atan2(sin_sum, cos_sum)
    if mean_angle < 0:
        mean_angle += 2.0 * math.pi
    mean_doy = (mean_angle / (2.0 * math.pi)) * _DAYS_IN_YEAR
    if len(angles) == 1:
        kappa = 3.0
    else:
        kappa = min(6.0, max(1.5, 1.0 / max(0.15, 1.0 - r_bar)))
    return mean_doy, kappa


def seasonal_hazard(
    doy: float,
    *,
    open_doy: float | None = None,
    deadline_doy: float | None = None,
    kappa_open: float = 2.5,
    kappa_deadline: float = 3.5,
    lambda_base: float = 1.0,
    amp_open: float = 4.0,
    amp_deadline: float = 5.0,
) -> float:
    """Evaluate the non-homogeneous seasonal renewal hazard lambda(t) > 0 at day-of-year `doy`."""
    lam = float(lambda_base)
    if open_doy is not None:
        phase = 2.0 * math.pi * (doy - open_doy) / _DAYS_IN_YEAR
        lam += amp_open * math.exp(kappa_open * (math.cos(phase) - 1.0))
    if deadline_doy is not None:
        phase = 2.0 * math.pi * (doy - deadline_doy) / _DAYS_IN_YEAR
        lam += amp_deadline * math.exp(kappa_deadline * (math.cos(phase) - 1.0))
    return max(1e-6, lam)


def hazard_interval_days(
    today: dt.date,
    *,
    open_month: int | None = None,
    past_open_dates: Sequence[dt.date] = (),
    past_deadlines: Sequence[dt.date] = (),
    annual_budget_checks: float | None = None,
) -> int:
    """Optimal inter-check interval in days under square-root seasonal renewal hazard
    r*(t) = B * sqrt(lambda(t)) / int_0^T sqrt(lambda(s)) ds (Cho & Garcia-Molina 2003).
    """
    default_days = int(settings.CYCLE_CHECK_DAYS_DEFAULT)
    season_days = int(settings.CYCLE_CHECK_DAYS_SEASON)
    deadline_days = int(settings.CYCLE_CHECK_DAYS_DEADLINE)

    open_doy: float | None = None
    kappa_open = 3.5
    if open_month is not None:
        open_doy = _month_center_doy(open_month)
    elif past_open_dates:
        open_doy, kappa_open = circular_mean_doy(past_open_dates)

    deadline_doy: float | None = None
    kappa_deadline = 4.5
    if past_deadlines:
        deadline_doy, kappa_deadline = circular_mean_doy(past_deadlines)

    if open_doy is None and deadline_doy is None:
        return default_days

    dt_grid = _DAYS_IN_YEAR / _INTEGRATION_STEPS
    integral_sqrt = 0.0
    for i in range(_INTEGRATION_STEPS):
        s = (i + 0.5) * dt_grid
        integral_sqrt += (
            math.sqrt(
                seasonal_hazard(
                    s,
                    open_doy=open_doy,
                    deadline_doy=deadline_doy,
                    kappa_open=kappa_open,
                    kappa_deadline=kappa_deadline,
                )
            )
            * dt_grid
        )

    budget = annual_budget_checks or (_DAYS_IN_YEAR / float(default_days)) * 1.65
    lam_today = seasonal_hazard(
        _day_of_year(today),
        open_doy=open_doy,
        deadline_doy=deadline_doy,
        kappa_open=kappa_open,
        kappa_deadline=kappa_deadline,
    )
    r_star = budget * math.sqrt(lam_today) / max(1e-9, integral_sqrt)
    optimal = round(1.0 / max(r_star, 1.0 / float(default_days)))
    return max(min(season_days, deadline_days), min(default_days, optimal))


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
    deadlines: Iterable[dt.date] = (),
    last_call_open: dt.date | None = None,
    projected_open: dt.date | None = None,
    open_month: int | None = None,
    past_open_dates: Sequence[dt.date] = (),
    past_deadlines: Sequence[dt.date] = (),
    annual_budget_checks: float | None = None,
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
    if open_month is not None and 1 <= open_month <= 12:
        diff = (today.month - open_month) % 12
        if diff in (0, 11):
            return today + days(settings.CYCLE_CHECK_DAYS_SEASON)
    base_days = int(settings.CYCLE_CHECK_DAYS_DEFAULT)
    if open_month is not None or past_open_dates or past_deadlines:
        base_days = hazard_interval_days(
            today,
            open_month=open_month,
            past_open_dates=past_open_dates,
            past_deadlines=past_deadlines,
            annual_budget_checks=annual_budget_checks,
        )
    upcoming = [start for start in starts if start > today]
    return min([today + days(base_days), *upcoming])


def projection_lapsed(projected_open: dt.date | None, *, today: dt.date, call_seen: bool) -> bool:
    if projected_open is None or call_seen:
        return False
    return today > projected_open + dt.timedelta(days=settings.CYCLE_PROJECTION_LAPSE_DAYS)
