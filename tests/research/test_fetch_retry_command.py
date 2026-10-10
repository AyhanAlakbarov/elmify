"""Rung 5's worker: re-enter the ladder for a fetch whose retry window has come.

Two things this file pins beyond the brief's own five tests:

* a `BUDGET` row with a `retry_after` is picked up exactly like a
  `RETRY_SCHEDULED` one (Task 7 ruling -- a budget boundary is never the
  host's fault, so it is not written as RETRY_SCHEDULED, and this queue must
  still come back for it);
* an older, now-superseded RETRY_SCHEDULED row is never re-spent. There is no
  round marker on FetchAttempt, so "what is this URL's current state" rests
  on `created_at` -- without that, the same stale row would be re-fetched
  forever, spending real vendor credits on a round that already happened.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.research.fetch.types import Attempt, FetchedPage, Outcome
from apps.research.models import FetchAttempt, HostProfile
from apps.research.services import acquire_domain_lease

pytestmark = pytest.mark.django_db


def _due(url="https://e.test/a", host="e.test", ago=timedelta(hours=1), attempt_no=1):
    return FetchAttempt.objects.create(
        url=url, host=host, rung=5, vendor="NONE", outcome=Outcome.RETRY_SCHEDULED,
        retry_after=timezone.now() - ago, attempt_no=attempt_no,
    )


def _served(url="https://e.test/a"):
    return FetchedPage(
        final_url=url, redirects=(), content_type="text/html", body=b"x" * 5_000,
        markdown="# A", outcome=Outcome.FETCHED, fetched_via="FIRECRAWL", rung=1,
        cost_credits=1, status_code=200,
        attempts=(Attempt(rung=1, vendor="FIRECRAWL", outcome=Outcome.FETCHED, credits=1),),
    )


def test_a_due_retry_is_re_entered(monkeypatch):
    _due()
    called = []
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: called.append(url) or _served(url))
    call_command("retry_due_fetches")
    assert called == ["https://e.test/a"]


def test_a_retry_not_yet_due_is_left_alone(monkeypatch):
    _due(ago=timedelta(hours=-5))
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: pytest.fail("spent a retry before it was due"))
    call_command("retry_due_fetches")


def test_a_host_inside_its_cool_off_is_rescheduled_not_spent(monkeypatch):
    """Otherwise the queue defeats the very cool-off it is meant to respect."""
    row = _due()
    HostProfile.objects.create(host="e.test",
                               blocked_until=timezone.now() + timedelta(hours=3))
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: pytest.fail("fetched inside a cool-off"))
    call_command("retry_due_fetches")
    row.refresh_from_db()
    assert row.retry_after > timezone.now() + timedelta(hours=2)


def test_a_successful_retry_closes_the_scheduled_row(monkeypatch):
    row = _due()
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: _served(url))
    call_command("retry_due_fetches")
    row.refresh_from_db()
    assert row.retry_after is None


def test_the_command_reports_what_it_did(monkeypatch, capsys):
    _due()
    _due(url="https://f.test/b", host="f.test")
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: _served(url))
    call_command("retry_due_fetches")
    out = capsys.readouterr().out
    assert "2 due" in out
    assert "2 served" in out


def test_a_budget_row_is_picked_up_alongside_retry_scheduled(monkeypatch):
    """Task 7's ruling: a budget boundary writes BUDGET + retry_after, never
    RETRY_SCHEDULED, so it must not be invisible to this queue."""
    FetchAttempt.objects.create(
        url="https://g.test/a", host="g.test", rung=3, vendor="NONE",
        outcome=Outcome.BUDGET, retry_after=timezone.now() - timedelta(hours=1), attempt_no=1,
    )
    called = []
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: called.append(url) or _served(url))
    call_command("retry_due_fetches")
    assert called == ["https://g.test/a"]


def test_a_superseded_round_is_never_re_spent(monkeypatch):
    """No round marker exists on FetchAttempt, so "what is current" rests on
    created_at. Without windowing on it, the OLD row -- still RETRY_SCHEDULED,
    still carrying a past retry_after -- would be re-fetched forever even
    though a later attempt already moved the URL on: an unbounded loop that
    spends real vendor credits on a round that already happened."""
    old = _due()
    newer = FetchAttempt.objects.create(
        url=old.url, host=old.host, rung=5, vendor="NONE",
        outcome=Outcome.RETRY_SCHEDULED,
        retry_after=timezone.now() + timedelta(hours=5), attempt_no=2,
    )
    # auto_now_add only fires on INSERT via .save(); .update() bypasses it, so
    # this is the one honest way to give the newer row a later created_at
    # without waiting on the wall clock.
    FetchAttempt.objects.filter(pk=newer.pk).update(
        created_at=timezone.now() + timedelta(seconds=1)
    )
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: pytest.fail("re-spent an already-superseded round"))
    call_command("retry_due_fetches")


def test_the_whole_run_spends_one_budget(monkeypatch):
    """Unattended and six-hourly, so a per-row `default_budget()` is no
    ceiling at all -- 5,000 due rows would be 5,000 uncapped ladder walks.
    One budget for the run also restores `sweep_id`'s own promise that one
    sweep's rows total without guessing at timestamps."""
    _due()
    _due(url="https://f.test/b", host="f.test")
    budgets = []
    monkeypatch.setattr(
        "apps.research.management.commands.retry_due_fetches.fetch_page",
        lambda url, **kwargs: budgets.append(kwargs["budget"]) or _served(url),
    )
    call_command("retry_due_fetches")
    assert len(budgets) == 2
    assert budgets[0] is budgets[1]


def test_a_run_can_be_bounded_by_rows(monkeypatch):
    """Credits are one ceiling; rows are the other, and a cheap outcome
    (a rescheduled row, an archive hit) spends few credits while still
    costing a request."""
    _due()
    _due(url="https://f.test/b", host="f.test")
    called = []
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: called.append(url) or _served(url))
    call_command("retry_due_fetches", "--limit", "1")
    assert len(called) == 1


def test_a_lease_held_elsewhere_is_left_for_the_next_run(monkeypatch):
    """Safe to run concurrently with a sweep: a host another worker already
    holds the DomainLease for is skipped, not crashed on or double-fetched."""
    _due()
    acquire_domain_lease("e.test", interval=timedelta(minutes=5))
    monkeypatch.setattr("apps.research.management.commands.retry_due_fetches.fetch_page",
                        lambda url, **kwargs: pytest.fail("fetched past a lease held elsewhere"))
    call_command("retry_due_fetches")
