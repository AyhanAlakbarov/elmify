from datetime import UTC, datetime, time, timedelta

from apps.portals.models import Rung
from apps.portals.reminders import (
    due_rungs,
    in_quiet_hours,
    owed_rung,
    remaining_phrase,
)

DEADLINE = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)


def _at(**delta):
    return DEADLINE - timedelta(**delta)


def test_nothing_is_due_a_month_out():
    assert due_rungs(DEADLINE, _at(days=30)) == ()


def test_the_first_rung_opens_at_fourteen_days():
    assert due_rungs(DEADLINE, _at(days=14)) == (Rung.D14,)


def test_every_earlier_rung_stays_due():
    assert due_rungs(DEADLINE, _at(days=5)) == (Rung.D14, Rung.D7)


def test_the_last_rung_opens_at_six_hours():
    assert due_rungs(DEADLINE, _at(hours=6)) == (Rung.D14, Rung.D7, Rung.D3, Rung.D1, Rung.H6)


def test_a_passed_deadline_owes_nothing():
    """Not a missed-deadline notice -- that is a different feature nobody asked for."""
    assert due_rungs(DEADLINE, DEADLINE + timedelta(minutes=1)) == ()


def test_the_tightest_unsent_rung_is_the_one_owed():
    due = (Rung.D14, Rung.D7, Rung.D3)

    assert owed_rung(due, {Rung.D14}) == Rung.D3


def test_nothing_is_owed_once_every_due_rung_is_sent():
    assert owed_rung((Rung.D14, Rung.D7), {Rung.D14, Rung.D7}) is None


def test_no_window_means_never_quiet():
    assert in_quiet_hours(time(3, 0), None, None) is False


def test_a_window_that_crosses_midnight_covers_the_small_hours():
    """The normal case: 22:00-07:00. A plain between() is empty here."""
    assert in_quiet_hours(time(3, 0), time(22, 0), time(7, 0)) is True
    assert in_quiet_hours(time(23, 30), time(22, 0), time(7, 0)) is True
    assert in_quiet_hours(time(12, 0), time(22, 0), time(7, 0)) is False


def test_a_window_inside_one_day_also_works():
    assert in_quiet_hours(time(13, 30), time(13, 0), time(14, 0)) is True
    assert in_quiet_hours(time(15, 0), time(13, 0), time(14, 0)) is False


def test_the_phrase_counts_days_when_there_are_days_left():
    assert remaining_phrase(timedelta(days=3, hours=2)) == "3 days"


def test_the_phrase_counts_hours_inside_two_days():
    assert remaining_phrase(timedelta(hours=6)) == "6 hours"
