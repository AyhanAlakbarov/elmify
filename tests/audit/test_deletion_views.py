"""Server behaviour of the deletion flow: authorization, ownership, rate limit.

Markup assertions carry @pytest.mark.frontend and are skipped while templates/
is absent -- tests/templates/README.md forbids enriching a stub to make a test
pass.
"""

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.audit.models import DeletionRequest, RetentionPolicy
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import Membership

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _policy(agency):
    with tenant_scope(agency.id):
        RetentionPolicy.objects.create(tenant=agency, version=1, effective_at=timezone.now())


def test_a_student_requests_deletion(client, agency_a, domain_a, user_a, membership_a):
    _policy(agency_a)
    client.force_login(user_a)
    response = client.post(
        "/student/account/delete/", {"reason": "SWITCHING_AGENCY"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.get(student=membership_a)
    assert request.state == "APPROVED"


def test_the_reason_must_be_one_of_the_choices(client, agency_a, domain_a, user_a, membership_a):
    """The view is the trust boundary. The CheckConstraint behind it would turn
    free text into a 500; this turns it into a 400 and writes nothing.
    """
    _policy(agency_a)
    client.force_login(user_a)
    response = client.post(
        "/student/account/delete/",
        {"reason": "jon@gmail.com moving to Berlin"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 400
    with tenant_scope(agency_a.id):
        assert not DeletionRequest.objects.filter(student=membership_a).exists()


def test_deletion_cannot_be_requested_by_GET(client, agency_a, domain_a, user_a, membership_a):
    _policy(agency_a)
    client.force_login(user_a)
    response = client.get("/student/account/delete/", HTTP_HOST=domain_a.host)
    assert response.status_code == 405


def test_a_counselor_cannot_use_the_student_flow(
    client, agency_a, domain_a, counselor_user, counselor_membership
):
    """Erasure is a student right. A counselor offboarding is another operation."""
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 403


def test_a_student_cannot_restore_another_students_request(
    client, agency_a, domain_a, user_a, membership_a, django_user_model
):
    """The ownership check, and the reason it matters: cancelling is not
    destructive, but it silently keeps alive data somebody asked to have
    deleted.
    """
    from apps.tenancy.models import Membership

    _policy(agency_a)
    other_user = django_user_model.objects.create_user(username="other-student")
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=other_user, role=Membership.Role.STUDENT
        )
        victim = DeletionRequest.objects.create(
            tenant=agency_a, student=other, state="APPROVED"
        )

    client.force_login(user_a)
    response = client.post(
        f"/student/account/restore/{victim.id}/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.get(id=victim.id).state == "APPROVED"


def test_a_student_restores_their_own_request(
    client, agency_a, domain_a, user_a, membership_a
):
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.get(student=membership_a)

    response = client.post(
        f"/student/account/restore/{request.id}/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.get(id=request.id).state == "CANCELLED"


def test_the_request_endpoint_is_rate_limited(
    client, agency_a, domain_a, user_a, membership_a
):
    """The limiter bounds the cancel-and-retry loop, which is the only way to
    reach this endpoint repeatedly.

    Task 4's lock means a student with an open request is redirected away from
    here entirely, so the lock is the primary bound and this limiter is what
    caps someone cycling delete/restore -- two audit rows per turn. The test
    cancels between attempts for exactly that reason; written without the
    cancel it passes before the lock exists and breaks the moment it lands.
    """
    _policy(agency_a)
    client.force_login(user_a)

    codes = []
    for _ in range(7):
        codes.append(
            client.post(
                "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
            ).status_code
        )
        with tenant_scope(agency_a.id):
            DeletionRequest.objects.filter(student=membership_a).exclude(
                state__in=("CANCELLED", "EXECUTED")
            ).update(state="CANCELLED")

    assert 429 in codes, f"no request was refused: {codes}"


def test_the_pending_screen_shows_the_request(
    client, agency_a, domain_a, user_a, membership_a
):
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)

    response = client.get("/student/account/deletion/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    assert response.context["request_record"].state == "APPROVED"
    assert response.context["request_record"].execute_after is not None


def test_the_pending_screen_404s_without_a_request(
    client, agency_a, domain_a, user_a, membership_a
):
    client.force_login(user_a)
    response = client.get("/student/account/deletion/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_a_locked_student_is_redirected_away_from_everything(
    client, agency_a, domain_a, user_a, membership_a
):
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)

    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302
    assert response["Location"] == "/student/account/deletion/"


def test_the_lock_does_not_trap_the_student_on_the_way_out(
    client, agency_a, domain_a, user_a, membership_a
):
    """The pending screen and restore must stay reachable, or the lock is a
    one-way door and the thirty-day window is decorative.
    """
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        record = DeletionRequest.objects.get(student=membership_a)

    assert client.get("/student/account/deletion/", HTTP_HOST=domain_a.host).status_code == 200
    restored = client.post(
        f"/student/account/restore/{record.id}/", HTTP_HOST=domain_a.host
    )
    assert restored.status_code == 302
    assert restored["Location"] != "/student/account/deletion/"


def test_cancelling_lifts_the_lock(client, agency_a, domain_a, user_a, membership_a):
    """Nothing is undone -- the middleware's query simply stops matching."""
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    with tenant_scope(agency_a.id):
        record = DeletionRequest.objects.get(student=membership_a)
    client.post(f"/student/account/restore/{record.id}/", HTTP_HOST=domain_a.host)

    assert client.get("/student/", HTTP_HOST=domain_a.host).status_code == 200


def test_a_counselor_is_never_locked(
    client, agency_a, domain_a, counselor_user, counselor_membership
):
    """The lock reads a student's own request. Staff have none, and the query
    must not run for them at all.
    """
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    assert client.get("/counselor/", HTTP_HOST=domain_a.host).status_code == 200


def test_a_second_open_request_is_refused_by_the_database(agency_a, membership_a):
    """The constraint, directly. Two open requests are what makes the pending
    screen raise MultipleObjectsReturned, which traps the student behind a
    500 with no way to reach restore.
    """
    from django.db import IntegrityError

    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="APPROVED")
        with pytest.raises(IntegrityError):
            DeletionRequest.objects.create(
                tenant=agency_a, student=membership_a, state="REQUESTED"
            )


def test_a_closed_request_does_not_block_a_new_one(agency_a, membership_a):
    """The constraint is partial. A student who cancels may ask again."""
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="CANCELLED")
        DeletionRequest.objects.create(tenant=agency_a, student=membership_a, state="EXECUTED")
        again = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )

    assert again.state == "REQUESTED"


def test_the_view_absorbs_a_duplicate_when_the_lock_does_not(
    client, agency_a, domain_a, user_a, membership_a, monkeypatch
):
    """The view's own guard, with the middleware lock disabled.

    The lock normally redirects a second POST before it ever reaches the view,
    so a test that just posts twice proves nothing about this layer -- it
    passes on the lock alone. Disabling the lock is what puts the second POST
    through the view, where the constraint raises IntegrityError and the
    savepoint has to keep the outer transaction usable for the redirect.
    Without the savepoint this returns a TransactionManagementError 500.
    """
    monkeypatch.setattr(
        "apps.tenancy.middleware.deletion_lock_target", lambda membership: None
    )
    _policy(agency_a)
    client.force_login(user_a)
    client.post("/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host)
    second = client.post(
        "/student/account/delete/", {"reason": "OTHER"}, HTTP_HOST=domain_a.host
    )

    assert second.status_code == 302, "the caught IntegrityError poisoned the transaction"
    with tenant_scope(agency_a.id):
        assert DeletionRequest.objects.filter(student=membership_a).count() == 1


def test_the_open_states_and_the_constraint_do_not_drift():
    """The Meta constraint spells out the states because it cannot import them.
    This is the guard on that duplication, same shape as
    test_the_constraints_and_the_enums_do_not_drift in test_deletion.py.
    """
    from apps.audit.views import OPEN_DELETION_STATES

    constraint = next(
        c
        for c in DeletionRequest._meta.constraints
        if c.name == "deletion_one_open_request_per_student"
    )
    ((lookup, states),) = constraint.condition.children
    assert lookup == "state__in"
    assert tuple(states) == OPEN_DELETION_STATES


@pytest.fixture
def owner_client(client, agency_a, domain_a, django_user_model):
    """A logged-in, MFA-verified OWNER at agency A. Owners are staff, so
    TenantMembershipMiddleware requires a verified device.
    """
    from tests.conftest import verify_mfa_session

    user = django_user_model.objects.create_user(username="owner-a")
    with tenant_scope(agency_a.id):
        Membership.objects.create(tenant=agency_a, user=user, role=Membership.Role.OWNER)
    client.force_login(user)
    verify_mfa_session(client, user)
    return client


def _held(agency, student, review_reason="APPLICATIONS_IN_FLIGHT"):
    with tenant_scope(agency.id):
        return DeletionRequest.objects.create(
            tenant=agency,
            student=student,
            state="RETENTION_REVIEW",
            review_reason=review_reason,
        )


def test_the_console_lists_held_requests(owner_client, agency_a, domain_a, membership_a):
    held = _held(agency_a, membership_a)

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert response.status_code == 200
    assert [r.id for r in response.context["held"]] == [held.id]


def test_the_console_lists_requests_counting_down(
    owner_client, agency_a, domain_a, membership_a
):
    """The APPROVED list is the agency's only notification that a student is
    leaving -- no email exists in this codebase.
    """
    from apps.audit.deletion import advance_deletion

    _policy(agency_a)
    with tenant_scope(agency_a.id):
        request = DeletionRequest.objects.create(
            tenant=agency_a, student=membership_a, state="REQUESTED"
        )
        advance_deletion(request, "RETENTION_REVIEW")
        advance_deletion(request, "APPROVED")

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert [r.id for r in response.context["counting_down"]] == [request.id]


def test_the_partial_erasure_list_carries_no_name(
    owner_client, agency_a, domain_a, membership_a
):
    """A retained identity is by definition unscrubbed, so rendering the
    student's name would put an erased person's real name back on the screen
    of the agency that erased them. The rows are .values() dicts, so the name
    is unreachable from the template rather than merely unrendered.
    """
    with tenant_scope(agency_a.id):
        DeletionRequest.objects.create(
            tenant=agency_a,
            student=membership_a,
            state="EXECUTED",
            identity_retained=True,
            identity_retained_reason="STILL_ENROLLED",
        )

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    rows = list(response.context["partially_erased"])
    assert len(rows) == 1
    assert rows[0]["identity_retained_reason"] == "STILL_ENROLLED"
    assert "student" not in rows[0], "the row can reach a Membership, and so a name"


def test_a_counselor_cannot_reach_the_console(
    client, agency_a, domain_a, counselor_user, counselor_membership
):
    """Criterion 9, the role half."""
    from tests.conftest import verify_mfa_session

    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get("/owner/deletions/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


def test_an_owner_cannot_see_another_agencys_requests(
    owner_client, agency_a, agency_b, domain_a, membership_b
):
    """Criterion 9, the tenant half."""
    _held(agency_b, membership_b)

    response = owner_client.get("/owner/deletions/", HTTP_HOST=domain_a.host)

    assert list(response.context["held"]) == []


def test_releasing_a_held_request_starts_the_clock(
    owner_client, agency_a, domain_a, membership_a
):
    _policy(agency_a)
    held = _held(agency_a, membership_a)

    response = owner_client.post(
        f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
    assert held.state == "APPROVED"
    assert held.execute_after is not None
    assert held.review_reason == "APPLICATIONS_IN_FLIGHT", (
        "the reason a request was held is the record of why, and survives release"
    )


def test_refusing_a_held_request_denies_it(owner_client, agency_a, domain_a, membership_a):
    held = _held(agency_a, membership_a, review_reason="LEGAL_HOLD")

    response = owner_client.post(f"/owner/deletions/{held.id}/deny/", HTTP_HOST=domain_a.host)

    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        held.refresh_from_db()
    assert held.state == "DENIED"


def test_the_owners_actions_are_audited_against_the_owner(
    owner_client, agency_a, domain_a, membership_a
):
    """Criterion 13. Every human transition carries the acting membership."""
    from apps.funding.models import AuditEvent

    _policy(agency_a)
    held = _held(agency_a, membership_a)

    owner_client.post(f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host)

    with tenant_scope(agency_a.id):
        event = AuditEvent.objects.get(object_id=held.id, event="deletion.released")
        owner = Membership.objects.get(user__username="owner-a")
    assert event.actor_id == owner.id
    assert event.actor_kind == "HUMAN"


def test_an_owner_cannot_release_another_agencys_request(
    owner_client, agency_a, agency_b, domain_a, membership_b
):
    """The tenant boundary on the write, not only on the read."""
    victim = _held(agency_b, membership_b)

    response = owner_client.post(
        f"/owner/deletions/{victim.id}/release/", HTTP_HOST=domain_a.host
    )

    assert response.status_code == 404
    with tenant_scope(agency_b.id):
        victim.refresh_from_db()
    assert victim.state == "RETENTION_REVIEW"


def test_the_console_actions_are_not_reachable_by_GET(
    owner_client, agency_a, domain_a, membership_a
):
    held = _held(agency_a, membership_a)
    assert (
        owner_client.get(
            f"/owner/deletions/{held.id}/release/", HTTP_HOST=domain_a.host
        ).status_code
        == 405
    )
