"""List Elmify staff file views and downloads across every agency (owner decision 2026-10-11).

Reads the `StaffFileView` lines apps/audit/staff_access.py logs, from the web log group in
CloudWatch Logs (named by the WEB_LOG_GROUP environment variable or --log-group) or from a
local file in dev. It never reads the database, so no tenant boundary is crossed.
"""

import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3  # type: ignore[import-untyped]
from django.core.management.base import BaseCommand, CommandError, CommandParser

_LINE = re.compile(
    r"StaffFileView action=(\S+) tenant=(\S+) staff=(\S+) student=(\S+) document=(\S+)"
)


def _timestamp(token: str) -> datetime | None:
    """An ISO timestamp (naive read as UTC), or None for anything else."""
    try:
        parsed = datetime.fromisoformat(token)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _start(since: str) -> datetime:
    if m := re.fullmatch(r"(\d+)([dh])", since):
        unit = "days" if m[2] == "d" else "hours"
        return datetime.now(UTC) - timedelta(**{unit: int(m[1])})
    if (parsed := _timestamp(since)) is None:
        raise CommandError(f"--since must be like 1d, 12h or 2026-10-11, not {since!r}")
    return parsed


class Command(BaseCommand):
    help = "Print one line per Elmify staff file view/download, across all agencies."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--since", default="1d")
        parser.add_argument("--file", help="read a local log file instead of CloudWatch")
        parser.add_argument("--log-group", default=os.environ.get("WEB_LOG_GROUP", ""))

    def _events(
        self, since: datetime, path: str | None, log_group: str
    ) -> Iterator[tuple[str, str]]:
        if path:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    if "StaffFileView" not in line:
                        continue
                    prefix = line.split("StaffFileView")[0].strip()
                    # A line whose prefix carries no ISO timestamp cannot be filtered
                    # and is kept. Never _start: a first token "1d" is not a window.
                    stamp = _timestamp(prefix.split()[0]) if prefix else None
                    if stamp is not None and stamp < since:
                        continue
                    yield prefix or "-", line
            return
        if not log_group:
            raise CommandError("set WEB_LOG_GROUP or pass --log-group (or --file)")
        pages = boto3.client("logs").get_paginator("filter_log_events").paginate(
            logGroupName=log_group,
            filterPattern='"StaffFileView"',
            startTime=int(since.timestamp() * 1000),
        )
        for page in pages:
            for event in page["events"]:
                when = datetime.fromtimestamp(event["timestamp"] / 1000, UTC).isoformat()
                yield when, event["message"]

    def handle(self, *args: object, **options: Any) -> None:
        since = _start(options["since"])
        for when, message in self._events(since, options["file"], options["log_group"]):
            if m := _LINE.search(message):
                action, tenant, staff, student, document = m.groups()
                self.stdout.write(
                    f"{when} action={action} tenant={tenant} staff={staff} "
                    f"student={student} document={document}"
                )
