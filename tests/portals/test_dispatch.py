"""Completion detection without a hook inside the concierge app.

Mirrors apps/research/dispatch.py::recover_undispatched_runs: the worker loop
polls for work a human has finished, so marking a roadmap item done stays an
ordinary concierge action with no automation reaching into it.
"""

from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _blocked_application(agency, student, *, item_state):
    from apps.concierge.models import RoadmapItem
    from apps.portals.models import Application, PortalForm

    form = PortalForm.objects.create(
        portal_host="apply.example.edu", form_key=f"personal-details-{uuid4()}"
    )
    item = RoadmapItem.objects.create(
        tenant=agency,
        student=student,
        stage=RoadmapItem.Stage.PORTAL_EXCEPTION,
        owner=student,
        deadline=timezone.now() + timedelta(days=1),
        state=item_state,
    )
    return Application.objects.create(
        tenant=agency,
        student=student,
        program_id=uuid4(),
        portal_form=form,
        state=Application.State.BLOCKED_CHALLENGE,
        exception_item=item,
    )


def test_a_finished_consultant_task_enqueues_a_resume(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_completed_exceptions
    from apps.portals.models import Application

    client = Mock()
    with tenant_scope(agency_a.id):
        application = _blocked_application(
            agency_a, membership_a, item_state=RoadmapItem.State.DONE
        )

    assert resume_completed_exceptions(client=client, queue_url="q") == 1

    body = client.send_message.call_args.kwargs["MessageBody"]
    assert str(application.id) in body
    assert "resume_application" in body
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.state == Application.State.PREPARING
        assert application.exception_item_id is None


def test_an_open_consultant_task_is_left_alone(agency_a, membership_a):
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_completed_exceptions

    client = Mock()
    with tenant_scope(agency_a.id):
        _blocked_application(agency_a, membership_a, item_state=RoadmapItem.State.PENDING)

    assert resume_completed_exceptions(client=client, queue_url="q") == 0
    client.send_message.assert_not_called()


def test_one_failed_enqueue_does_not_stop_the_rest_of_the_batch(agency_a, membership_a):
    """Each application dispatches in its own transaction: a raise on one
    enqueue must not roll back a sibling's already-flipped state, must not
    re-enqueue it, and must not propagate out of resume_completed_exceptions."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_completed_exceptions
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        boom = _blocked_application(agency_a, membership_a, item_state=RoadmapItem.State.DONE)
        fine = _blocked_application(agency_a, membership_a, item_state=RoadmapItem.State.DONE)

    client = Mock()

    def send_message(**kwargs: str) -> object:
        if str(boom.id) in kwargs["MessageBody"]:
            raise RuntimeError("SQS is down")
        return Mock()

    client.send_message.side_effect = send_message

    assert resume_completed_exceptions(client=client, queue_url="q") == 1

    with tenant_scope(agency_a.id):
        boom.refresh_from_db()
        fine.refresh_from_db()
        assert boom.state == Application.State.BLOCKED_CHALLENGE
        assert boom.exception_item_id is not None
        assert fine.state == Application.State.PREPARING
        assert fine.exception_item_id is None


def test_a_failed_tenant_does_not_block_a_second_tenants_resume(
    agency_a, membership_a, agency_b, membership_b
):
    """One tenant's dispatch failure must not abort another tenant's batch --
    each tenant's applications are dispatched independently."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_completed_exceptions
    from apps.portals.models import Application

    with tenant_scope(agency_a.id):
        boom = _blocked_application(agency_a, membership_a, item_state=RoadmapItem.State.DONE)
    with tenant_scope(agency_b.id):
        fine = _blocked_application(agency_b, membership_b, item_state=RoadmapItem.State.DONE)

    client = Mock()

    def send_message(**kwargs: str) -> object:
        if str(boom.id) in kwargs["MessageBody"]:
            raise RuntimeError("SQS is down")
        return Mock()

    client.send_message.side_effect = send_message

    assert resume_completed_exceptions(client=client, queue_url="q") == 1

    with tenant_scope(agency_a.id):
        boom.refresh_from_db()
        assert boom.state == Application.State.BLOCKED_CHALLENGE
    with tenant_scope(agency_b.id):
        fine.refresh_from_db()
        assert fine.state == Application.State.PREPARING


def test_the_recheck_rejects_an_item_that_left_done_between_select_and_dispatch(
    agency_a, membership_a
):
    """resume_application is the recheck: called directly (not through the
    batch) against an application whose roadmap item is no longer DONE, it
    must refuse to resume -- covering the whole select predicate, not just
    the state half of it."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_application
    from apps.portals.models import Application

    client = Mock()
    with tenant_scope(agency_a.id):
        application = _blocked_application(
            agency_a, membership_a, item_state=RoadmapItem.State.PENDING
        )

    assert (
        resume_application(
            tenant_id=agency_a.id, application_id=application.id, client=client, queue_url="q"
        )
        is False
    )

    client.send_message.assert_not_called()
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.state == Application.State.BLOCKED_CHALLENGE
        assert application.exception_item_id is not None


def test_a_portal_less_application_is_never_resumed_onto_the_portal_queue(
    agency_a, membership_a
):
    """The retiring worker asserts a portal; this is what makes that true."""
    from apps.concierge.models import RoadmapItem
    from apps.portals.dispatch import resume_application, resume_completed_exceptions
    from apps.portals.models import Application

    client = Mock()
    with tenant_scope(agency_a.id):
        application = _blocked_application(
            agency_a, membership_a, item_state=RoadmapItem.State.DONE
        )
        Application.objects.filter(id=application.id).update(portal_form=None)

    assert resume_completed_exceptions(client=client, queue_url="q") == 0
    assert not resume_application(
        tenant_id=agency_a.id, application_id=application.id, client=client, queue_url="q"
    )
    client.send_message.assert_not_called()
