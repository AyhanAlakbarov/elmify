"""Queueing and resuming per-application CV generation jobs (CV build step 4.2)."""

from __future__ import annotations

import logging
from datetime import timedelta
from functools import partial
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.portals.models import Application
from apps.ratelimit import seconds_until_reset
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership

from .document_queue import DocumentWorkMessage, enqueue_document_work
from .models import DocumentDraft

logger = logging.getLogger(__name__)


def _send_cv_job(
    tenant_id: UUID,
    student_id: UUID,
    application_id: UUID,
    programme_id: UUID | None,
    *,
    delay_seconds: int = 0,
) -> None:
    message = DocumentWorkMessage(
        action="generate",
        kind=DocumentDraft.Kind.CV,
        tenant_id=tenant_id,
        student_id=student_id,
        application_id=application_id,
        programme_id=programme_id,
    )
    try:
        enqueue_document_work(
            message,
            queue_url=settings.DOCUMENT_QUEUE_URL,
            delay_seconds=delay_seconds,
        )
    except Exception as error:
        logger.warning(
            "could not queue CV generation for application %s (%s)",
            application_id,
            type(error).__name__,
        )


def queue_application_cv(
    application: Application, *, delay_seconds: int = 0
) -> None:
    """Enqueue one `generate` job for `application` after commit and mark it `QUEUED`."""
    with tenant_scope(application.tenant_id), tenant_transaction(application.tenant_id):
        application.cv_status = Application.CVStatus.QUEUED
        application.cv_resumes_at = None
        application.save(update_fields=["cv_status", "cv_resumes_at"])
        transaction.on_commit(
            partial(
                _send_cv_job,
                application.tenant_id,
                application.student_id,
                application.id,
                application.program_id,
                delay_seconds=delay_seconds,
            )
        )


def resume_waiting_cvs(student: Membership) -> int:
    """Re-queue every application of `student` waiting on identity or email."""
    with tenant_scope(student.tenant_id), tenant_transaction(student.tenant_id):
        waiting = list(
            Application.objects.filter(
                student=student,
                cv_status__in=(
                    Application.CVStatus.WAITING_IDENTITY,
                    Application.CVStatus.WAITING_EMAIL,
                ),
            ).order_by("created_at", "id")
        )
        for application in waiting:
            queue_application_cv(application)
    return len(waiting)


def defer(
    message: DocumentWorkMessage,
    *,
    window_seconds: int,
    application: Application | None,
) -> None:
    """Re-enqueue a rate-limited `generate` job for the next window (capped at SQS's 900s).

    Does not catch `enqueue_document_work` failures: if re-enqueuing fails, the
    exception propagates so SQS keeps the current delivery for retry.
    """
    delay = min(900, seconds_until_reset(window_seconds))
    enqueue_document_work(
        message,
        queue_url=settings.DOCUMENT_QUEUE_URL,
        delay_seconds=delay,
    )
    if application is not None:
        resumes_at = timezone.now() + timedelta(seconds=delay)
        with tenant_scope(message.tenant_id), tenant_transaction(message.tenant_id):
            Application.objects.filter(id=application.id).update(
                cv_status=Application.CVStatus.QUEUED,
                cv_resumes_at=resumes_at,
            )
