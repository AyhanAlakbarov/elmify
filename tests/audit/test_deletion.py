from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.deletion import DeletionBlocked, DeletionRequest, advance_deletion
from apps.audit.models import RetentionPolicy
from apps.tenancy.context import tenant_scope


@pytest.mark.django_db
def test_deletion_blocked_without_retention_policy(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="RETENTION_REVIEW"
        )
    with pytest.raises(DeletionBlocked):
        advance_deletion(request, "APPROVED")


@pytest.mark.django_db
def test_deletion_allowed_after_retention_policy_exists(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(
            tenant=agency_a, version=1, effective_at="2026-01-01T00:00:00Z"
        )
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="RETENTION_REVIEW"
        )
    advanced = advance_deletion(request, "APPROVED")
    assert advanced.state == "APPROVED"


@pytest.mark.django_db
def test_deletion_blocked_under_legal_hold(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(
            tenant=agency_a, version=1, effective_at="2026-01-01T00:00:00Z"
        )
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="RETENTION_REVIEW", legal_hold=True
        )
    with pytest.raises(DeletionBlocked):
        advance_deletion(request, "APPROVED")


@pytest.mark.django_db
def test_invalid_transition_rejected(agency_a, membership_a):
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
    with pytest.raises(DeletionBlocked):
        advance_deletion(request, "APPROVED")


@pytest.mark.django_db
@pytest.mark.parametrize("start", ["REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED"])
def test_a_request_can_be_cancelled_from_any_non_terminal_state(agency_a, membership_a, start):
    """Restore is the student's way out, and DENIED is included deliberately.

    A request the agency refused leaves the student locked out but not erased;
    without this transition they would have no way back into their account.
    """
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state=start
        )
    assert advance_deletion(request, "CANCELLED").state == "CANCELLED"


@pytest.mark.django_db
@pytest.mark.parametrize("terminal", ["CANCELLED", "EXECUTED"])
def test_terminal_states_have_no_exit(agency_a, membership_a, terminal):
    """A cancelled or executed request is finished. Nothing moves it again."""
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state=terminal
        )
    for target in ("REQUESTED", "RETENTION_REVIEW", "APPROVED", "DENIED", "EXECUTED"):
        with pytest.raises(DeletionBlocked):
            advance_deletion(request, target)


@pytest.mark.django_db
def test_approval_stores_the_execution_date_on_the_row(agency_a, membership_a):
    """Reloaded from the database, not read off the in-memory object.

    advance_deletion saves with update_fields, which drops an assigned field
    that is not named there -- silently, with no error. An in-memory assertion
    cannot see that, and the failure it hides is an APPROVED request whose
    execute_after is NULL, which the scheduler's execute_after__lte filter
    never matches: an erasure that never runs, for a student who was shown a
    date.
    """
    with tenant_scope(agency_a.id):
        RetentionPolicy.objects.create(
            tenant=agency_a, version=1, effective_at="2026-01-01T00:00:00Z"
        )
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="RETENTION_REVIEW"
        )
    before = timezone.now()
    advance_deletion(request, "APPROVED")

    with tenant_scope(agency_a.id):
        stored = DeletionRequest.objects.get(id=request.id)
    assert stored.execute_after is not None
    assert stored.execute_after - before >= timedelta(days=29, hours=23)
    assert stored.execute_after - before <= timedelta(days=30, minutes=1)


@pytest.mark.django_db
def test_a_request_that_never_reaches_approved_has_no_execution_date(agency_a, membership_a):
    """A held request is waiting on a human, not on a clock."""
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
    advance_deletion(request, "RETENTION_REVIEW")

    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.get(id=request.id).execute_after is None


@pytest.mark.django_db
def test_the_reason_is_a_fixed_choice_and_never_free_text(agency_a, membership_a):
    """Free text from a student is personal data that would itself need
    redacting. A fixed list avoids the problem and still gives the agency a
    usable "why students leave" signal.
    """
    from django.core.exceptions import ValidationError

    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a,
            student=membership_a,
            state="REQUESTED",
            reason=DeletionRequest.Reason.SWITCHING_AGENCY,
        )
        request.full_clean()

        request.reason = "I am moving to Berlin and my counselor was unhelpful"
        with pytest.raises(ValidationError):
            request.full_clean()


@pytest.mark.django_db
def test_a_held_request_records_why_it_was_held(agency_a, membership_a):
    """review_reason is what the owner screen displays; without it a held
    request is a row nobody can act on.
    """
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a,
            student=membership_a,
            state="RETENTION_REVIEW",
            review_reason=DeletionRequest.ReviewReason.APPLICATIONS_IN_FLIGHT,
        )
        request.full_clean()
        assert DeletionRequest.objects.get(id=request.id).review_reason == "APPLICATIONS_IN_FLIGHT"


@pytest.mark.django_db
def test_the_lock_query_is_indexed(agency_a):
    """Slice 2's middleware runs this on every authenticated student request."""
    index_fields = [tuple(index.fields) for index in DeletionRequest._meta.indexes]
    assert ("tenant", "student", "state") in index_fields


@pytest.mark.django_db
def test_the_database_refuses_free_text_in_the_reason_columns(agency_a, membership_a):
    """choices= is validated by full_clean(), which .create() never calls.

    Without a constraint, a view doing create(reason=request.POST["reason"])
    stores thirty characters of arbitrary student free text -- in a field
    classified KEEP, so it outlives the erasure. That is exactly what a fixed
    list exists to prevent, so the database has to be the one enforcing it.
    """
    from django.db import IntegrityError, transaction

    for field in ("reason", "review_reason"):
        with tenant_scope(agency_a.id), pytest.raises(IntegrityError):
            with transaction.atomic():
                DeletionRequest.objects.create(
                    tenant=agency_a,
                    student=membership_a,
                    state="REQUESTED",
                    **{field: "jon@gmail.com moving to Berlin"},
                )


def test_the_constraints_and_the_enums_do_not_drift():
    """The CheckConstraints spell their values out; a nested Meta cannot read
    the outer class's enums. This is what keeps the duplication honest -- add a
    Reason without adding it to the constraint and the database silently
    rejects a value the form offers.
    """
    by_name = {c.name: c for c in DeletionRequest._meta.constraints}
    for name, choices in (
        ("deletion_reason_valid", DeletionRequest.Reason),
        ("deletion_review_reason_valid", DeletionRequest.ReviewReason),
    ):
        allowed = set(by_name[name].condition.children[0][1])
        assert allowed == {""} | set(choices.values), (
            f"{name} and {choices.__name__} disagree: "
            f"constraint-only={allowed - {''} - set(choices.values)}, "
            f"enum-only={set(choices.values) - allowed}"
        )
