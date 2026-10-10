from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.fetch.site import Pressure, note_concurrency
from apps.research.models import FetchAttempt

pytestmark = pytest.mark.django_db


def test_a_queued_response_halves_the_concurrency_for_the_rest_of_the_sweep(settings):
    """Spec 9.3. The vendor is already queueing our work; asking for more
    parallelism buys latency, not pages. It is per SWEEP, not per call,
    because a limit that reset on the next page would re-learn the same
    lesson 25 times."""
    settings.FIRECRAWL_CONCURRENCY = 24
    pressure = Pressure()

    note_concurrency({"concurrencyLimited": True, "concurrencyQueueDurationMs": 31_000}, pressure)

    assert pressure.concurrency == 12


def test_a_short_queue_is_not_back_pressure():
    """`concurrencyLimited` alone means 'you waited'. Every busy minute would
    otherwise halve the sweep down to 1 and keep it there."""
    pressure = Pressure(concurrency=24)

    note_concurrency({"concurrencyLimited": True, "concurrencyQueueDurationMs": 400}, pressure)

    assert pressure.concurrency == 24


def test_concurrency_never_falls_below_one():
    pressure = Pressure(concurrency=1)

    for _ in range(5):
        note_concurrency(
            {"concurrencyLimited": True, "concurrencyQueueDurationMs": 60_000}, pressure
        )

    assert pressure.concurrency == 1


def test_the_reconciliation_logs_a_gap_over_five_percent(capsys):
    """Spec 9.2: a gap over 5% is a defect in OUR accounting, not the
    vendor's. The budget is the only thing standing between a bug and a bill,
    and a budget summing the wrong number is not a budget."""
    now = timezone.now()
    for _ in range(10):
        FetchAttempt.objects.create(
            url="https://uni.example.org/", host="uni.example.org", rung=1,
            vendor="FIRECRAWL", credits=1, outcome="FETCHED", created_at=now - timedelta(days=1),
        )

    call_command("reconcile_fetch_credits", "--vendor", "FIRECRAWL", "--vendor-total", "20")

    assert "gap 100.0%" in capsys.readouterr().out


def test_a_gap_inside_the_tolerance_is_reported_without_alarm(capsys):
    now = timezone.now()
    for _ in range(100):
        FetchAttempt.objects.create(
            url="https://uni.example.org/", host="uni.example.org", rung=1,
            vendor="FIRECRAWL", credits=1, outcome="FETCHED", created_at=now - timedelta(days=1),
        )

    call_command("reconcile_fetch_credits", "--vendor", "FIRECRAWL", "--vendor-total", "103")

    out = capsys.readouterr().out
    assert "gap 3.0%" in out
    assert "DEFECT" not in out
