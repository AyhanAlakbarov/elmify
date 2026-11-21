"""Which deadline counts and how it reads (lanes spec §9.2-§9.4).

Pure functions over an Application's own copy (`route_snapshot`), falling back
to `Application.deadline`. Never reads the catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from apps.accounts.models import StudentProfileVersion
from apps.portals.models import Application, zone_named
from apps.portals.route_snapshot import RouteSnapshot, SnapshotDate, read_snapshot

ROLLING = "Apply early: places fill as applications arrive"
DECENTRALISED = "Deadline set by each university"
CLOSED = "Closed for this intake"
#: §9.2: no zone stated means the earliest instant the day ends anywhere.
_EARLIEST = ZoneInfo("Etc/GMT-14")
#: ...and the latest it ends anywhere: the only moment "passed" is certain.
_LATEST = ZoneInfo("Etc/GMT+12")
_ORDER = {
    True: ("FUNDING_CONSIDERATION", "PRIORITY", "FINAL"),
    False: ("PRIORITY", "FINAL"),
}
_SUBMITTED = (Application.State.SUBMITTED, Application.State.CONFIRMED)

if TYPE_CHECKING:
    from apps.tenancy.models import Membership


@dataclass(frozen=True)
class Deadline:
    at: datetime | None
    #: The IANA zone the date is stated in; "" when not stated.
    zone: str
    wording: str = ""


def _end_of_day(when: SnapshotDate, *, unzoned: ZoneInfo = _EARLIEST) -> datetime | None:
    try:
        day = date.fromisoformat(when.date)
    except ValueError:
        return None
    where = zone_named(when.timezone) if when.timezone else None
    return datetime.combine(day, time(23, 59), tzinfo=where or unzoned)


def _dates(snapshot: RouteSnapshot | None, purpose: str) -> dict[str, SnapshotDate]:
    if snapshot is None:
        return {}
    return {d.role: d for s in snapshot.steps if s.purpose == purpose for d in s.dates}


def funding_mandatory(student: Membership) -> bool:
    """§9.3's switch: the student's latest profile says funding is MANDATORY."""
    profile = StudentProfileVersion.objects.filter(student=student).order_by("-version").first()
    return bool(profile and (profile.snapshot or {}).get("funding_dependency") == "MANDATORY")


def counting_deadline(application: Application, *, mandatory: bool) -> Deadline | None:
    """§9.3: FUNDING_CONSIDERATION, then PRIORITY, then FINAL for a student whose
    funding is MANDATORY; PRIORITY, then FINAL for everyone else."""
    roles = _dates(read_snapshot(application), "APPLY")
    if "ROLLING" in roles:
        return Deadline(None, "", ROLLING)
    if "DECENTRALISED" in roles:
        return Deadline(None, "", DECENTRALISED)
    for role in _ORDER[mandatory]:
        when = roles.get(role)
        at = _end_of_day(when) if when is not None else None
        if at is not None:
            assert when is not None
            return Deadline(at, when.timezone if zone_named(when.timezone) else "")
    if application.deadline is not None:
        return Deadline(application.deadline, application.deadline_timezone)
    return None


def _city(zone: str) -> str:
    return zone.rsplit("/", 1)[-1].replace("_", " ")


def both_zones(at: datetime, zone: str, student_zone: str) -> str:
    """§9.2: "15 Jan, 23:59 Stockholm time (02:59 Baku time, 16 Jan)"."""
    where = zone_named(zone) if zone else None
    if where is None:
        # The UTC day: right for an earliest-instant date (09:59 UTC, same day)
        # and for a stored instant whose zone name is unknown.
        local = at.astimezone(UTC)
        return f"{local.day} {local:%b} (end of day)"
    local = at.astimezone(where)
    text = f"{local.day} {local:%b}, {local:%H:%M} {_city(zone)} time"
    home = zone_named(student_zone) if student_zone and student_zone != zone else None
    if home is None:
        return text
    mine = at.astimezone(home)
    day = "" if mine.date() == local.date() else f", {mine.day} {mine:%b}"
    return f"{text} ({mine:%H:%M} {_city(student_zone)} time{day})"


def pre_checks(application: Application, student_zone: str) -> tuple[str, ...]:
    """§5.1: a pre-check (uni-assist) is its own earlier deadline -- a date, never
    an instruction."""
    snapshot = read_snapshot(application)
    if snapshot is None:
        return ()
    lines = []
    for step in snapshot.steps:
        if step.purpose != "PRE_CHECK":
            continue
        roles = {d.role: d for d in step.dates}
        when = roles.get("FINAL") or next(iter(roles.values()), None)
        at = _end_of_day(when) if when is not None else None
        if at is None or when is None:
            continue
        name = step.portal_system or "Pre-check"
        lines.append(f"{name} check: send by {both_zones(at, when.timezone, student_zone)}")
    return tuple(lines)


def final_passed(application: Application, now: datetime) -> bool:
    """§9.4: the FINAL date passed with no submission -- "Closed for this intake"."""
    if application.state in _SUBMITTED or application.outcome:
        return False
    when = _dates(read_snapshot(application), "APPLY").get("FINAL")
    # Certain, not cautious: a date with no zone has not ended until it has
    # ended everywhere. An unreadable FINAL falls back as counting_deadline does.
    at = _end_of_day(when, unzoned=_LATEST) if when is not None else None
    if at is None:
        at = application.deadline
    return at is not None and at < now
