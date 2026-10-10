from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.privacy import requests
from apps.privacy.models import PrivacyRequest
from apps.tenancy.context import tenant_scope

OCT2 = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)


def test_seven_working_days_skip_weekends():
    friday = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)
    assert requests.working_days_after(friday, 7) == datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    saturday = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    assert requests.working_days_after(saturday, 1) == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def test_working_days_are_counted_on_the_baku_calendar():
    """Saturday 02:00 in Baku is still Friday in UTC; the law's days are Baku's."""
    from zoneinfo import ZoneInfo

    baku = ZoneInfo("Asia/Baku")
    # How it arrives: timezone.now() and the database both hand back UTC.
    saturday_night = datetime(2026, 10, 2, 22, 0, tzinfo=UTC)
    assert saturday_night.astimezone(baku).weekday() == 5
    due = requests.working_days_after(saturday_night, 7)
    assert due == datetime(2026, 10, 13, 2, 0, tzinfo=baku)
    assert due.tzinfo is not None


@pytest.mark.django_db
def test_recording_an_objection_stops_processing_and_sets_the_due_date(membership_a):
    with tenant_scope(membership_a.tenant_id):
        assert not requests.processing_stopped(membership_a)
        row = requests.record(membership_a, kind="objection", channel="email", received_at=OCT2)
        assert row.due_at == datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
        assert requests.processing_stopped(membership_a)
        row.outcome = "declined"
        row.save()
        assert not requests.processing_stopped(membership_a)


@pytest.mark.django_db
def test_an_access_request_does_not_stop_processing(membership_a):
    with tenant_scope(membership_a.tenant_id):
        requests.record(membership_a, kind="access", channel="paper_with_id", received_at=OCT2)
        assert not requests.processing_stopped(membership_a)


@pytest.mark.django_db
def test_unknown_kind_or_channel_is_refused(membership_a):
    with tenant_scope(membership_a.tenant_id):
        with pytest.raises(ValueError):
            requests.record(membership_a, kind="complaint", channel="email", received_at=OCT2)
        with pytest.raises(ValueError):
            requests.record(membership_a, kind="access", channel="phone", received_at=OCT2)


@pytest.mark.django_db
def test_recording_leaves_an_audit_event(membership_a):
    from apps.funding.models import AuditEvent

    with tenant_scope(membership_a.tenant_id):
        row = requests.record(membership_a, kind="deletion", channel="email", received_at=OCT2)
        event = "privacy.request.deletion"
        assert AuditEvent.objects.filter(event=event, object_id=row.id).exists()


@pytest.mark.django_db
def test_a_stopped_student_sees_the_notice_page(client, user_a, domain_a, membership_a):
    with tenant_scope(membership_a.tenant_id):
        requests.record(membership_a, kind="withdrawal", channel="email", received_at=OCT2)
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302 and response["Location"] == reverse("privacy-stopped")
    assert client.get(reverse("privacy-stopped"), HTTP_HOST=domain_a.host).status_code == 200


@pytest.mark.django_db
def test_a_stopped_student_can_still_reach_deletion_logout_and_legal_pages(
    client, user_a, domain_a, membership_a
):
    with tenant_scope(membership_a.tenant_id):
        requests.record(membership_a, kind="objection", channel="email", received_at=OCT2)
    client.force_login(user_a)
    for path in (
        reverse("privacy-legal", args=["terms"]),
        "/student/account/delete/",
        "/student/account/deletion/",
        "/api/auth/logout",
    ):
        response = client.get(path, HTTP_HOST=domain_a.host)
        assert response.get("Location") != reverse("privacy-stopped"), path
    # Django's LogoutView is added by another session; the route may not exist here,
    # so assert only that the lock does not redirect it.
    response = client.post("/accounts/logout/", HTTP_HOST=domain_a.host)
    assert response.get("Location") not in (reverse("privacy-stopped"), reverse("privacy-accept"))


@pytest.mark.django_db
def test_a_student_with_only_a_declined_request_is_not_redirected(
    client, user_a, domain_a, membership_a
):
    with tenant_scope(membership_a.tenant_id):
        row = requests.record(membership_a, kind="objection", channel="email", received_at=OCT2)
        row.outcome = "declined"
        row.save()
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.get("Location") != reverse("privacy-stopped")


@pytest.mark.django_db
def test_the_record_command_logs_a_request(domain_a, membership_a, user_a):
    out = StringIO()
    call_command(
        "record_privacy_request",
        host=domain_a.host,
        email=user_a.username,
        kind="objection",
        channel="email",
        received="2026-10-02T15:00:00+00:00",
        stdout=out,
    )
    assert "reply due 2026-10-13" in out.getvalue()
    with tenant_scope(membership_a.tenant_id):
        assert PrivacyRequest.objects.filter(student=membership_a, kind="objection").count() == 1


@pytest.mark.django_db
def test_the_record_command_refuses_bad_host_student_or_date(domain_a, membership_a, user_a):
    base = {"kind": "access", "channel": "email"}
    with pytest.raises(CommandError):
        call_command(
            "record_privacy_request", host="nope.example.test", email=user_a.username, **base
        )
    with pytest.raises(CommandError):
        call_command("record_privacy_request", host=domain_a.host, email="nobody", **base)
    with pytest.raises(CommandError):
        call_command(
            "record_privacy_request",
            host=domain_a.host,
            email=user_a.username,
            received="garbage",
            **base,
        )
    with pytest.raises(CommandError):  # naive datetime would make due_at ambiguous
        call_command(
            "record_privacy_request",
            host=domain_a.host,
            email=user_a.username,
            received="2026-10-02T15:00:00",
            **base,
        )


@pytest.mark.django_db
def test_the_list_command_shows_open_requests_and_marks_overdue(domain_a, membership_a):
    with tenant_scope(membership_a.tenant_id):
        requests.record(
            membership_a,
            kind="access",
            channel="email",
            received_at=datetime(2026, 1, 5, tzinfo=UTC),
        )
        done = requests.record(membership_a, kind="correction", channel="email", received_at=OCT2)
        done.outcome = "done"
        done.save()
    out = StringIO()
    call_command("list_privacy_requests", stdout=out)
    text = out.getvalue()
    assert "access" in text and "OVERDUE" in text
    assert "correction" not in text
    open_row = PrivacyRequest._base_manager.get(kind="access")
    assert str(open_row.id) in text  # what close_privacy_request --id takes


@pytest.mark.django_db
def test_the_list_command_includes_a_tenant_without_a_verified_host(
    domain_a, membership_a, membership_b
):
    for student in (membership_a, membership_b):  # agency B has no domain at all
        with tenant_scope(student.tenant_id):
            requests.record(student, kind="objection", channel="email", received_at=OCT2)
    out = StringIO()
    call_command("list_privacy_requests", stdout=out)
    lines = out.getvalue().splitlines()
    assert any(line.startswith(domain_a.host) for line in lines)
    assert any("Agency B" in line and "student-b" in line for line in lines)


@pytest.mark.django_db(transaction=True)
def test_privacy_requests_are_tenant_isolated_behind_the_policy(
    membership_a, agency_b, rls_enforced_orm
):
    from apps.tenancy.db import tenant_transaction

    with tenant_scope(membership_a.tenant_id), tenant_transaction(membership_a.tenant_id):
        requests.record(membership_a, kind="objection", channel="email", received_at=OCT2)
    with tenant_scope(membership_a.tenant_id), tenant_transaction(membership_a.tenant_id):
        assert PrivacyRequest._base_manager.count() == 1
    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        assert PrivacyRequest._base_manager.count() == 0


@pytest.mark.django_db(transaction=True)
def test_a_request_cannot_name_a_membership_of_another_tenant(
    membership_a, agency_b, rls_enforced_orm
):
    from django.db import IntegrityError

    from apps.tenancy.db import tenant_transaction

    with tenant_scope(agency_b.id), tenant_transaction(agency_b.id):
        with pytest.raises(IntegrityError):
            PrivacyRequest.objects.create(
                student=membership_a,
                kind="access",
                channel="email",
                received_at=OCT2,
                due_at=OCT2,
            )


@pytest.mark.django_db
def test_a_resumed_outcome_lifts_the_stop(membership_a):
    with tenant_scope(membership_a.tenant_id):
        row = requests.record(membership_a, kind="withdrawal", channel="email", received_at=OCT2)
        assert requests.processing_stopped(membership_a)
        row.outcome = PrivacyRequest.Outcome.RESUMED
        row.save()
        assert not requests.processing_stopped(membership_a)
        assert row.get_outcome_display() == "Resumed at the student's request"


def _close(row, **over):
    out = StringIO()
    options = {"host": "a.example.test", "id": str(row.id), "outcome": "resumed"}
    options.update(over)
    call_command("close_privacy_request", stdout=out, **options)
    return out.getvalue()


@pytest.mark.django_db
def test_the_close_command_sets_outcome_handled_at_and_handled_by(
    domain_a, membership_a, counselor_user, counselor_membership
):
    counselor_user.email = "Counselor@Agency.test"
    counselor_user.save()
    with tenant_scope(membership_a.tenant_id):
        row = requests.record(membership_a, kind="objection", channel="email", received_at=OCT2)
    text = _close(row, handled_by_email="counselor@agency.test")
    assert "resumed" in text
    with tenant_scope(membership_a.tenant_id):
        row.refresh_from_db()
        assert row.outcome == "resumed" and row.handled_at is not None
        assert row.handled_by_id == counselor_membership.id
        assert not requests.processing_stopped(membership_a)


@pytest.mark.django_db
def test_the_close_command_refuses_a_closed_request_and_bad_arguments(
    domain_a, domain_b, membership_a, counselor_membership
):
    with tenant_scope(membership_a.tenant_id):
        row = requests.record(membership_a, kind="access", channel="email", received_at=OCT2)
    _close(row, outcome="done")
    with pytest.raises(CommandError, match="already closed"):
        _close(row, outcome="declined")
    with tenant_scope(membership_a.tenant_id):
        row.refresh_from_db()
        assert row.outcome == "done"
        other = requests.record(membership_a, kind="access", channel="email", received_at=OCT2)
    with pytest.raises(CommandError):  # another tenant's host does not see the row
        _close(other, host=domain_b.host)
    with pytest.raises(CommandError):  # a student is not staff
        _close(other, handled_by_email=membership_a.user.username)
    with pytest.raises(CommandError):
        _close(other, host="nope.example.test")
    with pytest.raises(CommandError):
        _close(other, id="not-a-uuid")


@pytest.mark.django_db(transaction=True)
def test_handled_by_cannot_name_a_membership_of_another_tenant(
    membership_a, membership_b, rls_enforced_orm
):
    from django.db import IntegrityError

    from apps.tenancy.db import tenant_transaction

    with tenant_scope(membership_b.tenant_id), tenant_transaction(membership_b.tenant_id):
        with pytest.raises(IntegrityError):
            PrivacyRequest.objects.create(
                student=membership_b,
                handled_by=membership_a,
                kind="access",
                channel="email",
                received_at=OCT2,
                due_at=OCT2,
            )
