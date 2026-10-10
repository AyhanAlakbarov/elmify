import pytest

pytestmark = pytest.mark.django_db


def test_field_map_current_returns_latest_unsuperseded_version():
    from apps.portals.models import FieldMap, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    old = FieldMap.objects.create(
        portal_form=form,
        version=1,
        entries=[
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#fn", "method": "fill", "arguments": ["%value%"]},
            }
        ],
    )
    old.supersede()
    current = FieldMap.objects.create(
        portal_form=form,
        version=2,
        entries=[
            {
                "profile_field": "personal.given_name",
                "action": {"selector": "#given", "method": "fill", "arguments": ["%value%"]},
            }
        ],
    )

    assert FieldMap.current_for(form, None) == current


def test_field_map_versions_are_unique_per_form():
    from django.db.utils import IntegrityError

    from apps.portals.models import FieldMap, PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="personal-details")
    FieldMap.objects.create(portal_form=form, version=1, entries=[])
    with pytest.raises(IntegrityError):
        FieldMap.objects.create(portal_form=form, version=1, entries=[])


def test_a_new_portal_form_is_silent_about_automation(db) -> None:
    """Default posture is SILENT, not permissive-by-omission and not blocking.

    A portal nobody has read the terms of must not block filling (that would
    stop every new portal) and must not be recorded as having been cleared.
    """
    from apps.portals.models import PortalForm

    form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="k1")

    assert form.terms_posture == PortalForm.TermsPosture.SILENT
    assert form.terms_url == ""
    assert form.terms_read_on is None


def test_terms_posture_rejects_a_value_outside_the_enum(db) -> None:
    from django.db.utils import IntegrityError

    from apps.portals.models import PortalForm

    with pytest.raises(IntegrityError):
        PortalForm.objects.create(
            portal_host="apply.example.edu", form_key="k2", terms_posture="MAYBE"
        )


def test_an_application_may_carry_a_deadline_in_the_portal_s_own_timezone(
    agency_a, membership_a
) -> None:
    """Stored in the portal's zone, shown in the student's.

    A deadline of "1 December" means midnight where the portal is, and a
    student in another country who reads it as their own midnight submits a
    day late.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from apps.portals.models import Application, PortalForm
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="deadline")
        application = Application.objects.create(
            tenant=agency_a,
            student=membership_a,
            program_id=uuid4(),
            portal_form=form,
            deadline=datetime(2026, 12, 1, 23, 59, tzinfo=UTC),
            deadline_timezone="Europe/Berlin",
        )
        application.refresh_from_db()

    assert application.deadline.year == 2026
    assert application.deadline_timezone == "Europe/Berlin"


def test_an_application_without_a_deadline_is_legal(agency_a, membership_a) -> None:
    """Most applications reach the pipeline before anyone has read a date off
    the programme's page. A required column would block the pipeline on the
    discovery gap rather than on anything about this application."""
    from uuid import uuid4

    from apps.portals.models import Application, PortalForm
    from apps.tenancy.context import tenant_scope

    with tenant_scope(agency_a.id):
        form = PortalForm.objects.create(portal_host="apply.example.edu", form_key="nodeadline")
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), portal_form=form
        )

    assert application.deadline is None
    assert application.deadline_timezone == ""


def test_every_step_kind_a_writer_uses_is_in_the_enum() -> None:
    """One list, so the events route cannot accept a kind the trail has no
    name for, and a reader of the §5.5 trail has somewhere to look."""
    from apps.portals.models import ApplicationStep

    assert set(ApplicationStep.Kind.values) == {
        "PACKET",
        "FILL",
        "READ_BACK",
        "CHALLENGE",
        "SUBMITTED",
        "STATUS",
        "SIGNUP",
        "VERIFY",
        "ESCALATION",
        "RECOVERY",
    }
