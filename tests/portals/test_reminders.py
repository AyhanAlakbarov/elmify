import uuid
from datetime import UTC, datetime

from apps.concierge.models import Notification
from apps.portals.models import Application, PortalForm, ReminderSent, Rung
from apps.portals.reminders import (
    send_due_outcome_checkins_for_tenant,
    send_due_reminders_for_tenant,
)
from apps.tenancy.context import tenant_scope


def test_regular_programme_card_with_route_snapshot_deadline_receives_reminders(
    agency_a, membership_a
) -> None:
    moment = datetime(2027, 1, 12, 12, 0, tzinfo=UTC)
    with tenant_scope(agency_a.id):
        portal_form = PortalForm.objects.create(
            portal_host="portal.tum.de", form_key="apply"
        )
        application = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            deadline=None,
            route_snapshot={
                "source": "CATALOGUE",
                "steps": [
                    {
                        "position": 1,
                        "purpose": "APPLY",
                        "channel": "PORTAL",
                        "dates": [
                            {
                                "role": "FINAL",
                                "date": "2027-01-15",
                                "timezone": "UTC",
                            }
                        ],
                    }
                ],
            },
        )

    assert send_due_reminders_for_tenant(agency_a.id, now=moment) == 1

    with tenant_scope(agency_a.id):
        application.refresh_from_db()
        assert application.reminder_item is not None
        assert application.reminder_item.deadline == datetime(
            2027, 1, 15, 23, 59, tzinfo=UTC
        )
        assert Notification.objects.filter(recipient=membership_a).count() == 1
        assert set(
            ReminderSent.objects.filter(application=application).values_list(
                "rung", flat=True
            )
        ) == {Rung.D14, Rung.D7}


def test_rolling_route_snapshot_with_no_deadline_is_not_reminded(
    agency_a, membership_a
) -> None:
    moment = datetime(2027, 1, 12, 12, 0, tzinfo=UTC)
    with tenant_scope(agency_a.id):
        portal_form = PortalForm.objects.create(
            portal_host="portal.tum.de", form_key="apply-rolling"
        )
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            deadline=None,
            route_snapshot={
                "source": "CATALOGUE",
                "steps": [
                    {
                        "position": 1,
                        "purpose": "APPLY",
                        "channel": "PORTAL",
                        "dates": [{"role": "ROLLING", "date": "", "timezone": ""}],
                    }
                ],
            },
        )

    assert send_due_reminders_for_tenant(agency_a.id, now=moment) == 0


def test_decided_or_withdrawn_application_in_preparing_state_is_not_reminded(
    agency_a, membership_a
) -> None:
    moment = datetime(2027, 1, 12, 12, 0, tzinfo=UTC)
    with tenant_scope(agency_a.id):
        portal_form = PortalForm.objects.create(
            portal_host="portal.tum.de", form_key="apply-withdrawn"
        )
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            state=Application.State.PREPARING,
            outcome=Application.Outcome.WITHDRAWN,
            deadline=datetime(2027, 1, 15, 23, 59, tzinfo=UTC),
        )

    assert send_due_reminders_for_tenant(agency_a.id, now=moment) == 0


def test_post_deadline_outcome_checkin_uses_effective_deadline_from_route_snapshot(
    agency_a, membership_a
) -> None:
    moment = datetime(2027, 2, 1, 12, 0, tzinfo=UTC)
    with tenant_scope(agency_a.id):
        portal_form = PortalForm.objects.create(
            portal_host="portal.tum.de", form_key="apply-checkin-route"
        )
        Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid.uuid4(),
            portal_form=portal_form,
            state=Application.State.CONFIRMED,
            deadline=None,
            started_at=None,
            route_snapshot={
                "source": "CATALOGUE",
                "steps": [
                    {
                        "position": 1,
                        "purpose": "APPLY",
                        "channel": "PORTAL",
                        "dates": [
                            {
                                "role": "FINAL",
                                "date": "2027-01-15",
                                "timezone": "UTC",
                            }
                        ],
                    }
                ],
            },
        )

    assert send_due_outcome_checkins_for_tenant(agency_a.id, now=moment) == 1
    with tenant_scope(agency_a.id):
        assert Notification.objects.filter(
            recipient=membership_a,
            message__startswith="Have you heard back from ",
        ).count() == 1
