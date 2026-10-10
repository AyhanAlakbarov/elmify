from datetime import UTC, datetime, timedelta

from apps.watch.rules import CONFIRMATION_WINDOW, confirmation_due, escalation_target

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
FAR = T0 + timedelta(days=30)


def test_a_confirmation_is_due_two_days_after_submission():
    assert CONFIRMATION_WINDOW == timedelta(hours=48)
    assert confirmation_due(T0) == T0 + timedelta(hours=48)


def test_a_fresh_alert_is_not_escalated():
    assert escalation_target(T0, T0 + timedelta(hours=11), FAR) == 0


def test_far_from_a_deadline_email_at_12h_and_counsellor_at_24h():
    assert escalation_target(T0, T0 + timedelta(hours=12), FAR) == 1
    assert escalation_target(T0, T0 + timedelta(hours=23), FAR) == 1
    assert escalation_target(T0, T0 + timedelta(hours=24), FAR) == 2


def test_within_48h_of_a_deadline_email_at_2h_and_counsellor_at_4h():
    near = T0 + timedelta(hours=40)
    assert escalation_target(T0, T0 + timedelta(hours=1), near) == 0
    assert escalation_target(T0, T0 + timedelta(hours=2), near) == 1
    assert escalation_target(T0, T0 + timedelta(hours=4), near) == 2


def test_no_deadline_uses_the_slow_ladder():
    assert escalation_target(T0, T0 + timedelta(hours=2), None) == 0
    assert escalation_target(T0, T0 + timedelta(hours=24), None) == 2
