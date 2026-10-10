"""The paid academic-year cycle (transcript spec R13, §7.1)."""

from __future__ import annotations

from uuid import UUID

from .models import StudentCycle


def paid_cycle(student_id: UUID) -> StudentCycle | None:
    """The student's newest paid cycle, or None: no transcript upload and no search without one."""
    return (
        StudentCycle.objects.filter(student_id=student_id, paid_at__isnull=False)
        .order_by("-academic_year")
        .first()
    )
