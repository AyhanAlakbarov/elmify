import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.portals.models import Application, PortalForm, ReminderSent, Rung
from apps.tenancy.context import tenant_scope


@pytest.fixture
def portal_form(db):
    return PortalForm.objects.create(portal_host="portal.example.test", form_key="apply")


@pytest.fixture
def application(agency_a, membership_a, portal_form):
    with tenant_scope(agency_a.id):
        return Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
        )


def test_the_same_rung_cannot_be_recorded_twice(agency_a, application):
    with tenant_scope(agency_a.id):
        ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D7)
        with pytest.raises(IntegrityError), transaction.atomic():
            ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D7)


def test_two_different_rungs_on_one_application_are_fine(agency_a, application):
    with tenant_scope(agency_a.id):
        ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D7)
        ReminderSent.objects.create(tenant=agency_a, application=application, rung=Rung.D3)

        assert ReminderSent.objects.filter(application=application).count() == 2


def test_an_application_starts_with_no_reminder_item(application):
    assert application.reminder_item_id is None
