"""Spec section 11: erasure keeps consent and request records, de-identified."""

from datetime import UTC, datetime

import pytest
from django.utils import timezone

from apps.audit import deletion
from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.privacy import acceptance, documents, requests
from apps.privacy.models import Acceptance, PrivacyRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


def test_erasure_keeps_acceptances_and_requests_without_the_person(
    agency_a, django_user_model, monkeypatch
):
    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kwargs: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kwargs: 0)
    for kind in documents.KINDS:
        documents.publish(kind, "en", f"{kind} v1", material=True)
    user = django_user_model.objects.create_user(
        username="aysel@example.com",
        email="aysel@example.com",
        first_name="Aysel",
        last_name="Mammadova",
    )
    with tenant_scope(agency_a.id):
        student = Membership.objects.create(
            tenant=agency_a, user=user, role=Membership.Role.STUDENT, active=True
        )
        acceptance.record(
            student,
            acceptance.documents_to_accept(agency_a.id, "en"),
            surface="signup",
            language="en",
        )
        received = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
        requests.record(student, kind="deletion", channel="email", received_at=received)
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        erasure = DeletionRequest.objects.create(
            tenant=agency_a, student=student, state="REQUESTED"
        )
        for state in ("RETENTION_REVIEW", "APPROVED", "EXECUTED"):
            advance_deletion(erasure, state)

        kept = list(Acceptance.objects.filter(student=student))
        request = PrivacyRequest.objects.get(student=student)
    assert len(kept) == 2
    assert {row.surface for row in kept} == {"signup"}
    assert (request.kind, request.channel, request.received_at) == ("deletion", "email", received)
    user.refresh_from_db()
    assert user.username.startswith("deleted-")
    assert "aysel" not in user.email.lower()
    assert "Aysel" not in (user.first_name + user.last_name)


def test_erasure_completes_for_a_student_with_transcript_uploads_and_pages(
    agency_a, membership_a, paid_cycle_a, monkeypatch
):
    from apps.concierge.documents import register
    from apps.documents.models import TranscriptPage, TranscriptUpload

    monkeypatch.setattr(deletion, "delete_student_documents", lambda **kwargs: 0)
    monkeypatch.setattr(deletion, "delete_student_portal_credentials", lambda **kwargs: 0)
    monkeypatch.setattr(deletion, "delete_student_mailbox_tokens", lambda **kwargs: 0)
    document = register(agency_a.id, membership_a.id, kind="TRANSCRIPT")
    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.create(
            student=membership_a, cycle=paid_cycle_a, document=document, role="ORIGINAL",
            file_sha256="a" * 64,
        )
        page = TranscriptPage.objects.create(
            student=membership_a, cycle=paid_cycle_a, upload=upload, number=1, slot=1,
            state="READ", source="azure", page={"lines": [{"text": "Aysel Mammadova"}]},
        )
        RetentionPolicy.objects.create(tenant=agency_a, version=1, effective_at=timezone.now())
        erasure = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        for state in ("RETENTION_REVIEW", "APPROVED", "EXECUTED"):
            advance_deletion(erasure, state)
        page.refresh_from_db()
        upload.refresh_from_db()
    assert not page.page
    assert upload.file_sha256 == ""
    assert (page.slot, page.state) == (1, "READ")
