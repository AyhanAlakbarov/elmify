"""A notification must name the student it is about, not only its recipient.

Four of the six escalation triggers route to the assigned counselor, carrying
free text about the student. Without this link those messages are unfindable at
erasure: nothing in the row says whose data they hold.
"""

from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _application(agency, student):
    """Mirrors tests/portals/test_escalation.py::_application.

    form_key varies because PortalForm has a unique (portal_host, form_key)
    constraint and this helper is called more than once per test.
    """
    from apps.portals.models import Application, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    return Application.objects.create(
        tenant=agency, student=student, program_id=uuid4(), portal_form=form
    )


def test_counselor_bound_escalation_still_names_the_student(
    agency_a, membership_a, counselor_membership
):
    """MISSING_FACT routes to the counselor. The student must still be reachable."""
    from apps.concierge.models import Notification
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)

        escalate(application, Trigger.MISSING_FACT, detail="passport_number, date_of_birth")

        notification = Notification.objects.get()
        assert notification.recipient_id == counselor_membership.id, (
            "fixture is wrong: MISSING_FACT must route to the counselor for this "
            "test to mean anything"
        )
        assert notification.roadmap_item.student_id == membership_a.id


def test_student_bound_escalation_also_carries_the_link(
    agency_a, membership_a, counselor_membership
):
    """APPLICANT_MFA routes to the student. One path must cover both cases."""
    from apps.concierge.models import Notification
    from apps.portals.escalation import Trigger, escalate
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)

        escalate(application, Trigger.APPLICANT_MFA, detail="one-time code required")

        notification = Notification.objects.get()
        assert notification.recipient_id == membership_a.id
        assert notification.roadmap_item.student_id == membership_a.id


def test_the_first_portal_review_notification_also_carries_the_link(
    agency_a, membership_a, counselor_membership
):
    """The second writer. request_first_portal_review is not an escalation but
    creates a RoadmapItem and a Notification the same way."""
    from apps.concierge.models import Notification
    from apps.portals.escalation import request_first_portal_review
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        application = _application(agency_a, membership_a)
        application.portal_form.review_required = True
        application.portal_form.save(update_fields=["review_required"])

        request_first_portal_review(application)

        notification = Notification.objects.get()
        assert notification.roadmap_item.student_id == membership_a.id
