"""The paid academic-year cycle (transcript spec R13, §7.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from django.utils import timezone

from apps.tenancy.models import Membership

from .models import StudentCycle

REFUND_WINDOW_DAYS = 7
MAX_UNCONSUMED_KITS = 1
MAX_UNCONSUMED_EXPORTS = 0
MAX_UNCONSUMED_EXTENSION_SESSIONS = 0


@dataclass(frozen=True)
class CycleConsumptionStatus:
    """Anti-abuse ("Unconsumed Pass") consumption ledger for a StudentCycle.

    A 7-day cash refund is only available while a paid cycle pass is unconsumed:
    - 0 rendered/exported PDF or DOCX artefacts (`exports_count == 0`)
    - at most 1 application kit drafted (`kits_count <= 1`)
    - 0 browser-extension portal autofill / packet sessions (`extension_sessions_count == 0`)
    - within 7 days of `cycle.paid_at` (`within_7_day_window is True`)

    If transcript verification disqualifies a student's matches while the pass
    remains unconsumed (`is_consumed is False`), the student is also eligible
    for a free 12-month rollover to the next academic cycle (`rollover_eligible`).
    """

    kits_count: int
    exports_count: int
    extension_sessions_count: int
    transcript_pages_used: int
    within_7_day_window: bool
    is_consumed: bool
    refund_eligible: bool
    rollover_eligible: bool
    status_label: str
    summary: str


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


def cycle_consumption_status(
    student_id: UUID,
    cycle: StudentCycle | None = None,
    *,
    now: datetime | None = None,
) -> CycleConsumptionStatus:
    """Compute the deterministic Unconsumed Pass consumption state from PostgreSQL."""
    from apps.documents.models import DocumentDraft
    from apps.portals.models import Application, ApplicationStep, PreparedDocument

    now = now or timezone.now()
    applications_count = Application.objects.filter(student_id=student_id).count()
    programme_drafts_count = (
        DocumentDraft.objects.filter(student_id=student_id, is_general=False)
        .exclude(kind=DocumentDraft.Kind.CORE_NARRATIVE)
        .count()
    )
    kits_count = max(applications_count, programme_drafts_count)

    rendered_drafts_count = (
        DocumentDraft.objects.filter(student_id=student_id)
        .exclude(rendered_filename="")
        .count()
    )
    prepared_docs_count = PreparedDocument.objects.filter(student_id=student_id).count()
    exports_count = rendered_drafts_count + prepared_docs_count

    extension_sessions_count = ApplicationStep.objects.filter(
        application__student_id=student_id,
        kind__in=(
            ApplicationStep.Kind.PACKET,
            ApplicationStep.Kind.FILL,
            ApplicationStep.Kind.READ_BACK,
            ApplicationStep.Kind.SUBMITTED,
        ),
    ).count()

    transcript_pages_used = cycle.pages_used if cycle is not None else 0
    within_7_day_window = bool(
        cycle is not None
        and cycle.paid_at is not None
        and (now - cycle.paid_at) <= timedelta(days=REFUND_WINDOW_DAYS)
    )
    is_consumed = (
        exports_count > MAX_UNCONSUMED_EXPORTS
        or kits_count > MAX_UNCONSUMED_KITS
        or extension_sessions_count > MAX_UNCONSUMED_EXTENSION_SESSIONS
    )
    is_paid = cycle is not None and cycle.paid_at is not None
    refund_eligible = is_paid and within_7_day_window and not is_consumed
    rollover_eligible = is_paid and not is_consumed

    if not is_paid:
        status_label = "Unpaid (Explore preview)"
        summary = (
            "Pre-purchase match count preview is active on Explore (0 AZN). "
            "Inspect your matched Flagship and Hidden scholarship count before paying."
        )
    elif is_consumed:
        status_label = "Active & Consumed (Non-Refundable)"
        summary = (
            "Your Cycle Pass is active and has been consumed (2+ application kits drafted, "
            "PDF/DOCX files exported, or browser-extension portal autofill used). "
            "Cash refunds are locked once kits are exported or portal autofill runs."
        )
    elif within_7_day_window:
        status_label = "Unconsumed 7-Day Preview Window (Refund / Rollover Eligible)"
        summary = (
            "Eligible for the 7-day unconsumed refund (if < 5 verified matches) or a free "
            "12-month cycle rollover. Generating a 2nd application kit, exporting any "
            "CV/letter PDF, or running browser-extension autofill marks your pass as "
            "consumed and non-refundable."
        )
    else:
        status_label = "Active (7-Day Refund Window Closed · Rollover Eligible)"
        summary = (
            "The 7-day cash refund window has closed. Because your pass is still unconsumed, "
            "you remain eligible for a free 12-month rollover to the next academic cycle if "
            "transcript verification disqualifies your matches."
        )

    return CycleConsumptionStatus(
        kits_count=kits_count,
        exports_count=exports_count,
        extension_sessions_count=extension_sessions_count,
        transcript_pages_used=transcript_pages_used,
        within_7_day_window=within_7_day_window,
        is_consumed=is_consumed,
        refund_eligible=refund_eligible,
        rollover_eligible=rollover_eligible,
        status_label=status_label,
        summary=summary,
    )
