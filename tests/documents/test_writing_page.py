"""The CV & letters page: what it shows, and the letter door's two POSTs."""

from unittest.mock import patch

import pytest
from botocore.exceptions import EndpointConnectionError
from django.utils import timezone

from apps.documents.models import DocumentDraft, VerifiedFact
from apps.tenancy.context import tenant_scope
from tests.dashboard import conftest as dashboard_conftest
from tests.dashboard.conftest import add_card

pytestmark = pytest.mark.django_db
pack = dashboard_conftest.pack
PAGE = "/student/writing/"
ENQUEUE = "apps.documents.writing.enqueue_document_work"


def _identity(agency, student, *, confirmed=True):
    return VerifiedFact.objects.create(
        tenant=agency, student=student, category=VerifiedFact.Category.IDENTITY,
        payload={"full_name": "Aysel Example"},
        source_tier=VerifiedFact.SourceTier.STUDENT_STATEMENT, source_ref="upload:test",
        created_by=student, confirmed_by=student if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
    )


def _letter(agency, student, programme_id, *, status=DocumentDraft.Status.DRAFT, version=1):
    return DocumentDraft.objects.create(
        tenant=agency, student=student, kind=DocumentDraft.Kind.MOTIVATION_LETTER,
        version=version, programme_id=programme_id, status=status,
        content={"language": "en", "units": [
            {"archetype": "opening", "text": "I am applying because chemistry is my field."},
        ]},
    )


def test_the_page_lists_unconfirmed_details_in_words(
    client, agency_a, domain_a, user_a, membership_a
) -> None:
    with tenant_scope(agency_a.id):
        _identity(agency_a, membership_a, confirmed=False)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "Aysel Example" in body
    assert 'data-api-post="/api/documents/facts/confirm"' in body
    # Nothing confirmed yet, so the CV cannot be written.
    assert 'data-api-post="/api/documents/generate"' not in body


def test_a_letter_draft_is_shown_with_its_text_beside_its_application(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        add_card(agency_a, membership_a, programme)
        _letter(agency_a, membership_a, programme.program_id)
    client.force_login(user_a)
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert "M.Sc. Informatics" in body
    assert "I am applying because chemistry is my field." in body
    assert "Draft 1" in body


def test_write_queues_a_letter_for_a_programme_and_marks_it_queued(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _identity(agency_a, membership_a)
    client.force_login(user_a)
    with patch(ENQUEUE) as enqueue:
        response = client.post(
            f"/student/writing/letters/{application.id}/write/", HTTP_HOST=domain_a.host
        )
    assert response.status_code == 302
    message = enqueue.call_args.args[0]
    assert (message.action, message.kind) == ("generate", "MOTIVATION_LETTER")
    assert message.application_id == application.id
    assert message.programme_id == programme.program_id
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert application.letter_state == "QUEUED"


def test_write_refuses_without_a_confirmed_name(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
    client.force_login(user_a)
    with patch(ENQUEUE) as enqueue:
        client.post(f"/student/writing/letters/{application.id}/write/", HTTP_HOST=domain_a.host)
    enqueue.assert_not_called()


def test_a_scholarship_card_gets_no_letter(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    _programme, award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, award)
        _identity(agency_a, membership_a)
    client.force_login(user_a)
    with patch(ENQUEUE) as enqueue:
        client.post(f"/student/writing/letters/{application.id}/write/", HTTP_HOST=domain_a.host)
    enqueue.assert_not_called()
    body = client.get(PAGE, HTTP_HOST=domain_a.host).content.decode()
    assert f"/student/writing/letters/{application.id}/write/" not in body


def test_a_queue_outage_leaves_the_card_as_it_was(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        _identity(agency_a, membership_a)
    client.force_login(user_a)
    with patch(ENQUEUE, side_effect=EndpointConnectionError(endpoint_url="https://sqs")):
        response = client.post(
            f"/student/writing/letters/{application.id}/write/", HTTP_HOST=domain_a.host
        )
    assert response.status_code == 302
    with tenant_scope(agency_a.id):
        application.refresh_from_db()
    assert application.letter_state == ""


def test_approve_queues_the_check_and_never_approves_in_the_web_tier(
    client, agency_a, domain_a, user_a, membership_a, pack
) -> None:
    programme, _award = pack
    with tenant_scope(agency_a.id):
        application = add_card(agency_a, membership_a, programme)
        draft = _letter(agency_a, membership_a, programme.program_id)
    client.force_login(user_a)
    with patch(ENQUEUE) as enqueue:
        client.post(f"/student/writing/letters/{draft.id}/approve/", HTTP_HOST=domain_a.host)
    message = enqueue.call_args.args[0]
    assert (message.action, message.draft_id, message.application_id) == (
        "approve_letter", draft.id, application.id,
    )
    with tenant_scope(agency_a.id):
        draft.refresh_from_db()
        application.refresh_from_db()
    assert draft.status == DocumentDraft.Status.DRAFT
    assert application.letter_state == "CHECKING"


def test_another_students_letter_cannot_be_approved(
    client, agency_a, domain_a, user_a, user_b, membership_a, pack
) -> None:
    from apps.tenancy.models import Membership

    programme, _award = pack
    with tenant_scope(agency_a.id):
        other = Membership.objects.create(
            tenant=agency_a, user=user_b, role=Membership.Role.STUDENT
        )
        draft = _letter(agency_a, other, programme.program_id)
    client.force_login(user_a)
    with patch(ENQUEUE) as enqueue:
        response = client.post(
            f"/student/writing/letters/{draft.id}/approve/", HTTP_HOST=domain_a.host
        )
    assert response.status_code == 404
    enqueue.assert_not_called()
