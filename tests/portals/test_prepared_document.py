"""PreparedDocument: row-level security, the tenant-composite FKs, erasure."""

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.audit.redaction import redact_student
from apps.portals.models import Application, PreparedDocument
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction


def _row(agency, application, student, **extra):
    return PreparedDocument.objects.create(
        tenant=agency,
        application=application,
        student=student,
        slot="CV:1",
        document="CV",
        inputs_digest="d" * 64,
        state="READY",
        filename="Amina_Yusuf_CV.pdf",
        **extra,
    )


@pytest.fixture
def app_a(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        return Application.objects.create(tenant=agency_a, student=membership_a, program_id=uuid4())


@pytest.fixture
def app_b(agency_b, membership_b):
    with tenant_scope(agency_b.id):
        return Application.objects.create(tenant=agency_b, student=membership_b, program_id=uuid4())


def test_redaction_blanks_the_filename(agency_a, membership_a, app_a):
    with tenant_scope(agency_a.id):
        row = _row(agency_a, app_a, membership_a)
        redact_student(tenant_id=agency_a.id, student_id=membership_a.id)
        row.refresh_from_db()
        assert row.filename == "" and row.slot == "CV:1"


@pytest.mark.django_db(transaction=True)
def test_a_row_of_another_tenants_application_is_refused(
    agency_a, membership_a, app_b
):
    with pytest.raises(IntegrityError), transaction.atomic():
        with tenant_scope(agency_a.id):
            _row(agency_a, app_b, membership_a)


@pytest.mark.django_db(transaction=True)
def test_tenant_b_cannot_see_tenant_as_prepared_document(
    agency_a, agency_b, membership_a, app_a, rls_enforced_orm
):
    # _base_manager skips the ORM's tenant filter, so only Postgres RLS filters.
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        _row(agency_a, app_a, membership_a)
        assert PreparedDocument._base_manager.count() == 1
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert PreparedDocument._base_manager.count() == 0
