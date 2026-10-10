"""The paid academic-year cycle (transcript spec R13, §7.1)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from django.utils import timezone

from apps.tenancy.models import Membership

from .models import StudentCycle


def paid_cycle(student_id: UUID) -> StudentCycle | None:
    """The student's newest paid cycle, or None: no transcript upload and no search without one."""
    return (
        StudentCycle.objects.filter(student_id=student_id, paid_at__isnull=False)
        .order_by("-academic_year")
        .first()
    )


def current_academic_year(today: date | None = None) -> str:
    """The cycle a student applying now is in: applications for a September
    intake run from the summer before, so July starts the next cycle."""
    today = today or timezone.localdate()
    start = today.year if today.month >= 7 else today.year - 1
    return f"{start}-{start + 1}"


def grant_early_access_cycle(student: Membership) -> StudentCycle:
    """This year's cycle, paid by early access rather than a checkout. Recorded
    as its own audit event so it is never mistaken for a received fee."""
    from apps.funding.models import AuditEvent

    cycle, created = StudentCycle.objects.get_or_create(
        student=student,
        academic_year=current_academic_year(),
        defaults={"paid_at": timezone.now()},
    )
    if created:
        AuditEvent.objects.create(
            actor=None,
            actor_kind=AuditEvent.ActorKind.SYSTEM,
            event="cycle.early_access",
            object_id=cycle.id,
        )
    return cycle
