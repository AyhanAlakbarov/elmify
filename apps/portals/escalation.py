"""The whole escalation surface: six triggers, and nothing else escalates.

Everything not in this table recovers on its own and is recorded as a
RecoveryEvent instead (apps/portals/recovery.py). The distinction is the
spec's, and it is the difference between a platform that notifies a human when
only a human can answer and one that queues work behind every hiccup.
"""

import logging
from datetime import timedelta
from enum import StrEnum

from django.utils import timezone

from apps.concierge.models import Notification, RoadmapItem
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import CounselorAssignment, Membership

from .models import Application, ApplicationStep

logger = logging.getLogger(__name__)


class Trigger(StrEnum):
    """One member per row of §5.4's table. Adding a member is a product
    decision that changes what the platform asks people to do."""

    MISSING_FACT = "MISSING_FACT"
    PERSONAL_ATTESTATION = "PERSONAL_ATTESTATION"
    APPLICANT_MFA = "APPLICANT_MFA"
    UNSOLVED_CHALLENGE = "UNSOLVED_CHALLENGE"
    AMBIGUOUS_DECISION = "AMBIGUOUS_DECISION"
    PORTAL_ERROR = "PORTAL_ERROR"


BLOCKED_STATE = {
    Trigger.MISSING_FACT: Application.State.BLOCKED_MISSING_FACT,
    Trigger.PERSONAL_ATTESTATION: Application.State.BLOCKED_PERSONAL_ACTION,
    Trigger.APPLICANT_MFA: Application.State.BLOCKED_PERSONAL_ACTION,
    Trigger.UNSOLVED_CHALLENGE: Application.State.BLOCKED_CHALLENGE,
    # Ambiguity is a missing fact seen from the agent's side: the answer is not
    # determined by anything verified. It is deliberately NOT a portal error --
    # nothing is broken, and routing it there would hide real portal failures
    # in a bucket full of judgement calls.
    Trigger.AMBIGUOUS_DECISION: Application.State.BLOCKED_MISSING_FACT,
    Trigger.PORTAL_ERROR: Application.State.BLOCKED_PORTAL_ERROR,
}

#: The two rows that require one specific human. §5.4 gives the rest to the
#: consultant desk, and a student asked to resolve a portal error has been
#: handed work the platform sold them out of.
STUDENT_TRIGGERS = frozenset({Trigger.PERSONAL_ATTESTATION, Trigger.APPLICANT_MFA})

STAGE = {
    Trigger.UNSOLVED_CHALLENGE: RoadmapItem.Stage.PORTAL_EXCEPTION,
    Trigger.PERSONAL_ATTESTATION: RoadmapItem.Stage.PERSONAL_ACTION,
    Trigger.APPLICANT_MFA: RoadmapItem.Stage.PERSONAL_ACTION,
}
DEFAULT_STAGE = RoadmapItem.Stage.APPLICATION_PREP

#: Three days is the desk's own SLA, deliberately not a read of the portal's
#: deadline -- Application.deadline and deadline_timezone exist and are
#: carried separately (apps/portals/packets.py), but a roadmap item's own
#: urgency is the desk's response time, not the programme's. deadline_urgency
#: will show it as DUE_SOON immediately, which is correct -- a blocked
#: application is urgent regardless of how far off the portal's deadline is.
ESCALATION_SLA = timedelta(days=3)


def _recipient(application: Application, trigger: Trigger) -> Membership:
    if trigger in STUDENT_TRIGGERS:
        return application.student
    assignment = (
        # active=True, not merely assigned: the model allows one *active*
        # counselor per student and keeps the inactive rows, so dropping the
        # filter can route an escalation to someone who has left the agency.
        CounselorAssignment.objects.filter(student=application.student, active=True)
        .select_related("counselor")
        .first()
    )
    # No assignment is a tenancy configuration error, not a reason to drop the
    # escalation. The student is the only other principal we know exists.
    return assignment.counselor if assignment else application.student


def escalate(application: Application, trigger: Trigger, *, detail: str) -> RoadmapItem:
    """Block the application, create the human's task, and tell them.

    ``detail`` is the specific missing fact or required action -- §5.4 requires
    the notification to carry it, because "the application is blocked" is not
    something anyone can act on.
    """
    with tenant_transaction(application.tenant_id):
        return _escalate(application, trigger, detail=detail)


def _escalate(application: Application, trigger: Trigger, *, detail: str) -> RoadmapItem:
    recipient = _recipient(application, trigger)
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=STAGE.get(trigger, DEFAULT_STAGE),
        owner=recipient,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=timezone.now() + ESCALATION_SLA,
    )
    ApplicationStep.objects.create(
        tenant=application.tenant,
        application=application,
        sequence=application.next_step_sequence(),
        kind="ESCALATION",
        detail={"trigger": trigger.value, "detail": detail, "roadmap_item": str(item.id)},
    )
    application.state = BLOCKED_STATE[trigger]
    application.exception_item = item
    application.save(update_fields=["state", "exception_item"])
    Notification.objects.create(
        tenant=application.tenant,
        recipient=recipient,
        roadmap_item=item,
        message=f"{application.where}: {trigger.value} -- {detail}",
    )
    # Watched by PortalEscalationFilter (infra/template.yaml). The alarm is on
    # the rate: escalations are expected, a spike in them is not.
    logger.info(
        "PortalEscalation trigger=%s application=%s portal=%s",
        trigger.value,
        application.id,
        application.where,
    )
    return item


def request_first_portal_review(application: Application) -> RoadmapItem | None:
    """§5.2's first-application review. Returns None once the portal is known.

    Not an escalation: the application is prepared and stays prepared. The
    consultant is asked to look at it, not to unblock it, so no state moves and
    exception_item is left alone.
    """
    portal_form = application.portal_form
    if portal_form is None or not portal_form.review_required:
        return None
    with tenant_transaction(application.tenant_id):
        return _request_first_portal_review(application)


def _request_first_portal_review(application: Application) -> RoadmapItem:
    portal_form = application.portal_form
    assert portal_form is not None  # request_first_portal_review returned None for it
    recipient = _recipient(application, Trigger.AMBIGUOUS_DECISION)
    item = RoadmapItem.objects.create(
        tenant=application.tenant,
        student=application.student,
        stage=DEFAULT_STAGE,
        owner=recipient,
        owner_kind=RoadmapItem.OwnerKind.HUMAN,
        deadline=timezone.now() + ESCALATION_SLA,
    )
    Notification.objects.create(
        tenant=application.tenant,
        recipient=recipient,
        roadmap_item=item,
        message=(
            f"First prepared application on {portal_form.portal_host} -- "
            "review before it is submitted."
        ),
    )
    # PortalForm is platform-shared, so the first review covers every tenant.
    # That is the same amortisation argument as FieldMap: the form is public
    # and nothing about the review is tenant-specific.
    portal_form.review_required = False
    portal_form.save(update_fields=["review_required"])
    return item
