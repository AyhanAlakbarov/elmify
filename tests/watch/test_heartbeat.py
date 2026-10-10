from datetime import timedelta

import pytest
from django.utils import timezone

from apps.watch.heartbeat import EXPECTED_JOBS, record_run, report_silent, silent_jobs

pytestmark = pytest.mark.django_db


def test_a_job_that_has_never_run_is_silent():
    """First deploy, or a rule shipped disabled: never having run is not health."""
    assert set(silent_jobs()) == set(EXPECTED_JOBS)


def test_a_recent_run_is_not_silent():
    for name in EXPECTED_JOBS:
        record_run(name)
    assert silent_jobs() == []


def test_a_run_older_than_its_window_is_silent():
    now = timezone.now()
    for name, window in EXPECTED_JOBS.items():
        record_run(name, now=now - window - timedelta(minutes=1))
    assert set(silent_jobs(now=now)) == set(EXPECTED_JOBS)


def test_silence_is_logged_by_name_for_the_alarm(caplog):
    with caplog.at_level("ERROR"):
        report_silent()
    for name in EXPECTED_JOBS:
        assert f"JobSilent job={name}" in caplog.text


def test_every_scheduled_job_is_watched():
    """The two hourly jobs, and the six-hourly mailbox backstop since its
    schedule shipped (watch spec §3a)."""
    assert EXPECTED_JOBS == {
        "send_due_reminders": timedelta(hours=2),
        "watch_applications": timedelta(hours=2),
        "sync_mailboxes": timedelta(hours=13),
    }


def test_a_finished_run_is_logged_for_the_all_jobs_dead_alarm(caplog):
    """If every job dies, none is left to log JobSilent; the absence of this
    line is what JobFinishedMissingAlarm sees (infra/template.yaml)."""
    with caplog.at_level("INFO"):
        record_run("watch_applications")
    assert "JobFinished job=watch_applications" in caplog.text
