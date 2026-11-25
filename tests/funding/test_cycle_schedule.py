import datetime as dt

from apps.funding.cycle_schedule import next_check, projection_lapsed, tracked_intakes

TODAY = dt.date(2026, 9, 26)


def test_tracked_intakes_are_the_next_two_that_have_not_started():
    assert tracked_intakes(dt.date(2026, 8, 31)) == (2026, 2027)
    assert tracked_intakes(TODAY) == (2027, 2028)


def test_monthly_by_default():
    assert next_check(today=TODAY, deadlines=(), last_call_open=None,
                      projected_open=None) == TODAY + dt.timedelta(days=30)


def test_daily_within_fourteen_days_of_a_known_deadline():
    assert next_check(today=TODAY, deadlines=(dt.date(2026, 10, 5),), last_call_open=None,
                      projected_open=None) == TODAY + dt.timedelta(days=1)


def test_weekly_in_the_two_months_before_last_cycles_call_date():
    assert next_check(today=TODAY, deadlines=(), last_call_open=dt.date(2025, 11, 10),
                      projected_open=None) == TODAY + dt.timedelta(days=7)


def test_weekly_from_one_month_before_a_projected_opening():
    assert next_check(today=TODAY, deadlines=(), last_call_open=None,
                      projected_open=dt.date(2026, 10, 20)) == TODAY + dt.timedelta(days=7)


def test_a_projection_lapses_45_days_late_with_no_call():
    assert projection_lapsed(dt.date(2026, 8, 1), today=TODAY, call_seen=False) is True
    assert projection_lapsed(dt.date(2026, 8, 15), today=TODAY, call_seen=False) is False
    assert projection_lapsed(dt.date(2026, 8, 1), today=TODAY, call_seen=True) is False


def test_the_daily_checks_begin_at_the_start_of_a_deadline_window():
    assert next_check(today=TODAY, deadlines=(dt.date(2026, 10, 16),), last_call_open=None,
                      projected_open=None) == dt.date(2026, 10, 2)


def test_the_weekly_checks_begin_a_month_before_a_projected_opening():
    assert next_check(today=TODAY, deadlines=(), last_call_open=None,
                      projected_open=dt.date(2026, 11, 15)) == dt.date(2026, 10, 16)


def test_the_weekly_checks_begin_two_months_before_last_cycles_call_date():
    assert next_check(today=TODAY, deadlines=(), last_call_open=dt.date(2025, 12, 10),
                      projected_open=None) == dt.date(2026, 10, 10)


def test_circular_mean_doy_handles_december_january_wrap_around():
    from apps.funding.cycle_schedule import circular_mean_doy

    # Dec 28 (DOY 362) and Jan 3 (DOY 3) wrap across New Year's Day -> ~Dec 31 (DOY 365)
    mean_doy, kappa = circular_mean_doy([dt.date(2024, 12, 28), dt.date(2025, 1, 3)])
    assert mean_doy is not None
    assert mean_doy >= 360.0 or mean_doy <= 2.0
    assert kappa > 0.0


def test_seasonal_hazard_and_square_root_allocation_compress_interval_near_peak():
    from apps.funding.cycle_schedule import _month_center_doy, hazard_interval_days, seasonal_hazard

    # Peak around October (open_month=10) vs quiescent April
    oct_date = dt.date(2026, 10, 15)
    apr_date = dt.date(2026, 4, 15)
    oct_doy = _month_center_doy(10)
    h_oct = seasonal_hazard(oct_doy, open_doy=oct_doy)
    h_apr = seasonal_hazard(_month_center_doy(4), open_doy=oct_doy)
    assert h_oct > h_apr * 3.0
    assert hazard_interval_days(oct_date, open_month=10) < hazard_interval_days(
        apr_date, open_month=10
    )
    # next_check with open_month=10 on Oct 15 schedules a shorter interval than 30 days
    scheduled = next_check(
        today=oct_date,
        deadlines=(),
        last_call_open=None,
        projected_open=None,
        open_month=10,
    )
    assert (scheduled - oct_date).days <= 14

