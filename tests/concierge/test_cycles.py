from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError

from apps.concierge.cycles import paid_cycle
from apps.concierge.models import StudentCycle
from apps.funding.models import AuditEvent
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
