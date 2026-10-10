"""The scheduler. Every failure mode here is silent, which is why each has a test.

The S3 purge and the portal-credential purge are stubbed throughout: unpatched
they build real AWS clients, which need an ambient region -- passing on a laptop
with ~/.aws/config and failing in CI, which has none. Same stubs as
tests/audit/test_deletion_purges_documents.py.
"""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.audit.deletion import advance_deletion
from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch):
    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_portal_credentials", lambda **kw: 0)
    monkeypatch.setattr("apps.audit.deletion.delete_student_mailbox_tokens", lambda **kw: 0)


def _student(agency, django_user_model, name):
    with tenant_scope(agency.id):
        user = django_user_model.objects.create(username=name)
        return Membership.objects.create(
            tenant=agency, user=user, role=Membership.Role.STUDENT, active=True
        )


def _due(agency, student, *, overdue=True):
    """An APPROVED request whose clock has run out (or has not)."""
    with tenant_scope(agency.id):
        RetentionPolicy.objects.get_or_create(
            tenant=agency, version=1, defaults={"effective_at": timezone.now()}
        )
        request = DeletionRequest.objects.create(
            tenant=agency, student=student, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")
        if overdue:
            # Reach past execute_after rather than sleeping thirty days.
            DeletionRequest.objects.filter(id=request.id).update(
                execute_after=timezone.now() - timedelta(days=1)
            )
            request.refresh_from_db()
        return request


def test_a_due_request_is_erased(agency_a, django_user_model):
    student = _student(agency_a, django_user_model, "due-1")
    request = _due(agency_a, student)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "EXECUTED"


def test_a_request_still_counting_down_is_left_alone(agency_a, django_user_model):
    """Criterion 6: only requests past execute_after execute."""
    student = _student(agency_a, django_user_model, "due-2")
    request = _due(agency_a, student, overdue=False)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "APPROVED"


def test_a_held_request_is_never_erased_by_the_clock(agency_a, django_user_model):
    """RETENTION_REVIEW has no execute_after, so the filter must not reach it
    even if something later writes one.
    """
    student = _student(agency_a, django_user_model, "due-3")
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a,
            student=student,
            state="RETENTION_REVIEW",
            execute_after=timezone.now() - timedelta(days=1),
        )

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "RETENTION_REVIEW"


def test_a_restore_that_wins_the_race_is_honoured(agency_a, django_user_model, monkeypatch):
    """Criterion 6a. The student cancels between the scan and the erasure.

    Without select_for_update plus the state re-check, advance_deletion reads
    state off the in-memory object and erases a request that no longer exists
    -- irreversibly, after the student withdrew it. Simulated by cancelling
    inside the lock, which is where the real restore view's UPDATE would land.
    """
    student = _student(agency_a, django_user_model, "race-1")
    request = _due(agency_a, student)

    original = DeletionRequest.objects.select_for_update
    fired: list[int] = []

    def cancel_then_lock(*args, **kwargs):
        # Only on the first call, and never monkeypatch.undo() here: the
        # `monkeypatch` fixture is one instance shared with the autouse _no_aws
        # fixture above, so undoing would restore the real AWS clients midway
        # through the erasure.
        if not fired:
            fired.append(1)
            DeletionRequest.objects.filter(id=request.id).update(state="CANCELLED")
        return original(*args, **kwargs)

    monkeypatch.setattr(DeletionRequest.objects, "select_for_update", cancel_then_lock)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        request.refresh_from_db()
    assert request.state == "CANCELLED", "erased a request the student had withdrawn"


def test_a_caught_failure_does_not_strand_the_rest_of_the_batch(
    agency_a, django_user_model, monkeypatch
):
    """One stuck row must not stop the others. The except is per request.

    Note what this does NOT prove: a ClientError caught inside an atomic block
    is a Python error, not a database one, so it never marks the transaction
    for rollback and this passes under a single per-agency transaction too.
    The atomicity boundary is pinned by the next test, not this one.
    """
    from botocore.exceptions import ClientError

    first = _due(agency_a, _student(agency_a, django_user_model, "batch-1"))
    second = _due(agency_a, _student(agency_a, django_user_model, "batch-2"))

    seen: list[object] = []

    def boom(*, tenant_id, student_id):
        seen.append(student_id)
        if len(seen) == 1:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObjects")
        return 0

    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", boom)

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        second.refresh_from_db()
    # The scan's order is not guaranteed, so assert the property rather than
    # which row it landed on: the failure stopped one erasure and no more.
    assert sorted([first.state, second.state]) == ["APPROVED", "EXECUTED"], (
        "a failure on one student stranded the rest of the batch"
    )


def test_a_completed_erasure_survives_a_later_failure_in_the_batch(
    agency_a, django_user_model, monkeypatch
):
    """Criterion 6b, and the test that actually pins the atomicity boundary.

    Confirmed RED against a version that wraps the agency's batch in one
    atomic(): the first student's EXECUTED row rolls back while their S3
    objects are already gone, so tomorrow's run re-erases documents that no
    longer exist and in between the database says the erasure never happened.

    The error has to be one the command does NOT catch, because that is what
    reaches the transaction. A caught error leaves the database transaction
    healthy and commits under either design -- which is why the test above
    cannot tell the two apart and this one can.
    """
    first = _due(agency_a, _student(agency_a, django_user_model, "durable-1"))
    second = _due(agency_a, _student(agency_a, django_user_model, "durable-2"))

    seen: list[object] = []

    def boom(*, tenant_id, student_id):
        seen.append(student_id)
        if len(seen) > 1:
            raise RuntimeError("the box caught fire")
        return 0

    monkeypatch.setattr("apps.audit.deletion.delete_student_documents", boom)

    with pytest.raises(RuntimeError):
        call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        first.refresh_from_db()
        second.refresh_from_db()
    assert sorted([first.state, second.state]) == ["APPROVED", "EXECUTED"], (
        "a later failure rolled back an erasure that had already committed"
    )


def test_another_agencys_request_is_erased_too(
    agency_a, agency_b, django_user_model, monkeypatch
):
    """The per-agency loop. tenant_scope refuses to switch tenants, so a
    command that opened one scope and stayed in it would raise
    TenantContextConflict on the second agency rather than erase anything.
    """
    a = _due(agency_a, _student(agency_a, django_user_model, "multi-a"))
    b = _due(agency_b, _student(agency_b, django_user_model, "multi-b"))

    call_command("execute_due_erasures")

    with tenant_scope(agency_a.id):
        a.refresh_from_db()
    with tenant_scope(agency_b.id):
        b.refresh_from_db()
    assert (a.state, b.state) == ("EXECUTED", "EXECUTED")
