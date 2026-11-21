# ruff: noqa: F811 -- fixtures imported by name and requested as arguments
"""The staff desk: only Elmify staff, every student, a team inbox that can be answered."""

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.concierge.models import ConversationMessage
from apps.funding.models import AuditEvent
from apps.tenancy.context import tenant_scope
from tests.conftest import verify_mfa_session
from tests.portals.test_staff_file_access import _login, _staff

pytestmark = pytest.mark.django_db

PAGES = ["staff-overview", "staff-students", "staff-inbox"]


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def student_client(agency_a, user_a, membership_a):
    other = Client()
    other.force_login(user_a)
    return other


@pytest.fixture
def counselor_client(agency_a, counselor_user, counselor_membership):
    other = Client()
    other.force_login(counselor_user)
    verify_mfa_session(other, counselor_user)
    return other


@pytest.fixture
def staff_client(client, agency_a, domain_a):
    user, membership = _staff(agency_a)
    user.email = "team@elmify.test"
    user.save()
    _login(client, user)
    client.staff = membership
    return client


@pytest.mark.parametrize("name", PAGES)
def test_staff_open_every_page(staff_client, domain_a, name) -> None:
    assert staff_client.get(reverse(name), HTTP_HOST=domain_a.host).status_code == 200


@pytest.mark.parametrize("name", PAGES)
def test_a_student_is_refused_every_page(student_client, domain_a, name) -> None:
    assert student_client.get(reverse(name), HTTP_HOST=domain_a.host).status_code == 403


def test_a_counsellor_is_refused(counselor_client, domain_a, membership_a) -> None:
    for url in (reverse("staff-students"), reverse("staff-student", args=[membership_a.id])):
        assert counselor_client.get(url, HTTP_HOST=domain_a.host).status_code == 403


def test_signed_out_visitors_are_sent_to_login(client, domain_a) -> None:
    assert client.get(reverse("staff-students"), HTTP_HOST=domain_a.host).status_code == 302


def test_staff_list_and_search_students(staff_client, domain_a, membership_a) -> None:
    body = staff_client.get(reverse("staff-students"), HTTP_HOST=domain_a.host).content.decode()
    assert reverse("staff-student", args=[membership_a.id]) in body
    miss = staff_client.get(
        reverse("staff-students") + "?q=no-such-person", HTTP_HOST=domain_a.host
    ).content.decode()
    assert reverse("staff-student", args=[membership_a.id]) not in miss


def test_opening_a_student_is_audited(staff_client, domain_a, agency_a, membership_a) -> None:
    response = staff_client.get(
        reverse("staff-student", args=[membership_a.id]), HTTP_HOST=domain_a.host
    )
    assert response.status_code == 200
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            event="staff.student_viewed", object_id=membership_a.id, actor=staff_client.staff
        ).exists()


def test_a_student_message_without_counsellor_reaches_the_inbox_and_emails_staff(
    student_client, staff_client, domain_a, agency_a, membership_a,
    django_capture_on_commit_callbacks,
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        response = student_client.post(
            reverse("concierge-send-student-message"), {"body": "Hello team"},
            HTTP_HOST=domain_a.host,
        )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        message = ConversationMessage.objects.get(student=membership_a)
    assert message.counselor_id is None and message.read_by_staff_at is None
    assert [m.to for m in mail.outbox] == [["team@elmify.test"]]
    assert "Hello team" not in mail.outbox[0].body  # no text in the mail


def test_staff_read_and_reply_and_student_is_emailed(
    staff_client, domain_a, agency_a, membership_a, user_a, django_capture_on_commit_callbacks
) -> None:
    user_a.email = "student@example.test"
    user_a.save()
    with tenant_scope(agency_a.id):
        ConversationMessage.objects.create(
            tenant=agency_a, student=membership_a, counselor=None, sender=membership_a,
            body="Can you check my CV?",
        )
    inbox = staff_client.get(reverse("staff-inbox"), HTTP_HOST=domain_a.host).content.decode()
    assert "Can you check my CV?" in inbox and "1 new" in inbox
    thread_url = reverse("staff-thread", args=[membership_a.id])
    assert "Can you check my CV?" in staff_client.get(
        thread_url, HTTP_HOST=domain_a.host
    ).content.decode()
    with tenant_scope(agency_a.id):
        assert not ConversationMessage.objects.filter(read_by_staff_at__isnull=True).exists()
    with django_capture_on_commit_callbacks(execute=True):
        sent = staff_client.post(
            reverse("staff-reply", args=[membership_a.id]), {"body": "Yes, send it."},
            HTTP_HOST=domain_a.host,
        )
    assert sent.status_code == 302
    with tenant_scope(agency_a.id):
        reply = ConversationMessage.objects.get(body="Yes, send it.")
        assert reply.sender_id == staff_client.staff.id and reply.student_id == membership_a.id
        assert AuditEvent.objects.filter(event="staff.message_sent").exists()
    assert [m.to for m in mail.outbox] == [["student@example.test"]]
    assert mail.outbox[-1].subject == "Elmify replied to your message"
    assert "Yes, send it." not in mail.outbox[-1].body


def test_an_empty_reply_is_refused(staff_client, domain_a, agency_a, membership_a) -> None:
    response = staff_client.post(
        reverse("staff-reply", args=[membership_a.id]), {"body": "   "}, HTTP_HOST=domain_a.host
    )
    assert response.status_code >= 400
    with tenant_scope(agency_a.id):
        assert not ConversationMessage.objects.exists()


def test_staff_never_edit_a_students_profile(staff_client, domain_a, membership_a) -> None:
    for url in ("/student/profile/", "/student/consultation/"):
        assert staff_client.get(url, HTTP_HOST=domain_a.host).status_code in (403, 404)


def test_staff_are_sent_to_the_desk_from_the_bare_host(staff_client, domain_a) -> None:
    response = staff_client.get("/", HTTP_HOST=domain_a.host)
    assert response.status_code == 302 and response["Location"] == reverse("staff-overview")


def test_a_paused_students_page_is_a_404(staff_client, domain_a, membership_a, monkeypatch) -> None:
    monkeypatch.setattr("apps.staffdesk.views.staff_may_view", lambda staff, student: False)
    assert staff_client.get(
        reverse("staff-student", args=[membership_a.id]), HTTP_HOST=domain_a.host
    ).status_code == 404


def test_make_staff_command(agency_a, domain_a, user_b) -> None:
    from django.core.management import call_command

    call_command("make_staff", username=user_b.get_username(), agency_host=domain_a.host)
    with tenant_scope(agency_a.id):
        from apps.tenancy.models import Membership

        assert Membership.objects.filter(
            user=user_b, role=Membership.Role.PLATFORM_ADMIN, active=True
        ).exists()
