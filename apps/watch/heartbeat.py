"""Every scheduled job says when it finished; each checks the others.

A job that stops is otherwise invisible: the reminders simply never arrive and
every screen looks right. The ERROR line is what the CloudWatch metric filter
on the worker log group counts (infra/template.yaml, JobSilentAlarm). Both
hourly commands call report_silent, so either one notices the other stopping.
If both stop -- one image, one task definition, one bad deploy -- nobody is
left to log JobSilent, so every finished run also logs JobFinished and
JobFinishedMissingAlarm fires on its absence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.utils import timezone

from .models import JobRun

logger = logging.getLogger(__name__)

#: Job name (the management command) -> how long without a finished run is
#: silence. Two hours for an hourly job tolerates one missed run's jitter;
#: thirteen for the six-hourly mailbox backstop tolerates one missed run.
EXPECTED_JOBS: dict[str, timedelta] = {
    "send_due_reminders": timedelta(hours=2),
    "watch_applications": timedelta(hours=2),
    "sync_mailboxes": timedelta(hours=13),
}


def record_run(name: str, *, now: datetime | None = None) -> None:
    JobRun.objects.update_or_create(
        name=name, defaults={"last_success_at": now or timezone.now()}
    )
    logger.info("JobFinished job=%s", name)


def silent_jobs(*, now: datetime | None = None) -> list[str]:
    moment = now or timezone.now()
    last = dict(JobRun.objects.values_list("name", "last_success_at"))
    return [
        name
        for name, window in EXPECTED_JOBS.items()
        if name not in last or moment - last[name] > window
    ]


def report_silent(*, now: datetime | None = None) -> list[str]:
    silent = silent_jobs(now=now)
    for name in silent:
        logger.error("JobSilent job=%s", name)
    return silent
