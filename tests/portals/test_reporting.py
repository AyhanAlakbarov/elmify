from uuid import uuid4

import pytest

from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def test_the_rate_counts_escalated_applications_per_portal(
    agency_a, membership_a, counselor_membership
):
    from apps.portals.escalation import Trigger, escalate
    from apps.portals.models import Application, PortalForm
    from apps.portals.reporting import intervention_rates

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="slow.example.edu", form_key="f")
        applications = [
            Application.objects.create(
                tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
            )
            for _ in range(4)
        ]
        escalate(applications[0], Trigger.PORTAL_ERROR, detail="x")

    rates = {row.portal_host: row for row in intervention_rates()}

    assert rates["slow.example.edu"].applications == 4
    assert rates["slow.example.edu"].escalations == 1
    assert rates["slow.example.edu"].intervention_rate == 0.25


def test_recoveries_are_reported_but_are_not_interventions(agency_a, membership_a):
    """A recovery is the system working. Counting it as an intervention would
    make the autonomous path look like the expensive one."""
    from apps.portals.models import Application, PortalForm, RecoveryEvent
    from apps.portals.reporting import intervention_rates

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="drifty.example.edu", form_key="f")
        Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )
        RecoveryEvent.objects.create(
            portal_form=form, kind=RecoveryEvent.Kind.SELECTOR_MISS, detail={}
        )

    row = {r.portal_host: r for r in intervention_rates()}["drifty.example.edu"]
    assert (row.recoveries, row.escalations, row.intervention_rate) == (1, 0, 0.0)


def test_a_portal_with_no_applications_reports_a_zero_rate_not_a_crash(agency_a):
    from apps.portals.models import PortalForm
    from apps.portals.reporting import intervention_rates

    PortalForm.objects.create(portal_host="unused.example.edu", form_key="f")

    assert {r.portal_host: r.intervention_rate for r in intervention_rates()}[
        "unused.example.edu"
    ] == 0.0
