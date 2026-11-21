from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.concierge.models import ConversationMessage
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment, Membership
from tests.dashboard.conftest import add_card, pack  # noqa: F401
from tests.funding.conftest import make_db_candidate

pytestmark = pytest.mark.django_db
PAGE = "/student/messages/"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


def _signal(agency, student, *, application=None, **fields):
    connection, _ = MailboxConnection.objects.get_or_create(
        tenant=agency, membership=student, provider="MICROSOFT",
        defaults={"address": f"{student.id}@outlook.test"},
    )
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id=f"m-{uuid4()}",
        sender_domain="tum.de", received_at=timezone.now(), application=application, **fields,
    )


def test_mail_is_grouped_by_application_and_unlinked_mail_has_its_own_group(
    client, agency_a, domain_a, user_a, membership_a, pack  # noqa: F811
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _signal(agency_a, membership_a, application=application, label="DOCUMENT_REQUEST",
                document_name="Final transcript", trusted=True, sender_authenticated=True)
        _signal(agency_a, membership_a, label="DECISION", outcome="ADMITTED", trusted=False)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "<h3>M.Sc. Informatics</h3>" in body
    assert "asks for: Final transcript" in body
    assert "<h3>Not about one application</h3>" in body
    assert "the email reads: Admitted (unverified)" in body
    assert "sender not verified" in body


def test_another_students_mail_is_never_listed(
    client, agency_a, domain_a, user_a, membership_a, user_b
) -> None:
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        _signal(agency_a, other, label="FEE")
    client.force_login(user_a)
    assert "A fee is due" not in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()


def test_writing_from_the_messages_page_comes_back_to_it(
    client, agency_a, domain_a, user_a, membership_a, counselor_membership
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
        ConversationMessage.objects.create(
            tenant=agency_a, student=membership_a, counselor=counselor_membership,
            sender=counselor_membership, body="Your transcript arrived.",
        )
    client.force_login(user_a)
    assert "Your transcript arrived." in client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()

    sent = client.post(
        "/student/messages/send/", {"body": "Thanks", "return_to": "messages"},
        HTTP_HOST=domain_a.host,
    )
    assert sent["Location"] == PAGE

    refused = client.post(
        "/student/messages/send/", {"body": "x" * 4001, "return_to": "messages"},
        HTTP_HOST=domain_a.host,
    )
    body = refused.content.decode()
    assert refused.status_code == 400
    assert "<h1>Messages</h1>" in body
    assert 'role="alert"' in body
    assert "x" * 4001 in body


def _page(client, domain_a, user_a):
    client.force_login(user_a)
    return client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()


def test_unlabelled_mail_reading_failed_only_after_max_attempts(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    from apps.mailbox.sync import MAX_CLASSIFY_ATTEMPTS

    with tenant_scope(agency_a.id):
        _signal(agency_a, membership_a, classify_attempts=MAX_CLASSIFY_ATTEMPTS)
    body = _page(client, domain_a, user_a)
    assert "open the email to read it" in body
    assert "reading…" not in body


def test_unlabelled_content_tier_mail_below_the_limit_is_still_reading(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _signal(agency_a, membership_a, classify_attempts=1)
    body = _page(client, domain_a, user_a)
    assert "reading…" in body
    assert "open the email to read it" not in body


def test_unlabelled_metadata_tier_mail_is_neither_reading_nor_failed(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        signal = _signal(agency_a, membership_a)
        MailboxConnection.objects.filter(id=signal.connection_id).update(tier="METADATA")
    body = _page(client, domain_a, user_a)
    assert "this inbox connection does not read mail" in body
    assert "reading…" not in body
    assert "open the email to read it" not in body


def test_messages_context_exposes_no_student_only_action(
    agency_a, membership_a
) -> None:
    from apps.concierge.views import messages_context

    with tenant_scope(agency_a.id):
        context = messages_context(membership_a)
    assert set(context) == {
        "mail_groups", "conversation", "has_counselor", "has_mailbox", "outcome_labels"
    }


def test_a_hostile_return_to_falls_back_to_the_dashboard(
    client, agency_a, domain_a, user_a, membership_a, counselor_membership
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(user_a)
    sent = client.post(
        "/student/messages/send/", {"body": "Hi", "return_to": "https://evil.test/"},
        HTTP_HOST=domain_a.host,
    )
    assert sent["Location"] == "/student/"


def test_clean_message_body_is_the_one_rule() -> None:
    from apps.concierge.services import MessageBodyError, clean_message_body

    assert clean_message_body("  hi  ") == "hi"
    with pytest.raises(MessageBodyError) as empty:
        clean_message_body("   ")
    assert empty.value.status == 403
    with pytest.raises(MessageBodyError) as long:
        clean_message_body("x" * 4001)
    assert long.value.status == 400
    assert clean_message_body("x" * 4000) == "x" * 4000


@pytest.mark.parametrize(
    ("trusted", "authenticated", "fact"),
    [(True, True, True), (True, False, False), (False, False, False)],
)
def test_only_authenticated_mail_states_a_reading_as_fact(
    client, agency_a, domain_a, user_a, membership_a, trusted, authenticated, fact
) -> None:
    with tenant_scope(agency_a.id):
        _signal(
            agency_a, membership_a, label="DECISION", outcome="ADMITTED",
            document_name="Transcript", offered_programme="MSc Data",
            interview_at=timezone.now(), trusted=trusted, sender_authenticated=authenticated,
        )
    body = _page(client, domain_a, user_a)
    assert ("says: Admitted" in body) is fact
    assert ("asks for: Transcript" in body) is fact
    assert ("offers a place in: MSc Data" in body) is fact
    assert ("the email reads: Admitted (unverified)" in body) is not fact
    assert ("(unverified)" in body) is not fact


def test_same_titled_applications_and_the_unlinked_group_stay_separate(
    client, agency_a, domain_a, user_a, membership_a, pack  # noqa: F811
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        first = add_card(agency_a, membership_a, programme)
        twin = make_db_candidate(
            agency_a, programme.run, program_name="M.Sc. Informatics", funding_gap="1200.00"
        )
        twin.program_id = programme.program_id
        twin.save(update_fields=["program_id"])
        second = add_card(agency_a, membership_a, twin)
        _signal(agency_a, membership_a, application=first, label="FEE")
        _signal(agency_a, membership_a, application=second, label="FEE")
        _signal(agency_a, membership_a, label="FEE")
    body = _page(client, domain_a, user_a)
    assert body.count("<h3>M.Sc. Informatics</h3>") == 2
    assert body.count("<h3>Not about one application</h3>") == 1


def test_empty_text_mentions_settings_only_without_an_active_mailbox(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    assert "Connect your inbox in Settings." in _page(client, domain_a, user_a)
    with tenant_scope(agency_a.id):
        MailboxConnection.objects.create(
            tenant=agency_a, membership=membership_a, provider="MICROSOFT",
            address="a@outlook.test",
        )
    body = _page(client, domain_a, user_a)
    assert "No mail recognised yet." in body
    assert "Connect your inbox" not in body
