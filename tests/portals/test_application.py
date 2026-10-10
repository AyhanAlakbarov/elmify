import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_application_starts_preparing(agency_a, membership_a):
    from uuid import uuid4

    from apps.portals.models import Application, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        assert application.state == Application.State.PREPARING


def test_application_steps_record_an_ordered_audit_trail(agency_a, membership_a):
    from uuid import uuid4

    from apps.portals.models import Application, ApplicationStep, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    with tenant_scope(agency_a.id):
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        ApplicationStep.objects.create(
            tenant=agency_a,
            application=application,
            sequence=1,
            kind="FILL",
            detail={"field": "personal.given_name"},
        )
        ApplicationStep.objects.create(
            tenant=agency_a,
            application=application,
            sequence=2,
            kind="READ_BACK",
            detail={"ok": True},
        )
        assert [s.sequence for s in application.steps.order_by("sequence")] == [1, 2]
