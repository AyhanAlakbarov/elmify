"""The onboarding draft is kept per student, not in the login session (onboarding
friction design 2026-10-15, variant 8), so a student who signs in on another device
keeps their answers."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.consultation import ConsultationDraft, clear_draft, read_draft, write_draft
from apps.accounts.models import ConsultationDraftRecord
from apps.audit.redaction import KEEP, REDACT
from apps.tenancy.context import tenant_scope
from apps.tenancy.db import set_local_tenant
from apps.tenancy.models import Agency, Membership

pytestmark = pytest.mark.django_db


def test_a_draft_survives_a_new_session(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        write_draft(ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "Chemistry"}))
        draft = read_draft(tenant_id=agency_a.id, membership_id=membership_a.id)
    assert draft.answers == {"target_field": "Chemistry"}


def test_writing_twice_keeps_one_row(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        write_draft(ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "A"}))
        write_draft(ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "B"}))
        assert ConsultationDraftRecord.objects.filter(student=membership_a).count() == 1
        assert read_draft(tenant_id=agency_a.id, membership_id=membership_a.id).answers == {
            "target_field": "B"
        }


def test_clear_draft_removes_the_row(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        draft = ConsultationDraft(agency_a.id, membership_a.id, {"target_field": "Chemistry"})
        write_draft(draft)
        clear_draft(draft)
        assert not ConsultationDraftRecord.objects.filter(student=membership_a).exists()


@pytest.mark.parametrize(
    "answers", [{"no_longer_asked": 1}, {"nationality": " AZ "}, {"nationality": "AZE"}]
)
def test_a_stale_or_tampered_stored_draft_is_dropped_not_fatal(agency_a, membership_a, answers):
    with tenant_scope(agency_a.id):
        ConsultationDraftRecord.objects.create(
            student=membership_a,
            envelope={
                "tenant_id": str(agency_a.id),
                "membership_id": str(membership_a.id),
                "answers": answers,
            },
        )
        assert read_draft(tenant_id=agency_a.id, membership_id=membership_a.id).answers == {}
        assert not ConsultationDraftRecord.objects.filter(student=membership_a).exists()


def test_erasure_blanks_the_draft_and_keeps_only_the_timestamp():
    assert REDACT["accounts.ConsultationDraftRecord"].fields == ("envelope",)
    assert KEEP["accounts.ConsultationDraftRecord"] == ("updated_at",)


@pytest.fixture
def two_drafts(django_db_blocker):
    """Two agencies, each with one student and a stored draft, committed (rls_enforced_orm
    reconnects, so rows on the old connection must be committed to be seen)."""
    with django_db_blocker.unblock(), transaction.atomic():
        made = []
        for index in (0, 1):
            agency = Agency.objects.create(name=f"draft-agency-{index}")
            user = get_user_model().objects.create(username=f"draft-{index}-{uuid4().hex}")
            with tenant_scope(agency.id), transaction.atomic():
                set_local_tenant(agency.id)
                student = Membership.objects.create(
                    tenant=agency, user=user, role="STUDENT", active=True
                )
                ConsultationDraftRecord.objects.create(student=student, envelope={})
            made.append(agency)
    yield made


@pytest.mark.django_db(transaction=True)
def test_the_policy_hides_another_agencys_draft(rls_enforced_orm, two_drafts):
    first = two_drafts[0]
    with transaction.atomic():
        set_local_tenant(first.id)
        assert ConsultationDraftRecord._base_manager.count() == 1
