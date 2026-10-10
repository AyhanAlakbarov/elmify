import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.models import Notification
from apps.portals.models import Application, PortalForm
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


def _application(agency, student, portal_form):
    return Application.objects.create(
        tenant=agency,
        student=student,
        program_id=uuid.uuid4(),
        portal_form=portal_form,
        deadline=timezone.now() + timedelta(days=3, hours=1),
    )


def test_the_command_reminds_across_every_agency(
    agency_a, membership_a, agency_b, membership_b, portal_form
):
    """tenant_scope refuses to switch tenants, so a scope held across the loop
    raises on the second agency. This is the test that catches that."""
    with tenant_scope(agency_a.id):
        _application(agency_a, membership_a, portal_form)
    with tenant_scope(agency_b.id):
        _application(agency_b, membership_b, portal_form)

    call_command("send_due_reminders")

    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
    with tenant_scope(agency_b.id):
        assert Notification.objects.filter(recipient=membership_b).count() == 1


def test_the_command_is_quiet_when_nothing_is_due(agency_a):
    call_command("send_due_reminders")


@pytest.mark.django_db(transaction=True)
def test_the_sweep_works_behind_real_row_level_security(
    agency_a, membership_a, portal_form, rls_enforced_orm
):
    """The suite otherwise runs as a BYPASSRLS superuser, so a scan missing its
    set_local_tenant passes here and returns zero rows in production -- the
    command finds nothing, exits 0, and no reminder is ever sent.
    """
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _application(agency_a, membership_a, portal_form)

    call_command("send_due_reminders")

    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert Notification.objects.filter(recipient=membership_a).count() == 1
