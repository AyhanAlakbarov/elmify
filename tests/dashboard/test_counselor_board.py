import json
from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.audit.models import DeletionRequest
from apps.concierge.models import ConversationMessage, DocumentVersion, Notification, RoadmapItem
from apps.dashboard.board import board_for
from apps.dashboard.needs import items_for
from apps.funding.models import AuditEvent
from apps.mailbox.models import MailboxConnection, MailSignal
from apps.portals.models import Application
from apps.privacy.models import PrivacyRequest
from apps.tenancy.context import tenant_scope
from apps.tenancy.models import CounselorAssignment
from tests.conftest import verify_mfa_session

from .conftest import add_card

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def counselor_client(client, agency_a, counselor_user, counselor_membership, membership_a):
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    return client


def _audited(agency, actor, event) -> bool:
    with tenant_scope(agency.id):
        return AuditEvent.objects.filter(actor=actor, event=event).exists()


def _notification(agency, student) -> Notification:
    item = RoadmapItem.objects.create(
        tenant=agency, student=student, stage=RoadmapItem.Stage.MONITORING,
        owner_kind=RoadmapItem.OwnerKind.AGENT, deadline=timezone.now() + timedelta(days=3),
    )
    return Notification.objects.create(
        tenant=agency, recipient=student, roadmap_item=item, message="tum.de wrote."
    )


def _offer(agency, student, card) -> MailSignal:
    connection = MailboxConnection.objects.create(
        tenant=agency, membership=student, provider="MICROSOFT", address="a@o.test"
    )
    return MailSignal.objects.create(
        tenant=agency, connection=connection, provider_message_id="m-1",
        sender_domain="tum.de", received_at=timezone.now(), application=card,
        label="DECISION", offered_programme="M.Sc. Data Engineering", trusted=True,
    )


def test_the_counselor_sees_the_students_board_without_start(
    counselor_client, agency_a, domain_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
    base = f"/counselor/students/{membership_a.id}/"
    body = counselor_client.get(base, HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics" in body
    assert "Needs you now" in body
    assert "What each application needs" in body
    assert "/start/" not in body
    assert "/kit/" not in body
    assert f'action="{base}applications/{application.id}/remove/"' in body
    assert counselor_client.get(f"{base}gap-interview/", HTTP_HOST=domain_a.host).status_code == 200


def test_the_counselors_needs_point_at_counselor_routes(
    agency_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        note = _notification(agency_a, membership_a)
        offer = _offer(agency_a, membership_a, card)
        board = board_for(membership_a, counselor_view=True)
        items = items_for(membership_a, board=board, counselor_view=True)
    base = f"/counselor/students/{membership_a.id}/"
    acknowledge = [item.acknowledge_url for item in items if item.acknowledge_url]
    assert acknowledge == [f"{base}notifications/{note.id}/acknowledge/"]
    offers = [item for item in items if item.ignore_url]
    assert [(item.url, item.ignore_url) for item in offers] == [
        (f"{base}offers/{offer.id}/accept/", f"{base}offers/{offer.id}/ignore/")
    ]
    # Every URL on the counsellor's list stays on the counsellor's side.
    assert not [item for item in items if item.url.startswith("/student/")]
    assert "Pair" not in [item.button for item in items]


def test_counselor_writes_are_audited_with_the_counselor_as_actor(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership, pack
) -> None:
    programme, award = pack
    base = f"/counselor/students/{membership_a.id}/"
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, portal=False, state="SUBMITTED")
        note = _notification(agency_a, membership_a)
    host = {"HTTP_HOST": domain_a.host}
    counselor_client.post(f"{base}applications/{card.id}/outcome/", {"outcome": "ADMITTED"}, **host)
    counselor_client.post(
        f"{base}applications/{card.id}/portal/", {"form_url": "https://campus.tum.de/apply"}, **host
    )
    counselor_client.post(f"{base}applications/add/{award.id}/", **host)
    counselor_client.post(f"{base}notifications/{note.id}/acknowledge/", **host)
    counselor_client.post(f"{base}messages/send/", {"body": "Your transcript arrived."}, **host)
    with tenant_scope(agency_a.id):
        offer = _offer(agency_a, membership_a, card)
    counselor_client.post(f"{base}offers/{offer.id}/accept/", **host)
    # A second click finds the offer handled: a 404, never a 500.
    again = counselor_client.post(f"{base}offers/{offer.id}/accept/", **host)
    assert again.status_code == 404

    with tenant_scope(agency_a.id):
        assert Application.objects.filter(program_id=offer.id).exists()
        card.refresh_from_db()
        note.refresh_from_db()
        assert (card.outcome, card.outcome_source) == ("ADMITTED", "PERSON")
        assert card.portal_form.portal_host == "campus.tum.de"
        assert Application.objects.filter(candidate=award).exists()
        assert note.acknowledged_at is not None
        message = ConversationMessage.objects.get(student=membership_a)
        assert message.sender_id == counselor_membership.id
    for event in (
        "application.outcome_recorded", "application.portal_recorded", "application.added",
        "notification.acknowledged", "message.sent", "application.offer_accepted",
    ):
        assert _audited(agency_a, counselor_membership, event), event


def test_a_repeat_acknowledge_is_404_and_audits_once(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership
) -> None:
    with tenant_scope(agency_a.id):
        note = _notification(agency_a, membership_a)
    url = f"/counselor/students/{membership_a.id}/notifications/{note.id}/acknowledge/"
    assert counselor_client.post(url, HTTP_HOST=domain_a.host).status_code == 302
    assert counselor_client.post(url, HTTP_HOST=domain_a.host).status_code == 404
    with tenant_scope(agency_a.id):
        assert AuditEvent.objects.filter(
            actor=counselor_membership, event="notification.acknowledged"
        ).count() == 1


def test_the_counselor_ignores_an_offer(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        card = add_card(agency_a, membership_a, programme, state="SUBMITTED")
        offer = _offer(agency_a, membership_a, card)
    response = counselor_client.post(
        f"/counselor/students/{membership_a.id}/offers/{offer.id}/ignore/", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        offer.refresh_from_db()
    assert offer.offer_handled_at is not None
    assert _audited(agency_a, counselor_membership, "application.offer_ignored")


def test_an_empty_message_comes_back_inline(
    counselor_client, agency_a, domain_a, membership_a
) -> None:
    response = counselor_client.post(
        f"/counselor/students/{membership_a.id}/messages/send/", {"body": "   "},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 403
    body = response.content.decode()
    assert 'role="alert"' in body
    assert "A message is required." in body
    with tenant_scope(agency_a.id):
        assert not ConversationMessage.objects.filter(student=membership_a).exists()


def test_the_counselor_registers_an_upload_for_the_student(
    counselor_client, agency_a, domain_a, membership_a, counselor_membership, monkeypatch
) -> None:
    import apps.dashboard.views as views

    monkeypatch.setattr(
        views, "presigned_upload", lambda document: {"url": "https://s3.test/", "fields": {}}
    )
    response = counselor_client.post(
        f"/counselor/students/{membership_a.id}/uploads/", json.dumps({"kind": "PASSPORT"}),
        content_type="application/json", HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        document = DocumentVersion.objects.get(id=response.json()["document_id"])
    assert (document.student_id, document.kind) == (membership_a.id, "PASSPORT")
    assert _audited(agency_a, counselor_membership, "document.upload_registered")


_EVERY_ROUTE = [
    ("get", ""),
    ("get", "gap-interview/"),
    ("post", "gap-interview/"),
    ("post", "messages/send/"),
    ("post", "uploads/"),
    ("post", f"applications/{uuid4()}/outcome/"),
    ("post", f"applications/{uuid4()}/portal/"),
    ("post", f"applications/{uuid4()}/remove/"),
    ("post", f"applications/add/{uuid4()}/"),
    ("post", f"notifications/{uuid4()}/acknowledge/"),
    ("post", f"offers/{uuid4()}/accept/"),
    ("post", f"offers/{uuid4()}/ignore/"),
]


@pytest.mark.parametrize(("method", "suffix"), _EVERY_ROUTE)
def test_an_unassigned_counselor_gets_404_everywhere(
    client, domain_a, counselor_user, counselor_membership, membership_a, method, suffix
) -> None:
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = getattr(client, method)(
        f"/counselor/students/{membership_a.id}/{suffix}", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404


@pytest.mark.parametrize(("method", "suffix"), _EVERY_ROUTE)
def test_an_ended_assignment_gets_404_everywhere(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a, method, suffix
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a, active=False
        )
    client.force_login(counselor_user)
    verify_mfa_session(client, counselor_user)
    response = getattr(client, method)(
        f"/counselor/students/{membership_a.id}/{suffix}", HTTP_HOST=domain_a.host
    )
    assert response.status_code == 404


def test_a_student_cannot_open_a_counselor_board(client, domain_a, user_a, membership_a) -> None:
    client.force_login(user_a)
    response = client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 404


def test_the_board_needs_staff_mfa(
    client, agency_a, domain_a, counselor_user, counselor_membership, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        CounselorAssignment.objects.create(
            tenant=agency_a, counselor=counselor_membership, student=membership_a
        )
    client.force_login(counselor_user)
    response = client.get(f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host)
    assert response.status_code == 403


_PAUSED = {
    "deletion": "This student has asked to delete their account; changes are paused",
    "objection": "This student has stopped the processing of their data; changes are paused",
}


@pytest.fixture(params=sorted(_PAUSED))
def paused(request, agency_a, membership_a) -> str:
    """The TARGET student is locked (the middleware checks only the requester)."""
    now = timezone.now()
    with tenant_scope(agency_a.id):
        if request.param == "deletion":
            DeletionRequest.objects.create(
                tenant=agency_a, student=membership_a, state="REQUESTED", reason="OTHER"
            )
        else:
            PrivacyRequest.objects.create(
                tenant_id=agency_a.id, student=membership_a, kind="objection", channel="email",
                received_at=now, due_at=now + timedelta(days=9),
            )
    return _PAUSED[request.param]


def _populated(agency, student, programme) -> None:
    """A card with an outcome form, a notification with Acknowledge, and the upload form."""
    add_card(agency, student, programme, state="SUBMITTED", outcome="ADMITTED")
    _notification(agency, student)


def test_an_active_students_board_has_its_forms(
    counselor_client, agency_a, domain_a, membership_a, pack
) -> None:
    """Positive control for the read-only test below: the same rows carry forms."""
    programme, _award = pack
    with tenant_scope(agency_a.id):
        _populated(agency_a, membership_a, programme)
    body = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    base = f"/counselor/students/{membership_a.id}/"
    assert f'action="{base}notifications/' in body
    assert "/outcome/" in body
    assert f'data-upload="{base}uploads/"' in body
    assert f'action="{base}messages/send/"' in body
    for sentence in _PAUSED.values():
        assert sentence not in body


def test_a_paused_students_board_is_read_only(
    counselor_client, paused, agency_a, domain_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        _populated(agency_a, membership_a, programme)
    body = counselor_client.get(
        f"/counselor/students/{membership_a.id}/", HTTP_HOST=domain_a.host
    ).content.decode()
    assert paused in body
    assert "M.Sc. Informatics" in body
    assert "tum.de wrote." in body
    # The only form left is base.html's logout.
    assert body.count("<form") == 1


@pytest.mark.parametrize(
    ("method", "suffix"), [route for route in _EVERY_ROUTE if route != ("get", "")]
)
def test_every_write_is_refused_while_the_student_is_paused(
    counselor_client, paused, agency_a, domain_a, membership_a, counselor_membership,
    method, suffix,
) -> None:
    response = getattr(counselor_client, method)(
        f"/counselor/students/{membership_a.id}/{suffix}", {"body": "hello"},
        HTTP_HOST=domain_a.host,
    )
    assert response.status_code == 409
    with tenant_scope(agency_a.id):
        assert not AuditEvent.objects.filter(actor=counselor_membership).exists()
        assert not ConversationMessage.objects.filter(student=membership_a).exists()


def _counselor_transcript(counselor_client, domain, student, monkeypatch, **body):
    import apps.dashboard.views as views

    monkeypatch.setattr(
        views, "presigned_upload", lambda document: {"url": "https://s3.test/", "fields": {}}
    )
    return counselor_client.post(
        f"/counselor/students/{student.id}/uploads/",
        json.dumps({"kind": "TRANSCRIPT", **body}),
        content_type="application/json", HTTP_HOST=domain.host,
    )


def test_a_counselor_transcript_for_an_unpaid_student_is_refused(
    counselor_client, agency_a, domain_a, membership_a, monkeypatch
) -> None:
    response = _counselor_transcript(
        counselor_client, domain_a, membership_a, monkeypatch, role="ORIGINAL"
    )
    assert (response.status_code, response.json()) == (402, {"error": "cycle_unpaid"})
    with tenant_scope(agency_a.id):
        assert not DocumentVersion.objects.filter(student=membership_a).exists()


def test_a_counselor_transcript_registers_like_the_students_own(
    counselor_client, agency_a, domain_a, membership_a, paid_cycle_a, counselor_membership,
    monkeypatch,
) -> None:
    from apps.documents.models import TranscriptUpload

    response = _counselor_transcript(
        counselor_client, domain_a, membership_a, monkeypatch, role="TRANSLATION"
    )
    assert response.status_code == 201
    with tenant_scope(agency_a.id):
        upload = TranscriptUpload.objects.get(document_id=response.json()["document_id"])
    assert (upload.role, upload.mode, upload.cycle_id) == ("TRANSLATION", "ADD", paid_cycle_a.id)
    assert _audited(agency_a, counselor_membership, "document.upload_registered")


def test_a_counselor_transcript_waits_behind_a_pending_replace(
    counselor_client, agency_a, domain_a, membership_a, paid_cycle_a, monkeypatch
) -> None:
    first = _counselor_transcript(
        counselor_client, domain_a, membership_a, monkeypatch, role="ORIGINAL", mode="REPLACE"
    )
    assert first.status_code == 201
    response = _counselor_transcript(
        counselor_client, domain_a, membership_a, monkeypatch, role="ORIGINAL"
    )
    assert (response.status_code, response.json()) == (409, {"error": "replace_pending"})


def test_a_counselor_transcript_without_a_role_is_refused(
    counselor_client, agency_a, domain_a, membership_a, paid_cycle_a, monkeypatch
) -> None:
    response = _counselor_transcript(counselor_client, domain_a, membership_a, monkeypatch)
    assert (response.status_code, response.json()) == (400, {"error": "invalid_role"})
    with tenant_scope(agency_a.id):
        assert not DocumentVersion.objects.filter(student=membership_a).exists()
