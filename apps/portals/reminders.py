"""The reminder ladder's decisions, with no database and no side effects.

Everything here is a pure function so the awkward parts -- a quiet window that
crosses midnight, a rung that opens while the student is asleep -- can be
tested without a tenant, a transaction or a clock.

Design: docs/superpowers/specs/2026-09-19-reminder-ladder-design.md
"""

from __future__ import annotations

import logging
from collections.abc import Container, Sequence
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone as dj_timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.privacy.requests import stopping_requests
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership

from .models import Application, ReminderSent, Rung

logger = logging.getLogger(__name__)

#: How long before the deadline each rung opens. §8's cadence; the 1-hour rung
#: was dropped deliberately -- a failed upload cannot be recovered in an hour.
RUNG_LEAD: dict[Rung, timedelta] = {
    Rung.D14: timedelta(days=14),
    Rung.D7: timedelta(days=7),
    Rung.D3: timedelta(days=3),
    Rung.D1: timedelta(days=1),
    Rung.H6: timedelta(hours=6),
}

#: The rungs that also open a counselor task. Owner decision 2026-09-19, moved
#: in from §8's 3 days: three days out an automated reminder still has room to
#: work, inside 24 hours it does not.
COUNSELOR_RUNGS = frozenset({Rung.D1, Rung.H6})


def due_rungs(deadline: datetime, now: datetime) -> tuple[Rung, ...]:
    """Every rung whose lead time has been reached, widest first.

    Empty once the deadline has passed: "your deadline is in 6 hours" sent
    afterwards is worse than silence, and a missed-deadline notice is a
    different feature nobody has asked for.
    """
    if now >= deadline:
        return ()
    remaining = deadline - now
    return tuple(rung for rung in Rung if remaining <= RUNG_LEAD[rung])


def owed_rung(due: Sequence[Rung], already_sent: Container[Rung]) -> Rung | None:
    """The tightest due rung not yet sent, or None.

    Tightest rather than widest so an application that appears five days
    before its deadline gets one message saying five days, not a burst of
    every rung it slept through. The sweep records the whole `due` set as
    sent, so the ones passed over never fire later.
    """
    outstanding = [rung for rung in due if rung not in already_sent]
    return outstanding[-1] if outstanding else None


def in_quiet_hours(local: time, start: time | None, end: time | None) -> bool:
    """Whether `local` falls in the student's quiet window.

    A window normally crosses midnight (22:00-07:00), for which the test is
    `local >= start or local <= end`. The plain `start <= local <= end` is
    empty for every window anyone would actually set, which is the bug this
    function exists to not have.
    """
    if start is None or end is None:
        return False
    if start <= end:
        return start <= local <= end
    return local >= start or local <= end


def remaining_phrase(remaining: timedelta) -> str:
    """How long is left, in the units a person would say it in."""
    hours = int(remaining.total_seconds() // 3600)
    if hours >= 48:
        return f"{hours // 24} days"
    return f"{hours} hours"


def reminder_item(application: Application) -> RoadmapItem:
    """The roadmap item every rung's notification hangs on, created on demand.

    One per application rather than one per rung: Notification.roadmap_item is
    not nullable, and five items for five reminders about one deadline is five
    rows on the dashboard saying the same thing. Its deadline is the portal's,
    so RoadmapItem.deadline_urgency colours it without the ladder saying
    anything.
    """
    if application.reminder_item is not None:
        return application.reminder_item
    # The ladder never calls this for a deadline-less application -- due_rungs
    # returns empty without one -- so this narrows the nullable FK for mypy
    # rather than guarding a real runtime case.
    assert application.deadline is not None
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=RoadmapItem.Stage.SUBMISSION,
        owner=application.student,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=application.deadline,
    )
    application.reminder_item = item
    application.save(update_fields=["reminder_item"])
    return item


def notify_student(
    application: Application, item: RoadmapItem, remaining: timedelta
) -> Notification:
    """Tell the student how long is left and where."""
    return Notification.objects.create(
        tenant=application.tenant,
        recipient=application.student,
        roadmap_item=item,
        message=(
            f"{application.where}: your application is due in "
            f"{remaining_phrase(remaining)}."
        ),
    )


def _assigned_counselor(student: Membership) -> Membership | None:
    assignment = (
        CounselorAssignment.objects.filter(student=student, active=True)
        .select_related("counselor")
        .first()
    )
    return assignment.counselor if assignment is not None else None


def notify_counselor(
    application: Application, item: RoadmapItem, remaining: timedelta
) -> Notification | None:
    """Ask the counselor to reach the student on WhatsApp, or nobody.

    Returns None for a direct-to-student account, which has no counselor. That
    is the correct outcome and not a configuration error -- unlike
    escalation.py, which falls back to the student, because an escalation must
    reach somebody and this is a second copy of a message the student already
    has.
    """
    counselor = _assigned_counselor(application.student)
    if counselor is None:
        return None
    return Notification.objects.create(
        tenant=application.tenant,
        recipient=counselor,
        roadmap_item=item,
        message=(
            f"{application.where}: due in {remaining_phrase(remaining)}. "
            "Message this student on WhatsApp now -- email will not reach them in time."
        ),
    )


def email_student(application: Application, remaining: timedelta) -> bool:
    """Mail the student, or say why not. True when a message was handed off.

    Two ways to decline, both ordinary rather than exceptional: the channel is
    unconfigured (no sending domain exists yet), or the student has no
    confirmed address. Neither fails the sweep -- the dashboard rung has
    already fired, and a reminder is not worth stranding a tenant's whole run.
    """
    if not settings.REMINDER_EMAIL_FROM:
        logger.info("ReminderEmailSkipped reason=unconfigured application=%s", application.id)
        return False
    address = application.student.application_email
    if not address:
        # Deliberately no fallback to user.email: that address is signup and
        # login only (Membership.application_email's own docstring), and
        # publishing the login address is how replies go where nothing watches.
        logger.info("ReminderEmailSkipped reason=no_address application=%s", application.id)
        return False
    phrase = remaining_phrase(remaining)
    host = application.where
    send_mail(
        subject=f"Your application on {host} is due in {phrase}",
        message=(
            f"Your application on {host} is due in {phrase}.\n\n"
            "Open your dashboard to finish and submit it."
        ),
        from_email=settings.REMINDER_EMAIL_FROM,
        recipient_list=[address],
    )
    return True


#: An application is reminded only while it is one of these -- still being
#: worked on. An allowlist rather than a blocklist of the finished/blocked
#: states on purpose: this module is not one of the two ext_api.py/models.py
#: allows to name the submitted state (tests/portals/test_boundary.py's
#: test_nothing_in_the_app_can_submit), and a BLOCKED_* one is already
#: waiting on a human through escalation.py, where telling the student to
#: hurry is noise aimed at someone who cannot act.
_ACTIVE_STATES = frozenset({Application.State.PREPARING, Application.State.READY_TO_SUBMIT})


def held_for_quiet_hours(student: Membership, now: datetime) -> bool:
    """Whether this student is inside their own night.

    No zone means no quiet hours and the rung fires on time. Degrading the
    other way -- holding until a zone is known -- drops reminders silently,
    which is the failure this whole ladder exists to prevent.
    """
    if not student.timezone:
        return False
    local = now.astimezone(ZoneInfo(student.timezone)).time()
    return in_quiet_hours(local, student.quiet_hours_start, student.quiet_hours_end)


def send_due_reminders_for_tenant(tenant_id: UUID, *, now: datetime | None = None) -> int:
    """Remind every application in one tenant that has a rung owed.

    One transaction per application, never one per tenant: a failure on the
    fortieth student must not roll back the thirty-nine ReminderSent rows
    already written, or every one of them sends again on the next sweep.
    """
    moment = now or dj_timezone.now()
    # tenant_scope sets the contextvar TenantManager filters on; tenant_transaction
    # (inside it, per query) sets the RLS GUC. Both are required -- the manager and
    # the policy are the two independent filters CLAUDE.md's RLS section describes,
    # and this sweep is not a request path so nothing else has set either one.
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            due_ids = list(
                Application.objects.filter(
                    deadline__isnull=False,
                    state__in=_ACTIVE_STATES,
                    student__active=True,
                )
                # Exists, not a join through privacy_requests: a join repeats an
                # application once per request row, and a multi-valued exclude()
                # does not bind its two conditions to the same request.
                .exclude(Exists(stopping_requests().filter(student=OuterRef("student"))))
                .values_list("id", flat=True)
            )

        reminded = 0
        for application_id in due_ids:
            try:
                with tenant_transaction(tenant_id):
                    if _remind_one(application_id, moment):
                        reminded += 1
            except Exception:
                # Per application, so one bad row does not strand the tenant. The
                # next sweep retries it: nothing was recorded as sent.
                logger.exception("ReminderFailed application=%s", application_id)
        return reminded


def _remind_one(application_id: UUID, moment: datetime) -> bool:
    application = (
        Application.objects.select_related("student", "portal_form", "candidate", "reminder_item")
        .filter(id=application_id)
        .first()
    )
    if application is None or application.deadline is None:
        return False
    due = due_rungs(application.deadline, moment)
    if not due:
        return False
    already = {
        Rung(value)
        for value in ReminderSent.objects.filter(application=application).values_list(
            "rung", flat=True
        )
    }
    rung = owed_rung(due, already)
    if rung is None:
        return False
    if held_for_quiet_hours(application.student, moment):
        # Deferred, never skipped: nothing is recorded, so the next sweep
        # outside the window picks the same rung up. Owner decision,
        # 2026-09-19: this holds even for H6, the last rung -- if a
        # student's quiet window covers their own deadline, that final
        # reminder can lose its only remaining chance to fire and never
        # go out. Accepted deliberately: quiet hours are honoured without
        # exception, not "unless it's urgent".
        return False

    remaining = application.deadline - moment
    # Written before any notification is sent, and without ignore_conflicts:
    # two overlapping sweeps (EventBridge is at-least-once) can both read
    # "unsent" before either write lands, so the write itself is the race's
    # decision point. The loser's bulk_create raises IntegrityError on the
    # unique constraint, which rolls back this whole per-application
    # transaction -- including any notification calls below that already ran
    # -- and the caller's per-application try/except logs it and retries next
    # sweep. Every due rung, not just the one sent: an application that
    # appears five days before its deadline has slept through D14 and D7, and
    # recording them is what stops them firing later as stale news.
    ReminderSent.objects.bulk_create(
        [
            ReminderSent(
                tenant=application.tenant,
                application=application,
                rung=value,
                sent=(value == rung),
            )
            for value in due
            if value not in already
        ]
    )
    item = reminder_item(application)
    notify_student(application, item, remaining)
    email_student(application, remaining)
    if rung in COUNSELOR_RUNGS:
        notify_counselor(application, item, remaining)
    logger.info(
        "ReminderSent rung=%s application=%s portal=%s",
        rung.value,
        application.id,
        application.where,
    )
    return True


#: How long after the application deadline to ask for an unrecorded decision (R3),
#: countering winner-only self-reporting bias in `OutcomeSource.PERSON`.
POST_DEADLINE_OUTCOME_CHECKIN_DELAY = timedelta(days=14)
#: Second post-deadline follow-up when the first check-in was acknowledged without an outcome.
POST_DEADLINE_FOLLOWUP_CHECKIN_DELAY = timedelta(days=45)
_OUTCOME_CHECKIN_PREFIX = "Have you heard back from "


def email_outcome_checkin(application: Application) -> bool:
    """Mail the student asking whether a decision has arrived for a past-deadline application."""
    if not settings.REMINDER_EMAIL_FROM:
        return False
    address = application.student.application_email
    if not address:
        return False
    host = application.where
    send_mail(
        subject=f"Have you heard back about {application.title}?",
        message=(
            f"Have you heard back from {host} about {application.title}?\n\n"
            "Open your dashboard to record the decision on your board so your plan stays accurate."
        ),
        from_email=settings.REMINDER_EMAIL_FROM,
        recipient_list=[address],
    )
    return True


def send_due_outcome_checkins_for_tenant(
    tenant_id: UUID, *, now: datetime | None = None
) -> int:
    """Ask students (and assigned counselors) to record decisions for past-deadline applications.

    Targets applications that have moved past preparation (`_ACTIVE_STATES`) and are not
    in a `BLOCKED_*` escalation state, whose deadline passed at least
    `POST_DEADLINE_OUTCOME_CHECKIN_DELAY` ago (or whose `deadline` is missing and `started_at`
    is at least `POST_DEADLINE_FOLLOWUP_CHECKIN_DELAY` ago), and that still have no recorded
    `outcome` or `decision_available_at`. Sends an initial check-in and at most one `+45d`
    follow-up if the first check-in was acknowledged while the decision remained pending.
    """
    moment = now or dj_timezone.now()
    cutoff = moment - POST_DEADLINE_OUTCOME_CHECKIN_DELAY
    no_deadline_cutoff = moment - POST_DEADLINE_FOLLOWUP_CHECKIN_DELAY
    with tenant_scope(tenant_id):
        with tenant_transaction(tenant_id):
            due_ids = list(
                Application.objects.filter(
                    Q(deadline__isnull=False, deadline__lte=cutoff)
                    | Q(
                        deadline__isnull=True,
                        started_at__isnull=False,
                        started_at__lte=no_deadline_cutoff,
                    ),
                    Q(outcome="", decision_available_at__isnull=True)
                    | Q(
                        outcome__in=(
                            Application.Outcome.ADMITTED,
                            Application.Outcome.ADMITTED_CONDITIONAL,
                        ),
                        funding_outcome="",
                        candidate__estimated_funded_chance_pct__isnull=False,
                    ),
                    student__active=True,
                )
                .exclude(state__in=_ACTIVE_STATES)
                .exclude(state__startswith="BLOCKED_")
                .exclude(Exists(stopping_requests().filter(student=OuterRef("student"))))
                .exclude(
                    Exists(
                        Notification.objects.filter(
                            application=OuterRef("pk"),
                            roadmap_item__stage=RoadmapItem.Stage.MONITORING,
                            message__startswith=_OUTCOME_CHECKIN_PREFIX,
                            acknowledged_at__isnull=True,
                        )
                    )
                )
                .values_list("id", flat=True)
            )

        checked_in = 0
        for application_id in due_ids:
            try:
                with tenant_transaction(tenant_id):
                    if _checkin_one(application_id, moment):
                        checked_in += 1
            except Exception:
                logger.exception("OutcomeCheckinFailed application=%s", application_id)
        return checked_in


def _checkin_one(application_id: UUID, moment: datetime) -> bool:
    application = (
        Application.objects.select_for_update(of=("self",))
        .select_related("student", "portal_form", "candidate")
        .filter(id=application_id)
        .first()
    )
    if (
        application is None
        or application.state in _ACTIVE_STATES
        or application.state.startswith("BLOCKED_")
    ):
        return False
    needs_admission_checkin = (
        not application.outcome and application.decision_available_at is None
    )
    needs_bundled_funding_checkin = (
        application.outcome
        in (Application.Outcome.ADMITTED, Application.Outcome.ADMITTED_CONDITIONAL)
        and not application.funding_outcome
        and application.candidate is not None
        and application.candidate.estimated_funded_chance_pct is not None
    )
    if not needs_admission_checkin and not needs_bundled_funding_checkin:
        return False
    existing_checkins = list(
        Notification.objects.filter(
            application=application,
            roadmap_item__stage=RoadmapItem.Stage.MONITORING,
            message__startswith=_OUTCOME_CHECKIN_PREFIX,
        )
    )
    if any(n.acknowledged_at is None for n in existing_checkins) or len(existing_checkins) >= 2:
        return False
    is_followup = len(existing_checkins) == 1 or needs_bundled_funding_checkin
    if application.deadline is not None:
        required_delay = (
            POST_DEADLINE_FOLLOWUP_CHECKIN_DELAY
            if is_followup
            else POST_DEADLINE_OUTCOME_CHECKIN_DELAY
        )
        if application.deadline > moment - required_delay:
            return False
    else:
        if application.started_at is None:
            return False
        required_delay = (
            POST_DEADLINE_FOLLOWUP_CHECKIN_DELAY * 2
            if is_followup
            else POST_DEADLINE_FOLLOWUP_CHECKIN_DELAY
        )
        if application.started_at > moment - required_delay:
            return False
    if held_for_quiet_hours(application.student, moment):
        return False

    checkin_deadline = moment + timedelta(days=7)
    Notification.raise_card(
        student=application.student,
        recipient=application.student,
        stage=RoadmapItem.Stage.MONITORING,
        deadline=checkin_deadline,
        owner=application.student,
        application=application,
        action=Notification.Action.OPEN_PORTAL if application.portal_form_id else "",
        message=(
            f"Have you heard back from {application.where} about {application.title}? "
            "Record the decision on your board so your plan stays accurate."
        ),
    )
    if (counselor := _assigned_counselor(application.student)) is not None:
        Notification.raise_card(
            student=application.student,
            recipient=counselor,
            stage=RoadmapItem.Stage.MONITORING,
            deadline=checkin_deadline,
            owner=counselor,
            application=application,
            message=(
                f"{application.where} ({application.title}): deadline passed without a recorded "
                "decision. Check in with this student and record the outcome on their board."
            ),
        )
    email_outcome_checkin(application)
    logger.info(
        "OutcomeCheckinSent application=%s portal=%s",
        application.id,
        application.where,
    )
    return True
