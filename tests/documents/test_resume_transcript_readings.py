from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.concierge.documents import register
from apps.documents.models import TranscriptUpload
from apps.tenancy.context import tenant_scope

pytestmark = pytest.mark.django_db


def _upload(agency, membership, cycle, **fields):
    document = register(agency.id, membership.id, kind="TRANSCRIPT")
    with tenant_scope(agency.id):
        document.state = fields.pop("document_state", "AVAILABLE")
        document.save(update_fields=["state"])
        upload = TranscriptUpload.objects.create(
            student=membership, cycle=cycle, document=document, role="ORIGINAL", **fields
        )
        if "updated_at" in fields:
            TranscriptUpload.objects.filter(id=upload.id).update(updated_at=fields["updated_at"])
    return upload


def _sweep():
    with patch(
        "apps.documents.management.commands.resume_transcript_readings.process_upload"
    ) as run:
        call_command("resume_transcript_readings", stdout=StringIO())
    return {call.args[1] for call in run.call_args_list}


def test_due_delayed_stuck_and_lost_uploads_are_resumed_and_nothing_else(
    agency_a, membership_a, paid_cycle_a
):
    now, old = timezone.now(), timezone.now() - timedelta(hours=2)
    soon, past = now + timedelta(hours=1), now - timedelta(minutes=1)
    due = _upload(agency_a, membership_a, paid_cycle_a, state="DELAYED", next_attempt_at=past)
    _upload(agency_a, membership_a, paid_cycle_a, state="DELAYED", next_attempt_at=soon)
    stuck = _upload(agency_a, membership_a, paid_cycle_a, state="READING", updated_at=old)
    _upload(agency_a, membership_a, paid_cycle_a, state="READING")
    lost = _upload(agency_a, membership_a, paid_cycle_a, state="PENDING", updated_at=old)
    _upload(
        agency_a,
        membership_a,
        paid_cycle_a,
        state="PENDING",
        updated_at=old,
        document_state="QUARANTINED",
    )
    unassembled = _upload(agency_a, membership_a, paid_cycle_a, state="READ", updated_at=old)
    _upload(agency_a, membership_a, paid_cycle_a, state="READ", assembled=True, updated_at=old)
    _upload(agency_a, membership_a, paid_cycle_a, state="REFUSED", updated_at=old)
    assert _sweep() == {due.id, stuck.id, lost.id, unassembled.id}


def test_one_upload_crashing_does_not_stop_the_rest_and_is_delayed(
    agency_a, membership_a, paid_cycle_a
):
    old = timezone.now() - timedelta(hours=2)
    _upload(agency_a, membership_a, paid_cycle_a, state="READING", updated_at=old)
    _upload(agency_a, membership_a, paid_cycle_a, state="READING", updated_at=old)
    calls = []

    def run(tenant_id, upload_id, **kwargs):
        calls.append(upload_id)
        if len(calls) == 1:
            raise RuntimeError("boom")

    with patch(
        "apps.documents.management.commands.resume_transcript_readings.process_upload",
        side_effect=run,
    ):
        call_command("resume_transcript_readings", stdout=StringIO())
    assert len(set(calls)) == 2
    with tenant_scope(agency_a.id):
        crashed = TranscriptUpload.objects.get(id=calls[0])
        assert crashed.attempts == 1


def test_what_is_not_yet_due_is_left_alone_and_a_due_assembly_is_resumed(
    agency_a, membership_a, paid_cycle_a
):
    now = timezone.now()
    _upload(agency_a, membership_a, paid_cycle_a, state="PENDING")  # its scan message is on its way
    _upload(
        agency_a, membership_a, paid_cycle_a, state="READ",
        next_attempt_at=now + timedelta(hours=1), updated_at=now - timedelta(hours=2),
    )
    due = _upload(
        agency_a, membership_a, paid_cycle_a, state="READ",
        next_attempt_at=now - timedelta(minutes=1),
    )
    assert _sweep() == {due.id}
