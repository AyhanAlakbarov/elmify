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
