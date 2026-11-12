import pytest
from django.db import IntegrityError, transaction

from apps.concierge.documents import register
from apps.documents.models import DocumentReading
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction

pytestmark = pytest.mark.django_db


def _reading(agency, membership, **fields):
    document = register(agency.id, membership.id, kind="PASSPORT")
    with tenant_scope(agency.id):
        return DocumentReading.objects.create(
            student=membership, document=document, kind="PASSPORT", reader_version="id-1",
            **fields,
        )


def test_one_reading_per_document_and_reader_version(agency_a, membership_a):
    reading = _reading(agency_a, membership_a)
    with tenant_scope(agency_a.id), pytest.raises(IntegrityError), transaction.atomic():
        DocumentReading.objects.create(
            student=membership_a, document=reading.document, kind="PASSPORT",
            reader_version="id-1",
        )


@pytest.fixture
def reading_a(agency_a, membership_a):
    return _reading(agency_a, membership_a, values=[{"key": "identity.surname"}])


# transaction=True and reading_a listed before rls_enforced_orm: the fixture reconnects, and
# the setup must be committed and written as the superuser (see test_transcript_reading_rls).
@pytest.mark.django_db(transaction=True)
def test_a_tenant_never_sees_another_tenants_reading(reading_a, agency_a, agency_b,
                                                     rls_enforced_orm):
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert not DocumentReading._base_manager.exists()
    with tenant_scope(agency_a.id), tenant_transaction(agency_a.id):
        assert DocumentReading._base_manager.filter(pk=reading_a.pk).exists()


def test_erasure_deletes_the_readings(agency_a, membership_a, monkeypatch):
    """Mirrors tests/portals/test_answers.py::test_erasure_deletes_the_students_answers.
    The test role is BYPASSRLS, so this proves the delete exists, not its RLS placement."""
    from django.utils import timezone

    from apps.audit import deletion
    from apps.audit.deletion import advance_deletion
    from apps.audit.models import DeletionRequest, RetentionPolicy

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kw: 0)
    _reading(agency_a, membership_a, values=[{"key": "identity.surname", "value": "ALIYEVA"}])
    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        for state in ("RETENTION_REVIEW", "APPROVED", "EXECUTED"):
            advance_deletion(request, state)
        assert not DocumentReading.objects.filter(student=membership_a).exists()
