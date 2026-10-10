import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, ApplicationStep
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.watch.models import JobRun


def _overdue(agency, student, portal_form):
    application = Application.objects.create(
        tenant=agency,
        student=student,
        program_id=uuid.uuid4(),
        portal_form=portal_form,
        state="SUBMITTED",
    )
    step = ApplicationStep.objects.create(
        tenant=agency, application=application, sequence=1, kind="SUBMITTED"
    )
    ApplicationStep.objects.filter(pk=step.pk).update(
        created_at=timezone.now() - timedelta(hours=49)
    )


@pytest.mark.django_db
def test_the_command_watches_every_agency_and_records_its_run(
    agency_a, membership_a, agency_b, membership_b, portal_form
):
    with tenant_scope(agency_a.id):
        _overdue(agency_a, membership_a, portal_form)
    with tenant_scope(agency_b.id):
        _overdue(agency_b, membership_b, portal_form)

    call_command("watch_applications")

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
    with tenant_scope(agency_b.id):
        assert Notification.objects.filter(recipient=membership_b).count() == 1
    assert JobRun.objects.filter(name="watch_applications").exists()


@pytest.mark.django_db
def test_the_reminder_command_records_its_run_too(agency_a):
    call_command("send_due_reminders")
    assert JobRun.objects.filter(name="send_due_reminders").exists()


@pytest.mark.django_db(transaction=True)
def test_the_command_works_behind_real_row_level_security(
    agency_a, membership_a, portal_form, rls_enforced_orm
):
    """Run as a NOBYPASSRLS role, the production shape. The suite otherwise runs
    as a BYPASSRLS superuser, where a sweep that forgot its set_local_tenant
    still finds rows; in production that same sweep finds none, exits 0, and
    never alerts. This passes only if every query really runs inside
    tenant_transaction."""
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _overdue(agency_a, membership_a, portal_form)

    call_command("watch_applications")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1


@pytest.mark.django_db(transaction=True)
def test_escalation_reaches_the_counsellor_behind_real_row_level_security(
    settings, agency_a, user_a, membership_a, counselor_membership, rls_enforced_orm
):
    """The command test above only reaches level 0. This one climbs to level 2 as
    the NOBYPASSRLS role: the pending query's subqueries, the locked re-read,
    the assignment lookup and the counsellor's notification all have to run
    inside tenant_transaction, or production finds nothing and tells no one."""
    from django.core import mail

    from apps.concierge.models import RoadmapItem
    from apps.tenancy.models import CounselorAssignment

    settings.REMINDER_EMAIL_FROM = "alerts@example.test"
    user_a.email = "leyla@example.test"
    user_a.save(update_fields=["email"])
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.MONITORING,
            owner=membership_a,
            deadline=timezone.now() + timedelta(days=30),
        )
        note = Notification.objects.create(
            tenant=agency_a, recipient=membership_a, roadmap_item=item,
            message="TUM: act", urgent=True,
        )
        Notification.objects.filter(pk=note.pk).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

    call_command("watch_applications")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        note.refresh_from_db()
        assert note.escalation_level == 2
        assert Notification.objects.filter(recipient=counselor_membership).count() == 1
    assert [m.to for m in mail.outbox] == [["leyla@example.test"]]
