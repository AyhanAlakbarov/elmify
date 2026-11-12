from datetime import timedelta
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from apps.concierge.cycles import cycle_consumption_status, paid_cycle
from apps.concierge.models import StudentCycle
from apps.documents.models import DocumentDraft
from apps.funding.models import AuditEvent
from apps.portals.models import Application, ApplicationStep
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _mark(agency, membership, year="2026-2027"):
    out = StringIO()
    call_command(
        "mark_cycle_paid",
        tenant=str(agency.id),
        student=str(membership.id),
        academic_year=year,
        stdout=out,
    )
    return out.getvalue()


def test_no_cycle_means_unpaid(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        assert paid_cycle(membership_a.id) is None


def test_an_unpaid_cycle_row_is_still_unpaid(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")
        assert paid_cycle(membership_a.id) is None


def test_marking_a_cycle_paid_is_audited_and_found(agency_a, membership_a):
    assert "paid" in _mark(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        assert cycle is not None and cycle.academic_year == "2026-2027"
        assert cycle.pages_used == 0
        assert AuditEvent.objects.filter(event="cycle.marked_paid", object_id=cycle.id).count() == 1


def test_marking_twice_changes_nothing(agency_a, membership_a):
    _mark(agency_a, membership_a)
    assert "already paid" in _mark(agency_a, membership_a)
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(event="cycle.marked_paid").count() == 1


def test_the_newest_paid_cycle_wins(agency_a, membership_a):
    _mark(agency_a, membership_a, "2026-2027")
    _mark(agency_a, membership_a, "2027-2028")
    with tenant_scope(agency_a.id):
        assert paid_cycle(membership_a.id).academic_year == "2027-2028"


@pytest.mark.parametrize("year", ["2026", "2026-2028", "26-27", "2026/2027"])
def test_a_malformed_year_is_refused(agency_a, membership_a, year):
    with pytest.raises(CommandError):
        _mark(agency_a, membership_a, year)


def test_an_unknown_student_is_refused(agency_a):
    with pytest.raises(CommandError):
        call_command(
            "mark_cycle_paid",
            tenant=str(agency_a.id),
            student=str(uuid4()),
            academic_year="2026-2027",
            stdout=StringIO(),
        )


def test_one_cycle_per_student_and_year(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")
        with pytest.raises(IntegrityError):
            StudentCycle.objects.create(student=membership_a, academic_year="2026-2027")


def test_unpaid_cycle_consumption_status_shows_explore_preview(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        status = cycle_consumption_status(membership_a.id, None)
        assert not status.is_consumed
        assert not status.refund_eligible
        assert not status.rollover_eligible
        assert status.status_label == "Unpaid (Explore preview)"


def test_paid_unconsumed_cycle_within_7_days_is_refund_and_rollover_eligible(
    agency_a, membership_a
):
    _mark(agency_a, membership_a, "2026-2027")
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        # 1 base CV draft + 1 application kit stays within the unconsumed threshold (<= 1 kit)
        DocumentDraft.objects.create(
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content={},
            is_general=True,
        )
        Application.objects.create(student=membership_a, program_id=uuid4())
        status = cycle_consumption_status(membership_a.id, cycle)
        assert status.kits_count == 1
        assert status.exports_count == 0
        assert status.extension_sessions_count == 0
        assert not status.is_consumed
        assert status.refund_eligible
        assert status.rollover_eligible
        assert "Unconsumed 7-Day Preview Window" in status.status_label


def test_second_application_kit_marks_cycle_consumed_and_locks_refund(agency_a, membership_a):
    _mark(agency_a, membership_a, "2026-2027")
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        Application.objects.create(student=membership_a, program_id=uuid4())
        Application.objects.create(student=membership_a, program_id=uuid4())
        status = cycle_consumption_status(membership_a.id, cycle)
        assert status.kits_count == 2
        assert status.is_consumed
        assert not status.refund_eligible
        assert not status.rollover_eligible
        assert status.status_label == "Active & Consumed (Non-Refundable)"


def test_exported_pdf_draft_marks_cycle_consumed_and_locks_refund(agency_a, membership_a):
    _mark(agency_a, membership_a, "2026-2027")
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        DocumentDraft.objects.create(
            student=membership_a,
            kind=DocumentDraft.Kind.CV,
            version=1,
            content={},
            rendered_filename="cv-europass.pdf",
        )
        status = cycle_consumption_status(membership_a.id, cycle)
        assert status.exports_count == 1
        assert status.is_consumed
        assert not status.refund_eligible
        assert status.status_label == "Active & Consumed (Non-Refundable)"


def test_extension_autofill_step_marks_cycle_consumed_and_locks_refund(agency_a, membership_a):
    _mark(agency_a, membership_a, "2026-2027")
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        app = Application.objects.create(student=membership_a, program_id=uuid4())
        ApplicationStep.objects.create(
            application=app,
            sequence=1,
            kind=ApplicationStep.Kind.FILL,
            detail={"fields": 8},
        )
        status = cycle_consumption_status(membership_a.id, cycle)
        assert status.extension_sessions_count == 1
        assert status.is_consumed
        assert not status.refund_eligible
        assert status.status_label == "Active & Consumed (Non-Refundable)"


def test_unconsumed_cycle_past_7_days_closes_cash_refund_but_keeps_rollover(
    agency_a, membership_a
):
    _mark(agency_a, membership_a, "2026-2027")
    with tenant_scope(agency_a.id):
        cycle = paid_cycle(membership_a.id)
        later = cycle.paid_at + timedelta(days=8)
        status = cycle_consumption_status(membership_a.id, cycle, now=later)
        assert not status.is_consumed
        assert not status.refund_eligible
        assert status.rollover_eligible
        assert "7-Day Refund Window Closed · Rollover Eligible" in status.status_label
