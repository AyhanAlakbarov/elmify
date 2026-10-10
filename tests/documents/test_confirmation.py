"""confirm_facts is a trust boundary, so the authorisation tests here are the
point of the file rather than a formality: an id is resolved through
``student=student``, never by id alone."""

from uuid import uuid4

import pytest

from apps.documents.confirmation import FactNotFound, confirm_facts
from apps.documents.models import VerifiedFact
from apps.documents.verification import generatable_facts
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

from .conftest import make_fact

pytestmark = pytest.mark.django_db


def _candidate(student, name="Jane Doe"):
    return make_fact(student, VerifiedFact.Category.IDENTITY, {"full_name": name})


def test_a_candidate_becomes_visible_to_generation(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        assert not generatable_facts(membership_a).exists()

        confirmed = confirm_facts(
            student=membership_a, fact_ids=[fact.id], actor=membership_a
        )

        assert confirmed == 1
        fact.refresh_from_db()
        assert fact.confirmed_by_id == membership_a.id
        assert fact.confirmed_at is not None
        assert list(generatable_facts(membership_a)) == [fact]


def test_another_students_fact_id_is_not_found_and_nothing_is_written(
    agency_a, agency_b, membership_a, membership_b
):
    """404, not 403: a 403 would confirm the fact exists. All-or-nothing, so a
    batch carrying one foreign id confirms none of the caller's own either."""
    with tenant_scope(agency_b.id):
        theirs = _candidate(membership_b, name="Someone Else")
    with tenant_scope(agency_a.id):
        mine = _candidate(membership_a)

        with pytest.raises(FactNotFound):
            confirm_facts(
                student=membership_a, fact_ids=[mine.id, theirs.id], actor=membership_a
            )

        mine.refresh_from_db()
        assert mine.confirmed_by_id is None


def test_a_sibling_students_fact_in_same_tenant_is_not_found(
    agency_a, membership_a, django_user_model
):
    """The student= filter itself blocks a sibling's fact, not just RLS.

    The cross-tenant test cannot isolate this: membership_b in agency_b is
    hidden by RLS even without the student= check, so a test that passes
    identically if that filter is missing is not a test. This one creates a
    second student in agency_a and verifies the filter works at the app layer.
    """
    with tenant_scope(agency_a.id):
        # Create a second student in the same tenant
        user2 = django_user_model.objects.create(username="student2")
        membership_b_in_a = Membership.objects.create(
            tenant=agency_a, user=user2, role=Membership.Role.STUDENT, active=True
        )

        mine = _candidate(membership_a)
        theirs = _candidate(membership_b_in_a, name="Another Student")

        with pytest.raises(FactNotFound):
            confirm_facts(
                student=membership_a, fact_ids=[mine.id, theirs.id], actor=membership_a
            )

        theirs.refresh_from_db()
        assert theirs.confirmed_by_id is None


def test_an_unknown_id_is_not_found(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        with pytest.raises(FactNotFound):
            confirm_facts(student=membership_a, fact_ids=[uuid4()], actor=membership_a)


def test_confirming_twice_is_a_no_op(agency_a, membership_a):
    """A resubmitted list must not fail -- the client retries, and the second
    call is not an error the student can act on."""
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        confirm_facts(student=membership_a, fact_ids=[fact.id], actor=membership_a)
        fact.refresh_from_db()
        stamped_at = fact.confirmed_at

        again = confirm_facts(
            student=membership_a, fact_ids=[fact.id], actor=membership_a
        )

        assert again == 0
        fact.refresh_from_db()
        assert fact.confirmed_at == stamped_at


def test_a_superseded_fact_is_skipped_not_confirmed(agency_a, membership_a):
    """A superseded row is not a candidate any more -- confirming it would put
    a corrected-away claim back in front of generation."""
    with tenant_scope(agency_a.id):
        old = _candidate(membership_a, name="Old Name")
        VerifiedFact.objects.create(
            student=membership_a,
            category=VerifiedFact.Category.IDENTITY,
            payload={"full_name": "New Name"},
            source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT,
            source_ref="correction",
            supersedes=old,
            confirmed_by=None,
            created_by=membership_a,
        )

        assert confirm_facts(
            student=membership_a, fact_ids=[old.id], actor=membership_a
        ) == 0
        old.refresh_from_db()
        assert old.confirmed_by_id is None


def test_every_confirmation_is_audited(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        fact = _candidate(membership_a)
        confirm_facts(student=membership_a, fact_ids=[fact.id], actor=membership_a)

        events = AuditEvent.objects.filter(event="fact.confirmed", object_id=fact.id)
        assert events.count() == 1
        assert events.get().actor_id == membership_a.id
