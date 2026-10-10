"""Erasure reaches every field this plan adds (spec §4: REDACT for the outcome)."""

from datetime import date
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.audit.redaction import redact_student
from apps.concierge.documents import register
from apps.concierge.models import DocumentVersion
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant

pytestmark = pytest.mark.django_db


def test_erasure_empties_the_outcome_and_nulls_its_dates(agency_a, membership_a) -> None:
    with tenant_scope(agency_a.id):
        connection = MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT",
            address="amina@outlook.test",
        )
        signal = MailSignal.objects.create(
            tenant=agency_a, connection=connection, provider_message_id="m-1",
            sender_domain="tum.de", received_at=timezone.now(), label="DECISION",
            outcome="ADMITTED_CONDITIONAL", decision_reading={"is_decision": True, "p": {}},
            outcome_conditions=["final transcript"], funding_outcome="REJECTED",
            offered_programme="MSc Statistics", offer_handled_at=timezone.now(),
            document_name="Final transcript", document_due=date(2026, 12, 1),
            interview_at=timezone.now(),
        )
        application = Application.objects.create(
            tenant=agency_a, student=membership_a, program_id=uuid4(), name="MSc Statistics",
            decision_available_at=timezone.now(), outcome="ADMITTED_CONDITIONAL",
            outcome_recorded_at=timezone.now(), outcome_source="MAIL",
            outcome_evidence=signal, started_at=timezone.now(),
        )
        document = register(agency_a.id, membership_a.id, kind="PASSPORT")
        DocumentVersion.objects.filter(id=document.id).update(expires_on=date(2030, 1, 1))

        with transaction.atomic():
            set_local_tenant(agency_a.id)
            redact_student(tenant_id=agency_a.id, student_id=membership_a.id)

        application.refresh_from_db()
        signal.refresh_from_db()
        document.refresh_from_db()

    assert (application.outcome, application.outcome_source) == ("", "")
    assert application.decision_available_at is None
    assert application.outcome_recorded_at is None
    assert application.started_at is not None
    assert (signal.outcome, signal.funding_outcome) == ("", "")
    assert signal.decision_reading == {}
    assert signal.outcome_conditions == {}
    assert signal.document_name == ""
    assert signal.document_due is None
    assert signal.interview_at is None
    assert signal.offered_programme == ""
    assert signal.offer_handled_at is not None
    assert application.name == ""
    assert document.expires_on is None
