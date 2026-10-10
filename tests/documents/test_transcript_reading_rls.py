"""TranscriptReading behind a role that cannot bypass row-level security.

The rest of the suite runs as the test superuser, which is BYPASSRLS, so the
table's tenant_isolation policy is invisible there (CLAUDE.md, "Row-level
security"). These tests repoint the ORM at a NOBYPASSRLS role and check the
policy itself: the ORM's tenant filter is removed with ``_base_manager`` so
the only thing left filtering is Postgres.

Shape rules from tests/portals/test_ext_rls.py: ``transaction=True`` because
the fixture reconnects, and setup fixtures listed before ``rls_enforced_orm``
so they write as the superuser.
"""

from contextlib import ExitStack
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import DatabaseError
from django.utils import timezone

from apps.accounts.consultation import ConsultationDraft, prefill_from_latest_reading
from apps.concierge.documents import register
from apps.concierge.models import StudentCycle
from apps.documents.document_worker import handle_scan_result, mark_read_failed
from apps.documents.models import TranscriptReading, TranscriptUpload
from apps.documents.ocr_errors import OcrUnavailable
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import tenant_transaction
from apps.tenancy.models import Membership
from tests.accounts.test_prefill import _GRADE_UNSURE, _RECORD
from tests.documents.test_transcript_worker import PAGES, _event, _pipeline, _reading

pytestmark = pytest.mark.django_db(transaction=True)


def _student(agency, django_user_model):
    user = django_user_model.objects.create(username=f"rls-{uuid4().hex[:8]}")
    return Membership.objects.create(
        tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
    )


@pytest.fixture
def reading_a(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model)
        document = register(agency_a.id, student.id, kind="TRANSCRIPT")
        return TranscriptReading.objects.create(
            student=student,
            document=document,
            record=_RECORD,
            highlights=[_GRADE_UNSURE.model_dump()],
        )


@pytest.fixture
def unread_document_a(reading_a):
    with tenant_scope(reading_a.tenant_id):
        return register(reading_a.tenant_id, reading_a.student_id, kind="TRANSCRIPT")


def test_the_owning_tenant_prefills_its_reading(reading_a, rls_enforced_orm):
    tenant_id = reading_a.tenant_id
    with tenant_scope(tenant_id), tenant_transaction(tenant_id):
        student = Membership.objects.get(id=reading_a.student_id)
        draft = prefill_from_latest_reading(
            ConsultationDraft(tenant_id, student.id, {}), membership=student
        )
    assert draft.reading_id == reading_a.id
    assert draft.highlights == (_GRADE_UNSURE,)


def test_another_tenant_sees_no_reading_even_without_the_orm_filter(
    reading_a, agency_b, rls_enforced_orm
):
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert not TranscriptReading._base_manager.filter(id=reading_a.id).exists()
        updated = TranscriptReading._base_manager.filter(id=reading_a.id).update(
            accepted=_RECORD
        )
    assert updated == 0


def test_another_tenant_cannot_write_a_reading_into_the_first(
    reading_a, unread_document_a, agency_b, rls_enforced_orm
):
    # bulk_create skips TenantScopedModel.save's own tenant check, so the
    # policy's WITH CHECK is the only thing that can refuse this row.
    row = TranscriptReading(
        tenant_id=reading_a.tenant_id,
        student_id=reading_a.student_id,
        document_id=unread_document_a.id,
        record=_RECORD,
    )
    with tenant_scope(agency_b.id), pytest.raises(DatabaseError) as refused:  # noqa: PT012
        with tenant_transaction(agency_b.id):
            TranscriptReading._base_manager.bulk_create([row])
    assert "row-level security" in str(refused.value)


@pytest.fixture
def transcript_a(agency_a, django_user_model):
    with tenant_scope(agency_a.id):
        student = _student(agency_a, django_user_model)
        cycle = StudentCycle.objects.create(
            student=student, academic_year="2026-2027", paid_at=timezone.now()
        )
        document = register(agency_a.id, student.id, kind="TRANSCRIPT")
        TranscriptUpload.objects.create(
            student=student, cycle=cycle, document=document, role="ORIGINAL"
        )
        return document


def _stored(document):
    """What the worker left, read with the ORM filter removed so only the policy filters."""
    with tenant_scope(document.tenant_id), tenant_transaction(document.tenant_id):
        upload = TranscriptUpload._base_manager.get(document_id=document.id).state
        read = TranscriptReading._base_manager.filter(document_id=document.id).exists()
    return upload, read


def test_the_worker_stores_a_reading_behind_the_policy(transcript_a, rls_enforced_orm):
    """With the GUC unset the INSERT is refused by WITH CHECK; this proves it is set."""
    with ExitStack() as stack:
        _pipeline(stack, reading=_reading())
        handle_scan_result(_event(transcript_a))
    assert _stored(transcript_a) == ("READ", True)


def test_the_worker_refuses_an_unreadable_upload_behind_the_policy(transcript_a, rls_enforced_orm):
    """An UPDATE with the GUC unset matches zero rows and raises nothing (CLAUDE.md failure
    mode 1): the student would never be told the file was refused, and no test running as the
    superuser could tell."""
    with (
        patch(PAGES + "check_gates"),
        patch(PAGES + "open_document", return_value=b"GIF89a"),
    ):
        handle_scan_result(_event(transcript_a))
    assert _stored(transcript_a) == ("REFUSED", False)


def test_the_last_failure_delays_the_upload_behind_the_policy(transcript_a, rls_enforced_orm):
    with tenant_scope(transcript_a.tenant_id), tenant_transaction(transcript_a.tenant_id):
        TranscriptUpload._base_manager.filter(document_id=transcript_a.id).update(state="READING")
    with patch("apps.documents.document_worker.process_upload", side_effect=OcrUnavailable("x")):
        with pytest.raises(OcrUnavailable):
            handle_scan_result(_event(transcript_a))
    mark_read_failed(_event(transcript_a))
    assert _stored(transcript_a) == ("DELAYED", False)
