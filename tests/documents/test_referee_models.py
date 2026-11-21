"""Referee and RefereeRequest: row-level security, the tenant-composite FKs, erasure."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.audit.redaction import redact_student
from apps.documents.models import Referee, RefereeRequest
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


def _referee(agency, student, **extra):
    return Referee.objects.create(
        tenant=agency, student=student, name="Rauf Aliyev", title="Prof.",
        institution="ADA University", email="raliyev@ada.edu.az", institutional_email=True,
        relationship="Supervised my thesis on graph search.", agreed_requests=3, **extra,
    )


def _application(agency, student):
    return Application.objects.create(tenant=agency, student=student, program_id=uuid4())


@pytest.mark.django_db(transaction=True)
def test_another_tenant_sees_no_referee_and_no_request(
    agency_a, agency_b, membership_a, rls_enforced_orm
):
    # _base_manager skips the ORM's tenant filter, so only Postgres RLS filters.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        referee = _referee(agency_a, membership_a)
        RefereeRequest.objects.create(
            tenant=agency_a, referee=referee, application=_application(agency_a, membership_a)
        )
        assert Referee._base_manager.count() == 1
        assert RefereeRequest._base_manager.count() == 1
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert Referee._base_manager.count() == 0
        assert RefereeRequest._base_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_a_request_for_another_tenants_application_is_refused(
    agency_a, agency_b, membership_a, membership_b
):
    with tenant_scope(agency_b.id):
        theirs = _application(agency_b, membership_b)
    with pytest.raises(IntegrityError), transaction.atomic(), tenant_scope(agency_a.id):
        RefereeRequest.objects.create(
            tenant=agency_a, referee=_referee(agency_a, membership_a), application=theirs
        )


@pytest.mark.django_db
def test_an_unknown_state_is_refused_by_the_database(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        referee = _referee(agency_a, membership_a)
        with pytest.raises(IntegrityError), transaction.atomic():
            Referee.objects.filter(id=referee.id).update(status="GHOSTED")


@pytest.mark.django_db
def test_erasure_blanks_the_professor_and_keeps_the_plan_shape(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        referee = _referee(agency_a, membership_a)
        request = RefereeRequest.objects.create(
            tenant=agency_a, referee=referee, application=_application(agency_a, membership_a),
            state=RefereeRequest.State.ASKED,
        )
        redact_student(tenant_id=agency_a.id, student_id=membership_a.id)
        referee.refresh_from_db()
        request.refresh_from_db()
    assert (referee.name, referee.title, referee.institution, referee.email) == ("", "", "", "")
    assert referee.relationship == ""
    assert (referee.agreed_requests, request.state) == (3, "ASKED")


@pytest.mark.django_db
def test_a_professor_with_a_request_cannot_be_deleted(agency_a, membership_a):
    """A professor is marked declined or silent, never deleted: an ASKED letter
    must not vanish with them."""
    from django.db.models import ProtectedError

    with tenant_scope(agency_a.id):
        referee = _referee(agency_a, membership_a)
        RefereeRequest.objects.create(
            tenant=agency_a, referee=referee, application=_application(agency_a, membership_a),
            state=RefereeRequest.State.ASKED,
        )
        with pytest.raises(ProtectedError):
            referee.delete()
        assert RefereeRequest.objects.filter(referee=referee).count() == 1
