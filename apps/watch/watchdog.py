"""Notice what should have happened and has not.

First expectation: a portal confirms a submission within CONFIRMATION_WINDOW.
The confirmation arriving -- by mail, by the extension reading the portal, by
the student saying so -- moves the application to CONFIRMED, and that alone
meets the expectation; this module never needs to be told.

Design: docs/superpowers/specs/2026-09-25-application-watch-design.md §1, §4.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.audit.views import OPEN_DELETION_STATES
from apps.concierge.models import Notification, RoadmapItem
from apps.portals.models import Application, ApplicationStep
from apps.portals.reminders import held_for_quiet_hours
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

from .models import Expectation
from .rules import confirmation_due

logger = logging.getLogger(__name__)

#: RoadmapItem.deadline is NOT NULL. An application with no known deadline gets
#: this, so the card still sorts and still reads as due soon.
_NO_DEADLINE_HORIZON = timedelta(days=7)


def being_erased(student_field: str) -> Exists:
    """An open DeletionRequest for the student named by `student_field` on the
    outer queryset -- the same predicate as
    apps.tenancy.middleware.deletion_lock_target. Shared by watchdog and
    escalation so the lock is defined once."""
    return Exists(
        DeletionRequest.objects.filter(
            student=OuterRef(student_field), state__in=OPEN_DELETION_STATES
        )
    )


def watch_applications_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    """Raise every alert this tenant is owed. Returns how many were raised.

    One transaction per application, as the reminder ladder does: a failure on
    one must not roll back the alerts already recorded for the others.
    """
    moment = now or timezone.now()
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            submitted = list(
                Application.objects.filter(
                    state=Application.State.SUBMITTED, student__active=True
                )
                # Already alerted: nothing left to do, so not revisited hourly.
                # _watch_one's locked re-check stays the race guard.
                .exclude(expectations__alerted__isnull=False)
                # Being erased: locked out of the dashboard the alert points at.
                .exclude(being_erased("student"))
                .values_list("id", flat=True)
            )
        raised = 0
        for application_id in submitted:
            try:
                with tenant_transaction(tenant_id):
                    if _watch_one(application_id, moment):
                        raised += 1
            except Exception:
                logger.exception("WatchFailed application=%s", application_id)
        return raised


def _submitted_at(application: Application) -> datetime:
    """When the student pressed Submit, from the step ext_api.py records."""
    step_time = (
        ApplicationStep.objects.filter(
            application=application, kind=ApplicationStep.Kind.SUBMITTED
        )
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    return step_time or application.created_at


def _watch_one(application_id: UUID, moment: datetime) -> bool:
    # The listing ran in an earlier transaction; the state may have moved since.
    application = (
        Application.objects.select_related("student", "portal_form", "candidate")
        .filter(id=application_id, state=Application.State.SUBMITTED)
        .first()
    )
    if application is None:
        return False
    Expectation.objects.get_or_create(
        application=application,
        kind=Expectation.Kind.CONFIRMATION,
        defaults={
            "tenant": application.tenant,
            "due_at": confirmation_due(_submitted_at(application)),
        },
    )
    # Locked, then re-read: two overlapping sweeps both reaching here would
    # otherwise both see alerted=None and alert twice.
    expectation = Expectation.objects.select_for_update().get(
        application=application, kind=Expectation.Kind.CONFIRMATION
    )
    if expectation.alerted_id is not None or moment < expectation.due_at:
        return False
    if held_for_quiet_hours(application.student, moment):
        # Deferred, never skipped: nothing is recorded, so the next sweep
        # outside the window raises it.
        return False

    host = application.where
    note = Notification.raise_card(
        student=application.student,
        recipient=application.student,
        owner=application.student,
        stage=RoadmapItem.Stage.MONITORING,
        deadline=application.deadline or moment + _NO_DEADLINE_HORIZON,
        urgent=True,
        application=application,
        action=Notification.Action.OPEN_PORTAL,
        message=(
            f"We haven't seen a confirmation from {host} since you submitted. "
            f"Open your {host} portal and check your application arrived."
        ),
    )
    expectation.alerted = note
    expectation.save(update_fields=["alerted"])
    logger.info("ConfirmationOverdue application=%s portal=%s", application.id, host)
    return True
