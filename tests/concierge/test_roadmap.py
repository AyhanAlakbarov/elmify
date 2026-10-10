import pytest

from apps.tenancy.context import tenant_scope
from tests.conftest import verify_mfa_session


@pytest.mark.frontend
@pytest.mark.django_db
def test_counselor_sees_only_assigned_students(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, membership_b
):
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert str(membership_a.id) in response.content.decode()
    assert str(membership_b.id) not in response.content.decode()


@pytest.mark.django_db
def test_student_hitting_owner_dashboard_gets_clean_403_not_500(
    client, domain_a, user_a, membership_a
):
    client.force_login(user_a)
    response = client.get("/owner/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


@pytest.mark.django_db
def test_student_hitting_counselor_dashboard_gets_clean_403_not_500(
    client, domain_a, user_a, membership_a
):
    client.force_login(user_a)
    response = client.get("/counselor/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


@pytest.mark.frontend
@pytest.mark.django_db
def test_student_nav_does_not_link_to_owner_or_counselor_dashboards(
    client, domain_a, user_a, membership_a
):
    client.force_login(user_a)
    response = client.get("/student/", HTTP_HOST=domain_a.host)
    assert response.status_code == 200
    body = response.content.decode()
    assert 'href="/owner/"' not in body
    assert 'href="/counselor/"' not in body
    assert 'href="/student/"' in body


@pytest.mark.django_db
def test_manual_stage_requires_owner_and_deadline(agency_a, membership_a, counselor_membership):
    from datetime import timedelta

    from django.utils import timezone

    from apps.concierge.models import RoadmapItem

    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner=counselor_membership,
            deadline=timezone.now() + timedelta(days=14),
        )
    assert item.state == RoadmapItem.State.PENDING


@pytest.mark.django_db
def test_no_payment_or_portal_automation_call(agency_a):
    import inspect

    import apps.concierge.services as services_mod

    source = inspect.getsource(services_mod)
    for banned in ("requests.post(", "stripe.", "playwright.", "selenium."):
        assert banned not in source


@pytest.mark.frontend
@pytest.mark.django_db
def test_counselor_marks_roadmap_item_done(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a
):
    from datetime import timedelta

    from django.utils import timezone

    from apps.concierge.models import ManualOperation, RoadmapItem

    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner=counselor_membership,
            deadline=timezone.now() + timedelta(days=14),
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        f"/counselor/roadmap/{item.id}/done/",
        {"description": "Filed the form in person"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        item.refresh_from_db()
        assert item.state == RoadmapItem.State.DONE
        assert ManualOperation.objects.filter(roadmap_item=item).exists()

    # double-close is rejected, not silently re-recorded — and the counselor
    # gets the dashboard back with an inline alert, not a bare 403 text page
    # (design-lint-baseline defect 5)
    response = client.post(
        f"/counselor/roadmap/{item.id}/done/",
        {"description": "again"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 403
    body = response.content.decode()
    assert 'role="alert"' in body
    assert "already done" in body
    with tenant_scope(agency_a.id):
        assert ManualOperation.objects.filter(roadmap_item=item).count() == 1


@pytest.mark.django_db
def test_student_acknowledges_notification(client, agency_a, domain_a, user_a, membership_a):
    from datetime import timedelta

    from django.utils import timezone

    from apps.concierge.models import Notification, RoadmapItem

    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner_kind=RoadmapItem.OwnerKind.AGENT,
            deadline=timezone.now() + timedelta(days=14),
        )
        notification = Notification.objects.create(
            tenant=agency_a,
            recipient=membership_a,
            roadmap_item=item,
            message="Upload your transcript",
        )
    client.force_login(user_a)
    response = client.post(
        f"/student/notifications/{notification.id}/acknowledge/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        notification.refresh_from_db()
        assert notification.acknowledged_at is not None


@pytest.mark.django_db
def test_student_sends_message_to_assigned_counselor(
    client, agency_a, domain_a, user_a, membership_a, counselor_membership
):
    from apps.concierge.models import ConversationMessage
    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(user_a)
    response = client.post(
        "/student/messages/send/", {"body": "When is my deadline?"}, HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        message = ConversationMessage.objects.get(student=membership_a)
        assert message.sender_id == membership_a.id
        assert message.counselor_id == counselor_membership.id
        assert message.body == "When is my deadline?"


@pytest.mark.frontend
@pytest.mark.django_db(transaction=True)
def test_student_messages_are_rate_limited_and_length_capped(
    client, agency_a, domain_a, user_a, membership_a, counselor_membership
):
    from django.core.cache import cache

    from apps.tenancy.models import CounselorAssignment

    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    cache.clear()
    client.force_login(user_a)

    oversized = client.post(
        "/student/messages/send/", {"body": "x" * 4001}, HTTP_HOST=domain_a.host
    )
    assert oversized.status_code == 400
    body = oversized.content.decode()
    # Inline re-render (design-lint-baseline defect 5, student side): the
    # dashboard comes back with an alert and the typed message preserved.
    assert 'role="alert"' in body
    assert "4000 characters or fewer" in body
    assert "x" * 4001 in body

    for _ in range(19):
        assert (
            client.post(
                "/student/messages/send/", {"body": "hi"}, HTTP_HOST=domain_a.host
            ).status_code
            == 302
        )
    blocked = client.post("/student/messages/send/", {"body": "hi"}, HTTP_HOST=domain_a.host)
    assert blocked.status_code == 429
    assert "Too many messages." in blocked.content.decode()


@pytest.mark.parametrize("lock", ["deletion", "objection"])
@pytest.mark.django_db
def test_counselor_cannot_mark_a_paused_students_item_done(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, lock
):
    """The middleware locks only the requester; the target student's locks are checked here."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.audit.models import DeletionRequest
    from apps.concierge.models import ManualOperation, RoadmapItem
    from apps.privacy.models import PrivacyRequest

    now = timezone.now()
    with tenant_scope(agency_a.id):
        item = RoadmapItem.objects.create(
            tenant=agency_a,
            student=membership_a,
            stage=RoadmapItem.Stage.DOCUMENTS,
            owner=counselor_membership,
            deadline=now + timedelta(days=14),
        )
        if lock == "deletion":
            DeletionRequest.objects.create(
                tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
            )
        else:
            PrivacyRequest.objects.create(
                tenant_id=agency_a.id, student=membership_a, kind="objection",
                channel="email", received_at=now, due_at=now + timedelta(days=9),
            )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = client.post(
        f"/counselor/roadmap/{item.id}/done/",
        {"description": "Filed the form in person"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 409
    assert "changes are paused" in response.content.decode()
    with tenant_scope(agency_a.id):
        item.refresh_from_db()
        assert item.state == RoadmapItem.State.PENDING
        assert not ManualOperation.objects.filter(roadmap_item=item).exists()
