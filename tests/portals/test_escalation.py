"""Section 5.4's table is the whole escalation surface. These tests pin both
halves of that claim: every row escalates, and the table has no seventh row."""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    from apps.portals.models import Application, PortalForm

    # form_key varies: PortalForm has a unique (portal_host, form_key)
    # constraint and these helpers are called more than once per test.
    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_every_trigger_blocks_the_application_and_notifies_someone(agency_a, membership_a):
    from apps.concierge.models import Notification
    from apps.portals.escalation import BLOCKED_STATE, Trigger, escalate

    with tenant_scope(agency_a.id):
        for trigger in Trigger:
            application = _application(agency_a, membership_a)

            item = escalate(application, trigger, detail="because")

            application.refresh_from_db()
            assert application.state == BLOCKED_STATE[trigger], trigger
            assert application.exception_item_id == item.id
            assert Notification.objects.filter(recipient=item.owner).exists()
            step = application.steps.order_by("-sequence").first()
            assert step.kind == "ESCALATION"
            assert step.detail["trigger"] == trigger.value
            assert step.detail["detail"] == "because"


def test_the_trigger_table_is_exactly_section_54s_six_rows():
    """A seventh trigger is a product decision, not a refactor. If this fails,
    the requirements changed or something that recovers autonomously has been
    turned into a blocking escalation by accident."""
    from apps.portals.escalation import BLOCKED_STATE, Trigger

    assert [trigger.value for trigger in Trigger] == [
        "MISSING_FACT",
        "PERSONAL_ATTESTATION",
        "APPLICANT_MFA",
        "UNSOLVED_CHALLENGE",
        "AMBIGUOUS_DECISION",
        "PORTAL_ERROR",
    ]
    assert set(BLOCKED_STATE) == set(Trigger)


def test_only_the_two_personal_rows_reach_the_student(
    agency_a, membership_a, counselor_membership
):
    """§5.4 assigns everything else to the consultant desk. Sending a portal
    error to the student is not a smaller mistake than the reverse."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )

        personal = escalate(
            _application(agency_a, membership_a), Trigger.APPLICANT_MFA, detail="sms code"
        )
        portal = escalate(
            _application(agency_a, membership_a), Trigger.PORTAL_ERROR, detail="duplicate"
        )

        assert personal.owner_id == membership_a.id
        assert personal.stage == RoadmapItem.Stage.PERSONAL_ACTION
        assert portal.owner_id == counselor_membership.id
        assert portal.stage == RoadmapItem.Stage.APPLICATION_PREP


def test_a_challenge_escalation_uses_the_portal_exception_stage(
    agency_a, membership_a, counselor_membership
):
    """Spec design point 8: the dashboard requirement in §5.2 is already
    satisfied by the existing stages, so no new pause concept is introduced."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        item = escalate(
            _application(agency_a, membership_a), Trigger.UNSOLVED_CHALLENGE, detail="hcaptcha"
        )

        assert item.stage == RoadmapItem.Stage.PORTAL_EXCEPTION


def test_an_unassigned_student_still_reaches_a_human(agency_a, membership_a):
    """A missing CounselorAssignment is a tenancy configuration error. It must
    not silently swallow an escalation, and there is no third principal to
    fall back to, so the student is told."""
    from apps.portals.escalation import Trigger, escalate

    with tenant_scope(agency_a.id):
        item = escalate(_application(agency_a, membership_a), Trigger.PORTAL_ERROR, detail="x")

        assert item.owner_id == membership_a.id


def test_the_first_application_on_a_new_portal_asks_for_review_without_blocking(
    agency_a, membership_a, counselor_membership
):
    """§5.2 requires consultant review of the first prepared application on
    each portal. That is a review task, not an escalation: the application is
    ready, so its state must not move to a BLOCKED_* value."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.escalation import request_first_portal_review
    from apps.portals.models import Application
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)
        application.state = Application.State.READY_TO_SUBMIT
        application.save(update_fields=["state"])

        first = request_first_portal_review(application)
        application.refresh_from_db()

        assert first is not None
        assert first.stage == RoadmapItem.Stage.APPLICATION_PREP
        assert application.state == Application.State.READY_TO_SUBMIT
        assert application.portal_form.review_required is False

        # Second application on the same portal: the portal is no longer new.
        # (Built directly against application.portal_form, not via _application(),
        # which mints a fresh PortalForm -- and thus a fresh review_required --
        # on every call.)
        second = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=application.portal_form,
        )
        assert request_first_portal_review(second) is None
