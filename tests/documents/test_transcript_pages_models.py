import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import TranscriptPage, TranscriptUpload
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _upload(agency, membership, cycle, **fields):
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        return TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document,
            role=fields.pop("role", "ORIGINAL"), **fields,
        )


def _page(upload, slot, **fields):
    return TranscriptPage.objects.create(
        student=upload.student, cycle=upload.cycle, upload=upload, number=1, slot=slot,
        state=fields.pop("state", "READ"), source="azure", **fields,
    )


def test_a_new_upload_is_pending_and_charged_nothing(agency_a, membership_a, paid_cycle_a):
    upload = _upload(agency_a, membership_a, paid_cycle_a)
    assert (upload.state, upload.pages_counted, upload.attempts, upload.assembled) == (
        "PENDING", None, 0, False,
    )


def test_one_live_page_per_slot(agency_a, membership_a, paid_cycle_a):
    upload = _upload(agency_a, membership_a, paid_cycle_a)
    with tenant_scope(agency_a.id):
        _page(upload, 1)
        with pytest.raises(IntegrityError), transaction.atomic():
            _page(upload, 1)


def test_a_superseded_page_frees_its_slot(agency_a, membership_a, paid_cycle_a):
    upload = _upload(agency_a, membership_a, paid_cycle_a)
    with tenant_scope(agency_a.id):
        old = _page(upload, 1)
        old.superseded_at = timezone.now()
        old.save(update_fields=["superseded_at"])
        _page(upload, 1, retakes=1)
        assert TranscriptPage.objects.filter(slot=1, superseded_at__isnull=True).count() == 1


def test_a_retake_names_its_slot_and_nothing_else_does(agency_a, membership_a, paid_cycle_a):
    with pytest.raises(IntegrityError), transaction.atomic():
        _upload(agency_a, membership_a, paid_cycle_a, mode="RETAKE")
    with pytest.raises(IntegrityError), transaction.atomic():
        _upload(agency_a, membership_a, paid_cycle_a, mode="ADD", retake_slot=2)
